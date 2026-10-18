"""Native-only transport for `wam backup`; the engine owns the restore transaction.

No archive or key is staged in Runtipi media (a host mount on a Mac). No engine stderr,
request body, key, or raw engine error reaches a log or a job receipt. All routes,
including reads/downloads, require the native header and refuse *any* Origin.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import time

from aiohttp import web

HEADER = "X-Wizard-Backup"
HEADER_VALUE = "wizardbackup-v1"
MAX_BYTES = 64 << 30
TTL = 3600
PHASES = {
    "export": "Creating encrypted backup", "verify": "Checking every file and planning restore",
    "import": "Restoring; messaging and scheduled jobs will stay paused",
    "undo": "Putting the previous Wizard back", "activate": "Switching this Wizard on",
}
ERRORS = {
    "export": "Backup could not finish. Check free space and that Wizard's apps are running.",
    "verify": "Backup could not be verified. Check the key or passphrase and that the file is complete.",
    "import": "Restore did not finish. Your previous state is kept by Wizard; use Undo Last Restore before retrying.",
    "undo": "Undo did not finish. Keep this Wizard paused and check its restore status before retrying.",
    "activate": "Switch-over did not finish. Check the restore status; do not start the old machine.",
}


def reply(obj, status=200):
    return web.json_response(obj, status=status, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


def refuse(message, status=400):
    return reply({"ok": False, "error": message}, status)


def private_write(path: Path, value: str):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(value)


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def public_result(op, raw):
    """Project only the contract's owner-safe fields; never return raw error/manifest/config."""
    result: dict = {"ok": True}
    for key in ("bytes", "entries", "content_bytes", "seconds", "stamp", "digest_match"):
        if key in raw:
            result[key] = raw[key]
    manifest = raw.get("manifest", raw)
    for kind in ("agents", "apps"):
        result[kind] = [str(x.get("id", "")) if isinstance(x, dict) else str(x)
                        for x in manifest.get(kind, [])][:1000]
    files = manifest.get("files") or {}
    result["files"] = {k: files.get(k, 0) for k in ("count", "bytes")}
    plan = raw.get("plan") or {}
    result["plan"] = {k: plan.get(k, []) for k in ("install", "replace", "leave", "agents")}
    # Warn about omitted entries without echoing filenames or stderr (which may be confidential).
    result["warnings_count"] = len(plan.get("warnings") or []) + len(raw.get("skipped_links") or []) + int(raw.get("skipped_in_apps_count") or 0) + len(raw.get("changed_while_reading") or [])
    return result


