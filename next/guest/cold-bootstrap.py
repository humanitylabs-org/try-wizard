#!/usr/bin/env python3
"""0.3.0 cold admission. Enter as PID1, before systemd/containerd/dockerd.

Docker 29.9 restores containers internally (not through AuthZ). Disable *every*
restart policy offline, then install fail-closed AuthZ before allowing Docker to
start. Unknown formats fail with PID1 still in maintenance, never exec systemd.
Only a stopped-disk rollback restores a failed migration.
"""
import base64
import hashlib
import http.client
import http.server
import json
import os
from pathlib import Path
import re
import shutil
import socketserver
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit, unquote

STATE = Path('/var/lib/wizard/cold-bootstrap')
DOCKER = Path('/var/lib/docker/containers')
PAYLOAD = Path('/run/wizard-update')
# Exact images inspected from the original used 0.6.1 / guest0.3.0 disk.
STOCK = 'sha256:666d6c659574fa09c1ea47b7ec5f03e8d2c35a8aa8055fe60c1e2fe3d3e03e9b'
KNOWN = {
    'runtipi': 'sha256:bd2554bc739578346d04698d768d6d50621372533d4971b0215020ccf6fa4e78',
    'runtipi-db': 'sha256:46614df95668f639da560eed94b0f7405b31c4853a2adac4db92f68050fc80fb',
    'runtipi-queue': 'sha256:01a36bbf3db9360285268c5ea0b87afc7af429f68beb98f30a4136c6c278ed35',
    'runtipi-reverse-proxy': 'sha256:be7212fe3335b5e2ac127f372dda647ae481f02659cfe01c1ab721770c36ce44',
    'files-engine': 'sha256:e9116d24fb8f16426d1c766af84fca0c61e7a4517949869e1321977f34454140',
    'browser-engine': 'sha256:e0ee0385d06869093cdc7f61b94b9e38962e03cf651ac9875a6b36adbc810175',
    'secret-drop-engine': 'sha256:2b6d00c46309d4b44fd804f49356ed9a17c5e5330444a6754d17bed95aa0eeb3',
    'wizard-shell': 'sha256:b2f114e0520b4f210fd7e99dab08ccae44bb6bb47c870b00581f2cec30c24aca',
    'hermes-agent-engine': STOCK, 'transcriber-engine': STOCK,
}
for _service in ('files', 'browser', 'secret-drop', 'hermes-agent', 'transcriber'):
    KNOWN[_service] = 'sha256:2a8393f6eea69a4b558e5dd3a82e2b5a73d30ce3a2fcb5b848bea8545af70bb3'


def read(path):
    return json.loads(path.read_text())


