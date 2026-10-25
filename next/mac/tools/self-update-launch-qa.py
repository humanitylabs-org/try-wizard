#!/usr/bin/env python3
"""Thales-only, disposable native updater proof. Never publishes or boots a VM.
Builds three ad-hoc Apple-signed apps with an ephemeral Ed25519 update key,
then drives the real AppKit/Sparkle path 18001 -> 18002 -> 18003.
"""
import argparse, functools, hashlib, http.server, json, os, pathlib, plistlib, re, shutil, signal, subprocess, tempfile, threading, time

p = argparse.ArgumentParser()
p.add_argument('--root', required=True, type=pathlib.Path)
p.add_argument('--sparkle', required=True, type=pathlib.Path)
p.add_argument('--first-build', type=int, default=18001)
p.add_argument('--source-head', required=True)
a = p.parse_args(); root = a.root.resolve(); source = pathlib.Path(__file__).resolve().parents[1]
root.mkdir(parents=True, exist_ok=True)
evidence = root/'evidence'; evidence.mkdir(exist_ok=True)
feed = root/'feed'; feed.mkdir(exist_ok=True)
data = root/'data'; runtime = None
installed = root/'installed/Wizard.app'; installed.parent.mkdir(exist_ok=True)
builds=list(range(a.first_build,a.first_build+3))
results = []; requests = []; server = None; preference_backup = None; passed = False

def run(argv, **kw): return subprocess.run(list(map(str, argv)), check=True, **kw)
def source_identity(directory, expected):
    head = subprocess.check_output(['git','-C',str(directory),'rev-parse','HEAD'],text=True).strip()
    status = subprocess.check_output(['git','-C',str(directory),'status','--porcelain','--untracked-files=all'],text=True)
    assert head == expected, f'Source head mismatch: {head} != {expected}'
    assert not status, 'Native QA requires a clean source tree: '+status
    return {'head':head,'statusPorcelain':status}

def helper_pid_rows(text, bundle, domain):
    owned = []
    inside = str(bundle/'Contents')+'/'
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2 or not parts[0].isdigit(): continue
        pid, command = int(parts[0]), parts[1]
        if command.startswith(inside): owned.append(pid); continue
        # Sparkle 2.10 copies its progress Updater to a Launcher cache.
        # Match its executable component and exact host-bundle argument, not
        # a broad substring or another bundle's helper/cache.
        match = re.match(r'^(/.+/Updater\.app/Contents/MacOS/Updater) (.+) ([01])$',command)
        if match and match[2] == str(bundle): owned.append(pid); continue
    return owned

def assert_no_bundle_helpers():
    # Observation only. Cleanup never signals another installation's process.
    text=subprocess.check_output(['ps','-axo','pid=,command='],text=True)
    for line in text.splitlines():
        parts=line.strip().split(None,1)
        if len(parts)!=2: continue
        match=re.match(r'^(/.+/Autoupdate) (\S+) (.+) (\S+)$',parts[1])
        assert not (match and match[2]=='org.humanitylabs.wizard.mvp'), line
        progress=re.match(r'^(/.+/Updater\.app/Contents/MacOS/Updater) (.+) ([01])$',parts[1])
        if progress:
            info=pathlib.Path(progress[2])/'Contents/Info.plist'
            if info.exists():
                assert plistlib.loads(info.read_bytes()).get('CFBundleIdentifier')!='org.humanitylabs.wizard.mvp', line
    assert not owned_processes(), text

def record(name, detail=None):
    results.append({'name': name, 'pass': True, 'detail': detail})
    (evidence/'results.json').write_text(json.dumps(results, indent=2)+'\n')
    print('PASS', name, flush=True)
def version(): return plistlib.loads((installed/'Contents/Info.plist').read_bytes())['CFBundleVersion']
def live():
    pattern = '^' + re.escape(str(installed/'Contents/MacOS/Wizard')) + '([[:space:]]|$)'
    r = subprocess.run(['pgrep', '-f', pattern], capture_output=True, text=True)
    return [int(i) for i in r.stdout.split()]
def notify(command): run([root/'notify', *command.split()], stdout=subprocess.DEVNULL)
def snapshot():
    target=data/'updates/qa.json'; target.unlink(missing_ok=True); notify('update-state')
    end=time.time()+5
    while time.time()<end:
        if target.exists(): return json.loads(target.read_text())
        time.sleep(.15)
    return {}
