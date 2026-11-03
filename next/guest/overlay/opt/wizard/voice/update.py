"""Authenticated selected-voice image upgrade, separate from the code installer.
Only WAM owns app lifecycle. No mutable tags, registry pulls or image pruning.
The enclosing runtime BOM authenticates this module and the package descriptor.
"""
import hashlib, json, os, subprocess
from pathlib import Path

STATE = 'var/lib/wizard/patches/selected-voice-image-v1'

def sha(path):
    with path.open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()

WAM = 'home/wizard/wizard-app-manager'
WAM_PYTHON = ['sudo','-u','wizard','env','HOME=/home/wizard','/usr/bin/python3','-B','-E','-s','-c']


def wam_route(installer, root, run):
    # WAM install.sh installs its CLI and API with WorkingDirectory=$HERE.
    # Reuse that canonical checkout route, not caller cwd/PYTHONPATH/site fallback.
    source = root/WAM
    uid = 1000 if root == Path('/') else os.geteuid()
    for path in (source, source/'wam', source/'wam/__init__.py', source/'wam/cli.py'):
        installer.check_path(path)
        if not path.exists(): raise RuntimeError('Missing canonical WAM source')
        for member in (path, *path.parents):
            if member == root: break
            meta = member.stat()
            if meta.st_uid not in (0, uid) or meta.st_mode & 0o022:
                raise RuntimeError('Untrusted canonical WAM source')
    if not source.is_dir() or not (source/'wam/__init__.py').is_file() or not (source/'wam/cli.py').is_file():
        raise RuntimeError('Invalid canonical WAM source')
    # Import only: no Config(), auth read or lifecycle. Exact same interpreter,
    # user, HOME and cwd as both activation and recovery. Before any lock/write.
    code = ("import os;from pathlib import Path;from wam import cli;"
            "assert os.geteuid()=="+str(uid)+" and os.environ['HOME']=='/home/wizard';"
            "assert Path(cli.__file__)==Path.cwd()/'wam/cli.py'")
    run([*WAM_PYTHON,code],cwd=str(source),check=True,timeout=30,capture_output=True)
    return source


def lifecycle(run, action, route):
    if action not in ('start','stop'): raise RuntimeError('Invalid voice lifecycle action')
    code = "from pathlib import Path;from wam import cli;assert Path(cli.__file__)==Path.cwd()/'wam/cli.py';c=cli.Config();r=c.runtipi();u='transcriber:'+cli.STORE;r.req('POST','/app-lifecycle/'+u+'/"+action+"',{},timeout=300);r.wait_status(u,{'"+('running' if action=='start' else 'stopped')+"'},timeout=600)"
    run([*WAM_PYTHON,code],cwd=str(route),check=True,timeout=650)

def validate(payload, installer):
    descriptor = payload/'voice-package.json'; installer.check_path(descriptor)
    d=json.loads(descriptor.read_text());m=installer.load_reconciler(payload)
    old=m.validate_selection(d['previousSelection']);new=m.validate_selection(d['selection'])
    assert old['image']=='ghcr.io/humanitylabs-org/wizard-mac-security-transcriber@sha256:fe0bde3040230c526086ac5c729ad81d7ca96fc3c49d846ec27ed3a2065825f6'
    assert {k:v for k,v in old.items() if k not in ('image','bindings')}=={k:v for k,v in new.items() if k not in ('image','bindings')}
    assert old['bindings']['transcriber']==new['bindings']['transcriber']
    assert d['schema']==1 and d['securityPassed'] is True and d['configPreserved'] is True and d['baseLayersPreserved'] is True
    assert json.loads((payload/'selected-engine.json').read_text())==new
    assert d['archive']=='voice-engine.oci.tar'
    archive=payload/d['archive'];installer.check_path(archive)
    assert archive.is_file() and sha(archive)==d['archiveSha256'],'Voice image transport digest mismatch'
    return d,m

