#!/usr/bin/env python3
"""Mac release upgrade test (try-wizard#129): before a release is published, prove that the app installed Macs run
today updates to the candidate, and that the candidate's own updater can update it again.

Runs in the release workflow's `upgrade-test` job (macos-15, no secrets), only when the switch is on (repo variable
WOS_MAC_UPGRADE_TEST=on, or the "upgrade test" tick on a dry run). Two subcommands:

  loopback-feed   (build job) copy an appcast template with its enclosure moved from the public channel folder to the
                  loopback test server, so the sign job can sign a test feed for the very archive it publishes.
  run             (upgrade-test job) the two steps below, with real Sparkle installs and relaunches:
                    1. live -> candidate: the app the live mac/appcast.xml offers, installed in a temporary
                       Applications folder, updates to the candidate (signed candidate feed on loopback).
                    2. candidate -> candidate + 1: the installed candidate updates itself to a test-only copy built
                       with the build number raised by one (signed in the sign job, never published).
                  Pass for each step: the relaunched app reports the target build, the installed bundle's
                  CFBundleVersion is the target, `codesign --verify --deep --strict` passes and the update journal
                  (updates/transaction.json) says native-activated. Results go to the run summary; evidence (journals,
                  ui.json, qa.json, the app log, feed requests) goes to --evidence for the failure artifact.

Each app runs with a throwaway DataHome, QA hooks on, automatic checks off, the feed pointed at the loopback server
(SUFeedURL in the app's defaults, which Sparkle reads before Info.plist) and no VM: the chosen Wizard is a "remote"
stand-in page on the same loopback server whose voice state is idle, so Update and restart is admitted
(main.swift admitUpdateRestart) without starting a Host. These are written with `defaults write`, because Sparkle's
relaunch does not carry launch arguments. Only use it on a throwaway runner: it replaces the app's preferences.
"""
import argparse
import functools
import http.server
import json
import os
import pathlib
import plistlib
import shutil
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as X

DOMAIN = 'org.humanitylabs.wizard.mvp'
SPARKLE_NS = 'http://www.andymatuschak.org/xml-namespaces/sparkle'
# The first build published by the GitHub release workflow (0.8.1). Every such build answers the QA control channel
# used here (update-check / update-restart / update-state / update-quit, QAHooks) and reads SUFeedURL from defaults.
FIRST_QA_BUILD = 312
# A stand-in for Wizard UX: the window trusts it as the chosen Wizard and its voice state is idle.
STUB_PAGE = ('<!doctype html><html data-shell="upgrade-test"><meta charset=utf-8><title>Upgrade test</title>'
             '<script>window.__wux = {voice: "idle"};</script><body>WizardOS upgrade test (try-wizard#129)</body></html>\n')


# ---- pure parts (tested on any OS: next/mac/Tests/test_upgrade_test.py) ----

def loopback_feed(template, public_base, loopback_base):
    """The appcast template with its enclosure URL moved from the public channel folder to the loopback server."""
    public_base = public_base.rstrip('/') + '/'
    loopback_base = loopback_base.rstrip('/') + '/'
    if template.count('url="' + public_base) != 1:
        raise ValueError('expected exactly one enclosure under %s' % public_base)
    return template.replace('url="' + public_base, 'url="' + loopback_base)


def feed_items(text):
    """[(build, enclosure url, length)] of a Sparkle appcast (signature comments ignored)."""
    rss = X.fromstring(text.encode())
    items = []
    for item in rss.iter('item'):
        version = item.find('{%s}version' % SPARKLE_NS)
        enclosure = item.find('enclosure')
        if version is None or enclosure is None or not (version.text or '').strip().isdigit():
            continue
        items.append((int(version.text.strip()), enclosure.get('url'), int(enclosure.get('length') or 0)))
    return items


def newest(text):
    items = feed_items(text)
    if not items:
        raise ValueError('the live feed lists no build')
    return max(items)


