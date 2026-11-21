#!/usr/bin/env python3
"""Every Wizard app as its own Dock icon (try-wizard#147).

The shell's existing Add to home screen (wizard-ux core/home-screen-apps.js) talks to `window.wizardHomeScreenPort`,
which the Android app provides. The Mac's main window now provides it too (App/WizardDockApps.swift `portJS`), answered
through the one native bridge (`dock.message`): status, pin, pinned and refresh, the Android ops. A pin writes a thin
launcher in ~/Applications/Wizard Apps/ and adds it to the Dock; it opens `wizard://app/<id>`, which shows that app on
the shell's one-app page in its own window. The rules are in Shared/DockApps.swift (XCTest in Tests/DockApps, run by
`swift test` on macOS CI); this checks the wiring from source anywhere and, with Node, runs the page script against a
small fake page.
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

MAC = Path(__file__).resolve().parents[1]
ROOT = MAC.parents[1]


def block(source: str, start: str, end: str) -> str:
    i = source.find(start)
    j = source.find(end, i + len(start))
    if i < 0 or j < 0:
        raise AssertionError('%r not found' % start)
    return source[i:j]


def port_script() -> str:
    src = (MAC / 'App/WizardDockApps.swift').read_text()
    start = 'static let portJS = #"""\n'
    body = block(src, start, '\n    """#')[len(start):]
    assert '\\(' not in body, 'no Swift interpolation in the page script'
    return '\n'.join(line[4:] if line.startswith('    ') else line for line in body.split('\n'))


