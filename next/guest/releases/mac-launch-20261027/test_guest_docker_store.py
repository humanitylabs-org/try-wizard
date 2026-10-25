"""Synthetic control-plane tests. Real guest evidence is a separate Thales smoke."""
import copy, json, shutil, subprocess, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import guest_docker_store as store
HERE=Path(__file__).resolve().parent
INFO={'Driver':'overlayfs','DriverStatus':[['driver-type',store.SNAPSHOTTER]],'DockerRootDir':'/var/lib/docker'}
REF='unit.invalid/helper@sha256:'+'a'*64
IMAGE={'Id':'sha256:'+'b'*64,'Architecture':'arm64','RepoDigests':[REF]}
CONTAINER={'Id':'c'*64,'Name':'/unit','Image':IMAGE['Id'],'Config':{'Image':REF,'Labels':{}},'State':{'Status':'exited'},'GraphDriver':{'Name':'overlayfs'}}

class StoreTests(unittest.TestCase):
    def test_classic_driver_fails_closed(self):
        with patch.object(store,'run',return_value=json.dumps({'DriverStatus':[['Backing Filesystem','extfs']]})):
            with self.assertRaisesRegex(AssertionError,'snapshotter not active'):store.assert_store()
    def test_containerd_driver_is_read_back(self):
        with patch.object(store,'run',return_value=json.dumps(INFO)) as run:
            self.assertEqual(store.assert_store(),INFO);self.assertIn('{{json .}}',run.call_args.args[0])
    def test_config_merge_and_snapshot_precede_restart(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);config=root/'daemon.json';original={'log-driver':'local','features':{'unrelated':True},'log-opts':{'max-file':'3'}};config.write_text(json.dumps(original))
            def run(argv,**kw):
                if argv[0]=='systemctl':
                    self.assertTrue((root/'docker-store-before.json').exists());self.assertTrue(json.loads(config.read_text())['features']['containerd-snapshotter']);return ''
                return json.dumps([IMAGE])
            with patch.object(store,'containers',return_value=[copy.deepcopy(CONTAINER)]),patch.object(store,'disk',return_value={'unit':True}),patch.object(store,'assert_store',return_value=INFO),patch.object(store,'run',side_effect=run),patch.object(store.os,'geteuid',return_value=0):store.enable(root,config)
            expected=copy.deepcopy(original);expected['features']['containerd-snapshotter']=True
            self.assertEqual(json.loads(config.read_text()),expected)
            self.assertEqual(json.loads((root/'docker-store-before.json').read_text())[0]['FactoryImage'],IMAGE)
            with patch.object(store.os,'geteuid',return_value=0):
                with self.assertRaisesRegex(AssertionError,'fresh clone'):store.enable(root,config)
    def test_malformed_features_not_replaced(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);config=root/'daemon.json';config.write_text('{"features": false}')
            with patch.object(store,'containers',return_value=[copy.deepcopy(CONTAINER)]),patch.object(store,'disk',return_value={}),patch.object(store,'run',return_value=json.dumps([IMAGE])) as run,patch.object(store.os,'geteuid',return_value=0):
                with self.assertRaises(AssertionError):store.enable(root,config)
                self.assertFalse(any(c.args[0][0]=='systemctl' for c in run.call_args_list))
    def test_compose_new_override_and_container_paths(self):
        with tempfile.TemporaryDirectory() as t:
            rt=Path(t);override=rt/'user-config/wizardapps/files/docker-compose.yml';override.parent.mkdir(parents=True);override.write_text('services: {}')
            row=copy.deepcopy(CONTAINER);row['Config']['Labels']={'com.docker.compose.project':'files_wizardapps','com.docker.compose.project.config_files':'/data/apps/wizardapps/files/docker-compose.generated.yml','com.docker.compose.project.working_dir':'/data/apps/wizardapps/files','com.docker.compose.project.environment_file':'/app-data/wizardapps/files/app.env'}
            with patch.object(store,'RT',rt):projects=store.compose_projects([row,row])
            self.assertEqual(len(projects),1);self.assertIn(str(override),projects[0]['files']);self.assertIn(str(rt/'app-data/wizardapps/files/app.env'),projects[0]['env'])
            argv=store.compose_argv(projects[0]);self.assertIn('--env-file',argv);self.assertIn('--project-directory',argv)
    def verify_fixture(self,image=None,container=None,missing=None):
        image=image or IMAGE;container=container or CONTAINER
        def run(argv,**kw):
            if missing and argv[-1]==missing:raise subprocess.CalledProcessError(1,argv)
            return json.dumps([image])
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            with patch.object(store,'assert_store',return_value=INFO),patch.object(store,'disk',return_value={}),patch.object(store,'containers',return_value=[container]),patch.object(store,'run',side_effect=run):
                try:result=store.verify(root)
                except AssertionError:
                    self.assertTrue(json.loads((root/'docker-image-resolution.json').read_text())['unresolved']);raise
                return result
    def test_stopped_ref_and_image_id_resolve(self):
        result=self.verify_fixture();self.assertEqual(set(result['resolved']),{REF,IMAGE['Id']});self.assertFalse(result['unresolved'])
    def test_unresolved_ref_is_listed_and_fatal(self):
        with self.assertRaisesRegex(AssertionError,'unresolved image refs'):self.verify_fixture(missing=REF)
    def test_retagged_container_not_recreatable(self):
        image={**IMAGE,'Id':'sha256:'+'d'*64}
        with self.assertRaisesRegex(AssertionError,'differs from recreatable'):self.verify_fixture(image=image)
    def test_digest_preservation_still_mandatory(self):
        with self.assertRaisesRegex(AssertionError,'digest not preserved'):self.verify_fixture(image={**IMAGE,'RepoDigests':[]})
    def test_wrong_architecture_refused(self):
        with self.assertRaises(AssertionError):self.verify_fixture(image={**IMAGE,'Architecture':'amd64'})
    def test_classic_container_refused(self):
        with self.assertRaisesRegex(AssertionError,'classic container'):self.verify_fixture(container={**CONTAINER,'GraphDriver':{'Name':'overlay2'}})
    def test_apply_order_and_clone_only_growth(self):
        source=(HERE/'guest-apply.py').read_text();self.assertLess(source.index('store.enable(WORK)'),source.index('oci.load(ROOT,row)'))
        self.assertLess(source.index('store.bootstrap(WORK)'),source.index("installer=ROOT/'final/wam/get.sh'"))
        source=(HERE/'assemble.py').read_text();self.assertIn("with (work/'data/os/disk.img').open('r+b')",source);self.assertNotIn("original.open('r+b')",source)
    def test_seal_only_recreated_container_configs(self):
        source=(HERE/'seal-factory.py').read_text();self.assertIn('for identity in sorted(active)',source);self.assertIn('docker-seal-resolution.json',source)

