#!/usr/bin/env python3
"""Immutable PR35 Thales verification. Native only: no guest/DMG/release/deploy."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import signal
import subprocess
import sys

SOURCE = Path('/Volumes/ThalesMedia/Development/try-wizard-29')
BASELINE = Path('/Volumes/ThalesMedia/Development/try-wizard-29-baseline')
ROOT = SOURCE / 'evidence/pr29-final'
REV = '51e2c4ffc4f377f087201c831a47704371095901'
BASE_REV = '75c1f19'
SPARKLE = Path('/Volumes/ThalesMedia/Projects/wizard-desktop/mac-mvp-fix-round-20261014/updater/sparkle')
PY = Path('/Volumes/ThalesMedia/launch-lanes/L5/mac/venv/bin/python3')


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def git(*args, cwd=SOURCE):
    return subprocess.check_output(['git', *args], cwd=cwd, text=True).strip()


def manifest():
    return {name: sha(SOURCE / name) for name in git('ls-files').splitlines()}


def main():
    assert os.uname().sysname == 'Darwin'
    assert git('rev-parse', 'HEAD') == REV
    assert git('diff', 'HEAD', '--name-only') == ''
    assert git('rev-parse', 'HEAD', cwd=BASELINE).startswith(BASE_REV)
    assert sha(SPARKLE / 'Sparkle-2.10.0.tar.xz') == 'c2bf58aa8387266ac179357b1415d6f2635f044da8be41042af32425dae6da0c'
    ROOT.mkdir(parents=True, exist_ok=False)
    (ROOT / 'tmp').mkdir()
    (ROOT / 'modules').mkdir()
    env = dict(os.environ, PATH=f'{PY.parent}:/opt/homebrew/bin:' + os.environ['PATH'],
               TMPDIR=str(ROOT / 'tmp'), PYTHONDONTWRITEBYTECODE='1',
               WIZARD_WORK_ROOT=str(ROOT), CLANG_MODULE_CACHE_PATH=str(ROOT / 'modules'),
               SWIFT_MODULECACHE_PATH=str(ROOT / 'modules'), SWIFTPM_MODULECACHE_OVERRIDE=str(ROOT / 'modules'))
    env.pop('GUEST_UPDATE_PAYLOAD', None)
    result = {'source': REV, 'baseline': git('rev-parse', 'HEAD', cwd=BASELINE),
              'scope': 'native App/Host build and source/fixture tests, no guest image, DMG, publication or deployment',
              'steps': [], 'factoryRebuilt': False, 'dmgBuilt': False, 'published': False,
              'notProven': ['physical macOS permission dialog', 'actual VM delayed boot', 'live installation']}
    before = manifest()
    (ROOT / 'source-manifest.json').write_text(json.dumps(before, indent=2) + '\n')

    def save():
        (ROOT / 'result.json').write_text(json.dumps(result, indent=2) + '\n')

    def run(name, argv, cwd=SOURCE, timeout=300, allowed_failure=False, overrides=None):
        child_env = dict(env)
        child_env.update(overrides or {})
        log = ROOT / f'{name}.log'
        with log.open('w') as f:
            p = subprocess.Popen(list(map(str, argv)), cwd=cwd, env=child_env,
                                 stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
            timed_out = False
            try:
                rc = p.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(p.pid, signal.SIGTERM)
                try:
                    rc = p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid, signal.SIGKILL)
                    rc = p.wait(timeout=10)
        step = {'name': name, 'exitCode': rc, 'timedOut': timed_out, 'log': str(log), 'logSHA256': sha(log)}
        result['steps'].append(step)
        save()
        print(json.dumps(step), flush=True)
        if timed_out or (rc != 0 and not allowed_failure):
            raise RuntimeError(f'{name} failed; see {log}')
        return rc

    save()
    try:
        mac = SOURCE / 'next/mac'
        run('boot-wait', [PY, mac/'Tests/test_cold_boot_wait.py', '--out', ROOT/'boot-wait'])
        run('cold-serial', [PY, mac/'Tests/test_cold_serial.py', '--out', ROOT/'cold-serial'])
        run('shutdown', [PY, mac/'Tests/test_update_shutdown.py', '--out', ROOT/'shutdown'])
        run('compile-activation', ['xcrun', 'swiftc', '-swift-version', '5', '-target', 'arm64-apple-macos14.0',
                                   mac/'Shared/DiskIdentity.swift', mac/'App/WizardGuestActivation.swift',
                                   mac/'Tests/GuestActivation/main.swift', '-framework', 'AppKit', '-o', ROOT/'activation'])
        run('activation', [ROOT/'activation', ROOT/'activation-data'])
        public = plistlib.loads(Path('/Applications/Wizard Final306.app/Contents/Info.plist').read_bytes())['SUPublicEDKey']
        run('native-build', ['bash', mac/'build.sh'], timeout=1200,
            overrides={'SPARKLE_DIR': str(SPARKLE), 'SPARKLE_PUBLIC_KEY': public,
                       'SPARKLE_FEED': 'https://downloads.aiwizards.com/mac/appcast.xml',
                       'DMG': '0', 'BUILD': '390', 'VER': '0.7.0', 'RELEASE_ID': REV, 'SIGN_IDENTITY': '-'})
        result['nativeBinaries'] = {str(p.relative_to(SOURCE)): sha(p) for p in [
            mac/'dist/Wizard.app/Contents/MacOS/Wizard',
            mac/'dist/Wizard.app/Contents/Library/LoginItems/Wizard Host.app/Contents/MacOS/Wizard Host']}
        # Known broad-suite failures are retained in full, not renamed as green.
        for name, cwd in [('baseline-make-test', BASELINE), ('candidate-make-test', SOURCE)]:
            work = ROOT/name
            work.mkdir()
            (work/'tmp').mkdir()
            run(name, ['make', 'test'], cwd=cwd, timeout=1800, allowed_failure=True,
                overrides={'WIZARD_WORK_ROOT': str(work), 'TMPDIR': str(work/'tmp')})
        result['broadSuiteFailures'] = {}
        for name in ['baseline-make-test', 'candidate-make-test']:
            text = (ROOT/f'{name}.log').read_text(errors='replace')
            failed = re.findall(r"Test Case '([^']+)' failed", text)
            error_lines = [line for line in text.splitlines() if ('error:' in line or ' failed' in line or 'FAILED' in line)]
            result['broadSuiteFailures'][name] = {'failedTestCases': sorted(set(failed)), 'errorLines': error_lines}
        base_cases = result['broadSuiteFailures']['baseline-make-test']['failedTestCases']
        candidate_cases = result['broadSuiteFailures']['candidate-make-test']['failedTestCases']
        result['additionalXCTestFailures'] = sorted(set(candidate_cases) - set(base_cases))
        result['sourceUnchanged'] = manifest() == before and git('rev-parse', 'HEAD') == REV
        assert result['sourceUnchanged'], 'source drifted during checks'
        result['focusedPass'] = True
        result['broadSuiteGreen'] = all(s['exitCode'] == 0 for s in result['steps'] if s['name'].endswith('make-test'))
        result['needsBroadFailureReview'] = not result['broadSuiteGreen']
        result['state'] = 'completed'
        save()
        print(json.dumps(result, indent=2))
    except BaseException as e:
        result.update(state='failed', error=f'{type(e).__name__}: {e}')
        save()
        raise


if __name__ == '__main__':
    main()
