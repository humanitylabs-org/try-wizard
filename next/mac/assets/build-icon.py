#!/usr/bin/env python3
"""Losslessly package the supplied PNG representations; no invented paths."""
import hashlib
import json
from pathlib import Path
import struct
import sys

REPRESENTATIONS = ((b'icp4',16),(b'ic11',32),(b'icp5',32),(b'ic12',64),
                   (b'ic07',128),(b'ic13',256),(b'ic08',256),(b'ic14',512),
                   (b'ic09',512),(b'ic10',1024))

def pack(assets, output):
    manifest = json.loads((assets / 'provenance.json').read_text())['generated_sha256']
    chunks = []
    for kind, size in REPRESENTATIONS:
        name = 'wizard-icon-%d.png' % size
        data = (assets / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == manifest[name], name
        assert data[:8] == b'\x89PNG\r\n\x1a\n', name
        assert struct.unpack('>II', data[16:24]) == (size, size), name
        chunks.append(kind + struct.pack('>I', len(data)+8) + data)
    for name in ('wizard-mark-purple.png','wizard-mark-white.png'):
        assert hashlib.sha256((assets/name).read_bytes()).hexdigest() == manifest[name], name
    body = b''.join(chunks)
    output.write_bytes(b'icns' + struct.pack('>I',len(body)+8) + body)
    print('BRAND_ICON_OK', hashlib.sha256(output.read_bytes()).hexdigest())

if __name__ == '__main__':
    pack(Path(sys.argv[1]), Path(sys.argv[2]))