class FrozenReleaseTests(unittest.TestCase):
    def test_manifest_is_world_readable_for_the_unprivileged_installer(self):
        src=(Path(__file__).resolve().parent/'guest-apply.py').read_text()
        self.assertIn("release_dir.chmod(0o755);target.chmod(0o644)",src)
        self.assertLess(src.index("target.chmod(0o644)"),src.index("run(['bash',installer]"))

class SealedWamCheckoutTests(unittest.TestCase):
    def _module(self):
        import importlib.util,sys
        here=Path(__file__).resolve().parent;sys.path.insert(0,str(here))
        spec=importlib.util.spec_from_file_location('guest_apply_under_test',here/'guest-apply.py')
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
    def _sealed(self,tmp):
        repo=Path(tmp)/'repo';repo.mkdir();g=['git','-C',str(repo),'-c','user.name=t','-c','user.email=t@t']
        subprocess.run(['git','init','-q',str(repo)],check=True);(repo/'install.sh').write_text('echo v1\n')
        subprocess.run([*g,'add','.'],check=True);subprocess.run([*g,'commit','-qm','v1'],check=True)
        sha=subprocess.run([*g,'rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
        box=Path(tmp)/'wam';shutil.copytree(repo,box,ignore=shutil.ignore_patterns('.git'))
        (box/'SOURCE_COMMIT').write_text(sha+'\n');(box/'.venv').mkdir();return repo,box,sha
    def test_reattaches_git_at_the_sealed_commit_keeping_the_tree(self):
        m=self._module()
        with tempfile.TemporaryDirectory() as tmp:
            repo,box,sha=self._sealed(tmp)
            self.assertEqual(m.reattach_sealed_wam_checkout(box,str(repo),as_user=()),sha)
            self.assertTrue((box/'.git').is_dir());self.assertTrue((box/'.venv').is_dir())
            self.assertIsNone(m.reattach_sealed_wam_checkout(box,str(repo),as_user=()))
    def test_tracked_drift_in_the_sealed_tree_fails_closed(self):
        m=self._module()
        with tempfile.TemporaryDirectory() as tmp:
            repo,box,sha=self._sealed(tmp);(box/'install.sh').write_text('echo tampered\n')
            with self.assertRaises(AssertionError):m.reattach_sealed_wam_checkout(box,str(repo),as_user=())
    def test_runs_before_the_installer(self):
        src=(Path(__file__).resolve().parent/'guest-apply.py').read_text()
        self.assertLess(src.index("reattach_sealed_wam_checkout('/home/wizard"),src.index("run(['bash',installer]"))

if __name__=='__main__':unittest.main()

