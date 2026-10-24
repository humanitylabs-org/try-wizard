#!/usr/bin/env python3
"""Read-only App Manager invariants around system payload apply."""
import json
import subprocess

SYSTEM_SERVICES = frozenset(('hermes-agent-engine', 'hermes-agent', 'wizard-shell', 'transcriber-engine',
                             'runtipi', 'runtipi-db', 'runtipi-queue', 'runtipi-reverse-proxy'))


def apps(rows):
    result = {}
    for row in rows:
        service = (row['Config'].get('Labels') or {}).get('com.docker.compose.service', '')
        if service in SYSTEM_SERVICES:
            continue
        # Unknown containers are apps, not implicitly payload-owned.
        result[row['Id']] = {'name': row['Name'], 'image': row['Image'], 'config': row['Config'],
                             'mounts': row['Mounts'], 'running': row['State']['Running']}
    return result


def inventory():
    ids = subprocess.check_output(['docker', 'ps', '-aq'], text=True).split()
    return apps(json.loads(subprocess.check_output(['docker', 'inspect', *ids], text=True))) if ids else {}


def assert_stopped(rows):
    if any(row['running'] for row in rows.values()):
        raise RuntimeError('App Manager apps must remain stopped during system payload apply')


def assert_unchanged(before, after):
    assert_stopped(before); assert_stopped(after)
    if before != after:
        raise RuntimeError('System payload touched an App Manager container, image or volume')


def assert_running_after(before, after):
    for cid, row in before.items():
        if row['running'] and (cid not in after or not after[cid]['running']):
            raise RuntimeError('Previously running app did not resume: ' + row['name'])