def wait_state(check, seconds=90):
    end=time.time()+seconds; last={}
    while time.time()<end:
        last=snapshot()
        if check(last): return last
        time.sleep(.3)
    raise AssertionError('Timed out waiting for updater: '+json.dumps(last))
def quit_app():
    if live():
        notify('update-quit'); end=time.time()+55
        while live() and time.time()<end: time.sleep(.25)
        assert not live(), 'Ordinary Quit did not terminate owned app'
def owned_processes():
    text = subprocess.check_output(['ps','-axo','pid=,command='],text=True)
    return helper_pid_rows(text, installed, 'org.humanitylabs.wizard.mvp')

def no_helpers(seconds=15):
    end=time.monotonic()+seconds
    while owned_processes() and time.monotonic()<end: time.sleep(.2)
    assert not owned_processes(), 'Owned app or copied Sparkle helper remains'

def phase_sequence(*phases):
    state=json.loads((data/'updates/ui.json').read_text())
    history=state.get('phaseHistory',[])
    positions=[history.index(p) for p in phases]
    assert positions==sorted(positions), history
    return state

def cleanup_app(grace=5):
    """Only this run's bundle; a failed Quit must not strand a job."""
    cleanup = {'notifyError': None, 'signals': []}
    if live():
        try: notify('update-quit')
        except Exception as error: cleanup['notifyError'] = str(error)
    for sig in (None, signal.SIGTERM, signal.SIGKILL):
        if sig is not None:
            for pid in owned_processes():
                try:
                    os.kill(pid, sig)
                    cleanup['signals'].append({'pid': pid, 'signal': sig.name})
                except ProcessLookupError: pass
        end = time.monotonic() + grace
        while owned_processes() and time.monotonic() < end: time.sleep(.1)
        if not owned_processes(): break
    assert not owned_processes(), 'Owned Wizard/helper survived cleanup SIGKILL'
    return cleanup

def launch():
    run(['open','-n','-a',installed,'--args','--wizard-data-home',data])
    wait_state(lambda s: s.get('build') == version())
    notify('connect '+base+'/wizard/')
    time.sleep(2)
def stage(build, mutate=None, signing_key=None):
    run(['python3',source/'tools/make-update-feed.py',root/f'build-{build}/Wizard.app',feed,
         '--base-url',base,'--sign-tool',signer,'--key-file',key], stdout=subprocess.DEVNULL)
    if mutate or signing_key:
        import xml.etree.ElementTree as X
        X.register_namespace('sparkle','http://www.andymatuschak.org/xml-namespaces/sparkle')
        X.register_namespace('wizard','https://humanitylabs.co/wizard-updates/v1')
        path=feed/'appcast.xml'; tree=X.parse(path); item=tree.find('./channel/item')
        if mutate: mutate(item)
        tree.write(path,encoding='utf-8',xml_declaration=True)
        run([signer,'--ed-key-file',signing_key or key,path],stdout=subprocess.DEVNULL)

def add_delta(item):
    import copy, xml.etree.ElementTree as X
    ns='{http://www.andymatuschak.org/xml-namespaces/sparkle}'
    delta=copy.deepcopy(item.find('enclosure')); delta.set(ns+'deltaFrom',str(first+1))
    X.SubElement(item,ns+'deltas').append(delta)

def ready():
    notify('update-check')
    return wait_state(lambda s: s.get('phase')=='ready' and s.get('ready'),180)
def fail_without_replacement(name, message, archive=True, signature=False, install=False, outer_code=None):
    before=version(); request_count=len(requests); notify('update-check')
    end=time.time()+90
    while time.time()<end:
        seen=requests[request_count:]
        if '/appcast.xml' in seen and (not archive or any(x.endswith('.zip') for x in seen)): break
        time.sleep(.1)
    else: raise AssertionError('Negative case never reached its feed/archive: '+name)
    if install:
        wait_state(lambda s:s.get('phase')=='ready' and s.get('ready'),90)
        notify('update-restart')
    s=wait_state(lambda s:s.get('phase')=='failed' and message in s.get('message',''),90)
    if signature:
        assert {'domain':'SUSparkleErrorDomain','code':3002} in s.get('errors',[]), s
    if outer_code is not None:
        assert s.get('errors',[None])[0] == {'domain':'SUSparkleErrorDomain','code':outer_code}, s
    assert not s.get('ready') and version()==before
    record(name,s)

