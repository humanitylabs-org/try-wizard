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

def prepare_dark(assets):
    """Maintenance only: scale the preserved approved compositor output, never redraw.

    Native builds need only the stdlib packer and committed hash-checked PNGs.
    Pillow is an explicit asset-maintenance dependency, not a build dependency.
    """
    from PIL import Image, __version__
    assert __version__ == '12.3.0', 'Use the provenance-pinned Pillow version'
    target = assets/'dark'
    provenance = json.loads((target/'provenance.json').read_text())
    source = (target/'originals/wizard-ux-icon-512.png').read_bytes()
    assert hashlib.sha256(source).hexdigest() == '228489a32e0c6e0d7e668e7cbe752fbfd6bfc9c8de23b45552325ab23bc91481'
    with Image.open(target/'originals/wizard-ux-icon-512.png') as image:
        rgba = image.convert('RGBA')
        for size in sorted(set(size for _, size in REPRESENTATIONS)):
            name = 'wizard-icon-%d.png' % size
            output = target/name
            if size == 512:
                output.write_bytes(source)
            else:
                rgba.resize((size,size),Image.Resampling.LANCZOS).save(output)
            assert hashlib.sha256(output.read_bytes()).hexdigest() == provenance['generated_sha256'][name], name


def pack(assets, output, dark=False):
    manifest = json.loads((assets / 'provenance.json').read_text())['generated_sha256']
    # Native-only variant; existing PWA/guest/QEMU inputs remain byte-identical.
    icon_assets = assets / 'dark' if dark else assets
    icon_manifest = json.loads((icon_assets / 'provenance.json').read_text())['generated_sha256']
    if dark:
        provenance = json.loads((icon_assets / 'provenance.json').read_text())
        for name, expected in provenance['source_sha256'].items():
            assert hashlib.sha256((icon_assets/'originals'/name).read_bytes()).hexdigest() == expected, name
    chunks = []
    for kind, size in REPRESENTATIONS:
        name = 'wizard-icon-%d.png' % size
        data = (icon_assets / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == icon_manifest[name], name
        assert data[:8] == b'\x89PNG\r\n\x1a\n', name
        assert struct.unpack('>II', data[16:24]) == (size, size), name
        chunks.append(kind + struct.pack('>I', len(data)+8) + data)
    for name in ('wizard-mark-purple.png','wizard-mark-white.png'):
        assert hashlib.sha256((assets/name).read_bytes()).hexdigest() == manifest[name], name
    body = b''.join(chunks)
    output.write_bytes(b'icns' + struct.pack('>I',len(body)+8) + body)
    print('BRAND_ICON_OK', hashlib.sha256(output.read_bytes()).hexdigest())

if __name__ == '__main__':
    if sys.argv[1] == '--prepare-dark':
        prepare_dark(Path(sys.argv[2]))
    else:
        pack(Path(sys.argv[1]), Path(sys.argv[2]), dark='--dark' in sys.argv[3:])
