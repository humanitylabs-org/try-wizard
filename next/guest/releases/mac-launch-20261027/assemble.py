#!/usr/bin/env python3
"""Build-307 retained-factory clone/apply/seal adapter. Unsigned, never publishes.
Default --plan is read-only. Only admission may call --execute on the Thales worker.
"""
import argparse, hashlib, importlib.util, json, os, re, shutil, socket, subprocess, sys, time
from pathlib import Path
HERE=Path(__file__).resolve().parent
E2='/opt/homebrew/opt/e2fsprogs/sbin/'

def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def run(argv,timeout=120,**kw):
    return subprocess.run(list(map(str,argv)),check=True,timeout=timeout,**kw)

def guest(command,timeout=600):
    # The retained owned dev-shell transport, never an owner's running VM.
    nonce=os.urandom(16).hex();marker='__WZ_'+nonce+'_'
    with socket.create_connection(('127.0.0.1',48000),timeout=10) as s:
        s.settimeout(timeout);s.sendall(('( set -e\n'+command+'\n); rc=$?; printf "\\n'+marker+'%s__\\n" "$rc"\nexit\n').encode());data=b''
        while True:
            chunk=s.recv(65536)
            if not chunk:break
            data+=chunk
    text=data.decode(errors='replace')
    if not re.search(re.escape(marker)+r'0__\r?\n',text):raise RuntimeError('guest command failed; inspect private worker log: '+text[-3000:])
    return text

def plan(pins):
    return {'base':pins['assembly']['base'],'steps':['verify-base-and-boot-sha256','APFS-clone-owned-disposable-VM','boot-owned-host-only','refuse-onboarded-state','generate-validated-runtime-release','sha256-verify-os.sh','WIZARD_RELEASE-install-without-WAM_REF','apply-Mac-overlay-and-managed-runtime','verify-default-sources-and-running-images','security-all-client-closure','seal-empty-identity','clean-shutdown-and-owned-host-exit','offline-fsck-and-zero-free-blocks','BOM-manifest-sparse-archive'],'signing':'unsigned/pluggable','publishing':False}

def runtime_release(pins,root):
    rc=json.loads((HERE/'wizard-os-release-candidate.json').read_text());images={}
    for key,name in [('wam','wizard-app-manager'),('service','wizard-agent-service'),('ux','wizard-ux')]:
        receipt=json.loads((root/'image-packaging'/key/'result.json').read_text())
        assert receipt['sourceCommit']==pins['finalPins'][key] and receipt['pullVerified'] is True
        selected=pins['assembly']['images'][key]
        assert receipt['digest']==selected['digest'] and receipt['ref']==selected['ref']
        assert re.fullmatch(r'sha256:[0-9a-f]{64}',receipt['digest'])
        images[name]={'ref':receipt['ref'],'digest':receipt['digest'],'source_commit':receipt['sourceCommit']}
    return {'version':rc['version'],'components':rc['components'],'default_apps':rc['default_apps'],'hermes':rc['hermes'],'images':images}

