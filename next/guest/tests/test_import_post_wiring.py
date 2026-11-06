"""The importer's Wizard wiring (POST_IMPORT) against real Hermes config loading.

Needs a Hermes checkout and an interpreter with its dependencies, so it skips unless both are given:
    HERMES_SRC=<hermes-agent checkout> HERMES_PYTHON=<its python> python3 -m unittest next/guest/tests/test_import_post_wiring.py
Inside the agent image (run as uid 1000 with a writable /wizard-managed-state holding admission.lock and launch/,
which the image's launch guard needs): HERMES_SRC=/opt/hermes HERMES_PYTHON=/opt/hermes/.venv/bin/python.
"""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).parents[1] / 'overlay/opt/wizard/bin/wizard-import-hermes'
loader = importlib.machinery.SourceFileLoader('importer_wiring', str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)

SRC = os.environ.get('HERMES_SRC')
PY = os.environ.get('HERMES_PYTHON')

LOAD = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from gateway.config import load_gateway_config, Platform
cfg = load_gateway_config()
print(json.dumps({p.value: c.enabled for p, c in cfg.platforms.items()}))
'''


@unittest.skipUnless(SRC and PY, 'set HERMES_SRC and HERMES_PYTHON to run against real Hermes')
class PostImportWiring(unittest.TestCase):
    def run_wiring(self, config: str, env_lines: list[str], keep: dict | None = None, out: dict | None = None) -> tuple[dict, dict]:
        with tempfile.TemporaryDirectory() as home:
            Path(home, 'config.yaml').write_text(config)
            Path(home, '.env').write_text('\n'.join(env_lines) + '\n')
            env = {**os.environ, 'HERMES_HOME': home, 'HOME': home, 'PYTHONPATH': SRC}
            for k in [k for k in env if k.startswith(('API_SERVER_', 'TELEGRAM_', 'WHATSAPP_'))]:
                env.pop(k)
            done = subprocess.run([PY, '-c', m.POST_IMPORT], input=json.dumps({'api_server': None, **(keep or {})}), env=env,
                                  capture_output=True, text=True, timeout=120, check=True)
            report = json.loads(done.stdout.strip().splitlines()[-1])
            if out is not None:
                out['config'] = Path(home, 'config.yaml').read_text()
            # In the agent container Wizard's API_SERVER_KEY arrives in the process environment.
            loaded = subprocess.run([PY, '-c', LOAD, SRC], env={**env, 'API_SERVER_KEY': 'k' * 32}, capture_output=True, text=True, timeout=120,
                                    check=True)
            return report, json.loads(loaded.stdout.strip().splitlines()[-1])

    def test_imported_nested_api_server_disable_does_not_keep_wizard_api_off(self):
        config = 'gateway:\n  platforms:\n    api_server:\n      enabled: false\n'
        _, enabled = self.run_wiring(config, ['API_SERVER_KEY=' + 'k' * 32])
        self.assertTrue(enabled.get('api_server'), enabled)

    def test_nested_messaging_enable_is_switched_off(self):
        config = ('gateway:\n  platforms:\n    telegram:\n      enabled: true\n'
                  '  whatsapp:\n    enabled: true\n')
        report, enabled = self.run_wiring(config, ['API_SERVER_KEY=' + 'k' * 32])
        self.assertFalse(enabled.get('telegram', False), enabled)
        self.assertFalse(enabled.get('whatsapp', False), enabled)
        self.assertEqual(sorted(report['disabled_messaging']), ['telegram', 'whatsapp'])
        self.assertTrue(enabled.get('api_server'), enabled)

    def test_wizard_model_replaces_the_imported_one(self):
        # James, 31 Oct (try-wizard#51): the AI runs through Wizard's own connections, not the imported provider.
        config = ('model:\n  default: claude-opus\n  provider: anthropic\n'
                  'fallback_model:\n  provider: anthropic\n  model: claude-sonnet\n')
        wizard = {'default': 'gpt-x', 'provider': 'openai-codex', 'base_url': 'https://chatgpt.com/backend-api/codex'}
        out = {}
        self.run_wiring(config, ['API_SERVER_KEY=' + 'k' * 32], keep={'model': wizard}, out=out)
        import yaml
        cfg = yaml.safe_load(out['config'])
        self.assertEqual(cfg['model'], wizard)
        self.assertNotIn('fallback_model', cfg)

    def test_keep_wizard_auth_puts_wizard_logins_back(self):
        with tempfile.TemporaryDirectory() as home:
            old = (m.DATA, m.UID, m.GID)
            m.DATA, m.UID, m.GID = Path(home), os.getuid(), os.getgid()
            try:
                Path(home, 'auth.json').write_text('{"imported": true}')
                self.assertTrue(m.keep_wizard_auth(b'{"wizard": true}'))
                self.assertEqual(Path(home, 'auth.json').read_text(), '{"wizard": true}')
                self.assertEqual(Path(home, 'auth.json').stat().st_mode & 0o777, 0o600)
                self.assertFalse(m.keep_wizard_auth(None))
                self.assertFalse(Path(home, 'auth.json').exists())
            finally:
                m.DATA, m.UID, m.GID = old


if __name__ == '__main__':
    unittest.main()
