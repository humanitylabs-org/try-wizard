#!/usr/bin/env python3
"""Thales-only, disposable native updater proof. Never publishes or boots a VM.
Builds three ad-hoc Apple-signed apps with an ephemeral Ed25519 update key,
then drives the real AppKit/Sparkle path 18001 -> 18002 -> 18003.
"""
import argparse, functools, hashlib, http.server, json, os, pathlib, plistlib, shutil, subprocess, threading, time

p = argparse.ArgumentParser()
p.add_argument('--root', required=True, type=pathlib.Path)
p.add_argument('--sparkle', required=True, type=pathlib.Path)
p.add_argument('--first-build', type=int, default=18001)
a = p.parse_args(); root = a.root.resolve(); source = pathlib.Path(__file__).resolve().parents[1]
root.mkdir(parents=True, exist_ok=True)
evidence = root/'evidence'; evidence.mkdir(exist_ok=True)
feed = root/'feed'; feed.mkdir(exist_ok=True)
data = root/'data'; data.mkdir(exist_ok=True)
installed = root/'installed/Wizard.app'; installed.parent.mkdir(exist_ok=True)
builds=list(range(a.first_build,a.first_build+3))
results = []; requests = []; server = None; preference_backup = None; passed = False

def run(argv, **kw): return subprocess.run(list(map(str, argv)), check=True, **kw)
def record(name, detail=None):
    results.append({'name': name, 'pass': True, 'detail': detail})
    (evidence/'results.json').write_text(json.dumps(results, indent=2)+'\n')
    print('PASS', name, flush=True)
def version(): return plistlib.loads((installed/'Contents/Info.plist').read_bytes())['CFBundleVersion']
def live():
    r = subprocess.run(['pgrep', '-f', str(installed/'Contents/MacOS/Wizard')], capture_output=True, text=True)
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
        notify('update-quit'); end=time.time()+20
        while live() and time.time()<end: time.sleep(.25)
        assert not live(), 'Ordinary Quit did not terminate owned app'
def launch():
    run(['open','-n','-a',installed,'--args','--wizard-data-home',data])
    wait_state(lambda s: s.get('build') == version())
    notify('connect '+base+'/wizard/')
    time.sleep(2)
def stage(build, mutate=None):
    run(['python3',source/'tools/make-update-feed.py',root/f'build-{build}/Wizard.app',feed,
         '--base-url',base,'--sign-tool',signer,'--key-file',key], stdout=subprocess.DEVNULL)
    if mutate:
        import xml.etree.ElementTree as X
        X.register_namespace('sparkle','http://www.andymatuschak.org/xml-namespaces/sparkle')
        X.register_namespace('wizard','https://humanitylabs.co/wizard-updates/v1')
        path=feed/'appcast.xml'; tree=X.parse(path); item=tree.find('./channel/item')
        mutate(item); tree.write(path,encoding='utf-8',xml_declaration=True)
        run([signer,'--ed-key-file',key,path],stdout=subprocess.DEVNULL)

def ready():
    notify('update-check')
    return wait_state(lambda s: s.get('phase')=='ready' and s.get('ready'),180)
def fail_without_replacement(name, message, archive=True):
    before=version(); request_count=len(requests); notify('update-check')
    end=time.time()+90
    while time.time()<end:
        seen=requests[request_count:]
        if '/appcast.xml' in seen and (not archive or any(x.endswith('.zip') for x in seen)): break
        time.sleep(.1)
    else: raise AssertionError('Negative case never reached its feed/archive: '+name)
    s=wait_state(lambda s:s.get('phase')=='failed' and message in s.get('message',''),90)
    assert not s.get('ready') and version()==before
    record(name,s)

