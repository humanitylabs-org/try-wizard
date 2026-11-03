"""Real Python import/lifecycle subprocesses; fake WAM, Docker and systemd only.
The adapter replaces sudo identity switching, never invokes a host lifecycle.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import types
import unittest
from unittest.mock import patch
import test_voice_update as fixture

u, i = fixture.u, fixture.i

FAKE = '''import json
from pathlib import Path
STORE='wizardapps'
def record(row):
    with (Path(__file__).parent.parent/'events.jsonl').open('a') as f:
        f.write(json.dumps(row)+'\\n')
class Config:
    def __init__(self): record(['Config'])
    def runtipi(self): return self
    def req(self,*args,**kwargs): record(['req',args,kwargs])
    def wait_status(self,urn,status,**kwargs): record(['wait',urn,sorted(status),kwargs])
'''

class WamRoute(unittest.TestCase):
    apply = fixture.Update.apply
    def setUp(self):
        fixture.Update.setUp(self)
        self.source=self.root/u.WAM
        (self.source/'wam/cli.py').write_text(FAKE)
        self.original_run=self.execute
        self.routes=[]
        def adapter(argv,**kwargs):
            if argv[:1]!=['sudo']: return self.original_run(argv,**kwargs)
            # Verify exact production identity/argv. Only the privilege boundary
            # is replaced; execute actual production -c body against fake WAM.
            self.assertEqual(argv[:-1],['sudo','-u','wizard','env','HOME=/home/wizard','/usr/bin/python3','-B','-E','-s','-c'])
            self.assertEqual(kwargs['cwd'],str(self.source))
            self.assertTrue(kwargs['check'])
            self.routes.append((list(argv),dict(kwargs)))
            env=dict(os.environ,HOME='/home/wizard',PYTHONPATH=str(self.base/'poison'),PYTHONDONTWRITEBYTECODE='1')
            return subprocess.run([sys.executable,'-B','-E','-s','-c',argv[-1]],env=env,**kwargs)
        self.execute=adapter
    def events(self):
        p=self.source/'events.jsonl'
        return [json.loads(s) for s in p.read_text().splitlines()] if p.exists() else []
    def snapshot(self):
        return {str(p.relative_to(self.root)):(p.read_bytes(),p.stat().st_mode & 0o777)
                for p in self.root.rglob('*') if p.is_file()}
    def test_unrelated_cwd_reproduces_original_then_canonical_route_works(self):
        unrelated=self.base/'unrelated';unrelated.mkdir()
        original=subprocess.run([sys.executable,'-E','-s','-c','from wam import cli'],cwd=unrelated,capture_output=True)
        self.assertNotEqual(original.returncode,0)
        self.assertIn(b"No module named 'wam'",original.stderr)
        route=u.wam_route(i,self.root,self.execute)
        self.assertEqual(route,self.source);self.assertEqual(self.events(),[])
        u.lifecycle(self.execute,'stop',route);u.lifecycle(self.execute,'start',route)
        self.assertEqual([e for e in self.events() if e[0]=='req'],[
            ['req',['POST','/app-lifecycle/transcriber:wizardapps/stop',{}],{'timeout':300}],
            ['req',['POST','/app-lifecycle/transcriber:wizardapps/start',{}],{'timeout':300}]])
        self.assertEqual([e for e in self.events() if e[0]=='wait'],[
            ['wait','transcriber:wizardapps',['stopped'],{'timeout':600}],
            ['wait','transcriber:wizardapps',['running'],{'timeout':600}]])
        self.assertEqual([k['timeout'] for _,k in self.routes],[30,650,650])
    def test_apply_repeat_and_explicit_recovery_share_route(self):
        before=self.binding.read_bytes()
        self.assertTrue(self.apply()['selectedImageUpdated'])
        self.assertTrue(self.apply()['alreadyInstalled'])
        self.assertTrue(u.recover(self.payload,i,self.root,self.execute)['selectedImageRolledBack'])
        self.assertEqual(self.binding.read_bytes(),before)
        self.assertEqual((self.root/i.FENCE).read_bytes(),i.FENCE_BYTES)
        actions=[e[1][1].rsplit('/',1)[1] for e in self.events() if e[0]=='req']
        self.assertEqual(actions,['stop','start','stop','start'])
        self.assertEqual(sum(c[:2]==['docker','load'] for c in self.calls),1)
    def test_missing_route_refused_before_any_mutation(self):
        (self.source/'wam/cli.py').unlink();before=self.snapshot()
        with self.assertRaisesRegex(RuntimeError,'Missing canonical'): self.apply()
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.calls,[]);self.assertEqual(self.routes,[])
        self.assertFalse((self.root/'var/lib/wizard/voice-reconcile.lock').exists())
    def test_redirected_route_refused(self):
        p=self.source/'wam/cli.py';p.unlink();p.symlink_to(self.source/'wam/__init__.py')
        with self.assertRaisesRegex(RuntimeError,'Redirected'): self.apply()
        self.assertEqual(self.calls,[]);self.assertEqual(self.routes,[])
    def test_writable_route_refused(self):
        self.source.chmod(0o777);before=self.snapshot()
        with self.assertRaisesRegex(RuntimeError,'Untrusted'): self.apply()
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.calls,[])
    def test_foreign_owner_refused_without_chown(self):
        real=Path.stat
        def stat(p,*a,**kw):
            row=real(p,*a,**kw)
            if p==self.source: return types.SimpleNamespace(st_mode=row.st_mode,st_uid=987654)
            return row
        with patch.object(Path,'stat',stat):
            with self.assertRaisesRegex(RuntimeError,'Untrusted'): self.apply()
        self.assertEqual(self.calls,[]);self.assertEqual(self.routes,[])
    def test_import_failure_refused_before_lock_fence_or_journal(self):
        (self.source/'wam/cli.py').write_text("raise ImportError('synthetic missing dependency')\n")
        before=self.snapshot()
        with self.assertRaises(subprocess.CalledProcessError): self.apply()
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.calls,[])
        self.assertFalse((self.root/'var/lib/wizard/voice-reconcile.lock').exists())
    def test_shadow_environment_cannot_substitute_wam(self):
        poison=self.base/'poison/wam';poison.mkdir(parents=True)
        (poison/'__init__.py').write_text("raise RuntimeError('poison environment imported')\n")
        self.assertEqual(u.wam_route(i,self.root,self.execute),self.source)
        self.assertEqual(self.events(),[])
    def test_apply_failure_uses_preflighted_route_for_automatic_rollback(self):
        real=self.execute
        def fail(argv,**kwargs):
            if argv[:2]==['docker','load']: raise RuntimeError('primary-load-error')
            return real(argv,**kwargs)
        self.execute=fail;before=self.binding.read_bytes()
        with self.assertRaisesRegex(RuntimeError,'primary-load-error'): self.apply()
        self.assertEqual(self.binding.read_bytes(),before)
        self.assertTrue((self.root/u.STATE/'rolled-back.json').is_file())
        self.assertEqual([e[1][1].rsplit('/',1)[1] for e in self.events() if e[0]=='req'],['stop','stop','start'])
    def test_failed_rollback_keeps_primary_exception_and_cause(self):
        real=self.execute;count=0
        def fail(argv,**kwargs):
            nonlocal count
            if argv[:2]==['docker','load']: raise ValueError('primary-load-error')
            if argv[:1]==['sudo'] and 'Config()' in argv[-1]:
                count+=1
                if count==2: raise RuntimeError('rollback-route-error')
            return real(argv,**kwargs)
        self.execute=fail
        with self.assertRaisesRegex(ValueError,'primary-load-error') as caught: self.apply()
        self.assertIsInstance(caught.exception.__cause__,RuntimeError)
        self.assertEqual(str(caught.exception.__cause__),'rollback-route-error')
        self.assertIn('rollback failed',caught.exception.__notes__[0])
        self.assertTrue((self.root/u.STATE/'journal.json').is_file())
        self.assertEqual((self.root/i.FENCE).read_bytes(),i.FENCE_BYTES)
    def test_explicit_recovery_preflights_before_mutating(self):
        self.apply();(self.source/'wam/cli.py').unlink();before=self.snapshot();calls=len(self.calls)
        with self.assertRaisesRegex(RuntimeError,'Missing canonical'):u.recover(self.payload,i,self.root,self.execute)
        self.assertEqual(self.snapshot(),before);self.assertEqual(len(self.calls),calls)
    def test_unknown_action_and_untrusted_rollback_route_refused(self):
        with self.assertRaisesRegex(RuntimeError,'Invalid voice'):u.lifecycle(self.execute,'restart',self.source)
        with self.assertRaisesRegex(RuntimeError,'Canonical WAM'):u.rollback(i,self.root,self.execute,locked=True,route=self.base)
        self.assertEqual(self.calls,[]);self.assertEqual(self.routes,[])

if __name__=='__main__':unittest.main(verbosity=2)
