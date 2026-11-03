#!/usr/bin/env python3
"""Full normal voice acceptance after actual focused-source completion.
Inherit exact secured image and production core; never perform host image loads.
"""
import argparse,base64,hashlib,importlib.util,json,os,platform,re,shutil,signal,socket,stat,subprocess,sys,time,uuid
from pathlib import Path
if not __debug__:raise SystemExit('refusing optimized worker harness')
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
PRIOR=Path('/Volumes/ThalesMedia/WizardBuilds/slim-arm-33e623e6434b-accept-r2')
BASELINE=PRIOR/'evidence/fresh-data/os/disk.img'
DRIVER=PRIOR/'evidence/build/slim-core'
CORE_SHA='214b1950bfe7d448d65eba6d6ce445944f914a39aaa0053d717e82f21339d63c'
R4=Path('/Volumes/ThalesMedia/WizardBuilds/slim-arm-33e623e6434b-accept-r4')

def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def need(value,message):
    if not value:raise RuntimeError(message)
def metadata(path):
    s=path.stat();return {'inode':s.st_ino,'device':s.st_dev,'mode':stat.S_IMODE(s.st_mode),'bytes':s.st_size,'mtimeNs':s.st_mtime_ns}
def save(path,data):path.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n')
def load_helpers():
    spec=importlib.util.spec_from_file_location('inherited_core_transport',HERE/'r4_runner.py');assert spec and spec.loader
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.HERE=R4;return m

def preflight(stage):
    need(platform.system()=='Darwin' and platform.machine()=='arm64','Native Thales ARM required')
    need(str(HERE).startswith('/Volumes/ThalesMedia/WizardBuilds/voice-repair-'),'Wrong stage root')
    for rel,want in stage['files'].items():
        path=HERE/rel;need(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(HERE) and sha(path)==want and (path.stat().st_mode&0o777)==stage['fileModes'][rel],'Staged file drift '+rel)
    for row in stage['priorFailureEvidence'].values():
        need(sha(Path(row['remotePath']))==row['sha256'],'Original A3 failed evidence changed')
    need(not (HERE/'arm-evidence').exists(),'Immutable attempt already used')
    need(metadata(BASELINE)==stage['baselineMetadata'],'Pristine metadata changed since seal')
    need(metadata(BASELINE)['inode']==27850082 and metadata(BASELINE)['mode']==0o400,'Wrong pristine baseline')
    need(sha(DRIVER)==CORE_SHA,'Exact already-compiled production core changed')
    m=load_helpers();m.closed(BASELINE)
    census=subprocess.run(['/usr/bin/pgrep','-f','^'+str(DRIVER)+'$'],capture_output=True,text=True,timeout=10)
    need(census.returncode==1 and not census.stdout.strip(),'Owned test core running or census failed')
    for port in (48023,48030):
        with socket.socket() as sock:sock.bind(('127.0.0.1',port))
    resources=m.resources();need(shutil.disk_usage(HERE).free>=180<<30,'Need 180GiB start floor/100GiB reserve')
    return {'preflight':True,'noVMStarted':True,'baseline':metadata(BASELINE),'coreSha256':CORE_SHA,'resources':resources}

def recovery_binding(stage,completion_sha,full_payload=False):
    completion_path=HERE/'inputs/recovery-completion.json'
    need(completion_sha and sha(completion_path)==completion_sha,'Exact parent-reviewed recovery completion required')
    completion=json.loads(completion_path.read_text())
    need(completion['parentVerifiedNativeCompleted'] is True and completion['nativeExitCode']==0 and re.fullmatch(r'heavy_[0-9a-f]{32}',completion['jobId']),'Actual successful native recovery receipt required')
    need(completion['recoveryStageSha256']==stage['recoveryStageSha256'],'Wrong recovery admission')
    for label in ('nativeReceipt','nativeLog'):
        need(sha(Path(completion[label+'Path']))==completion[label+'Sha256'],'Recovery native evidence drift '+label)
    native=json.loads(Path(completion['nativeReceiptPath']).read_text())
    need(native['job_id']==completion['jobId'] and native['state']=='completed' and native['exit_code']==0 and native['log_path']==completion['nativeLogPath'] and native['log_sha256']==completion['nativeLogSha256'],'Native successful completion identity mismatch')
    package_root=Path(stage['recoveryRoot'])/'recovery-evidence';proof_path=package_root/'result.json'
    need(sha(proof_path)==completion['recoveryResultSha256'],'Parent-reviewed recovery result drift')
    proof=json.loads(proof_path.read_text())
    need(proof['success'] is True and proof['source']==stage['sourceRevisions'] and proof['sourceStageSha256']==stage['inheritedSourceStageSha256'] and proof['requestSha256']==stage['recoveryRequestSha256'],'Actual secured recovered package proof required')
    receipt=Path(proof['imageReceipt'])
    need(str(receipt)==stage['recoveryImageReceipt'] and sha(receipt)==proof['imageReceiptSha256'],'Secured recovered package receipt drift')
    source=package_root/'voice-package';inventory=json.loads((source/'resolved-files.json').read_text())
    need(sha(source/'resolved-files.json')==proof['resolvedFilesSha256'],'Resolved package inventory drift')
    for name,want in inventory.items():
        path=source/name
        need(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(source),'Redirected payload refused')
        if full_payload or path.stat().st_size<=2<<20:need(sha(path)==want,'Resolved payload drift '+name)
    return completion,proof,source


