#!/usr/bin/env python3
"""Wizard for Mac front door + first-run onboarding (WizardOS 0.2 stack).

Runs on the WizardOS VM host as the `wizard` user (docker group). Everything else is a Runtipi app installed by
os.sh: Hermes Agent (`hermes-agent`), the Wizard shell with the Agent Service and Wizard UX (`wizard-shell`), Files,
Transcriber, and so on. The Mac window always opens this server first:

* onboarding incomplete -> the onboarding page (name, brain, wake-up check, first chat)
* onboarding complete   -> redirect into the Wizard UX served by the wizard-shell app

Brains (applied inside the hermes-agent engine container with stock Hermes code, see hermes_brain.py):
* free   -> Hermes guest identity on the Nous free tier (zero login)
* chatgpt-> Hermes' own OpenAI Codex device-code login; the sign-in page opens in the Mac's browser
* apikey -> Anthropic or OpenRouter key saved to Hermes' .env

Private first (try-wizard#134, wizard-os DECISIONS #115, spec/AGENTS.md section 10), off by default: on when the Mac
asks for it (it always opens this page with `?private_first=1`), when env WIZARD_PRIVATE_FIRST=1,
or when the box's own `wizard/private-first-setup` switch is on (the Agent Service's GET /wizard/v1/private-first).
WIZARD_PRIVATE_FIRST=0 forces it off. With it on, the brain step leads with Tinfoil and this server runs none of the
brains above: Continue switches the box's `wizard/private-first-setup` on (the owner's Look file, the same switch the
Linux install uses) and hands over to the Wizard UX Welcome, whose Connect your AI signs in through the wizard-tinfoil
app; the Agent Service then makes the private agent the default. Claude or ChatGPT are added there or later as a
separate standard agent. An Agent Service without the private-first route keeps the brains above.
"""

from __future__ import annotations

import asyncio
import errno
import json
import os
import secrets
import socket
import stat
import re
import subprocess
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

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
SHELL_ORIGIN = os.environ.get("WIZARD_SHELL_ORIGIN", "http://127.0.0.1:8924")
# The Mac app reaches the shell through a vsock bridge on this loopback port.
PUBLIC_UX_ORIGIN = os.environ.get("WIZARD_PUBLIC_UX_ORIGIN", "http://127.0.0.1:48023")
UX_PATH = "/wizard-os-home/"
OPEN_URL_CMD = os.environ.get("WIZARD_OPEN_URL_CMD", "/opt/wizard/bin/wizard-open-url")
CODEX_DEVICE_URL = "https://auth.openai.com/codex/device"

_state_lock = threading.Lock()
_codex: dict[str, Any] = {"status": "idle"}
_codex_lock = threading.RLock()
_codex_lifecycle = asyncio.Lock()
_voice_retry_lock = asyncio.Lock()
_voice_retry_at = -float("inf")
VOICE_PATH = ROOT / "voice.json"

# The CLI's death does NOT stop `docker exec` inside the container. Keep the stock
# auth script intact, but fence its process with an attempt-scoped lock/kill handshake.
# A cancellation marker also covers cancel arriving before exec actually starts.
_CODEX_RUN = r'''
import fcntl, os, pathlib, sys
attempt = sys.argv[2]
base = pathlib.Path('/tmp/wizard-codex-' + attempt)
with open(str(base) + '.lock', 'w') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    if pathlib.Path(str(base) + '.cancel').exists():
        sys.exit(0)
    pathlib.Path(str(base) + '.pid').write_text(str(os.getpid()))
    if pathlib.Path(str(base) + '.cancel').exists():
        sys.exit(0)
    source = sys.argv[3]
    sys.argv = ['hermes_brain.py', 'codex', attempt]
    exec(compile(source, 'hermes_brain.py', 'exec'), {'__name__': '__main__'})
'''
_CODEX_CANCEL = r'''
import fcntl, os, pathlib, signal, sys, time
base = pathlib.Path('/tmp/wizard-codex-' + sys.argv[1])
pathlib.Path(str(base) + '.cancel').touch()
with open(str(base) + '.lock', 'a') as lock:
    deadline = time.monotonic() + 6
    while True:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            try:
                pid = int(pathlib.Path(str(base) + '.pid').read_text())
                # Never kill a reused PID belonging to something else.
                args = pathlib.Path('/proc/%s/cmdline' % pid).read_bytes().split(b'\0')
                if sys.argv[1].encode() in args:
                    os.kill(pid, signal.SIGKILL)
            except (FileNotFoundError, ProcessLookupError, ValueError):
                pass
            if time.monotonic() > deadline:
                raise RuntimeError('Previous ChatGPT attempt did not stop')
            time.sleep(.05)
'''


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


