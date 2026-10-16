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


def snapshot():
    import headless_cold_config, headless_preservation
    config_raw = (DATA/'config.yaml').read_text()
    expected_config, _ = headless_cold_config.migrate(config_raw)
    config = yaml.safe_load(config_raw)
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
        'configExpectedSHA256':digest(expected_config.encode()),
        'authSnapshot':headless_preservation.auth_snapshot(json.loads((DATA/'auth.json').read_text()) if (DATA/'auth.json').exists() else None),
        'configRawSHA256':digest((DATA/'config.yaml').read_bytes()),
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
                         'oldEngineRunning':False,'forbiddenExecutionEvents':0,'historyNotSaturated':True}
        if policy['phase']=='fenced':
            assert not any(c['State']['Running'] for c in containers), 'Unprimed cold target auto-started a container'
        elif policy['phase']=='committed':
            witness=json.loads(Path('/var/lib/wizard/cold-bootstrap/witness.json').read_text())
            assert witness['executionFenceHeldAfterCommit'] is True
            report['fence']['witness']=witness
        else: raise AssertionError('Unexpected audit phase')
    else:
        health=json.load(urllib.request.urlopen('http://127.0.0.1:8923/wizard/health',timeout=20))
        report['health']={k:health.get(k) for k in ('upstream_reachable','queue')}
        if not report['unprimed']:
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
    print('HEADLESS_AUDIT '+json.dumps(snapshot(),sort_keys=True),flush=True)
