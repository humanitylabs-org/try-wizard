"""Hash-only preservation: pin permanent credentials and identities; audit stock refresh.

Unknown providers/mutations fail closed. The sole token-rotation exception is the
observed stock Nous anonymous invoke-JWT flow, with pinned anon refresh material,
pool membership, client/account/config identity, matching JWT identity claims,
provider/pool mirrors and fresh jointly changed grant timestamps. Expiry-triggered
and stock force-refresh turnover are both supported; an unaccompanied token change
is rejected.
No credential bytes are returned or written by this module. JWT identity/expiry
checks are metadata invariants, not a signature-verifier replacement; the pinned
stock runtime produces the grant and real model acceptance verifies usability.
"""
import base64
import datetime
import hashlib
import json
import time

VOLATILE_PATHS = frozenset({'/updated_at'})
NOUS_BASES = ('/providers/nous', '/credential_pool/nous/0')
GRANT_FIELDS = ('access_token', 'agent_key', 'expires_at', 'expires_in', 'obtained_at',
                'agent_key_expires_at', 'agent_key_expires_in', 'agent_key_obtained_at')
GRANT_PATHS = frozenset(base+'/'+field for base in NOUS_BASES for field in GRANT_FIELDS)
TELEMETRY_PATHS = frozenset('/credential_pool/nous/0/'+field for field in ('last_status_at','request_count'))
CLEAR_STATUS_PATHS = frozenset('/credential_pool/nous/0/'+field for field in
    ('last_status','last_status_at','last_error_code','last_error_message','last_error_reason','last_error_reset_at'))
CLEAR_STATUS_TYPE_PATHS = frozenset(path+'/@type' for path in CLEAR_STATUS_PATHS)
TTL_PATHS = frozenset(base+'/'+field for base in NOUS_BASES for field in ('expires_in','agent_key_expires_in'))

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def _epoch(value):
    return datetime.datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()

def _nous_evidence(doc):
    try:
        provider=doc['providers']['nous']; pool=doc['credential_pool']['nous']
        if len(pool)!=1: return {'eligible':False}
        row=pool[0]
        eligible=(provider.get('auth_method')==row.get('auth_method')=='anonymous' and
                  isinstance(provider.get('anon_token'),str) and bool(provider['anon_token']) and
                  provider['anon_token']==row.get('anon_token') and
                  bool(provider.get('client_id')) and provider['client_id']==row.get('client_id') and
                  bool(row.get('id')))
        token=provider['access_token']
        parts=token.split('.')
        if len(parts)!=3 or not all(parts):return {'eligible':False}
        claims=json.loads(base64.urlsafe_b64decode(parts[1]+'='*(-len(parts[1])%4)))
        exp=claims['exp']; now=time.time()
        if not isinstance(exp,(int,float)) or not isinstance(claims,dict):return {'eligible':False}
        identity={k:v for k,v in claims.items() if k not in ('exp','iat','nbf','jti')}
        mirrors=(all(field in provider and field in row and provider[field]==row[field] for field in GRANT_FIELDS) and
                 provider['access_token']==provider['agent_key'])
        fresh=(exp>now and abs(_epoch(provider['expires_at'])-exp)<2 and
               abs(_epoch(provider['agent_key_expires_at'])-exp)<2 and
               now-600<=_epoch(provider['agent_key_obtained_at'])<=now+60)
        return {'eligible':bool(eligible and identity),'grant_mirrors':bool(mirrors),
                'jwt_identity_sha256':digest(identity),'jwt_identity_field_names':sorted(identity),
                'jwt_identity_field_hashes':{k:digest(v) for k,v in identity.items()},
                'old_grant_expiring':exp<=now+180,'fresh_current_grant_metadata':bool(fresh)}
    except (KeyError,TypeError,ValueError,AttributeError):
        return {'eligible':False}

def auth_snapshot(doc):
    leaves = {}
    def visit(value, path):
        if isinstance(value, dict):
            leaves[path + '/@shape'] = digest(['dict', sorted(value)])
            for key, child in value.items():
                visit(child, path + '/' + key.replace('~', '~0').replace('/', '~1'))
        elif isinstance(value, list):
            leaves[path + '/@shape'] = digest(['list', len(value)])
            for index, child in enumerate(value):visit(child, path + '/' + str(index))
        else:
            leaves[path + '/@type'] = digest(type(value).__name__)
            leaves[path] = digest([type(value).__name__, value])
    visit(doc, '')
    nous=_nous_evidence(doc)
    exclusions=VOLATILE_PATHS | (GRANT_PATHS|TELEMETRY_PATHS|CLEAR_STATUS_PATHS|CLEAR_STATUS_TYPE_PATHS if nous.get('eligible') else frozenset())
    stable = {k: v for k, v in leaves.items() if k not in exclusions}
    return {'file_semantic_sha256':digest(leaves),'stable_identity_credentials_sha256':digest(stable),
            'field_hashes':leaves,'nous_refresh_evidence':nous}

def compare_auth(before, after):
    b,a=before['field_hashes'],after['field_hashes']
    changed=sorted(k for k in set(b)|set(a) if b.get(k)!=a.get(k))
    bn,an=before.get('nous_refresh_evidence',{}),after.get('nous_refresh_evidence',{})
    possible=VOLATILE_PATHS|GRANT_PATHS|TELEMETRY_PATHS|CLEAR_STATUS_PATHS|CLEAR_STATUS_TYPE_PATHS
    stable_unchanged=all(b.get(k)==a.get(k) for k in (set(b)|set(a))-possible)
    pinned=(stable_unchanged and bn.get('eligible') and an.get('eligible') and bn.get('grant_mirrors') and
            an.get('grant_mirrors') and bn.get('jwt_identity_sha256')==an.get('jwt_identity_sha256'))
    token_changed=b.get('/providers/nous/access_token')!=a.get('/providers/nous/access_token')
    fresh_obtained=(b.get('/providers/nous/agent_key_obtained_at')!=a.get('/providers/nous/agent_key_obtained_at') and
                    b.get('/providers/nous/obtained_at')!=a.get('/providers/nous/obtained_at'))
    rotation=bool(pinned and token_changed and fresh_obtained and an.get('fresh_current_grant_metadata'))
    allowed=set(VOLATILE_PATHS)
    if pinned:
        allowed.update(TELEMETRY_PATHS)
        if rotation:
            allowed.update(GRANT_PATHS)
            # Stock _CLEAR_STATUS invalidates stale health/error telemetry on
            # token turnover. Only clearing existing scalar fields to null is
            # permitted; new values, deleted keys and shapes remain protected.
            for path in CLEAR_STATUS_PATHS:
                if path in b and path in a and a[path]==digest(['NoneType',None]):
                    allowed.update((path,path+'/@type'))
        elif not token_changed:allowed.update(TTL_PATHS)
    volatile=[k for k in changed if k in allowed and k in b and k in a]
    unexpected=[k for k in changed if k not in volatile]
    return {'stable_identity_credentials_preserved':not unexpected,
            'nous_anonymous_invoke_refresh_accounted':rotation,
            'permanent_identity_pinned':bool(pinned),
            'volatile_field_changes':[{'path':k,'before_sha256':b[k],'after_sha256':a[k]} for k in volatile],
            'unexpected_field_changes':[{'path':k,'before_sha256':b.get(k),'after_sha256':a.get(k)} for k in unexpected]}
