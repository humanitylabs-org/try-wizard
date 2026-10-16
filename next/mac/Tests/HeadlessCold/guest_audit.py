#!/usr/bin/env python3
"""Read-only guest auditor, transported over the owned VZ socket (no TCP shell).
Outputs hashes and nonsecret structural facts only. No guest transaction priming.
"""
import base64
import collections
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time
import urllib.request
import yaml

ROOT = Path('/home/wizard/runtipi')
DATA = ROOT/'app-data/wizardapps/hermes-agent/data'
STOCK = 'sha256:666d6c659574fa09c1ea47b7ec5f03e8d2c35a8aa8055fe60c1e2fe3d3e03e9b'
POLICY = Path('/var/lib/wizard/cold-bootstrap/policy.json')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def hashed(value):
    return digest(json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode())


def run(*args):
    return subprocess.check_output(args, text=True, timeout=90).strip()


def rows(path):
    # SQL snapshot is internally coherent, read-only, no DB/WAL copying races.
    db = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)
    db.execute('begin')
    result = {}
    for (name,) in db.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name"):
        q = '"'+name.replace('"','""')+'"'
        cols = [r[1] for r in db.execute('pragma table_info('+q+')')]
        result[name] = {'columns':cols, 'rows': sorted(hashed(list(r)) for r in db.execute('select * from '+q))}
    db.rollback(); db.close()
    return result


def wait_health(timeout=240, *, require_managed=False):
    deadline = time.monotonic() + timeout
    while True:
        try:
            # 8923 is AF_VSOCK, bridged by wizard-ux-bridge to TCP 8924.
            request = urllib.request.Request('http://127.0.0.1:8924/wizard/health',
                                             headers={'Host': '127.0.0.1:48023'})
            with urllib.request.urlopen(request, timeout=5) as response:
                health = json.load(response)
            if isinstance(health, dict) and (not require_managed or (
                    health.get('upstream_reachable') is True and
                    isinstance(health.get('queue'), dict) and
                    health['queue'].get('liveness_available') is True)):
                return health
        except (OSError, ValueError):
            pass
        if time.monotonic() >= deadline:
            raise TimeoutError('Guest application health did not become ready')
        time.sleep(1)


def same_boot_restart():
    """QA-owned daemon replacement, only after a real committed cold migration."""
    before = snapshot()  # retain the old daemon's bounded event evidence
    assert before['coldBoot'] and before['fence']['phase'] == 'committed'
    pid_before = run('systemctl','show','docker.service','--property=MainPID','--value')
    assert int(pid_before) > 1
    policy_before = POLICY.read_bytes()
    daemon = Path('/etc/docker/daemon.json')
    daemon_before = daemon.read_bytes()
    ids = run('docker','ps','-aq').split()
    cs = json.loads(run('docker','inspect',*ids))
    stock = {c['Id']:c['State']['StartedAt'] for c in cs if c['Image']==STOCK}
    assert stock, 'Expected retained stock transcriber to exercise internal restore'
    for c in cs:
        if c['Id'] in json.loads(policy_before)['containers']:
            assert c['HostConfig']['RestartPolicy']=={'Name':'no','MaximumRetryCount':0}
    # Default TimeoutStopSec could force-kill dockerd. Disable that escalation for
    # this disposable guest service; a timeout is failure, never passing restart.
    dropin = Path('/run/systemd/system/docker.service.d/headless-clean-restart.conf')
    dropin.parent.mkdir(parents=True,exist_ok=True)
    dropin.write_text('[Service]\nTimeoutStopSec=60\nSendSIGKILL=no\n')
    try:
        run('systemctl','daemon-reload')
        run('systemctl','restart','docker.service')
        pid_after = run('systemctl','show','docker.service','--property=MainPID','--value')
        assert int(pid_after)>1 and pid_after!=pid_before
        assert POLICY.read_bytes()==policy_before and daemon.read_bytes()==daemon_before
        assert json.loads(run('docker','info','--format','{{json .Plugins.Authorization}}'))==['wizard-cold']
        after_cs = json.loads(run('docker','inspect',*run('docker','ps','-aq').split()))
        assert stock == {c['Id']:c['State']['StartedAt'] for c in after_cs if c['Image']==STOCK}
        assert not any(c['Image']==STOCK and c['State']['Running'] for c in after_cs)
        probes = [['create','--label','com.docker.compose.service=hermes-agent-engine',STOCK,'python3','-c','raise SystemExit(99)']]
        for cid in stock:
            probes.extend([[action,cid] for action in ('start','restart','unpause')])
            probes.append(['exec',cid,'python3','-c','raise SystemExit(99)'])
        for args in probes:
            denied = subprocess.run(['docker',*args],capture_output=True,text=True,timeout=30)
            assert denied.returncode!=0 and 'WIZARD_COLD_DENIED' in denied.stderr, args[0]
        after = snapshot()
        assert before['bootID']==after['bootID']
        after['daemonReplacement']={'sameBoot':True,'pidBefore':int(pid_before),'pidAfter':int(pid_after),
            'beforeFence':before['fence'],'afterFence':after['fence'],
            'stockStartedAtUnchanged':True,'persistedFenceUnchanged':True,
            'authorizationPluginActive':True,'deniedRoutes':sorted({p[0] for p in probes}),
            'forceKillDisabled':True}
        return after
    finally:
        dropin.unlink(missing_ok=True)
        run('systemctl','daemon-reload')