# wizard-os#133: with the browser boundary on (`wam browser-boundary on`), every owner call needs the box's shell
# token. The setup page is a program on the box (the owner there, wizard-os spec/OWNER_PROOF.md), so it reads the same
# file the App Manager's own owner-API clients read (wam/browser_boundary.py owner_headers). No file: no header.
SHELL_TOKEN_FILE = Path(os.environ.get("WIZARD_OS_HOME", str(Path.home() / ".wizard-os"))).expanduser() \
    / "browser-boundary" / "shell-token"


def shell_token_headers() -> dict[str, str]:
    try:
        got = SHELL_TOKEN_FILE.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return {}
    return {"X-Wizard-Shell-Token": got} if re.fullmatch(r"[0-9a-f]{64}", got) else {}


async def shell(method: str, path: str, body: Any = None, *, timeout: float = 60,
                headers: dict[str, str] | None = None) -> tuple[int, Any]:
    """The Agent Service API (what Wizard UX itself calls), on the VM's loopback."""
    all_headers = {"Content-Type": "application/json", "Host": urlsplit(PUBLIC_UX_ORIGIN).netloc,
                   **shell_token_headers(), **(headers or {})}
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


# ── private first (try-wizard#134) ─────────────────────────────────────────
PRIVATE_FIRST_SWITCH = "wizard/private-first-setup"
PRIVATE_FIRST_STATE = "/wizard/v1/private-first"
LOOK_FILE = "/wizard/v1/pages/wizard-look/look.json"
PRIVATE_FIRST_REFUSAL = ("Private first is on: connect Tinfoil first. Claude or ChatGPT can be added after that "
                         "as a separate second agent.")


def private_first_forced() -> bool | None:
    """Env WIZARD_PRIVATE_FIRST: '1' forces it on, '0' off, anything else follows the Mac and the box switch."""
    value = os.environ.get("WIZARD_PRIVATE_FIRST", "")
    return True if value == "1" else False if value == "0" else None


async def private_first() -> dict[str, Any]:
    """Whether this setup runs private first. Only an Agent Service that serves the private-first route can."""
    forced = private_first_forced()
    try:
        status, answer = await shell("GET", PRIVATE_FIRST_STATE, timeout=8)
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        status, answer = 0, None
    reply: dict[str, Any] = answer if isinstance(answer, dict) else {}
    supported = status == 200 and isinstance(reply.get("on"), bool)
    asked = load_state().get("privateFirst") is True
    on = supported and forced is not False and (forced is True or asked or reply.get("on") is True)
    agent = reply.get("private_agent") if supported else None
    return {"on": bool(on), "supported": supported, "privateAgent": agent if isinstance(agent, str) else None}


def _look_stamps(look: dict[str, Any]) -> list[float]:
    stamps: list[float] = []
    for group in ("tweaks", "defaults", "views"):
        for choice in (look.get(group) or {}).values() if isinstance(look.get(group), dict) else ():
            if isinstance(choice, dict) and isinstance(choice.get("at"), (int, float)):
                stamps.append(choice["at"])
    for key in ("skin", "desktopBackdrop"):
        if isinstance(look.get(key), dict) and isinstance(look[key].get("at"), (int, float)):
            stamps.append(look[key]["at"])
    return stamps


def look_with_private_first(text: str | None) -> dict[str, Any] | None:
    """The owner's Look file (wizard-ux core/look-sync.js) with the private-first switch on; None = already on.

    A new revision (`at` above every one seen) so every device's look sync keeps it. Never overwrites a file it can't
    read: that would drop the owner's skin and switches."""
    if text is None:
        look: dict[str, Any] = {"version": 1, "skin": None, "tweaks": {}}
    else:
        try:
            look = json.loads(text)
        except ValueError:
            look = None  # type: ignore[assignment]
        if not isinstance(look, dict) or look.get("version") != 1:
            raise RuntimeError("look file unreadable")
    tweaks = look.get("tweaks") if isinstance(look.get("tweaks"), dict) else {}
    if isinstance(tweaks.get(PRIVATE_FIRST_SWITCH), dict) and tweaks[PRIVATE_FIRST_SWITCH].get("on") is True:
        return None
    tweaks[PRIVATE_FIRST_SWITCH] = {"on": True, "at": int(max(_look_stamps(look), default=0)) + 1}
    look["tweaks"] = tweaks
    return look


