#!/usr/bin/env python3
"""Fast policy/config checks. No VM, daemon, Docker, or owner data touched."""
import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

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
    def test_commit_required_for_other_apps(self):
        self.assertFalse(G.authorize(self.request('/containers/old/start'),self.policy,lambda _:self.old))
        self.policy['phase']='committed'
        self.assertTrue(G.authorize(self.request('/containers/old/start'),self.policy,lambda _:self.old))
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
