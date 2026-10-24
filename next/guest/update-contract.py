#!/usr/bin/env python3
"""Shared guest admission policy; no mutation, subprocesses or core Hermes changes."""
import json
from pathlib import Path

LEGACY_ABI = {'0.3.0': 0, '0.4.0': 1, '0.4.1': 1}
SUPPORTED = {'min': 0, 'max': 1}


def image_abi(manifest):
    if 'guestABI' in manifest:
        abi = manifest['guestABI']
        if type(abi) is not int:
            raise ValueError('guestABI must be an integer')
    else:
        abi = LEGACY_ABI.get(manifest.get('version'))
    if abi not in (0, 1):
        raise ValueError('Unsupported guestABI; update Wizard before using this image')
    return abi


def admit_payload(bom, abi):
    bounds = bom.get('guestABI', {})
    lo, hi = bounds.get('min'), bounds.get('max')
    if type(abi) is not int or type(lo) is not int or type(hi) is not int or not 0 <= lo <= hi <= 1 or not lo <= abi <= hi:
        raise ValueError('Payload guestABI range does not admit this disk')


def read_platform(path, admitted_abi):
    """Modern factory writes a platform marker; legacy disks use Host admission."""
    path = Path(path)
    abi = image_abi(json.loads(path.read_text())) if path.exists() else admitted_abi
    if abi != admitted_abi:
        raise ValueError('Host and guest guestABI disagree')
    return abi
