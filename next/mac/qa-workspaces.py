#!/usr/bin/env python3
"""Thales-only QAHooks acceptance. App-only, two fake Node Wizard origins, no VM.
Run under the shared worker lock; requires the output of build-workspaces-qa.sh.
Direct executable launch is deliberate: this does NOT certify Finder/Host/TCC.
"""
import argparse
import json
import pathlib
import platform
import plistlib
import subprocess as sp
import time

parser = argparse.ArgumentParser()
parser.add_argument('--app', required=True, type=pathlib.Path)
parser.add_argument('--out', required=True, type=pathlib.Path)
a = parser.parse_args()
if platform.system() != 'Darwin':
    raise SystemExit('Native acceptance requires Thales/macOS')
APP = a.app.resolve()
OUT = a.out.resolve()
OUT.mkdir(parents=True, exist_ok=False)
DOMAIN = plistlib.loads((APP/'Contents/Info.plist').read_bytes())['CFBundleIdentifier']
if not DOMAIN.startswith('org.humanitylabs.wizard.switcherqa.'):
    raise SystemExit('Refusing any non-scratch bundle identity')

def run(*cmd, check=True):
    return sp.run(list(map(str, cmd)), check=check, text=True, stdout=sp.PIPE, stderr=sp.STDOUT, timeout=45)

if run('pgrep', '-f', '/Contents/MacOS/Wizard$', check=False).returncode == 0:
    raise SystemExit('Another Wizard app is running; will not touch it')
if run('defaults', 'read', DOMAIN, check=False).returncode == 0:
    raise SystemExit('Scratch defaults already exist; rebuild with a new identity')
servers = []
logs = []
proc = None
passed = []
report = {'domain': DOMAIN, 'app': str(APP), 'surface': 'unsigned direct-launch native WKWebView fixture; no VM, physical mic, Finder or Host acceptance'}

def ok(condition, text):
    assert condition, text
    passed.append(text)
    print('PASS', text, flush=True)

def wait(fn, timeout=20):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        result = fn()
        if result:
            return result
        time.sleep(.1)
    raise AssertionError('Timed out waiting for fixture/native response')

def qa(command):
    run(OUT/'qa-post', command)

def ask(suffix, command):
    target = pathlib.Path('/tmp/wizard-mvp-qa-' + suffix)
    target.unlink(missing_ok=True)
    qa(command)
    if command == 'state':
        end = time.monotonic() + 15
        while not target.exists() and time.monotonic() < end:
            time.sleep(.2); qa(command)
    wait(target.exists)
    return target.read_text()

def ev(code, workspace=None):
    text = ask('eval.txt', ('workspace-eval ' + workspace + ' ' if workspace else 'eval ') + code)
    assert not text.startswith('ERROR'), text
    return text

def value(code, workspace=None):
    return json.loads(ev('JSON.stringify(' + code + ')', workspace))

def state():
    return json.loads(ask('workspaces.json', 'workspace-state'))

def bridge(method, params=None, workspace=None):
    token = ev('callNative(' + json.dumps(method) + ',' + json.dumps(params or {}) + ')', workspace)
    wait(lambda: ev('Object.hasOwn(replies,' + json.dumps(token) + ')', workspace) == '1')
    return value('replies[' + json.dumps(token) + ']', workspace)

def ready():
    return ev('!!window.callNative && !!window.wizardUX.native?.workspaces') == '1'

def launch():
    log = (OUT/('app-' + str(time.monotonic_ns()) + '.log')).open('w')
    logs.append(log)
    return sp.Popen([str(APP/'Contents/MacOS/Wizard'), '-ApplePersistenceIgnoreState', 'YES', '-CapsLockRemap', 'NO'], stdout=log, stderr=sp.STDOUT)

def stop():
    global proc
    if proc and proc.poll() is None:
        qa('command-q'); qa('command-q')
        proc.wait(timeout=10)
    proc = None

def screenshot(name):
    path = OUT/(name+'.png')
    qa('snapshot ' + str(path))
    wait(path.exists)
    ok(path.stat().st_size > 1000, 'WK screenshot captured: ' + name)

