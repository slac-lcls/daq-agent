import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from daq_agent.collectors.logs import MAX_FILE_BYTES, snapshot_logs
from daq_agent.config import Settings
from daq_agent.log_analysis import analyze_logs
from daq_agent.reports import validate_findings
from daq_agent.runtime import audit_evidence_access, extract_response, runtime_environment, select_provider, session_config


RESPONSE = {
    "summary": "An operation was denied in the supplied synthetic excerpt.",
    "findings": [{
        "title": "Access failure",
        "observation": "The excerpt reports permission denied.",
        "hypothesis": "The reason for denial is not established.",
        "next_check": "Inspect ownership and active users of the resource.",
        "evidence": [{"source": "log-1", "line_start": 1, "line_end": 1}],
    }],
    "limitations": ["Grafana unavailable; supplied excerpts only."],
}


class LogAnalysisTests(unittest.TestCase):
    settings = Settings("tmo", 0, "America/Los_Angeles", "slac/example")

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.log = self.root / "input.log"
        self.log.write_text("SYNTHETIC: permission denied\n")
        self.provider = self.root / "provider.json"
        self.provider.write_text(json.dumps({
            "provider": {"slac": {
                "npm": "@ai-sdk/anthropic",
                "options": {"apiKey": "{env:TEST_EXAMPLE_KEY}", "baseURL": "https://example.invalid/v1"},
                "models": {"example": {"name": "Example"}, "unrelated": {}},
            }},
            "permission": {"*": "allow"},
            "mcp": {"unrelated": {"enabled": True}},
            "plugin": ["unrelated-plugin"],
        }))

    def run_analysis(self, output="output", **kwargs):
        return analyze_logs(self.settings, "2026-09-18", "2026-09-19", [self.log],
                            self.root / output, self.provider, str(self.root / "fake-opencode"),
                            synthetic=True, **kwargs)

    def fake_runtime(self, text=None, delay=False):
        executable = self.root / "fake-opencode"
        payload = json.dumps(RESPONSE if text is None else text)
        executable.write_text(
            "#!/usr/bin/env python3\nimport json,sys,time,os\n"
            "from pathlib import Path\n"
            "if '--version' in sys.argv:\n print('test-runtime'); sys.exit(0)\n"
            "prompt=sys.stdin.read()\n"
            "assert 'log-triage' in prompt\n"
            "config=json.loads((Path(os.environ['OPENCODE_CONFIG_DIR'])/'opencode.json').read_text())\n"
            "assert config['permission']['*']=='deny'\n"
            "assert not config['mcp'] and not config['plugin']\n"
            "print(json.dumps({'type':'tool_use','part':{'tool':'skill','state':{'status':'completed','input':{'name':'log-triage'}}}}))\n"
            "for p in (Path.cwd()/'evidence').glob('*.txt'):\n"
            " print(json.dumps({'type':'tool_use','part':{'tool':'read','state':{'status':'completed','input':{'filePath':str(p)}}}}))\n"
            + ("time.sleep(60)\n" if delay else "")
            + f"print(json.dumps({{'type':'text','part':{{'text':{payload!r}}}}}))\n"
        )
        executable.chmod(0o700)

    def test_prepare_requires_no_runtime_or_credentials(self):
        output = analyze_logs(self.settings, "2026-09-18", "2026-09-19", [self.log],
                              self.root / "prepared", None, "nonexistent", prepare_only=True)
        manifest = json.loads((output / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "prepared_only")
        self.assertFalse(manifest["grafana"]["queried"])
        self.assertEqual((output / "evidence/log-1.txt").read_bytes(), self.log.read_bytes())
        self.assertFalse((output / "report.md").exists())

    def test_end_to_end_with_fake_subprocess(self):
        self.fake_runtime()
        output = self.run_analysis()
        manifest = json.loads((output / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "completed")
        self.assertEqual(manifest["opencode_version"], "test-runtime")
        self.assertEqual(manifest["runtime_audit"]["sources_read"], ["log-1"])
        self.assertEqual(json.loads((output / "findings.json").read_text()), RESPONSE)
        self.assertIn("synthetic", (output / "report.md").read_text())
        self.assertIn("not queried", (output / "report.md").read_text())
        self.assertEqual(output.stat().st_mode & 0o777, 0o700)

    def test_unknown_citation_fails_without_report(self):
        response = json.loads(json.dumps(RESPONSE))
        response["findings"][0]["evidence"][0]["source"] = "invented"
        self.fake_runtime(response)
        with self.assertRaisesRegex(ValueError, "unknown source"):
            self.run_analysis()
        self.assertEqual(json.loads((self.root / "output/manifest.json").read_text())["status"], "failed")
        self.assertFalse((self.root / "output/report.md").exists())

    def test_timeout_is_recorded(self):
        self.fake_runtime(delay=True)
        with self.assertRaises(TimeoutError):
            self.run_analysis(timeout=1)
        self.assertEqual(json.loads((self.root / "output/manifest.json").read_text())["status"], "failed")

    def test_out_of_bounds_citation_rejected(self):
        response = json.loads(json.dumps(RESPONSE))
        response["findings"][0]["evidence"][0]["line_end"] = 2
        with self.assertRaisesRegex(ValueError, "outside"):
            validate_findings(json.dumps(response), [{"id": "log-1", "lines": 1}])

    def test_existing_output_not_overwritten(self):
        output = self.root / "output"
        output.mkdir()
        (output / "keep.txt").write_text("keep")
        with self.assertRaises(FileExistsError):
            self.run_analysis(prepare_only=True)
        self.assertEqual((output / "keep.txt").read_text(), "keep")

    def test_oversize_and_duplicate_inputs_rejected(self):
        with self.assertRaisesRegex(ValueError, "more than once"):
            snapshot_logs([self.log, self.log], self.root / "evidence")
        self.log.write_bytes(b"x" * (MAX_FILE_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "exceed"):
            snapshot_logs([self.log], self.root / "evidence")
        self.assertFalse((self.root / "evidence").exists())

    def test_imports_only_selected_provider_and_model(self):
        provider = select_provider(self.provider, self.settings.model)
        self.assertEqual(set(provider), {"slac"})
        self.assertEqual(set(provider["slac"]["models"]), {"example"})
        config = session_config(self.root, provider, self.settings.model)
        self.assertEqual(config["permission"]["*"], "deny")
        self.assertEqual(config["mcp"], {})
        self.assertEqual(config["plugin"], [])
        self.assertEqual(config["permission"]["read"]["*"], "deny")

    def test_literal_credential_rejected(self):
        data = json.loads(self.provider.read_text())
        data["provider"]["slac"]["options"]["apiKey"] = "not-a-real-secret"
        self.provider.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "reference"):
            select_provider(self.provider, self.settings.model)

    def test_runtime_does_not_inherit_opencode_overrides(self):
        with patch.dict(os.environ, {"OPENCODE_CONFIG_CONTENT": '{"permission":"allow"}',
                                     "OPENCODE_CONFIG": "/unexpected/config"}):
            env = runtime_environment(self.root)
        self.assertNotIn("OPENCODE_CONFIG_CONTENT", env)
        self.assertNotIn("OPENCODE_CONFIG", env)
        self.assertEqual(env["OPENCODE_DISABLE_PROJECT_CONFIG"], "true")

    def test_text_without_evidence_access_is_rejected(self):
        events = self.root / "events.jsonl"
        events.write_text(json.dumps({"type": "text", "part": {"text": json.dumps(RESPONSE)}}))
        with self.assertRaisesRegex(ValueError, "read every"):
            audit_evidence_access(events, self.root, [{"id": "log-1", "snapshot": "evidence/log-1.txt"}])

    def test_error_event_cannot_be_mistaken_for_success(self):
        events = self.root / "events.jsonl"
        events.write_text(json.dumps({"type": "error", "error": {"message": "example failure"}}))
        with self.assertRaisesRegex(ValueError, "error event"):
            extract_response(events)


if __name__ == "__main__":
    unittest.main()
