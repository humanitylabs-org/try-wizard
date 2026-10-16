#!/usr/bin/env python3
"""Bounded final307 continuation. Parent durable worker executes; NEVER publishes.
No VM/factory/native product build. Reuse exact signed candidate. Native tests
use no-VM data and real signed Sparkle replacement, with explicit evidence layers.
"""
import argparse
import hashlib
import http.server
import json
import os
from pathlib import Path
import plistlib
import shutil
import signal
import socket
import subprocess as sp
import sys
import threading
import time
import xml.etree.ElementTree as X

PRODUCTION = 'c7952d68e6a61da74b1e26485293cb7b5d881c7b'
DOMAIN = 'org.humanitylabs.wizard.mvp'
SPARKLE_NS = '{http://www.andymatuschak.org/xml-namespaces/sparkle}'


def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda: f.read(8*1024*1024), b''): h.update(b)
    return h.hexdigest()


def function(text, signature):
    start = text.index(signature); left = text.index('{', start); depth = 1; end = left+1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}'); end += 1
    return text[start:end]


def plist(p): return plistlib.loads(Path(p).read_bytes())
def read(p):
    try: return json.loads(Path(p).read_text())
    except (FileNotFoundError, json.JSONDecodeError): return {}


def run(argv, timeout=60, check=True, **kwargs):
    return sp.run(list(map(str, argv)), timeout=timeout, check=check, capture_output=True, **kwargs)


def public_inventory():
    data = run(['curl', '-fsS', '--connect-timeout', '10', '--max-time', '30',
                'https://downloads.aiwizards.com/mac/appcast.xml']).stdout
    root = X.fromstring(data)
    builds = [int(x.text or '') for x in root.findall('.//'+SPARKLE_NS+'version')]
    assert builds and max(builds) < 307, 'Build307 already public or superseded; do not reuse number'
    objects = {}
    for name in ['Wizard-307.zip', 'Wizard-0.7.0.dmg']:
        code = run(['curl', '-sS', '-I', '-o', '/dev/null', '-w', '%{http_code}',
                    '--connect-timeout', '10', '--max-time', '30',
                    'https://downloads.aiwizards.com/mac/307/'+name]).stdout.decode().strip()
        assert code == '404', (name, code, 'fail closed on non-404')
        objects[name] = code
    return {'feedSHA256': hashlib.sha256(data).hexdigest(), 'builds': builds, 'objects': objects}


def owned_processes(app):
    prefix = str(app) + '/Contents/'
    rows = []
    for row in run(['ps', '-axo', 'pid=,command='], text=True).stdout.splitlines():
        parts = row.strip().split(None, 1)
        if len(parts) == 2 and parts[1].startswith(prefix): rows.append((int(parts[0]), parts[1]))
    return rows


def mvp_processes():
    rows = []
    for row in run(['ps', '-axo', 'pid=,command='], text=True).stdout.splitlines():
        parts = row.strip().split(None, 1)
        if len(parts) != 2 or '.app/Contents/MacOS/' not in parts[1]: continue
        path = parts[1].split('.app/Contents/MacOS/', 1)[0] + '.app'
        try: identity = plist(Path(path)/'Contents/Info.plist').get('CFBundleIdentifier')
        except (OSError, ValueError): continue
        if identity in [DOMAIN, DOMAIN+'.host']: rows.append((int(parts[0]), parts[1]))
    return rows


def console():
    x = plistlib.loads(run(['ioreg', '-n', 'Root', '-d1', '-a']).stdout)
    x = x[0] if isinstance(x, list) else x
    return bool(x.get('IOConsoleLocked') or any(u.get('CGSSessionScreenIsLocked') for u in x.get('IOConsoleUsers', [])))


def notify(command):
    # Foundation distributed notifications; NOT Apple Events/System Events.
    code = 'ObjC.import("Foundation"); $.NSDistributedNotificationCenter.defaultCenter.postNotificationNameObjectUserInfoDeliverImmediately('+json.dumps(DOMAIN+'.qa')+','+json.dumps(command)+',null,true);'
    run(['osascript', '-l', 'JavaScript', '-e', code], timeout=10)


def wait(predicate, seconds, label):
    end = time.monotonic()+seconds
    while time.monotonic() < end:
        value = predicate()
        if value: return value
        time.sleep(.3)
    raise TimeoutError(label)


