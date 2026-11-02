#!/usr/bin/env python3
"""Phone access wiring for the Mac guest (wizard-agent-service docs/phone-setup.md), checked without a VM."""
import ast, copy, json, pathlib, re, subprocess, sys, unittest

GUEST = pathlib.Path(__file__).parents[1]
CONFIGURE = GUEST / 'overlay/opt/wizard/bin/wizard-runtime-configure'
PHONE = GUEST / 'overlay/opt/wizard/bin/wizard-phone-access'
HELPER = GUEST / 'overlay/opt/wizard/private-access'
LOCAL_PROXY = GUEST / 'overlay/opt/wizard/local-proxy.conf'


def configure_namespace():
    """The production phone_access() and its constants, lifted out of wizard-runtime-configure."""
    tree = ast.parse(CONFIGURE.read_text())
    keep = [n for n in tree.body if (isinstance(n, ast.Assign) and any(getattr(t, 'id', '').startswith('PHONE_') for t in n.targets))
            or (isinstance(n, ast.FunctionDef) and n.name in ('phone_access', 'phone_setup'))]
    namespace = {'json': json, 'subprocess': subprocess, 'sys': sys, 'run': None}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(CONFIGURE), 'exec'), namespace)
    return namespace


def shell_value(name):
    return re.search(rf'^{name}=(\S+)', PHONE.read_text(), re.M).group(1)


