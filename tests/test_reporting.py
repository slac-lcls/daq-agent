from contextlib import redirect_stdout
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from fake_runtime import write_fake_runtime

from daq_agent.reporting import generate_report, report_settings, report_window
from daq_agent.cli import main
from daq_agent.collectors.session_logs import collect_logs, time_bucket
from daq_agent.config import Settings
from daq_agent.viewer import latest_report


class ReportingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.logs = self.root / "logs"
        self.logs.mkdir()
        self.start = datetime(2026, 9, 1, tzinfo=timezone.utc)
        self.end = self.start + timedelta(days=2)
        self.settings = Settings("tmo", "UTC", "example/model", log_root=str(self.logs))

    def log(self, name="2026/09/01_00:00:00_node:control.log", partition=0, body="ERROR example\n", mtime=None):
        path = self.logs / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# PLATFORM: {partition}\n# ID: control\n# HOST: node\n# TESTRELDIR: /synthetic/release\n" + body)
        value = self.start.timestamp() if mtime is None else mtime
        os.utime(path, (value, value))
        return path

    def collect(self, **kwargs):
        return collect_logs(self.logs, self.root / "inputs", "tmo", self.start, self.end, "UTC", **kwargs)

    def test_window_is_elapsed_time_across_dst_and_validated(self):
        now = datetime(2026, 11, 2, 12, tzinfo=ZoneInfo("America/Los_Angeles"))
        start, end = report_window("2d", None, None, "America/Los_Angeles", now=now)
        self.assertEqual(end - start, timedelta(hours=48))
        self.assertEqual(start.astimezone(now.tzinfo).hour, 13)
        for value in ("0d", "8d", "169h", "2days", "-1h"):
            with self.assertRaises(ValueError):
                report_window(value, None, None, "UTC")
        with self.assertRaises(ValueError):
            report_window("2d", "2026-09-01", None, "UTC")
        with self.assertRaises(ValueError):
            report_window(None, None, None, "UTC")

    def test_month_boundary_carry_in_partition_and_provenance(self):
        previous = self.log("2026/08/31_10:00:00_node:control.log", body="2026-08-31 10:00:00 ERROR old\n")
        self.log("2026/08/30_10:00:00_node:old.log", mtime=self.start.timestamp() - 1)
        self.log("2026/09/02_10:00:00_node:other.log", partition=6)
        self.log("2026/09/04_10:00:00_node:future.log")
        inputs = self.collect()
        self.assertEqual(len(inputs), 3)
        metadata = json.loads((self.root / "inputs/collection.json").read_text())
        self.assertEqual(len(metadata["files"]), 2)
        record = next(r for r in metadata["files"] if r["partition"] == 0)
        self.assertEqual(record["sha256"], hashlib.sha256(previous.read_bytes()).hexdigest())
        self.assertEqual(record["matches"]["error|outside_if_local"], 1)
        self.assertIn("2026/08/31", inputs[1].read_text())
        self.assertNotIn("partition 6", inputs[1].read_text())
        self.assertEqual(inputs[1].stat().st_mode & 0o777, 0o600)

    def test_traceback_end_memory_errors_counts_and_secret_masking(self):
        body = ("fatal: detected dubious ownership\n"
                "2026-09-01T01:00:00Z ERROR failed to read CA PV\n" * 3 +
                "Traceback (most recent call last):\n" +
                "  File synthetic.py, line 7\n" * 8 +
                "UnicodeEncodeError: synthetic exception terminator\n"
                "double free or corruption\n"
                "ERROR Authorization: Bearer synthetic-sensitive-value\n"
                "Inbound  link with DRP ID 3 configured in 1500 ms\n")
        self.log(body=body)
        inputs = self.collect()
        document = inputs[1].read_text()
        self.assertIn("UnicodeEncodeError: synthetic exception terminator", document)
        self.assertNotIn("synthetic-sensitive-value", document)
        self.assertIn("[REDACTED sensitive field]", document)
        record = json.loads((self.root / "inputs/collection.json").read_text())["files"][0]
        self.assertEqual(record["matches"]["traceback_or_fatal|untimed_or_unparsed"], 1)
        self.assertEqual(record["matches"]["pv_read|inside"], 3)
        self.assertEqual(record["matches"]["memory_error|untimed_or_unparsed"], 1)
        self.assertEqual(record["matches"]["slow_link_config|untimed_or_unparsed"], 1)

    def test_missing_and_unknown_platform_preserved_without_excluding_logs(self):
        self.log(partition="unknown")
        other = self.log("2026/09/01_00:00:00_node:other.log", partition=6)
        missing = self.log("2026/09/01_00:00:00_node:missing.log")
        missing.write_text("ERROR no headers\n")
        inputs = self.collect()
        self.assertEqual(len(inputs), 2)
        metadata = json.loads((self.root / "inputs/collection.json").read_text())
        self.assertEqual(len(metadata["files"]), 3)
        self.assertEqual([r["partition"] for r in metadata["files"]], [None, None, 6])
        self.assertIn(str(other), inputs[1].read_text())
        self.assertIn(str(missing), inputs[1].read_text())

    def test_excess_launches_fail_before_reading_file_contents(self):
        for hour in range(8):
            self.log(f"2026/09/01_{hour:02}:00:00_node:control.log")
        with patch("daq_agent.collectors.session_logs.capture") as capture:
            with self.assertRaisesRegex(ValueError, "seven launch groups"):
                self.collect()
            capture.assert_not_called()
        self.assertFalse((self.root / "inputs").exists())

    def test_compressed_and_oversized_candidates_fail(self):
        path = self.log(name="2026/09/01_00:00:00_node:control.log.zst")
        with self.assertRaisesRegex(ValueError, "compressed"):
            self.collect()
        path.unlink()
        self.log()
        with patch("daq_agent.collectors.session_logs.MAX_SCAN_FILE", 1):
            with self.assertRaisesRegex(ValueError, "scan exceeds"):
                collect_logs(self.logs, self.root / "inputs2", "tmo", self.start, self.end, "UTC")

    def test_symlink_candidate_fails(self):
        original = self.log()
        original.with_name("01_00:00:00_node:link.log").symlink_to(original)
        with self.assertRaisesRegex(ValueError, "non-symlink"):
            self.collect()

    def test_separate_launches_with_same_platform_are_both_included(self):
        self.log()
        self.log("2026/09/02_00:00:00_node:control.log")
        inputs = self.collect()
        self.assertEqual(len(inputs), 3)
        self.assertIn("2026/09/01_00:00:00", inputs[1].read_text())
        self.assertIn("2026/09/02_00:00:00", inputs[2].read_text())

    def test_ambiguous_bare_timestamp_is_not_assigned_to_window(self):
        value = time_bucket("2026-11-01 01:30:00 ERROR", self.start, self.end,
                            ZoneInfo("America/Los_Angeles"))
        self.assertEqual(value, "untimed_or_unparsed")

    def test_prepare_creates_one_hutch_report_and_preserves_existing_output(self):
        self.log()
        self.log("2026/09/02_00:00:00_node:other.log", partition=6)
        output = self.root / "report"
        result = generate_report(self.settings, self.start, self.end, output, prepare_only=True)
        self.assertEqual(result["status"], "prepared_only")
        manifest = json.loads((output / "manifest.json").read_text())
        self.assertNotIn("partition", manifest["settings"])
        self.assertEqual(manifest["scope"], {"kind": "hutch"})
        self.assertEqual(len(manifest["sources"]), 3)
        self.assertEqual(manifest["status"], "prepared_only")
        collection = json.loads((output / manifest["collection"]).read_text())
        self.assertEqual({r["partition"] for r in collection["files"]}, {0, 6})
        for source in manifest["sources"]:
            self.assertTrue(Path(source["original_path"]).is_file())
        self.assertFalse(list(output.glob("partition-*")))
        before = (output / "manifest.json").read_bytes()
        with self.assertRaises(FileExistsError):
            generate_report(self.settings, self.start, self.end, output, prepare_only=True)
        self.assertEqual(before, (output / "manifest.json").read_bytes())

    def fake_settings(self):
        provider = self.root / "provider.json"
        provider.write_text(json.dumps({"provider": {"example": {
            "npm": "@ai-sdk/anthropic",
            "options": {"apiKey": "{env:TEST_EXAMPLE_KEY}", "baseURL": "https://example.invalid/v1"},
            "models": {"model": {"name": "Example"}},
        }}}))
        runtime = write_fake_runtime(self.root, {
            "summary": "Synthetic multi-session report.", "findings": [],
            "limitations": ["Synthetic fixture; no live DAQ or model access."],
        })
        return replace(self.settings, provider_config=str(provider), opencode=str(runtime))

    def test_one_analysis_reads_all_launches_and_renders_hutch_report(self):
        self.log()
        self.log("2026/09/02_00:00:00_node:other.log", partition=6)
        output = self.root / "reports/tmo/2026/09/example-report"
        from daq_agent.log_analysis import analyze_logs
        with patch("daq_agent.reporting.analyze_logs", wraps=analyze_logs) as analyze:
            result = generate_report(self.fake_settings(), self.start, self.end, output)
        self.assertEqual(analyze.call_count, 1)
        self.assertEqual(result["status"], "completed")
        manifest = json.loads((output / "manifest.json").read_text())
        self.assertEqual(manifest["runtime_audit"]["sources_read"], ["log-1", "log-2", "log-3"])
        for name in ("report.md", "report.html"):
            text = (output / name).read_text()
            self.assertIn("scope: hutch and time window", text)
            self.assertNotIn("partition: None", text)
        self.assertEqual(latest_report(self.root / "reports", "tmo").directory, output)

    def test_failed_analysis_retains_collection_and_failed_manifest(self):
        self.log()
        output = self.root / "report"
        with patch("daq_agent.log_analysis.run_opencode", side_effect=ValueError("synthetic failure")):
            with self.assertRaisesRegex(ValueError, "synthetic failure"):
                generate_report(self.fake_settings(), self.start, self.end, output)
        manifest = json.loads((output / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "failed")
        self.assertTrue((output / manifest["collection"]).is_file())
        self.assertFalse((output / "report.html").exists())

    def test_packaged_profile_cli_prepares_without_credentials_or_checkout(self):
        self.log()
        output = self.root / "report"
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = main(["report", "--hutch", "tmo", "--from", "2026-08-31", "--to", "2026-09-03",
                         "--log-root", str(self.logs), "--output", str(output),
                         "--prepare-only", "--local-skills-only"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stream.getvalue())["status"], "prepared_only")
        with self.assertRaisesRegex(ValueError, "no packaged profile"):
            report_settings("rix")
        repository = Path(__file__).resolve().parents[1]
        self.assertEqual((repository / "src/daq_agent/profiles/tmo.toml").read_text(),
                         (repository / "config/hutches/tmo.toml").read_text())

    def test_cli_has_one_reporting_command_and_no_partition_filter(self):
        stream = io.StringIO()
        with redirect_stdout(stream), self.assertRaises(SystemExit) as raised:
            main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("report", stream.getvalue())
        self.assertNotIn("analyze-logs", stream.getvalue())
        stream = io.StringIO()
        with redirect_stdout(stream), self.assertRaises(SystemExit):
            main(["report", "--help"])
        self.assertNotIn("--partition", stream.getvalue())



if __name__ == "__main__":
    unittest.main()
