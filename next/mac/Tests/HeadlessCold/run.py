#!/usr/bin/env python3
"""Durable-worker-only real VZ driver. Never starts an App/NSWorkspace/GUI.

A successful report is scoped headless acceptance, not native UI acceptance.
All large data stays on ThalesMedia; no baseline, installed app or preferences writes.
"""
import argparse
import base64
import collections
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import shutil
import signal
import socket
import subprocess
import sys
import time
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[3]
sys.path.insert(0,str(HERE.parent))
import legacy061_probe as legacy
from build_driver import PRODUCTION


def save(path, value):
    path.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n'); path.chmod(0o600)


def sha(path):
    with path.open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()


def run(argv, **kw):
    return subprocess.run(list(map(str,argv)),check=True,**kw)


def clone(source,target):
    assert not target.exists()
    run(['/bin/cp','-c',source,target]); target.chmod(0o600)


def closed(disk):
    p=subprocess.run(['/usr/sbin/lsof','-t',str(disk)],capture_output=True,text=True)
    assert p.returncode==1 and not p.stdout.strip(), 'Disk descriptors remain: '+str(disk)


def console_state():
    raw=subprocess.check_output(['ioreg','-n','Root','-d1','-a'])
    d=plistlib.loads(raw); roots=d if isinstance(d,list) else [d]
    flags=[]
    for root in roots:
        if 'IOConsoleLocked' in root: flags.append(bool(root['IOConsoleLocked']))
        for row in root.get('IOConsoleUsers',[]):
            if 'CGSSessionScreenIsLocked' in row: flags.append(bool(row['CGSSessionScreenIsLocked']))
    assert flags, 'Console lock state unavailable'
    return {'locked':any(flags),'flags':flags}


def prefs():
    p=subprocess.run(['defaults','export',legacy.DOMAIN,'-'],capture_output=True)
    if p.returncode:
        # Never normalize an absent/failed preference read into a passing empty set.
        raise RuntimeError('Cannot snapshot existing MVP preferences')
    return plistlib.loads(p.stdout)


def tree_hash(root):
    result={}
    for path in sorted(root.rglob('*')):
        if path.is_symlink(): result[str(path.relative_to(root))]={'link':os.readlink(path)}
        elif path.is_file(): result[str(path.relative_to(root))]=sha(path)
    return result


