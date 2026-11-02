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
        return {'RequestMethod':method,'RequestUri':'/v1.54'+path,'RequestBody':base64.b64encode(json.dumps(body or {}).encode()).decode()}
    def test_docker_wire_json_through_real_http_handler(self):
        # Docker AuthZ API wire names (RequestUri, not Go field RequestURI).
        # Literal wire envelopes deliberately do not use the policy-test helper.
        import http.client, http.server, threading
        with tempfile.TemporaryDirectory() as tmp, patch.object(G, 'STATE', Path(tmp)):
            G.write(Path(tmp)/'policy.json', self.policy)
            with http.server.HTTPServer(('127.0.0.1', 0), G.Handler) as server:
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                def post(raw):
                    conn = http.client.HTTPConnection(*server.server_address, timeout=3)
                    try:
                        conn.request('POST', '/AuthZPlugin.AuthZReq', raw, {'Content-Type':'application/json'})
                        response = conn.getresponse()
                        self.assertEqual(response.status, 200)
                        return json.loads(response.read())
                    finally: conn.close()
                try:
                    self.assertTrue(post('{"User":"","UserAuthNMethod":"","RequestMethod":"GET","RequestUri":"/v1.54/containers/json?all=1","RequestBody":null,"RequestHeaders":{}}')['Allow'])
                    denied = post('{"RequestMethod":"POST","RequestUri":"/v1.54/exec/id/start","RequestBody":"e30="}')
                    self.assertFalse(denied['Allow'])
                    self.assertEqual(json.loads((Path(tmp)/'denied.jsonl').read_text())['path'], '/v1.54/exec/id/start')
                    for malformed in ('{"RequestMethod":"GET","RequestURI":"/v1.54/containers/json"}', '{}', 'null', '{', '{"RequestMethod":"GET","RequestUri":null}', '{"RequestUri":"/v1.54/containers/json"}'):
                        self.assertFalse(post(malformed)['Allow'], malformed)
                finally: server.shutdown(); worker.join(timeout=3)

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

    def lifecycle_fixture(self):
        import contextlib
        @contextlib.contextmanager
        def fixture():
            with tempfile.TemporaryDirectory() as tmp:
                state = Path(tmp)/'state'; docker = Path(tmp)/'containers'
                daemon = Path(tmp)/'daemon.json'; cid = 'a'*64
                rp = {'Name':'unless-stopped','MaximumRetryCount':0}
                old = {'image':G.STOCK,'service':'transcriber-engine','restart':rp}
                p = {**self.policy, 'bootID':'cold-boot','token':'test','containers':{cid:old}}
                c = {'Id':cid, 'Image':G.STOCK,'State':{'Running':False},
                     'Config':{'Labels':{'com.docker.compose.service':'transcriber-engine'}}}
                G.write(docker/cid/'config.v2.json', c)
                G.write(docker/cid/'hostconfig.json', {'RestartPolicy':{'Name':'no','MaximumRetryCount':0},'Other':'retain'})
                G.write(state/'policy.json',p); G.write(state/'witness.json',{})
                original = '{ "log-driver": "json-file", "features": {"containerd-snapshotter": false} }\n'
                G.write(state/'daemon.original.json',original)
                G.write(daemon,{'authorization-plugins':['wizard-cold'],'live-restore':False})
                with patch.object(G,'STATE',state), patch.object(G,'DOCKER',docker), patch.object(G,'DAEMON',daemon), \
                     patch.object(G,'boot_context',return_value=('cold-boot',['wizard.cold=test'])) as boot:
                    yield state,docker,daemon,cid,p,c,boot,original
        return fixture()

    def commit_fixture(self, p, c):
        cs = [c, {'Id':'b'*64,'Image':p['managed'],'Config':self.old['Config'],'State':{'Running':False}}]
        real_read=G.read
        def read(path):
            if str(path)=='/var/lib/wizard/managed/lease.json': return {'token':'test','phase':'held'}
            return real_read(path)
        with patch.object(G,'read',side_effect=read), \
             patch.object(G,'run',side_effect=[' '.join(c['Id'] for c in cs),json.dumps(cs)]), \
             patch.object(G.subprocess,'run',return_value=Mock(returncode=1,stderr='WIZARD_COLD_DENIED')):
            return G.commit()

    def test_commit_and_same_boot_daemon_replacement_keep_both_fences(self):
        with self.lifecycle_fixture() as (state,docker,daemon,cid,p,c,boot,original):
            before = [daemon.read_bytes(), (docker/cid/'hostconfig.json').read_bytes()]
            self.commit_fixture(p,c)
            for _ in range(3): G.daemon_start()
            self.assertEqual(before,[daemon.read_bytes(),(docker/cid/'hostconfig.json').read_bytes()])
            self.assertEqual(G.read(state/'policy.json')['phase'],'committed')
            self.assert_stock_denied(G.read(state/'policy.json'))

    def test_normal_boot_restores_exact_config_and_original_policies_once(self):
        with self.lifecycle_fixture() as (state,docker,daemon,cid,p,c,boot,original):
            self.commit_fixture(p,c)
            boot.return_value=('normal-boot',['console=hvc0','root=/dev/vda','rw'])
            G.daemon_start()
            self.assertEqual(daemon.read_text(),original)
            h=G.read(docker/cid/'hostconfig.json')
            self.assertEqual(h,{'RestartPolicy':p['containers'][cid]['restart'],'Other':'retain'})
            self.assertEqual(G.read(state/'policy.json')['phase'],'activated')
            G.write(daemon, {'later-owner-config':True}); G.daemon_start()
            self.assertEqual(G.read(daemon),{'later-owner-config':True})

    def test_partial_commit_or_cold_reboot_cannot_restore(self):
        with self.lifecycle_fixture() as (state,docker,daemon,cid,p,c,boot,original):
            for phase,cmdline in [('fenced',[]),('committed',[]),('committed',['wizard.cold=test']),('committed',['init=/bin/sh'])]:
                p['phase']=phase; G.write(state/'policy.json',p)
                boot.return_value=('next-boot',cmdline)
                with self.assertRaises(RuntimeError): G.daemon_start()
                self.assertEqual(G.read(daemon)['authorization-plugins'],['wizard-cold'])
                self.assertEqual(G.read(docker/cid/'hostconfig.json')['RestartPolicy']['Name'],'no')

    def test_offline_restore_crash_is_retryable_and_cold_reentry_refused(self):
        # Crash at every durable write boundary, including after daemon restoration.
        for fail_at in range(1,5):
            with self.subTest(fail_at=fail_at), self.lifecycle_fixture() as (state,docker,daemon,cid,p,c,boot,original):
                self.commit_fixture(p,c); boot.return_value=('normal-boot',[])
                real_write=G.write; calls=0
                def crash(path,value,*args):
                    nonlocal calls
                    calls+=1
                    if calls==fail_at: raise OSError('injected power loss')
                    real_write(path,value,*args)
                with patch.object(G,'write',side_effect=crash):
                    with self.assertRaises(OSError): G.daemon_start()
                boot.return_value=('cold-boot',['wizard.cold=test'])
                if fail_at > 1:
                    with self.assertRaises(RuntimeError): G.daemon_start()
                boot.return_value=('rebooted-normal',[]); G.daemon_start()
                self.assertEqual(daemon.read_text(),original)
                self.assertEqual(G.read(docker/cid/'hostconfig.json')['RestartPolicy'],p['containers'][cid]['restart'])

    def test_daemon_fence_tamper_and_identity_mismatch_fail_closed(self):
        with self.lifecycle_fixture() as (state,docker,daemon,cid,p,c,boot,original):
            G.write(daemon, {})
            with self.assertRaisesRegex(RuntimeError,'daemon fence'): G.daemon_start()
            G.write(daemon,{'authorization-plugins':['wizard-cold'],'live-restore':False})
            G.write(docker/cid/'hostconfig.json',{'RestartPolicy':{'Name':'always'}})
            with self.assertRaisesRegex(RuntimeError,'restart policy'): G.daemon_start()
            c['Image']='unknown'; G.write(docker/cid/'config.v2.json',c)
            with self.assertRaisesRegex(RuntimeError,'identity'): G.daemon_start()

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