try:
    identity=source_identity(source,a.source_head)
    (evidence/'source-identity.json').write_text(json.dumps(identity,indent=2)+'\n')
    units=root/'artifact-unit'; units.mkdir()
    for qa in (False,True):
        name='qa' if qa else 'production'; binary=units/name
        command=['xcrun','swiftc','-swift-version','5','-module-cache-path',str(units/'cache')]
        if qa: command+=['-D','WIZARD_UPDATE_QA']
        command += [str(source/'App/UpdateArtifact.swift'),str(source/'Tests/UpdateArtifact/main.swift'),'-o',str(binary)]
        run(command)
        output=subprocess.check_output([binary],text=True,env={**os.environ,'WIZARD_ARTIFACT_TEST_ROOT':str(units/(name+'-data'))})
        (evidence/f'artifact-unit-{name}.txt').write_text(output)
        record(f'artifact-unit-{name}',output)
    # Never interfere with another app/Host or another QA session's global defaults.
    existing=subprocess.run(['pgrep','-x','Wizard|Wizard Host'],capture_output=True,text=True)
    assert existing.returncode != 0, 'Another native Wizard app/Host is active; retry after its owner finishes'
    assert_no_bundle_helpers()
    mappings=subprocess.check_output(['/usr/bin/hidutil','property','--get','UserKeyMapping'],text=True)
    assert 'HIDKeyboardModifierMappingSrc' not in mappings, 'Existing keyboard remapping belongs to another owner; not running native QA'
    # Keep the small disposable installation + AppKit state on the internal
    # cache volume. LaunchServices ad-hoc apps can block in __open writing state
    # to a removable volume; Sparkle can likewise block in renameatx_np there.
    # Builds, archives and retained evidence stay under --root (ThalesMedia).
    cache = pathlib.Path.home()/'Library/Caches'; cache.mkdir(parents=True, exist_ok=True)
    runtime = tempfile.TemporaryDirectory(prefix='wizard-update-qa-', dir=cache)
    data = pathlib.Path(runtime.name)/'data'; data.mkdir()
    installed = pathlib.Path(runtime.name)/'installed/Wizard.app'; installed.parent.mkdir()
    record('isolated-local-runtime', {'dataHome': str(data), 'installedApp': str(installed)})
    key=root/'update-key'; signer=a.sparkle/'bin/sign_update'
    # Exporting a dedicated keychain item could touch the production signer. Use a
    # fresh CryptoKit key instead, as the 32-byte seed this sign_update accepts.
    generator=root/'key.swift'
    generator.write_text('import Foundation\nimport CryptoKit\nlet k=Curve25519.Signing.PrivateKey(); let d=k.rawRepresentation\ntry d.base64EncodedString().write(toFile:CommandLine.arguments[1],atomically:true,encoding:.utf8)\nprint(k.publicKey.rawRepresentation.base64EncodedString())\n')
    public=subprocess.check_output(['swift',generator,key],text=True).strip()
    os.chmod(key,0o600)
    wrong_key=root/'wrong-update-key'
    subprocess.check_output(['swift',generator,wrong_key],text=True)
    os.chmod(wrong_key,0o600)
    run(['swiftc',source/'tools/update-qa-notify.swift','-o',root/'notify'])
    env=os.environ|{'SPARKLE_DIR':str(a.sparkle),'SPARKLE_PUBLIC_KEY':public,
                    'SPARKLE_FEED':'http://127.0.0.1:1/appcast.xml','RELEASE_ID':a.source_head,
                    'DMG':'0','SIGN_IDENTITY':'-','GUEST_UPDATE_PAYLOAD':'','WIZARD_UPDATE_QA':'1'}
    for build in builds:
        with (evidence/f'build-{build}.log').open('w') as log:
            run(['bash',source/'build.sh'],env=env|{'BUILD':str(build),'VER':f'0.7.1-qa.{build}'},stdout=log,stderr=subprocess.STDOUT)
            run(['ditto',source/'dist/Wizard.app',root/f'build-{build}/Wizard.app'],stdout=log,stderr=subprocess.STDOUT)
    for build in builds:
        bundle=root/f'build-{build}/Wizard.app'
        run(['codesign','--verify','--deep','--strict',bundle])
        info=subprocess.run(['codesign','-d','--verbose=4',bundle],capture_output=True,text=True,check=True).stderr
        assert 'Signature=adhoc' in info, info
        metadata=plistlib.loads((bundle/'Contents/Info.plist').read_bytes())
        assert metadata['SURequireSignedFeed'] and metadata['SUVerifyUpdateBeforeExtraction'] and metadata['SUPublicEDKey']==public
        assert metadata.get('SUSignedFeedFailureExpirationInterval') == 0
        assert metadata.get('SUAllowsAutomaticUpdates') is False
        (evidence/f'signing-{build}.txt').write_text(info)
    record('three-native-builds-ad-hoc-no-Developer-ID-signed-feed-required',list(builds))
    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path.split('?',1)[0])
            if self.path == '/redirect.zip':
                self.send_response(302); self.send_header('Location',base+'/redirect-target.zip'); self.end_headers()
            elif self.path.startswith('/wizard'):
                body=b'<!doctype html><title>Updater protocol fixture</title><script>window.__wux={voice:"idle"};window.wizardUX={ready:true};</script><p>Isolated updater protocol fixture, not a real guest.</p>'
                self.send_response(200); self.send_header('Content-Type','text/html'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
            else: super().do_GET()
        def log_message(self, format, *args):
            with (evidence/'http.log').open('a') as log: log.write(format % args+'\n')
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(feed)))
    threading.Thread(target=server.serve_forever,daemon=True).start(); base=f'http://127.0.0.1:{server.server_port}'
    domain='org.humanitylabs.wizard.mvp'
    original=subprocess.run(['defaults','export',domain,'-'],capture_output=True)
    preference_backup=original.stdout if original.returncode==0 else b''
    (evidence/'preferences-before.plist').write_bytes(preference_backup)
    subprocess.run(['defaults','delete',domain],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    prefs={'QAHooks':True,'QAWebStorage':True,'DataHome':str(data),'SUFeedURL':base+'/appcast.xml',
           'SUEnableAutomaticChecks':True,'SUAutomaticallyUpdate':False,'SUHasLaunchedBefore':True,
           'backends':b'[]','activeBackend':0,'filesFolder':str(root/'files'),
           'SUEnableSystemProfiling':False,'wizardKeyEnabled':False,'MeetingPrompts':False,'VoiceKeys':False,
           'SUSkippedVersion':str(a.first_build-2),'QAQuitDuringUpdateExtraction':True}
    pref=root/'preferences.plist'; pref.write_bytes(plistlib.dumps(prefs)); run(['defaults','import',domain,pref])
    first=a.first_build
    stage(first+1)
    run(['ditto',root/f'build-{first}/Wizard.app',installed])
    run(['open','-n','-a',installed,'--args','--wizard-data-home',data])
    end=time.time()+20
    while not live() and not (data/'updates/ui.json').exists() and time.time()<end: time.sleep(.1)
    assert live() or (data/'updates/ui.json').exists(), 'Installed app did not launch'
    # A fast successful Quit can finish before the first PID sample. The UI
    # file and consumed one-shot preference provide durable hook evidence.
    end=time.time()+180
    while live() and time.time()<end: time.sleep(.25)
    assert not live() and version()==str(first), 'Quit during extraction replaced app or failed to terminate'
    saved=plistlib.loads(subprocess.check_output(['defaults','export',domain,'-']))
    assert not saved.get('QAQuitDuringUpdateExtraction') and saved.get('SUSkippedVersion')==str(first-2)
    extraction=phase_sequence('quit-deferring','quit-dismissed')
    no_helpers(); assert_no_bundle_helpers()
    time.sleep(30)
    assert version()==str(first) and not owned_processes(), 'Late replacement/helper after extraction Quit'
    assert_no_bundle_helpers()
    record('ordinary-quit-during-extraction-defers-tears-down-preserves-previous-skip',extraction)
    launch(); initial=ready()
    (evidence/'ps-at-ready.txt').write_text(subprocess.check_output(['ps','-axo','pid=,command='],text=True))
    # Ready is now private verified staging; no Sparkle installer exists before
    # explicit restart admission. Killing an actual Sparkle stage 1 would INSTALL
    # on host death in 2.10, so never manufacture that unsafe production state.
    assert initial.get('freshDownloadReady')
    assert owned_processes()==live(), 'Installer created before restart admission'
    record('real-Sparkle-signed-feed-SHA256-private-download-ready',initial)
    for pid in live(): os.kill(pid,signal.SIGKILL)
    no_helpers(); time.sleep(3); assert version()==str(first)
    launch()
    discarded=wait_state(lambda s:s.get('phase')=='discarded' and 'Previously staged update discarded' in s.get('message',''))
    assert not list((data/'updates').glob('download-*')) and owned_processes()==live()
    assert version()==str(first)
    record('SIGKILL-ready-relaunch-discards-private-stage-no-helper-unchanged-build',discarded)
    ready(); record('clean-reoffer-after-interrupted-staging')
    # Missing dismissal acknowledgement: exercise the real 45-second deadline
    # while no installer is armed. This does not freeze the AppKit event loop.
    run(['defaults','write',domain,'QAStallUpdateDismiss','-bool','true'])
    time.sleep(.5)
    started=time.monotonic(); quit_app(); elapsed=time.monotonic()-started
    assert 44 <= elapsed < 55, elapsed
    timeout_state=phase_sequence('quit-deferring','quit-timeout')
    no_helpers(); assert version()==str(first)
    record('stalled-dismissal-quit-bounded-45-seconds',{'elapsed':elapsed,'ui':timeout_state})
    launch(); ready()
    notify('update-power-off')
    end=time.monotonic()+5
    while live() and time.monotonic()<end: time.sleep(.1)
    no_helpers(); assert version()==str(first)
    record('power-off-notification-does-not-block-termination')
    # Crash-safe cancellation recovery, including preservation of an older skip.
    (data/'updates/cancelled-release.json').write_text(json.dumps({'cancelledRelease':str(first+1),'skipBeforeCancellation':{'SUSkippedVersion':str(first-2)}}))
    run(['defaults','write',domain,'SUSkippedVersion',str(first+1)])
    launch(); initial=ready()
    recovered=plistlib.loads(subprocess.check_output(['defaults','export',domain,'-']))
    assert recovered.get('SUSkippedVersion')==str(first-2)
    assert not (data/'updates/cancelled-release.json').exists()
    record('persisted-cancellation-snapshot-restored-on-start')
    notify('update-later'); time.sleep(1); assert version()==str(first); record('later-does-not-install')
    notify('update-check'); wait_state(lambda s:s.get('phase')=='ready' and s.get('visible'))
    record('menu-check-reopens-postponed-update')
    notify('update-busy on'); notify('update-restart'); blocked=wait_state(lambda s:s.get('phase')=='busy')
    assert version()==str(first) and live(); record('busy-defers-restart',blocked)
    notify('update-busy off'); quit_app(); assert version()==str(first); record('ordinary-quit-does-not-install')
    saved=plistlib.loads(subprocess.check_output(['defaults','export',domain,'-']))
    assert saved.get('SUSkippedVersion') == str(first-2)
    launch(); wait_state(lambda s:s.get('phase')=='ready' and s.get('ready'),180)
    record('automatic-reoffer-after-ordinary-quit')
    notify('update-restart')
    installed_state=wait_state(lambda s:s.get('build')==str(first+1) and s.get('installedBundleBuild')==str(first+1),120)
    record('first-hop-replaced-and-relaunched',installed_state)
    # The installed successor must exercise its own updater, not a copied test app.
    notify('connect '+base+'/wizard/'); time.sleep(2)
    ns='{https://humanitylabs.co/wizard-updates/v1}'
    stage(first+2,add_delta)
    fail_without_replacement('delta-bearing-item-rejected-before-download','Delta updates are not supported',archive=False)
    stage(first+2,lambda item:item.remove(item.find(ns+'sha256')))
    fail_without_replacement('missing-SHA256-rejected','missing archive SHA-256',archive=False)
    stage(first+2,lambda item:setattr(item.find(ns+'sha256'),'text','0'*64))
    fail_without_replacement('validly-signed-wrong-SHA256-rejected','Archive SHA-256 or size mismatch')
    import base64
    stage(first+2,lambda item:item.find('enclosure').set('{http://www.andymatuschak.org/xml-namespaces/sparkle}edSignature',base64.b64encode(bytes(64)).decode()))
    fail_without_replacement('valid-SHA256-invalid-Ed25519-rejected','improperly signed',signature=True,install=True,outer_code=4005)
    stage(first+2)
    path=feed/'appcast.xml'
    signed=path.read_bytes(); assert b'Wizard ' in signed
    path.write_bytes(signed.replace(b'Wizard ',b'WizOrd ',1))
    fail_without_replacement('feed-edited-after-signing-rejected','improperly signed',archive=False,signature=True,outer_code=1000)
    stage(first+2,signing_key=wrong_key)
    fail_without_replacement('wrong-key-signed-feed-rejected','improperly signed',archive=False,signature=True,outer_code=1000)
    stage(first)
    count=len(requests); notify('update-check')
    current=wait_state(lambda s:s.get('phase')=='current')
    assert '/appcast.xml' in requests[count:] and not any(x.endswith('.zip') for x in requests[count:])
    assert version()==str(first+1) and not current.get('ready')
    record('signed-downgrade-not-offered',current)
    stage(first+2,lambda item:item.find('enclosure').set('length','1024'))
    fail_without_replacement('oversize-body-rejected','Archive exceeds signed size')
    stage(first+2,lambda item:item.find('enclosure').set('url',base+'/redirect.zip'))
    fail_without_replacement('302-to-http-redirect-rejected','Insecure update archive redirect refused')
    assert '/redirect-target.zip' not in requests
    stage(first+2)
    notify('update-no-space on')
    fail_without_replacement('free-space-precheck-fails-closed','free disk space',archive=False)
    notify('update-no-space off')
    stage(first+2)
    archive=feed/f'Wizard-{first+2}.zip'; original_bytes=archive.read_bytes()
    archive.write_bytes(b'not a signed update'+original_bytes[19:])
    fail_without_replacement('tampered-archive-rejected','Archive SHA-256 or size mismatch')
    archive.write_bytes(original_bytes); del original_bytes
    ready(); notify('update-restart')
    second=wait_state(lambda s:s.get('build')==str(first+2) and s.get('installedBundleBuild')==str(first+2),120)
    record('second-hop-successor-updater-replaced-and-relaunched',second)
    assert not list((data/'updates').glob('download-*')); record('verified-downloads-cleaned')
    record('guest-not-booted-or-rebuilt')
    passed = True
except Exception as error:
    (evidence/'failure.json').write_text(json.dumps({'pass':False,'error':str(error)},indent=2)+'\n'); raise
finally:
    # Do not lose the original failure behind a second ordinary-Quit assertion.
    # Kill owned processes before restoring defaults, even if notification fails.
    cleanup = None
    try:
        if preference_backup is not None:
            try:
                cleanup = cleanup_app()
                (evidence/'process-cleanup.json').write_text(json.dumps(cleanup, indent=2)+'\n')
            finally:
                # `defaults import` merges, so clear QA-written keys before restoring.
                subprocess.run(['defaults','delete','org.humanitylabs.wizard.mvp'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                if preference_backup:
                    backup=root/'restore.plist'; backup.write_bytes(preference_backup); run(['defaults','import','org.humanitylabs.wizard.mvp',backup])
                else: subprocess.run(['defaults','delete','org.humanitylabs.wizard.mvp'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                after=subprocess.run(['defaults','export','org.humanitylabs.wizard.mvp','-'],capture_output=True)
                assert (plistlib.loads(after.stdout) if after.returncode==0 else {}) == (plistlib.loads(preference_backup) if preference_backup else {}), 'Preferences did not restore'
                record('original-global-preferences-restored')
    finally:
        try:
            if server: server.shutdown()
            if runtime:
                shutil.copytree(data, root/'data', dirs_exist_ok=True, symlinks=True)
                if installed.exists(): shutil.copytree(installed, root/'installed/Wizard.app', dirs_exist_ok=True, symlinks=True)
        finally:
            if runtime: runtime.cleanup()
            for path in [root/'update-key',root/'wrong-update-key',root/'restore.plist',root/'preferences.plist',evidence/'preferences-before.plist']:
                path.unlink(missing_ok=True)
    if passed:
        assert cleanup is not None and not cleanup['signals'], 'Final Quit required forced process cleanup; see process-cleanup.json'
        record('no-owned-Wizard-process-remains')
        (evidence/'complete.json').write_text(json.dumps({'pass':True,'sourceIdentity':source_identity(source,a.source_head),'builds':list(builds),'checks':len(results),'publication':'none','DeveloperID':False,'guestCoverage':'not booted; app-only native update proof'},indent=2)+'\n')