try:
    # Never interfere with another app/Host or another QA session's global defaults.
    existing=subprocess.run(['pgrep','-x','Wizard|Wizard Host'],capture_output=True,text=True)
    assert existing.returncode != 0, 'Another native Wizard app/Host is active; retry after its owner finishes'
    mappings=subprocess.check_output(['/usr/bin/hidutil','property','--get','UserKeyMapping'],text=True)
    assert 'HIDKeyboardModifierMappingSrc' not in mappings, 'Existing keyboard remapping belongs to another owner; not running native QA'
    key=root/'update-key'; signer=a.sparkle/'bin/sign_update'
    # Exporting a dedicated keychain item could touch the production signer. Use a
    # fresh CryptoKit key instead, in sign_update's documented private+public format.
    generator=root/'key.swift'
    generator.write_text('import Foundation\nimport CryptoKit\nlet k=Curve25519.Signing.PrivateKey(); let d=k.rawRepresentation+k.publicKey.rawRepresentation\ntry d.base64EncodedString().write(toFile:CommandLine.arguments[1],atomically:true,encoding:.utf8)\nprint(k.publicKey.rawRepresentation.base64EncodedString())\n')
    public=subprocess.check_output(['swift',generator,key],text=True).strip()
    os.chmod(key,0o600)
    run(['swiftc',source/'tools/update-qa-notify.swift','-o',root/'notify'])
    env=os.environ|{'SPARKLE_DIR':str(a.sparkle),'WIZARD_UPDATE_PUBLIC_KEY':public,
                    'WIZARD_FEED_URL':'http://127.0.0.1:1/appcast.xml'}
    for build in builds:
        with (evidence/f'build-{build}.log').open('w') as log:
            run(['bash',source/'build.sh',root/f'build-{build}'],env=env|{'WIZARD_BUILD':str(build),'WIZARD_VERSION':f'0.7.1-qa.{build}'},stdout=log,stderr=subprocess.STDOUT)
    for build in builds:
        bundle=root/f'build-{build}/Wizard.app'
        run(['codesign','--verify','--deep','--strict',bundle])
        info=subprocess.run(['codesign','-d','--verbose=4',bundle],capture_output=True,text=True,check=True).stderr
        assert 'Signature=adhoc' in info, info
        metadata=plistlib.loads((bundle/'Contents/Info.plist').read_bytes())
        assert metadata['SURequireSignedFeed'] and metadata['SUVerifyUpdateBeforeExtraction'] and metadata['SUPublicEDKey']==public
        (evidence/f'signing-{build}.txt').write_text(info)
    record('three-native-builds-ad-hoc-no-Developer-ID-signed-feed-required',list(builds))
    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path.split('?',1)[0])
            if self.path.startswith('/wizard'):
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
    prefs={'QAHooks':True,'QAWebStorage':True,'wizardDataHome':str(data),'SUFeedURL':base+'/appcast.xml',
           'SUEnableAutomaticChecks':True,'SUAutomaticallyUpdate':False,'SUHasLaunchedBefore':True,
           'SUValidateBeforeExtraction':True,'backends':b'[]','activeBackend':0,'filesFolder':str(root/'files'),
           'SUEnableSystemProfiling':False,'wizardKeyEnabled':False,'MeetingPrompts':False,'VoiceKeys':False}
    pref=root/'preferences.plist'; pref.write_bytes(plistlib.dumps(prefs)); run(['defaults','import',domain,pref])
    first=a.first_build
    stage(first+1)
    run(['ditto',root/f'build-{first}/Wizard.app',installed])
    launch(); initial=ready(); record('real-Sparkle-signed-feed-SHA256-download-ready',initial)
    notify('update-later'); time.sleep(1); assert version()==str(first); record('later-does-not-install')
    notify('update-check'); wait_state(lambda s:s.get('phase')=='ready' and s.get('visible'))
    record('menu-check-reopens-postponed-update')
    notify('update-busy on'); notify('update-restart'); blocked=wait_state(lambda s:s.get('phase')=='busy')
    assert version()==str(first) and live(); record('busy-defers-restart',blocked)
    notify('update-busy off'); quit_app(); assert version()==str(first); record('ordinary-quit-does-not-install')
    saved=plistlib.loads(subprocess.check_output(['defaults','export',domain,'-']))
    assert saved.get('SUSkippedVersion') != str(first+1)
    launch(); wait_state(lambda s:s.get('phase')=='ready' and s.get('ready'),180)
    record('automatic-reoffer-after-ordinary-quit')
    notify('update-restart')
    installed_state=wait_state(lambda s:s.get('build')==str(first+1) and s.get('installedBundleBuild')==str(first+1),120)
    record('first-hop-replaced-and-relaunched',installed_state)
    # The installed successor must exercise its own updater, not a copied test app.
    notify('connect '+base+'/wizard/'); time.sleep(2)
    ns='{https://humanitylabs.co/wizard-updates/v1}'
    stage(first+2,lambda item:item.remove(item.find(ns+'sha256')))
    fail_without_replacement('missing-SHA256-rejected','missing archive SHA-256',archive=False)
    stage(first+2,lambda item:setattr(item.find(ns+'sha256'),'text','0'*64))
    fail_without_replacement('validly-signed-wrong-SHA256-rejected','Archive SHA-256 or size mismatch')
    import base64
    stage(first+2,lambda item:item.find('enclosure').set('{http://www.andymatuschak.org/xml-namespaces/sparkle}edSignature',base64.b64encode(bytes(64)).decode()))
    fail_without_replacement('valid-SHA256-invalid-Ed25519-rejected','validation failed')
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
    if preference_backup is not None:
        try: quit_app()
        finally:
            if preference_backup:
                backup=root/'restore.plist'; backup.write_bytes(preference_backup); run(['defaults','import','org.humanitylabs.wizard.mvp',backup])
            else: subprocess.run(['defaults','delete','org.humanitylabs.wizard.mvp'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            after=subprocess.run(['defaults','export','org.humanitylabs.wizard.mvp','-'],capture_output=True)
            assert (plistlib.loads(after.stdout) if after.returncode==0 else {}) == (plistlib.loads(preference_backup) if preference_backup else {}), 'Preferences did not restore'
            record('original-global-preferences-restored')
    if server: server.shutdown()
    if passed:
        (evidence/'complete.json').write_text(json.dumps({'pass':True,'builds':list(builds),'checks':len(results),'publication':'none','DeveloperID':False,'guestCoverage':'not booted; app-only native update proof'},indent=2)+'\n')
