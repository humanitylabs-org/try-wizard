#!/usr/bin/env python3
"""Read-only, secret-free migration evidence from a DISPOSABLE Wizard guest.
Run as the guest's Wizard user from the WAM checkout. Optional argv[1] is a fixture
marker manifest. Never point this at an owner's live installation.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

if not Path("/var/lib/wizard-backup-disposable").exists():
    raise SystemExit("Disposable-guest admission marker required")
sys.path.insert(0, str(Path.cwd()))
from wam.backup.box import Box, box_digest

STOCK = r'''
import hashlib, json, os, sqlite3, sys
from pathlib import Path
sys.path.insert(0, "/opt/hermes")
from hermes_constants import get_hermes_home
from hermes_state import SessionDB
from tools.memory_tool_store import MemoryStore
from cron import jobs
from hermes_cli.config import read_raw_config
home = Path(get_hermes_home())
def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
m = MemoryStore(); m.load_from_disk()
db = SessionDB()
with sqlite3.connect("file:" + str(home / "state.db") + "?mode=ro", uri=True) as sql:
    ids = sorted(row[0] for row in sql.execute("SELECT id FROM sessions"))
sessions = {}
for sid in ids:
    rows = db.get_messages(sid)
    messages = [{"role": r.get("role"), "content": r.get("content")} for r in rows]
    sessions[sid] = {"messages": len(rows), "sha256": sha(messages)}
db.close()
cfg = read_raw_config() or {}
cron = [{k:j.get(k) for k in ("id", "name", "enabled", "state", "paused_at")} for j in jobs.list_jobs(include_disabled=True)]
print(json.dumps({"memory_sha256":sha(m.memory_entries), "user_sha256":sha(m.user_entries),
    "memory_entries":len(m.memory_entries), "user_entries":len(m.user_entries), "sessions":sessions,
    "cron":cron, "telegram_enabled": ((cfg.get("platforms") or {}).get("telegram") or {}).get("enabled")}))
'''


def sha_file(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def last_json(text):
    for line in reversed(text.splitlines()):
        try:
            return json.loads(line)
        except ValueError:
            pass
    raise ValueError("No JSON evidence from stock Hermes")


box = Box()
result: dict = {"agents": {}, "files": {}, "settings": {}, "app_versions": {}, "fixture_checks": {}}
for agent in box.agents():
    result["agents"][agent.id] = last_json(box.runner.python(agent, STOCK, ""))
root = box.files_root()
for path in sorted(root.rglob("*")):
    if path.is_file() and not path.is_symlink() and ".wizard-restore" not in path.relative_to(root).parts:
        result["files"][str(path.relative_to(root))] = {"sha256": sha_file(path), "bytes": path.stat().st_size}
for name in ("settings.json", "launcher.json"):
    p = box.home / name
    if p.exists():
        result["settings"][name] = hashlib.sha256(json.dumps(json.loads(p.read_text()), sort_keys=True).encode()).hexdigest()
for ident, row in box.registry_rows().items():
    result["app_versions"][ident] = {k: row.get(k) for k in ("version", "commit", "urn")}
result["box_digest"] = box_digest(box)
result["files_mount"] = subprocess.run(["findmnt", "-n", "-o", "FSTYPE", "-T", str(root)], capture_output=True, text=True).stdout.strip()
result["staging_mount"] = subprocess.run(["findmnt", "-n", "-o", "FSTYPE", "-T", "/var/lib/wizard"], capture_output=True, text=True).stdout.strip()
if len(sys.argv) > 1:
    marker = json.loads(Path(sys.argv[1]).read_text())
    checks = result["fixture_checks"]
    for entry in marker.get("owner_files", {}).get("files", []):
        checks["file/" + entry["path"]] = result["files"].get(entry["path"], {}).get("sha256") == entry["sha256"]
    for entry in marker.get("agents", {}).values():
        agent = result["agents"].get(entry["id"], {})
        for session in entry.get("sessions", []):
            messages = [{"role": "user" if i % 2 == 0 else "assistant", "content": msg} for i, msg in enumerate(session["messages"])]
            expected = hashlib.sha256(json.dumps(messages, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            checks["session/" + session["id"]] = agent.get("sessions", {}).get(session["id"], {}).get("sha256") == expected
    notify = marker.get("apps", {}).get("notifications", {})
    if notify.get("db"):
        sql = "import json,sqlite3,sys; db=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True); print(json.dumps(any(sys.argv[2] in str(r[0]) for r in db.execute('SELECT message FROM messages'))))"
        p = subprocess.run(["sudo", "-n", "python3", "-c", sql, notify["db"], notify["marker"]], capture_output=True, text=True)
        checks["app/notification"] = p.returncode == 0 and p.stdout.strip() == "true"
    volume = marker.get("apps", {}).get("named_volume", {})
    if volume.get("volume"):
        p = subprocess.run(["sudo", "-n", "python3", "-c", "from pathlib import Path; import sys; print(sys.argv[2] in Path(sys.argv[1]).read_text())",
                            "/var/lib/docker/volumes/" + volume["volume"] + "/_data/" + volume["file"], volume["marker"]], capture_output=True, text=True)
        checks["app/named-volume"] = p.returncode == 0 and p.stdout.strip() == "True"
print(json.dumps(result, sort_keys=True))