def pack(work,pins):
    disk=work/'data/os/disk.img';out=work/'package';(out/'boot').mkdir(parents=True)
    def check(image):
        p=subprocess.run([E2+'e2fsck','-fn',str(image)],capture_output=True,text=True,timeout=300)
        (work/(image.name+'-fsck.log')).write_text(p.stdout+p.stderr);assert p.returncode==0,p.stdout+p.stderr
    check(disk)
    machine=subprocess.run([E2+'debugfs','-R','cat /etc/machine-id',str(disk)],capture_output=True,check=True)
    assert machine.stdout==b'', 'machine identity not sealed'
    source=subprocess.run([E2+'debugfs','-R','cat /home/wizard/wizard-app-manager/SOURCE_COMMIT',str(disk)],capture_output=True,check=True)
    assert source.stdout.decode().strip()==pins['finalPins']['wam'], 'sealed WAM source mismatch'
    for forbidden in ['/var/lib/wizard/setup.json','/home/wizard/.wizard-os/private-access.json']:
        probe=subprocess.run([E2+'debugfs','-R','stat '+forbidden,str(disk)],capture_output=True,check=True)
        assert b'File not found' in probe.stderr, 'identity survived sealing: '+forbidden
    text=subprocess.check_output([E2+'dumpe2fs',str(disk)],text=True,stderr=subprocess.DEVNULL,timeout=90)
    block_match=re.search(r'^Block size:\s+(\d+)',text,re.M);assert block_match
    block=int(block_match[1]);ranges=[]
    for line in text.splitlines():
        if line.startswith('  Free blocks:'):
            for item in line.split(':',1)[1].split(','):
                item=item.strip()
                if item:
                    a,_,b=item.partition('-');ranges.append((int(a),int(b or a)))
    free_match=re.search(r'^Free blocks:\s+(\d+)',text,re.M);assert free_match
    assert sum(b-a+1 for a,b in ranges)==int(free_match[1]);ranges.sort()
    sealed=out/'rootfs.img';run(['cp','-c',disk,sealed]);zero=b'\0'*(8*1024*1024)
    with sealed.open('r+b') as f:
        for a,b in ranges:
            f.seek(a*block);left=(b-a+1)*block
            while left:
                n=min(left,len(zero));f.write(zero[:n]);left-=n
        f.flush();os.fsync(f.fileno())
    # Read back allocated byte identity and free-block zeros, not only writes.
    cursor=0
    with disk.open('rb') as src,sealed.open('rb') as dst:
        for a,b in ranges+[(disk.stat().st_size//block,disk.stat().st_size//block-1)]:
            end=a*block;src.seek(cursor);dst.seek(cursor);left=end-cursor
            while left:
                n=min(left,len(zero));one=src.read(n);two=dst.read(n);assert len(one)==n and one==two;left-=n
            dst.seek(a*block);left=(b-a+1)*block
            while left:
                chunk=dst.read(min(left,len(zero)));assert chunk and not any(chunk);left-=len(chunk)
            cursor=(b+1)*block
    check(sealed)
    for name in ['vmlinux','initrd']:shutil.copy2(work/'data/os/boot'/name,out/'boot'/name)
    files=['rootfs.img','boot/vmlinux','boot/initrd']
    manifest={'name':'Wizard OS','version':pins['factory']['version'],'stack':'wizard-os-0.3.39-runtipi','sourceCommit':pins['finalPins']['native'],'arch':'arm64','kernel':'boot/vmlinux','initrd':'boot/initrd','rootfs':'rootfs.img','cmdline':'console=hvc0 root=/dev/vda rw quiet loglevel=3 systemd.show_status=false','memoryMiB':4096,'installBytes':sum((out/x).stat().st_size for x in files),'files':{x:sha(out/x) for x in files},'sizes':{x:(out/x).stat().st_size for x in files}}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    bom={'schema':1,'base':pins['assembly']['base'],'sources':pins['finalPins'],'runtimeReleaseSha256':sha(work/'runtime-release.json'),'sealedManifest':manifest,'unsigned':True,'publishing':False}
    (out/'bom.json').write_text(json.dumps(bom,indent=2)+'\n')
    archive=work/('wizard-os-'+pins['factory']['version']+'.tar.xz')
    env={**os.environ,'COPYFILE_DISABLE':'1','TMPDIR':str(work)}
    with archive.open('xb') as target,(work/'compression.log').open('w') as log:
        tar=subprocess.Popen(['/usr/bin/tar','-cf','-','-C',str(out),'manifest.json',*files,'bom.json'],stdout=subprocess.PIPE,stderr=log,env=env)
        assert tar.stdout is not None
        xz=subprocess.Popen(['/opt/homebrew/bin/xz','-T2','-1','-c'],stdin=tar.stdout,stdout=target,stderr=log,env=env);tar.stdout.close()
        try:assert xz.wait(timeout=3600)==0 and tar.wait(timeout=30)==0
        finally:
            for proc in [xz,tar]:
                if proc.poll() is None:proc.terminate();proc.wait(timeout=30)
    # Stream the archive, hash every member and reject a layout mismatch; no second 16GB extraction.
    import tarfile
    reader=subprocess.Popen(['/opt/homebrew/bin/xz','-dc',str(archive)],stdout=subprocess.PIPE)
    seen={}
    with tarfile.open(fileobj=reader.stdout,mode='r|') as tar:
        for member in tar:
            assert member.isfile() and member.name in ['manifest.json',*files,'bom.json']
            stream=tar.extractfile(member);assert stream is not None
            hasher=hashlib.sha256()
            for chunk in iter(lambda:stream.read(8*1024*1024),b''):hasher.update(chunk)
            seen[member.name]=hasher.hexdigest()
    assert reader.wait(timeout=30)==0 and set(seen)==set(['manifest.json',*files,'bom.json'])
    assert all(seen[x]==manifest['files'][x] for x in files)
    return {'archive':str(archive),'sha256':sha(archive),'manifest':manifest,'archiveMembersVerified':True}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--stage-root',type=Path,required=True);mode=parser.add_mutually_exclusive_group();mode.add_argument('--execute',action='store_true');mode.add_argument('--plan',action='store_true');a=parser.parse_args()
    pins=json.loads((HERE/'pins.json').read_text());root=a.stage_root.resolve()
    if not a.execute:print(json.dumps(plan(pins),indent=2));return 0
    # Defence in depth: direct invocation cannot bypass admission.
    spec=importlib.util.spec_from_file_location('admission',HERE/'audit.py');assert spec and spec.loader
    audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
    errors=audit.inspect(pins,root)
    if errors:raise SystemExit('BLOCKED: '+json.dumps(errors))
    assert sys.platform=='darwin' and root.is_relative_to(Path(os.environ.get('THALES_MEDIA','/unconfigured-external-media')))
    base=pins['assembly']['base'];original=Path(os.path.expandvars(base['path']));assert sha(original)==base['sha256']
    work=root/'assembly-work';work.mkdir(exist_ok=False);os.chmod(work,0o700)
    assert shutil.disk_usage(work).free>60*1024**3
    for port in [48000,48023,48030]:
        with socket.socket() as sock:sock.bind(('127.0.0.1',port))
    boot=work/'data/os/boot';boot.mkdir(parents=True)
    run(['cp','-c',original,work/'data/os/disk.img']);(work/'data/os/disk.img').chmod(0o600)
    for name,item in base['boot'].items():
        assert sha(Path(os.path.expandvars(item['path'])))==item['sha256'];shutil.copy2(os.path.expandvars(item['path']),boot/name)
    host=Path(os.path.expandvars(pins['assembly']['host']['path']));assert sha(host)==pins['assembly']['host']['sha256']
    (work/'data/os/manifest.json').write_text(json.dumps({'cmdline':'console=hvc0 root=/dev/vda rw','memoryMiB':4096}))
    (work/'data/dev-shell').write_text('owned disposable launch factory\n');(work/'data/files-folder.json').write_text(json.dumps({'path':str(root)}))
    rel=runtime_release(pins,root);(work/'runtime-release.json').write_text(json.dumps(rel,indent=2)+'\n')
    (work/'source-pins.json').write_text(json.dumps({'source':pins['finalPins']['native'],**{x:pins['finalPins'][x] for x in ['ux','service','wam']}}))
    os_sh=root/'final/wam/get.sh';assert sha(os_sh)==pins['osInstaller']['sha256']
    result={'buildStarted':True,'publishing':False,'phase':'booting','baseSha256':base['sha256']};proc=None
    def save():(work/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    save()
    try:
        with (work/'host.stdout').open('w') as out,(work/'host.stderr').open('w') as err:proc=subprocess.Popen([str(host),'--wizard-data-home',str(work/'data')],stdout=out,stderr=err)
        end=time.monotonic()+180
        while time.monotonic()<end:
            assert proc.poll() is None
            try:guest('true',5);break
            except (OSError,RuntimeError):time.sleep(2)
        else:raise TimeoutError('owned guest boot')
        guest('resize2fs /dev/vda; mkdir -p /mnt/launch; mount -t virtiofs wizard-files /mnt/launch; test ! -e /var/lib/wizard/setup.json')
        # Read-only identity refusal happens before network or release installation.
        guest('python3 /mnt/launch/preparation/guest-apply.py --check-pristine > /mnt/launch/assembly-work/pristine.log 2>&1')
        result['phase']='release-and-Mac-layers';save()
        guest('python3 /mnt/launch/preparation/guest-apply.py --apply > /mnt/launch/assembly-work/apply.log 2>&1',5400)
        # Seal may close the socket on poweroff; demand its separate receipt, never swallow a pre-seal failure.
        result['phase']='sealing';save()
        try:guest('python3 /mnt/launch/preparation/seal-factory.py > /mnt/launch/assembly-work/seal.log 2>&1',180)
        except (OSError,RuntimeError):
            assert (work/'factory-sanitization.json').is_file(), 'seal failed before its receipt'
        receipt=json.loads((work/'factory-sanitization.json').read_text());assert receipt['pristine'] is True
        end=time.monotonic()+120
        while time.monotonic()<end:
            status=work/'data/host-status.json'
            if proc.poll() is not None or (status.exists() and json.loads(status.read_text()).get('state')=='stopped'):break
            time.sleep(1)
        else:raise TimeoutError('clean guest shutdown')
        # Quit only this spawned host; do not use killall or touch any installed owner VM.
        if proc.poll() is None:proc.terminate();proc.wait(timeout=30)
        result.update(phase='packing',hostExited=True);save();result.update(pack(work,pins));result['phase']='assembled-unsigned-unpublished'
    except Exception as exc:result.update(phase='failed',error=type(exc).__name__+': '+str(exc));raise
    finally:
        if proc and proc.poll() is None:
            try:guest('sync; systemctl poweroff',20)
            except (OSError,RuntimeError):pass
            try:proc.wait(timeout=60)
            except subprocess.TimeoutExpired:proc.terminate();proc.wait(timeout=30)
        result['baseUnchanged']=sha(original)==base['sha256'];save()
    assert result['baseUnchanged'];print(json.dumps(result,indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
