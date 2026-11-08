"""The imported .env: model-provider keys stay behind, Wizard's own lines win, and the file is written privately.

Exercises the production helpers with synthetic fixtures, without Hermes. Set IMPORTER_SCRIPT to run these
identical regressions against another revision. All fixtures live under the caller's scratch TMPDIR.
"""
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(os.environ.get(
    "IMPORTER_SCRIPT",
    str(Path(__file__).parents[1] / "overlay/opt/wizard/bin/wizard-import-hermes"),
))
loader = importlib.machinery.SourceFileLoader("importer_env", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec is not None
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)

IMPORTED = "\n".join([
    "# my desktop Hermes",
    "ANTHROPIC_API_KEY=fixture-imported-anthropic",
    "export OPENAI_API_KEY=fixture-imported-openai",
    "OPENAI_BASE_URL=https://example.invalid/v1",
    "OPENROUTER_API_KEY=fixture-imported-openrouter",
    "CLAUDE_CODE_OAUTH_TOKEN=fixture-imported-claude-code",
    "GEMINI_API_KEY=fixture-imported-gemini",
    "HERMES_INFERENCE_PROVIDER=anthropic",
    "FIRECRAWL_API_KEY=fixture-tool-key",
    "TELEGRAM_BOT_TOKEN=fixture-messaging",
    "ELEVENLABS_API_KEY=fixture-voice",
    "API_SERVER_KEY=fixture-imported-api-server",
    "",
])
WIZARD = ["API_SERVER_KEY=fixture-wizard-api-server", "OPENAI_API_KEY=fixture-wizard-openai"]


class ImportedEnv(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.home.cleanup)
        self.data = Path(self.home.name)
        self.settings = mock.patch.multiple(m, DATA=self.data, UID=os.getuid(), GID=os.getgid())
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.env = self.data / ".env"

    def merged(self):
        self.env.write_text(IMPORTED)
        rec = {}
        replaced = m.env_merge(list(WIZARD), rec)
        return self.env.read_text(), replaced, rec

    def test_imported_provider_keys_stay_behind(self):
        text, _, _ = self.merged()
        for value in ("fixture-imported-anthropic", "fixture-imported-openai", "example.invalid",
                      "fixture-imported-openrouter", "fixture-imported-claude-code", "fixture-imported-gemini",
                      "HERMES_INFERENCE_PROVIDER"):
            self.assertNotIn(value, text)

    def test_tool_and_messaging_keys_still_come_along(self):
        text, _, _ = self.merged()
        for line in ("FIRECRAWL_API_KEY=fixture-tool-key", "TELEGRAM_BOT_TOKEN=fixture-messaging",
                     "ELEVENLABS_API_KEY=fixture-voice", "# my desktop Hermes"):
            self.assertIn(line, text.splitlines())

    def test_wizard_lines_win(self):
        text, replaced, _ = self.merged()
        lines = text.splitlines()
        self.assertIn("OPENAI_API_KEY=fixture-wizard-openai", lines)
        self.assertIn("API_SERVER_KEY=fixture-wizard-api-server", lines)
        self.assertNotIn("fixture-imported-api-server", text)
        self.assertEqual(replaced, ["API_SERVER_KEY"])

    def test_record_names_left_behind_keys_without_values(self):
        _, _, rec = self.merged()
        self.assertEqual(rec["env_left_behind"], sorted([
            "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENROUTER_API_KEY",
            "CLAUDE_CODE_OAUTH_TOKEN", "GEMINI_API_KEY", "HERMES_INFERENCE_PROVIDER"]))
        self.assertNotIn("fixture", repr(rec))

    def test_box_keeps_its_own_provider_lines_for_after_the_import(self):
        self.env.write_text("WIZARD_TOKEN=fixture-w\nOPENAI_API_KEY=fixture-wizard-openai\nFIRECRAWL_API_KEY=x\n")
        self.assertEqual(m.wizard_env_lines(), ["WIZARD_TOKEN=fixture-w", "OPENAI_API_KEY=fixture-wizard-openai"])

    def test_written_private_even_with_a_predictable_temp_file_present(self):
        planted = self.data / ".env.wizard-import"
        planted.write_text("planted")
        os.chmod(planted, 0o644)
        self.merged()
        self.assertEqual(stat.S_IMODE(self.env.stat().st_mode), 0o600)
        self.assertFalse(self.env.is_symlink())

    def test_never_writes_through_a_planted_temp_link(self):
        target = self.data / "elsewhere"
        target.write_text("synthetic-sentinel")
        (self.data / ".env.wizard-import").symlink_to(target)
        self.merged()
        self.assertEqual(target.read_text(), "synthetic-sentinel")

    def test_never_reads_through_a_planted_env_link(self):
        target = self.data / "root-only-sentinel"
        target.write_text("WIZARD_SECRET=synthetic-private-sentinel\n")
        self.env.symlink_to(target)
        with self.assertRaises(OSError):
            m.wizard_env_lines()
        with self.assertRaises(OSError):
            m.env_merge([], {})
        self.assertEqual(target.read_text(), "WIZARD_SECRET=synthetic-private-sentinel\n")

    def test_no_env_at_all(self):
        self.assertEqual(m.wizard_env_lines(), [])
        self.assertEqual(m.env_merge(list(WIZARD), {}), [])
        self.assertEqual(stat.S_IMODE(self.env.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