class BackupDoor:
    def __init__(self, root=None, command=None, name_provider=None):
        self.name_provider = name_provider or (lambda: "Wizard")
        self.root = Path(root or "/var/lib/wizard/backup-transfer")
        self.command = command or [str(Path.home() / ".local/bin/wam"), "backup"]
        self.lock = asyncio.Lock()
        self.jobs = {}
        self.tasks = set()
        self.processes = set()

    async def startup(self, app):
        if self.root.is_symlink():
            raise ValueError("Backup staging must not be a symlink")
        for p in self.root.iterdir() if self.root.exists() else []:
            if p.is_dir() and re.fullmatch(r"[a-f0-9]{32}", p.name):
                # No keys survive service restart, even if the previous process was killed.
                with contextlib.suppress(OSError, ValueError, TypeError):
                    j = json.loads((p / "receipt.json").read_text())
                    j.update(state="interrupted", phase="Wizard restarted. Check restore status before retrying.")
                    j.pop("result", None)
                    self.jobs[p.name] = j
                shutil.rmtree(p)
        self.sweeper = asyncio.create_task(self.sweep())

    async def cleanup(self, app):
        self.sweeper.cancel()
        await asyncio.gather(self.sweeper, return_exceptions=True)
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    async def sweep(self):
        while True:
            await asyncio.sleep(60)
            now = time.time()
            for ident, j in list(self.jobs.items()):
                if j["state"] not in ("running", "uploading", "downloading") and now - j["updated"] > TTL:
                    shutil.rmtree(self.root / ident, ignore_errors=True)
                    del self.jobs[ident]

    def save(self, job):
        job["updated"] = time.time()
        folder = self.root / job["id"]
        if folder.exists():
            tmp = folder / "receipt.tmp"
            tmp.unlink(missing_ok=True)
            private_write(tmp, json.dumps(job))
            tmp.replace(folder / "receipt.json")

    def ensure_root(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.is_symlink():
            raise ValueError("Backup staging must not be a symlink")
        self.root.chmod(0o700)

    def new_job(self, op, state="running"):
        self.ensure_root()
        if len(self.jobs) >= 128:
            raise web.HTTPTooManyRequests(text="Too many backup jobs; try again later")
        ident = secrets.token_hex(16)
        (self.root / ident).mkdir(mode=0o700)
        job = {"id": ident, "operation": op, "state": state, "phase": PHASES.get(op, "Receiving backup"),
               "created": time.time(), "updated": time.time()}
        self.jobs[ident] = job
        self.save(job)
        return job

    async def run(self, args, secret=None, job=None, timeout=7200):
        key = None
        try:
            if secret is not None:
                folder = self.root / job["id"] if job else self.root
                key = folder / ("key-" + secrets.token_hex(16))
                private_write(key, secret)
                args = [*args, "--key-file", str(key)]
            env = dict(os.environ)
            # Only explicit body input or the engine's stored key; never inherited test credentials.
            env.pop("WIZARD_BACKUP_KEY", None)
            env.pop("WIZARD_BACKUP_PASSPHRASE", None)
            proc = await asyncio.create_subprocess_exec(*self.command, *args, "--json", env=env,
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL)
            self.processes.add(proc)
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), timeout)
                raw = json.loads(out)
                if proc.returncode or not isinstance(raw, dict) or not raw.get("ok", True):
                    raise ValueError("Engine refused")
                return raw
            finally:
                if proc.returncode is None:
                    proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), 5)
                    except asyncio.TimeoutError:
                        proc.kill()
                        await proc.wait()
                self.processes.discard(proc)
        finally:
            if key:
                key.unlink(missing_ok=True)

    async def body(self, request):
        # Do not permit a key in the query string, even if an old client tries it.
        if request.query_string:
            raise ValueError("Query parameters are not supported")
        if request.content_length is None or request.content_length > 16384:
            raise ValueError("A small JSON body is required")
        b = await request.read()
        if len(b) > 16384:
            raise ValueError("Body too large")
        d = json.loads(b)
        if not isinstance(d, dict):
            raise ValueError("JSON object required")
        secret = d.get("secret")
        if secret is not None and (not isinstance(secret, str) or not secret.strip() or len(secret) > 4096 or "\n" in secret or "\r" in secret):
            raise ValueError("Enter a recovery key or passphrase")
        return d

    async def capability(self, request):
        # Also proves the installed engine supports backup; no endpoint advertises a false capability.
        try:
            raw = await self.run(["key", "show-id"], timeout=15)
            return reply({"ok": True, "version": 1, "stored_key": bool(raw.get("stored")), "key_id": raw.get("key_id"),
                          "busy": self.lock.locked(), "name": str(self.name_provider())[:80]})
        except (OSError, ValueError, asyncio.TimeoutError):
            return reply({"ok": False, "version": 0, "error": "Needs Wizard OS update"}, 503)

    async def status(self, request):
        ident = request.match_info.get("job")
        if ident:
            j = self.jobs.get(ident)
            return reply(j) if j else refuse("Backup job not found or expired", 404)
        try:
            raw = await self.run(["status"], timeout=20)
            return reply({"ok": True, "busy": self.lock.locked(), "last_restore": raw.get("last_restore"),
                          "jobs": list(self.jobs.values())})
        except (OSError, ValueError, asyncio.TimeoutError):
            return refuse("Backup status is unavailable", 503)

    async def key_new(self, request):
        await self.body(request)
        if self.lock.locked():
            return refuse("A backup operation is already running", 409)
        async with self.lock:
            try:
                raw = await self.run(["key", "new"], timeout=20)
                # Never save this response in jobs/receipts. Engine refuses a second new without --force.
                return reply({"ok": True, "recovery_key": raw["recovery_key"], "key_id": raw["key_id"], "shown_once": True})
            except (OSError, ValueError, KeyError, asyncio.TimeoutError):
                return refuse("A recovery key already exists, or Wizard could not create one. Use your saved key or a passphrase.", 409)

    async def upload(self, request):
        size = request.content_length
        if not size or size > MAX_BYTES or request.headers.get("Content-Encoding"):
            return refuse("Backup size is missing, too large, or encoded", 413)
        if self.lock.locked():
            return refuse("A backup operation is already running", 409)
        async with self.lock:
            self.ensure_root()
            if shutil.disk_usage(self.root).free < size + (256 << 20):
                return refuse("Not enough space in Wizard for this backup", 507)
            j = self.new_job("upload", "uploading")
            path = self.root / j["id"] / "bundle.wizardbackup"
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                got = 0
                with os.fdopen(fd, "wb") as f:
                    async with asyncio.timeout(3600):
                        async for chunk in request.content.iter_chunked(1 << 20):
                            got += len(chunk)
                            if got > size:
                                raise ValueError("Wrong size")
                            await asyncio.to_thread(f.write, chunk)
                            j.update(received_bytes=got, total_bytes=size)
                if got != size:
                    raise ValueError("Incomplete upload")
                j.update(state="uploaded", phase="Ready to verify", sha256=await asyncio.to_thread(digest, path))
                self.save(j)
                return reply(j, 201)
            except BaseException:
                path.unlink(missing_ok=True)
                j.update(state="failed", phase="Upload did not finish; select the file again")
                self.save(j)
                raise

    async def start(self, request):
        op = request.match_info["operation"]
        if op not in PHASES:
            return refuse("Unknown backup operation", 404)
        data = await self.body(request)
        if self.lock.locked():
            return refuse("A backup operation is already running", 409)
        if op == "activate" and data.get("old_is_off") is not True:
            return refuse("Confirm that the old machine is off before switching over")
        if op in ("import", "undo") and data.get("confirm") is not True:
            return refuse("Owner confirmation is required")
        ident = request.match_info.get("job")
        if op in ("verify", "import"):
            j = self.jobs.get(ident)
            required = ("uploaded", "verified", "failed") if op == "verify" else ("verified",)
            if not j or j["state"] not in required or not (self.root / j["id"] / "bundle.wizardbackup").is_file():
                return refuse("Upload and verify this backup before restoring", 409)
            if not data.get("secret"):
                return refuse("Enter this backup's recovery key or passphrase")
        elif ident:
            return refuse("This operation does not use an existing job", 400)
        else:
            j = self.new_job(op)
        await self.lock.acquire()
        j.update(operation=op, state="running", phase=PHASES[op])
        j.pop("result", None)
        j.pop("error", None)
        self.save(j)
        task = asyncio.create_task(self.work(j, data.get("secret")))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return reply(j, 202)

    async def work(self, j, secret):
        op = j["operation"]
        path = self.root / j["id"] / "bundle.wizardbackup"
        try:
            args = [op]
            if op == "export":
                args += ["-o", str(path)]
            elif op in ("verify", "import"):
                args += [str(path)]
                if op == "import":
                    args += ["--yes"]
            elif op == "activate":
                args += ["--old-is-off"]
            raw = await self.run(args, secret=secret, job=j)
            result = public_result(op, raw)
            if secret:
                # Defensive: even a malicious fixture/engine must not echo the submitted secret in a receipt.
                result = json.loads(json.dumps(result).replace(json.dumps(secret)[1:-1], "[redacted]"))
            j.update(result=result, state="verified" if op == "verify" else "complete", phase="Verified" if op == "verify" else "Finished")
            if op == "undo" and raw.get("digest_match") is not True:
                j.update(state="failed", error="Undo finished with differences. Keep both copies until these are checked.")
            if op == "export":
                path.chmod(0o600)
                j.update(sha256=await asyncio.to_thread(digest, path), total_bytes=path.stat().st_size)
        except (Exception, asyncio.CancelledError):
            j.update(state="failed", phase="Needs attention", error=ERRORS[op])
        finally:
            if op == "import" or (op == "export" and j["state"] != "complete"):
                path.unlink(missing_ok=True)
                path.with_suffix(path.suffix + ".part").unlink(missing_ok=True)
            self.save(j)
            self.lock.release()

    async def download(self, request):
        j = self.jobs.get(request.match_info["job"])
        if not j or j["operation"] != "export" or j["state"] != "complete":
            return refuse("Finished backup is not available", 409)
        path = self.root / j["id"] / "bundle.wizardbackup"
        j.update(state="downloading", phase="Sending backup to your Mac")
        response = web.StreamResponse(headers={"Content-Type": "application/octet-stream", "Content-Length": str(path.stat().st_size),
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "X-Wizard-SHA256": j["sha256"]})
        try:
            await response.prepare(request)
            with path.open("rb") as f:
                while chunk := await asyncio.to_thread(f.read, 1 << 20):
                    await response.write(chunk)
            await response.write_eof()
            path.unlink()
            j.update(state="downloaded", phase="Sent to your Mac; guest copy deleted")
        finally:
            if j["state"] == "downloading":
                j.update(state="complete", phase="Download interrupted; ready to retry")
            self.save(j)
        return response

    async def discard(self, request):
        j = self.jobs.get(request.match_info["job"])
        if not j:
            return refuse("Backup job not found", 404)
        if j["state"] in ("running", "uploading", "downloading"):
            return refuse("An active backup operation cannot be discarded", 409)
        shutil.rmtree(self.root / j["id"], ignore_errors=True)
        del self.jobs[j["id"]]
        return reply({"ok": True})


