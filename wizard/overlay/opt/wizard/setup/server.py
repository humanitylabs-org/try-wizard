#!/usr/bin/env python3
"""Wizard Desktop front door + first-run onboarding.

Runs inside the guest as the `wizard` user, next to Hermes (8865) and the
Wizard UX server (8923). The kiosk browser always opens this server first:

* onboarding incomplete -> the onboarding app (name, brain, verify, first chat)
* onboarding complete   -> redirect straight into the Wizard UX

Brains:
* free   -> Hermes guest identity on the Nous free tier (zero login)
* chatgpt-> Hermes' own OpenAI Codex device-code login; the sign-in page opens
            in the *Mac's* browser through the Wizard Desktop bridge
* apikey -> Anthropic or OpenRouter key saved to Hermes' .env
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import aiohttp
from aiohttp import web

ROOT = Path(os.environ.get("WIZARD_ROOT", "/var/lib/wizard"))
STATE_PATH = ROOT / "setup.json"
PORTRAIT_PATH = ROOT / "portrait"
STATIC = Path(__file__).resolve().parent / "static"
HOST = os.environ.get("WIZARD_SETUP_HOST", "127.0.0.1")
PORT = int(os.environ.get("WIZARD_SETUP_PORT", "8930"))
UX_ORIGIN = os.environ.get("WIZARD_UX_ORIGIN", "http://127.0.0.1:8923")
HERMES_ORIGIN = os.environ.get("WIZARD_HERMES_ORIGIN", "http://127.0.0.1:8865")
HERMES_KEY = os.environ.get("WIZARD_HERMES_API_KEY") or os.environ.get("API_SERVER_KEY") or ""
RESTART_CMD = os.environ.get("WIZARD_HERMES_RESTART_CMD", "sudo -n systemctl restart wizard-hermes.service")
OPEN_URL_CMD = os.environ.get("WIZARD_OPEN_URL_CMD", "/opt/wizard/bin/wizard-open-url")
CODEX_DEVICE_URL = "https://auth.openai.com/codex/device"

API_KEY_PROVIDERS = {
    "anthropic": {"env": "ANTHROPIC_API_KEY", "base_url": "https://api.anthropic.com", "label": "Anthropic"},
    "openrouter": {"env": "OPENROUTER_API_KEY", "base_url": "https://openrouter.ai/api/v1", "label": "OpenRouter"},
}

_state_lock = threading.Lock()
_codex: dict[str, Any] = {"status": "idle"}


# ── state ──────────────────────────────────────────────────────────────────


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        return {}


def save_state(**changes: Any) -> dict[str, Any]:
    with _state_lock:
        state = load_state()
        state.update(changes)
        ROOT.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        os.chmod(tmp, 0o600)
        tmp.replace(STATE_PATH)
        return state


def public_state() -> dict[str, Any]:
    state = load_state()
    return {
        "name": state.get("name", ""),
        "hasPortrait": PORTRAIT_PATH.exists(),
        "brain": state.get("brain"),
        "verified": bool(state.get("verified")),
        "done": bool(state.get("done")),
        "firstSessionId": state.get("firstSessionId"),
        "uxOrigin": UX_ORIGIN,
    }


# ── Hermes plumbing ────────────────────────────────────────────────────────


def _read_raw_config() -> dict[str, Any]:
    from hermes_cli.auth import read_raw_config
    return read_raw_config() or {}


def _write_config(config: dict[str, Any]) -> None:
    from hermes_cli.auth import atomic_config_write, get_config_path
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_config_write(path, config)


# The Wizard owns this VM outright: it is the only user, it has passwordless
# sudo, and the Mac host is the security boundary. Hermes otherwise refuses
# privileged commands on API sessions because "no human is present to approve".
WIZARD_MACHINE_DEFAULTS: dict[str, Any] = {
    "approvals": {"mode": "off", "unattended_mode": "approve"},
    "terminal": {"cwd": os.environ.get("HOME") or "/home/wizard"},
}


def apply_machine_defaults(config: dict[str, Any]) -> dict[str, Any]:
    for section, values in WIZARD_MACHINE_DEFAULTS.items():
        current = config.get(section)
        merged = dict(current) if isinstance(current, dict) else {}
        merged.update(values)
        config[section] = merged
    return config


def set_model(provider: str, base_url: str, model: str) -> None:
    from hermes_cli.auth import _update_config_for_provider
    _update_config_for_provider(provider, base_url, default_model=model)
    config = _read_raw_config()
    model_cfg = dict(config.get("model") or {})
    model_cfg["default"] = model
    model_cfg["provider"] = provider
    config["model"] = model_cfg
    _write_config(apply_machine_defaults(config))


def write_soul(name: str) -> None:
    from hermes_constants import get_hermes_home
    soul = get_hermes_home() / "SOUL.md"
    soul.parent.mkdir(parents=True, exist_ok=True)
    soul.write_text(
        f"# {name}\n\n"
        f"You are {name}, a personal AI wizard living on your own Arch Linux computer "
        "inside the user's Mac. You have a real shell with passwordless sudo, so you can install "
        "packages with pacman, write and run code, and manage this machine yourself.\n\n"
        "Be warm, direct, and capable. Prefer doing over describing: when the user asks for "
        "something you can do on this machine, do it, then report what happened in plain words.\n"
    )


async def restart_hermes() -> None:
    if RESTART_CMD:
        proc = await asyncio.create_subprocess_shell(
            RESTART_CMD, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await proc.wait()
    await wait_hermes_ready(timeout=90)


async def wait_hermes_ready(timeout: float = 60) -> bool:
    deadline = time.monotonic() + timeout
    headers = {"Authorization": f"Bearer {HERMES_KEY}"}
    async with aiohttp.ClientSession() as session:
        while time.monotonic() < deadline:
            try:
                async with session.get(f"{HERMES_ORIGIN}/health", headers=headers,
                                       timeout=aiohttp.ClientTimeout(total=3)) as resp:
                    if resp.status == 200:
                        return True
            except (aiohttp.ClientError, asyncio.TimeoutError):
                pass
            await asyncio.sleep(1)
    return False


async def hermes(method: str, path: str, body: Any = None, *, timeout: float = 240,
                 headers: dict[str, str] | None = None) -> tuple[int, Any]:
    all_headers = {"Authorization": f"Bearer {HERMES_KEY}", "Content-Type": "application/json"}
    all_headers.update(headers or {})
    async with aiohttp.ClientSession() as session:
        async with session.request(method, f"{HERMES_ORIGIN}{path}", headers=all_headers,
                                   data=None if body is None else json.dumps(body),
                                   timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            text = await resp.text()
            try:
                return resp.status, json.loads(text)
            except ValueError:
                return resp.status, text


def open_on_mac(url: str) -> bool:
    try:
        return subprocess.run([OPEN_URL_CMD, url], timeout=8).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


# ── brain: free tier ──────────────────────────────────────────────────────


def connect_free() -> dict[str, Any]:
    from hermes_cli.anon_auth import GUEST_MODEL
    from hermes_cli.free_tier_bootstrap import run_bootstrap
    record = run_bootstrap(announce=False)
    if not getattr(record, "has_identity", False):
        raise RuntimeError(getattr(record, "error", "") or "The free tier is not available right now.")
    set_model("nous", "", GUEST_MODEL)
    return {"kind": "free", "provider": "nous", "model": GUEST_MODEL, "label": "Free starter brain"}


# ── brain: API key ─────────────────────────────────────────────────────────


def default_model(provider: str) -> str:
    from hermes_cli.models import _PROVIDER_MODELS
    if provider == "openrouter":
        options = _PROVIDER_MODELS.get("nous") or []
        return options[0] if options else "anthropic/claude-opus-5.5"
    options = _PROVIDER_MODELS.get(provider) or []
    if not options:
        raise RuntimeError(f"No default model is known for {provider}.")
    return options[0]


def connect_api_key(provider: str, key: str) -> dict[str, Any]:
    spec = API_KEY_PROVIDERS.get(provider)
    if not spec:
        raise RuntimeError("Choose Anthropic or OpenRouter.")
    key = key.strip()
    if len(key) < 20 or any(ch.isspace() for ch in key):
        raise RuntimeError("That key doesn't look right. Paste the whole key.")
    from hermes_cli.config import save_env_value
    save_env_value(spec["env"], key)
    os.environ[spec["env"]] = key
    model = default_model(provider)
    set_model(provider, spec["base_url"], model)
    return {"kind": "apikey", "provider": provider, "model": model, "label": f"{spec['label']} key"}


# ── brain: ChatGPT (Codex device login) ───────────────────────────────────


def _codex_worker(attempt: str) -> None:
    from hermes_cli.auth import _save_codex_tokens, _utc_now_z
    from hermes_cli.auth_codex import (_codex_base_url, _codex_exchange_authorization_code,
                                       _codex_poll_authorization_code, _codex_request_device_code)
    from hermes_cli.auth_constants import CODEX_OAUTH_CLIENT_ID
    issuer = "https://auth.openai.com"
    try:
        device = _codex_request_device_code(issuer, CODEX_OAUTH_CLIENT_ID)
        if _codex.get("attempt") != attempt:
            return
        _codex.update(status="waiting", userCode=device["user_code"], url=CODEX_DEVICE_URL,
                      openedOnMac=open_on_mac(CODEX_DEVICE_URL))
        code = _codex_poll_authorization_code(
            issuer, device_auth_id=device["device_auth_id"], user_code=device["user_code"],
            poll_interval=device["interval"])
        tokens = _codex_exchange_authorization_code(issuer, CODEX_OAUTH_CLIENT_ID, code)
        if _codex.get("attempt") != attempt:
            return
        _save_codex_tokens({"access_token": tokens.get("access_token", ""),
                            "refresh_token": tokens.get("refresh_token", "")}, _utc_now_z())
        model = default_model("openai-codex")
        set_model("openai-codex", _codex_base_url(), model)
        brain = {"kind": "chatgpt", "provider": "openai-codex", "model": model, "label": "ChatGPT account"}
        save_state(brain=brain, verified=False)
        _codex.update(status="signed-in", brain=brain)
    except Exception as error:  # surfaced to the onboarding page
        if _codex.get("attempt") == attempt:
            _codex.update(status="error", error=str(error) or error.__class__.__name__)


# ── HTTP ───────────────────────────────────────────────────────────────────


def json_error(message: str, status: int = 400) -> web.Response:
    return web.json_response({"error": message}, status=status)


async def index(request: web.Request) -> web.StreamResponse:
    state = load_state()
    if state.get("done") and request.query.get("setup") != "1":
        session_id = state.get("firstSessionId")
        target = f"{UX_ORIGIN}/wizard"
        if session_id and not state.get("firstSessionOpened"):
            save_state(firstSessionOpened=True)
            target += f"?session={session_id}"
        raise web.HTTPFound(target)
    return web.FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


async def healthz(_: web.Request) -> web.Response:
    return web.Response(text="ok", headers={"Access-Control-Allow-Origin": "*"})


async def get_state(_: web.Request) -> web.Response:
    return web.json_response(public_state())


async def post_name(request: web.Request) -> web.Response:
    body = await request.json()
    name = " ".join(str(body.get("name", "")).split())[:40]
    if not name:
        return json_error("Give your Wizard a name.")
    save_state(name=name)
    await asyncio.to_thread(write_soul, name)
    return web.json_response(public_state())


async def post_portrait(request: web.Request) -> web.Response:
    data = await request.read()
    if not data:
        PORTRAIT_PATH.unlink(missing_ok=True)
        return web.json_response(public_state())
    if len(data) > 6 * 1024 * 1024:
        return json_error("Pick an image under 6 MB.")
    if not (data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n" or data[8:12] == b"WEBP"
            or data[:6] in (b"GIF87a", b"GIF89a")):
        return json_error("Use a PNG, JPEG, WebP, or GIF image.")
    PORTRAIT_PATH.write_bytes(data)
    return web.json_response(public_state())


async def get_portrait(_: web.Request) -> web.StreamResponse:
    if not PORTRAIT_PATH.exists():
        raise web.HTTPNotFound()
    return web.FileResponse(PORTRAIT_PATH, headers={"Cache-Control": "no-store"})


async def post_brain(request: web.Request) -> web.Response:
    body = await request.json()
    kind = body.get("kind")
    try:
        if kind == "free":
            brain = await asyncio.to_thread(connect_free)
        elif kind == "apikey":
            brain = await asyncio.to_thread(connect_api_key, str(body.get("provider", "")), str(body.get("key", "")))
        else:
            return json_error("Unknown brain.")
    except Exception as error:
        return json_error(str(error) or "Could not connect that brain.")
    save_state(brain=brain, verified=False)
    await restart_hermes()
    return web.json_response(public_state())


async def post_codex_start(_: web.Request) -> web.Response:
    attempt = uuid.uuid4().hex
    _codex.clear()
    _codex.update(status="starting", attempt=attempt)
    threading.Thread(target=_codex_worker, args=(attempt,), daemon=True).start()
    return web.json_response({"status": "starting"})


async def get_codex(_: web.Request) -> web.Response:
    view = {k: v for k, v in _codex.items() if k != "attempt"}
    if _codex.get("status") == "signed-in" and not _codex.get("restarted"):
        _codex["restarted"] = True
        await restart_hermes()
        view["status"] = "signed-in"
    return web.json_response(view)


async def post_codex_open(_: web.Request) -> web.Response:
    return web.json_response({"opened": await asyncio.to_thread(open_on_mac, CODEX_DEVICE_URL)})


async def post_codex_cancel(_: web.Request) -> web.Response:
    _codex.clear()
    _codex.update(status="idle")
    return web.json_response({"status": "idle"})


def _session_id(payload: Any) -> str | None:
    if isinstance(payload, dict):
        inner = payload.get("session")
        if isinstance(inner, dict) and inner.get("id"):
            return str(inner["id"])
        if payload.get("id"):
            return str(payload["id"])
    return None


def _reply_text(payload: Any) -> str:
    if isinstance(payload, dict):
        message = payload.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content
    return ""


async def post_verify(_: web.Request) -> web.Response:
    state = load_state()
    name = state.get("name") or "Wizard"
    if not await wait_hermes_ready(timeout=60):
        return json_error("Your Wizard's mind is still starting. Try again in a moment.", 503)
    status, session = await hermes("POST", "/api/sessions", {"source": "wizard-setup", "title": f"Wake-up check {secrets.token_hex(3)}"}, timeout=30)
    session_id = _session_id(session)
    if status >= 300 or not session_id:
        return json_error(f"Hermes could not open a session ({status}).", 502)
    prompt = (f"Your name is {name}. This is your first moment awake. In one short, warm sentence, "
              "introduce yourself by name. No preamble.")
    status, reply = await hermes("POST", f"/api/sessions/{session_id}/chat", {"message": prompt}, timeout=180)
    text = _reply_text(reply).strip()
    if status >= 300 or not text:
        detail = reply.get("error") if isinstance(reply, dict) else str(reply)[:300]
        return json_error(f"The brain didn't answer: {detail or status}", 502)
    await hermes("DELETE", f"/api/sessions/{session_id}", timeout=15)
    save_state(verified=True, verifyReply=text)
    return web.json_response({"reply": text, **public_state()})


FIRST_TASK = (
    "Hi {name}! Show me what you can do on your own computer: install the `figlet` package with "
    "pacman (use sudo), use it to print your name as a big banner (show it in a code block), then "
    "tell me in two friendly sentences what kind of machine you live on."
)


async def post_finish(_: web.Request) -> web.Response:
    state = load_state()
    name = state.get("name") or "Wizard"
    status, session = await hermes("POST", "/api/sessions", {
        "id": f"wizard_{int(time.time() * 1000)}_{secrets.token_hex(6)}",
        "source": "wizard-mobile", "title": f"Meet {name}" if not state.get("firstSessionId") else f"Meet {name} ({secrets.token_hex(2)})"}, timeout=30)
    session_id = _session_id(session)
    if status >= 300 or not session_id:
        return json_error(f"Could not open your first chat ({status}).", 502)
    status, run = await hermes("POST", "/v1/runs", {
        "session_id": session_id, "input": FIRST_TASK.format(name=name)},
        headers={"Idempotency-Key": uuid.uuid4().hex}, timeout=30)
    if status >= 300:
        return json_error(f"Your Wizard could not start its first task ({status}).", 502)
    save_state(done=True, firstSessionId=session_id, firstSessionOpened=True, finishedAt=time.time())
    return web.json_response({"target": f"{UX_ORIGIN}/wizard?session={session_id}", **public_state()})


# ── developer diagnostics (only when the Mac owner enabled SSH forwarding) ──


def dev_mode() -> bool:
    try:
        return "tryomarchy.ssh_access=1" in Path("/proc/cmdline").read_text().split()
    except OSError:
        return False


async def post_dev_exec(request: web.Request) -> web.Response:
    if not dev_mode():
        raise web.HTTPNotFound()
    body = await request.json()
    cmd = str(body.get("cmd") or "")
    if not cmd:
        return json_error("cmd required")
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=float(body.get("timeout") or 60))
    except asyncio.TimeoutError:
        proc.kill()
        return web.json_response({"rc": -1, "out": "timeout"})
    return web.json_response({"rc": proc.returncode, "out": out.decode("utf-8", "replace")[-60000:]})


def build_app() -> web.Application:
    app = web.Application(client_max_size=8 * 1024 * 1024)
    app.add_routes([
        web.get("/", index),
        web.get("/healthz", healthz),
        web.get("/api/state", get_state),
        web.post("/api/name", post_name),
        web.post("/api/portrait", post_portrait),
        web.get("/api/portrait", get_portrait),
        web.post("/api/brain", post_brain),
        web.post("/api/brain/chatgpt/start", post_codex_start),
        web.get("/api/brain/chatgpt", get_codex),
        web.post("/api/brain/chatgpt/open", post_codex_open),
        web.post("/api/brain/chatgpt/cancel", post_codex_cancel),
        web.post("/api/verify", post_verify),
        web.post("/api/finish", post_finish),
        web.post("/api/dev/exec", post_dev_exec),
        web.static("/static", STATIC),
    ])
    return app


if __name__ == "__main__":
    web.run_app(build_app(), host=HOST, port=PORT, access_log=None)
