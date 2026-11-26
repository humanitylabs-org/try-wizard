#!/usr/bin/env python3
"""Start free must reach Nous on every Mac guest, also one without the #158 DNS route (try-wizard#192).

A fresh Mac downloads the 0.4.0 disk, which has no /etc/systemd/resolved.conf.d/50-wizard-dns.conf; only the bundled
guest update brings it, and when that update didn't apply, the guest and the hermes-agent engine container asked the
Mac's NAT DNS alone. On a Mac whose NAT DNS truncates answers (Tailscale, #155) the free-brain call then failed with
Hermes' "The Nous service couldn't be reached". The Host now puts the same public servers on the guest's boot command
line (systemd-resolved's nameserver=), so they are there whatever the disk.

The source checks run everywhere. The live check boots a stand-in guest (next/guest/tests/dns-standin: Debian trixie
with systemd-resolved, no #158 drop-in, a fake NAT DNS that truncates every answer, Docker inside for the engine) with
and without the Host's boot arguments. It needs Docker with --privileged and internet, so it runs only with
WIZARD_DNS_LIVE=1 (about 3 minutes the first time).
"""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HOST = ROOT / 'next/mac/Host/main.swift'
APP = ROOT / 'next/mac/App/main.swift'
DNS_CONF = ROOT / 'next/guest/overlay/etc/systemd/resolved.conf.d/50-wizard-dns.conf'
STANDIN = ROOT / 'next/guest/tests/dns-standin'
# The command line the published 0.4.0 disk's manifest.json carries (os/latest.json, checked 26 Nov 2026).
DISK_040_CMDLINE = 'console=hvc0 root=/dev/vda rw quiet loglevel=3 systemd.show_status=false'


def host_dns_args():
    """The nameserver= arguments Host/main.swift adds, and the guard that keeps a disk's own."""
    source = HOST.read_text()
    m = re.search(r'if !boot\.commandLine\.contains\("nameserver="\) \{ boot\.commandLine \+= "( [^"]+)" \}', source)
    if not m:
        raise AssertionError('Host/main.swift no longer adds nameserver= to the guest boot command line')
    return m.group(1)


def boot_cmdline(manifest_cmdline):
    """What the Host boots a normal (not cold-bootstrap) disk with, following makeConfiguration()."""
    line = manifest_cmdline if manifest_cmdline is not None else 'console=hvc0 root=/dev/vda rw quiet'
    if 'nameserver=' not in line:
        line += host_dns_args()
    return line


class HostBootDNS(unittest.TestCase):
    def test_host_adds_public_dns_after_the_disk_cmdline(self):
        source = HOST.read_text()
        start = source.index('private func makeConfiguration()')
        body = source[start:source.index('let c = VZVirtualMachineConfiguration()', start)]
        manifest = body.index('boot.commandLine = (manifest["cmdline"] as? String)')
        dns = body.index('if !boot.commandLine.contains("nameserver=")')
        cold = body.index('if let token = WizardShared.coldBootstrapToken')
        self.assertLess(manifest, dns)
        self.assertLess(dns, cold, 'the cold bootstrap keeps its fixed command line')

    def test_old_disk_gets_the_same_servers_as_the_158_route(self):
        line = boot_cmdline(DISK_040_CMDLINE)
        servers = re.findall(r'nameserver=(\S+)', line)
        conf = re.search(r'^DNS=(.+)$', DNS_CONF.read_text(), re.M).group(1).split()
        self.assertEqual(servers, conf, 'keep the boot arguments and 50-wizard-dns.conf in step')
        self.assertTrue(line.startswith(DISK_040_CMDLINE + ' '))
        # No Domains=~. equivalent: the NAT DNS keeps answering tailnet names (#158).
        self.assertNotIn('domain=', line)

    def test_a_disk_that_sets_its_own_nameserver_keeps_it(self):
        own = DISK_040_CMDLINE + ' nameserver=192.0.2.1'
        self.assertEqual(boot_cmdline(own), own)


