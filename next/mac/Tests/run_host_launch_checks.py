#!/usr/bin/env python3
"""Execute extracted production startup code with no AppKit or actual app/VM.

Run natively only via an admitted macOS job. --emit-only is a source-generation
check that can run anywhere; it is not compilation or behavior proof.
"""
import argparse
from pathlib import Path
import platform
import subprocess
import tempfile
from test_host_launch_errors import body


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--emit-only', type=Path)
    args = parser.parse_args()
    source = (args.source_root / 'App/main.swift').read_text()
    host = 'enum HostControl {' + body(source, 'enum HostControl {') + '}\n'
    connect = 'func connectLocal() {' + body(source, 'func connectLocal()') + '}\n'
    template = Path(__file__).with_name('HostLaunch').joinpath('main.swift.in').read_text()
    fixture = template.replace('// PRODUCTION_HOSTCONTROL', host).replace('// PRODUCTION_CONNECTLOCAL', connect)
    assert fixture.count('enum HostControl {') == fixture.count('func connectLocal() {') == 1
    if args.emit_only:
        args.emit_only.write_text(fixture)
        print(f'EMITTED_ONLY (not compiled or executed): {args.emit_only}')
        return
    if platform.system() != 'Darwin':
        parser.error('Native fixture needs macOS Objective-C interop; use --emit-only elsewhere')
    with tempfile.TemporaryDirectory(prefix='wizard-host-launch-') as directory:
        root = Path(directory)
        swift = root / 'main.swift'; swift.write_text(fixture)
        binary = root / 'host-launch-checks'
        subprocess.run(['xcrun', 'swiftc', '-swift-version', '5', str(swift), '-o', str(binary)], check=True, timeout=60)
        import os
        env = dict(os.environ, WIZARD_TEST_HOME=str(root / 'isolated-home'))
        subprocess.run([str(binary)], env=env, check=True, timeout=15)


if __name__ == '__main__':
    main()