def source_binding(stage, completion_sha):
    path=HERE.parent/(HERE.name+'-admission')/'source-completion.json'
    need(completion_sha and sha(path)==completion_sha,'Actual parent-reviewed source completion required')
    c=json.loads(path.read_text())
    need(c['parentVerifiedWorkerCompleted'] is True and c['nativeExitCode']==0 and re.fullmatch(r'heavy_[0-9a-f]{32}',c['jobId']),'Actual successful source worker completion required')
    need(c['sourceStageSha256']==stage['sourceStageSha256'] and c['sourceSpecSha256']==stage['sourceSpecSha256'] and c['sourceRevision']==stage['newNativeSourceRevision'],'Wrong source completion identity')
    # These are copies of actual Forum evidence, transferred by the parent to
    # this sibling admission directory; the native receipt retains Forum paths.
    for label in ('nativeReceipt','nativeLog','nativeSpec','sourceResult'):
        p=Path(c[label+'Path'])
        need(p.parent==path.parent and not p.is_symlink() and sha(p)==c[label+'Sha256'],'Source evidence missing or drifted '+label)
    native_spec=json.loads(Path(c['nativeSpecPath']).read_text())
    need(all(native_spec[k]==stage['sourceSubmit'][k] for k in ('cwd','argv','timeout_seconds')) and native_spec.get('lane')=='light','Native source command mismatch')
    n=json.loads(Path(c['nativeReceiptPath']).read_text())
    need(n['job_id']==c['jobId'] and n['state']=='completed' and n['exit_code']==0 and n['log_sha256']==c['nativeLogSha256'] and n['spec_sha256']==c['nativeSpecSha256'],'Native source completion mismatch')
    r=json.loads(Path(c['sourceResultPath']).read_text())
    need(r['success'] is True and r['stageSha256']==stage['sourceStageSha256'] and r['sourceRevision']==stage['newNativeSourceRevision'] and r['testsRun']==stage['focusedTestsExpected'] and r['skipped']==0 and r['failures']==[] and r['errors']==[],'Focused source proof incomplete')
    return c


def derivative_binding(stage, source):
    p=HERE/'derivative-inventory.json'
    d=json.loads(p.read_text())
    need(d['newNativeSourceRevision']==stage['newNativeSourceRevision'] and d['acceptedImage']==stage['acceptedImage'],'Derivative source/image mismatch')
    need(d['originalInventorySha256']==sha(source/'resolved-files.json'),'Original inventory changed')
    old=json.loads((source/'resolved-files.json').read_text())
    need(set(d['changedOverlay'])=={'overlay/opt/wizard/voice/update.py'},'Unexpected production delta')
    for name,row in d['changedOverlay'].items():
        need(old[name]==row['beforeSha256'],'Wrong original overlay source')
        p=HERE/'code-overlay'/name
        need(p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(HERE/'code-overlay') and sha(p)==row['afterSha256'],'Derivative overlay drift')
    need(d['originalImageDescriptorSha256']==sha(source/'voice-package.json'),'Security descriptor changed')
    descriptor=json.loads((source/'voice-package.json').read_text())
    need(descriptor['selection']['image'].endswith(stage['acceptedImage']),'Wrong accepted voice image')
    return d

