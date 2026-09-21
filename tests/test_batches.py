from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fake_runtime import write_fake_runtime
from daq_agent.batches import plan_batches
from daq_agent.collectors.logs import MAX_FILES, MAX_TOTAL_BYTES
from daq_agent.config import Settings
from daq_agent.log_analysis import analyze_logs
from daq_agent.reporting import generate_report
from daq_agent.reports import validate_findings
from daq_agent.viewer import latest_report, load_report, report_assets


class BatchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.start = datetime(2026, 9, 1, tzinfo=timezone.utc)
        self.end = self.start + timedelta(days=1)
        self.log_root = self.root / "input"
        month = self.log_root / "2026/09"
        month.mkdir(parents=True)
        self.logs = []
        for hour in range(8):
            path = month / f"01_{hour:02}:00:00_node:control.log"
            path.write_text(f"# PLATFORM: {hour % 2}\n# ID: control\nERROR synthetic launch {hour}\n")
            os.utime(path, (self.start.timestamp(), self.start.timestamp()))
            self.logs.append(path)
        provider = self.root / "provider.json"
        provider.write_text(json.dumps({"provider": {"example": {
            "npm": "@ai-sdk/anthropic", "models": {"test": {}},
            "options": {"apiKey": "{env:SYNTHETIC_KEY}", "baseURL": "https://example.invalid/v1"},
        }}}))
        self.response = {"summary": "Synthetic batch findings.", "limitations": ["Synthetic only."],
                         "findings": [{"title": "Synthetic error", "observation": "An error is logged.",
                                       "hypothesis": "Unknown.", "next_check": "Inspect the original source.",
                                       "evidence": [{"source": "log-2", "line_start": 1, "line_end": 2}]}]}
        self.executable = write_fake_runtime(self.root, self.response)
        self.settings = Settings("tmo", "UTC", "example/test", provider_config=str(provider),
                                 opencode=str(self.executable), log_root=str(self.log_root))
        self.output = self.root / "reports/tmo/2026/09/new-report"

    def run_report(self, **kwargs):
        return generate_report(self.settings, self.start, self.end, self.output, **kwargs)

    def test_eight_launches_produce_one_complete_report_with_remapped_citations(self):
        with patch("daq_agent.batches.analyze_logs", wraps=analyze_logs) as analyze:
            result = self.run_report()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(analyze.call_count, 2)
        for call in analyze.call_args_list:
            logs = call.args[3]
            self.assertLessEqual(len(logs), MAX_FILES)
            self.assertLessEqual(sum(p.stat().st_size for p in logs), MAX_TOTAL_BYTES)
        report = load_report(self.output)
        self.assertEqual(len(report.manifest["sources"]), 9)
        self.assertEqual([f["evidence"][0]["source"] for f in report.findings["findings"]], ["log-2", "log-9"])
        self.assertEqual([b["source_ids"] for b in report.manifest["batches"]],
                         [[f"log-{i}" for i in range(1, 9)], ["log-1", "log-9"]])
        for batch in report.manifest["batches"]:
            child = json.loads((self.output / batch["directory"] / "manifest.json").read_text())
            self.assertEqual(child["status"], "completed")
            self.assertEqual(len(child["runtime_audit"]["sources_read"]), len(batch["source_ids"]))
        assets = report_assets(report)
        self.assertIn(b'logs/log-9.html#L1-L2', assets["report.html"][0])
        self.assertIn('2026/09/01_07:00:00', report.evidence["log-9"])
        self.assertEqual(latest_report(self.root / "reports", "tmo").directory, self.output)
        (self.output / "evidence/log-9.txt").write_text("changed")
        with self.assertRaisesRegex(ValueError, "integrity"):
            load_report(self.output)

    def test_prepare_only_retains_all_inputs_and_batches_without_model_calls(self):
        with patch("daq_agent.log_analysis.run_opencode") as run:
            result = self.run_report(prepare_only=True)
            run.assert_not_called()
        manifest = json.loads((self.output / "manifest.json").read_text())
        self.assertEqual(result["status"], "prepared_only")
        self.assertEqual(len(manifest["sources"]), 9)
        self.assertEqual([b["status"] for b in manifest["batches"]], ["prepared_only", "prepared_only"])
        self.assertTrue((self.output / "collection/collection.json").exists())
        self.assertFalse((self.output / "report.md").exists())
        with self.assertRaisesRegex(ValueError, "no valid completed"):
            latest_report(self.root / "reports")

    def test_failure_in_later_batch_does_not_publish_partial_report(self):
        older = self.output.with_name("older-report")
        generate_report(self.settings, self.start, self.end, older, logs=self.logs[:2], synthetic=True)
        def analyze(*args, **kwargs):
            if kwargs["batch_context"]["number"] == 2:
                raise ValueError("synthetic later-batch failure")
            return analyze_logs(*args, **kwargs)
        with patch("daq_agent.batches.analyze_logs", side_effect=analyze):
            with self.assertRaisesRegex(ValueError, "later-batch failure"):
                self.run_report()
        manifest = json.loads((self.output / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "failed")
        self.assertEqual([b["status"] for b in manifest["batches"]], ["completed", "failed"])
        self.assertFalse((self.output / "report.md").exists())
        # Searching at this depth encounters internal batch manifests too.
        self.assertEqual(latest_report(self.root / "reports/tmo").directory, older)

    def test_byte_budget_also_splits_batches_and_repeats_only_shared_scope(self):
        paths = []
        for i in range(6):
            path = self.root / f"large-{i}.log"
            path.write_text("x" * (60 * 1024))
            paths.append(path)
        groups = plan_batches(paths, shared_scope=True)
        self.assertEqual(groups, [[0, 1, 2, 3], [0, 4, 5]])
        self.assertEqual([i for group in groups for i in group if i != 0], list(range(1, 6)))
        for group in groups:
            self.assertLessEqual(sum(paths[i].stat().st_size for i in group), MAX_TOTAL_BYTES)

    def test_supplied_excerpts_are_batched_without_treating_first_as_scope(self):
        ninth = self.root / "extra.log"
        ninth.write_text("synthetic extra source\ncontext\n")
        result = self.run_report(logs=self.logs + [ninth], synthetic=True, prepare_only=True)
        self.assertEqual(result["status"], "prepared_only")
        manifest = json.loads((self.output / "manifest.json").read_text())
        self.assertEqual(manifest["batches"][1]["source_ids"], ["log-9"])

    def test_all_findings_retained_when_combined_count_exceeds_model_limit(self):
        response = deepcopy(self.response)
        response["findings"] *= 12
        write_fake_runtime(self.root, response)
        self.run_report()
        report = load_report(self.output)
        self.assertEqual(len(report.findings["findings"]), 24)
        with self.assertRaisesRegex(ValueError, "at most 20"):
            validate_findings(json.dumps(report.findings), report.manifest["sources"])

    def test_session_budget_rejected_before_any_model_call(self):
        with patch("daq_agent.batches.MAX_BATCHES", 1), patch("daq_agent.log_analysis.run_opencode") as run:
            with self.assertRaisesRegex(ValueError, "more than 1 model batches"):
                self.run_report()
            run.assert_not_called()
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