def plan_live_step(live_build, candidate_build, first_qa_build=FIRST_QA_BUILD):
    """(run, reason): whether step 1 (live -> candidate) can run."""
    if live_build < first_qa_build:
        return False, ('the live build %d is older than build %d, the first with the QA control channel'
                       % (live_build, first_qa_build))
    if live_build >= candidate_build:
        return False, ('the live build %d is not older than the candidate %d (a dry run of a released version)'
                       % (live_build, candidate_build))
    return True, ''


def summary(results):
    lines = ['### Upgrade test (try-wizard#129)', '', '| Step | Result | Detail |', '|---|---|---|']
    for r in results:
        mark = {'pass': 'passed', 'fail': 'FAILED', 'skip': 'skipped'}[r['result']]
        lines.append('| %s | %s | %s |' % (r['step'], mark, r['detail'].replace('|', '/').replace('\n', ' ')))
    return '\n'.join(lines) + '\n'


# ---- the Mac part ----

def fetch(url, dest):
    sh(['/usr/bin/curl', '-fsSL', '--retry', '3', '--max-time', '300', '-o', dest, url])


def sh(args, **kw):
    return subprocess.run([str(a) for a in args], check=True, **kw)


def out(args):
    return subprocess.check_output([str(a) for a in args], text=True).strip()


class Failed(Exception):
    pass


def wait(probe, timeout, what):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            value = probe()
            if value:
                return value
        except (OSError, ValueError, KeyError) as e:
            last = e
        time.sleep(1)
    raise Failed('timed out after %ds waiting for %s%s' % (timeout, what, (' (%s)' % last) if last else ''))


class Server:
    """Loopback feed + archives + the stand-in Wizard page. Requests are logged for the evidence."""

    def __init__(self, root, port, log):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        for name in ('index.html', 'desktop.html'):
            (root / 'wizard-os-home').mkdir(exist_ok=True)
            (root / 'wizard-os-home' / name).write_text(STUB_PAGE)
        (root / 'index.html').write_text(STUB_PAGE)

        class Handler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, format, *args):
                with open(log, 'a') as f:
                    f.write('%s %s\n' % (time.strftime('%H:%M:%S'), format % args))

            def end_headers(self):
                self.send_header('Cache-Control', 'no-store')
                super().end_headers()

        self.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', port), functools.partial(Handler, directory=str(root)))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def feed(self, signed_feed):
        shutil.copyfile(signed_feed, self.root / 'appcast.xml')

    def archive(self, build, zip_path):
        d = self.root / str(build)
        d.mkdir(exist_ok=True)
        shutil.copyfile(zip_path, d / zip_path.name)


