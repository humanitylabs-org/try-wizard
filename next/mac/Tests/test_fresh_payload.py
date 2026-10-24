import unittest
from test_guest_abi import policy, MAC


class FreshPayloadContract(unittest.TestCase):
    def test_id_compare(self):
        cases = [(None, None, True), ('', '', True), (None, 'sha256:new', True),
                 ('sha256:old', 'sha256:new', True), ('sha256:same', 'sha256:same', False)]
        for baked, bundled, expected in cases:
            with self.subTest(baked=baked, bundled=bundled):
                self.assertEqual(policy.requires_fresh_apply(baked, bundled), expected)
        source = (MAC / 'Shared/UpdateContract.swift').read_text()
        self.assertIn('!baked.isEmpty, !bundled.isEmpty else { return true }', source)
        self.assertIn('return baked != bundled', source)

    def test_fresh_reuses_activation_and_clones_before_compare(self):
        source = (MAC / 'App/WizardGuestActivation.swift').read_text()
        fresh = source[source.index('func prepareFresh()'):source.index('func activate()')]
        self.assertIn('"kind": "fresh"', fresh)
        self.assertLess(fresh.index('"fresh-placed"'), fresh.index('try Self.snapshotStoppedDisk()'))
        self.assertLess(fresh.index('try Self.snapshotStoppedDisk()'), fresh.index('requiresFreshApply('))
        self.assertIn('"applyGuest": true', fresh)
        self.assertIn('activate()', fresh)
        self.assertIn('"systemOwner": "host-payload"', fresh)
        self.assertIn('self.finish("Guest did not become ready', source)
        self.assertIn('clonefile(Self.backup.path, restored.path, 0)', source)
        app = (MAC / 'App/main.swift').read_text()
        self.assertIn('WizardGuestActivation.shared.prepareFresh()', app)
        self.assertIn('Wizard installation needs attention', app)

    def test_payload_identity_in_signed_release(self):
        build = (MAC / 'build.sh').read_text()
        self.assertIn('r=dict(payloadID=payload_id,', build)
        self.assertIn("['payloadID'] if guest else None", build)
        sealing = (MAC.parent / 'guest/seal-runtime-payload.py').read_text()
        self.assertIn("if k!='payloadID'", sealing)
        self.assertLess(sealing.index("bom['files']="), sealing.index("bom['payloadID']="))


if __name__ == '__main__':
    unittest.main()