class SetupWindowStays(unittest.TestCase):
    """Before setup is done, opening a view or an app keeps the window on setup instead of a blank page."""
    def setUp(self):
        self.app = APP.read_text()

    def block(self, start, end):
        i = self.app.index(start)
        return self.app[i:self.app.index(end, i)]

    def test_shows_local_setup_means_the_setup_origin(self):
        prop = self.block('var showsLocalSetup: Bool {', 'var isTrustedDocument: Bool {')
        self.assertIn('Store.active?.kind == .thisMac', prop)
        self.assertIn('NativeOrigin(WizardShared.localSetupURL)', prop)
        self.assertIn('return origin == setup', prop)

    def test_open_view_stays_on_setup(self):
        body = self.block('func openView(_ path: String) {', 'func applicationShouldHandleReopen')
        stay = body.index('if controller.showsLocalSetup {')
        self.assertLess(body.index('showMainWindow()'), stay)
        self.assertLess(stay, body.index('controller.uxSend("wizard:open"'))
        self.assertLess(stay, body.index('self?.controller.load(url)'))

    def test_app_link_stays_on_setup(self):
        body = self.block('func application(_ application: NSApplication, open urls: [URL]) {', '@MainActor @objc func addAppsToDock')
        self.assertLess(body.index('if controller.showsLocalSetup { showMainWindow(); continue }'),
                        body.index('WizardAppWindows.shared.open('))


def docker(*args, **kw):
    return subprocess.run(['docker', *args], capture_output=True, text=True, **kw)


@unittest.skipUnless(os.environ.get('WIZARD_DNS_LIVE') == '1' and shutil.which('docker'),
                     'live stand-in guest: set WIZARD_DNS_LIVE=1 (needs Docker --privileged and internet)')
class StandInGuestWithoutRoute(unittest.TestCase):
    IMAGE = 'try-wizard-192-dns-standin'

    @classmethod
    def setUpClass(cls):
        build = docker('build', '-q', '-t', cls.IMAGE, str(STANDIN), timeout=900)
        if build.returncode:
            raise unittest.SkipTest('stand-in image did not build: ' + build.stderr[-300:])
        cls.tmp = tempfile.mkdtemp(prefix='tw192-dns-')
        if docker('pull', '-q', 'alpine:3', timeout=300).returncode or \
                docker('save', '-o', os.path.join(cls.tmp, 'alpine.tar'), 'alpine:3').returncode:
            raise unittest.SkipTest('could not fetch alpine:3 for the engine stand-in')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(getattr(cls, 'tmp', ''), ignore_errors=True)

    def boot(self, extra_args):
        name = 'try-wizard-192-dns-%d' % os.getpid()
        docker('rm', '-f', name)
        run = docker('run', '-d', '--name', name, '--privileged', '--cgroupns=host', '--dns', '127.0.0.53',
                     '-v', '/sys/fs/cgroup:/sys/fs/cgroup:rw', '--tmpfs', '/run', '--tmpfs', '/run/lock',
                     '-v', '%s:/standin:ro' % STANDIN, '-v', '%s:/standin-image:ro' % self.tmp,
                     self.IMAGE, '/lib/systemd/systemd', *extra_args)
        self.assertEqual(run.returncode, 0, run.stderr)
        try:
            for _ in range(30):
                if docker('exec', name, 'systemctl', 'is-active', 'systemd-resolved').stdout.strip() == 'active':
                    break
                subprocess.run(['sleep', '1'])
            out = docker('exec', name, 'bash', '/standin/probe.sh', timeout=300).stdout
        finally:
            docker('rm', '-f', name)
        print(out)
        return dict(line.split(': ', 1) for line in out.splitlines() if ': ' in line)

    def test_free_brain_lookup_fails_without_and_works_with_the_host_args(self):
        # Inside a container systemd reads PID 1's arguments as the kernel command line.
        before = self.boot([])
        self.assertEqual(before['engine-dns'].split(), [before['engine-dns'].split()[0]], 'only the NAT DNS')
        self.assertEqual(before['guest-lookup'], 'failed')
        self.assertEqual(before['engine-lookup'], 'failed', 'the case Start free reported as unreachable')

        args = boot_cmdline(DISK_040_CMDLINE).split()
        after = self.boot([a for a in args if a.startswith('nameserver=')])
        self.assertEqual(after['engine-dns'].split()[:2], ['1.1.1.1', '9.9.9.9'])
        self.assertEqual(after['guest-lookup'], 'ok')
        self.assertEqual(after['engine-lookup'], 'ok')
        self.assertEqual(after['engine-https'], '200')


if __name__ == '__main__':
    unittest.main()