class Fixture(http.server.BaseHTTPRequestHandler):
    """Explicit loopback backend fixture; never proxy to real accounts/services."""
    commands = []; results = {}; root = Path('.')
    def log_message(self, format, *args): pass
    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == '/command':
            data = json.dumps(self.commands.pop(0) if self.commands else None).encode(); ct = 'application/json'
        elif path in ['/appcast.xml', '/Wizard-307.zip']:
            p = self.root/path[1:]; self.send_response(200); self.send_header('Content-Length', str(p.stat().st_size)); self.end_headers()
            try:
                with p.open('rb') as f: shutil.copyfileobj(f, self.wfile)
            except (BrokenPipeError, ConnectionResetError): pass
            return
        else:
            data = HTML.encode(); ct = 'text/html'
        self.send_response(200); self.send_header('Content-Type', ct); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_POST(self):
        size = int(self.headers.get('Content-Length', '0'))
        # Real recorder may upload audio; consume locally and discard, never persist it.
        body = self.rfile.read(size)
        if self.path == '/result':
            value = json.loads(body); self.results[value['id']] = value
        self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(b'{"ok":true}')


HTML = '''<!doctype html><meta charset="utf-8"><title>Private native307 acceptance fixture</title>
<p>Local protocol fixture — no production account or guest.</p><script>
window.__wux={voice:'idle'};
let running=false;
async function poll(){if(running)return;running=true;try{
 const c=await (await fetch('/command')).json(); if(c){let result;
 try {const m=window.wizardNative.meetings;
 if(c.op==='start') result=await m.start({meetingId:'native307-local-fixture',title:'Private local acceptance',includeSystemAudio:false});
 else if(c.op==='stop')result=await m.stop({finalize:false}); else result=await m[c.op]();
 }catch(e){result={error:String(e)}}
 await fetch('/result',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:c.id,result})});
 }}finally{running=false}}
setInterval(()=>poll().catch(()=>{}),250);
</script>'''


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--spec', required=True, type=Path)
    ap.add_argument('--preflight-only', action='store_true')
    a = ap.parse_args(); s = read(a.spec)
    source = Path(s['productionDir']); candidate = Path(s['candidateApp']); root = Path(s['evidenceRoot'])
    harness = Path(__file__).resolve().parents[4]
    assert s['productionSource'] == PRODUCTION
    assert run(['git','-C',source,'rev-parse','HEAD'], text=True).stdout.strip() == PRODUCTION
    assert run(['git','-C',harness,'rev-parse','HEAD'], text=True).stdout.strip() == s['harnessSource']
    assert not run(['git','-C',harness,'status','--porcelain'], text=True).stdout.strip()
    assert not run(['git','-C',source,'status','--porcelain'], text=True).stdout.strip()
    assert root.is_relative_to('/Volumes/ThalesMedia/') and os.uname().sysname == 'Darwin'
    info = plist(candidate/'Contents/Info.plist'); release = read(candidate/'Contents/Resources/wizard-release.json')
    assert info['CFBundleVersion'] == '307' and release['releaseID'] == PRODUCTION
    assert info['SUFeedURL'] == 'https://downloads.aiwizards.com/mac/appcast.xml' and info['SURequireSignedFeed'] is True
    assert sha(candidate/'Contents/MacOS/Wizard') == s['candidateAppSHA256']
    assert sha(candidate/'Contents/Library/LoginItems/Wizard Host.app/Contents/MacOS/Wizard Host') == s['candidateHostSHA256']
    accepted = read(s['headlessReport'])
    assert sha(s['headlessReport']) == s['headlessReportSHA256']
    assert accepted['success'] and accepted['cleanupVerified'] and len(accepted['gates']) == 17 and all(g['passed'] for g in accepted['gates'])
    inventory = public_inventory()
    if a.preflight_only:
        print(json.dumps({'preflightOnly':True,'candidate':str(candidate),'publicInventory':inventory,'nativeExecuted':False,'packaged':False})); return
    assert os.environ.get('WIZARD_HEAVY_JOB_ID') or s.get('workerLease') == 'inherited', 'Parent durable worker only'
    # Native tests never start a VM. One bounded fixture compile; no product compile.
    assert not root.exists(), 'Use an immutable fresh evidence root'
    root.mkdir(parents=True, mode=0o700)
    os.environ.update(TMPDIR='/Volumes/ThalesMedia/tmp', CLANG_MODULE_CACHE_PATH=str(root/'module-cache'), PYTHONDONTWRITEBYTECODE='1')
    foreign_before = run(['ps','-p','78546','-o','command='],check=False,text=True).stdout.strip()
    r = {'foreign78546Before':foreign_before,'productionSource':PRODUCTION,'harnessSource':s['harnessSource'],'candidateApp':str(candidate),
         'headlessReportReused':s['headlessReport'],'headlessReportSHA256':s['headlessReportSHA256'],
         'realMigrationRepeated':False,'nativeProductRecompiled':False,'factoryRebuilt':False,'published':False,
         'consoleBefore':console(),'gates':{},'publicInventory':inventory,'readyForPublication':False,
         'physicalSpeechQuality':'not claimed','launchServicesHostAcceptance':'not retried: known locked-console external-file stall'}
    def save(): (root/'result.json').write_text(json.dumps(r, indent=2)+'\n')
    def gate(name, f):
        try: r['gates'][name] = {'passed':True,'evidence':f()}
        except Exception as ex:
            r['gates'][name] = {'passed':False,'error':repr(ex)}
            if name.startswith('exact307-'):
                for pid,cmd in owned_processes(Path(s['testApp'])):
                    sample=run(['sample',str(pid),'2','-file',root/(name+'-'+str(pid)+'.sample.txt')],timeout=10,check=False)
                (root/(name+'-processes.txt')).write_text(run(['ps','-axo','pid=,command='],text=True).stdout)
        save()
    def logged(name, argv, timeout=180):
        p = run(argv, timeout=timeout, check=False)
        (root/(name+'.log')).write_bytes(p.stdout+p.stderr)
        assert p.returncode == 0, (name,p.returncode)
        return {'logSHA256':sha(root/(name+'.log'))}
    save()
    gate('candidate-signature', lambda: logged('candidate-signature',['codesign','--verify','--deep','--strict',candidate]))
    mac = source/'next/mac'; fixture = root/'policy'
    def appkit_policy():
        text = (mac/'App/main.swift').read_text()
        ipc = function(text, 'static func send(_ command: String)')
        (root/'main.swift').write_text('import Foundation\nimport AppKit\nenum ProductionHostIPC {\n'+ipc+'\n}\nif CommandLine.arguments.count > 2 && CommandLine.arguments[2] == "host-command" { ProductionHostIPC.send(CommandLine.arguments[3]) } else { MainActor.assumeIsolated { exercise() } }\n')
        logged('compile-policy',['xcrun','swiftc','-swift-version','5','-target','arm64-apple-macos14.0',
               mac/'App/WizardUpdater.swift',Path(__file__).with_name('fixture.swift'),root/'main.swift',
               '-F',s['sparkle'],'-framework','Sparkle','-framework','AppKit','-Xlinker','-rpath','-Xlinker',s['sparkle'],'-o',fixture],240)
        proof = logged('appkit-policy',[fixture,root/'policy-data'],40)
        proof.update(productionUpdaterSHA256=sha(mac/'App/WizardUpdater.swift'),hostSendSHA256=hashlib.sha256(ipc.encode()).hexdigest(),
                     layer='Entire unchanged production updater + real NSAlert/NSButton; explicit state adapters; NOT physical capture or installed App')
        return proof
    gate('production-AppKit-policy',appkit_policy)
    stage = root/'public-mac307'; package_app = root/'package/Wizard MVP.app'
    def package():
        assert r['gates']['candidate-signature']['passed']
        package_app.parent.mkdir(); run(['cp','-cR',candidate,package_app],timeout=90)
        stage.mkdir()
        logged('feed-package',[s['python'],mac/'tools/make-update-feed.py',package_app,stage,'--base-url',
               'https://downloads.aiwizards.com/mac/307/','--sign-tool',s['signTool'],'--key-file',s['keyFile']],900)
        for p in stage.glob('receipt-*'): p.rename(root/p.name)
        dmg_source = root/'dmg-source'; dmg_source.mkdir()
        run(['cp','-cR',package_app,dmg_source/'Wizard MVP.app'],timeout=90)
        (dmg_source/'Applications').symlink_to('/Applications')
        logged('dmg-create',['hdiutil','create','-quiet','-volname','Wizard','-srcfolder',dmg_source,'-fs','HFS+','-format','UDZO',stage/'Wizard-0.7.0.dmg'],900)
        logged('dmg-verify',['hdiutil','verify',stage/'Wizard-0.7.0.dmg'],180)
        mount = root/'mounted-dmg'; mount.mkdir()
        attached = False
        try:
            run(['hdiutil','attach','-readonly','-nobrowse','-mountpoint',mount,stage/'Wizard-0.7.0.dmg'],timeout=90); attached=True
            logged('mounted-signature',['codesign','--verify','--deep','--strict',mount/'Wizard MVP.app'])
            for rel in ['Contents/MacOS/Wizard','Contents/Library/LoginItems/Wizard Host.app/Contents/MacOS/Wizard Host','Contents/Resources/wizard-release.json']:
                assert sha(mount/'Wizard MVP.app'/rel) == sha(candidate/rel)
        finally:
            if attached: run(['hdiutil','detach',mount],timeout=60)
        assert sorted(p.name for p in stage.iterdir()) == ['Wizard-0.7.0.dmg','Wizard-307.zip','appcast.xml']
        files = {p.name:{'sha256':sha(p),'bytes':p.stat().st_size} for p in stage.iterdir()}
        return {'stage':str(stage),'files':files,'publication':False,'appleSigning':'ad-hoc, not Developer ID or notarized',
                'publisherContract':'flat directory: ZIP + DMG + appcast only; publisher adds mac/307/'}
    gate('release-packaging',package)
    app = Path(s['testApp']); data = root/'native-data'; server = None; before = None; restored = False
    assert app.parent == Path('/Applications') and not app.exists() and app != candidate
    def props():
        p = run(['defaults','export',DOMAIN,'-'],check=False)
        return plistlib.loads(p.stdout) if p.returncode == 0 else None
    def apply(values):
        p = root/'native-prefs.plist'; p.write_bytes(plistlib.dumps(values)); p.chmod(0o600)
        run(['defaults','import',DOMAIN,p])
        actual = props(); assert actual is not None and all(actual.get(k) == v for k,v in values.items())
    def stop_owned():
        for pid,cmd in owned_processes(app):
            # No VM is ever present in either native-data or host-data.
            assert '/Contents/MacOS/' in cmd
            os.kill(pid,signal.SIGTERM)
        wait(lambda:not owned_processes(app),15,'owned no-VM process termination')
    def launch():
        assert not owned_processes(app)
        with (root/'native-app.log').open('ab') as f:
            p = sp.Popen([str(app/'Contents/MacOS/Wizard')],stdout=f,stderr=sp.STDOUT)
        return p.pid
    def state():
        notify('update-state'); return read(data/'updates/qa.json')
    def native():
        nonlocal server,before
        assert r['gates']['release-packaging']['passed']
        assert not mvp_processes(), 'Another MVP owns the common preferences/QA domain; do not alter it'
        before = props(); (root/'prefs-before.plist').write_bytes(plistlib.dumps(before or {})); (root/'prefs-before.plist').chmod(0o600)
        assert not owned_processes(app)
        for port in [s['port'],48000,48023,48030]:
            with socket.socket() as sock: sock.bind(('127.0.0.1',port))
        private = root/'private-feed'; private.mkdir()
        run(['cp','-c',stage/'Wizard-307.zip',private/'Wizard-307.zip'])
        # Same signed ZIP, separately signed loopback appcast; public appcast never altered.
        tree = X.parse(stage/'appcast.xml'); enclosure = tree.find('./channel/item/enclosure')
        assert enclosure is not None
        enclosure.set('url',f'http://127.0.0.1:{s["port"]}/Wizard-307.zip')
        X.register_namespace('sparkle',SPARKLE_NS[1:-1]); X.register_namespace('wizard','https://humanitylabs.co/wizard-updates/v1')
        tree.write(private/'appcast.xml',encoding='utf-8',xml_declaration=True)
        logged('private-feed-sign',[s['signTool'],'--ed-key-file',s['keyFile'],private/'appcast.xml'])
        logged('private-feed-verify',[s['signTool'],'--ed-key-file',s['keyFile'],'--verify',private/'appcast.xml'])
        Fixture.root = private; Fixture.commands=[]; Fixture.results={}
        server = http.server.ThreadingHTTPServer(('127.0.0.1',s['port']),Fixture)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever,daemon=True).start()
        data.mkdir(); (data/'Files').mkdir(); (data/'files-folder.json').write_text(json.dumps({'path':str(data/'Files')}))
        origin = f'http://127.0.0.1:{s["port"]}/'
        config = dict(before or {})
        config.update(DataHome=str(data),QAHooks=True,QAWebStorage=True,WizardKeyEnabled=False,VoiceKeysEnabled=False,
                      backends=json.dumps([{'kind':'remote','name':'Native307 private fixture','url':origin},
                                           {'kind':'thisMac','name':'Consent-only no-VM fixture','url':''}]).encode(),
                      activeBackend=0,SUFeedURL=origin+'appcast.xml',SUEnableAutomaticChecks=False,SUSkippedVersion='')
        apply(config)
        run(['cp','-cR',s['publicApp'],app],timeout=90)
        old_pid = launch(); wait(lambda:state().get('pid') == old_pid,30,'direct App306 entry')
        notify('update-check')
        ready = wait(lambda:(q if (q:=state()).get('phase') == 'ready' else False),180,'signed exact307 archive ready')
        assert ready['build']=='306'
        notify('update-busy on'); notify('update-restart')
        wait(lambda:state().get('phase')=='busy',10,'306 old ready synthetic busy check')
        notify('update-busy off'); notify('update-restart')
        new = wait(lambda:(q if (q:=state()).get('build')=='307' and q.get('pid') != old_pid and q.get('installedBundleBuild')=='307' else False),180,'actual packaged307 replacement AND Sparkle relaunch')
        assert read(app/'Contents/Resources/wizard-release.json')['releaseID']==PRODUCTION
        assert sha(app/'Contents/MacOS/Wizard')==s['candidateAppSHA256']
        assert read(data/'updates/transaction.json').get('phase')=='native-activated'
        r['gates']['packaged-self-update']={'passed':True,'evidence':{'state':new,'archiveSHA256':sha(private/'Wizard-307.zip'),
            'scope':'real Sparkle306→307 replacement/relaunch; no-VM remote loopback backend; initial306 direct worker launch; not LaunchServices Host'}}; save()
        def command(op):
            key=op+'-'+str(time.time_ns()); Fixture.commands.append({'id':key,'op':op})
            return wait(lambda:Fixture.results.get(key),40,'real native recorder '+op)['result']
        try:
            capture={'start':command('start')}
            assert capture['start'].get('recording') is True, capture
            assert state().get('recording') is True
            # A tiny deliberately unauthenticated legacy fixture can never boot.
            (data/'os/boot').mkdir(parents=True)
            for path in ['disk.img','boot/vmlinux','boot/initrd']: (data/'os'/path).write_bytes(b'NOT_A_VM_FINAL307_CONSENT_ONLY\n')
            (data/'os/manifest.json').write_text('{"version":"0.3.0"}')
            notify('switch 1')
            capture['legacyRefusal']=wait(lambda:(q if (q:=state()).get('phase')=='busy' and q.get('recording') else False),10,'exact307 real recording legacy admission refusal')
            assert not (data/'updates/legacy-pre-upgrade.img').exists() and not (data/'updates/maintenance.json').exists()
            capture['pause']=command('pause'); capture['resume']=command('resume')
            assert capture['pause']['paused'] is True and capture['resume']['paused'] is False
            capture['stop']=command('stop'); wait(lambda:state().get('recording') is False,15,'capture stop')
            r['gates']['exact307-native-capture']={'passed':True,'evidence':capture,'scope':'real native capture lifecycle to local discard fixture, no speech-quality claim'};save()
        except Exception as ex:
            r['gates']['exact307-native-capture']={'passed':False,'error':repr(ex)};save()
            # Do not click unknown TCC dialogs or repeat failed capture transports.
            stop_owned()
        # Exact installed app entry consent: safe dummy disk, Not now and authenticated rejection only.
        stop_owned(); config['activeBackend']=1; apply(config)
        if not (data/'os/boot').exists():
            (data/'os/boot').mkdir(parents=True)
            for path in ['disk.img','boot/vmlinux','boot/initrd']: (data/'os'/path).write_bytes(b'NOT_A_VM_FINAL307_CONSENT_ONLY\n')
            (data/'os/manifest.json').write_text('{"version":"0.3.0"}')
        disk_before=sha(data/'os/disk.img'); pid=launch()
        # Exactly one bounded AX traversal per observed phase, never loginwindow.
        time.sleep(2)
        logged('exact307-not-now',[s['python'],harness/'next/mac/Tests/ax_press_button.py',str(pid),'Not now'],15)
        deferred=wait(lambda:(q if (q:=state()).get('phase')=='deferred' else False),10,'exact307 native consent deferred')
        assert sha(data/'os/disk.img')==disk_before
        notify('switch 1'); time.sleep(1)
        logged('exact307-confirm',[s['python'],harness/'next/mac/Tests/ax_press_button.py',str(pid),'Upgrade existing Wizard'],15)
        denied=wait(lambda:(q if (q:=state()).get('phase')=='failed' else False),10,'exact307 authenticated unknown boot rejection')
        assert 'Unknown legacy boot files' in denied['message'] and sha(data/'os/disk.img')==disk_before
        assert not owned_processes(app/'Contents/Library/LoginItems/Wizard Host.app')
        stop_owned()
        return {'deferred':deferred,'confirmRejectedUnknownBoot':denied,'dummyDiskUnchanged':True,
                'scope':'exact307 App direct worker launch, real AX button actions on dummy disk; no physical mouse or real migration'}
    gate('exact307-native-entry',native)
    # Separate direct Host + production DNC message. No repeated NSWorkspace transport.
    def host_ipc():
        assert fixture.exists() and app.exists() and not owned_processes(app)
        assert plist(app/'Contents/Info.plist')['CFBundleVersion']=='307'
        assert not mvp_processes()
        d=root/'host-data'; d.mkdir(); (d/'Files').mkdir(); (d/'files-folder.json').write_text(json.dumps({'path':str(d/'Files')}))
        binary=app/'Contents/Library/LoginItems/Wizard Host.app/Contents/MacOS/Wizard Host'
        with (root/'host.log').open('ab') as log: child=sp.Popen([str(binary),'--wizard-data-home',str(d)],stdout=log,stderr=sp.STDOUT)
        try:
            status=wait(lambda:(v if (v:=read(d/'host-status.json')).get('state')=='notInstalled' and v.get('pid')==child.pid else False),25,'direct exact307 Host no-VM status')
            assert status['dataHome']==str(d) and status['build']=='307'
            logged('exact307-host-ipc',[fixture,root/'policy-data','host-command','quit'],10)
            child.wait(timeout=20)
            return {'status':status,'exitCode':child.returncode,'transport':'exact production HostControl.send body → actual Host command handler','launch':'direct inherited worker chain, NOT production NSWorkspace launch'}
        finally:
            if child.poll() is None: child.terminate(); child.wait(timeout=10)
    # Do not attempt a Host while a failed native entry is still live.
    try: stop_owned()
    except Exception as ex: r['cleanupError']=repr(ex)
    gate('exact307-direct-Host-IPC',host_ipc)
    try:
        stop_owned()
        if before is not None:
            actual=props() or {}
            for key in set(actual)-set(before): run(['defaults','delete',DOMAIN,key],check=False)
            run(['defaults','import',DOMAIN,root/'prefs-before.plist'])
            restored=props()==before
        elif (root/'prefs-before.plist').exists():
            run(['defaults','delete',DOMAIN],check=False); restored=props() is None
        else: restored=True # Native work refused before touching defaults.
        assert restored and not owned_processes(app)
        r['cleanupVerified']=True
    except Exception as ex: r['cleanupVerified']=False;r['cleanupError']=repr(ex)
    finally:
        if server: server.shutdown();server.server_close()
        r['consoleAfter']=console();r['preferencesRestored']=restored
        r['foreign78546After']=run(['ps','-p','78546','-o','command='],check=False,text=True).stdout.strip()
        r['foreign78546Unchanged']=r['foreign78546After']==foreign_before
        if not r['foreign78546Unchanged']: r['cleanupVerified']=False
        # Gate remains explicit even if this entire bounded continuation passes.
        r['remainingAcceptance']=['Exact production NSWorkspace App→Host external-volume launch is NOT certified by direct inherited Host IPC. Prior locked-console transport was not retried.']
        r['readyForPublication']=False
        save()
    print(json.dumps({'result':str(root/'result.json'),'gates':{k:v['passed'] for k,v in r['gates'].items()},'published':False,'readyForPublication':False}))
    if not r.get('cleanupVerified') or not all(x['passed'] for x in r['gates'].values()): raise SystemExit(1)


if __name__ == '__main__': main()