try:
    urls = []
    fixture = pathlib.Path(__file__).parent/'Tests/Workspaces/fixture.cjs'
    for label in ['One', 'Two']:
        log = (OUT/(label+'-server.log')).open('w'); logs.append(log)
        server = sp.Popen(['node', str(fixture), label], stdout=sp.PIPE, stderr=log, text=True)
        servers.append(server)
        assert server.stdout is not None
        urls.append(json.loads(server.stdout.readline())['url'])
    # Same old defaults schema intentionally exercises migration in the real app.
    entries = [{'kind': 'remote', 'name': 'Wizard '+label, 'url': url} for label, url in zip(['One', 'Two'], urls)]
    seed = OUT/'seed.plist'
    seed.write_bytes(plistlib.dumps({'QAHooks': True, 'QAWebStorage': True, 'CapsLockRemap': False,
                                    'DataHome': str(OUT/'data-home'), 'activeBackend': 0,
                                    'backends': json.dumps(entries).encode()}))
    run('defaults', 'import', DOMAIN, seed)
    run('defaults', 'write', DOMAIN, 'QAHooks', '-bool', 'true')
    notifier = OUT/'qa-post.swift'
    notifier.write_text('import Foundation\nDistributedNotificationCenter.default().postNotificationName(Notification.Name("org.humanitylabs.wizard.mvp.qa"),object:CommandLine.arguments[1],userInfo:nil,deliverImmediately:true)\nRunLoop.main.run(until:Date().addingTimeInterval(0.1))\n')
    run('xcrun', 'swiftc', '-O', notifier, '-o', OUT/'qa-post')
    proc = launch()
    ask('state.json', 'state')
    wait(ready)
    qa('update-later')
    listing = bridge('workspaces.list')
    ids = [item['id'] for item in listing['items']]
    one, two = ids
    ok(len(ids) == 2 and listing['active'] == one, 'bridge list has both migrated entries and correct active ID')
    ok(value('wizardUX.native.workspaces && wizardNativeCaps.workspaces && wizardUX.fixture === "One"'), 'document-start capability survives later wizardUX assignment')
    original = value('loadToken')
    ev('counter=17;document.querySelector("#draft").value="draft survives";render();true')
    screenshot('one-before-switch')
    ok(bridge('workspaces.switch', {'id': two}, one).get('ok') is True, 'native switch bridge acknowledges old/background caller')
    wait(ready)
    second = value('loadToken')
    screenshot('two-active')
    before_one = value('events.filter(e=>e.name!=="workspaces").length', one)
    before_two = value('events.filter(e=>e.name!=="workspaces").length', two)
    qa('workspace-dictation fixture text'); qa('workspace-orb')
    wait(lambda: value('events.filter(e=>e.name!=="workspaces").length', two) >= before_two + 2)
    ok(value('events.filter(e=>e.name!=="workspaces").length', one) == before_one, 'orb and dictation events target only active Wizard')
    ok(bridge('workspaces.switch', {'id': one}, two).get('ok') is True, 'switch back accepted')
    result = state()
    ok(result['switchMilliseconds'] < 200, 'cached native view swap <200 ms: ' + str(result['switchMilliseconds']))
    ok([p['id'] for p in result['pages'] if p['visible']] == [one], 'only the active native WKWebView is visible')
    ok(value('loadToken') == original and value('counter') == 17 and value('document.querySelector("#draft").value') == 'draft survives', 'draft/counter/load token survive round trip without reloading')
    ok(value('events.some(e=>e.name==="workspaces" && e.detail.active===' + json.dumps(one) + ')', two), 'switch event reaches hidden Wizard')
    ok(bridge('workspaces.rename', {'id': two, 'name': 'Renamed fixture'}).get('ok') is True, 'rename accepted')
    wait(lambda: value('events.some(e=>e.name==="workspaces" && e.detail.items.some(i=>i.name==="Renamed fixture"))', two))
    ok(True, 'rename event reaches hidden Wizard')
    screenshot('one-restored')
    report['beforeRelaunch'] = state()
    stop(); proc = launch(); ask('state.json', 'state'); wait(ready); qa('update-later')
    persisted = bridge('workspaces.list')
    ok([i['id'] for i in persisted['items']] == ids and persisted['items'][1]['name'] == 'Renamed fixture', 'IDs and rename persist across app relaunch')
    ok(bridge('workspaces.remove', {'id': two}).get('ok') is True, 'remove forgets inactive entry')
    refused = bridge('workspaces.remove', {'id': one})
    ok(refused.get('ok') is False and 'error' in refused, 'last-entry removal is refused')
    final = bridge('workspaces.list')
    ok(len(final['items']) == 1 and final['active'] == one, 'last-entry refusal preserves registry')
    report['final'] = final
    report['status'] = 'PASS'
except BaseException as error:
    report['status'] = 'FAIL'; report['error'] = repr(error)
    raise
finally:
    forced = False
    if proc and proc.poll() is None:
        try:
            stop()
        except Exception:
            forced = True; proc.terminate()
            try: proc.wait(timeout=5)
            except sp.TimeoutExpired: proc.kill(); proc.wait(timeout=5)
    for server in servers:
        server.terminate(); server.wait(timeout=5)
    for log in logs: log.close()
    run('defaults', 'delete', DOMAIN, check=False)
    report['defaultsRemoved'] = run('defaults', 'read', DOMAIN, check=False).returncode != 0
    report['forcedCleanup'] = forced
    report['checks'] = passed
    report['count'] = len(passed)
    if forced or not report['defaultsRemoved']: report['status'] = 'FAIL'
    (OUT/'receipt.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
if report['status'] != 'PASS':
    raise SystemExit(1)
