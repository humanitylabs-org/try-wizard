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
    p.add_argument('--expect-baseline', action='store_true',
                   help='d22dcd5 baseline: the four original onboarding behaviours must fail')
    p.add_argument('--expect-fail', action='append', default=[], metavar='CHECK',
                   help='any other baseline: EXACTLY these named checks must FAIL (it must compile and run)')
    p.add_argument('--legacy-shared', type=Path, default=Path(__file__).with_name('fixtures') / 'legacy-d22dcd5-Shared.swift',
                   help="the PRIOR build's Shared.swift, used only to seed files-folder.json exactly as it wrote it")
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
    begin, end = '// MARK: files-share-decision begin', '// MARK: files-share-decision end'
    candidate_share = begin in shared
    if candidate_share:
        # Whole production decision region (raw/explicit/legacy/active accessors + setFilesFolder), verbatim.
        start = shared.index('\n', shared.index(begin)) + 1
        persisted = shared[start:shared.index(end)] + '\n'
    else:
        persisted = 'static var filesFolder: URL? {' + body(shared, 'static var filesFolder: URL?') + '}\n'
        persisted += 'static func setFilesFolder(_ url: URL) throws {' + body(shared, 'static func setFilesFolder(_ url: URL)') + '}\n'
    fixture = fixture.replace('// PRODUCTION_PERSISTENCE', persisted)
    legacy = args.legacy_shared.read_text()
    writer = 'static func setFilesFolder(_ url: URL) throws {' + body(legacy, 'static func setFilesFolder(_ url: URL)') + '}\n'
    fixture = fixture.replace('// PRODUCTION_LEGACY_WRITER', writer)
    host = (args.source_root / 'Host/main.swift').read_text()
    add_share = 'func addFilesShare(to c: VZVirtualMachineConfiguration)'
    if add_share in host:
        host_share = add_share + ' {' + body(host, add_share) + '}\n'
    else:   # eeb4770 and older: the decision was inline in makeConfiguration
        inline = 'if let folder = WizardShared.filesFolder {' + body(host, 'if let folder = WizardShared.filesFolder') + '}'
        host_share = add_share + ' {\n' + inline + '\n}\n'
    fixture = fixture.replace('// PRODUCTION_HOST_SHARE', host_share)
    if candidate_share:
        fixture = fixture.replace('// PRODUCTION_ACTIVE_MOCK', """static var activeSharedFolder: URL? { shareReads += 1; return usePersisted ? PersistedShare.activeSharedFolder : share }
    static var legacyAutoShareIgnored: Bool { usePersisted ? PersistedShare.legacyAutoShareIgnored : false }""")
        fixture = fixture.replace('// PRODUCTION_ACTIVE_CHECKS', """do {
    _ = try seedLegacyAutoShare(legacyDefault); resetSpies(); _ = shareConfiguration()
    check("test_boot_decision_consults_legacy_default_only_as_a_path_string", PersistedShare.defaultFilesFolderReads >= 1 && touchedUnder(legacyDefault).isEmpty)
    _ = try seedLegacyAutoShare(legacyDefault)
    check("test_legacy_share_is_saved_but_not_active_for_boot_or_finder",
          PersistedShare.filesFolder != nil && PersistedShare.activeSharedFolder == nil
          && PersistedShare.legacyAutoShareIgnored && !PersistedShare.filesFolderIsExplicit)
    try freshSupport(); try PersistedShare.setFilesFolder(legacyDefault)
    check("test_explicit_marker_makes_legacy_path_active",
          PersistedShare.activeSharedFolder?.path == legacyDefault.path && PersistedShare.filesFolderIsExplicit && !PersistedShare.legacyAutoShareIgnored)
}""")
    with tempfile.TemporaryDirectory(prefix='wizard-onboarding-') as directory:
        root = Path(directory)
        swift = root / 'main.swift'; swift.write_text(fixture)
        exe = root / 'onboarding-checks'
        subprocess.run(['xcrun', 'swiftc', '-swift-version', '5', str(swift), '-o', str(exe)], check=True, timeout=60)
        result = subprocess.run([str(exe), str(root / 'home')], text=True, capture_output=True, timeout=15)
        print(result.stdout, end=''); print(result.stderr, end='')
        fails = sorted(line.split(' ', 1)[1] for line in result.stdout.splitlines() if line.startswith('FAIL '))
        compiled_and_ran = 'RESULT ' in result.stdout
        if args.expect_fail:
            # Baseline must compile and run; the ONLY failures are the named behavioural ones.
            assert compiled_and_ran and result.returncode == 1, ('baseline must run and fail behaviour', result.returncode)
            assert fails == sorted(args.expect_fail), ('unexpected failure set', fails, sorted(args.expect_fail))
            print('BASELINE_REGRESSIONS_CONFIRMED ' + ','.join(fails))
        elif args.expect_baseline:
            assert result.returncode == 1, ('baseline must fail behavior assertions', result.returncode)
            for name in ['local-no-share', 'abandoned-local', 'first-explicit-share-cancel', 'start-fresh']:
                assert 'FAIL ' + name in result.stdout, name
            print('BASELINE_REGRESSIONS_CONFIRMED')
        else:
            assert result.returncode == 0 and not fails, (result.returncode, fails)
            required = ['test_upgrade_with_legacy_default_share_does_not_touch_documents', 'test_explicit_share_is_honored_on_relaunch',
                        'test_other_path_legacy_share_is_honored', 'test_explicit_share_carries_explicit_marker',
                        'test_access_detector_catches_a_legacy_folder_create_and_mount',
                        'test_legacy_share_is_saved_but_not_active_for_boot_or_finder',
                        'test_boot_decision_consults_legacy_default_only_as_a_path_string']
            for name in required:
                assert 'PASS ' + name in result.stdout, ('required check missing', name)
            print('CANDIDATE_ALL_CHECKS_PASSED %d' % result.stdout.count('PASS '))

if __name__ == '__main__':
    main()
