#!/usr/bin/env python3
"""Thales acceptance for "Bring My Hermes into Wizard". Runs under the shared worker lock; writes evidence to $E.

Stand-in for Jan: a stock Hermes on this Mac (jan-hermes-home) with a planted memory (LIGHTHOUSE-7Q), one chat,
a scheduled job and a (fake) Telegram token. Target: a clone of an onboarded WizardOS disk (qa-user-v3).
"""
import hashlib, json, os, socket, subprocess as sp, sys, time
from pathlib import Path

WORK_ROOT = Path(os.environ.get("WIZARD_WORK_ROOT") or Path(os.environ.get("TMPDIR") or "/tmp") / "wizard-work").expanduser().resolve()
WORK_ROOT.mkdir(parents=True, exist_ok=True)

Q = (WORK_ROOT / 'Projects/wizard-desktop/existing-hermes-20261014')
BASE = (WORK_ROOT / 'Projects/wizard-desktop/mac-mvp-jan-20261013')
E = Path(os.environ.get('E') or Q / 'evidence-r8'); E.mkdir(parents=True, exist_ok=True)
SRC = Q / 'bring-src'
DISK = Q / 'import-test.img'
JAN = Q / 'jan-hermes-home'
HERMES = Q / 'hermes-src/.venv/bin/hermes'
SHELL, IMPORT = 48400, 48430   # IMPORT = the front door (guest 8930), as the Mac's 48030
results = {}


def note(k, v):
    results[k] = v
    (E / 'results.json').write_text(json.dumps(results, indent=2))
    print('RESULT', k, json.dumps(v)[:600], flush=True)


def guest(cmd, timeout=1800):
    s = socket.create_connection(('127.0.0.1', SHELL), timeout=timeout)
    s.sendall(('{\n' + cmd + '\n} </dev/null 2>&1\nexit\n').encode()); out = b''
    while True:
        b = s.recv(65536)
        if not b: break
        out += b
    return out.decode(errors='replace')


def wait(fn, seconds=300):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            v = fn()
            if v: return v
        except Exception: pass
        time.sleep(2)
    raise RuntimeError('bounded wait failed')


def jan_hashes():
    out = {}
    for n in ('config.yaml', '.env', 'state.db', 'memories/MEMORY.md', 'cron/jobs.json', 'SOUL.md'):
        p = JAN / n
        out[n] = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
    return out


CHAT = r'''
import json, sys, time, uuid, urllib.request
B = 'http://127.0.0.1:8924'
def req(m, path, body=None, headers=None):
    r = urllib.request.Request(B + path, data=None if body is None else json.dumps(body).encode(), method=m,
                               headers={'Content-Type': 'application/json', **(headers or {})})
    with urllib.request.urlopen(r, timeout=120) as f:
        return json.loads(f.read() or b'{}')
sid, msg = sys.argv[1], sys.argv[2]
try:
    req('POST', '/wizard/hermes/api/sessions', {'source': 'wizard-mobile', 'id': sid})
except Exception:
    pass
run = req('POST', '/wizard/hermes/v1/runs', {'session_id': sid, 'input': msg}, {'Idempotency-Key': str(uuid.uuid4())})
rid = run.get('run_id') or run.get('id')
end = time.time() + 900; st = {}
while time.time() < end:
    st = req('GET', f'/wizard/hermes/v1/runs/{rid}')
    if st.get('status') in ('completed', 'failed', 'cancelled', 'canceled', 'error', 'expired'):
        break
    time.sleep(3)
msgs = req('GET', f'/wizard/hermes/api/sessions/{sid}/messages?order=oldest&limit=500')
rows = msgs.get('data') or msgs.get('messages') or msgs.get('items') or []
reply = next((str(m.get('content') or '') for m in reversed(rows) if m.get('role') == 'assistant' and m.get('content')), '')
tools = sorted({m.get('tool_name') for m in rows if m.get('tool_name')} |
               {(tc.get('function') or {}).get('name') for m in rows for tc in (m.get('tool_calls') or []) if isinstance(tc, dict)} - {None})
print(json.dumps({'status': st.get('status'), 'reply': reply[-600:], 'tools': tools}))
'''


def chat(sid, msg):
    (SRC / 'chat.py').write_text(CHAT)
    raw = guest(f"python3 /mnt/eh/chat.py {sid} {json.dumps(msg)}")
    try:
        return json.loads(raw.strip().splitlines()[-1])
    except Exception:
        return {'status': 'harness_error', 'reply': raw[-600:], 'tools': []}