class Mac:
    def __init__(self, work, evidence, port, notify):
        self.work, self.evidence, self.port, self.notify = work, evidence, port, notify
        self.data = None
        self.since = None

    def prefs(self, data):
        """Fresh preferences for one step: throwaway DataHome, QA hooks, loopback feed, stand-in remote Wizard."""
        subprocess.run(['defaults', 'delete', DOMAIN], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.rmtree(pathlib.Path.home() / 'Library/Caches' / DOMAIN, ignore_errors=True)
        backends = json.dumps([{'kind': 'remote', 'name': 'Upgrade test', 'url': 'http://127.0.0.1:%d/' % self.port}])
        for key, *value in (('DataHome', '-string', str(data)), ('QAHooks', '-bool', 'true'),
                            ('QAWebStorage', '-bool', 'true'), ('VoiceKeys', '-bool', 'false'),
                            ('SUEnableAutomaticChecks', '-bool', 'false'), ('SUAutomaticallyUpdate', '-bool', 'false'),
                            ('SUFeedURL', '-string', 'http://127.0.0.1:%d/appcast.xml' % self.port),
                            ('backends', '-data', backends.encode().hex()), ('activeBackend', '-int', '0')):
            sh(['defaults', 'write', DOMAIN, key, *value])
        self.data = data

    def qa(self, command):
        sh([self.notify, command], stdout=subprocess.DEVNULL)

    def state(self):
        q = self.data / 'updates/qa.json'
        q.unlink(missing_ok=True)
        self.qa('update-state')
        end = time.time() + 6
        while time.time() < end:
            try:
                return json.loads(q.read_text())
            except (OSError, ValueError):
                time.sleep(0.2)
        raise OSError('the app did not answer update-state')

    def journal(self):
        return json.loads((self.data / 'updates/transaction.json').read_text())

    def launch(self, app, tag):
        sh(['/usr/bin/open', '-g', '-n', '--stdout', self.evidence / ('%s-stdout.log' % tag),
            '--stderr', self.evidence / ('%s-stderr.log' % tag), app])

    def quit(self):
        try:
            pid = self.state()['pid']
        except OSError:
            pid = None
        try:
            self.qa('update-quit')
        except subprocess.CalledProcessError:
            pass
        if pid:
            try:
                wait(lambda: subprocess.run(['/bin/kill', '-0', str(pid)], stderr=subprocess.DEVNULL).returncode != 0,
                     20, 'the app to quit')
            except Failed:
                subprocess.run(['/bin/kill', str(pid)])
        # Sparkle's helpers and any Wizard left from this step (this runner is throwaway).
        subprocess.run(['/usr/bin/pkill', '-f', str(self.work / 'Applications-')], stderr=subprocess.DEVNULL)
        time.sleep(1)

    def collect(self, tag):
        """Journals, ui.json, qa.json, the app's logs and the unified log of this step, for the failure artifact."""
        dest = self.evidence / tag
        dest.mkdir(parents=True, exist_ok=True)
        if self.data:
            for sub in ('updates', 'logs'):
                src = self.data / sub
                if src.is_dir():
                    for f in src.iterdir():
                        if f.is_file() and f.suffix in ('.json', '.log', '.txt'):
                            shutil.copyfile(f, dest / ('%s-%s' % (sub, f.name)))
        with open(dest / 'app.log', 'w') as f:
            when = ['--start', self.since] if self.since else ['--last', '15m']
            subprocess.run(['/usr/bin/log', 'show', *when, '--style', 'compact', '--predicate',
                            'process == "Wizard" OR process CONTAINS "Sparkle" OR process == "Autoupdate" '
                            'OR process == "Updater" OR subsystem == "org.sparkle-project.Sparkle"'],
                           stdout=f, stderr=subprocess.STDOUT)

    def upgrade(self, tag, app_zip, start_build, target_build, feed, server):
        """Install app_zip in a temporary Applications folder and update it to target_build through feed."""
        self.since = time.strftime('%Y-%m-%d %H:%M:%S')
        apps = self.work / ('Applications-' + tag)
        shutil.rmtree(apps, ignore_errors=True)
        apps.mkdir(parents=True)
        unzip = self.work / ('unzip-' + tag)
        shutil.rmtree(unzip, ignore_errors=True)
        sh(['/usr/bin/ditto', '-x', '-k', app_zip, unzip])
        found = [p for p in unzip.iterdir() if p.suffix == '.app']
        if len(found) != 1:
            raise Failed('%s holds %d apps' % (app_zip.name, len(found)))
        app = apps / 'WizardOS.app'
        sh(['/usr/bin/ditto', found[0], app])
        installed = plistlib.loads((app / 'Contents/Info.plist').read_bytes())['CFBundleVersion']
        if installed != str(start_build):
            raise Failed('the installed app is build %s, expected %s' % (installed, start_build))
        data = self.work / ('data-' + tag)
        shutil.rmtree(data, ignore_errors=True)
        data.mkdir(parents=True)
        self.prefs(data)
        server.feed(feed)
        self.launch(app, tag)
        s = wait(lambda: (lambda s: s if s.get('build') == str(start_build) else None)(self.state()), 90,
                 'build %s to start' % start_build)
        print('started build %s (pid %s)' % (s['build'], s['pid']), flush=True)

        # Check, then the automatic download and Sparkle's verification (archive and feed signatures).
        checked = 0
        def ready():
            nonlocal checked
            s = self.state()
            if s.get('ready') and s.get('phase') == 'ready':
                return s
            if s.get('phase') in ('failed', 'current', 'unavailable'):
                raise Failed('the update was not accepted: %s (%s)' % (s.get('phase'), s.get('message')))
            if s.get('phase') in ('idle', '', None) and time.time() - checked > 20:
                self.qa('update-check')
                checked = time.time()
            return None
        s = wait(ready, 300, 'the update to download and verify')
        print('ready to restart: %s' % s.get('message'), flush=True)

        # Update and restart, as the owner presses it.
        pressed = 0
        def relaunched():
            nonlocal pressed
            try:
                s = self.state()
            except OSError:
                return None   # restarting
            if s.get('build') == str(target_build):
                return s
            if s.get('phase') == 'failed':
                raise Failed('Update and restart failed: %s' % s.get('message'))
            if s.get('phase') in ('ready', 'busy') and time.time() - pressed > 35:
                self.qa('update-restart')
                pressed = time.time()
            return None
        s = wait(relaunched, 300, 'the app to relaunch as build %s' % target_build)
        journal = wait(lambda: (lambda j: j if j.get('phase') == 'native-activated' else None)(self.journal()), 60,
                       'the update journal to say native-activated')
        bundle = pathlib.Path(s['appPath'])
        if bundle.resolve() != app.resolve():
            raise Failed('the relaunched app runs from %s, not the installed %s' % (bundle, app))
        build = plistlib.loads((app / 'Contents/Info.plist').read_bytes())['CFBundleVersion']
        if build != str(target_build):
            raise Failed('the installed bundle says CFBundleVersion %s, expected %s' % (build, target_build))
        sign = subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)],
                              capture_output=True, text=True)
        if sign.returncode != 0:
            raise Failed('codesign --verify --deep --strict failed: %s' % (sign.stderr or sign.stdout).strip())
        if journal.get('installedBuild') != str(target_build):
            raise Failed('the journal names build %s' % journal.get('installedBuild'))
        return app, ('build %s -> %s: relaunched as %s, CFBundleVersion %s, codesign --verify --deep --strict passed, '
                     'journal native-activated' % (start_build, target_build, s['build'], build))