def snapshot():
    import headless_cold_config, headless_preservation, headless_config_expectation
    cold = POLICY.exists() and 'wizard.cold=' in Path('/proc/cmdline').read_text()
    health = None if cold else wait_health(require_managed=POLICY.exists())
    config_raw = (DATA/'config.yaml').read_bytes()
    expected_config, config_migration = headless_config_expectation.migrate(
        config_raw, headless_cold_config.migrate)
    normalized = yaml.safe_load(expected_config)
    protected = {}
    # Entire owner content trees; exclude known runtime caches/logs and credential
    # refresh files handled by the production field-aware preservation auditor.
    roots = [DATA/'memories',DATA/'skills',DATA/'documents', DATA/'sessions',
             ROOT/'media',Path('/home/wizard/Files'),Path('/home/wizard/.wizard-os/agent-ssh')]
    for path in [DATA/'SOUL.md', DATA/'USER.md', DATA/'AGENTS.md']:
        if path.is_file(): protected[str(path)] = digest(path.read_bytes())
    for root in roots:
        if not root.exists(): continue
        for path in sorted(root.rglob('*')):
            if path.is_symlink(): protected[str(path)] = hashed({'symlink':os.readlink(path)})
            elif path.is_file():
                with path.open('rb') as f: protected[str(path)] = hashlib.file_digest(f,'sha256').hexdigest()
    databases = {}
    for path in sorted(DATA.rglob('*')):
        if path.is_file() and path.suffix in ('.db','.sqlite','.sqlite3'):
            with path.open('rb') as f: magic = f.read(16)
            if magic == b'SQLite format 3\0': databases[str(path)] = rows(path)
    assert databases, 'No real chat/state database found'
    # Installed app identity from supported WAM on normal boot; cold target does
    # not start WAM's ordinary user services, so inspect disk registry instead.
    apps = sorted(p.name for p in (ROOT/'app-data/wizardapps').iterdir() if p.is_dir())
    account_files = {}
    for app in ('ai-accounts','accounts'):
        tree = ROOT/'app-data/wizardapps'/app
        if tree.exists():
            for p in sorted(tree.rglob('*')):
                if p.is_file() and not p.is_symlink():
                    with p.open('rb') as f: account_files[str(p)] = hashlib.file_digest(f,'sha256').hexdigest()
    ids = run('docker','ps','-aq').split()
    containers = json.loads(run('docker','inspect',*ids))
    engines = [c for c in containers if c.get('Config',{}).get('Labels',{}).get('com.docker.compose.service') == 'hermes-agent-engine']
    assert len(engines)==1
    cold = POLICY.exists() and 'wizard.cold=' in Path('/proc/cmdline').read_text()
    report = {'schema':1,'bootID':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        'coldBoot':cold,'configNormalizedSHA256':hashed(normalized),
        'configExpectedSHA256':digest(expected_config),
        'configMigrationExpectation':config_migration,
        'authSnapshot':headless_preservation.auth_snapshot(json.loads((DATA/'auth.json').read_text()) if (DATA/'auth.json').exists() else None),
        'configRawSHA256':digest(config_raw),
        'protected':protected,'databases':databases,'installedApps':apps,'accountFiles':account_files,
        'engineImage':engines[0]['Image'], 'engineRunning':engines[0]['State']['Running'],
        'unprimed':not POLICY.exists() and not Path('/var/lib/wizard/patches/mac-stack-v1/applied.json').exists()
                   and not Path('/var/lib/wizard/managed/lease.json').exists(),
        'dockerVersions':run('dpkg-query','-W','-f=${Package}=${Version}\n','docker-ce','containerd.io')}
    if cold:
        policy = json.loads(POLICY.read_text())
        assert policy['bootID']==report['bootID']
        assert not any(c['Image']==STOCK and c['State']['Running'] for c in containers)
        # Query the daemon's retained event history from this boot. The documented
        # 256-event buffer is a hard coverage bound: reject saturation, never claim
        # continuity from a truncated event list.
        since = max(0,int(time.time()-float(Path('/proc/uptime').read_text().split()[0])))
        until = str(int(time.time()))
        raw = run('docker','events','--since',str(since),'--until',until,'--format','{{json .}}')
        events = [json.loads(line) for line in raw.splitlines() if line]
        assert len(events)<256, 'Docker event history saturated; cannot certify interval'
        refs = {key for key,value in policy.get('references',{}).items() if value==STOCK}|{STOCK}
        old_ids = {key for key,value in policy['containers'].items() if value['image']==STOCK}
        forbidden=[]
        for e in events:
            action=e.get('Action',e.get('status',''))
            actor=e.get('Actor',{}); attrs=actor.get('Attributes',{})
            if action in ('start','restart','unpause') or action.startswith('exec_start'):
                if actor.get('ID') in old_ids or attrs.get('image') in refs: forbidden.append(e)
        assert not forbidden, 'Old engine execution observed in real daemon event history'
        report['fence']={'phase':policy['phase'],'eventCount':len(events),'since':since,'until':int(until),
                         'oldEngineRunning':False,'forbiddenExecutionEvents':0,'historyNotSaturated':True,
                         'historyScope':'current daemon event ring; restart boundary audited separately'}
        if policy['phase']=='fenced':
            assert not any(c['State']['Running'] for c in containers), 'Unprimed cold target auto-started a container'
        elif policy['phase']=='committed':
            witness=json.loads(Path('/var/lib/wizard/cold-bootstrap/witness.json').read_text())
            assert witness['executionFenceHeldAfterCommit'] is True
            report['fence']['witness']=witness
        else: raise AssertionError('Unexpected audit phase')
    else:
        assert isinstance(health, dict), 'Missing ready application health'
        report['health']={k:health.get(k) for k in ('upstream_reachable','queue')}
        if not report['unprimed']:
            policy = json.loads(POLICY.read_text())
            assert policy['phase']=='activated' and policy['normalBootID']!=policy['bootID']
            assert Path('/etc/docker/daemon.json').read_bytes()==(POLICY.parent/'daemon.original.json').read_bytes()
            assert 'wizard-cold' not in (json.loads(run('docker','info','--format','{{json .Plugins.Authorization}}')) or [])
            retained = 0
            for c in containers:
                old = policy['containers'].get(c['Id'])
                if old:
                    assert c['Image']==old['image']
                    assert c['HostConfig']['RestartPolicy']==old['restart']
                    retained += 1
            assert retained > 0
            report['normalBootRestoration']={'phase':'activated','retainedPoliciesVerified':retained,
                'originalDaemonBytesRestored':True,'coldPluginRemoved':True}
            assert health.get('upstream_reachable') is True
            assert health.get('queue',{}).get('liveness_available') is True
            assert not Path('/var/lib/wizard/managed/lease.json').exists(), 'Managed lease still held'
            # A real production operation reservation, not a fake queue response
            # or a model call. Exercise acquire's actual busy exclusion unchanged.
            import sys, uuid
            sys.path.insert(0,'/opt/wizard/agent-runtime')
            from managed_maintenance import ManagedMaintenance, MaintenanceError
            manager=ManagedMaintenance(); reservation=manager.enter(); token=str(uuid.uuid4())
            denied=False
            try:
                try: manager.acquire(token)
                except MaintenanceError as error:
                    assert str(error)=='runtime_operation_in_flight', str(error)
                    denied=True
                if not denied: manager.release(token)
                assert denied, 'Maintenance admitted while real owned operation held'
                assert not reservation.closed
                assert manager.read() is None, 'Busy rejection left maintenance held'
                report['activeOwnedOperationRefused']=True
            finally:
                reservation.close(); Path(reservation.name).unlink(missing_ok=True)
    return report

if __name__=='__main__':
    print('HEADLESS_AUDIT '+json.dumps(same_boot_restart() if os.environ.get('HEADLESS_RESTART')=='1' else snapshot(),sort_keys=True),flush=True)
