"""Exact QA expectation for proven Mac product-enable then cold SSH migration.

Not a config writer or an allowlist of ignored keys. Replay the pinned product
serializer only when its plugin append is required; otherwise preserve every
byte. The raw hash comparison remains mandatory, including repeat and rollback.
"""
import copy
import json
import yaml


def semantic(value):
    # JSON distinguishes bool/int/null/string values unlike Python equality.
    return json.dumps(value, sort_keys=True, separators=(',', ':'), default=str)


def migrate(raw, cold_migrate):
    text = raw.decode('utf-8')
    before = yaml.safe_load(text)
    if not isinstance(before, dict):
        raise ValueError('Not a config mapping')
    doc = copy.deepcopy(before)
    plugins = doc.setdefault('plugins', {})
    if not isinstance(plugins, dict):
        raise ValueError('Unsupported plugins config')
    enabled = plugins.setdefault('enabled', [])
    if not isinstance(enabled, list):
        raise ValueError('Unsupported plugins.enabled')
    added = 'wizard-product' not in enabled
    if added:
        enabled.append('wizard-product')
        # Refuse alias side effects outside the two authorized paths. Detach the
        # intended containers independently instead of waiving their whole trees.
        intended = copy.deepcopy(before)
        intended['plugins'] = dict(before.get('plugins', {}))
        intended['plugins']['enabled'] = list(before.get('plugins', {}).get('enabled', [])) + ['wizard-product']
        if semantic(doc) != semantic(intended):
            raise ValueError('Plugin append changes aliased owner configuration')
        text = yaml.safe_dump(doc, sort_keys=False)
        if semantic(yaml.safe_load(text)) != semantic(intended):
            raise ValueError('Product serialization changes owner configuration')
    text, ssh = cold_migrate(text)
    return text.encode('utf-8'), {'productPluginAppended': added, 'ssh': ssh,
        'contract': 'wizard-product-configure append/serialization, then cold-config scalar; all resulting bytes pinned'}
