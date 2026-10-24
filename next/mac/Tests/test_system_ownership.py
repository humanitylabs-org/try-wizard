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

    def test_payload_writes_supported_hermes_managed_config_only(self):
        source = (MAC.parent / 'guest/upgrade-mvp-stack.py').read_text()
        self.assertIn("(data/'.managed').write_text('host-payload\\n')", source)
        self.assertIn("for home in (data/'profiles').glob('*')", source)
        self.assertIn('app_guard.assert_unchanged(apps_before,app_guard.inventory())', source)
        self.assertIn('System payload requires an apps-stopped maintenance boot', source)
        self.assertNotIn("'restart','wizard-app-manager-api'", source)


if __name__ == '__main__':
    unittest.main()
