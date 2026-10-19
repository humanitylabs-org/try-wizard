#!/usr/bin/env python3
"""Durable Thales job: exact native307 build, then no-GUI real acceptance.
Parent submits; no nested locks, factory build, publication or GUI launch.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import signal
import subprocess
import sys

sys.dont_write_bytecode = True
from build_driver import PRODUCTION, SOURCES


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def clean_pin(path, pin):
    assert path.resolve().is_relative_to('/Volumes/ThalesMedia')
    assert subprocess.check_output(['git', '-C', path, 'rev-parse', 'HEAD'], text=True).strip() == pin
    assert not subprocess.check_output(['git', '-C', path, 'status', '--porcelain'], text=True).strip()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--spec', type=Path, required=True)
    p.add_argument('--worker-lease', choices=['inherited'], required=True)
    a = p.parse_args()
    spec = json.loads(a.spec.read_text())
    harness = Path(__file__).resolve().parents[4]
    source = Path(spec['productionDir'])
    root = Path(spec['evidenceRoot'])
    app = Path(spec['candidateApp'])
    assert os.uname().sysname == 'Darwin'
    assert spec['sourceDir'] == str(harness) and spec['productionSource'] == PRODUCTION
    clean_pin(harness, spec['harnessSource']); clean_pin(source, PRODUCTION)
    assert root.resolve().is_relative_to('/Volumes/ThalesMedia') and not root.exists()
    assert app.parent == Path('/Applications') and not app.exists()
    # No relabelled old binary: both build and driver sources must be exact pins.
    source_hashes = {}
    for name in SOURCES + ['next/mac/build.sh']:
        pinned = subprocess.check_output(['git', '-C', source, 'show', PRODUCTION+':'+name])
        assert (source/name).read_bytes() == pinned == (harness/name).read_bytes(), name
        source_hashes[name] = hashlib.sha256(pinned).hexdigest()
    root.mkdir(mode=0o700)
    os.umask(0o077)
    env = dict(os.environ, PATH='/opt/homebrew/bin:'+os.environ['PATH'],
               TMPDIR='/Volumes/ThalesMedia/tmp', PYTHONDONTWRITEBYTECODE='1',
               UV_CACHE_DIR='/Volumes/ThalesMedia/tmp/uv-cold-cache',
               UV_PYTHON_INSTALL_DIR='/Volumes/ThalesMedia/tmp/uv-cold-python',
               CLANG_MODULE_CACHE_PATH=str(root/'module-cache'))
    report = {'productionSource':PRODUCTION, 'harnessSource':spec['harnessSource'],
              'sourceSHA256':source_hashes, 'specSHA256':sha(a.spec), 'build':'307',
              'success':False, 'factoryRebuilt':False, 'published':False,
              'GUIStarted':False, 'checks':[], 'phase':'fixtures'}
    def save():
        (root/'result.json').write_text(json.dumps(report, indent=2)+'\n')
    def check(name, argv, timeout=180):
        with (root/(name+'.log')).open('w') as log:
            child = subprocess.Popen(list(map(str, argv)), env=env, stdout=log, stderr=log)
            try:
                rc = child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                child.terminate()
                # The real acceptance runner owns graceful VM cleanup and keeps
                # forced exits failing. Never count a timeout as a passing phase.
                rc = child.wait(timeout=300)
                report['timedOut'] = name
            finally:
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=300)
                    except subprocess.TimeoutExpired:
                        child.kill(); child.wait()
                        report['forcedChildExit'] = name
        report['checks'].append({'name':name, 'exitCode':rc, 'logSHA256':sha(root/(name+'.log'))})
        save()
        if rc or report.get('timedOut') == name:
            raise RuntimeError(name+' failed; inspect private phase log')
    def cancelled(signum, frame):
        raise KeyboardInterrupt('Durable worker cancellation')
    signal.signal(signal.SIGTERM, cancelled)
    signal.signal(signal.SIGINT, cancelled)
    save()
    try:
        check('qa-venv', [spec['uv'], 'venv', '--python', spec['python'], root/'venv'])
        python = root/'venv/bin/python'
        check('qa-deps', [spec['uv'], 'pip', 'install', '--python', python, 'PyYAML==6.0.3', 'Pillow==12.0.0'])
        env['PATH'] = str(root/'venv/bin')+':'+env['PATH']
        check('headless-contracts', [python, '-m', 'unittest', 'discover',
              '-s', harness/'next/mac/Tests/HeadlessCold', '-p', 'test_*.py', '-v'])
        mac = source/'next/mac'
        check('cold-serial', [python, mac/'Tests/test_cold_serial.py', '--out', root/'serial'])
        check('update-shutdown', [python, harness/'next/mac/Tests/test_update_shutdown.py', '--out', root/'shutdown'])
        check('guest-policy', [python, source/'next/guest/tests/test_cold_bootstrap.py'])
        check('guest-permissions', [python, source/'next/guest/tests/test_patch_permissions.py'])
        check('process-identity', [python, mac/'Tests/test_legacy_process_identity.py'])
        check('compile-admission', ['xcrun','swiftc','-swift-version','5','-target','arm64-apple-macos14.0',mac/'Shared/UpdateContract.swift',mac/'Tests/LegacyAdmission/main.swift','-o',root/'admission'])
        check('admission', [root/'admission',root/'admission-data'])
        check('compile-activation', ['xcrun','swiftc','-swift-version','5','-target','arm64-apple-macos14.0',mac/'Shared/DiskIdentity.swift',mac/'App/WizardGuestActivation.swift',mac/'Tests/GuestActivation/main.swift','-framework','AppKit','-o',root/'activation'])
        check('activation', [root/'activation',root/'activation-data'])
        frozen = Path(spec['frozenPayload']); payload = root/'payload'
        check('clone-sealed-payload', ['/bin/cp','-cR',frozen,payload])
        bom = json.loads((payload/'runtime-bom.json').read_text())
        # Verify the frozen BOM before making the bounded source/BOM update.
        for name, digest in bom['files'].items():
            assert sha(payload/name) == digest, 'Frozen BOM mismatch: '+name
        report['runtimeArchives'] = {}
        for name in ('wizard-shell.tar','wizard-hermes-managed.tar'):
            digest = sha(payload/name)
            assert digest == sha(frozen/name)
            report['runtimeArchives'][name] = digest
        for name in ('upgrade-mvp-stack.py','cold-bootstrap.py','cold-config.py'):
            relative = 'source/next/guest/'+name
            target = payload/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source/'next/guest'/name, target)
            bom['files'][relative] = sha(target)
        # The config expectation is tied to the actual sealed writer, not merely
        # a same-named file in our checkout. Frozen WAM/archives stay unchanged.
        product = 'overlay/opt/wizard/bin/wizard-product-configure'
        assert (payload/product).read_bytes() == (source/'next/guest'/product).read_bytes()
        bom['sources']['COLD_BOOTSTRAP'] = PRODUCTION
        (payload/'runtime-bom.json').write_text(json.dumps(bom,sort_keys=True)+'\n')
        public = plistlib.loads((Path(spec['publicApp'])/'Contents/Info.plist').read_bytes())
        env.update(VER='0.7.0', BUILD='307', SPARKLE_DIR=spec['sparkle'],
                   SPARKLE_PUBLIC_KEY=public['SUPublicEDKey'],
                   SPARKLE_FEED='https://downloads.aiwizards.com/mac/appcast.xml',
                   GUEST_UPDATE_PAYLOAD=str(payload), RELEASE_ID=PRODUCTION, SIGN_IDENTITY='-', DMG='0')
        report['phase'] = 'native-build'; save()
        check('native307-build', ['bash',mac/'build.sh'], 1200)
        check('install-owned-candidate', ['/bin/cp','-cR',mac/'dist/Wizard.app',app])
        check('candidate-signature', ['codesign','--verify','--deep','--strict',app])
        release = json.loads((app/'Contents/Resources/wizard-release.json').read_text())
        assert release['releaseID'] == PRODUCTION and release['build'] == '307'
        info = plistlib.loads((app/'Contents/Info.plist').read_bytes())
        assert info['SUPublicEDKey'] == public['SUPublicEDKey']
        assert info['SUFeedURL'] == env['SPARKLE_FEED']
        assert info['SURequireSignedFeed'] and info['SUVerifyUpdateBeforeExtraction']
        assert not info['SUAutomaticallyUpdate']
        report['candidateApp'] = str(app)
        report['releaseManifestSHA256'] = sha(app/'Contents/Resources/wizard-release.json')
        # Separate exact-pin headless entrypoint; never legacy061_probe's GUI path.
        child_spec = dict(spec, evidenceRoot=str(root/'headless'))
        child_spec_path = root/'headless-spec.json'
        child_spec_path.write_text(json.dumps(child_spec,indent=2)+'\n')
        report['phase'] = 'headless-real-acceptance'; save()
        check('headless-real', [python,harness/'next/mac/Tests/HeadlessCold/run.py',
                               '--spec',child_spec_path,'--worker-lease','inherited'], 14400)
        real = json.loads((root/'headless/report.json').read_text())
        assert real['success'] and real['cleanupVerified']
        assert real['productionReleaseID'] == PRODUCTION and real['harnessSource'] == spec['harnessSource']
        clean_pin(source, PRODUCTION); clean_pin(harness, spec['harnessSource'])
        report['success'] = True
        report['phase'] = 'headless-accepted-not-release-accepted'
    except BaseException as error:
        report['phase'] = 'failed'; report['error'] = type(error).__name__+': '+str(error)
        raise
    finally:
        save()
    print(json.dumps({'success':True,'report':str(root/'result.json'),'releaseAccepted':False}))


if __name__ == '__main__':
    main()
