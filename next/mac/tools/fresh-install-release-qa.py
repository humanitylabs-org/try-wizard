#!/usr/bin/env python3
"""Fresh-install acceptance for the unmodified, non-QA release app on Thales.
No broad pkill, no real DataHome deletion. Temporarily overlay preferences only
while no Wizard is running, then restore the exact prior persistent domain.
All OS bytes must be fetched by production OSInstaller from a loopback p2 feed.
"""
import argparse
import functools
import hashlib
import http.server
import json
import os
from pathlib import Path
import plistlib
import signal
import socket
import subprocess
import threading
import time
import urllib.request
import uuid

DOMAIN = 'org.humanitylabs.wizard.mvp'
HOST = DOMAIN + '.host'


def run(*argv, **kw):
    return subprocess.run([str(a) for a in argv], check=True, text=True, capture_output=True, timeout=120, **kw).stdout


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for b in iter(lambda: stream.read(8 << 20), b''):
            h.update(b)
    return h.hexdigest()


def preferences():
    p = subprocess.run(['/usr/bin/defaults','export',DOMAIN,'-'],capture_output=True,timeout=30)
    if p.returncode:
        assert b'does not exist' in p.stderr or b'not found' in p.stderr, p.stderr.decode()
        return None
    return plistlib.loads(p.stdout)


def preanswer_files_folder(data, files):
    """Match WizardShared.setFilesFolder; this is not native Finder consent proof."""
    files.mkdir()
    target=data/'files-folder.json'
    temporary=data/'files-folder.json.tmp'
    temporary.write_text(json.dumps({'path':str(files)},indent=2))
    temporary.replace(target)
    assert json.loads(target.read_text())=={'path':str(files)}
    return {'filesFolderPromptPreAnswered':True,'filesFolder':str(files),
            'finalAppFinderConsentProven':False}


def isolated_overlay(original, data, feed_url):
    # Match Backend: Codable (kind/name/url), Store.activeIndex is an integer.
    # An extra UUID cannot replace the required url: decoding fails to [] and
    # leaves the final app at the backend chooser without ever fetching a feed.
    overlay=dict(original or {})
    overlay.update(DataHome=str(data),osFeedURL=feed_url,QAHooks=False,WizardKeyEnabled=False,
                   WizardKeyUseGlobal=False,ShowMenuBarIcon=False,SUEnableAutomaticChecks=False,
                   SUAutomaticallyUpdate=False,activeBackend=0,
                   backends=json.dumps([{'name':'This Mac','kind':'thisMac',
                                         'url':'http://127.0.0.1:48030/'}]).encode())
    return overlay


def restore_preferences(original, backup):
    # defaults import MERGES; remove all temporary/Sparkle keys before import.
    run('/usr/bin/defaults','delete',DOMAIN)
    if original is not None:run('/usr/bin/defaults','import',DOMAIN,backup)
    assert preferences()==original,'Preference restore mismatch: preserved backup at '+str(backup)


def process_rows():
    result=[]
    for line in run('/bin/ps','-axo','pid=,command=').splitlines():
        parts=line.strip().split(None,1)
        if len(parts)==2: result.append((int(parts[0]),parts[1]))
    return result


def owned_hosts(app, data):
    executable=str(app/'Contents/Library/LoginItems/Wizard Host.app/Contents/MacOS/Wizard Host')
    return [pid for pid,cmd in process_rows() if cmd == executable+' --wizard-data-home '+str(data)]


def shell(command, timeout=120):
    token = 'WIZARD_QA_EXIT_'+uuid.uuid4().hex
    with socket.create_connection(('127.0.0.1',48000),timeout=timeout) as s:
        s.settimeout(timeout)
        wrapped='{\n'+command+'\n}; rc=$?; printf "\\n'+token+':%s\\n" "$rc"\nexit\n'
        s.sendall(wrapped.encode()); chunks=[]
        while True:
            b=s.recv(65536)
            if not b: break
            chunks.append(b)
    out=b''.join(chunks).decode(errors='replace')
    assert token+':0' in out, out
    return out