def install(app, door=None):
    door = door or BackupDoor()

    @web.middleware
    async def native_only(request, handler):
        if not request.path.startswith("/api/backup"):
            return await handler(request)
        if (request.headers.get(HEADER) != HEADER_VALUE or "Origin" in request.headers
                or request.headers.get("Sec-Fetch-Site") in ("cross-site", "same-site")
                or request.query_string):
            return refuse("Use the native Wizard app for backups", 403)
        try:
            return await handler(request)
        except (ValueError, OSError, asyncio.TimeoutError, ConnectionError):
            # Never echo exceptions: aiohttp/engine errors may contain request data or secrets.
            return refuse("Backup request could not finish. Check the file, key and free space.", 400)

    app.middlewares.insert(0, native_only)
    app.on_startup.append(door.startup)
    app.on_cleanup.append(door.cleanup)
    app.add_routes([
        web.get("/api/backup/capabilities", door.capability),
        web.get("/api/backup/status", door.status),
        web.post("/api/backup/key/new", door.key_new),
        web.post("/api/backup/upload", door.upload),
        web.get("/api/backup/jobs/{job}", door.status),
        web.get("/api/backup/jobs/{job}/download", door.download, allow_head=False),
        web.delete("/api/backup/jobs/{job}", door.discard),
        web.post("/api/backup/jobs/{job}/{operation}", door.start),
        web.post("/api/backup/{operation}", door.start),
    ])
    return door
