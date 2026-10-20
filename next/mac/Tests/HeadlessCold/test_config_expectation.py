#!/usr/bin/env python3
"""Synthetic adversarial config fixtures; not runtime acceptance evidence."""
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[3]
sys.path.insert(0, str(HERE))
import config_expectation
import run as runner


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cold = load('cold_config_fixture', SOURCE/'next/guest/cold-config.py')
guard = load('config_guard_fixture', SOURCE/'next/guest/stack-preservation.py')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def snapshot(raw):
    expected, _ = config_expectation.migrate(raw, cold.migrate)
    return {'protected':{}, 'installedApps':['hermes-agent'], 'accountFiles':{},
        'configNormalizedSHA256':digest(config_expectation.semantic(yaml.safe_load(expected)).encode()),
        'configRawSHA256':digest(raw), 'configExpectedSHA256':digest(expected),
        'authSnapshot':guard.auth_snapshot(None),
        'databases':{'state.db':{'messages':{'columns':['id'], 'rows':['existing-message']}}}}


class ConfigExpectation(unittest.TestCase):
    def setUp(self):
        # Test data only. No real config, accounts or owner strings enter this file.
        self.doc = {'owner':{'name':'fixture-owner','preferences':{'on':True}},
            'model':{'provider':'fixture-provider','default':'fixture-model'},
            'provider':{'base_url':'https://fixture.invalid','unknown':[1,True,None,'1']},
            'plugins':{'enabled':['owner-plugin'], 'unknown':{'keep':'exact'}},
            'terminal':{'backend':'ssh','ssh_host':'wizard-vm','ssh_user':'wizard','ssh_port':22,'ssh_key':cold.OLD},
            'unknown':{'nested':['custom',{'typed':False}]}}
        self.raw = ('# fixture comments\n'+yaml.safe_dump(self.doc,sort_keys=False)).encode()

    def actual_product_bytes(self, raw):
        # Execute the real production config block with private temporary paths.
        # Fake only ownership and atomic writer I/O, not the config transform.
        script = (SOURCE/'next/guest/overlay/opt/wizard/bin/wizard-product-configure').read_text()
        block = script[script.index("cfg = ROOT/'config.yaml'"):script.index('HOME.mkdir(exist_ok=True)')]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'config.yaml').write_bytes(raw)
            def write(path, data, mode, uid, gid): path.write_bytes(data)
            import os
            with patch.object(os,'chown'):
                exec(compile(ast.parse(block), 'real-product-config-block', 'exec'),
                     {'ROOT':root, 'yaml':yaml, 'os':os, 'write':write})
            return (root/'config.yaml').read_bytes()

    def test_matches_actual_production_writer_and_cold_order(self):
        actual, _ = cold.migrate(self.actual_product_bytes(self.raw).decode())
        expected, receipt = config_expectation.migrate(self.raw,cold.migrate)
        self.assertEqual(expected,actual.encode())
        self.assertTrue(receipt['productPluginAppended'])
        want=copy.deepcopy(self.doc)
        want['plugins']['enabled'].append('wizard-product')
        want['terminal']['ssh_key']=cold.NEW
        self.assertEqual(config_expectation.semantic(yaml.safe_load(expected)),config_expectation.semantic(want))
        runner.compare(snapshot(self.raw),snapshot(expected),guard)

    def test_repeat_is_byte_exact_and_rollback_uses_original(self):
        expected,_=config_expectation.migrate(self.raw,cold.migrate)
        self.assertEqual(config_expectation.migrate(expected,cold.migrate)[0],expected)
        runner.compare(snapshot(expected),snapshot(expected),guard)
        runner.compare(snapshot(self.raw),snapshot(self.raw),guard,rollback=True)
        with self.assertRaises(AssertionError):runner.compare(snapshot(self.raw),snapshot(expected),guard,rollback=True)

    def test_already_enabled_keeps_every_other_byte(self):
        raw=b"# retain comment\r\nplugins: {enabled: [wizard-product, custom]}\r\nmodel: 'fixture'\r\nunknown: 1\r\n"
        self.assertEqual(config_expectation.migrate(raw,cold.migrate)[0],raw)
        self.assertEqual(self.actual_product_bytes(raw),raw)
        raw=("# retain comment\nplugins: {enabled: [wizard-product, custom]}\nterminal:\n  backend: ssh\n  ssh_host: wizard-vm\n  ssh_user: wizard\n  ssh_key: '"+cold.OLD+"' # preserve style\n").encode()
        self.assertEqual(config_expectation.migrate(raw,cold.migrate)[0],raw.replace(cold.OLD.encode(),cold.NEW.encode()))

    def test_owner_and_provider_and_unknown_changes_rejected(self):
        expected,_=config_expectation.migrate(self.raw,cold.migrate)
        good=yaml.safe_load(expected)
        changes=[(('owner','name'),'other'),(('model','provider'),'other'),(('model','default'),'other'),
            (('provider','base_url'),'https://changed.invalid'),(('provider','unknown'),[True,True,None,'1']),
            (('unknown','nested'),[]),(('plugins','unknown'),{}),(('plugins','enabled'),['wizard-product']),
            (('terminal','ssh_host'),'other'),(('terminal','ssh_key'),cold.OLD)]
        for path,value in changes:
            with self.subTest(path=path):
                bad=copy.deepcopy(good); bad[path[0]][path[1]]=value
                with self.assertRaises(AssertionError):runner.compare(snapshot(self.raw),snapshot(yaml.safe_dump(bad,sort_keys=False).encode()),guard)
        for bad in (dict(good, added={'unknown':True}), {k:v for k,v in good.items() if k!='owner'}):
            with self.assertRaises(AssertionError):runner.compare(snapshot(self.raw),snapshot(yaml.safe_dump(bad,sort_keys=False).encode()),guard)

    def test_unexpected_serialization_and_extra_plugin_rejected(self):
        expected,_=config_expectation.migrate(self.raw,cold.migrate)
        bads=[b'# unexpected new comment\n'+expected,expected.replace(b'\n',b'\r\n'),
              yaml.safe_dump(yaml.safe_load(expected),sort_keys=True).encode()]
        doc=yaml.safe_load(expected);doc['plugins']['enabled'].append('unexpected-plugin')
        bads.append(yaml.safe_dump(doc,sort_keys=False).encode())
        for bad in bads:
            with self.subTest(digest=digest(bad)):
                with self.assertRaises(AssertionError):runner.compare(snapshot(self.raw),snapshot(bad),guard)
        with self.assertRaises(AssertionError):runner.compare(snapshot(expected),snapshot(b'# repeat rewrite\n'+expected),guard)

    def test_custom_ssh_routes_remain_unchanged(self):
        for key,value in [('backend','local'),('ssh_host','custom-host'),('ssh_user','owner'),('ssh_port',2222),('ssh_key','/custom/key')]:
            with self.subTest(key=key):
                doc=copy.deepcopy(self.doc);doc['terminal'][key]=value
                raw=yaml.safe_dump(doc,sort_keys=False).encode()
                expected,_=config_expectation.migrate(raw,cold.migrate)
                self.assertEqual(yaml.safe_load(expected)['terminal'],doc['terminal'])
                self.assertEqual(expected,self.actual_product_bytes(raw))

    def test_missing_plugin_container_and_bad_shapes(self):
        for raw in (b'model: fixture\n',b'plugins: {}\nmodel: fixture\n'):
            self.assertEqual(config_expectation.migrate(raw,cold.migrate)[0],self.actual_product_bytes(raw))
        for raw in (b'[]',b'plugins: null',b'plugins: []',b'plugins: {enabled: false}',b'plugins: {enabled: null}'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):config_expectation.migrate(raw,cold.migrate)

    def test_alias_append_cannot_mutate_owner_settings(self):
        raw=b'owner: &p [custom]\nplugins: {enabled: *p}\n'
        with self.assertRaisesRegex(ValueError,'aliased owner'):config_expectation.migrate(raw,cold.migrate)


if __name__=='__main__':unittest.main()
