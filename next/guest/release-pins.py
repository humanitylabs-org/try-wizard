#!/usr/bin/env python3
"""Validate the single Mac release input manifest (no network or side effects)."""
import argparse
import hashlib
import json
import re
import shlex
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def load(path):
    pins = json.loads(Path(path).read_text())
    selected = pins['runtimeSelected']
    sources = pins['sourceInputs']
    result = {}
    for key in ('ux', 'service', 'wam'):
        item = sources[selected[key]]
        if not SHA.fullmatch(item['commit']):
            raise ValueError('full immutable commit required: ' + key)
        result[key] = item['commit']
    result['source'] = sources['native']['commit']
    if not SHA.fullmatch(result['source']):
        raise ValueError('full immutable native commit required')
    installer = pins['osInstaller']
    expected = f"https://raw.githubusercontent.com/humanitylabs-org/wizard-app-manager/{result['wam']}/get.sh"
    if installer['url'] != expected or not re.fullmatch('[0-9a-f]{64}', installer['sha256']):
        raise ValueError('os.sh must name the selected WAM commit and a sha256')
    build = pins['runtimeBuild']
    if not DIGEST.fullmatch(build['baseImageId']):
        raise ValueError('base image must be content addressed')
    for key in ('wamImage', 'hermesImage'):
        if not re.fullmatch(r'[a-z0-9./_-]+@sha256:[0-9a-f]{64}', build[key]):
            raise ValueError('image digest required: ' + key)
    version = pins['factory']['version']
    if version != '0.5.0':
        raise ValueError('this recipe admits factory 0.5.0 only')
    return pins, result


def shell(path):
    p, s = load(path)
    env = {'VERSION': p['factory']['version'], 'WAM_COMMIT': s['wam'],
           'WAM_IMAGE': p['runtimeBuild']['wamImage'], 'HERMES_IMAGE': p['runtimeBuild']['hermesImage'],
           'OS_SH_URL': p['osInstaller']['url'], 'OS_SH_SHA256': p['osInstaller']['sha256'],
           'WIZARD_RELEASE': json.loads((Path(path).parent / p['wizardOsCandidate']['path']).read_text())['version'],
           'WIZARD_RELEASE_BASE': 'file:///var/lib/wizard/frozen-release'}
    return '\n'.join(k + '=' + shlex.quote(v) for k, v in env.items())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pins', type=Path)
    parser.add_argument('--shell', action='store_true')
    a = parser.parse_args()
    if a.shell:
        print(shell(a.pins))
    else:
        p, sources = load(a.pins)
        print(json.dumps({'sources': sources, 'manifestSha256': hashlib.sha256(a.pins.read_bytes()).hexdigest()}))


if __name__ == '__main__':
    main()