def run(a):
    work = a.work.resolve()
    evidence = a.evidence.resolve()
    work.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(parents=True, exist_ok=True)
    stage = json.loads((a.candidate / 'release-stage.json').read_text())
    plus = json.loads((a.plus_one / 'release-stage.json').read_text())
    candidate_build, plus_build = int(stage['build']), int(plus['build'])
    if plus_build != candidate_build + 1 or plus['releaseID'] != stage['releaseID']:
        raise SystemExit('the test-only copy must be the candidate with the build raised by one')
    candidate_zip = a.candidate / stage['archive']['name']
    plus_zip = a.plus_one / plus['archive']['name']

    notify = work / 'notify'
    sh(['xcrun', 'swiftc', a.notify_source, '-o', notify])
    server = Server(work / 'srv', a.port, evidence / 'feed-requests.log')
    server.archive(candidate_build, candidate_zip)
    server.archive(plus_build, plus_zip)
    mac = Mac(work, evidence, a.port, notify)
    results = []

    def step(name, tag, fn):
        try:
            _, detail = fn()
            results.append({'step': name, 'result': 'pass', 'detail': detail})
        except (Failed, subprocess.CalledProcessError, OSError, ValueError) as e:
            results.append({'step': name, 'result': 'fail', 'detail': str(e)})
            print('::error::Upgrade test, %s: %s' % (name, e), flush=True)
        finally:
            try:
                mac.collect(tag)
            finally:
                mac.quit()

    # Step 1: the app installed Macs run now -> the candidate. curl, not urllib: downloads.aiwizards.com refuses
    # Python's user agent (403).
    live_feed = evidence / 'live-appcast.xml'
    try:
        fetch(a.live_feed + '?upgrade-test=%d' % time.time(), live_feed)
        live_build, live_url, live_length = newest(live_feed.read_text())
    except (subprocess.CalledProcessError, OSError, ValueError, X.ParseError) as e:
        live_build = None
        why = 'could not read the live feed %s: %s' % (a.live_feed, e)
        print('::error::Upgrade test, step 1: %s' % why, flush=True)
        results.append({'step': 'live -> candidate %d' % candidate_build, 'result': 'fail', 'detail': why})
    go = False
    if live_build is not None:
        go, why = plan_live_step(live_build, candidate_build, a.first_qa_build)
        name1 = 'live %d -> candidate %d' % (live_build, candidate_build)
    if live_build is not None and not go:
        print('::warning::Upgrade test step 1 skipped: %s' % why, flush=True)
        results.append({'step': name1, 'result': 'skip', 'detail': why})
    elif go:
        def live_step():
            live_zip = work / ('live-%d.zip' % live_build)
            fetch(live_url, live_zip)
            if live_length and live_zip.stat().st_size != live_length:
                raise Failed('the live archive is %d bytes, the feed says %d' % (live_zip.stat().st_size, live_length))
            return mac.upgrade('live', live_zip, live_build, candidate_build, a.signed / 'appcast-candidate.xml', server)
        step(name1, 'step1-live-to-candidate', live_step)

    # Step 2: the candidate updates itself (its own updater, key and contract checks) to candidate + 1.
    step('candidate %d -> candidate + 1 (%d)' % (candidate_build, plus_build), 'step2-candidate-to-plus-one',
         lambda: mac.upgrade('candidate', candidate_zip, candidate_build, plus_build,
                             a.signed / 'appcast-plus-one.xml', server))

    subprocess.run(['defaults', 'delete', DOMAIN], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    text = summary(results)
    print(text, flush=True)
    (evidence / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    if a.summary:
        with open(a.summary, 'a') as f:
            f.write(text)
    return 1 if any(r['result'] == 'fail' for r in results) else 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n\n', 1)[0])
    sub = p.add_subparsers(dest='cmd', required=True)
    f = sub.add_parser('loopback-feed')
    f.add_argument('--template', type=pathlib.Path, required=True)
    f.add_argument('--out', type=pathlib.Path, required=True)
    f.add_argument('--public-base', required=True)
    f.add_argument('--loopback-base', required=True)
    r = sub.add_parser('run')
    r.add_argument('--live-feed', required=True)
    r.add_argument('--candidate', type=pathlib.Path, required=True, help='the staged release (mac-stage)')
    r.add_argument('--plus-one', type=pathlib.Path, required=True, help='the staged test-only candidate + 1')
    r.add_argument('--signed', type=pathlib.Path, required=True, help='appcast-candidate.xml, appcast-plus-one.xml')
    r.add_argument('--work', type=pathlib.Path, required=True)
    r.add_argument('--evidence', type=pathlib.Path, required=True)
    r.add_argument('--port', type=int, default=48219)
    r.add_argument('--first-qa-build', type=int, default=FIRST_QA_BUILD)
    r.add_argument('--notify-source', type=pathlib.Path,
                   default=pathlib.Path(__file__).resolve().parent / 'update-qa-notify.swift')
    r.add_argument('--summary', default=os.environ.get('GITHUB_STEP_SUMMARY'))
    a = p.parse_args(argv)
    if a.cmd == 'loopback-feed':
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(loopback_feed(a.template.read_text(), a.public_base, a.loopback_base))
        return 0
    return run(a)


if __name__ == '__main__':
    sys.exit(main())
