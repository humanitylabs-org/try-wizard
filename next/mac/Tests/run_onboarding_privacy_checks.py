#!/usr/bin/env python3
"""Native-only extracted production routing/consent tests. No real GUI/VM/defaults.

Models Documents denied by counting any attempt to consult a host share during
routing. Does NOT claim a real macOS TCC denial or runtime mount was exercised.
"""
import argparse
from pathlib import Path
import platform
import subprocess
import tempfile
from test_host_launch_errors import body


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument('--expect-baseline', action='store_true')
    args = p.parse_args()
    if platform.system() != 'Darwin':
        p.error('macOS native job required')
    source = (args.source_root / 'App/main.swift').read_text()
    names = ['begin()', 'showChooser()', 'chooseThisMac()', 'chooseRemote()',
             'askFilesFolder(sizeNote: String? = nil)', 'chooseFilesFolder()',
             'setFilesFolder(_ url: URL)', 'backToChooser()']
    extracted = []
    for name in names:
        signature = 'func ' + name
        extracted.append(('@objc ' if name in ['chooseThisMac()', 'chooseRemote()', 'chooseFilesFolder()', 'backToChooser()'] else '') + signature + ' {' + body(source, signature) + '}')
    for name, fallback in [('startFreshOnboarding()', 'begin()'), ('cancelFilesFolder()', 'loadHome()')]:
        signature = 'func ' + name
        extracted.append('@objc ' + signature + ' {' + (body(source, signature) if signature in source else fallback) + '}')
    template = Path(__file__).with_name('OnboardingPrivacy.swift.in').read_text()
    fixture = template.replace('// PRODUCTION_METHODS', '\n'.join(extracted))
    admission = 'func admitSharedFolderRestart(_ done: @escaping (Bool) -> Void)'
    # Baseline had no admission guard; keep its absence explicit in the model.
    admission_body = body(source, admission) if admission in source else 'controller.admitUpdateRestart(done)'
    fixture = fixture.replace('// PRODUCTION_ADMISSION', admission + ' {' + admission_body + '}')
    shared = (args.source_root / 'Shared/Shared.swift').read_text()
    persisted = 'static var filesFolder: URL? {' + body(shared, 'static var filesFolder: URL?') + '}\n'
    persisted += 'static func setFilesFolder(_ url: URL) throws {' + body(shared, 'static func setFilesFolder(_ url: URL)') + '}\n'
    fixture = fixture.replace('// PRODUCTION_PERSISTENCE', persisted)
    host = (args.source_root / 'Host/main.swift').read_text()
    host_share = 'if let folder = WizardShared.filesFolder {' + body(host, 'if let folder = WizardShared.filesFolder') + '}'
    fixture = fixture.replace('// PRODUCTION_HOST_SHARE', host_share)
    with tempfile.TemporaryDirectory(prefix='wizard-onboarding-') as directory:
        root = Path(directory)
        swift = root / 'main.swift'; swift.write_text(fixture)
        exe = root / 'onboarding-checks'
        subprocess.run(['xcrun', 'swiftc', '-swift-version', '5', str(swift), '-o', str(exe)], check=True, timeout=60)
        result = subprocess.run([str(exe), str(root / 'home')], text=True, capture_output=True, timeout=15)
        print(result.stdout, end=''); print(result.stderr, end='')
        if args.expect_baseline:
            assert result.returncode == 1, ('baseline must fail behavior assertions', result.returncode)
            for name in ['local-no-share', 'abandoned-local', 'first-explicit-share-cancel', 'start-fresh']:
                assert 'FAIL ' + name in result.stdout, name
            print('BASELINE_REGRESSIONS_CONFIRMED')
        else:
            assert result.returncode == 0, result.returncode


if __name__ == '__main__':
    main()
