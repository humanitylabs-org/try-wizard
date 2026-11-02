#!/usr/bin/env python3
"""Execute the unchanged production boot-wait method with isolated console/status I/O.

The 200-second pre-boot wait models a delayed macOS folder permission response;
this is not a physical permission-dialog or VM acceptance test.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--source', type=Path, help='production activation source (for before/after reproduction)')
    parser.add_argument('--expect-stale-bypass', action='store_true', help='expect the unfixed PR race')
    args = parser.parse_args()
    mac = Path(__file__).resolve().parents[1]
    source = args.source or mac / 'App/WizardGuestActivation.swift'
    production = source.read_text()
    method = production[production.index('    private var waitingNoticeShown'):production.index('    private func waitColdStarted(')]
    root = Path(os.environ.get('WIZARD_WORK_ROOT') or tempfile.gettempdir()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    out = args.out.resolve() if args.out else Path(tempfile.mkdtemp(prefix='cold-boot-wait-', dir=root))
    out.mkdir(parents=True, exist_ok=True)
    assert os.uname().sysname == 'Darwin', 'Swift regression must run on macOS'
    template = (mac / 'Tests/ColdBootWait/main.swift').read_text()
    fixture = template.replace('// PRODUCTION_WAIT', method)
    (out / 'main.swift').write_text(fixture)
    subprocess.run(['xcrun', 'swiftc', '-swift-version', '5', '-module-cache-path', str(out / 'module-cache'),
                    str(out / 'main.swift'), '-o', str(out / 'probe')], check=True)
    result = subprocess.run([str(out / 'probe'), str(out / 'data'), str(args.expect_stale_bypass).lower()],
                            capture_output=True, text=True)
    (out / 'stdout.log').write_text(result.stdout)
    (out / 'stderr.log').write_text(result.stderr)
    stale = None
    for line in result.stdout.splitlines():
        if line.startswith('STALE_VERDICT_STARTS_150S_BUDGET='):
            stale = line.split('=', 1)[1] == 'true'
    receipt = {'scope': 'unchanged production waitColdBoot; isolated file/status I/O and captured scheduling; no real permission dialog or VM',
               'production_sha256': hashlib.sha256(production.encode()).hexdigest(),
               'method_sha256': hashlib.sha256(method.encode()).hexdigest(),
               'fixture_sha256': hashlib.sha256(fixture.encode()).hexdigest(),
               'exit_code': result.returncode, 'stdout': result.stdout,
               'stale_console_verdict_bypasses_new_boot_wait': stale}
    (out / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt))
    print(f'Receipt: {out / "result.json"}')
    result.check_returncode()


if __name__ == '__main__':
    main()
