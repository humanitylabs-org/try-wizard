#!/usr/bin/env python3
"""Owned pristine clone only. Synthetic audio; production component/Retry route.
Full acceptance requires ordinary transcription, Retry, rollback and clean stop.
"""
import ast,hashlib,importlib.util,json,os,re,subprocess,tarfile,time,urllib.request,urllib.error
from pathlib import Path
REPORT={'success':False,'voiceTranscriptionAccepted':False,'fullAcceptance':False,'noOwnerData':True,'checks':{}}
MEDIA=Path('/home/wizard/runtipi/media')
MODEL='istupakov/parakeet-tdt-0.6b-v2-onnx'
ENGINE='ghcr.io/humanitylabs-org/wizard-mac-security-transcriber@sha256:fe0bde3040230c526086ac5c729ad81d7ca96fc3c49d846ec27ed3a2065825f6'

def run(argv,timeout=60,check=True):
    result=subprocess.run(list(map(str,argv)),capture_output=True,text=True,timeout=timeout)
    if check and result.returncode:raise RuntimeError('command refused: '+str(argv[:2])+' rc='+str(result.returncode))
    return result

def docker(*args):return run(['docker',*args],120,False)
def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);assert spec and spec.loader
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def public(path,method='GET',body=None):
    authority='127.0.0.1:'+str(48030 if path.startswith('/api/voice/') else 48023)
    port=8930 if path.startswith('/api/voice/') else 8924
    headers={'Host':authority,'Origin':'http://'+authority}
    if body is not None:headers.update({'Content-Type':'audio/wav','X-Wizard-Filename':'synthetic-local-voice.wav'})
    req=urllib.request.Request('http://127.0.0.1:'+str(port)+path,data=body if body is not None else (b'' if method=='POST' else None),headers=headers,method=method)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req,timeout=120 if body else 10) as response:
        return response.status,json.loads(response.read(65536))

def identities():
    ids=run(['docker','image','ls','-q','--no-trunc']).stdout.split()
    rows=json.loads(run(['docker','image','inspect',*sorted(set(ids))]).stdout)
    return sorted([{'Id':r['Id'],'RepoDigests':sorted(r.get('RepoDigests') or [])} for r in rows],key=lambda r:r['Id'])

def state_files(installer):
    result={}
    for rel in (*installer.FILES,installer.CONTRACT,installer.BINDING):
        p=Path('/')/rel
        result[rel]={'exists':p.exists(),'sha256':sha(p) if p.is_file() else None,
                     'mode':p.stat().st_mode&0o777 if p.exists() else None,
                     'uid':p.stat().st_uid if p.exists() else None,'gid':p.stat().st_gid if p.exists() else None}
    return result

MAX_VISIBLE = 16384

def stream_evidence(value, trusted):
    raw = value.encode('utf-8') if isinstance(value, str) else (value or b'')
    text = raw.decode('utf-8', errors='replace')
    visible = []
    frames = []
    for line in text.splitlines()[-100:]:
        frame = re.fullmatch(r'  File "([^"]+)", line ([0-9]+), in ([A-Za-z_][A-Za-z_0-9]*|<module>)', line)
        if frame and frame[1] in trusted:
            spec = trusted[frame[1]]
            number = int(frame[2])
            if 1 <= number <= spec['lines'] and frame[3] in spec['functions']:
                row = {'file': spec['label'], 'line': number, 'function': frame[3]}
                frames.append(row)
                visible.append('FRAME ' + json.dumps(row, sort_keys=True))
                continue
        if line in ('Traceback (most recent call last):',
                    'During handling of the above exception, another exception occurred:',
                    'The above exception was the direct cause of the following exception:'):
            visible.append(line)
        elif line in ("ModuleNotFoundError: No module named 'wam'", "ModuleNotFoundError: No module named 'yaml'",
                       "ModuleNotFoundError: No module named 'wam.cli'"):
            visible.append(line)
        elif line in trusted.get('__literal_errors__', ()):
            visible.append(line)
        else:
            # Exception *class* is useful even when its payload is sensitive.
            kind = re.match(r'^([A-Za-z_][A-Za-z_0-9]*(?:Error|Exception|Exit|Interrupt))(?::|$)', line)
            if kind and kind[1] in ('RuntimeError','AssertionError','FileNotFoundError','PermissionError',
                                    'CalledProcessError','TimeoutExpired','ImportError','ModuleNotFoundError',
                                    'BlockingIOError','ValueError','KeyError','SystemExit','KeyboardInterrupt'):
                visible.append(kind[1] + ': <payload withheld>')
            else:
                visible.append('<line withheld sha256=' + hashlib.sha256(line.encode()).hexdigest() + '>')
    safe = '\n'.join(visible)
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'safeTail':safe[-MAX_VISIBLE:],'tailTruncated':len(text.splitlines())>100 or len(safe)>MAX_VISIBLE,
            'trustedFrames':frames[-30:],'rawExported':False}

