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

from daq_agent.batch_report import generate_report, report_settings, report_window
from daq_agent.cli import main
from daq_agent.collectors.session_logs import collect_logs, time_bucket
from daq_agent.config import Settings
from daq_agent.viewer import latest_report


class BatchReportTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.logs = self.root / "logs"
        self.logs.mkdir()
        self.start = datetime(2026, 9, 1, tzinfo=timezone.utc)
        self.end = self.start + timedelta(days=2)
        self.settings = Settings("tmo", 0, "UTC", "example/model", log_root=str(self.logs))

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
        self.assertEqual(set(inputs), {0, 6})
        self.assertEqual([len(paths) for paths in inputs.values()], [2, 2])
        metadata = json.loads((self.root / "inputs/collection.json").read_text())
        self.assertEqual(len(metadata["files"]), 2)
        record = next(r for r in metadata["files"] if r["partition"] == 0)
        self.assertEqual(record["sha256"], hashlib.sha256(previous.read_bytes()).hexdigest())
        self.assertEqual(record["matches"]["error|outside_if_local"], 1)
        self.assertIn("2026/08/31", inputs[0][1].read_text())
        self.assertNotIn("partition 6", inputs[0][1].read_text())
        self.assertEqual(inputs[0][1].stat().st_mode & 0o777, 0o600)

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
        document = inputs[0][1].read_text()
        self.assertIn("UnicodeEncodeError: synthetic exception terminator", document)
        self.assertNotIn("synthetic-sensitive-value", document)
        self.assertIn("[REDACTED sensitive field]", document)
        record = json.loads((self.root / "inputs/collection.json").read_text())["files"][0]
        self.assertEqual(record["matches"]["traceback_or_fatal|untimed_or_unparsed"], 1)
        self.assertEqual(record["matches"]["pv_read|inside"], 3)
        self.assertEqual(record["matches"]["memory_error|untimed_or_unparsed"], 1)
        self.assertEqual(record["matches"]["slow_link_config|untimed_or_unparsed"], 1)

    def test_unknown_partition_fails_without_assigning_default(self):
        self.log(partition="unknown")
        with self.assertRaisesRegex(ValueError, "PLATFORM"):
            self.collect()

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

    def test_missing_requested_partition_fails(self):
        self.log()
        with self.assertRaisesRegex(ValueError, "requested partition"):
            self.collect(partitions=[0, 6])

    def test_ambiguous_bare_timestamp_is_not_assigned_to_window(self):
        value = time_bucket("2026-11-01 01:30:00 ERROR", self.start, self.end,
                            ZoneInfo("America/Los_Angeles"))
        self.assertEqual(value, "untimed_or_unparsed")

    def test_prepare_creates_partition_runs_and_preserves_existing_output(self):
        self.log()
        self.log("2026/09/02_00:00:00_node:other.log", partition=6)
        output = self.root / "batch"
        result = generate_report(self.settings, self.start, self.end, output, prepare_only=True)
        self.assertEqual(result["status"], "prepared_only")
        self.assertEqual([r["partition"] for r in result["reports"]], [6, 0])
        for partition in (0, 6):
            manifest = json.loads((output / f"partition-{partition}/manifest.json").read_text())
            self.assertEqual(manifest["settings"]["partition"], partition)
            self.assertEqual(manifest["status"], "prepared_only")
        before = (output / "batch.json").read_bytes()
        with self.assertRaises(FileExistsError):
            generate_report(self.settings, self.start, self.end, output, prepare_only=True)
        self.assertEqual(before, (output / "batch.json").read_bytes())

    def test_failed_partition_retains_other_results_and_batch_fails(self):
        self.log()
        self.log("2026/09/02_00:00:00_node:other.log", partition=6)
        output = self.root / "batch"
        from daq_agent.log_analysis import analyze_logs
        def analyze(settings, *args, **kwargs):
            if settings.partition == 6:
                raise ValueError("synthetic failure")
            return analyze_logs(settings, *args, **kwargs)
        with patch("daq_agent.batch_report.analyze_logs", side_effect=analyze):
            with self.assertRaisesRegex(ValueError, "partition analyses failed"):
                generate_report(self.settings, self.start, self.end, output, prepare_only=True)
        batch = json.loads((output / "batch.json").read_text())
        self.assertEqual(batch["status"], "failed")
        self.assertEqual([r["status"] for r in batch["reports"]], ["failed", "prepared_only"])

    def test_packaged_profile_cli_prepares_without_credentials_or_checkout(self):
        self.log()
        output = self.root / "batch"
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

    def test_viewer_discovers_nested_batch_report(self):
        self.log()
        output = self.root / "reports/tmo/2026/09/example-report"
        generate_report(self.settings, self.start, self.end, output, prepare_only=True)
        run = output / "partition-0"
        manifest = json.loads((run / "manifest.json").read_text())
        manifest.update(status="completed", completed_at=self.end.isoformat())
        (run / "manifest.json").write_text(json.dumps(manifest))
        (run / "findings.json").write_text(json.dumps({"summary": "Synthetic test", "findings": [], "limitations": ["Synthetic test only"]}))
        report = latest_report(self.root / "reports", "tmo")
        self.assertEqual(report.directory, run)


if __name__ == "__main__":
    unittest.main()
