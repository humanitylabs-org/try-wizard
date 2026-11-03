#!/usr/bin/env python3
"""One normal installer observation on a pristine synthetic clone; no acceptance."""
import ast,hashlib,json,os,re,subprocess,tarfile,time
from pathlib import Path
REPORT={'success':False,'voiceTranscriptionAccepted':False,'fullAcceptance':False,'noOwnerData':True,'checks':{},'diagnosticOnly':True,'reviewRequired':True,'installerPhase':'guest-preconditions'}
MEDIA=Path('/home/wizard/runtipi/media')

ENGINE='ghcr.io/humanitylabs-org/wizard-mac-security-transcriber@sha256:fe0bde3040230c526086ac5c729ad81d7ca96fc3c49d846ec27ed3a2065825f6'

def run(argv,timeout=60,check=True):
    result=subprocess.run(list(map(str,argv)),capture_output=True,text=True,timeout=timeout)
    if check and result.returncode:raise RuntimeError('command refused: '+str(argv[:2])+' rc='+str(result.returncode))
    return result

def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


# No arbitrary exception text, source lines, argv, env, credentials or WAM
# response bodies are exported. Stream identities cover exact original bytes;
# only source-bound traceback locations and fixed literal failures are visible.
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

def wam_preconditions(invoke=subprocess.run):
    # Same account/HOME/python/cwd route as update.lifecycle; find_spec only,
    # never import cli, construct Config, read auth or call an app lifecycle.
    code = "import importlib.util,json,os;from pathlib import Path;print(json.dumps({'uid':os.geteuid(),'wamDiscoverable':importlib.util.find_spec('wam') is not None,'sourcePackageExists':Path('/home/wizard/wizard-app-manager/wam/__init__.py').is_file()}))"
    argv=['sudo','-u','wizard','env','HOME=/home/wizard','python3','-c',code]
    try:
        p=invoke(argv,capture_output=True,timeout=15,check=False)
        body=json.loads(p.stdout) if p.returncode==0 else {}
        valid=set(body)=={'uid','wamDiscoverable','sourcePackageExists'} and type(body['uid']) is int and all(type(body[k]) is bool for k in ('wamDiscoverable','sourcePackageExists'))
        return {'operation':'wam-discovery-only','returncode':p.returncode,'valid':valid,
                'fields':body if valid else {},'stderr':stream_evidence(p.stderr,{})}
    except (subprocess.TimeoutExpired,ValueError):
        return {'operation':'wam-discovery-only','valid':False,'fields':{}}


def main():
    assert os.geteuid()==0 and not Path('/var/lib/wizard/setup.json').exists(),'non-pristine guest refused'
    assert not list(Path('/home/wizard/runtipi/app-data/wizard-os/agents').glob('*/agent.json'))
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();attempt=os.environ['VOICE_ATTEMPT']
    witness='SLIM_BOOT_WITNESS '+boot+' '+attempt+' first'
    with open('/dev/hvc0','w') as console:console.write(witness+'\n');console.flush()
    REPORT['checks']['synthetic-marker']={'passed':True,'evidence':{'bootID':boot,'attempt':attempt,'repeat':False,'consoleWitness':witness}}
    image=json.loads(run(['docker','image','inspect',ENGINE]).stdout)[0]
    assert ENGINE in image.get('RepoDigests',[]),'selected immutable image unavailable'
    ids=run(['docker','ps','-aq','--filter','label=com.docker.compose.service=transcriber-engine']).stdout.split()
    assert len(ids)==1,'selected engine missing/ambiguous'
    before=json.loads(run(['docker','inspect',ids[0]]).stdout)[0];assert before['Image']==image['Id']

    REPORT['selectedEngine']={'id':image['Id'],'repoDigests':image.get('RepoDigests',[]),'container':before['Id'],
        'entrypoint':before['Config'].get('Entrypoint'),'user':before['Config'].get('User'),
        'readOnlyRoot':before['HostConfig']['ReadonlyRootfs'],'privileged':before['HostConfig']['Privileged'],
        'capDrop':before['HostConfig'].get('CapDrop'),'securityOpt':before['HostConfig'].get('SecurityOpt')}
    REPORT['installerPhase']='verifying-selected-package'
    package=MEDIA/'voice-code.tar';assert sha(package)==os.environ['VOICE_CODE_SHA256']
    destination=Path('/opt/wizard-voice-update-'+attempt);destination.mkdir(mode=0o755)
    with tarfile.open(package) as archive:archive.extractall(destination,filter='data')

    trusted=trusted_sources(destination)
    REPORT['diagnosticOnly']=True
    REPORT['sourceBindings']={v['label']:v['sha256'] for k,v in trusted.items() if not k.startswith('__')}
    REPORT['wamPreconditions']=wam_preconditions()
    REPORT['installerPhase']='about-to-run-normal-install'
    print('VOICE_CHECKPOINT '+json.dumps({'installerPhase':REPORT['installerPhase'],'wamPreconditions':REPORT['wamPreconditions']},sort_keys=True),flush=True)
    row=observe_installer(['python3',destination/'overlay/opt/wizard/voice/install.py',destination,'--apply'],trusted)
    REPORT['installerCommand']=row
    REPORT['installerPhase']=row['phase']
    REPORT['diagnosticCompleted']=True
    REPORT['reviewRequired']=True
    REPORT['installerSucceeded']=row['returncode']==0 and not row['timedOut']
    # Always stop here, including unexpected success. Never repeat a transaction
    # or continue into Retry/transcription/explicit rollback in an observation.
    raise RuntimeError('Diagnostic-only installer observation complete; review required')

if __name__=='__main__':
    try:main()
    except BaseException as e:
        REPORT['errorClass']=type(e).__name__
        REPORT['error']='Installer observation stopped; inspect safe installerCommand evidence'
    finally:
        REPORT.update(success=False,fullAcceptance=False,voiceTranscriptionAccepted=False)
        print('SLIM_AUDIT '+json.dumps(REPORT,sort_keys=True),flush=True)
    raise SystemExit(1)
