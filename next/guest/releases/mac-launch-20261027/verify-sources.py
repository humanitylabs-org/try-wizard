#!/usr/bin/env python3
"""Parent-submitted source verification only. Never builds/boots/publishes a guest."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage-root', type=Path, required=True)
    a = parser.parse_args()
    root = a.stage_root.resolve()
    if sys.platform != 'darwin' or not root.is_relative_to(Path(os.environ.get('THALES_MEDIA','/unconfigured-external-media'))):
        raise SystemExit('Use the Thales external-volume worker')
    checks = root / 'source-checks'
    checks.mkdir(exist_ok=False)
    env = {**os.environ, 'PATH': '/opt/homebrew/bin:' + os.environ.get('PATH', ''),
           'TMPDIR': str(checks / 'tmp')}
    Path(env['TMPDIR']).mkdir()
    result = {'guestBuildStarted': False, 'publishing': False, 'commands': []}

    def run(key, argv, cwd, timeout=300):
        log = checks / (key + '.log')
        started = time.time()
        with log.open('w') as stream:
            p = subprocess.run(list(map(str, argv)), cwd=cwd, env=env, stdout=stream,
                               stderr=subprocess.STDOUT, timeout=timeout, check=False)
        row = {'key': key, 'argv': list(map(str, argv)), 'returncode': p.returncode,
               'seconds': round(time.time() - started, 3), 'log': str(log.relative_to(root))}
        result['commands'].append(row)
        (checks / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        return p.returncode == 0

    sources = {}
    for name in ('service', 'ux', 'wam', 'native'):
        target = checks / name
        shutil.copytree(root / 'final' / name, target, symlinks=True)
        sources[name] = target
        run('git-init-' + name, ['git', 'init', '-q'], target)
        run('git-track-' + name, ['git', 'add', '-A'], target)
    service = sources['service']
    if run('service-deps', ['npm', 'ci', '--ignore-scripts', '--no-audit', '--no-fund'], service):
        run('service-vitest', ['npx', 'vitest', 'run', '--maxWorkers=4'], service, 600)
        run('service-maintenance', ['node', '--test', 'tests/maintenance.node-test.mjs',
                                  'tests/app-lifecycle.node-test.mjs', 'tests/app-view-adapters.node-test.mjs'], service)
        run('service-managed-root', ['sudo', '-n', 'env', 'TMPDIR=' + env['TMPDIR'],
                                    '/opt/homebrew/bin/python3', 'tests/managed_recovery_test.py'], service)
    run('ux-unit', ['node', '--test', *sorted(str(p.relative_to(sources['ux'])) for p in (sources['ux'] / 'tests').glob('*.test.mjs'))], sources['ux'], 180)
    venv = checks / 'venv'
    if run('wam-venv', ['/opt/homebrew/bin/python3', '-m', 'venv', venv], checks):
        py = venv / 'bin/python'
        if run('wam-deps', [py, '-m', 'pip', 'install', 'pytest==9.1.1', 'pyyaml==6.0.3', 'pyjwt==2.15.1'], checks):
            run('wam-unit', [py, '-m', 'pytest', '-q', '-rs'], sources['wam'], 600)
    native = sources['native']
    run('factory-pins', ['/opt/homebrew/bin/python3', '-m', 'unittest', 'discover', '-s', 'next/guest/tests', '-p', 'test_release_pins.py'], native)
    run('phone', ['/opt/homebrew/bin/python3', '-m', 'unittest', 'discover', '-s', 'next/guest/tests', '-p', 'test_phone_access.py'], native)
    run('stock-builder', ['/opt/homebrew/bin/python3', '-m', 'unittest', 'discover', '-s', 'next/tests', '-p', 'test_stock_builder.py'], native)
    run('factory-admission', ['/opt/homebrew/bin/python3', 'next/mac/tools/check-factory-admission.py', '--work', checks / 'factory-admission'], native, 180)
    result['passed'] = all(x['returncode'] == 0 for x in result['commands'])
    (checks / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
