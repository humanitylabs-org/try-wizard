import importlib.util,unittest
from pathlib import Path
s=importlib.util.spec_from_file_location('guard',Path(__file__).parents[1]/'stack-preservation.py');g=importlib.util.module_from_spec(s);s.loader.exec_module(g)
class EnvGuard(unittest.TestCase):
 old=b'# keep formatting\nAPI_KEY=fixture-not-a-secret\nTERMINAL_SSH_KEY=/opt/data/.ssh-vm/id_ed25519\n'
 new=old.replace(b'/opt/data/.ssh-vm/',b'/opt/agent-ssh/')
 def test_exact(self):self.assertTrue(g.compare_env(self.old,self.old)['stable_credentials_preserved'])
 def test_only_managed_path(self):self.assertTrue(g.compare_env(self.old,self.new,managed_ssh_verified=True)['managed_terminal_key_path_migrated'])
 def test_requires_live_ssh_proof(self):self.assertFalse(g.compare_env(self.old,self.new)['stable_credentials_preserved'])
 def test_credential_edit_rejected(self):self.assertFalse(g.compare_env(self.old,self.new.replace(b'fixture-not-a-secret',b'changed'),managed_ssh_verified=True)['stable_credentials_preserved'])
 def test_any_added_field_rejected(self):self.assertFalse(g.compare_env(self.old,self.new+b'OTHER=x\n',managed_ssh_verified=True)['stable_credentials_preserved'])
 def test_duplicate_path_rejected(self):self.assertFalse(g.compare_env(self.old+self.old,self.new+self.new,managed_ssh_verified=True)['stable_credentials_preserved'])
 def test_arbitrary_path_rejected(self):self.assertFalse(g.compare_env(self.old,self.old.replace(b'/opt/data/.ssh-vm/',b'/attacker/'),managed_ssh_verified=True)['stable_credentials_preserved'])
 def test_comments_pinned(self):self.assertFalse(g.compare_env(self.old,self.new.replace(b'# keep formatting',b'# changed'),managed_ssh_verified=True)['stable_credentials_preserved'])
 def test_no_other_whitespace_changes(self):self.assertFalse(g.compare_env(self.old,self.new.rstrip(),managed_ssh_verified=True)['stable_credentials_preserved'])
 def test_reverse_rejected(self):self.assertFalse(g.compare_env(self.new,self.old,managed_ssh_verified=True)['stable_credentials_preserved'])
if __name__=='__main__':unittest.main()