STATE = r'''
import json, sqlite3, yaml, pathlib, re

D = pathlib.Path('/home/wizard/runtipi/app-data/wizardapps/hermes-agent/data')
cfg = yaml.safe_load((D/'config.yaml').read_text()) or {}
env = {l.split('=',1)[0].strip() for l in (D/'.env').read_text().splitlines() if '=' in l and not l.lstrip().startswith('#')}
envv = dict(l.split('=',1) for l in (D/'.env').read_text().splitlines() if '=' in l and not l.lstrip().startswith('#'))
c = sqlite3.connect(f'file:{D}/state.db?mode=ro', uri=True)
sessions = [r[0] for r in c.execute('select id from sessions')]
jobs = json.loads((D/'cron/jobs.json').read_text()).get('jobs', []) if (D/'cron/jobs.json').is_file() else []
mem = (D/'memories/MEMORY.md').read_text() if (D/'memories/MEMORY.md').is_file() else ''
setup = json.loads(pathlib.Path('/var/lib/wizard/setup.json').read_text())
import hashlib
print(json.dumps({
  'terminal': cfg.get('terminal'), 'mcp_wizard': bool((cfg.get('mcp_servers') or {}).get('wizard')),
  'plugins': (cfg.get('plugins') or {}).get('enabled'), 'external_dirs': (cfg.get('skills') or {}).get('external_dirs'),
  'platforms': {k: (v or {}).get('enabled') for k, v in (cfg.get('platforms') or {}).items() if isinstance(v, dict)},
  'model': cfg.get('model'), 'env_names': sorted(env),
  'api_key_sha': hashlib.sha256(envv.get('API_SERVER_KEY','').strip().encode()).hexdigest()[:12],
  'api_port': envv.get('API_SERVER_PORT'), 'telegram_token_present': 'TELEGRAM_BOT_TOKEN' in env,
  'sessions': len(sessions), 'session_ids': sessions[-5:], 'jobs': [(j.get('name'), j.get('enabled'), j.get('state')) for j in jobs],
  'memory_has_codename': 'LIGHTHOUSE-7Q' in mem, 'soul_head': (D/'SOUL.md').read_text()[:60] if (D/'SOUL.md').is_file() else None,
  'setup': {k: setup.get(k) for k in ('done','brain','name')}, 'bin_files': sorted(p.name for p in (D/'bin').glob('*')) if (D/'bin').is_dir() else [],
}))
'''


def state(label):
    (SRC / 'state.py').write_text(STATE)
    raw = guest('python3 /mnt/eh/state.py')
    try:
        st = json.loads(raw.strip().splitlines()[-1])
    except Exception:
        st = {'raw': raw[-1500:]}
    (E / f'state-{label}.json').write_text(json.dumps(st, indent=2))
    return st


