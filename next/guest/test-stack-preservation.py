import base64
import copy
import datetime
import time
import importlib.util
import pathlib
import unittest

spec=importlib.util.spec_from_file_location('preservation',pathlib.Path(__file__).with_name('stack-preservation.py'))
assert spec is not None and spec.loader is not None
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
class PreservationTests(unittest.TestCase):
 def setUp(self):
  self.base={'updated_at':'2026-10-14T00:00:00Z','active_provider':'nous','providers':{'nous':{'account_id':'qa-fixture-account','access_token':'fixture-access','refresh_token':'fixture-refresh'}},'credential_pool':{'nous':[{'id':'fixture-pool','api_key':'fixture-key'}]}}
 def check(self,doc):return p.compare_auth(p.auth_snapshot(self.base),p.auth_snapshot(doc))
 def test_equal_and_formatting(self):self.assertTrue(self.check(copy.deepcopy(self.base))['stable_identity_credentials_preserved'])
 def test_stock_save_timestamp(self):
  doc=copy.deepcopy(self.base);doc['updated_at']='2026-10-14T00:01:00Z';r=self.check(doc)
  self.assertTrue(r['stable_identity_credentials_preserved']);self.assertEqual([c['path'] for c in r['volatile_field_changes']],['/updated_at'])
  self.assertNotIn(doc['updated_at'],str(r))
 def test_token_mutation_fails(self):
  for field in ['account_id','access_token','refresh_token']:
   doc=copy.deepcopy(self.base);doc['providers']['nous'][field]='changed-fixture'
   self.assertFalse(self.check(doc)['stable_identity_credentials_preserved'])
 def test_pool_replacement_fails(self):
  doc=copy.deepcopy(self.base);doc['credential_pool']['nous'][0]['id']='replacement'
  self.assertFalse(self.check(doc)['stable_identity_credentials_preserved'])
 def test_provider_deletion_fails(self):
  doc=copy.deepcopy(self.base);del doc['providers']['nous'];self.assertFalse(self.check(doc)['stable_identity_credentials_preserved'])
 def test_unknown_metadata_fails(self):
  doc=copy.deepcopy(self.base);doc['last_refresh']='new';self.assertFalse(self.check(doc)['stable_identity_credentials_preserved'])
 def test_volatile_removal_or_type_mutation_fails(self):
  for value in [None,123,{}]:
   doc=copy.deepcopy(self.base);doc['updated_at']=value;self.assertFalse(self.check(doc)['stable_identity_credentials_preserved'])
  doc=copy.deepcopy(self.base);del doc['updated_at'];self.assertFalse(self.check(doc)['stable_identity_credentials_preserved'])
 def test_secret_free_report(self):
  doc=copy.deepcopy(self.base);doc['providers']['nous']['access_token']='changed-fixture';r=str(self.check(doc));self.assertNotIn('changed-fixture',r);self.assertNotIn('fixture-access',r)
class NousRefreshTests(unittest.TestCase):
 def grant(self,old=True,subject='fixture-account'):
  now=int(time.time());issued=now-3600 if old else now;expiry=now-10 if old else now+900
  enc=lambda v:base64.urlsafe_b64encode(p.json.dumps(v).encode()).decode().rstrip('=')
  token=enc({'alg':'fixture-only'})+'.'+enc({'sub':subject,'aud':'fixture-inference','iss':'fixture-issuer','iat':issued,'exp':expiry})+'.fixture-signature'
  iso=lambda v:datetime.datetime.fromtimestamp(v,datetime.timezone.utc).isoformat()
  provider={'auth_method':'anonymous','anon_token':'fixture-permanent-anon','client_id':'fixture-client','user_id':'fixture-account','org_id':'fixture-org','access_token':token,'agent_key':token,'expires_at':iso(expiry),'agent_key_expires_at':iso(expiry),'expires_in':max(0,expiry-now),'agent_key_expires_in':max(0,expiry-now),'obtained_at':iso(issued),'agent_key_obtained_at':iso(issued)}
  row={**provider,'id':'fixture-pool-id','request_count':0,'last_status_at':float(issued)}
  return {'updated_at':iso(issued),'active_provider':'nous','providers':{'nous':provider},'credential_pool':{'nous':[row]}}
 def check(self,b,a):return p.compare_auth(p.auth_snapshot(b),p.auth_snapshot(a))
 def test_observed_anonymous_grant_refresh(self):
  r=self.check(self.grant(),self.grant(False));self.assertTrue(r['stable_identity_credentials_preserved']);self.assertTrue(r['nous_anonymous_invoke_refresh_verified'])
 def test_permanent_anon_material_remains_protected(self):
  b=self.grant();a=self.grant(False)
  a['providers']['nous']['anon_token']=a['credential_pool']['nous'][0]['anon_token']='changed-permanent-fixture'
  self.assertFalse(self.check(b,a)['stable_identity_credentials_preserved'])
 def test_pool_identity_remains_protected(self):
  b=self.grant();a=self.grant(False);a['credential_pool']['nous'][0]['id']='replacement'
  self.assertFalse(self.check(b,a)['stable_identity_credentials_preserved'])
 def test_other_provider_key_remains_protected(self):
  b=self.grant();a=self.grant(False)
  b['providers']['openrouter']={'api_key':'fixture-one'};a['providers']['openrouter']={'api_key':'fixture-two'}
  self.assertFalse(self.check(b,a)['stable_identity_credentials_preserved'])
 def test_wrong_jwt_account_fails(self):self.assertFalse(self.check(self.grant(),self.grant(False,'other-account'))['stable_identity_credentials_preserved'])
 def test_unexpected_nonexpiring_rotation_fails(self):
  b=self.grant(False);a=self.grant(False)
  # Keep subject, but rotate the token outside the observed expiring-grant path.
  a['providers']['nous']['access_token']=a['providers']['nous']['agent_key']=a['credential_pool']['nous'][0]['access_token']=a['credential_pool']['nous'][0]['agent_key']=a['providers']['nous']['access_token']+'changed-fixture'
  self.assertFalse(self.check(b,a)['stable_identity_credentials_preserved'])
 def test_unmirrored_refresh_fails(self):
  b=self.grant();a=self.grant(False);a['credential_pool']['nous'][0]['agent_key']='unmirrored-fixture'
  self.assertFalse(self.check(b,a)['stable_identity_credentials_preserved'])
 def test_unknown_credential_field_remains_protected(self):
  b=self.grant();a=self.grant(False);a['providers']['nous']['new_secret']='new-fixture'
  self.assertFalse(self.check(b,a)['stable_identity_credentials_preserved'])
 def test_snapshot_is_secret_free(self):
  doc=self.grant();snapshot=str(p.auth_snapshot(doc));self.assertNotIn('fixture-permanent-anon',snapshot);self.assertNotIn(doc['providers']['nous']['access_token'],snapshot)
if __name__=='__main__':unittest.main()