def compare(before,after,guard,*,rollback=False):
    for key in ('protected','installedApps','accountFiles','configNormalizedSHA256'):
        assert before[key]==after[key], 'Preservation mismatch: '+key
    expected=before['configRawSHA256'] if rollback else before['configExpectedSHA256']
    assert expected==after['configRawSHA256'], 'Unexpected config byte changes'
    auth=guard.compare_auth(before['authSnapshot'],after['authSnapshot'])
    assert auth['stable_identity_credentials_preserved'] and not auth['unexpected_field_changes']
    counts={}
    for path,tables in before['databases'].items():
        assert path in after['databases'], 'Database vanished: '+path
        for table,record in tables.items():
            # Chat preservation contract, not incidental runtime caches/FTS or
            # lease/heartbeat bookkeeping. All table hashes remain in evidence.
            if table not in ('sessions','messages'): continue
            assert table in after['databases'][path], 'Table vanished: '+table
            current=after['databases'][path][table]
            assert record['columns']==current['columns'], 'Unexpected schema change: '+table
            # Existing rows must remain, including every old message and session.
            # Additive new runtime rows are allowed; no discarded/changed old row.
            missing=collections.Counter(record['rows'])-collections.Counter(current['rows'])
            assert not missing, 'Existing database rows changed: '+path+'/'+table
            counts[path+'/'+table]=len(record['rows'])
    assert any(k.endswith('/messages') and n>0 for k,n in counts.items()), 'No original chat messages covered'
    return {'auth':auth,'existingRowsPreserved':counts,'protectedFileCount':len(before['protected']),
            'installedApps':before['installedApps'],'configBytesOnlyProductionMigration':not rollback}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--spec',type=Path,required=True)
    p.add_argument('--worker-lease',choices=['inherited'],required=True);a=p.parse_args()
    spec=json.loads(a.spec.read_text()); root=Path(spec['evidenceRoot'])
    assert os.uname().sysname=='Darwin'
    assert root.resolve().is_relative_to('/Volumes/ThalesMedia') and not root.exists()
    source=Path(spec['sourceDir']); assert source.resolve()==SOURCE
    head=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
    assert head==spec['harnessSource']
    run(['git','-C',source,'diff','--exit-code','HEAD','--'])
    baseline=Path(spec['baselineDisk']); boot=Path(spec['bootDir']); candidate=Path(spec['candidateApp']);old=Path(spec['oldApp'])
    assert all(x.resolve().is_relative_to('/Volumes/ThalesMedia') for x in (baseline,boot,old))
    release=json.loads((candidate/'Contents/Resources/wizard-release.json').read_text())
    assert release['releaseID']==PRODUCTION and release['build']=='307'
    assert plistlib.loads((old/'Contents/Info.plist').read_bytes())['CFBundleShortVersionString']=='0.6.1'
    closed(baseline)
    disjoint=legacy.assert_no_competing_wizard()
    for port in (48000,48023,48030):
        with socket.socket() as sock: sock.bind(('127.0.0.1',port))
    locked=console_state(); assert locked['locked'], 'This acceptance requires the console to remain locked (no unlock requested)'
    original_prefs=prefs()
    root.mkdir(mode=0o700)
    (root/'tmp').mkdir(mode=0o700)
    os.environ['TMPDIR']=str(root/'tmp')
    os.environ['CLANG_MODULE_CACHE_PATH']=str(root/'build/module-cache')
    report={'harnessSource':head,'productionReleaseID':PRODUCTION,'success':False,'gates':[],
        'evidenceLayer':'headless real Virtualization + exact production migration/activation; NOT native UI',
        'adapterConsent':True,'physicalClick':False,'GUIStarted':False,'workerLease':'inherited',
        'consoleBefore':locked,'foreignBefore':disjoint}
    save(root/'report.json',report)
    baseline_hash=sha(baseline);old_hash=tree_hash(old);candidate_hash=tree_hash(candidate)
    save(root/'immutable-inputs.json',{'baselineSHA256':baseline_hash,'oldApp':old_hash,'candidateApp':candidate_hash})
    guard_spec=importlib.util.spec_from_file_location('preservation',source/'next/guest/stack-preservation.py')
    assert guard_spec is not None and guard_spec.loader is not None
    guard=importlib.util.module_from_spec(guard_spec);guard_spec.loader.exec_module(guard)
    audit_script='import base64,sys,types\n'
    for name,relative in [('headless_cold_config','next/guest/cold-config.py'),('headless_preservation','next/guest/stack-preservation.py')]:
        encoded=base64.b64encode((source/relative).read_bytes()).decode()
        audit_script+=f'm=types.ModuleType({name!r});exec(base64.b64decode({encoded!r}),m.__dict__);sys.modules[{name!r}]=m\n'
    audit_script+='exec(compile(base64.b64decode('+repr(base64.b64encode((HERE/'guest_audit.py').read_bytes()).decode())+'),"headless_guest_audit","exec"))\n'
    shell=root/'audit.sh';shell.write_text("python3 - <<'HEADLESS_PY'\n"+audit_script+'HEADLESS_PY\n')
    def gate(name,**data):
        report['gates'].append({'name':name,'passed':True,**data});save(root/'report.json',report)
    def prepare(name,source_disk):
        data=root/name/'data';(data/'os').mkdir(parents=True,mode=0o700)
        shutil.copytree(boot,data/'os/boot')
        shutil.copyfile(boot.parent/'manifest.json',data/'os/manifest.json')
        clone(source_disk,data/'os/disk.img');(data/'dev-shell').touch(mode=0o600)
        return data
    child=None
    def execute(mode,data,label):
        nonlocal child
        assert data.resolve().is_relative_to(root)
        closed(data/'os/disk.img');legacy.assert_no_competing_wizard()
        out=root/label;out.mkdir(mode=0o700)
        environment=dict(os.environ,WIZARD_HEADLESS_DATA=str(data),WIZARD_HEADLESS_APP=str(candidate),
            WIZARD_HEADLESS_MODE=mode,WIZARD_HEADLESS_OUTPUT=str(out),WIZARD_HEADLESS_AUDIT=str(shell))
        with (out/'driver.log').open('w') as log:
            child=subprocess.Popen([str(root/'build/headless-cold')],env=environment,stdout=log,stderr=log)
            save(out/'owned-process.json',{'pid':child.pid,'executable':str(root/'build/headless-cold'),'dataHome':str(data)})
            try: rc=child.wait(timeout=2280)
            except subprocess.TimeoutExpired:
                child.terminate()
                try: child.wait(timeout=220)
                except subprocess.TimeoutExpired:
                    # Exact owned driver only; keep disks and mark unclean failure.
                    child.kill();child.wait();report['forcedOwnedDriverExit']=True
                raise RuntimeError('CLI deadline; see private driver log')
            finally:
                if child.poll() is not None: child=None
        closed(data/'os/disk.img')
        result=json.loads((out/'result.json').read_text())
        assert rc==0 and result['success'] and result['stopped'] and result['lastStopDescriptorsClosed'], (label,result.get('error'))
        gate(label,result=result)
        return out
    def cancellation(signum,frame):
        if child and child.poll() is None: child.terminate()
        raise KeyboardInterrupt('Worker cancelled')
    signal.signal(signal.SIGTERM,cancellation);signal.signal(signal.SIGINT,cancellation)
    try:
        # Compilation is intentionally part of this durable command, never SSH preflight.
        with (root/'build.log').open('w') as log:
            run([sys.executable,HERE/'build_driver.py','--source',source,'--out',root/'build'],stdout=log,stderr=log)
        gate('compile-exact-production-driver',binarySHA256=sha(root/'build/headless-cold'))
        data=prepare('success-clone',baseline)
        before_dir=execute('baseline',data,'01-baseline')
        before=json.loads((before_dir/'baseline.json').read_text())
        assert before['unprimed'] and before['engineImage']== 'sha256:666d6c659574fa09c1ea47b7ec5f03e8d2c35a8aa8055fe60c1e2fe3d3e03e9b'
        assert before['engineRunning'] and not before['coldBoot']
        assert set(before['dockerVersions'].splitlines())=={'docker-ce=5:29.9.0-1~debian.13~trixie','containerd.io=2.4.1-2~debian.13~trixie'}
        gate('original061-guest030-unprimed',runtimeProof=before['dockerVersions'])
        # Fork both tests from the SAME cleanly stopped, observed original baseline.
        fault=prepare('fault-clone',data/'os/disk.img')
        upgrade_dir=execute('upgrade',data,'02-upgrade')
        after=json.loads((upgrade_dir/'normal-after.json').read_text())
        gate('upgrade-preservation',comparison=compare(before,after,guard))
        for label in ('cold-before','cold-after'):
            cold=json.loads((upgrade_dir/(label+'.json')).read_text())
            assert cold['coldBoot'] and cold['fence']['historyNotSaturated'] and cold['fence']['forbiddenExecutionEvents']==0
        gate('real-cold-fence-before-through-apply',limits='Docker history verified unsaturated through post-apply audit; production post-commit denial witness; stopped confirmation follows')
        saved={name:sha(data/'updates'/name) for name in ('transaction.json','legacy-complete.json','guest-receipt.json')}
        repeat=execute('repeat',data,'03-repeat')
        assert saved=={name:sha(data/'updates'/name) for name in saved}
        gate('repeat-no-migration',comparison=compare(after,json.loads((repeat/'repeat.json').read_text()),guard))
        fault_dir=execute('fault',fault,'04-post-apply-fault')
        # Byte-identical stopped production rollback BEFORE a normal old boot.
        previous=fault/'updates/previous-disk.img';restored=fault/'os/disk.img'
        assert sha(previous)==sha(restored)
        gate('production-stopped-rollback-byte-identical',sha256=sha(restored))
        recovered=execute('normal',fault,'05-old-recovery')
        recovered_doc=json.loads((recovered/'normal.json').read_text())
        assert recovered_doc['unprimed'] and recovered_doc['engineImage']==before['engineImage'] and recovered_doc['engineRunning']
        gate('old-normal-boot-preservation',comparison=compare(before,recovered_doc,guard,rollback=True))
        # Real stopped disk replacement, not a tiny fake fixture. Recovery must
        # refuse it without replacing either image or mutating the cold journal.
        replacement=fault/'os/replacement.img';clone(restored,replacement);os.replace(replacement,restored)
        tracked=[restored,previous,fault/'updates/transaction.json']
        hashes={str(path):sha(path) for path in tracked}
        execute('reject-disk',fault,'06-changed-disk')
        assert hashes=={str(path):sha(path) for path in tracked}
        gate('changed-real-disk-refused-without-writes')
        assert after['activeOwnedOperationRefused']
        gate('real-production-owned-operation-admission-refused',scope='ManagedMaintenance.enter live reservation; not an active model generation')
        report['success']=True
    except BaseException as error:
        report['error']=type(error).__name__+': '+str(error)
        raise
    finally:
        if child and child.poll() is None:
            child.terminate()
            try: child.wait(timeout=220)
            except subprocess.TimeoutExpired:
                child.kill();child.wait();report['forcedOwnedDriverExit']=True
        # Zero preferences mutations: semantic equality is stronger than import.
        try:
            assert prefs()==original_prefs, 'MVP preferences changed externally; not overwritten'
            assert sha(baseline)==baseline_hash, 'Original disk bytes changed'
            assert tree_hash(old)==old_hash and tree_hash(candidate)==candidate_hash, 'Installed app bytes changed'
            assert legacy.assert_no_competing_wizard()==disjoint, 'Disjoint foreign activity changed'
            report['consoleAfter']=console_state();assert report['consoleAfter']['locked'], 'Console did not remain locked'
            for disk in root.glob('*-clone/data/os/disk.img'):closed(disk)
            report['cleanupVerified']=True
        except BaseException as error:
            report['cleanupVerified']=False;report['cleanupError']=str(error);report['success']=False
        save(root/'report.json',report)
    assert report['success'] and report['cleanupVerified'],report.get('cleanupError')
    print(json.dumps({'success':True,'evidence':str(root/'report.json'),'gates':len(report['gates'])}))

if __name__=='__main__': main()
