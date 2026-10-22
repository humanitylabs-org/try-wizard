import copy
from pathlib import Path
import textwrap
import unittest

class ReceiptConsumer(unittest.TestCase):
    def test_exact_embedded_consumer(self):
        source = (Path(__file__).parents[1]/'Shared/GuestPatchCommand.swift').read_text()
        code = textwrap.dedent(source[source.index("    assert d['patch']"):source.index("    print('WIZARD_PATCH_OK")])
        good = {'patch':'mac-stack-v1', 'permanent_identity_credentials_preserved':True, 'service_image':'sha256:fixture',
                'auth':{'stable_identity_credentials_preserved':True,'unexpected_field_changes':[]},
                'env':{'stable_credentials_preserved':True,'other_bytes_unchanged':True,'managed_terminal_key_path_migrated':False},
                'protected_before_sha256':{'/data/.env':'env-old','/data/auth.json':'auth-old','/data/SOUL.md':'soul'},
                'protected_after_sha256':{'/data/.env':'env-old','/data/auth.json':'auth-new','/data/SOUL.md':'soul'}}
        exec(code, {'d':good})
        changed = copy.deepcopy(good); changed['protected_after_sha256']['/data/.env']='env-new'
        with self.assertRaises(AssertionError): exec(code, {'d':changed})
        changed['env']['managed_terminal_key_path_migrated']=True
        exec(code, {'d':changed})
        for key in ('stable_credentials_preserved','other_bytes_unchanged'):
            invalid=copy.deepcopy(changed);invalid['env'][key]=False
            with self.assertRaises(AssertionError):exec(code, {'d':invalid})
        invalid=copy.deepcopy(changed);invalid['protected_after_sha256']['/data/SOUL.md']='changed'
        with self.assertRaises(AssertionError):exec(code, {'d':invalid})
        invalid=copy.deepcopy(changed);invalid['auth']['unexpected_field_changes']=['provider']
        with self.assertRaises(AssertionError):exec(code, {'d':invalid})

if __name__ == '__main__': unittest.main()