FAKE_PAGE = r"""
const posted = [], observers = [], docListeners = {}, offered = [];
let prevReplies = [];
class El {
  constructor(cls = '', attrs = {}) { this.nodeType = 1; this.cls = cls; this.attrs = attrs; this.dataset = attrs.dataset || {}; this.children = []; this.textContent = attrs.text || ''; this.closestMap = attrs.closest || {}; }
  get classList() { const c = this.cls.split(' '); return { contains: x => c.includes(x) }; }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  setAttribute(k, v) { this.attrs[k] = v; }
  querySelector(sel) { return this.children.find(c => sel.includes(c.cls.split(' ')[0])) || null; }
  querySelectorAll(sel) { return sel === 'button' ? this.children.filter(c => c.cls === 'button') : []; }
  closest(sel) { for (const k of Object.keys(this.closestMap)) if (sel.includes(k)) return this.closestMap[k]; return null; }
}
global.MutationObserver = class { constructor(fn) { this.fn = fn; observers.push(this); } observe(target, opts) { this.target = target; this.opts = opts; } };
const body = new El('body');
global.document = { readyState: 'complete', body, addEventListener: (t, fn) => { docListeners[t] = fn; } };
global.location = { search: process.argv[1] || '' };
global.URLSearchParams = URLSearchParams;
global.window = global;
window.webkit = { messageHandlers: { wizardNative: { postMessage: m => posted.push(m) } } };
window.wizardNativeReply = m => prevReplies.push(m);
eval(require('fs').readFileSync(0, 'utf8'));
const out = { hasPort: !!window.wizardHomeScreenPort };
if (out.hasPort) {
  const got = [];
  window.wizardHomeScreenPort.onmessage = e => got.push(e.data);
  window.wizardHomeScreenPort.postMessage(JSON.stringify({ op: 'status', requestId: '1', appId: 'wizard-notes' }));
  window.wizardHomeScreenPort.postMessage({ not: 'a string' });
  out.posted = posted.slice();
  window.wizardNativeReply({ id: posted[0].id, result: '{"requestId":"1","status":"ready"}' });
  window.wizardNativeReply({ id: posted[0].id, result: 'again' });       // answered once only
  window.wizardNativeReply({ id: 7, result: { meeting: true } });        // the meeting adapter's own reply
  out.got = got; out.prevReplies = prevReplies;
  out.portLocked = (() => { try { window.wizardHomeScreenPort = null; } catch (_) {} return !!window.wizardHomeScreenPort; })();
  // The shell's sheet: its words say Dock.
  const button = new El('button', { text: 'Add to home screen' }); button.cls = 'button';
  const sheet = new El('home-pin-sheet', { 'aria-label': 'Notes home screen' }); sheet.children.push(button);
  const backdrop = new El('home-pin-backdrop'); backdrop.children.push(sheet);
  observers[0].fn([{ addedNodes: [backdrop] }]);
  out.words = [button.textContent, sheet.getAttribute('aria-label')];
  button.textContent = 'Added to home screen'; observers[1].fn([]);
  out.words.push(button.textContent);
  // Right-click an app in the launcher: the shell's own Add to home screen sheet for that app.
  const notes = { id: 'wizard-notes', name: 'Notes', kind: 'wizard' }, shellApp = { id: 'agents', name: 'Agents' };
  window.WizCore = { apps: () => ({ APP: { 'wizard-notes': notes, agents: shellApp } }) };
  window.WizHomeScreenApps = { canOffer: a => a === notes, offer: a => { offered.push(a.id); return true; } };
  const click = (target, trusted = true) => { const e = { isTrusted: trusted, target, prevented: false, preventDefault() { this.prevented = true; }, stopPropagation() {} }; docListeners.contextmenu(e); return e.prevented; };
  out.menus = [
    click(new El('i', { closest: { '.home [data-app]': new El('app-chip', { dataset: { app: 'wizard-notes' } }) } })),
    click(new El('i', { closest: { '#palList .pal-app': new El('pal-app', { title: 'Notes · Your notes' }) } })),
    click(new El('i', { closest: { '.home [data-app]': new El('app-chip', { dataset: { app: 'wizard-notes' } }) } }), false),
    click(new El('i', { closest: { '.home [data-app]': new El('app-chip', { dataset: { app: 'agents' } }) } })),
    click(new El('i')),
  ];
  out.offered = offered;
}
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which('node'), 'node not installed')
class PortScriptTests(unittest.TestCase):
    def run_page(self, search=''):
        r = subprocess.run(['node', '-e', FAKE_PAGE, search], input=port_script(), capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_main_window_gets_the_android_port(self):
        out = self.run_page()
        self.assertTrue(out['hasPort'])
        self.assertTrue(out['portLocked'])
        self.assertEqual(len(out['posted']), 1, 'only string messages reach the Mac')
        msg = out['posted'][0]
        self.assertEqual(msg['method'], 'dock.message')
        self.assertTrue(msg['id'].startswith('dock-'))
        self.assertEqual(json.loads(msg['params']['data'])['op'], 'status')

    def test_replies_reach_the_shell_once_and_others_pass_through(self):
        out = self.run_page()
        self.assertEqual(out['got'], ['{"requestId":"1","status":"ready"}'])
        self.assertEqual(out['prevReplies'], [{'id': 7, 'result': {'meeting': True}}])

    def test_one_app_window_has_no_port(self):
        self.assertFalse(self.run_page('?app-session=wizard-notes')['hasPort'])

    def test_sheet_says_dock(self):
        self.assertEqual(self.run_page()['words'], ['Add to Dock', 'Notes Dock', 'Added to the Dock'])

    def test_right_click_offers_add_to_dock(self):
        out = self.run_page()
        self.assertEqual(out['menus'], [True, True, False, False, False])
        self.assertEqual(out['offered'], ['wizard-notes', 'wizard-notes'])


class WiringTests(unittest.TestCase):
    def setUp(self):
        self.main = (MAC / 'App/main.swift').read_text()
        self.dock = (MAC / 'App/WizardDockApps.swift').read_text()
        self.rule = (MAC / 'Shared/DockApps.swift').read_text()
        self.build = (MAC / 'build.sh').read_text()

    def test_port_script_is_main_frame_only_after_the_meeting_adapter(self):
        adapter = self.main.index('WKUserScript(source: MeetingBridge.adapterJS')
        port = self.main.index('WKUserScript(source: WizardDockApps.portJS, injectionTime: .atDocumentStart, forMainFrameOnly: true)')
        self.assertLess(adapter, port)
        self.assertNotIn('WKUserScript(', self.dock)

    def test_bridge_handler_and_pin_needs_a_fresh_click(self):
        self.assertIn('NativeBridge.shared.register("dock.")', self.main)
        self.assertIn('WizardDockApps.shared.answer(data, reply: reply)', self.main)
        pin = block(self.dock, 'case "pin":', 'case "pin-widget":')
        self.assertIn('Date().timeIntervalSince(lastUserAction) < 3', pin)
        self.assertIn('mainWindow?.isKeyWindow == true', pin)
        for op in ('"pinned"', '"status"', '"refresh"', '"pin"'):
            self.assertIn(op, self.dock)

    def test_dock_icons_open_their_app_window(self):
        self.assertIn('func application(_ application: NSApplication, open urls: [URL])', self.main)
        self.assertIn('WizardDockAppsRule.parse(url)', self.main)
        self.assertIn('WizardAppWindows.shared.open(link.appId, path: link.path)', self.main)
        self.assertIn('<key>CFBundleURLSchemes</key><array><string>wizard</string></array>', self.build)
        self.assertIn('static func sessionURL(home: URL, appId: String', self.rule)
        self.assertIn('"app-session"', self.rule)

    def test_add_all_and_refresh_come_from_the_shell(self):
        self.assertIn('Add Apps to Dock…', self.main)
        self.assertIn("window.dispatchEvent(new Event('wos-native-resume'))", self.dock)
        self.assertIn('box.state = .on', self.dock)

    def test_app_windows_keep_wizard_in_the_dock(self):
        close = block(self.main, 'func windowWillClose(_ notification: Notification) {', '\n    }')
        self.assertIn('WizardAppWindows.shared.anyVisible', close)

    def test_build_and_package_list_the_new_files(self):
        self.assertIn('Shared/BundleName.swift Shared/DockApps.swift Shared/NowPlaying.swift', self.build)
        self.assertIn('App/WizardRollbackCleanup.swift App/WizardDockApps.swift App/WizardUpdater.swift', self.build)
        pkg = (MAC / 'Package.swift').read_text()
        self.assertIn('sources: ["DockApps.swift"]', pkg)
        self.assertIn('path: "Tests/DockApps"', pkg)
        self.assertIn('next/mac/Tests/test_dock_apps.py', (ROOT / 'Makefile').read_text())


if __name__ == '__main__':
    import sys
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
