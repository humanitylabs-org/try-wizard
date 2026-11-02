import importlib.util
import pathlib
import plistlib
import types
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('native_qa_launch', pathlib.Path(__file__).parents[1] / 'tools/native_qa_launch.py')
assert spec is not None and spec.loader is not None
launch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launch)


class InstalledLaunchTests(unittest.TestCase):
    def test_background_first_gui_launch_not_direct_executable(self):
        self.assertEqual(launch.launch_command('/Applications/Wizard.app', 501),
                         ['/usr/bin/sudo', '-n', '/bin/launchctl', 'asuser', '501',
                          '/usr/bin/sudo', '-n', '-u', '#501', '/usr/bin/open', '-g', '-j', '/Applications/Wizard.app'])

    def test_user_app_install_is_allowed(self):
        p = pathlib.Path.home() / 'Applications/Wizard.app'
        self.assertEqual(launch.launch_command(p, 501)[-1], str(p))

    def test_external_build_or_relative_or_executable_is_not_installation(self):
        for path in ('Wizard.app', '/Volumes/QA/Wizard.app', '/Applications/Wizard.app/Contents/MacOS/Wizard'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                launch.launch_command(path, 501)

    def test_non_user_uid_is_rejected(self):
        for uid in (0, -1, True, '501'):
            with self.subTest(uid=uid), self.assertRaises(ValueError):
                launch.launch_command('/Applications/Wizard.app', uid)

    @patch.object(launch.subprocess, 'run')
    @patch.object(launch.os, 'stat', return_value=types.SimpleNamespace(st_uid=502))
    @patch.object(launch.os, 'getuid', return_value=501)
    def test_never_launches_in_another_console_owners_session(self, uid, stat, run):
        with self.assertRaises(RuntimeError): launch.launch_installed('/Applications/Wizard.app')
        run.assert_not_called()

    @patch.object(launch.subprocess, 'run')
    @patch.object(launch.pathlib.Path, 'read_bytes', return_value=plistlib.dumps({'CFBundleIdentifier': 'foreign.app'}))
    @patch.object(launch.os, 'stat', return_value=types.SimpleNamespace(st_uid=501))
    @patch.object(launch.os, 'getuid', return_value=501)
    def test_foreign_bundle_is_refused(self, uid, stat, read, run):
        with self.assertRaises(ValueError): launch.launch_installed('/Applications/Wizard.app')
        run.assert_not_called()

    @patch.object(launch.subprocess, 'check_output', return_value=plistlib.dumps({'IOConsoleLocked': False, 'IOConsoleUsers': [{'kCGSSessionUserIDKey': 501, 'kCGSSessionOnConsoleKey': True}]}))
    @patch.object(launch.subprocess, 'run')
    @patch.object(launch.pathlib.Path, 'read_bytes', return_value=plistlib.dumps({'CFBundleIdentifier': launch.APP_ID}))
    @patch.object(launch.os, 'stat', return_value=types.SimpleNamespace(st_uid=501))
    @patch.object(launch.os, 'getuid', return_value=501)
    def test_signature_verification_precedes_launch_and_no_privacy_commands(self, uid, stat, read, run, registry):
        launch.launch_installed('/Applications/Wizard.app')
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0], ['/usr/bin/codesign', '--verify', '--deep', '--strict', '/Applications/Wizard.app'])
        self.assertEqual(run.call_args_list[1].args[0], launch.launch_command('/Applications/Wizard.app', 501))

    def test_unlocked_selected_console_is_accepted(self):
        data = {'IOConsoleLocked': False, 'IOConsoleUsers': [{'kCGSSessionUserIDKey': 501, 'kCGSSessionOnConsoleKey': True}]}
        self.assertTrue(launch.console_unlocked(data, 501))
        self.assertTrue(launch.console_unlocked([data], 501))

    def test_locked_or_unknown_or_other_console_is_rejected(self):
        for data in ({}, {'IOConsoleLocked': True},
                     {'IOConsoleLocked': False, 'IOConsoleUsers': []},
                     {'IOConsoleLocked': False, 'IOConsoleUsers': [{'kCGSSessionUserIDKey': 502, 'kCGSSessionOnConsoleKey': True}]},
                     {'IOConsoleLocked': False, 'IOConsoleUsers': [{'kCGSSessionUserIDKey': 501, 'kCGSSessionOnConsoleKey': False}]},
                     {'IOConsoleLocked': False, 'IOConsoleUsers': [{'kCGSSessionUserIDKey': 501, 'kCGSSessionOnConsoleKey': True, 'CGSSessionScreenIsLocked': True}]}):
            with self.subTest(data=data): self.assertFalse(launch.console_unlocked(data, 501))

    @patch.object(launch.subprocess, 'check_output', return_value=plistlib.dumps({'IOConsoleLocked': True}))
    @patch.object(launch.subprocess, 'run')
    @patch.object(launch.pathlib.Path, 'read_bytes', return_value=plistlib.dumps({'CFBundleIdentifier': launch.APP_ID}))
    @patch.object(launch.os, 'stat', return_value=types.SimpleNamespace(st_uid=501))
    @patch.object(launch.os, 'getuid', return_value=501)
    def test_locked_console_launch_fails_before_signature_or_process_start(self, uid, stat, read, run, registry):
        with self.assertRaisesRegex(RuntimeError, 'Unlock the Mac console'):
            launch.launch_installed('/Applications/Wizard.app')
        run.assert_not_called()


if __name__ == '__main__': unittest.main()