def trusted_sources(destination):
    result = {'__literal_errors__': []}
    for name in ('install','update','reconcile'):
        p = destination/'overlay/opt/wizard/voice'/(name+'.py')
        raw = p.read_bytes(); text = raw.decode(); tree = ast.parse(text)
        functions = {'<module>'} | {n.name for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
        result[str(p)] = {'label':name+'.py','sha256':hashlib.sha256(raw).hexdigest(),
                          'lines':len(text.splitlines()),'functions':functions}
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and isinstance(node.exc.func, ast.Name):
                args = node.exc.args
                if node.exc.func.id in ('RuntimeError','ValueError') and len(args)==1 and isinstance(args[0],ast.Constant) and isinstance(args[0].value,str):
                    result['__literal_errors__'].append(node.exc.func.id+': '+args[0].value)
    return result

def observe_installer(argv, trusted, timeout=900, invoke=subprocess.run):
    started=time.monotonic()
    try:
        # Bytes mode preserves exact stream hashes, including invalid UTF-8.
        p=invoke(list(map(str,argv)),capture_output=True,timeout=timeout,check=False)
        row={'returncode':p.returncode,'timedOut':False,'stdout':stream_evidence(p.stdout,trusted),
             'stderr':stream_evidence(p.stderr,trusted)}
    except subprocess.TimeoutExpired as e:
        row={'returncode':None,'timedOut':True,'stdout':stream_evidence(e.stdout,trusted),
             'stderr':stream_evidence(e.stderr,trusted)}
    row.update(operation='normal-selected-image-install',seconds=round(time.monotonic()-started,3),
               phase='installer-returned' if not row['timedOut'] else 'installer-timeout',checkBypassed=False)
    frames=row['stderr']['trustedFrames']
    row['lastTrustedFrame']=frames[-1] if frames else None
    return row

def installer_receipt(argv, destination, label, timeout=900):
    # Keep complete raw streams in memory only; publish sanitized source-bound
    # failure evidence BEFORE enforcing exit/timeout or parsing a success row.
    trusted=trusted_sources(destination);captured={}
    def invoke(*args,**kwargs):
        value=subprocess.run(*args,**kwargs);captured['stdout']=value.stdout
        return value
    row=observe_installer(argv,trusted,timeout=timeout,invoke=invoke)
    row['operation']=label
    REPORT.setdefault('installerCommands',{})[label]=row
    REPORT['sourceBindings']={v['label']:v['sha256'] for k,v in trusted.items() if not k.startswith('__')}
    print('VOICE_CHECKPOINT '+json.dumps({'operation':label,'installerCommand':row},sort_keys=True),flush=True)
    if row['returncode']!=0 or row['timedOut']:
        raise RuntimeError('Normal voice installer failed; inspect safe installerCommands evidence')
    return json.loads(captured['stdout'].decode().splitlines()[-1])

def main():
    assert os.geteuid()==0 and not Path('/var/lib/wizard/setup.json').exists(),'non-pristine guest refused'
    assert not list(Path('/home/wizard/runtipi/app-data/wizard-os/agents').glob('*/agent.json'))
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();attempt=os.environ['VOICE_ATTEMPT']
    witness='SLIM_BOOT_WITNESS '+boot+' '+attempt+' first'
    with open('/dev/hvc0','w') as console:console.write(witness+'\n');console.flush()
    REPORT['checks']['synthetic-marker']={'passed':True,'evidence':{'bootID':boot,'attempt':attempt,'repeat':False,'consoleWitness':witness}}
    before_images=identities();image=json.loads(run(['docker','image','inspect',ENGINE]).stdout)[0]
    assert ENGINE in image.get('RepoDigests',[]),'selected immutable image unavailable'
    ids=run(['docker','ps','-aq','--filter','label=com.docker.compose.service=transcriber-engine']).stdout.split()
    assert len(ids)==1,'selected engine missing/ambiguous'
    before=json.loads(run(['docker','inspect',ids[0]]).stdout)[0];assert before['Image']==image['Id']
    runtime_code="""import hashlib,importlib.metadata as m,inspect,json,platform,sys
from speaches.executors import parakeet
from onnx_asr.models import NemoConformerTdt
s=inspect.getsource(parakeet)
def version(name):
 try:return m.version(name)
 except m.PackageNotFoundError:return None
print(json.dumps({'python':sys.version,'machine':platform.machine(),'libc':platform.libc_ver(),'packages':{p:version(p) for p in ['speaches','onnx-asr','onnxruntime','numpy','huggingface-hub']},'parakeetSourceSha256':hashlib.sha256(s.encode()).hexdigest(),'parakeetSource':s,'int8Files':NemoConformerTdt._get_model_files(quantization='int8')}))"""
    runtime=run(['docker','exec',ids[0],'python','-c',runtime_code],60,False)
    REPORT['shippedRuntime']={'returncode':runtime.returncode}
    if runtime.returncode==0:REPORT['shippedRuntime'].update(json.loads(runtime.stdout))
    REPORT['selectedEngine']={'id':image['Id'],'repoDigests':image.get('RepoDigests',[]),'container':before['Id'],
        'entrypoint':before['Config'].get('Entrypoint'),'user':before['Config'].get('User'),
        'readOnlyRoot':before['HostConfig']['ReadonlyRootfs'],'privileged':before['HostConfig']['Privileged'],
        'capDrop':before['HostConfig'].get('CapDrop'),'securityOpt':before['HostConfig'].get('SecurityOpt')}
    package=MEDIA/'voice-code.tar';assert sha(package)==os.environ['VOICE_CODE_SHA256']
    destination=Path('/opt/wizard-voice-update-'+attempt);destination.mkdir(mode=0o755)
    with tarfile.open(package) as archive:archive.extractall(destination,filter='data')
    installer=load('voice_component',destination/'overlay/opt/wizard/voice/install.py')
    originals=state_files(installer)
    receipt=installer_receipt(['python3',destination/'overlay/opt/wizard/voice/install.py',destination,'--apply'],destination,'apply');REPORT['normalSelectedImageInstall']=receipt
    image=json.loads(run(['docker','image','inspect',receipt['selection']['image']]).stdout)[0]
    # Exact same production selected-image + component entrypoint is a no-op.
    repeated=installer_receipt(['python3',destination/'overlay/opt/wizard/voice/install.py',destination,'--apply'],destination,'repeat',timeout=120)
    assert repeated.get('alreadyInstalled') is True
    REPORT['componentRepeatedInstall']=True
    now=run(['docker','ps','-aq','--filter','label=com.docker.compose.service=transcriber-engine']).stdout.split();assert len(now)==1
    current=json.loads(run(['docker','inspect',now[0]]).stdout)[0]
    assert current['Image']==image['Id']
    for key in ('ReadonlyRootfs','Privileged','CapDrop','SecurityOpt'):
        assert current['HostConfig'].get(key)==before['HostConfig'].get(key),'selected-image update changed security'
    assert current['Config']['User']==before['Config']['User']=='ubuntu'
    updated_images=identities()
    # Setup restart is inside production transaction. Await its existing route.
    until=time.monotonic()+45
    while True:
        try:public('/api/voice/status');break
        except (OSError,urllib.error.URLError):
            if time.monotonic()>until:raise
            time.sleep(1)
    status_file=Path('/var/lib/wizard/voice.json')
    previous_status_stamp=status_file.stat().st_mtime_ns if status_file.exists() else 0
    requests=[]
    for _ in range(3):
        status,body=public('/api/voice/retry','POST');assert status==202 and body.get('accepted') is True
        requests.append(body)
    REPORT['normalRetryResponses']=requests
    until=time.monotonic()+620
    while True:
        stamp_before=status_file.stat().st_mtime_ns if status_file.exists() else 0
        _,status=public('/api/voice/status')
        stamp_after=status_file.stat().st_mtime_ns if status_file.exists() else 0
        active=run(['systemctl','is-active','wizard-voice'],check=False).stdout.strip()
        if stamp_before==stamp_after and stamp_after>previous_status_stamp and active in ('failed','inactive') and status['state'] in ('ready','error'):break
        if time.monotonic()>until:raise RuntimeError('normal Retry did not finish bounded preparation')
        time.sleep(2)
    REPORT['publicVoiceStatus']=status
    module=load('voice_runtime_probe',Path('/opt/wizard/voice/reconcile.py'))
    row=module.engine(docker,image['Id']);assert row
    REPORT['engineUnchangedAfterRetry']=row['Id']==current['Id'] and identities()==updated_images
    assert REPORT['engineUnchangedAfterRetry']
    try:
        module.health(row);module.verify_model_runtime(docker,row)
        _,voice=public('/wizard/voice/status')
        assert voice.get('provider')=='local' and voice.get('model')==MODEL and voice.get('ready') is True,'normal route did not select required local model'
        wav=MEDIA/'synthetic.wav';assert sha(wav)==os.environ['VOICE_WAV_SHA256']
        _,transcript=public('/wizard/voice/transcribe','POST',wav.read_bytes())
        text=str(transcript.get('text','')).lower()
        assert all(word in text for word in ('blue','lantern','window')),'synthetic phrase not recovered'
        REPORT['syntheticTranscription']={'text':text,'audioSha256':sha(wav),'route':'/wizard/voice/transcribe','provider':'local','model':MODEL}
        REPORT['voiceTranscriptionAccepted']=True
    except module.Refusal as e:
        REPORT['runtimeBoundary']={'supported':False,'actionableReason':str(e),'newPackagingNeeded':True,'transcriptionAttempted':False}
        assert status['state']=='error','unverified runtime must not report ready'
    # Exercise actual normal selected-image rollback, including code fencing.
    rollback=installer_receipt(['python3',destination/'overlay/opt/wizard/voice/install.py',destination,'--rollback'],destination,'rollback');REPORT['normalSelectedImageRollback']=rollback
    REPORT['restoredFiles']=state_files(installer)
    assert REPORT['restoredFiles']==originals,'rollback did not restore exact original code/bindings/modes/owners'
    assert (Path('/')/installer.FENCE).read_bytes()==installer.FENCE_BYTES
    fields=('LoadState','ActiveState','SubState','Result','ConditionResult','ExecMainCode','ExecMainStatus','MainPID','ExecMainStartTimestampMonotonic','InvocationID','ConditionTimestampMonotonic','DropInPaths','FragmentPath','UnitFileState','NeedDaemonReload')
    def snapshot(label):
        result=run(['systemctl','show','wizard-voice',*[v for f in fields for v in ('-p',f)]],check=False)
        value={'returncode':result.returncode,'fields':dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line),'stderr':result.stderr[:300]}
        value['hashes']={str(p):sha(p) if p.is_file() else None for p in (Path('/var/lib/wizard/voice.json'),Path('/var/lib/wizard/voice-installed'),Path('/')/installer.BINDING,Path('/')/installer.CONTRACT,Path('/opt/wizard/bin/wizard-apps'))}
        REPORT.setdefault('rollbackDiagnostics',{})[label]=value
        print('VOICE_CHECKPOINT '+json.dumps({label:value},sort_keys=True),flush=True)
        return value
    time.sleep(6) # exceeds normal endpoint coalescing window; no bypass route
    before_retry=snapshot('beforeRetry')
    status,reply=public('/api/voice/retry','POST');REPORT['rollbackRetryResponse']={'status':status,'body':reply}
    time.sleep(2);after_retry=snapshot('afterRetry')
    # ConditionResult alone is historical, and a false condition does not clear
    # a former failed ActiveState. Prove no writer invocation or output change.
    assert status==202 and reply.get('accepted') is True
    def inert(a,b):
        assert a['returncode']==b['returncode']==0
        for key in ('ExecMainStartTimestampMonotonic','InvocationID'):
            assert a['fields'].get(key)==b['fields'].get(key),'rollback started a writer: '+key
        assert b['fields'].get('MainPID')=='0' and b['fields'].get('ActiveState')=='inactive'
        assert a['hashes']==b['hashes'],'rollback Retry changed old-writer output/config'
    inert(before_retry,after_retry)
    # Prove the actual systemd activation fence even if Retry was coalesced.
    for label in ('directStart','afterDaemonReload'):
        if label=='afterDaemonReload':run(['systemctl','daemon-reload'])
        prior=snapshot(label+'Before')
        result=run(['systemctl','start','wizard-voice'],check=False)
        after_start=snapshot(label+'After');after_start['startReturncode']=result.returncode
        inert(prior,after_start)
        assert after_start['fields'].get('ConditionResult')=='no','rollback fence not evaluated false'
        assert int(after_start['fields']['ConditionTimestampMonotonic'])>int(prior['fields'].get('ConditionTimestampMonotonic') or 0),'no fresh condition evaluation'
    assert identities()==updated_images,'unexpected image store change/prune during rollback'
    rows=run(['docker','ps','-aq','--filter','label=com.docker.compose.service=transcriber-engine']).stdout.split();assert len(rows)==1
    after=json.loads(run(['docker','inspect',rows[0]]).stdout)[0]
    for key in ('ReadonlyRootfs','Privileged','CapDrop','SecurityOpt'):
        assert after['HostConfig'].get(key)==before['HostConfig'].get(key),'security setting changed'
    assert after['Image']==before['Image'] and after['Config']['User']==before['Config']['User']
    assert REPORT['voiceTranscriptionAccepted'] is True,'new engine did not transcribe synthetic audio via normal Wizard route'
    REPORT.update(success=True,fullAcceptance=True,componentRollbackPassed=True,rollbackRetryInert=True,selectedImagesAndSecurityPreserved=True)

if __name__=='__main__':
    try:main()
    except BaseException as e:REPORT['errorClass']=type(e).__name__;REPORT['error']=str(e)[:400]
    finally:print('SLIM_AUDIT '+json.dumps(REPORT,sort_keys=True),flush=True)
