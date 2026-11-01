#!/usr/bin/env python3
"""Fast source/JS checks only. Not a Swift compile or native acceptance receipt."""
import pathlib
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'App/main.swift').read_text()
PAGES = (ROOT / 'App/WorkspacePages.swift').read_text()
MODEL = (ROOT / 'Shared/WorkspaceStore.swift').read_text()

class WorkspaceSourceChecks(unittest.TestCase):
    def test_capability_survives_bridge_handle_assignment(self):
        script = MODEL.split('static let script = """', 1)[1].split('"""', 1)[0]
        test = "global.window = {wizardUX:{existing:42}};\n" + script + r'''
        const assert = require('assert');
        assert.equal(window.wizardUX.existing,42);
        assert.equal(window.wizardUX.native.workspaces,true);
        const handler = ()=>true;
        window.wizardUX = {handle:handler,native:{voice:true},other:'retained'};
        assert.equal(window.wizardUX.handle,handler);
        assert.equal(window.wizardUX.native.voice,true);
        assert.equal(window.wizardUX.native.workspaces,true);
        assert.equal(window.wizardUX.other,'retained');
        assert.equal(window.wizardNativeCaps.workspaces,true);
        console.log('CAPABILITY_MERGE_PASS');
        '''
        result = subprocess.run(['node', '-e', test], check=True, text=True, capture_output=True)
        self.assertIn('CAPABILITY_MERGE_PASS', result.stdout)
    def test_bridge_authority_is_per_view_and_main_frame(self):
        self.assertIn('owner?.allowsNative(message.frameInfo, in: web) == true', MAIN)
        self.assertIn('frame.isMainFrame, isTrustedDocument(view)', PAGES)
        self.assertIn('workspaceCall || owner?.web === web', MAIN)
        self.assertIn('webView === web && allowsNative(frame, in: webView)', MAIN)
    def test_local_restart_admission_includes_hidden_pages_not_remote(self):
        body = MAIN.split('func admitUpdateRestart', 1)[1].split('/// Is the page', 1)[0]
        self.assertIn('pages.values.filter { $0.backend.kind == .thisMac }', body)
        self.assertIn('local.allSatisfy', body)
        self.assertIn('window.__wizardUpdateFrozen = true', body)
        self.assertNotIn('web.isHidden', body)
    def test_build_consumes_new_sources(self):
        build = (ROOT / 'build.sh').read_text()
        for source in ['Shared/WorkspaceStore.swift', 'App/WorkspacePages.swift']:
            self.assertIn(source, build)
    def test_forgetting_entry_never_controls_vm(self):
        body = MODEL.split('func remove(_ id:', 1)[1].split('private func failure', 1)[0]
        for forbidden in ['FileManager', 'HostControl', 'URLSession', 'removeItem']:
            self.assertNotIn(forbidden, body)
    def test_background_did_finish_cannot_hide_active_overlay(self):
        body = MAIN.split('didFinish navigation:', 1)[1].split('func webView(', 1)[0]
        self.assertLess(body.index('guard webView === web'), body.index('overlay.isHidden = true'))

if __name__ == '__main__':
    unittest.main()
