#!/usr/bin/env python3
"""Cheap, network-free regressions; not native trust or inference acceptance."""
import ast, copy, importlib.util, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
HERE=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location('recovery',HERE/'resume-voice-security.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
HOST='DNS configuration\n\nresolver #1\n  nameserver[0] : 192.168.1.1\n\nresolver #2\n  domain : tail.test\n  nameserver[0] : 100.100.100.100\nDNS configuration (for scoped queries)\nresolver #1\n  nameserver[0] : 10.1.1.1\n'
EXACT='ghcr.io/humanitylabs-org/wizard-mac-security-transcriber@sha256:'+'a'*64

class Recovery(unittest.TestCase):
    def test_existing_default_only_not_split_or_scoped(self):
        self.assertEqual(m.host_resolver(HOST),'192.168.1.1')
    def test_ambiguous_route_refused(self):
        with self.assertRaises(RuntimeError):m.host_resolver(HOST.replace('192.168.1.1','192.168.1.1\n  nameserver[1] : 10.0.0.1'))
    def test_public_or_loopback_refused(self):
        for value in ('8.8.8.8','127.0.0.1'):
            with self.assertRaises(RuntimeError):m.host_resolver(HOST.replace('192.168.1.1',value))
    def test_default_split_refused(self):
        with self.assertRaises(RuntimeError):m.host_resolver(HOST.replace('resolver #1\n','resolver #1\n  domain : private.test\n',1))
    def test_actual_probe_flags_are_ephemeral_and_hardened(self):
        argv=m.probe_argv(EXACT,'owned','192.168.1.1','python')
        self.assertEqual(argv[argv.index('--dns')+1],'192.168.1.1')
        for v in ('--pull=never','--rm','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges'):self.assertIn(v,argv)
        for v in ('--privileged','--user','--network=host','--add-host','--dns-search'):self.assertNotIn(v,argv)
        self.assertEqual(argv[-2:], [EXACT,'-'])
    def test_original_exact_callsite_lacks_dns_prerequisite(self):
        tree=ast.parse((HERE/'package-voice-image.py').read_text())
        tls=next(x.value for x in ast.walk(tree) if isinstance(x,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='tls' for t in x.targets))
        old_literals=[x.value for x in ast.walk(tls.args[0]) if isinstance(x,ast.Constant)]
        self.assertNotIn('--dns',old_literals)
        self.assertIn('--dns',m.probe_argv(EXACT,'owned','192.168.1.1','/bin/sh'))
    def test_config_and_old_rootfs_unchanged(self):
        old={'architecture':'arm64','config':{'User':'ubuntu','Env':['A=B']},'rootfs':{'diff_ids':['old']},'history':[{'created_by':'old'}]}
        new=copy.deepcopy(old);new['rootfs']['diff_ids'].append('overlay');new['history'].append({'created_by':'overlay'})
        m.preserved_config(old,new)
        for field,value in [('config',{'User':'root'}),('architecture','amd64'),('rootfs',{'diff_ids':['foreign','overlay']}),('history',[{'created_by':'foreign'},{'created_by':'overlay'}])]:
            bad=copy.deepcopy(new);bad[field]=value
            with self.assertRaises(RuntimeError):m.preserved_config(old,bad)
    def test_unrelated_or_mutable_image_refused(self):
        for value in ('image:latest',EXACT.replace('transcriber','hermes')):
            with self.assertRaises(RuntimeError):m.probe_argv(value,'owned','192.168.1.1','python')
    def test_metadata_custody_and_exclusive_receipts(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as d:
            p=Path(d)/'x';p.write_text('input');before=m.metadata(p);p.write_text('mutate');self.assertNotEqual(before,m.metadata(p))
            link=Path(d)/'link';link.symlink_to(p)
            with self.assertRaises(RuntimeError):m.metadata(link)
            dest=Path(d)/'receipt';m.save(dest,{'success':False})
            with self.assertRaises(FileExistsError):m.save(dest,{'success':True})
            self.assertFalse(json.loads(dest.read_text())['success'])
    def test_protected_tags_not_untagged_row_identity(self):
        a=json.dumps({'Repository':'r','Tag':'latest','ID':'a','Digest':'b'})
        self.assertEqual(m.tag_rows(a),m.tag_rows(a+'\n'+json.dumps({'Tag':'<none>','ID':'new'})))
        self.assertNotEqual(m.tag_rows(a),m.tag_rows(a.replace('"a"','"changed"')))
    def test_source_never_rebuilds_loads_or_changes_global_dns(self):
        text=(HERE/'resume-voice-security.py').read_text();tree=ast.parse(text)
        for n in ast.walk(tree):
            if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute):self.assertNotIn(n.func.attr,('derive','export','load_image'))
        self.assertNotIn('oci.load(',text)
        self.assertIn("security.PROBE,470",text)
        self.assertIn("(launch/'security-probe.py').read_text(),260",text)
        self.assertIn("result-recovery-a3.json",text)
        self.assertNotIn('colima start',text)
    def test_optimized_worker_refused_before_native_access(self):
        r=subprocess.run([sys.executable,'-O',str(HERE/'resume-voice-security.py')],capture_output=True,text=True)
        self.assertNotEqual(r.returncode,0);self.assertIn('refusing optimized recovery',r.stderr)

if __name__=='__main__':unittest.main()
