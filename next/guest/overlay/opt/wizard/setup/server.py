#!/usr/bin/env python3
"""Wizard for Mac front door + first-run onboarding (Wizard OS 0.2 stack).

Runs on the Wizard OS VM host as the `wizard` user (docker group). Everything else is a Runtipi app installed by
os.sh: Hermes Agent (`hermes-agent`), the Wizard shell with the Agent Service and Wizard UX (`wizard-shell`), Files,
Transcriber, and so on. The Mac window always opens this server first:

* onboarding incomplete -> the onboarding page (name, brain, wake-up check, first chat)
* onboarding complete   -> redirect into the Wizard UX served by the wizard-shell app

Brains (applied inside the hermes-agent engine container with stock Hermes code, see hermes_brain.py):
* free   -> Hermes guest identity on the Nous free tier (zero login)
* chatgpt-> Hermes' own OpenAI Codex device-code login; the sign-in page opens in the Mac's browser
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
BRAIN_SCRIPT = (Path(__file__).resolve().parent / "hermes_brain.py").read_text()
HOST = os.environ.get("WIZARD_SETUP_HOST", "127.0.0.1")
PORT = int(os.environ.get("WIZARD_SETUP_PORT", "8930"))
RUNTIPI = Path(os.environ.get("RUNTIPI_ROOT", "/home/wizard/runtipi"))
# The wizard-shell app (Agent Service + Wizard UX) on the VM's loopback.
SHELL_ORIGIN = os.environ.get("WIZARD_SHELL_ORIGIN", "http://127.0.0.1:8796")
# The Mac app reaches the shell through a vsock bridge on this loopback port.
PUBLIC_UX_ORIGIN = os.environ.get("WIZARD_PUBLIC_UX_ORIGIN", "http://127.0.0.1:47823")
UX_PATH = "/wizard-ux/"
OPEN_URL_CMD = os.environ.get("WIZARD_OPEN_URL_CMD", "/opt/wizard/bin/wizard-open-url")
CODEX_DEVICE_URL = "https://auth.openai.com/codex/device"

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
        "uxOrigin": PUBLIC_UX_ORIGIN,
    }


# ── the installed apps ─────────────────────────────────────────────────────


def app_dir(app_id: str) -> Path | None:
    for d in sorted(RUNTIPI.glob(f"app-data/*/{app_id}")):
        return d
    return None


def app_env(app_id: str) -> dict[str, str]:
    d = app_dir(app_id)
    out: dict[str, str] = {}
    try:
        for line in (d / "app.env").read_text().splitlines() if d else []:
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip("'\"")
    except OSError:
        pass
    return out


def docker(*args: str, stdin: str | None = None, timeout: float = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], input=stdin, capture_output=True, text=True, timeout=timeout)


def engine() -> str:
    """The container running Hermes itself (the hermes-agent app's engine service)."""
    r = docker("ps", "--filter", "label=com.docker.compose.service=hermes-agent-engine", "--format", "{{.Names}}")
    name = r.stdout.strip().splitlines()[0] if r.stdout.strip() else ""
    if not name:
        raise RuntimeError("Hermes Agent isn't running yet. Give it a moment and try again.")
    return name


def hermes_origin() -> str:
    r = docker("inspect", engine(), "--format", "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}")
    ips = r.stdout.split()
    if not ips:
        raise RuntimeError("Hermes Agent has no network address yet.")
    return f"http://{ips[0]}:8642"


def hermes_key() -> str:
    return app_env("hermes-agent").get("HERMES_API_KEY", "")


def brain_exec(command: str, payload: dict | None = None, timeout: float = 120) -> dict[str, Any]:
    """Run hermes_brain.py inside the Hermes container; return its last JSON line."""
    r = docker("exec", "-i", "-u", "hermes", engine(), "/opt/hermes/.venv/bin/python", "-c", BRAIN_SCRIPT, command,
               stdin=json.dumps(payload or {}), timeout=timeout)
    lines = [l for l in r.stdout.splitlines() if l.startswith("{")]
    result = json.loads(lines[-1]) if lines else {"error": (r.stderr or r.stdout)[-400:] or f"exit {r.returncode}"}
    if result.get("error"):
        raise RuntimeError(result["error"])
    return result


def open_on_mac(url: str) -> bool:
    try:
        return subprocess.run([OPEN_URL_CMD, url], timeout=8).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def write_shell_settings(name: str) -> None:
    """The Agent Service's settings.json (agent name), read by Wizard UX through /wizard/v1/bootstrap."""
    d = app_dir("wizard-shell")
    if not d:
        return
    path = d / "data" / "wizard-os" / "settings.json"
    try:
        settings = json.loads(path.read_text())
    except (OSError, ValueError):
        settings = {"schema": 1}
    settings.setdefault("agent", {})["name"] = name
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings, indent=1) + "\n")
    tmp.replace(path)


async def restart_hermes() -> None:
    await asyncio.to_thread(docker, "restart", "-t", "20", engine(), timeout=120)
    await wait_hermes_ready(timeout=120)


async def wait_hermes_ready(timeout: float = 60) -> bool:
    deadline = time.monotonic() + timeout
    async with aiohttp.ClientSession() as session:
        while time.monotonic() < deadline:
            try:
                origin = await asyncio.to_thread(hermes_origin)
                async with session.get(f"{origin}/health", headers={"Authorization": f"Bearer {hermes_key()}"},
                                       timeout=aiohttp.ClientTimeout(total=3)) as resp:
                    if resp.status == 200:
                        return True
            except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError, subprocess.SubprocessError):
                pass
            await asyncio.sleep(1)
    return False