async def switch_private_first_on() -> None:
    """Turn the box's `wizard/private-first-setup` switch on through the Agent Service Pages file API (as Wizard UX's
    look sync does), so the Agent Service and the Welcome both run private first. A stale save (409) is retried."""
    for _ in range(3):
        status, found = await shell("GET", LOOK_FILE, timeout=15)
        if status == 200 and isinstance(found, dict) and isinstance(found.get("text"), str):
            text, version = found["text"], found.get("version")
        elif status == 404:
            text, version = None, None
        else:
            raise RuntimeError(f"look file read failed ({status})")
        look = look_with_private_first(text)
        if look is None:
            return
        status, _ = await shell("PUT", LOOK_FILE, {"text": json.dumps(look, indent=1) + "\n", "version": version},
                                timeout=15)
        if status == 200:
            return
        if status != 409:
            raise RuntimeError(f"look file save failed ({status})")
    raise RuntimeError("look file kept changing")


PRIVATE_FIRST_SETTLE_S = 8.0   # the Agent Service caches the Look switch for 3 s (channels-switch ttlMs)


async def wait_until_private_first_reads_on(limit: float | None = None) -> bool:
    """After the switch is saved, wait until the Agent Service itself answers on:true before handing over. Its switch
    read is cached for a few seconds, and the Welcome reads it once at boot: handing over too early showed Claude
    first in Connect your AI (try-wizard#134 tester). Gives up after `limit` seconds; the hand-over still happens."""
    end = time.monotonic() + (PRIVATE_FIRST_SETTLE_S if limit is None else limit)
    while True:
        try:
            status, answer = await shell("GET", PRIVATE_FIRST_STATE, timeout=4)
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            status, answer = 0, None
        if status == 200 and isinstance(answer, dict) and answer.get("on") is True:
            return True
        if time.monotonic() >= end:
            return False
        await asyncio.sleep(0.5)


async def refuse_if_private_first() -> web.Response | None:
    """With private first on, this server runs no brain of its own (one implementation: the connection apps)."""
    if (await private_first())["on"]:
        return json_error(PRIVATE_FIRST_REFUSAL, 409)
    return None


# ── brain: ChatGPT (Codex device login, inside the Hermes container) ─────


def _codex_current(attempt: str) -> bool:
    return _codex.get("attempt") == attempt and _codex.get("status") not in ("idle", "cancelling")


def _codex_worker(attempt: str) -> None:
    proc = None
    try:
        container = engine()
        with _codex_lock:
            if not _codex_current(attempt):
                return
            proc = subprocess.Popen(["docker", "exec", "-i", "-u", "hermes", container,
                                     "/opt/hermes/.venv/bin/python", "-c", _CODEX_RUN, "codex", attempt, BRAIN_SCRIPT],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, text=True)
            _codex.update(proc=proc, container=container)
        for line in proc.stdout:  # type: ignore[union-attr]
            if not line.startswith("{"):
                continue
            msg = json.loads(line)
            with _codex_lock:
                if not _codex_current(attempt):
                    return
                if msg.get("error"):
                    raise RuntimeError("ChatGPT sign-in failed. Try again.")
                if msg.get("status") == "waiting":
                    _codex.update(status="waiting", userCode=msg["userCode"], url=CODEX_DEVICE_URL,
                                  openedOnMac=False)
                elif msg.get("status") == "signed-in":
                    save_state(brain=msg["brain"], verified=False)
                    _codex.update(status="signed-in", brain=msg["brain"])
        proc.wait()
        with _codex_lock:
            if _codex_current(attempt) and _codex.get("status") != "signed-in":
                raise RuntimeError("ChatGPT sign-in stopped. Try again.")
    except Exception:
        with _codex_lock:
            if _codex_current(attempt):
                _codex.update(status="error", error="ChatGPT sign-in failed. Try again.")
    finally:
        if proc:
            # Normal completion is reaped here; cancellation reaps after its remote
            # handshake. Never kill only docker exec and leave stock auth orphaned.
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
            if proc.stdout:
                proc.stdout.close()


