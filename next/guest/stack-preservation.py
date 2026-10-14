"""Hash-only preservation checks; no credential values in receipts.

Only stock auth-store save metadata is volatile. Every other leaf (including
provider/account IDs, access/refresh/API credentials and pool membership) and
all container structure remain protected. Unknown refresh mutations fail closed.
"""
import hashlib
import json

VOLATILE_PATHS = frozenset({'/updated_at'})

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def auth_snapshot(doc):
    leaves = {}
    def visit(value, path):
        if isinstance(value, dict):
            leaves[path + '/@shape'] = digest(['dict', sorted(value)])
            for key, child in value.items():
                visit(child, path + '/' + key.replace('~', '~0').replace('/', '~1'))
        elif isinstance(value, list):
            leaves[path + '/@shape'] = digest(['list', len(value)])
            for index, child in enumerate(value):
                visit(child, path + '/' + str(index))
        else:
            leaves[path + '/@type'] = digest(type(value).__name__)
            leaves[path] = digest([type(value).__name__, value])
    visit(doc, '')
    stable = {k: v for k, v in leaves.items() if k not in VOLATILE_PATHS}
    return {'file_semantic_sha256': digest(leaves), 'stable_identity_credentials_sha256': digest(stable), 'field_hashes': leaves}

def compare_auth(before, after):
    b, a = before['field_hashes'], after['field_hashes']
    changed = sorted(k for k in set(b) | set(a) if b.get(k) != a.get(k))
    volatile = [k for k in changed if k in VOLATILE_PATHS and k in b and k in a]
    unexpected = [k for k in changed if k not in volatile]
    return {'stable_identity_credentials_preserved': not unexpected,
            'volatile_field_changes': [{'path': k, 'before_sha256': b[k], 'after_sha256': a[k]} for k in volatile],
            'unexpected_field_changes': [{'path': k, 'before_sha256': b.get(k), 'after_sha256': a.get(k)} for k in unexpected]}
