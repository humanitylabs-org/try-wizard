#!/usr/bin/env python3
"""Exact scalar-only replacement for the Wizard-owned terminal key.
No stock Hermes execution or implementation edits. Preserve all other bytes,
comments, YAML style and user-owned terminal routes. Ambiguity fails closed.
"""
import copy
import json
from pathlib import Path
import yaml

OLD = '/opt/data/.ssh-vm/id_ed25519'
NEW = '/opt/agent-ssh/id_ed25519'


def migrate(text):
    before = yaml.safe_load(text)
    if not isinstance(before, dict): raise ValueError('Not a config mapping')
    terminal = before.get('terminal') or {}
    if not (terminal.get('backend') == 'ssh' and terminal.get('ssh_host') == 'wizard-vm'
            and terminal.get('ssh_user') == 'wizard' and str(terminal.get('ssh_port',22)) == '22'
            and terminal.get('ssh_key') in (OLD,NEW)):
        return text, {'changed': False, 'explicit_route_preserved': True}
    if terminal['ssh_key'] == NEW: return text, {'changed': False, 'already_migrated': True}
    root = yaml.compose(text)
    nodes = [v for k,v in root.value if k.value == 'terminal']
    if len(nodes)!=1 or not isinstance(nodes[0],yaml.MappingNode): raise ValueError('Ambiguous terminal')
    keys = [v for k,v in nodes[0].value if k.value == 'ssh_key']
    if len(keys)!=1 or not isinstance(keys[0],yaml.ScalarNode): raise ValueError('Ambiguous key')
    node = keys[0]; scalar = text[node.start_mark.index:node.end_mark.index]
    if scalar not in (OLD, '"'+OLD+'"', "'"+OLD+"'"): raise ValueError('Aliases/tags/complex scalar not supported')
    updated = text[:node.start_mark.index] + scalar.replace(OLD,NEW) + text[node.end_mark.index:]
    expected = copy.deepcopy(before); expected['terminal']['ssh_key'] = NEW
    if yaml.safe_load(updated) != expected: raise ValueError('Unexpected config change')
    return updated, {'changed': True, 'other_bytes_unchanged': True, 'only_change': 'terminal.ssh_key'}


def apply(path):
    # write through the existing inode, preserving UID/GID/mode; stopped snapshot
    # protects an interrupted write. Do not print config or credential values.
    raw = path.read_bytes(); text = raw.decode('utf-8')
    updated, receipt = migrate(text)
    if updated != text:
        with path.open('r+b') as f:
            f.write(updated.encode()); f.truncate(); f.flush()
            import os
            os.fsync(f.fileno())
    return receipt


if __name__ == '__main__':
    import sys
    print(json.dumps(apply(Path(sys.argv[1]))))