async def _cancel_codex(attempt: str) -> None:
    """Caller owns lifecycle lock. Fail closed if remote termination isn't proven."""
    with _codex_lock:
        if _codex.get("attempt") != attempt or _codex.get("status") == "idle":
            return
        _codex["status"] = "cancelling"
        container, proc = _codex.get("container"), _codex.get("proc")
    if container:
        result = await asyncio.to_thread(docker, "exec", "-u", "hermes", container,
                                         "/opt/hermes/.venv/bin/python", "-c", _CODEX_CANCEL, attempt, timeout=10)
        if result.returncode != 0:
            raise RuntimeError("Could not stop the previous sign-in. Retry cancellation before starting again.")
    if proc:
        try:
            await asyncio.to_thread(proc.wait, timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()  # remote auth has already been proven stopped above
            await asyncio.to_thread(proc.wait, timeout=2)
    with _codex_lock:
        _codex.clear()
        _codex.update(status="idle", attempt=attempt)


def voice_status() -> dict[str, Any]:
    """Read only bounded public progress, never arbitrary producer fields/logs."""
    try:
        fd = os.open(VOICE_PATH, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("not a regular file")
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError("status too large")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("invalid status")
    except FileNotFoundError:
        return {"state": "preparing", "stage": "Waiting for local voice preparation", "downloaded": 0, "total": 0}
    except (OSError, ValueError):
        return {"state": "error", "stage": "Local voice status unavailable", "downloaded": 0, "total": 0}
    state = value.get("state")
    if state == "downloading":  # older image's producer
        state = "preparing"
    if state not in ("preparing", "ready", "retrying", "error"):
        state = "error"
    # Stage labels are allowlisted summaries: producer detail may contain signed
    # download URLs or exception text and must not cross the public boundary.
    detail = str(value.get("stage") or value.get("detail") or "").lower()[:1024]
    stage = {"preparing": "Preparing local voice", "ready": "Local voice ready",
             "retrying": "Local voice will retry", "error": "Local voice needs attention"}[state]
    if state == "preparing":
        for token, label in (("wheel", "Installing voice dependencies"), ("download", "Downloading voice model"),
                             ("loading", "Loading voice model"), ("install", "Installing local voice"),
                             ("starting", "Starting voice engine")):
            if token in detail:
                stage = label
                break
    def byte_count(key: str) -> int:
        n = value.get(key, 0)
        return n if type(n) is int and 0 <= n <= 2**53 else 0
    return {"state": state, "stage": stage, "downloaded": byte_count("downloaded"), "total": byte_count("total")}


async def get_voice_status(_: web.Request) -> web.Response:
    return web.json_response(await asyncio.to_thread(voice_status), headers={"Cache-Control": "no-store"})


async def post_voice_retry(_: web.Request) -> web.Response:
    global _voice_retry_at
    # A single command in flight plus a short admission window; systemd itself
    # coalesces starts while the unit is running. It remains the sole JSON writer.
    if _voice_retry_lock.locked() or time.monotonic() - _voice_retry_at < 5:
        return web.json_response({"accepted": True, "alreadyRequested": True}, status=202)
    async with _voice_retry_lock:
        _voice_retry_at = time.monotonic()
        try:
            result = await asyncio.to_thread(subprocess.run,
                ["sudo", "-n", "systemctl", "--no-block", "start", "wizard-voice"],
                capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                raise RuntimeError("start rejected")
        except (OSError, RuntimeError, subprocess.SubprocessError):
            _voice_retry_at = -float("inf")
            return json_error("Could not request local voice preparation. Try again.", 503)
    return web.json_response({"accepted": True}, status=202)


@web.middleware
async def same_origin_mutations(request: web.Request, handler):
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("Origin")
        if ((origin is not None and origin != f"{request.scheme}://{request.host}")
                or request.headers.get("Sec-Fetch-Site") == "cross-site"):
            return json_error("Cross-origin mutations are not allowed.", 403)
    return await handler(request)


@web.middleware
async def json_api_errors(request: web.Request, handler):
    """Never answer an /api/ call with aiohttp's plain-text 500: the page would show "Request failed (500)"."""
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception as error:
        if not request.path.startswith("/api/"):
            raise
        log_failure(f"{request.method} {request.path}")
        return json_error(storage_problem(error) or "Something went wrong on your Wizard. Try again.", 500)


# ── HTTP ───────────────────────────────────────────────────────────────────


def json_error(message: str, status: int = 400) -> web.Response:
    return web.json_response({"error": message}, status=status)


def log_failure(what: str) -> None:
    """The traceback goes to the journal (and the Mac's console.log); the page only gets a plain reason."""
    print(f"{what} failed:\n{traceback.format_exc()}", flush=True)


def storage_problem(error: BaseException) -> str | None:
    """A plain-words reason for a disk problem, or None when the error is something else."""
    if not isinstance(error, OSError):
        return None
    if error.errno in (errno.ENOSPC, errno.EDQUOT):
        return "Your Wizard's disk is full, so it could not save this. Free up space, then try again."
    if error.errno in (errno.EACCES, errno.EPERM, errno.EROFS):
        return ("Your Wizard is not allowed to save its setup on its disk (permission denied). "
                "Restart WizardOS and try again.")
    return "Your Wizard could not save this to its disk. Try again."


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
    return web.json_response({**public_state(), "privateFirst": await private_first()})


async def post_private_first(request: web.Request) -> web.Response:
    """The Mac asked for private first (`?private_first=1`, which every Mac sends). Only before setup ends,
    and never against WIZARD_PRIVATE_FIRST=0; whether it runs still needs an Agent Service with the route."""
    try:
        body = await request.json()
    except ValueError:
        body = None
    state = load_state()
    if isinstance(body, dict) and body.get("ask") is True and not state.get("done") and private_first_forced() is not False:
        save_state(privateFirst=True)
    return web.json_response({**public_state(), "privateFirst": await private_first()})


async def post_brain_private(_: web.Request) -> web.Response:
    """Private first's Continue: switch the box's private-first switch on, then hand over to the Wizard UX Welcome,
    whose Connect your AI signs in to Tinfoil in the wizard-tinfoil app (the Agent Service makes the private agent)."""
    pf = await private_first()
    if not pf["on"]:
        return json_error("Private first isn't available on this Wizard yet. Pick another brain.", 409)
    try:
        await switch_private_first_on()
    except Exception:
        log_failure("Switching private first on")
        return json_error("Your Wizard could not switch private first on. Try again.", 502)
    if not await wait_until_private_first_reads_on():
        print("setup: the Agent Service did not read private first on yet; handing over anyway", flush=True)
    state = load_state()
    name = state.get("name") or "Wizard"
    if state.get("soulPending"):
        try:
            await asyncio.to_thread(brain_exec, "soul", {"name": name})
            save_state(soulPending=False)
        except Exception:
            pass
    if state.get("shellSettingsPending"):
        try:
            await asyncio.to_thread(write_shell_settings, name)
            save_state(shellSettingsPending=False)
        except Exception:
            log_failure("Writing the shell settings for private first")
    # No first chat here: a deep link would keep the Welcome away, and the Welcome sends its own first message.
    save_state(privateFirst=True, brain={"kind": "private", "provider": "tinfoil", "label": "Tinfoil (private)"},
               verified=False, done=True, firstSessionId=None, firstSessionOpened=True, finishedAt=time.time())
    return web.json_response({"target": f"{PUBLIC_UX_ORIGIN}{UX_PATH}", **public_state(), "privateFirst": pf})


async def post_name(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return json_error("That name did not arrive. Tap Continue to try again.")
    name = " ".join(str(body.get("name", "")).split())[:40]
    if not name:
        return json_error("Give your Wizard a name.")
    try:
        save_state(name=name)
    except OSError as error:
        log_failure("Saving the name")
        status = 507 if error.errno in (errno.ENOSPC, errno.EDQUOT) else 500
        return json_error(storage_problem(error) or "Your Wizard could not save the name. Try again.", status)
    try:  # best effort like SOUL.md below: the name is saved, finish applies the shell settings again
        await asyncio.to_thread(write_shell_settings, name)
    except Exception:
        log_failure("Writing the shell settings")
        try:
            save_state(shellSettingsPending=True)
        except OSError:
            log_failure("Marking the shell settings pending")
    else:
        if load_state().get("shellSettingsPending"):
            try:
                save_state(shellSettingsPending=False)
            except OSError:
                log_failure("Clearing the shell settings mark")
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
    async with _codex_lifecycle:
        with _codex_lock:
            if _codex.get("status") != "idle":
                return json_error("Cancel ChatGPT sign-in before changing brains.", 409)
        return await _post_brain(request)


async def _post_brain(request: web.Request) -> web.Response:
    refused = await refuse_if_private_first()
    if refused:
        return refused
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


async def post_codex_start(request: web.Request) -> web.Response:
    attempt = (await request.json()).get("attempt")
    if not isinstance(attempt, str) or not re.fullmatch(r"[0-9a-f]{32}", attempt):
        return json_error("A valid sign-in attempt ID is required.")
    refused = await refuse_if_private_first()
    if refused:
        return refused
    async with _codex_lifecycle:
        with _codex_lock:
            if _codex.get("attempt") == attempt:
                if _codex.get("status") == "idle":
                    return json_error("This sign-in attempt was cancelled. Start a new attempt.", 409)
                return web.json_response({"status": _codex["status"], "attempt": attempt})
            if _codex.get("status") != "idle":
                return json_error("Cancel the previous sign-in before starting another.", 409)
            _codex.clear()
            _codex.update(status="starting", attempt=attempt)
            threading.Thread(target=_codex_worker, args=(attempt,), daemon=True).start()
        return web.json_response({"status": "starting", "attempt": attempt})


async def get_codex(request: web.Request) -> web.Response:
    attempt = request.query.get("attempt")
    async with _codex_lifecycle:
        with _codex_lock:
            if not attempt or _codex.get("attempt") != attempt:
                return json_error("This sign-in attempt is no longer current.", 409)
            status = _codex.get("status")
            needs_open = status == "waiting" and not _codex.get("openRequested")
            if needs_open:
                _codex["openRequested"] = True
            needs_restart = status == "signed-in" and not _codex.get("restarted")
        if needs_open:
            opened = await asyncio.to_thread(open_on_mac, CODEX_DEVICE_URL)
            with _codex_lock:
                _codex["openedOnMac"] = opened
        if needs_restart:
            try:
                await restart_hermes()
            except Exception:
                return json_error("Signed in, but the brain could not restart. Try polling again.", 503)
            with _codex_lock:
                _codex["restarted"] = True
        with _codex_lock:
            view = {k: _codex[k] for k in ("status", "attempt", "userCode", "url", "openedOnMac", "brain", "error") if k in _codex}
        return web.json_response(view, headers={"Cache-Control": "no-store"})


async def post_codex_open(request: web.Request) -> web.Response:
    attempt = (await request.json()).get("attempt")
    async with _codex_lifecycle:
        with _codex_lock:
            if not attempt or _codex.get("attempt") != attempt or _codex.get("status") != "waiting":
                return json_error("This sign-in attempt is no longer waiting.", 409)
        return web.json_response({"opened": await asyncio.to_thread(open_on_mac, CODEX_DEVICE_URL), "attempt": attempt})


async def post_codex_cancel(request: web.Request) -> web.Response:
    attempt = (await request.json()).get("attempt")
    async with _codex_lifecycle:
        with _codex_lock:
            if not attempt or _codex.get("attempt") != attempt:
                return json_error("This sign-in attempt is no longer current.", 409)
        try:
            await _cancel_codex(attempt)
        except Exception:
            return json_error("Could not stop the previous sign-in. Try again.", 503)
        return web.json_response({"status": "idle", "attempt": attempt})


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


# The owner's first message (shown in the Setup preview bubble too). The agent's `wizard-guide` system skill answers
# it: a short hello, three things to try, and the offer of one Wizard tip a day for five days (wizard_tips).
FIRST_TASK = (
    "Hi {name}! I'm new to Wizard. Say hello in a couple of sentences, show me three things I can try right now, "
    "and ask if I'd like a quick Wizard tip each day for the next five days."
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
    if state.get("shellSettingsPending"):
        try:
            await asyncio.to_thread(write_shell_settings, name)
            save_state(shellSettingsPending=False)
        except Exception:
            log_failure("Writing the shell settings at finish")
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


# ── Bring My Hermes into Wizard (an existing Hermes's own `hermes backup` zip) ──
# The Mac posts the zip here (127.0.0.1:48030, Mac loopback only). Browsers can't: the custom header forces a CORS
# preflight this server never answers, and cross-site mutations are refused above. The zip holds sign-ins, so it is
# streamed into a root-only folder, never the shared Files folder, and deleted when the import ends.
IMPORT_TOOL = "/opt/wizard/bin/wizard-import-hermes"
IMPORT_DIR = Path("/var/lib/wizard/agent-import-incoming")
IMPORT_MAX = 64 << 30
_import_lock = asyncio.Lock()


def _import_headers_ok(request: web.Request) -> bool:
    return request.headers.get("X-Wizard-Import") == "hermes-backup" and request.headers.get("Origin") is None


async def _run_importer(*args: str, timeout: float = 3600) -> tuple[int, dict]:
    proc = await asyncio.create_subprocess_exec("sudo", "-n", IMPORT_TOOL, *args, stdin=asyncio.subprocess.DEVNULL,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    line = (out.decode(errors="replace").strip().splitlines() or [""])[-1]
    try:
        return proc.returncode or 0, json.loads(line)
    except ValueError:
        return proc.returncode or 1, {"ok": False, "error": "importer_no_reply"}


async def post_agent_import(request: web.Request) -> web.Response:
    if not _import_headers_ok(request):
        return json_error("Send the backup with X-Wizard-Import: hermes-backup.", 403)
    size = request.content_length or 0
    if not 0 < size <= IMPORT_MAX:
        return json_error("Backup size missing or too large.", 413)
    if _import_lock.locked():
        return json_error("An import is already running.", 409)
    async with _import_lock:
        await asyncio.to_thread(subprocess.run, ["sudo", "-n", "install", "-d", "-o", "wizard", "-g", "wizard",
                                                 "-m", "0700", str(IMPORT_DIR)], check=True)
        dst = IMPORT_DIR / f"hermes-backup-{secrets.token_hex(6)}.zip"
        try:
            fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            got = 0
            with os.fdopen(fd, "wb") as fh:
                async for chunk in request.content.iter_chunked(1 << 20):
                    got += len(chunk)
                    if got > size:
                        return json_error("Backup larger than announced.", 400)
                    fh.write(chunk)
            if got != size:
                return json_error(f"Backup ended early ({got} of {size} bytes).", 400)
            code, result = await _run_importer("file", str(dst))
            return web.json_response(result, status=200 if result.get("ok") else 500)
        finally:
            dst.unlink(missing_ok=True)


async def post_agent_import_undo(request: web.Request) -> web.Response:
    if not _import_headers_ok(request):
        return json_error("Send X-Wizard-Import: hermes-backup.", 403)
    if _import_lock.locked():
        return json_error("An import is already running.", 409)
    async with _import_lock:
        code, result = await _run_importer("undo")
    return web.json_response(result, status=200 if result.get("ok") else 500)


async def get_agent_import(_: web.Request) -> web.Response:
    code, result = await _run_importer("status", timeout=30)
    last = (result or {}).get("last") or {}
    return web.json_response({"running": _import_lock.locked(),
                              "last": {k: last.get(k) for k in ("stamp", "complete", "undone", "disabled_messaging",
                                                                 "paused_jobs", "sessions_after")} if last else None})


# ── phone: "Use Wizard on your phone" ──────────────────────────────────────
# The Agent Service owns phone setup (wizard-agent-service docs/phone-setup.md: /wizard/v1/setup/phone*). The front
# door only relays it and opens the Tailscale links in the Mac's browser; it never touches Tailscale itself.
PHONE_STEPS = {"unavailable", "off", "signin", "https", "serving", "phone_seen"}
# Where to get the phone app. Empty until the apps are published (TestFlight / Play testing links can go here).
PHONE_APPS = {"ios": os.environ.get("WIZARD_IOS_APP_URL", ""), "android": os.environ.get("WIZARD_ANDROID_APP_URL", "")}


def _tailscale_link(url: Any) -> str | None:
    parts = urlsplit(url) if isinstance(url, str) else None
    if parts and parts.scheme == "https" and (parts.hostname == "tailscale.com" or (parts.hostname or "").endswith(".tailscale.com")):
        return url
    return None


def _phone_view(status: int, payload: Any) -> dict[str, Any]:
    if status != 200 or not isinstance(payload, dict) or payload.get("step") not in PHONE_STEPS:
        return {"step": "unavailable", "apps": {k: bool(v) for k, v in PHONE_APPS.items()}}
    view = {k: payload.get(k) for k in ("step", "device_name", "error")}
    view["signin"] = bool(payload.get("auth_url"))
    view["https"] = bool(payload.get("https_enable_url"))
    # Shown as a copyable fallback in case the browser doesn't open. Only Tailscale's own https pages.
    view["signin_url"] = _tailscale_link(payload.get("auth_url"))
    view["https_url"] = _tailscale_link(payload.get("https_enable_url"))
    # The name the Wizard joins the tailnet under (the guest's hostname until Tailscale reports one), so the
    # owner knows which device to approve: it is not the Mac's own Tailscale.
    view["this_device"] = str(payload.get("device_name") or socket.gethostname() or "wizard").split(".")[0][:64]
    view["phones"] = [{"name": str(p.get("name") or "phone")[:64], "os": str(p.get("os") or "")[:32],
                       "online": p.get("online") is True} for p in (payload.get("phones") or []) if isinstance(p, dict)][:8]
    url = payload.get("wizard_url") or ""
    parts = urlsplit(url) if isinstance(url, str) else None
    if parts and parts.scheme == "https" and parts.netloc:
        origin = f"https://{parts.netloc}"
        view["address"] = parts.netloc
        # What the Wizard phone apps (and the iPhone Camera) open: android/CONNECT.md, ios/README.md.
        view["connect_url"] = "wizard://connect?origin=" + quote(origin, safe="")
    view["apps"] = {k: bool(v) for k, v in PHONE_APPS.items()}
    return view


async def _phone_status() -> tuple[int, Any]:
    try:
        return await shell("GET", "/wizard/v1/setup/phone", timeout=20)
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return 503, None


async def get_phone(_: web.Request) -> web.Response:
    return web.json_response(_phone_view(*await _phone_status()))


async def post_phone_start(_: web.Request) -> web.Response:
    try:
        # A same-origin write as Wizard UX itself makes it (the Setup API refuses cross-origin writes).
        status, payload = await shell("POST", "/wizard/v1/setup/phone/start", {}, timeout=30,
                                      headers={"Origin": PUBLIC_UX_ORIGIN})
    except (aiohttp.ClientError, asyncio.TimeoutError):
        status, payload = 503, None
    return web.json_response(_phone_view(status, payload))


async def post_phone_open(request: web.Request) -> web.Response:
    """Open a link in the Mac's browser. Only links the Wizard itself reported, never one from the page."""
    try:
        kind = (await request.json()).get("kind")
    except ValueError:
        return json_error("Invalid request.")
    if kind in PHONE_APPS:
        url = PHONE_APPS[kind]
    elif kind in ("signin", "https"):
        status, payload = await _phone_status()
        url = payload.get("auth_url" if kind == "signin" else "https_enable_url") if status == 200 and isinstance(payload, dict) else None
    else:
        return json_error("Unknown link.")
    if not isinstance(url, str) or not url.startswith("https://"):
        return json_error("That link isn't available right now.", 409)
    opened = await asyncio.to_thread(open_on_mac, url)
    return web.json_response({"opened": opened})


def build_app() -> web.Application:
    app = web.Application(client_max_size=8 * 1024 * 1024, middlewares=[json_api_errors, same_origin_mutations])
    app.add_routes([
        web.get("/api/voice/status", get_voice_status),
        web.post("/api/voice/retry", post_voice_retry),
        web.get("/", index),
        web.get("/healthz", healthz),
        web.get("/api/state", get_state),
        web.post("/api/name", post_name),
        web.post("/api/portrait", post_portrait),
        web.get("/api/portrait", get_portrait),
        web.post("/api/private-first", post_private_first),
        web.post("/api/brain/private", post_brain_private),
        web.post("/api/brain", post_brain),
        web.post("/api/brain/chatgpt/start", post_codex_start),
        web.get("/api/brain/chatgpt", get_codex),
        web.post("/api/brain/chatgpt/open", post_codex_open),
        web.post("/api/brain/chatgpt/cancel", post_codex_cancel),
        web.post("/api/verify", post_verify),
        web.post("/api/finish", post_finish),
        web.get("/api/phone", get_phone),
        web.post("/api/phone/start", post_phone_start),
        web.post("/api/phone/open", post_phone_open),
        web.post("/api/agent-import", post_agent_import),
        web.post("/api/agent-import/undo", post_agent_import_undo),
        web.get("/api/agent-import", get_agent_import),
        web.static("/static", STATIC),
    ])
    # Import by file so source-loaded contract tests and the systemd entrypoint use
    # the same adjacent module, without depending on the caller's working directory.
    import importlib.util
    spec = importlib.util.spec_from_file_location("wizard_backup_frontdoor", Path(__file__).with_name("backup_frontdoor.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.install(app, module.BackupDoor(name_provider=lambda: load_state().get("name") or "Wizard"))
    return app


if __name__ == "__main__":
    web.run_app(build_app(), host=HOST, port=PORT, access_log=None)