class PhoneAccess(unittest.TestCase):
    def setUp(self):
        self.ns = configure_namespace()
        self.svc = {'image': 'wizard-shell:mac-mvp-20261013',
                    'environment': {'WIZARD_AUTH_MODE': 'none', 'WIZARD_ALLOWED_HOSTS': '127.0.0.1:48023'},
                    'ports': ['127.0.0.1:8798:8788'], 'volumes': ['/a:/b']}

    def test_adds_tailnet_listener_on_loopback_only(self):
        self.ns['phone_access'](self.svc)
        self.assertEqual(self.svc['environment']['WIZARD_TAILNET_PORT'], '8789')
        self.assertEqual(self.svc['environment']['WIZARD_PRIVATE_ACCESS_SOCKET'], '/run/wizard-private-access/sock')
        self.assertIn('127.0.0.1:8809:8789', self.svc['ports'])
        for port in self.svc['ports']:
            self.assertTrue(port.startswith('127.0.0.1:'), port)  # rule 0: nothing reachable from the tailnet directly
        self.assertIn('/run/wizard-private-access:/run/wizard-private-access', self.svc['volumes'])
        self.assertEqual(self.svc['group_add'], ['980'])

    def test_keeps_the_local_owner_path_and_sets_no_identity(self):
        self.ns['phone_access'](self.svc)
        env = self.svc['environment']
        self.assertEqual(env['WIZARD_AUTH_MODE'], 'none')                 # main port: Mac app path unchanged
        self.assertEqual(env['WIZARD_ALLOWED_HOSTS'], '127.0.0.1:48023')
        self.assertNotIn('WIZARD_TAILNET_LOGIN', env)                      # settings (Setup) name the owner, not env
        self.assertNotIn('WIZARD_TAILNET_ORIGIN', env)
        self.assertIn('127.0.0.1:8798:8788', self.svc['ports'])
        self.assertNotIn('owner@wizard.local', repr(self.svc))

    def test_idempotent(self):
        self.ns['phone_access'](self.svc)
        once = copy.deepcopy(self.svc)
        self.ns['phone_access'](self.svc)
        self.assertEqual(self.svc, once)

    def test_helper_failure_leaves_the_runtime_provisionable(self):
        # A failed helper install (e.g. gid 980 taken) must not stop runtime provisioning, and the Service must not be
        # given a socket mount, socket group or tailnet listener that does not exist.
        before = copy.deepcopy(self.svc)
        def failing(args):
            raise subprocess.CalledProcessError(1, args)
        for runner in (failing, lambda args: 'not json', lambda args: '{"phone_access":"blocked"}'):
            result = self.ns['phone_setup'](self.svc, runner)
            self.assertEqual(result, {'phone_access': 'unavailable'})
            self.assertEqual(self.svc, before)

    def test_non_object_helper_json_is_unavailable(self):
        for output in ('null', '[]', '"ready"', 'true', '0'):
            with self.subTest(output=output):
                svc = copy.deepcopy(self.svc)
                result = self.ns['phone_setup'](svc, lambda args: output)
                self.assertEqual(result, {'phone_access': 'unavailable'})
                self.assertEqual(svc, self.svc)

    def test_repeated_provisioning_failure_removes_only_phone_wiring(self):
        def failed_install(args):
            raise subprocess.CalledProcessError(1, args)
        def missing_helper(args):
            raise FileNotFoundError(args[0])
        for runner in (failed_install, missing_helper, lambda args: 'not json',
                       lambda args: '{"phone_access":"blocked"}', lambda args: 'null',
                       lambda args: '[]', lambda args: '"ready"'):
            with self.subTest(runner=runner):
                svc = copy.deepcopy(self.svc)
                svc['environment']['OWNER_SETTING'] = 'preserved'
                svc['group_add'] = ['1001', 'owner-group']
                svc['labels'] = {'owner.label': 'preserved'}
                svc['volumes'].append('/owner:/owner:ro')
                svc['ports'].append('127.0.0.1:9000:9000')
                before = copy.deepcopy(svc)
                ready = self.ns['phone_setup'](svc, lambda args: '{"phone_access":"ready"}')
                self.assertEqual(ready['phone_access'], 'ready')
                self.assertIn('980', svc['group_add'])
                # A persisted YAML overlay can contain numeric or string gids.
                svc['group_add'][-1] = 980
                result = self.ns['phone_setup'](svc, runner)
                self.assertEqual(result, {'phone_access': 'unavailable'})
                self.assertEqual(svc, before)
                # Failure is idempotent, and a subsequent healthy install can recover.
                self.assertEqual(self.ns['phone_setup'](svc, runner), result)
                self.assertEqual(svc, before)
                self.ns['phone_setup'](svc, lambda args: '{"phone_access":"ready"}')
                self.assertIn('127.0.0.1:8809:8789', svc['ports'])
                self.assertIn('/run/wizard-private-access:/run/wizard-private-access', svc['volumes'])
                self.assertIn('980', svc['group_add'])

    def test_null_ports_degrades_without_aborting(self):
        svc = copy.deepcopy(self.svc)
        svc['ports'] = None
        result = self.ns['phone_setup'](svc, lambda args: '{"phone_access":"blocked"}')
        self.assertEqual(result, {'phone_access': 'unavailable'})
        self.assertEqual(svc['ports'], [])

    def test_ready_helper_wires_the_service(self):
        result = self.ns['phone_setup'](self.svc, lambda args: '{"phone_access":"ready","socket_gid":980}')
        self.assertEqual(result['phone_access'], 'ready')
        self.assertIn('127.0.0.1:8809:8789', self.svc['ports'])
        self.assertEqual(self.svc['group_add'], ['980'])

    def test_installer_and_overlay_agree(self):
        self.assertEqual(shell_value('UPSTREAM'), self.ns['PHONE_UPSTREAM'])
        self.assertEqual(shell_value('GID'), self.ns['PHONE_GID'])
        self.assertEqual(shell_value('GROUP'), 'wizard-access')            # never the wizard user's own group

    def test_serve_never_reaches_an_owner_injecting_listener(self):
        upstream = self.ns['PHONE_UPSTREAM']
        self.assertNotEqual(upstream, '8799')                              # the Wizard app template's default port
        owner_ports = set(re.findall(r'listen 127\.0\.0\.1:(\d+)', LOCAL_PROXY.read_text())) | {'8796', '8798'}
        self.assertNotIn(upstream, owner_ports)

    def test_helper_is_vendored_from_a_pinned_commit(self):
        self.assertRegex((HELPER / 'SOURCE').read_text(), r'^wizard-agent-service@[0-9a-f]{40} ops/private-access$')
        for name in ['wizard-private-access', 'wizard-private-access.service', 'install.sh']:
            self.assertTrue((HELPER / name).is_file(), name)
        self.assertTrue(PHONE.stat().st_mode & 0o111)
        subprocess.run(['bash', '-n', str(PHONE)], check=True)
        subprocess.run(['sh', '-n', str(HELPER / 'install.sh')], check=True)

    def test_ssh_guard_drops_tailnet_ssh_before_tailscales_filter(self):
        text = PHONE.read_text()
        self.assertIn('-t raw', text)
        self.assertIn('-i tailscale0 -p tcp --dport 22 -j DROP', text)

    def test_existing_installs_receive_it(self):
        upgrade = (GUEST / 'upgrade-mvp-stack.py').read_text()
        self.assertIn("'private-access'", upgrade)
        self.assertIn("'bin/wizard-phone-access'", upgrade)
        self.assertIn("'wizard-phone-access'", upgrade)


if __name__ == '__main__':
    unittest.main()