def main():
    p=argparse.ArgumentParser();p.add_argument('--stage-sha256',required=True);p.add_argument('--preflight',action='store_true');p.add_argument('--recovery-completion-sha256');p.add_argument('--source-completion-sha256');a=p.parse_args()
    need(sha(HERE/'stage.json')==a.stage_sha256,'Stage manifest digest changed')
    stage=json.loads((HERE/'stage.json').read_text());need(stage.get('acceptanceScope')=='full-normal-voice','Full voice acceptance stage required');initial=preflight(stage)
    if a.preflight:
        completion,proof,source=recovery_binding(stage,a.recovery_completion_sha256)
        derivative_binding(stage,source)
        initial.update(sourceCompletionPending=not bool(a.source_completion_sha256),fullAcceptance=False,securityCompletionBound=True,recoveryJobId=completion['jobId'],recoveryResultSha256=completion['recoveryResultSha256'],imageDigest=proof['image']['digest'],largeArchiveRehashed=False)
        print(json.dumps(initial,sort_keys=True));return
    source_completion=source_binding(stage,a.source_completion_sha256)
    m=load_helpers();lease=m.admission();initial=preflight(stage)
    completion,proof,source=recovery_binding(stage,a.recovery_completion_sha256,full_payload=True)
    derivative=derivative_binding(stage,source)
    # Transport the unchanged image/security descriptor with a NEW code closure. This
    # does not rebuild/repackage/reimport any image on the host. Normal product
    # apply may load this unchanged candidate inside only the synthetic guest.
    with __import__('tarfile').open(HERE/'voice-code.tar','x') as archive:
        for path in sorted(source.rglob('*')):
            if path.is_file():
                name=str(path.relative_to(source))
                selected=HERE/'code-overlay'/name if name in derivative['changedOverlay'] else path
                archive.add(selected,arcname=name,recursive=False)
        archive.add(HERE/'derivative-inventory.json',arcname='derivative-inventory.json',recursive=False)

    out=HERE/'arm-evidence';out.mkdir(mode=0o700)
    for name in ('home','tmp','share'):(out/name).mkdir(mode=0o700)
    result={'success':False,'diagnosticCompleted':False,'fullAcceptance':False,'voiceTranscriptionAccepted':False,
            'sourceRevisions':stage['sourceRevisions'],'stageSha256':a.stage_sha256,'admission':lease,'preflight':initial,
            'coreRecompiled':False,'imageLoadsRepeated':False,'newImageTransportRequired':True,'guestRebuilt':False,'ownerStateAccess':False,'newNativeSourceRevision':stage['newNativeSourceRevision'],'sourceCompletionSha256':a.source_completion_sha256,'sourceJobId':source_completion['jobId'],'derivativeInventorySha256':sha(HERE/'derivative-inventory.json'),'packageReceiptSha256':proof['imageReceiptSha256'],'recoveryCompletionSha256':a.recovery_completion_sha256,'recoveryJobId':completion['jobId'],'recoveryResultSha256':completion['recoveryResultSha256'],'recoveryNativeLogSha256':completion['nativeLogSha256']}
    disk=None
    def cancel(signum,frame):
        if m.CHILD and m.CHILD.poll() is None:m.CHILD.terminate()
        raise KeyboardInterrupt('Parent worker cancellation')
    signal.signal(signal.SIGTERM,cancel);signal.signal(signal.SIGINT,cancel)
    try:
        m.closed(BASELINE);anchor=metadata(BASELINE)
        data=out/'run-data';(data/'os/boot').mkdir(parents=True);(data/'logs').mkdir()
        for name in ('manifest.json','boot/vmlinux','boot/initrd'):shutil.copyfile(BASELINE.parent/name,data/'os'/name)
        manifest=json.loads((data/'os/manifest.json').read_text())
        need(manifest['cmdline'].split().count('console=hvc0')==1,'Inherited userspace console route changed')
        volume=__import__('plistlib').loads(subprocess.check_output(['/usr/sbin/diskutil','info','-plist','/Volumes/ThalesMedia'],timeout=15))
        need(volume.get('FilesystemType')=='apfs','APFS cheap clone required')
        free_before=shutil.disk_usage(HERE).free
        subprocess.run(['/bin/cp','-c',str(BASELINE),str(data/'os/disk.img')],check=True,timeout=60)
        disk=data/'os/disk.img';disk.chmod(0o600);m.closed(disk)
        need(disk.stat().st_dev==BASELINE.stat().st_dev and disk.stat().st_ino!=BASELINE.stat().st_ino,'Clone identity not fresh')
        need(free_before-shutil.disk_usage(HERE).free<4<<30,'Not a cheap clone')
        need(metadata(BASELINE)==anchor,'Pristine baseline changed during clone')
        result['clone']={'baseline':anchor,'clone':metadata(disk),'largeDiskRehashed':False}
        (data/'dev-shell').touch(mode=0o600);save(data/'files-folder.json',{'path':str(out/'share')})
        shutil.copyfile(HERE/'voice-code.tar',out/'share/voice-code.tar')
        subprocess.run(['/usr/bin/say','-r','140','-o',str(out/'share/synthetic.aiff'),'The blue lantern is beside the window. This is a local voice test.'],check=True,timeout=60)
        subprocess.run(['/usr/bin/afconvert','-f','WAVE','-d','LEI16@16000','-c','1',str(out/'share/synthetic.aiff'),str(out/'share/synthetic.wav')],check=True,timeout=30)
        attempt=str(uuid.uuid4());code=base64.b64encode((HERE/'guest_voice.py').read_bytes()).decode()
        env_code='VOICE_ATTEMPT='+attempt+' VOICE_CODE_SHA256='+sha(HERE/'voice-code.tar')+' VOICE_WAV_SHA256='+sha(out/'share/synthetic.wav')
        script=env_code+" python3 - <<'VOICE_PY'\nimport base64\nexec(compile(base64.b64decode("+repr(code)+"),'voice-component-diagnostic','exec'),{'__name__':'__main__'})\nVOICE_PY\n"
        audit=out/'audit.sh';audit.write_text(script);subprocess.run(['/bin/bash','-n',str(audit)],check=True,timeout=10)
        target=out/'01-component';target.mkdir();console=data/'logs/console.log';fence=m.console_begin(console,target)
        env=dict(os.environ,HOME=str(out/'home'),TMPDIR=str(out/'tmp'),PYTHONDONTWRITEBYTECODE='1',
            WIZARD_ACCEPT_ROOT=str(out),WIZARD_HEADLESS_DATA=str(data),WIZARD_HEADLESS_OUTPUT=str(target),
            WIZARD_HEADLESS_MODE='normal',WIZARD_HEADLESS_APP=str(m.APP),WIZARD_HEADLESS_ARCHIVE=str(m.ARCHIVE),WIZARD_HEADLESS_AUDIT=str(audit))
        command=m.command(out,'01-component',[DRIVER],3000,env,False)
        core=json.loads((target/'result.json').read_text());result['core']=core;result['command']=command
        m.closed(disk)
        log=(out/'01-component.log').read_text()
        need(not command['timedOut'] and not m.REPORT.get('forcedOwnedDriverExit') and 'forcing stop' not in log and not core.get('stopFailed'),'Forced cleanup/timeout is not clean acceptance')
        need(core.get('stopped') and core.get('lastStopDescriptorsClosed') and core.get('productionStopCompleted'),'Missing clean production stop/descriptor proof')
        audit=json.loads((target/'guest-audit.json').read_text());result['guest']=audit
        result['console']={**fence,**m.console_end(console,target,audit,'first',attempt)}
        need(metadata(BASELINE)==anchor,'Pristine baseline changed')
        need(core.get('success') and audit.get('success') and command['returncode']==0,'Normal voice acceptance incomplete; inspect safe guest receipt')
        for key in ('fullAcceptance','voiceTranscriptionAccepted','componentRollbackPassed','rollbackRetryInert','selectedImagesAndSecurityPreserved'):
            need(audit.get(key) is True,'Missing ordinary voice acceptance '+key)
        result.update(success=True,fullAcceptance=True,voiceTranscriptionAccepted=True,componentRollbackPassed=True,rollbackRetryInert=True)
    except BaseException as e:result.update(errorClass=type(e).__name__,error=str(e)[:500]);raise
    finally:
        if m.CHILD and m.CHILD.poll() is None:
            m.CHILD.terminate()
            try:m.CHILD.wait(timeout=220)
            except subprocess.TimeoutExpired:
                m.CHILD.kill();m.CHILD.wait();result['forcedOwnedDriverExit']=True;result['success']=False
        result['ownedDiskDescriptorsClosed']=False
        if disk:
            try:m.closed(disk);result['ownedDiskDescriptorsClosed']=True
            except Exception:result['success']=False
        result['baselineMetadataPreserved']=metadata(BASELINE)==stage['baselineMetadata']
        result['finished']=time.time();save(out/'result.json',result)

if __name__=='__main__':main()
