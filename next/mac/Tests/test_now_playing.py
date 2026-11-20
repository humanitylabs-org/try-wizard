#!/usr/bin/env python3
"""Music and Podcasts in the Mac's Now Playing, with the media keys (try-wizard#142, wizard-ux#1661).

Off by default behind the `NowPlaying` user default. The rules live in Shared/NowPlaying.swift (XCTest in
Tests/NowPlaying, run by `swift test` on macOS CI); this checks the wiring from source on any machine and, when Node
is installed, runs the page script against a small fake page to show what it reports and how it answers the keys.
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

MAC = Path(__file__).resolve().parents[1]


def block(source: str, start: str, end: str) -> str:
    i = source.find(start)
    j = source.find(end, i + len(start))
    if i < 0 or j < 0:
        raise AssertionError('%r not found' % start)
    return source[i:j]


def page_script() -> str:
    src = (MAC / 'App/WizardNowPlaying.swift').read_text()
    body = block(src, 'static let script = """\n', '\n    """')
    body = body[len('static let script = """\n'):]
    assert '\\(' not in body, 'no Swift interpolation in the page script'
    return '\n'.join(line[4:] if line.startswith('    ') else line for line in body.split('\n')).replace('\\\\', '\\')


FAKE_PAGE = r"""
const posted = [];
const listeners = {};
const timers = [];
global.setTimeout = (fn) => { timers.push(fn); return timers.length; };
global.setInterval = () => 1; global.clearInterval = () => {};
const flush = () => { while (timers.length) timers.shift()(); };
class HTMLMediaElement {
  constructor() { this.paused = true; this.ended = false; this.duration = 1800; this.currentTime = 0; this.playbackRate = 1; this.ls = {}; }
  addEventListener(t, fn) { (this.ls[t] = this.ls[t] || []).push(fn); }
  fire(t) { (this.ls[t] || []).forEach(f => f()); }
  play() { this.paused = false; this.fire('play'); return Promise.resolve(); }
  pause() { this.paused = true; this.fire('pause'); }
}
const handlers = {};
class MediaSession { constructor() { this._m = null; } }
Object.defineProperty(MediaSession.prototype, 'metadata', {configurable: true, enumerable: true,
  get() { return this._m; }, set(v) { this._m = v; }});
MediaSession.prototype.setActionHandler = function (a, fn) { handlers[a] = fn; };
global.window = global;
global.HTMLMediaElement = HTMLMediaElement;
global.MediaSession = MediaSession;
global.MediaMetadata = class { constructor(m) { Object.assign(this, m); } };
global.location = {pathname: process.argv[1], href: 'http://localhost:48023' + process.argv[1]};
Object.defineProperty(global, 'navigator', {value: {mediaSession: new MediaSession()}, configurable: true});
global.document = {addEventListener: () => {}};
global.addEventListener = (t, fn) => { listeners[t] = fn; };
global.webkit = {messageHandlers: {wizardNowPlaying: {postMessage: m => posted.push(JSON.parse(JSON.stringify(m)))}}};
eval(require('fs').readFileSync(0, 'utf8'));
const out = {active: !!window.__wizardNowPlaying};
if (out.active) {
  // The app, like Podcasts: metadata + action handlers, then plays its own element.
  const audio = new HTMLMediaElement();
  const calls = [];
  navigator.mediaSession.metadata = new MediaMetadata({title: 'Episode 7', artist: 'The Show', album: 'Podcasts',
    artwork: [{src: '/art-96.png', sizes: '96x96'}, {src: '/art-512.png', sizes: '512x512'}]});
  navigator.mediaSession.setActionHandler('seekbackward', d => calls.push(['seekbackward', d.seekOffset]));
  navigator.mediaSession.setActionHandler('pause', () => { calls.push(['pause']); audio.pause(); });
  audio.play(); audio.currentTime = 60; flush();
  out.playing = posted[posted.length - 1];
  out.skip = window.__wizardNowPlaying.command('skipBack', 15);
  out.pause = window.__wizardNowPlaying.command('toggle', 0); flush();
  out.paused = posted[posted.length - 1];
  // No seekto handler: falls back to the element.
  window.__wizardNowPlaying.command('seek', 120);
  out.seekTime = audio.currentTime;
  out.unknown = window.__wizardNowPlaying.command('evil', 0);
  listeners.pagehide();
  out.gone = posted[posted.length - 1];
  out.calls = calls;
}
console.log(JSON.stringify(out));
"""


