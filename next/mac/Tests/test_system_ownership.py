import copy
import importlib.util
import unittest
from test_guest_abi import MAC, policy


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, MAC.parent / 'guest' / file)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


guard = load('app_guard', 'app-update-guard.py')
cold = load('cold_gate', 'cold-bootstrap.py')


def container(cid='app', service='notes', running=False):
    return {'Id': cid, 'Name': '/' + cid, 'Image': 'sha256:' + 'a' * 64,
            'Config': {'Labels': {'com.docker.compose.service': service}, 'Env': ['PRESERVE=1']},
            'Mounts': [{'Name': 'user-data', 'Source': '/data'}], 'State': {'Running': running}}


class SystemOwnershipContract(unittest.TestCase):
    def test_system_owner_refusal(self):
        policy.require_system_owner({})  # explicit legacy migration
        policy.require_system_owner({'systemOwner': 'host-payload'})
        for owner in ('guest-feed', '', None, False):
            with self.subTest(owner=owner), self.assertRaises(ValueError):
                policy.require_system_owner({'systemOwner': owner})
        for file in ('App/WizardGuestActivation.swift', 'Host/main.swift'):
            self.assertIn('WizardGuestABI.requireSystemOwner(', (MAC / file).read_text())
        source = (MAC / 'Shared/UpdateContract.swift').read_text()
        self.assertIn('System payload downgrade refused', source)
        self.assertIn('incomingBuild.compare(build, options: .numeric)', source)
        identity = (MAC / 'Shared/DiskIdentity.swift').read_text()
        self.assertIn('journal["maintenanceCold"] as? Bool == true else { return }', identity)
        self.assertIn('Payload transaction disk identity changed', (MAC / 'App/WizardGuestActivation.swift').read_text())

    def test_apps_untouched(self):
        before = guard.apps([container(), container('system', 'wizard-shell', True)])
        self.assertEqual(set(before), {'app'})
        guard.assert_unchanged(before, copy.deepcopy(before))
        for key, value in [('image', 'sha256:other'), ('mounts', []), ('config', {}), ('running', True)]:
            after = copy.deepcopy(before); after['app'][key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                guard.assert_unchanged(before, after)
        with self.assertRaises(RuntimeError):
            guard.assert_unchanged(before, {})
        with self.assertRaises(RuntimeError):
            guard.assert_stopped(guard.apps([container(running=True)]))

    def test_runtipi_store_state_is_read_only(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            app = root / 'user-config/notes/settings.json'
            app.parent.mkdir(parents=True); app.write_text('{"keep":true}')
            owned = root / 'user-config/wizardapps/wizard-shell/compose.yml'
            owned.parent.mkdir(parents=True); owned.write_text('old system')
            before = guard.store_state(root)
            owned.write_text('new system')
            self.assertEqual(before, guard.store_state(root))
            app.write_text('{"keep":false}')
            self.assertNotEqual(before, guard.store_state(root))

    def test_running_apps_must_resume(self):
        before = guard.apps([container(running=True), container('stopped')])
        guard.assert_running_after(before, copy.deepcopy(before))
        for after in ({}, guard.apps([container(running=False)])):
            with self.assertRaises(RuntimeError):
                guard.assert_running_after(before, after)
        source = (MAC / 'App/WizardGuestActivation.swift').read_text()
        self.assertIn('verify-apps-after-update', source)
        self.assertIn('health["nonce"] as? String == journal["nonce"] as? String', source)
        self.assertIn('"appsBefore"', (MAC / 'Host/main.swift').read_text())

    def test_authz_never_mutates_app_or_prunes_images(self):
        import base64, json
        app = container()
        p = {'phase': 'fenced', 'managed': 'sha256:managed', 'service': 'sha256:shell'}
        def request(method, path, body=None):
            return {'RequestMethod': method, 'RequestUri': path,
                    'RequestBody': base64.b64encode(json.dumps(body or {}).encode()).decode()}
        for method, path in [('DELETE', '/containers/app'), ('DELETE', '/volumes/user-data'),
                             ('DELETE', '/networks/apps'), ('POST', '/images/prune'),
                             ('POST', '/containers/app/start'), ('POST', '/containers/app/rename')]:
            self.assertFalse(cold.authorize(request(method, path), p, find=lambda _: app), path)
        self.assertFalse(cold.authorize(request('POST', '/volumes/create', {'Name': 'user-data'}), p))

    def test_guard_is_loaded_before_store_inventory(self):
        source = (MAC.parent / 'guest/upgrade-mvp-stack.py').read_text()
        self.assertLess(source.index('app_guard=importlib.util.module_from_spec'), source.index('app_store_before=app_guard.store_state(root)'))
        self.assertIn('bom["guestABI"] as? [String: Any]', (MAC / 'Shared/UpdateContract.swift').read_text())
        # Execute the real preflight prefix with disposable fixture paths and a
        # read-only empty Docker inventory. No guest, daemon or owner state touched.
        import ast, json, sys, tempfile, types
        from pathlib import Path
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory); payload = work / 'payload'; root = work / 'runtipi'
            for relative in ('wam/wam/registry.py','wam/wam/fresh_agent.py','overlay/opt/wizard/local-proxy.conf',
                             'overlay/opt/wizard/bin/wizard-product-configure','overlay/opt/wizard/bin/wizard-runtime-configure',
                             'agent-runtime/agent_runtime.py','wizard-shell.tar'):
                file = payload / relative; file.parent.mkdir(parents=True, exist_ok=True); file.write_text('fixture')
            (payload / 'runtime-bom.json').write_text(json.dumps({'guestABI': {'min':0,'max':1}}))
            config = root / 'app-data/wizardapps/hermes-agent/data/config.yaml'
            config.parent.mkdir(parents=True); config.write_text('{}')
            paths = {'/home/wizard/runtipi':str(root), '/etc/wizard-platform.json':str(work/'platform.json'),
                     '/var/lib/wizard/system-owner.json':str(work/'owner.json')}
            class FixturePaths(ast.NodeTransformer):
                def visit_Constant(self, node):
                    if isinstance(node.value, str) and node.value in paths:
                        return ast.copy_location(ast.Constant(paths[node.value]), node)
                    return node
            tree = ast.parse(source[:source.index("with (a.payload/'wizard-shell.tar')")])
            tree = ast.fix_missing_locations(FixturePaths().visit(tree))
            namespace = {'__file__':str(MAC.parent/'guest/upgrade-mvp-stack.py')}
            with patch.object(sys, 'argv', ['upgrade',str(payload),'--apply','--cold-bootstrap','--guest-abi','1']), \
                 patch.dict(sys.modules, {'yaml':types.ModuleType('yaml')}), \
                 patch('os.geteuid', return_value=0), patch('subprocess.check_output', return_value='') as docker:
                exec(compile(tree, '<real-applier-preflight-fixture>', 'exec'), namespace)
                self.assertEqual(namespace['apps_before'], {})
                self.assertEqual(namespace['app_store_before'], {})
                docker.assert_called_once_with(['docker','ps','-aq'], text=True)

    def test_payload_writes_supported_hermes_managed_config_only(self):
        source = (MAC.parent / 'guest/upgrade-mvp-stack.py').read_text()
        self.assertIn("(data/'.managed').write_text('host-payload\\n')", source)
        self.assertIn("for home in (data/'profiles').glob('*')", source)
        self.assertIn('ENV HERMES_MANAGED=host-payload', (MAC.parent / 'guest/managed-launch/Dockerfile').read_text())
        self.assertIn('app_guard.assert_unchanged(apps_before,app_guard.inventory())', source)
        self.assertIn('System payload requires an apps-stopped maintenance boot', source)
        self.assertNotIn("'restart','wizard-app-manager-api'", source)


if __name__ == '__main__':
    unittest.main()
