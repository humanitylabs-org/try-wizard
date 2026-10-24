import unittest
from test_guest_abi import MAC


class SparkleFirstContract(unittest.TestCase):
    def test_download_waits_for_update_check(self):
        source = (MAC / 'App/main.swift').read_text()
        entry = source[source.index('func installOnThisMac()'):source.index('private func installOSAfterAppCheck()')]
        self.assertIn('checkBeforeOSDownload', entry)
        self.assertIn('if proceed { self.installOSAfterAppCheck() }', entry)
        self.assertNotIn('installer.install()', entry)
        self.assertIn('No OS download has started.', entry)

    def test_compatible_sparkle_offer_and_offline_choice(self):
        source = (MAC / 'App/WizardUpdater.swift').read_text()
        self.assertIn('updater.checkForUpdates(); return', source)
        self.assertIn('contract.supportedGuestABI', source)
        self.assertIn('guard range.contains(abi)', source)
        self.assertIn('Update Wizard First', source)
        self.assertIn('reply(.dismiss); complete(true); return', source)
        self.assertIn('complete(false)', source)
        self.assertIn('Continue with This App', source)
        self.assertIn('complete(alert.runModal() == .alertSecondButtonReturn)', source)
        self.assertIn('finishFirstInstallCheck(unavailable: false)', source)
        self.assertIn('finishFirstInstallCheck(unavailable: true)', source)


if __name__ == '__main__':
    unittest.main()
