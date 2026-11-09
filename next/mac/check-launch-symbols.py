#!/usr/bin/env python3
"""Fail the build when a binary hard-links a symbol that macOS 14 doesn't have.

The app declares macOS 14.0 as its minimum. A symbol the binary links as required (not weak) must
exist on every macOS it launches on: if dyld can't find it, macOS kills the app before any of our
code runs, and `#available` / `@available` checks can't help.

Apple's SDK labels some Swift overlay APIs older than the OS that ships them. Known case: the
SDK's `CATapDescription` Swift initializers (`excludingProcesses:deviceUID:stream:` and friends) are
labelled macOS 14.0, but `excludingProcesses:deviceUID:stream:` only exists in
/usr/lib/swift/libswiftCoreAudio.dylib from macOS 15. Wizard 0.7.0 crashed at launch on macOS 14.3
because of it. Use the Objective-C initializers (`CATapDescription(__excludingProcesses:...)`)
instead: they are plain message sends and add no Swift symbol.

Usage: check-launch-symbols.py <binary>...   (runs `xcrun nm -m` on each)
"""
import re
import subprocess
import sys

# Swift overlay symbols that must never be linked as required: (prefix, why).
FORBIDDEN = [
    ('_$sSo16CATapDescriptionC9CoreAudioE',
     'CATapDescription Swift overlay API (some of it is missing in macOS 14\'s libswiftCoreAudio); '
     'use the Objective-C initializer, e.g. CATapDescription(__excludingProcesses:andDeviceUID:withStream:)'),
]

UNDEFINED = re.compile(r'^\s*\(undefined\) (weak )?external (\S+)(?: \(from (\S+)\))?')


def violations(nm_output):
    """Required (non-weak) imports in `nm -m` output that match FORBIDDEN, as (symbol, library, why)."""
    found = []
    for line in nm_output.splitlines():
        m = UNDEFINED.match(line)
        if not m or m.group(1):
            continue
        for prefix, why in FORBIDDEN:
            if m.group(2).startswith(prefix):
                found.append((m.group(2), m.group(3) or '?', why))
    return found


def main(paths):
    if not paths:
        print('Usage: check-launch-symbols.py <binary>...', file=sys.stderr)
        return 2
    bad = 0
    for path in paths:
        out = subprocess.run(['xcrun', 'nm', '-m', path], check=True, capture_output=True, text=True).stdout
        for sym, lib, why in violations(out):
            bad += 1
            print(f'{path}: links {sym} (from {lib}) as required; it would stop the app launching on macOS 14.\n'
                  f'  {why}', file=sys.stderr)
    if bad:
        return 1
    print(f'launch symbols OK ({len(paths)} binaries)')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