def write(path, value, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.cold-new')
    with tmp.open('w') as f:
        f.write(value if isinstance(value, str) else json.dumps(value, sort_keys=True))
        f.flush(); os.fsync(f.fileno())
    os.chmod(tmp, mode); tmp.replace(path)
    fd = os.open(path.parent, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


def run(args, **kwargs):
    return subprocess.check_output(args, text=True, timeout=180, **kwargs).strip()


def service(c):
    return (c['Config'].get('Labels') or {}).get('com.docker.compose.service', '')


def inventory(directory=DOCKER):
    rows = []
    for p in sorted(directory.iterdir()):
        if not re.fullmatch('[a-f0-9]{64}', p.name) or p.is_symlink():
            raise RuntimeError('Unknown Docker metadata layout')
        c, h = read(p/'config.v2.json'), read(p/'hostconfig.json')
        s = c['State']
        if any(s.get(k) for k in ('Running', 'Paused', 'Restarting', 'Pid')):
            raise RuntimeError('Disk was not cleanly stopped')
        if KNOWN.get(service(c)) != c['Image'] or h.get('Runtime') not in ('runc', ''):
            raise RuntimeError('Unknown legacy container/image/runtime')
        if c.get('Driver') != 'overlay2' or h.get('AutoRemove'):
            raise RuntimeError('Unknown legacy storage/removal semantics')
        rows.append((p, c, h))
    engines = [c for _, c, _ in rows if service(c) == 'hermes-agent-engine']
    if len(engines) != 1 or not all(any(service(c) == s for _, c, _ in rows) for s in ('runtipi', 'runtipi-db', 'runtipi-queue', 'wizard-shell')):
        raise RuntimeError('Not the supported legacy stack')
    return rows


def install():
    if os.getpid() != 1 or os.geteuid() != 0:
        raise RuntimeError('Cold bootstrap is PID1 only')
    token = next((x.split('=', 1)[1] for x in Path('/proc/cmdline').read_text().split() if x.startswith('wizard.cold=')), '')
    if not re.fullmatch('[a-fA-F0-9-]{36}', token): raise RuntimeError('Missing cold transaction')
    if STATE.exists(): raise RuntimeError('Interrupted cold bootstrap: restore stopped snapshot first')
    versions = run(['dpkg-query', '-W', '-f=${Package}=${Version}\n', 'docker-ce', 'containerd.io'])
    if set(versions.splitlines()) != {'docker-ce=5:29.9.0-1~debian.13~trixie', 'containerd.io=2.4.1-2~debian.13~trixie'}:
        raise RuntimeError('Unsupported Docker/containerd version')
    daemon = Path('/etc/docker/daemon.json')
    cfg = read(daemon)
    if set(cfg) - {'features', 'log-driver', 'log-opts'} or cfg.get('features') != {'containerd-snapshotter': False}:
        raise RuntimeError('Unknown Docker daemon configuration')
    if Path('/var/lib/docker/swarm/state.json').exists(): raise RuntimeError('Swarm not supported')
    rows = inventory()
    bom = read(PAYLOAD/'runtime-bom.json')
    managed = read(PAYLOAD/'managed-runtime.json')
    if managed['image'] != bom['managed_runtime']['image']: raise RuntimeError('Managed BOM mismatch')
    STATE.mkdir(mode=0o700)
    shutil.copy2(daemon, STATE/'daemon.original.json')
    saved = {}
    for p, c, h in rows:
        saved[p.name] = {'service': service(c), 'image': c['Image'], 'restart': h['RestartPolicy'], 'started': c.get('HasBeenStartedBefore', False)}
        # Preserve complete original bytes locally too; authoritative rollback is the Mac snapshot.
        shutil.copy2(p/'hostconfig.json', STATE/(p.name+'.hostconfig.json'))
        h['RestartPolicy'] = {'Name': 'no', 'MaximumRetryCount': 0}
        write(p/'hostconfig.json', h)
    policy = {'schema': 1, 'token': token, 'phase': 'fenced', 'versions': versions,
              'references': {c['Config']['Image']: c['Image'] for _, c, _ in rows},
              'containers': saved, 'managed': managed['image'], 'service': bom['service_image_id'],
              'bootID': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    for _, c, _ in rows:
        if service(c) == 'wizard-shell': policy['references'][c['Config']['Image']] = policy['service']
    write(STATE/'policy.json', policy)
    shutil.copy2(__file__, STATE/'gate.py'); os.chmod(STATE/'gate.py', 0o700)
    # Managed fence exists BEFORE any managed image can be started by the AuthZ gate.
    shutil.copytree(PAYLOAD/'agent-runtime', Path('/opt/wizard/agent-runtime'), dirs_exist_ok=True)
    sys.path.insert(0, '/opt/wizard/agent-runtime')
    from managed_maintenance import ManagedMaintenance
    m = ManagedMaintenance()
    if m.read(): raise RuntimeError('Unexpected pre-existing managed lease')
    m.save({'token': token, 'phase': 'held', 'created': time.time(), 'runtimes': [], 'containers': [], 'admission': 'cold-pid1'})
    write(Path('/etc/docker/plugins/wizard-cold.spec'), 'unix:///run/wizard-cold-authz.sock\n', 0o644)
    cfg['authorization-plugins'] = ['wizard-cold']; cfg['live-restore'] = False
    write(daemon, cfg, 0o644)
    unit = '[Unit]\nDefaultDependencies=no\nAfter=systemd-tmpfiles-setup.service\nBefore=docker.service\n[Service]\nType=notify\nNotifyAccess=main\nExecStart=/usr/bin/python3 /var/lib/wizard/cold-bootstrap/gate.py serve\nRestart=on-failure\n'
    write(Path('/etc/systemd/system/wizard-cold-authz.service'), unit, 0o644)
    write(Path('/etc/systemd/system/docker.service.d/wizard-cold.conf'), '[Unit]\nRequires=wizard-cold-authz.service\nAfter=wizard-cold-authz.service\n', 0o644)
    # No default target, timers, user sessions or arbitrary user units in this boot.
    write(Path('/etc/systemd/system/wizard-cold.target'), '[Unit]\nDescription=Wizard cold upgrade\nDefaultDependencies=no\nRequires=sysinit.target docker.service systemd-networkd.service systemd-resolved.service wizard-dev.service wizard-ctl.service wizard-media.service\nAfter=sysinit.target\n', 0o644)
    os.sync()
    print('WIZARD_COLD_FENCED '+json.dumps({'bootID': policy['bootID'], 'containers': len(rows)}), flush=True)
    os.execv('/sbin/init', ['/sbin/init', '--unit=wizard-cold.target'])


def lookup(name):
    matches = []
    for p in DOCKER.iterdir():
        if not re.fullmatch('[a-f0-9]{64}', p.name): continue
        c = read(p/'config.v2.json')
        if p.name == name or (len(name) >= 12 and p.name.startswith(name)) or c['Name'].lstrip('/') == name:
            matches.append(c)
    return matches[0] if len(matches) == 1 else None


def permitted_container(c, policy):
    s = service(c)
    # Baseline engine + transcriber are NEVER allowed in this daemon, including
    # newly created containers using that image under a different name.
    if c['Image'] == policy['managed']:
        return s == 'hermes-agent-engine'
    if c['Image'] == policy['service']: return s == 'wizard-shell'
    return (s.startswith('runtipi') or s in ('hermes-agent',)) and KNOWN.get(s) == c['Image']


def authorize(request, policy, find=lookup):
    # Do not turn malformed/encoded/unknown execution routes into an allow.
    path = re.sub(r'^/v[0-9]+\.[0-9]+', '', urlsplit(request['RequestURI']).path)
    if unquote(path) != path or '..' in path or '//' in path: return False
    method = request['RequestMethod']
    if policy['phase'] not in ('fenced', 'restoring', 'committed'): return False
    if method in ('GET', 'HEAD'): return True
    body = json.loads(base64.b64decode(request.get('RequestBody') or 'e30='))
    if not isinstance(body, dict): return False
    # A single exact restoration, never general execution authority. Use the
    # full saved ID and image/service identity; names, prefixes and query flags
    # cannot broaden this allowance. It is revoked even if the update fails.
    restore = policy.get('restoration')
    if policy['phase'] == 'restoring' and restore and method == 'POST':
        if request['RequestURI'] == '/v1.54/containers/'+restore['id']+'/update':
            c = find(restore['id'])
            return (c is not None and c['Image'] == restore['image']
                    and service(c) == restore['service']
                    and body == {'RestartPolicy': restore['restart']})
    if method == 'POST' and path == '/containers/create':
        image = policy.get('references', {}).get(body.get('Image'), body.get('Image'))
        if image == policy['managed']:
            hc = body.get('HostConfig') or {}
            if hc.get('Privileged') or hc.get('CapAdd') or hc.get('PidMode') == 'host': return False
            if '/var/lib/wizard/managed:/wizard-managed-state:rw' not in hc.get('Binds',[]) and '/var/lib/wizard/managed:/wizard-managed-state' not in hc.get('Binds',[]): return False
        return permitted_container({'Config': body, 'Image': image}, policy)
    match = re.fullmatch('/containers/([^/]+)/(start|restart|unpause|exec|update|stop|kill|wait|attach|resize|rename)', path)
    if match:
        name, action = match.groups(); c = find(name)
        if not c: return False
        if action in ('stop', 'kill', 'wait', 'rename'): return True
        if action == 'exec': return False  # no stock CLI invocation during cold migration
        if action == 'update':
            return method == 'POST' and body == {'RestartPolicy': {'Name': 'no', 'MaximumRetryCount': 0}}
        return permitted_container(c, policy)
    # Minimal non-executing API used by sealed image load + Runtipi compose.
    if method == 'POST' and path in ('/images/load', '/images/prune', '/networks/create', '/volumes/create'): return True
    if method == 'POST' and re.fullmatch('/networks/[^/]+/(connect|disconnect)', path): return True
    if method == 'DELETE' and re.fullmatch('/(containers|networks|volumes)/[^/]+', path): return True
    return False  # exec-start, build, plugins, swarm, checkpoint restore, etc.


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_POST(self):
        try:
            n = int(self.headers.get('Content-Length', '0'))
            if not 0 <= n <= 4*1024*1024: raise ValueError('size')
            req = json.loads(self.rfile.read(n) or '{}')
            if self.path == '/Plugin.Activate': result = {'Implements': ['authz']}
            elif self.path == '/AuthZPlugin.AuthZRes': result = {'Allow': True}
            elif self.path == '/AuthZPlugin.AuthZReq':
                allowed = authorize(req, read(STATE/'policy.json'))
                result = {'Allow': allowed, 'Msg': '' if allowed else 'WIZARD_COLD_DENIED'}
                if not allowed:
                    with (STATE/'denied.jsonl').open('a') as f:
                        f.write(json.dumps({'method': req.get('RequestMethod'), 'path': urlsplit(req.get('RequestURI','')).path})+'\n')
            else: result = {'Allow': False, 'Msg': 'unknown authorization request'}
        except Exception: result = {'Allow': False, 'Msg': 'WIZARD_COLD_POLICY_UNKNOWN'}
        data = json.dumps(result).encode()
        self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)


def admit(token):
    p = read(STATE/'policy.json')
    if p['token'] != token or p['phase'] != 'fenced': raise RuntimeError('Cold authority mismatch')
    if p['bootID'] != Path('/proc/sys/kernel/random/boot_id').read_text().strip(): raise RuntimeError('Not original maintenance boot')
    # This is a consequence check of the closed launch boundary, not idle polling.
    if run(['docker', 'ps', '-q']): raise RuntimeError('Unexpected cold-started container')
    old = next(k for k,v in p['containers'].items() if v['service']=='hermes-agent-engine')
    denied_routes = []
    for args in (['start',old], ['restart',old], ['unpause',old], ['exec',old,'python3','-c','raise SystemExit(99)']):
        denied = subprocess.run(['docker',*args],capture_output=True,text=True,timeout=30)
        if denied.returncode == 0 or 'WIZARD_COLD_DENIED' not in denied.stderr: raise RuntimeError('Forbidden execution not rejected by AuthZ: '+args[0])
        denied_routes.append(args[0])
    if run(['docker', 'ps', '-q']): raise RuntimeError('Forbidden engine started')
    write(STATE/'witness.json', {'bootID': p['bootID'], 'noOldEngine': True, 'forbiddenStartDenied': True, 'deniedRoutes': denied_routes, 'restartPoliciesDisabled': len(p['containers'])})
    for name in ('runtipi-db', 'runtipi-queue', 'runtipi', 'runtipi-reverse-proxy'):
        run(['docker', 'start', name])
    # Runtipi startup (DB migrations/queue connection) is bounded, not assumed.
    for _ in range(90):
        c = json.loads(run(['docker', 'inspect', 'runtipi']))[0]
        if c['State'].get('Health',{}).get('Status') == 'healthy': break
        time.sleep(1)
    else: raise RuntimeError('Runtipi failed to become healthy')
    return p


def restore_restart(container_id, restart):
    # Avoid Docker CLI's broad HostConfig default fields: this request can only
    # change the one saved restart policy. Docker 29.9 uses API v1.54.
    conn = http.client.HTTPConnection('localhost', timeout=30)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(30)
    try:
        sock.connect('/var/run/docker.sock'); conn.sock = sock
        conn.request('POST', '/v1.54/containers/'+container_id+'/update',
                     json.dumps({'RestartPolicy': restart}), {'Content-Type': 'application/json'})
        response = conn.getresponse(); response.read()
        if response.status != 200: raise RuntimeError('Restart policy restoration refused')
    finally:
        conn.close(); sock.close()


def commit():
    p = read(STATE/'policy.json')
    if p['phase'] != 'fenced': raise RuntimeError('Cold commit authority mismatch')
    ids = run(['docker','ps','-aq']).split()
    cs = json.loads(run(['docker','inspect',*ids]))
    main = [c for c in cs if service(c)=='hermes-agent-engine']
    if len(main)!=1 or main[0]['Image'] != p['managed']: raise RuntimeError('Main runtime not replaced')
    if any(c['State']['Running'] and not permitted_container(c,p) for c in cs): raise RuntimeError('Unadmitted runtime')
    lease = read(Path('/var/lib/wizard/managed/lease.json'))
    if lease['token'] != p['token'] or lease['phase'] != 'held': raise RuntimeError('Managed admission lost')
    denied = subprocess.run(['docker','create','--label','com.docker.compose.service=hermes-agent-engine',STOCK,'python3','-c','raise SystemExit(99)'],capture_output=True,text=True,timeout=30)
    if denied.returncode == 0 or 'WIZARD_COLD_DENIED' not in denied.stderr: raise RuntimeError('Old image recreation admitted after load/refresh')
    witness = read(STATE/'witness.json'); witness['oldImageRecreationDeniedAfterMigration'] = True
    write(STATE/'witness.json', witness)
    # Restore only one exact saved policy at a time. No phase ever makes the
    # live plugin permissive; even a partial restoration failure stays fenced.
    try:
        for c in cs:
            old = p['containers'].get(c['Id'])
            if old:
                if c['Image'] != old['image'] or service(c) != old['service']:
                    raise RuntimeError('Restoration container identity changed')
                p['phase'] = 'restoring'
                p['restoration'] = {'id': c['Id'], **old}
                write(STATE/'policy.json', p)
                restore_restart(c['Id'], old['restart'])
    finally:
        p.pop('restoration', None); p['phase'] = 'fenced'
        write(STATE/'policy.json', p)
    # Remove AuthZ only on the next Docker start; current daemon retains its
    # configured plugin and execution denial until shutdown.
    shutil.copy2(STATE/'daemon.original.json', '/etc/docker/daemon.json')
    p['phase'] = 'committed'; write(STATE/'policy.json', p)
    # Exercise the still-live plugin after commit, not just before restoration.
    # This receipt reaches the Host while the maintenance VM is still running.
    probes = [('create', ['create', '--label', 'com.docker.compose.service=hermes-agent-engine', STOCK, 'python3', '-c', 'raise SystemExit(99)'])]
    for c in cs:
        if c['Image'] == STOCK:
            probes.extend([(action, [action, c['Id']]) for action in ('start', 'restart', 'unpause')])
            probes.append(('exec', ['exec', c['Id'], 'python3', '-c', 'raise SystemExit(99)']))
    for action, args in probes:
        denied = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=30)
        if denied.returncode == 0 or 'WIZARD_COLD_DENIED' not in denied.stderr:
            raise RuntimeError('Post-commit stock execution not rejected: '+action)
    witness['postCommitDeniedRoutes'] = sorted(set(action for action, _ in probes))
    witness['executionFenceHeldAfterCommit'] = True
    write(STATE/'witness.json', witness)
    return witness


if __name__ == '__main__':
    if sys.argv[1:] == ['serve']:
        path = '/run/wizard-cold-authz.sock'
        if Path(path).exists(): Path(path).unlink()
        with socketserver.UnixStreamServer(path, Handler) as server:
            os.chmod(path,0o600)
            notify = os.environ.get('NOTIFY_SOCKET')
            if notify:
                with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as sock:
                    sock.connect('\0'+notify[1:] if notify.startswith('@') else notify); sock.sendall(b'READY=1')
            server.serve_forever()
    elif sys.argv[1:] == ['init']:
        try: install()
        except BaseException as e:
            print('WIZARD_COLD_FAILED '+type(e).__name__+': '+str(e), flush=True)
            os.sync()
            # PID1 must not exit/fall through to an ordinary boot after refusal.
            while True: time.sleep(3600)
    else: raise SystemExit('Expected init or serve')
