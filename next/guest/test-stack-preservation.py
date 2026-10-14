import copy
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
if __name__=='__main__':unittest.main()
