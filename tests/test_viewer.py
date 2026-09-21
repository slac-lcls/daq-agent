from contextlib import redirect_stdout
from dataclasses import replace
import hashlib
from http.client import HTTPConnection
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch

from daq_agent.cli import main
from daq_agent.html_reports import html_bundle, write_html_bundle
from daq_agent.viewer import (ViewerSettings, latest_report, load_report, load_viewer_settings,
                              make_server, save_viewer_settings, viewing_instructions)


class Tags(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.tags = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class ViewerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def report(self, name="run-1", *, status="completed", hutch="tmo", day=21):
        directory = self.root / hutch / "2026/09" / name
        (directory / "evidence").mkdir(parents=True)
        content = b'SYNTHETIC excerpt\n</script><script>alert(1)</script>\npermission denied\n'
        (directory / "evidence/log-1.txt").write_bytes(content)
        findings = {
            "summary": '<img src=x onerror="alert(1)">',
            "findings": [{"title": "Configure failure", "observation": "permission denied",
                          "hypothesis": "Unknown cause", "next_check": "Check resource ownership",
                          "evidence": [{"source": "log-1", "line_start": 2, "line_end": 3}]}],
            "limitations": ["Synthetic excerpts only"],
        }
        manifest = {
            "schema_version": 1, "workflow": "analyze-logs", "status": status,
            "created_at": f"2026-09-{day:02}T12:00:00+00:00", "evidence_kind": "synthetic",
            "settings": {"hutch": hutch, "partition": 0, "model": "slac/example"},
            "window": {"start_inclusive": "2026-09-18T07:00:00+00:00",
                       "end_exclusive": "2026-09-19T07:00:00+00:00"},
            "sources": [{"id": "log-1", "snapshot": "evidence/log-1.txt", "lines": 3,
                         "original_path": '/original/control-"quoted".log',
                         "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}],
        }
        (directory / "manifest.json").write_text(json.dumps(manifest))
        (directory / "findings.json").write_text(json.dumps(findings))
        return directory

    def test_latest_uses_completion_time_and_skips_unusable_runs(self):
        old = self.report("old", day=18)
        newest = self.report("newest", hutch="rix", day=20)
        self.report("prepared", status="prepared_only", day=22)
        self.report("failed", status="failed", day=23)
        broken = self.report("broken", day=24)
        (broken / "findings.json").unlink()
        os.utime(old / "manifest.json", (2_000_000_000, 2_000_000_000))
        self.assertEqual(latest_report(self.root).directory, newest)
        self.assertEqual(latest_report(self.root, "tmo").directory, old)
        manifest = json.loads((old / "manifest.json").read_text())
        manifest["completed_at"] = "2026-09-25T00:00:00+00:00"
        (old / "manifest.json").write_text(json.dumps(manifest))
        self.assertEqual(latest_report(self.root).directory, old)
        with self.assertRaisesRegex(ValueError, "no valid completed"):
            latest_report(self.root, "xpp")

    def test_legacy_layout_supported(self):
        original = self.report()
        legacy = self.root / "2026/09/legacy"
        legacy.parent.mkdir(parents=True)
        original.rename(legacy)
        self.assertEqual(latest_report(self.root).directory, legacy)

    def test_snapshot_integrity_and_directory_boundary(self):
        directory = self.report()
        snapshot = directory / "evidence/log-1.txt"
        original = snapshot.read_bytes()
        snapshot.write_bytes(b"changed\n")
        with self.assertRaisesRegex(ValueError, "integrity"):
            load_report(directory)
        external = self.root / "outside.txt"
        external.write_bytes(original)
        snapshot.unlink()
        snapshot.symlink_to(external)
        with self.assertRaisesRegex(ValueError, "within the run"):
            load_report(directory)

    def test_html_escapes_content_and_links_citations(self):
        report = load_report(self.report())
        pages = html_bundle(report.findings, report.manifest, report.evidence)
        document = pages["report.html"].decode()
        tags = Tags(document).tags
        self.assertNotIn("img", [tag for tag, _ in tags])
        links = [attrs for tag, attrs in tags if tag == "a"]
        citation = next(link for link in links if link.get("target") == "_blank")
        self.assertEqual(citation["href"], "logs/log-1.html#L2-L3")
        self.assertEqual(citation["rel"], "noopener noreferrer")
        log = pages["logs/log-1.html"].decode()
        self.assertIn("&lt;/script&gt;&lt;script&gt;alert(1)&lt;/script&gt;", log)
        log_tags = Tags(log).tags
        self.assertEqual(sum(tag == "script" for tag, _ in log_tags), 1)
        self.assertIn(("div", {"class": "line", "id": "L3", "data-number": "3"}), log_tags)
        self.assertIn("line.classList.toggle('selected'", log)
        write_html_bundle(report.directory, report.findings, report.manifest)
        for name, content in pages.items():
            path = report.directory / name
            self.assertEqual(path.read_bytes(), content)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_http_requires_token_and_serves_only_report_assets(self):
        report = load_report(self.report())
        (report.directory / "runtime.stderr.log").write_text("not served")
        server, token = make_server(report, 0)
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            self.assertEqual(server.server_address[0], "127.0.0.1")
            for resource in ("/report.html", "/wrong/report.html", f"/{token}/runtime.stderr.log",
                             f"/{token}/../manifest.json", f"/{token}/%2e%2e/manifest.json", f"/{token}/"):
                with self.subTest(resource=resource):
                    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                    connection.request("GET", resource)
                    response = connection.getresponse()
                    self.assertEqual(response.status, 404)
                    response.read()
                    connection.close()
            for resource in ("report.html", "logs/log-1.html", "evidence/log-1.txt", "manifest.json", "report.md"):
                connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                connection.request("GET", f"/{token}/{resource}")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader("Cache-Control"), "no-store")
                self.assertEqual(response.getheader("Referrer-Policy"), "no-referrer")
                self.assertIn("frame-ancestors 'none'", response.getheader("Content-Security-Policy"))
                content = response.read()
                if resource.endswith(".txt"):
                    self.assertEqual(content, report.raw_evidence["log-1"])
                    self.assertIn("attachment", response.getheader("Content-Disposition"))
                connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_personal_settings_and_alias_instructions(self):
        path = self.root / "config/daq-agent/viewer.toml"
        settings = ViewerSettings(output_root=str(self.root), port=8766, ssh_host="sdfiana")
        self.assertEqual(save_viewer_settings(settings, path), path)
        self.assertEqual(load_viewer_settings(path), settings)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        for invalid in (replace(settings, port=True), replace(settings, ssh_host="-oProxyCommand=bad")):
            with self.assertRaises(ValueError):
                save_viewer_settings(invalid, path)
        text = viewing_instructions(load_report(self.report()), 8766, "example-token", "sdfiana")
        self.assertIn("ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:8766:127.0.0.1:8766 sdfiana", text)
        self.assertIn("http://127.0.0.1:8766/example-token/report.html", text)
        self.assertIn("LOCAL terminal", text)
        self.assertIn("jump hosts", text)

    def test_view_cli_needs_no_hutch_configuration(self):
        with patch("daq_agent.cli.view_report", return_value=0) as view:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["view"]), 0)
            self.assertIsNone(view.call_args.args[0].run)
            self.assertIsNone(view.call_args.args[0].port)
            main(["view", "--ssh-host", "sdfiana", "--save-settings", "--port", "8766"])
            self.assertEqual(view.call_args.args[0].ssh_host, "sdfiana")
            self.assertTrue(view.call_args.args[0].save_settings)


if __name__ == "__main__":
    unittest.main()