def bounded_wait(predicate, seconds, label):
    end=time.monotonic()+seconds
    last='not ready'
    while time.monotonic()<end:
        try:
            value=predicate()
            if value: return value
        except (OSError, ValueError, AssertionError) as e:
            last=str(e)
        time.sleep(2)
    raise AssertionError(label+' timed out: '+last)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--app',type=Path,required=True)
    p.add_argument('--public-flat-os',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--work-root',type=Path,required=True)
    p.add_argument('--allow-temporary-preferences-overlay',action='store_true',required=True)
    a=p.parse_args(); app=a.app.resolve(); out=a.output.resolve(); flat=a.public_flat_os.resolve()
    assert not out.exists(), 'One-shot fresh evidence directory required'
    assert out.is_relative_to(a.work_root.resolve()) and out != a.work_root.resolve() and out != Path.home(), out
    info=plistlib.loads((app/'Contents/Info.plist').read_bytes())
    release=json.loads((app/'Contents/Resources/wizard-release.json').read_text())
    assert info['CFBundleVersion']=='309' and info['CFBundleShortVersionString']=='0.7.2'
    assert not info.get('WizardUpdateQA') and not release.get('qa')
    run('/usr/bin/codesign','--verify','--deep','--strict',app)
    # Refuse contention rather than stopping any existing user's application/VM.
    foreign=[(pid,cmd) for pid,cmd in process_rows() if '/Contents/MacOS/Wizard' in cmd and not cmd.startswith(('/bin/','/usr/bin/','/opt/'))]
    assert not foreign, 'Close existing Wizard/Host applications yourself; no process will be killed: '+repr(foreign)
    for port in (48000,48023,48030):
        with socket.socket() as sock: sock.bind(('127.0.0.1',port))
    feed=json.loads((flat/'latest.json').read_text()); assert feed['version']=='0.5.0'
    requests=[]
    # Serve only the exact already-verified artifacts, with a distinct p2 feed path.
    out.mkdir(parents=True,mode=0o700); os.chmod(out,0o700)
    www=out/'www'; (www/'os/p2').mkdir(parents=True)
    for part in feed['parts']:
        name=Path(part['url']).name
        assert name==part['url'] or part['url'].endswith('/'+name)
        src=flat/name; assert src.is_file() and digest(src)==part['sha256'], name
        os.symlink(src,www/name)
        part['url']='/'+name
    (www/'os/p2/latest.json').write_text(json.dumps(feed))
    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format, *args): pass
        def do_GET(self):
            assert self.client_address[0]=='127.0.0.1'
            requests.append({'path':self.path,'at':time.time()})
            super().do_GET()
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(www)))
    server.daemon_threads=True
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    feed_url='http://127.0.0.1:'+str(server.server_port)+'/os/p2/latest.json'
    data=out/'data'; assert not data.exists(); data.mkdir()
    (out/'fresh-before.json').write_text(json.dumps({'dataHome':str(data),'entries':list(data.iterdir()),'feedURL':feed_url},default=str))
    # Config is the only preseed. No disk, manifest, receipt or onboarding identity.
    setup=preanswer_files_folder(data,out/'files')
    (out/'preanswered-prompts.json').write_text(json.dumps(setup,indent=2))
    (data/'dev-shell').touch()
    original=preferences()
    real_home=Path((original or {}).get('DataHome',Path.home()/'Library/Application Support/Wizard MVP')).resolve()
    assert not data.is_relative_to(real_home) and not real_home.is_relative_to(data)
    def real_state():
        result={}
        for name in ('os/disk.img','os/manifest.json','files-folder.json','host-status.json'):
            path=real_home/name
            if path.exists():
                s=path.stat(); result[name]={'inode':s.st_ino,'bytes':s.st_size,'mtimeNS':s.st_mtime_ns}
        return result
    before=real_state()
    (out/'real-state-before.json').write_text(json.dumps(before,indent=2))
    backup=out/'original-preferences.plist'
    backup.write_bytes(plistlib.dumps(original or {}));os.chmod(backup,0o600)
    overlay=isolated_overlay(original,data,feed_url)
    testprefs=out/'isolated-preferences.plist';testprefs.write_bytes(plistlib.dumps(overlay));os.chmod(testprefs,0o600)
    # A tiny AppKit tool terminates ONLY a verified PID/executable pair gracefully.
    helper=out/'terminate.swift';helper.write_text('''import AppKit
let pid=pid_t(CommandLine.arguments[1])!
let expected=URL(fileURLWithPath:CommandLine.arguments[2]).resolvingSymlinksInPath()
guard let app=NSRunningApplication(processIdentifier:pid), app.executableURL?.resolvingSymlinksInPath()==expected else { exit(2) }
exit(app.terminate() ? 0 : 3)
''')
    run('/usr/bin/xcrun','swiftc',helper,'-o',out/'terminate')
    appproc=None; success=False; prefs_changed=False; cleanup={}
    def interrupt(signum, frame):
        raise RuntimeError('Interrupted; clean up owned VM and restore preferences')
    signal.signal(signal.SIGTERM,interrupt)
    signal.signal(signal.SIGINT,interrupt)
    try:
        prefs_changed=True
        run('/usr/bin/defaults','import',DOMAIN,testprefs)
        actual=preferences(); assert actual is not None
        assert actual['DataHome']==str(data) and actual['backends']==overlay['backends']
        with (out/'app.log').open('w') as log:
            appproc=subprocess.Popen([str(app/'Contents/MacOS/Wizard'),'-DataHome',str(data),'-osFeedURL',feed_url,
                                      '-SUEnableAutomaticChecks','NO'],stdout=log,stderr=log)
        bounded_wait(lambda:appproc.poll() is None and any(r['path']=='/os/p2/latest.json' for r in requests),
                     300,'release app first feed request (check backend selection/Files-folder prompt and app.log)')
        def installed():
            assert appproc.poll() is None, 'Release app exited'
            manifest=data/'os/manifest.json'
            if not manifest.exists():return False
            m=json.loads(manifest.read_text());assert m['version']=='0.5.0';return m
        manifest=bounded_wait(installed,2400,'production installer downloading loopback p2 feed')
        (out/'installed-manifest.json').write_text(json.dumps(manifest,indent=2))
        def healthy():
            status=json.loads((data/'host-status.json').read_text())
            assert status['dataHome']==str(data) and str(status['build'])=='309'
            assert status['pid'] in owned_hosts(app,data)
            if status['state']!='running':return False
            health={}
            for name,url in [('onboarding','http://127.0.0.1:48030/healthz'),('agent','http://127.0.0.1:48023/wizard/health')]:
                with urllib.request.urlopen(url,timeout=5) as response:
                    assert response.status==200;health[name]=response.read().decode()
            return {'status':status,'health':health}
        health=bounded_wait(healthy,1200,'new factory onboarding and agent health')
        with urllib.request.urlopen('http://127.0.0.1:48030/',timeout=15) as response:
            html=response.read().decode(); assert response.status==200 and ('Wizard' in html or 'wizard' in html)
        (out/'onboarding.html').write_text(html)
        (out/'guest-state.txt').write_text(shell('set -eu; test -f /opt/wizard/release/factory-composition.json; cat /opt/wizard/release/factory-composition.json; test ! -e /mnt/wizard-mac/onboarded.json; docker ps --format "{{.Names}} {{.Status}}"'))
        forbidden=list((data/'updates').glob('legacy-*')) if (data/'updates').exists() else []
        assert not forbidden, 'Precomposed 0.5.0 must never start legacy bootstrap: '+repr(forbidden)
        paths={r['path'] for r in requests};assert '/os/p2/latest.json' in paths
        for part in feed['parts']:assert part['url'] in paths, part['url']
        (out/'health.json').write_text(json.dumps(health,indent=2))
        success=True
    finally:
        # Keep the unmodified final app and its guest until clean shutdown, then
        # restore preferences even on a failed installer/health assertion.
        try:
            app_error=None
            try:
                if appproc and appproc.poll() is None:
                    run(out/'terminate',appproc.pid,app/'Contents/MacOS/Wizard')
                    appproc.wait(timeout=30)
            except Exception as e:
                app_error=e
            hosts=owned_hosts(app,data)
            for pid in hosts:
                run(out/'terminate',pid,app/'Contents/Library/LoginItems/Wizard Host.app/Contents/MacOS/Wizard Host')
            bounded_wait(lambda:not owned_hosts(app,data),120,'owned VM clean shutdown')
            if app_error and appproc and appproc.poll() is None:
                # Only our retained Popen child, after the owned VM stopped.
                appproc.terminate()
                try: appproc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    appproc.kill(); appproc.wait(timeout=15)
                cleanup['ownedAppSignalFallback']=True
            cleanup['ownedProcessesStopped']=True
        finally:
            try:
                if prefs_changed:
                    restore_preferences(original,backup)
                    cleanup['preferencesRestored']=True
                after=real_state()
                (out/'real-state-after.json').write_text(json.dumps(after,indent=2))
                assert after==before,'Real data state changed; stop and inspect evidence'
                cleanup['realStateUnchanged']=True
            finally:
                server.shutdown();server.server_close();thread.join(timeout=10)
                (out/'requests.json').write_text(json.dumps(requests,indent=2))
                (out/'cleanup.json').write_text(json.dumps(cleanup,indent=2))
    assert success and cleanup.get('ownedProcessesStopped') and cleanup.get('preferencesRestored')
    (out/'result.json').write_text(json.dumps({'pass':True,'version':'0.7.2','build':'309','factory':'0.5.0',
        'releaseAppUnmodified':True,'qaHooks':False,'feedURL':feed_url,'dataHome':str(data),
        'productionInstaller':True,'onboardingHealth':True,'agentHealth':True,
        'preferencesRestored':True,'vmStopped':True,'publication':'none',**setup},indent=2))
    print((out/'result.json').read_text())


if __name__=='__main__':main()