def apply(payload, installer, root=Path('/'), run=subprocess.run):
    d,m=validate(payload,installer);base=root/STATE;installer.check_path(base)
    for rel in installer.FILES:
        installer.check_path(payload/'overlay'/rel)
        if not (payload/'overlay'/rel).is_file(): raise RuntimeError('Incomplete voice component')
    fence=root/installer.FENCE;installer.check_path(fence)
    if (root/'var/lib/wizard/voice-rollback-approved').exists(): raise RuntimeError('Rollback approval marker refused')
    if fence.exists() and fence.read_bytes()!=installer.FENCE_BYTES: raise RuntimeError('Unknown rollback fence')
    binding=root/installer.BINDING;contract=root/installer.CONTRACT
    installer.check_path(binding);installer.check_path(contract)
    route=wam_route(installer,root,run)
    # Same cross-process lock as coordinator and component installer. Do not
    # release it between selected-image activation and code transaction commit.
    import fcntl
    lock=root/'var/lib/wizard/voice-reconcile.lock';installer.check_path(lock);lock.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(lock,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        if root==Path('/'): os.fchown(fd,1000,1000)
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (base/'complete.json').exists() and not (base/'rolled-back.json').exists():
            assert json.loads((base/'complete.json').read_text())['selection']==d['selection']
            m.migrate_override(binding,d['selection'])
            return installer._install(payload,root,run)
        if (base/'rolled-back.json').exists():
            # Preserve the failed journal, permit a fresh authenticated retry.
            destination = base.with_name(base.name + '.rolled-back.' + str(__import__('time').time_ns()))
            os.replace(base,destination)
        if base.exists(): raise RuntimeError('Interrupted voice image update; rollback it before retrying')
        # Refuse foreign settings BEFORE lifecycle, loading or selection changes.
        probe=binding.with_name('.voice-image-preflight');m.atomic(probe,binding.read_bytes(),0o600)
        try: m.migrate_override(probe,d['previousSelection'])
        finally: probe.unlink(missing_ok=True)
        if contract.exists() and json.loads(contract.read_text())!=d['previousSelection']:
            raise RuntimeError('Unknown previous selected voice contract')
        # The old image MUST remain present and digest-bound for rollback.
        old=json.loads(run(['docker','image','inspect',d['previousSelection']['image']],check=True,capture_output=True,text=True).stdout)[0]
        assert d['previousSelection']['image'] in old.get('RepoDigests',[])
        base.mkdir(parents=True,mode=0o700)
        saved={}
        for rel in (installer.BINDING,installer.CONTRACT):
            p=root/rel;saved[rel]={'exists':p.exists(),'mode':p.stat().st_mode&0o777 if p.exists() else None,'uid':p.stat().st_uid if p.exists() else None,'gid':p.stat().st_gid if p.exists() else None}
            if p.exists():
                q=base/'original'/rel;q.parent.mkdir(parents=True,exist_ok=True);m.atomic(q,p.read_bytes(),0o600)
        m.atomic(base/'journal.json',json.dumps({'schema':1,'saved':saved,'selection':d['selection'],'previousSelection':d['previousSelection']}).encode(),0o600)
        try:
            run(['systemctl','stop','wizard-voice'],check=True)
            fence=root/installer.FENCE;fence.parent.mkdir(parents=True,exist_ok=True);m.atomic(fence,installer.FENCE_BYTES)
            run(['systemctl','daemon-reload'],check=True)
            lifecycle(run,'stop',route)
            # Immutable new package only; never reload old/base archives.
            run(['docker','load','-i',str(payload/d['archive'])],check=True,timeout=600)
            row=json.loads(run(['docker','image','inspect',d['selection']['image']],check=True,capture_output=True,text=True).stdout)[0]
            assert row['Id']==d['imageId'] and d['selection']['image'] in row.get('RepoDigests',[])
            assert row['Architecture']=='arm64'
            m.atomic(binding,__import__('yaml').safe_dump(m.binding_document(d['selection']),sort_keys=False).encode())
            if root==Path('/'): os.chown(binding,1000,1000)
            if contract.exists(): m.atomic(contract,(payload/'selected-engine.json').read_bytes())
            # Strict component contract checks stay unchanged. This image-owning
            # transaction, not Retry, is the only selected-image transition.
            result=installer._install(payload,root,run)
            lifecycle(run,'start',route)
            m.atomic(base/'complete.json',json.dumps(d,sort_keys=True).encode(),0o600)
            return {'selectedImageUpdated':True,'component':result,'selection':d['selection']}
        except BaseException as primary:
            try: rollback(installer,root,run,locked=True,module=m,route=route)
            except BaseException as recovery_error:
                primary.add_note('Selected voice rollback failed; inspect chained recovery error')
                raise primary from recovery_error
            raise
    finally: os.close(fd)

def recover(payload, installer, root=Path('/'), run=subprocess.run):
    d,m=validate(payload,installer)
    route=wam_route(installer,root,run)
    import fcntl
    lock=root/'var/lib/wizard/voice-reconcile.lock';installer.check_path(lock)
    fd=os.open(lock,os.O_RDWR|os.O_NOFOLLOW)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        journal=json.loads((root/STATE/'journal.json').read_text())
        if journal['selection']!=d['selection']: raise RuntimeError('Rollback package differs from journal')
        return rollback(installer,root,run,locked=True,module=m,route=route)
    finally: os.close(fd)


def rollback(installer, root=Path('/'), run=subprocess.run, locked=False, module=None, route=None):
    if not locked:
        raise RuntimeError('Use the authenticated package entrypoint for locked voice image rollback')
    if route != root/WAM: raise RuntimeError('Canonical WAM route required for rollback')
    m=module;base=root/STATE;installer.check_path(base)
    journal=json.loads((base/'journal.json').read_text())
    run(['systemctl','stop','wizard-voice'],check=True)
    fence=root/installer.FENCE;fence.parent.mkdir(parents=True,exist_ok=True);m.atomic(fence,installer.FENCE_BYTES)
    run(['systemctl','daemon-reload'],check=True);lifecycle(run,'stop',route)
    if (root/installer.BACKUP/'originals.json').exists(): installer._rollback(root,run)
    for rel,meta in journal['saved'].items():
        assert rel in (installer.BINDING,installer.CONTRACT)
        p=root/rel;installer.check_path(p)
        if meta['exists']:
            m.atomic(p,(base/'original'/rel).read_bytes(),meta['mode'])
            if root==Path('/'):os.chown(p,meta['uid'],meta['gid'])
        else:p.unlink(missing_ok=True)
    lifecycle(run,'start',route)
    m.atomic(base/'rolled-back.json',json.dumps(journal,sort_keys=True).encode(),0o600)
    return {'selectedImageRolledBack':True,'coordinatorFenced':True,'imagesPruned':False}