async def hermes(method: str, path: str, body: Any = None, *, timeout: float = 240,
                 headers: dict[str, str] | None = None) -> tuple[int, Any]:
    all_headers = {"Authorization": f"Bearer {hermes_key()}", "Content-Type": "application/json"}
    all_headers.update(headers or {})
    origin = await asyncio.to_thread(hermes_origin)
    return await _request(method, f"{origin}{path}", body, all_headers, timeout)


async def shell(method: str, path: str, body: Any = None, *, timeout: float = 60,
                headers: dict[str, str] | None = None) -> tuple[int, Any]:
    """The Agent Service API (what Wizard UX itself calls), on the VM's loopback."""
    all_headers = {"Content-Type": "application/json", **(headers or {})}
    return await _request(method, f"{SHELL_ORIGIN}{path}", body, all_headers, timeout)


async def _request(method: str, url: str, body: Any, headers: dict[str, str], timeout: float) -> tuple[int, Any]:
    async with aiohttp.ClientSession() as session:
        async with session.request(method, url, headers=headers, data=None if body is None else json.dumps(body),
                                   timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            text = await resp.text()
            try:
                return resp.status, json.loads(text)
            except ValueError:
                return resp.status, text


# ── brain: ChatGPT (Codex device login, inside the Hermes container) ─────


def _codex_worker(attempt: str) -> None:
    try:
        proc = subprocess.Popen(["docker", "exec", "-i", "-u", "hermes", engine(), "/opt/hermes/.venv/bin/python",
                                 "-c", BRAIN_SCRIPT, "codex"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        _codex["proc"] = proc
        for line in proc.stdout:  # type: ignore[union-attr]
            if _codex.get("attempt") != attempt:
                proc.kill(); return
            if not line.startswith("{"):
                continue
            msg = json.loads(line)
            if msg.get("error"):
                raise RuntimeError(msg["error"])
            if msg.get("status") == "waiting":
                _codex.update(status="waiting", userCode=msg["userCode"], url=CODEX_DEVICE_URL,
                              openedOnMac=open_on_mac(CODEX_DEVICE_URL))
            elif msg.get("status") == "signed-in":
                save_state(brain=msg["brain"], verified=False)
                _codex.update(status="signed-in", brain=msg["brain"])
        proc.wait()
        if _codex.get("status") != "signed-in" and _codex.get("attempt") == attempt:
            raise RuntimeError((proc.stderr.read() if proc.stderr else "")[-300:] or "ChatGPT sign-in stopped.")
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
        target = f"{PUBLIC_UX_ORIGIN}{UX_PATH}"
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
    await asyncio.to_thread(write_shell_settings, name)
    try:
        await asyncio.to_thread(brain_exec, "soul", {"name": name})
    except Exception as error:  # Hermes still starting: the name is saved; SOUL.md is written again at finish
        save_state(soulPending=True)
        print(f"SOUL.md not written yet: {error}", flush=True)
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
            # Right after boot the network can take a few seconds; retry briefly before failing.
            for attempt in range(6):
                try:
                    brain = await asyncio.to_thread(brain_exec, "free")
                    break
                except Exception:
                    if attempt == 5:
                        raise
                    await asyncio.sleep(2.5)
        elif kind == "apikey":
            brain = await asyncio.to_thread(brain_exec, "apikey",
                                            {"provider": str(body.get("provider", "")), "key": str(body.get("key", ""))})
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
    view = {k: v for k, v in _codex.items() if k not in ("attempt", "proc")}
    if _codex.get("status") == "signed-in" and not _codex.get("restarted"):
        _codex["restarted"] = True
        await restart_hermes()
        view["status"] = "signed-in"
    return web.json_response(view)


async def post_codex_open(_: web.Request) -> web.Response:
    return web.json_response({"opened": await asyncio.to_thread(open_on_mac, CODEX_DEVICE_URL)})


async def post_codex_cancel(_: web.Request) -> web.Response:
    proc = _codex.get("proc")
    if proc:
        proc.kill()
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
    "Hi {name}! Tell me in a few friendly sentences who you are and which apps you can use on this computer "
    "(check your tools), then where my files live."
)


async def post_finish(_: web.Request) -> web.Response:
    """Open the first chat the way Wizard UX does (through the Agent Service) and start its first run."""
    state = load_state()
    name = state.get("name") or "Wizard"
    if state.get("soulPending"):
        try:
            await asyncio.to_thread(brain_exec, "soul", {"name": name})
            save_state(soulPending=False)
        except Exception:
            pass
    # Same shape as a new chat from Wizard UX (live.js/outbox.js): a `wizard_` id and source wizard-mobile, so the
    # Agent Service lists it in Chats.
    session_id = f"wizard_{int(time.time() * 1000)}_{uuid.uuid4().hex[:12]}"
    status, session = await shell("POST", "/wizard/hermes/api/sessions", {"source": "wizard-mobile", "id": session_id})
    if status >= 300:
        return json_error(f"Could not open your first chat ({status}).", 502)
    await shell("PATCH", f"/wizard/hermes/api/sessions/{session_id}", {"title": f"Meet {name}"})
    status, run = await shell("POST", "/wizard/hermes/v1/runs", {
        "session_id": session_id, "input": FIRST_TASK.format(name=name)},
        headers={"Idempotency-Key": uuid.uuid4().hex})
    if status >= 300:
        return json_error(f"Your Wizard could not start its first task ({status}).", 502)
    save_state(done=True, firstSessionId=session_id, firstSessionOpened=True, finishedAt=time.time())
    return web.json_response({"target": f"{PUBLIC_UX_ORIGIN}{UX_PATH}?session={session_id}", **public_state()})


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
        web.static("/static", STATIC),
    ])
    return app


if __name__ == "__main__":
    web.run_app(build_app(), host=HOST, port=PORT, access_log=None)