def main():
    if not DISK.exists():
        sp.run(['cp', '-c', str(BASE / 'qa-user-v3/os/disk.img'), str(DISK)], check=True)
    for port in (SHELL, IMPORT, 48423):
        s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try: s.bind(('127.0.0.1', port))
        finally: s.close()
    log = (E / 'vm.log').open('w')
    vm = sp.Popen([str(BASE / 'source/next/mac/tools/vmrun'), '--kernel', str(BASE / 'work/boot/vmlinux'),
                   '--initrd', str(BASE / 'work/boot/initrd'), '--disk', str(DISK),
                   '--cmdline', 'console=hvc0 root=/dev/vda rw wizard.dev=1', '--cpus', '3', '--mem', '4096',
                   '--bridge', f'{SHELL}:9200', '--bridge', '48423:8923', '--bridge', f'{IMPORT}:8930',
                   '--share', f'eh={SRC}', '--timeout', '5400', '--console', str(E / 'console.log')],
                  stdout=log, stderr=log)
    try:
        wait(lambda: 'READY' in guest('echo READY'), 300)
        wait(lambda: 'healthy' in guest('docker inspect runtipi --format "{{.State.Health.Status}}"'), 600)
        wait(lambda: 'running' in guest("docker inspect $(docker ps -aq --filter label=com.docker.compose.service=hermes-agent-engine) --format '{{.State.Status}}'"), 600)
        wait(lambda: '"status":"ok"' in guest('curl -s http://127.0.0.1:8924/wizard/health').replace(' ', ''), 600)
        # --- old layout first: the agent loses its terminal after any Runtipi restart (the bug being fixed)
        note('old_key_path', guest("docker exec -u 1000:1000 -e HERMES_HOME=/opt/data $(docker ps -q --filter label=com.docker.compose.service=hermes-agent-engine) /opt/hermes/.venv/bin/hermes config get terminal.ssh_key").strip()[-120:])
        # --- install the patch the way upgrade-mvp-stack does (wam package + named overlay files), then migrate the key
        print(guest('mkdir -p /mnt/eh && (mountpoint -q /mnt/eh || mount -t virtiofs eh /mnt/eh); '
                    'cp -a /mnt/eh/wam/. /home/wizard/wizard-app-manager/wam/; chown -R wizard:wizard /home/wizard/wizard-app-manager/wam; '
                    'for f in wizard-import-hermes wizard-agent-ssh-migrate wizard-apps; do install -m 755 /mnt/eh/bin/$f /opt/wizard/bin/$f; done; '
                    'install -m 644 /mnt/eh/setup/server.py /opt/wizard/setup/server.py; systemctl restart wizard-setup; sleep 2; '
                    'systemctl is-active wizard-setup'), flush=True)
        mig = guest('/opt/wizard/bin/wizard-agent-ssh-migrate')
        note('key_migration', mig.strip()[-500:])
        wait(lambda: '"status":"ok"' in guest('curl -s http://127.0.0.1:8924/wizard/health').replace(' ', ''), 600)
        note('overlay_mount', guest("grep -c ':/opt/agent-ssh:ro' /home/wizard/runtipi/user-config/wizardapps/hermes-agent/docker-compose.yml").strip())
        # Runtipi restart (its start-time chmod -R a+rwx on app-data) must no longer cost the agent its terminal
        note('runtipi_restart', guest("sudo -iu wizard python3 -c \"import sys;sys.path.insert(0,'/home/wizard/wizard-app-manager');from wam import cli;c=cli.Config();rt=c.runtipi();u='hermes-agent:'+cli.STORE;rt.req('POST',f'/app-lifecycle/{u}/restart',{},timeout=300);print(rt.wait_status(u,{'running'},timeout=900))\" 2>&1 | tail -3").strip()[-300:])
        time.sleep(15)
        note('ssh_with_new_key_after_restart', guest("docker exec -u 1000:1000 $(docker ps -q --filter label=com.docker.compose.service=hermes-agent-engine) ssh -i /opt/agent-ssh/id_ed25519 -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null -o ConnectTimeout=15 wizard@wizard-vm 'hostname; echo AGENT_SSH_OK' 2>&1").strip()[-200:])
        note('key_mode_after_restart', guest("docker exec $(docker ps -q --filter label=com.docker.compose.service=hermes-agent-engine) stat -c '%a %u' /opt/agent-ssh/id_ed25519").strip())
        b0 = chat(f"wizard_baseline_{int(time.time())}", "Use your terminal tool to run exactly: hostname && test -d /home/wizard/runtipi && echo IN_WIZARD_VM . Reply with the command output only.")
        note('terminal_before_import_after_runtipi_restart', {'in_vm': 'IN_WIZARD_VM' in b0['reply'], **b0})
        before = state('before'); note('before', {k: before.get(k) for k in ('sessions', 'memory_has_codename', 'setup', 'api_key_sha', 'terminal')})
        jan_before = jan_hashes()

        # --- the Mac side, exactly as the menu item runs it
        t0 = time.time()
        p = sp.run(['/usr/bin/python3', str(SRC / 'wizard-bring-hermes'), '--hermes', str(HERMES), '--port', str(IMPORT)],
                   env={**os.environ, 'HERMES_HOME': str(JAN)}, capture_output=True, text=True, timeout=3600)
        (E / 'bring.txt').write_text(p.stdout + '\n--stderr--\n' + p.stderr)
        res = json.loads(p.stdout.strip().splitlines()[-1])
        note('import', {**res, 'seconds': round(time.time() - t0)})
        assert res.get('ok'), 'import failed'
        note('front_door_refuses_browser_post', guest("curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Origin: https://evil.example' -H 'X-Wizard-Import: hermes-backup' -H 'Content-Length: 3' --data abc http://127.0.0.1:8930/api/agent-import").strip())
        note('import_status_endpoint', guest("curl -s http://127.0.0.1:8930/api/agent-import").strip()[-400:])
        after = state('after')
        note('wiring_kept', {'terminal_backend': (after.get('terminal') or {}).get('backend'),
                             'terminal_same_as_before': after.get('terminal') == before.get('terminal'),
                             'mcp_wizard': after.get('mcp_wizard'), 'plugins': after.get('plugins'),
                             'api_key_same': after.get('api_key_sha') == before.get('api_key_sha'),
                             'imported_api_port_dropped': after.get('api_port') != '18742',
                             'mac_binaries_dropped': after.get('bin_files')})
        note('carried_over', {'memory_has_codename': after.get('memory_has_codename'), 'model': after.get('model'),
                              'soul_head': after.get('soul_head'), 'sessions': after.get('sessions'),
                              'imported_chat_present': any(s.startswith('20261014_180953') for s in after.get('session_ids') or [])})
        note('safety', {'platforms': after.get('platforms'), 'telegram_token_kept_for_later': after.get('telegram_token_present'),
                        'jobs': after.get('jobs'), 'setup': after.get('setup')})
        # The gateway must not try Telegram (a fake token would log a connect failure).
        tg = guest("C=$(docker ps -q --filter label=com.docker.compose.service=hermes-agent-engine); sleep 20; "
                   "docker logs --since 10m $C 2>&1 | grep -ci telegram; docker logs --since 10m $C 2>&1 | grep -i telegram | tail -5")
        note('telegram_log_lines', tg.strip()[-600:])

        # --- the user job, through the Agent Service (what Wizard UX calls)
        thr = guest("curl -s 'http://127.0.0.1:8924/wizard/hermes/api/sessions?limit=100&offset=0&include_children=false'")
        (E / 'thread-list.json').write_text(thr)
        note('thread_list', {'imported_cli_chat_listed': '20261014_180953_877252' in thr, 'head': thr[:200]})
        sid = f"wizard_import_check_{int(time.time())}"
        r1 = chat(sid, "What's the codename of my QA agent project? Reply with just the codename.")
        note('memory_recall', {'has_codename': 'LIGHTHOUSE-7Q' in r1['reply'], **r1})
        r2 = chat(sid, "Use your terminal tool to run exactly: hostname && test -d /home/wizard/runtipi && echo IN_WIZARD_VM . Reply with the command output only.")
        note('terminal_in_vm', {'in_vm': 'IN_WIZARD_VM' in r2['reply'], **r2})
        r3 = chat(sid, "Use the wizard_apps tool (from the wizard MCP server, via tool search if needed) and list the installed app ids, comma separated.")
        note('app_tool', r3)
        r5 = chat(sid, "Search your past sessions for what we said about Playwright, and tell me in one sentence.")
        note('past_chat_search', r5)
        listed = False
        for _ in range(12):   # the Agent Service serves its cached list while it refreshes (30 s cache)
            thr2 = guest("curl -s 'http://127.0.0.1:8924/wizard/hermes/api/sessions?limit=100&offset=0&include_children=false'")
            if sid in thr2:
                listed = True; break
            time.sleep(10)
        note('new_chat_listed', {'listed': listed, 'old_box_threads_gone': 'wizard_1791893870614' not in thr2})

        # --- the agent survives an app restart
        guest("sudo -iu wizard python3 -c \"import sys;sys.path.insert(0,'/home/wizard/wizard-app-manager');from wam import cli;c=cli.Config();rt=c.runtipi();u='hermes-agent:'+cli.STORE;rt.req('POST',f'/app-lifecycle/{u}/restart',{},timeout=300);print(rt.wait_status(u,{'running'},timeout=900))\"")
        time.sleep(15)
        r4 = chat(sid, "Remind me: what's my QA project codename? Just the codename.")
        note('after_restart_recall', {'has_codename': 'LIGHTHOUSE-7Q' in r4['reply'], **r4})
        r6 = chat(sid, "Use your terminal tool to run exactly: hostname && echo STILL_IN_VM . Reply with the command output only.")
        note('terminal_after_import_and_restart', {'in_vm': 'STILL_IN_VM' in r6['reply'], **r6})

        # --- undo puts the old agent back
        p = sp.run(['/usr/bin/python3', str(SRC / 'wizard-bring-hermes'), '--undo', '--port', str(IMPORT)],
                   capture_output=True, text=True, timeout=3600)
        (E / 'undo.txt').write_text(p.stdout + p.stderr)
        note('undo', json.loads(p.stdout.strip().splitlines()[-1]))
        undone = state('undone')
        note('undo_restored', {'sessions_match': undone.get('sessions') == before.get('sessions'),
                               'memory_codename_gone': not undone.get('memory_has_codename'),
                               'setup_match': undone.get('setup') == before.get('setup'),
                               'terminal_match': undone.get('terminal') == before.get('terminal'),
                               'api_key_match': undone.get('api_key_sha') == before.get('api_key_sha')})
        note('mac_hermes_untouched', jan_hashes() == jan_before)
        note('no_backup_left_in_vm', {'incoming': guest('ls -A /var/lib/wizard/agent-import-incoming/ 2>&1').strip(),
                                      'workdirs': guest('ls /var/lib/wizard/agent-import/*/ 2>/dev/null').strip()})
        print('ACCEPTANCE_DONE', flush=True)
    finally:
        try: (E / 'import-journal.txt').write_text(guest('journalctl -u wizard-import --no-pager | tail -60'))
        except Exception: pass
        try: guest('systemctl poweroff')
        except OSError: pass
        try: vm.wait(timeout=90)
        except sp.TimeoutExpired: vm.terminate(); vm.wait(timeout=45)
        print('VM_STOPPED', vm.returncode, flush=True)


if __name__ == '__main__':
    main()
