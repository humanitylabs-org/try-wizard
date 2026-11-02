#!/usr/bin/env python3
"""Offline ext4 compaction. No mount, VM, image build or network access.
Run only on the sealed disposable copy after its VM has exited.
"""
import os
import re
import subprocess


def geometry(image, tools):
    text = subprocess.check_output([tools + 'dumpe2fs', str(image)], text=True,
                                   stderr=subprocess.DEVNULL, timeout=300)
    def field(name):
        match = re.search(r'^' + name + r':\s+(\d+)', text, re.M)
        assert match, 'missing ext4 field: ' + name
        return int(match[1])
    ranges = []
    for line in text.splitlines():
        if line.startswith('  Free blocks:'):
            for item in line.split(':', 1)[1].split(','):
                if item.strip():
                    a, _, b = item.strip().partition('-')
                    ranges.append((int(a), int(b or a)))
    ranges.sort()
    count, block, free = field('Block count'), field('Block size'), field('Free blocks')
    assert sum(b-a+1 for a, b in ranges) == free, 'incomplete free-block inventory'
    end = -1
    for a, b in ranges:
        assert end < a <= b < count, 'invalid/overlapping free-block range'
        end = b
    return count, block, ranges


def check(image, tools, repair=False):
    result = subprocess.run([tools + 'e2fsck', '-fy' if repair else '-fn', str(image)],
                            capture_output=True, text=True, timeout=300)
    assert result.returncode in ((0, 1) if repair else (0,)), result.stdout + result.stderr


def compact(image, tools, headroom=512 * 1024**2):
    # resize2fs -M changes metadata/data placement, so zero free blocks AFTER shrinking.
    check(image, tools, repair=True)
    subprocess.run([tools + 'resize2fs', '-M', str(image)], check=True,
                   capture_output=True, timeout=300)
    count, block, _ = geometry(image, tools)
    target = count + (headroom + block - 1) // block
    subprocess.run([tools + 'resize2fs', str(image), str(target)], check=True,
                   capture_output=True, timeout=300)
    count, block, ranges = geometry(image, tools)
    with image.open('r+b') as disk:
        disk.truncate(count * block)
        zero = bytes(8 * 1024**2)
        for a, b in ranges:
            disk.seek(a * block)
            left = (b-a+1) * block
            while left:
                n = min(left, len(zero))
                disk.write(zero[:n])
                left -= n
        disk.flush()
        os.fsync(disk.fileno())
    # Verify the zeros independently; errors/incomplete inventories fail packing.
    with image.open('rb') as disk:
        for a, b in ranges:
            disk.seek(a * block)
            left = (b-a+1) * block
            while left:
                chunk = disk.read(min(left, len(zero)))
                assert chunk and not any(chunk), 'free blocks were not zeroed'
                left -= len(chunk)
    check(image, tools)
    return {'bytes': count * block, 'freeBlocksZeroed': sum(b-a+1 for a, b in ranges),
            'blockBytes': block, 'headroomBytes': headroom}
