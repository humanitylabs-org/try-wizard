#!/usr/bin/env python3
"""Fast policy/config checks. No VM, daemon, Docker, or owner data touched."""
import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/(name+'.py'))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
G = load('cold-bootstrap')
C = load('cold-config')

class ColdTests(unittest.TestCase):
    def setUp(self):
        self.policy = {'phase':'fenced', 'managed':'sha256:managed', 'service':'sha256:service', 'references':{}}
        self.old = {'Image':G.STOCK,'Config':{'Labels':{'com.docker.compose.service':'hermes-agent-engine'}}}
    def request(self, path, method='POST', body=None):
        return {'RequestMethod':method,'RequestURI':'/v1.54'+path,'RequestBody':base64.b64encode(json.dumps(body or {}).encode()).decode()}
    def test_all_old_execution_routes_denied(self):
        for action in ('start','restart','unpause','exec','update'):
            self.assertFalse(G.authorize(self.request('/containers/old/'+action, body={'RestartPolicy':{'Name':'always'}}),self.policy,lambda _:self.old),action)
        for path in ('/exec/id/start','/build','/services/create','/plugins/create','/containers/old/checkpoints','/containers/old/%73tart'):
            self.assertFalse(G.authorize(self.request(path),self.policy,lambda _:self.old),path)
        self.assertFalse(G.authorize(self.request('/containers/create',body={'Image':G.STOCK,'Labels':{'com.docker.compose.service':'runtipi'}}),self.policy))
    def test_inspection_loading_cleanup_not_execution(self):
        for path in ('/images/load','/networks/create','/volumes/create'):
            self.assertTrue(G.authorize(self.request(path),self.policy),path)
        self.assertTrue(G.authorize(self.request('/containers/old/json','GET'),self.policy))
        self.assertTrue(G.authorize(self.request('/containers/old/stop'),self.policy,lambda _:self.old))
    def test_known_core_only(self):
        for s,image in G.KNOWN.items():
            c={'Image':image,'Config':{'Labels':{'com.docker.compose.service':s}}}
            self.assertEqual(G.permitted_container(c,self.policy),s.startswith('runtipi') or s=='hermes-agent',s)
    def test_managed_creation_requires_bom_and_shared_fence(self):
        body={'Image':self.policy['managed'],'Labels':{'com.docker.compose.service':'hermes-agent-engine'},'HostConfig':{}}
        self.assertFalse(G.authorize(self.request('/containers/create',body=body),self.policy))
        body['HostConfig']['Binds']=['/var/lib/wizard/managed:/wizard-managed-state:rw']
        self.assertTrue(G.authorize(self.request('/containers/create',body=body),self.policy))
        body['HostConfig']['Privileged']=True
        self.assertFalse(G.authorize(self.request('/containers/create',body=body),self.policy))
    def assert_stock_denied(self, policy):
        for action in ('start', 'restart', 'unpause', 'exec'):
            self.assertFalse(G.authorize(self.request('/containers/old/'+action), policy, lambda _: self.old), action)
        self.assertFalse(G.authorize(self.request('/containers/create', body={'Image': G.STOCK}), policy))
        self.assertFalse(G.authorize(self.request('/exec/id/start'), policy))

    def test_commit_keeps_execution_fenced(self):
        for phase in ('fenced', 'restoring', 'committed', 'unknown'):
            self.policy['phase'] = phase
            self.assert_stock_denied(self.policy)

    def test_restoration_is_exact_and_only_while_pending(self):
        cid = 'a'*64
        rp = {'Name': 'on-failure', 'MaximumRetryCount': 3}
        self.policy.update(phase='restoring', restoration={'id':cid, 'image':G.STOCK, 'service':'hermes-agent-engine', 'restart':rp})
        path = '/containers/'+cid+'/update'
        body = {'RestartPolicy':rp}
        self.assertTrue(G.authorize(self.request(path, body=body), self.policy, lambda _:self.old))
        for route, payload in ((path+'?force=1',body), ('/containers/old/update',body),
                               (path,{'RestartPolicy':{'Name':'always','MaximumRetryCount':0}}),
                               (path,{**body,'Memory':4096}), (path,{**body,'Privileged':True})):
            self.assertFalse(G.authorize(self.request(route, body=payload), self.policy, lambda _:self.old))
        self.assertFalse(G.authorize(self.request(path, body=body), self.policy, lambda _:None))
        changed = {**self.old, 'Image':'sha256:other'}
        self.assertFalse(G.authorize(self.request(path, body=body), self.policy, lambda _:changed))
        for phase in ('fenced','committed'):
            self.policy['phase']=phase
            self.assertFalse(G.authorize(self.request(path, body=body), self.policy, lambda _:self.old))

    def exercise_commit(self, fail):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            cid = 'a'*64
            rp = {'Name':'unless-stopped','MaximumRetryCount':0}
            p = {**self.policy, 'token':'test', 'containers':{cid:{'image':G.STOCK,'service':'hermes-agent-engine','restart':rp}}}
            cs = [{**self.old,'Id':cid,'State':{'Running':False}, 'Config':{'Labels':{'com.docker.compose.service':'transcriber-engine'}}},
                  {'Id':'b'*64,'Image':p['managed'],'Config':self.old['Config'],'State':{'Running':False}}]
            p['containers'][cid]['service']='transcriber-engine'
            G.write(state/'policy.json',p); G.write(state/'witness.json',{})
            G.write(state/'daemon.original.json',{'original':True})
            real_read=G.read
            def read(path):
                if str(path)=='/var/lib/wizard/managed/lease.json': return {'token':'test','phase':'held'}
                return real_read(path)
            def restore(container_id, restart):
                active=real_read(state/'policy.json')
                self.assert_stock_denied(active)
                self.assertTrue(G.authorize(self.request('/containers/'+cid+'/update',body={'RestartPolicy':rp}), active, lambda _:cs[0]))
                if fail: raise RuntimeError('injected restoration failure')
            with patch.object(G,'STATE',state), patch.object(G,'read',side_effect=read), \
                 patch.object(G,'run',side_effect=[' '.join(c['Id'] for c in cs),json.dumps(cs)]), \
                 patch.object(G.subprocess,'run',return_value=Mock(returncode=1,stderr='WIZARD_COLD_DENIED')), \
                 patch.object(G,'restore_restart',side_effect=restore), patch.object(G.shutil,'copy2') as copy:
                if fail:
                    with self.assertRaisesRegex(RuntimeError,'injected'): G.commit()
                    copy.assert_not_called()
                else:
                    G.commit()
                    copy.assert_called_once_with(state/'daemon.original.json','/etc/docker/daemon.json')
            final=real_read(state/'policy.json')
            self.assertEqual(final['phase'], 'fenced' if fail else 'committed')
            self.assertNotIn('restoration',final)
            self.assert_stock_denied(final)
            self.assertFalse(G.authorize(self.request('/containers/'+cid+'/update',body={'RestartPolicy':rp}), final, lambda _:cs[0]))

    def test_restoration_http_request_is_bounded_and_restart_only(self):
        cid='a'*64; rp={'Name':'always','MaximumRetryCount':0}
        for status in (200,500):
            with patch.object(G.http.client,'HTTPConnection') as connection, patch.object(G.socket,'socket') as socket:
                client=connection.return_value
                client.getresponse.return_value.status=status
                if status==200: G.restore_restart(cid,rp)
                else:
                    with self.assertRaisesRegex(RuntimeError,'restoration refused'): G.restore_restart(cid,rp)
                connection.assert_called_once_with('localhost',timeout=30)
                socket.return_value.settimeout.assert_called_once_with(30)
                client.request.assert_called_once_with('POST','/v1.54/containers/'+cid+'/update',json.dumps({'RestartPolicy':rp}),{'Content-Type':'application/json'})
                client.close.assert_called_once(); socket.return_value.close.assert_called_once()

    def test_real_commit_never_opens_stock_execution(self): self.exercise_commit(False)
    def test_restoration_failure_revokes_allowance_keeps_fence(self): self.exercise_commit(True)
    def test_scalar_only_byte_preservation_and_idempotence(self):
        for quote in ('', "'", '"'):
            text='# untouched\nmodel: preserve-this\nterminal:\n  backend: ssh\n  ssh_host: wizard-vm\n  ssh_user: wizard\n  ssh_key: '+quote+C.OLD+quote+' # retain comment\ncustom: [a, b]\n'
            out,report=C.migrate(text)
            self.assertEqual(out,text.replace(C.OLD,C.NEW))
            self.assertTrue(report['other_bytes_unchanged'])
            self.assertEqual(C.migrate(out)[0],out)
    def test_custom_route_preserved(self):
        text='terminal:\n  backend: ssh\n  ssh_host: elsewhere\n  ssh_key: '+C.OLD+'\n'
        self.assertEqual(C.migrate(text)[0],text)
    def test_duplicate_keys_refused(self):
        text='terminal:\n  backend: ssh\n  ssh_host: wizard-vm\n  ssh_user: wizard\n  ssh_key: '+C.OLD+'\n  ssh_key: '+C.OLD+'\n'
        with self.assertRaises(ValueError): C.migrate(text)
    def test_inventory_running_unknown_image_and_restart_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for i,s in enumerate(('runtipi','runtipi-db','runtipi-queue','wizard-shell','hermes-agent-engine')):
                p=root/f'{i:064x}';p.mkdir()
                G.write(p/'config.v2.json',{'Driver':'overlay2','Image':G.KNOWN[s],'Config':{'Labels':{'com.docker.compose.service':s}},'State':{'Running':False,'Pid':0}})
                G.write(p/'hostconfig.json',{'Runtime':'runc','RestartPolicy':{'Name':'unless-stopped','MaximumRetryCount':0}})
            rows=G.inventory(root);self.assertEqual(len(rows),5)
            self.assertTrue(all(h['RestartPolicy']['Name']=='unless-stopped' for _,_,h in rows))
            p,c,h=rows[-1];c['State']['Running']=True;G.write(p/'config.v2.json',c)
            with self.assertRaises(RuntimeError):G.inventory(root)
            c['State']['Running']=False;c['Image']='unknown';G.write(p/'config.v2.json',c)
            with self.assertRaises(RuntimeError):G.inventory(root)

if __name__ == '__main__': unittest.main()