class NowPlayingTests(unittest.TestCase):
    def setUp(self):
        self.main = (MAC / 'App/main.swift').read_text()
        self.center = (MAC / 'App/WizardNowPlaying.swift').read_text()
        self.rule = (MAC / 'Shared/NowPlaying.swift').read_text()
        self.build = (MAC / 'build.sh').read_text()

    def test_switch_is_off_by_default(self):
        body = block(self.main, 'enum WizardNowPlaying {', '\n}\n')
        self.assertIn('static let key = "NowPlaying"', body)
        self.assertRegex(body, r'static var isOn: Bool \{ UserDefaults\.standard\.bool\(forKey: key\) \}')
        self.assertIn('defaults write org.humanitylabs.wizard.mvp NowPlaying -bool YES', self.main)

    def test_script_and_handler_only_with_switch_on(self):
        self.assertIn('if WizardNowPlaying.isOn { WizardNowPlayingCenter.install(into: cfg.userContentController) }', self.main)
        self.assertEqual(self.main.count('WizardNowPlayingCenter.install('), 1)
        install = block(self.center, 'static func install(into controller: WKUserContentController) {', '\n    }\n')
        self.assertIn('controller.add(shared, name: name)', install)
        self.assertIn('WKUserScript(source: script, injectionTime: .atDocumentStart, forMainFrameOnly: false)', install)
        self.assertIn('WizardNowPlayingCenter.shared.owner = self', self.main)

    def test_reports_admitted_only_through_the_rule(self):
        handler = block(self.center, 'func userContentController(', '\n    }\n')
        self.assertIn('WizardNowPlaying.isOn', handler)
        self.assertIn('owner.web === web', handler)
        self.assertIn('trustedShell: owner.isTrustedDocument', handler)
        self.assertIn('owner.isWizardAppAddress(message.frameInfo.securityOrigin)', handler)
        self.assertIn('path: url.path', handler)
        self.assertIn('guard switchOn, trustedShell, wizardAddress else { return nil }', self.rule)
        self.assertIn('static let apps: Set<String> = ["wizard-music", "wizard-podcasts"]', self.rule)
        address = block(self.main, 'func isWizardAppAddress(', '\n    }\n')
        self.assertIn('selectedControlOrigins', address)
        self.assertIn('.thisMac', address)

    def test_keys_go_only_to_the_playing_frame(self):
        send = block(self.center, 'private func send(', '\n    }\n')
        self.assertIn('activeApp == app', send)
        self.assertIn('frames[app]', send)
        self.assertIn('in: frame, in: .page', send)
        self.assertIn('WizardNowPlayingCenter.shared.reset()', block(self.main, 'func webView(_ webView: WKWebView, didCommit', '\n    }\n'))

    def test_clicking_now_playing_opens_the_playing_app(self):
        reopen = block(self.main, 'func applicationShouldHandleReopen(', '\n    }\n')
        self.assertIn('WizardNowPlayingCenter.shared.openPlayingApp()', reopen)
        self.assertIn('Rule.openScript(app)', self.center)

    def test_build_and_package(self):
        self.assertIn('Shared/NowPlaying.swift Shared/AppLocation.swift Shared/HostHandover.swift', self.build)
        self.assertIn('App/WizardUpdater.swift App/WizardNowPlaying.swift App/main.swift', self.build)
        self.assertIn('-framework MediaPlayer', self.build)
        self.assertIn('"NowPlaying.swift"', (MAC / 'Package.swift').read_text())
        self.assertTrue((MAC / 'Tests/NowPlaying/NowPlayingTests.swift').exists())

    def run_page(self, path):
        node = shutil.which('node')
        if not node:
            self.skipTest('node not installed')
        r = subprocess.run([node, '-e', FAKE_PAGE, path], input=page_script(), capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_page_script_stays_idle_outside_music_and_podcasts(self):
        for path in ['/', '/wizard-maps/', '/apps/wizard-youtube-music/', '/wizard-musicbox/']:
            self.assertFalse(self.run_page(path)['active'], path)

    def test_page_script_reports_and_answers_keys(self):
        out = self.run_page('/apps/wizard-podcasts/')
        self.assertTrue(out['active'])
        p = out['playing']
        self.assertEqual(p['v'], 1)
        self.assertTrue(p['playing'])
        self.assertEqual((p['title'], p['artist'], p['album']), ('Episode 7', 'The Show', 'Podcasts'))
        self.assertEqual(p['artwork'], 'http://localhost:48023/art-512.png')
        self.assertEqual((p['duration'], p['position'], p['rate']), (1800, 60, 1))
        self.assertTrue(out['skip'])
        self.assertTrue(out['pause'])
        self.assertFalse(out['paused']['playing'])
        self.assertEqual(out['calls'], [['seekbackward', 15], ['pause']])
        self.assertEqual(out['seekTime'], 120)
        self.assertFalse(out['unknown'])
        self.assertEqual(out['gone'], {'v': 1, 'gone': True})
        self.assertTrue(self.run_page('/wizard-music/')['active'])


if __name__ == '__main__':
    unittest.main()
