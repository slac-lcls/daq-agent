from contextlib import redirect_stdout
from datetime import datetime
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from daq_agent.cli import default_output, main
from daq_agent.config import Settings


class CliDefaultsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.config = self.root / "config.toml"
        self.config.write_text(
            'hutch="tmo"\npartition=0\ntimezone="America/Los_Angeles"\n'
            'model="slac/example"\n'
            f'provider_config="{self.root}/provider.json"\n'
            f'opencode="{self.root}/opencode"\n'
            f'output_root="{self.root}/new-parent/agent-logs"\n'
        )
        self.log = self.root / "input.log"
        self.log.write_text("SYNTHETIC example\n")
        self.args = ["analyze-logs", "--config", str(self.config),
                     "--from", "2026-08-01", "--to", "2026-08-02", "--log", str(self.log)]

    def invoke(self, extra):
        stream = io.StringIO()
        with redirect_stdout(stream):
            self.assertEqual(main(self.args + extra), 0)
        return json.loads(stream.getvalue())

    def test_prepare_groups_distinct_runs_by_hutch_and_launch_month(self):
        instant = datetime(2026, 9, 21, 9, 30, tzinfo=ZoneInfo("America/Los_Angeles"))
        with patch("daq_agent.cli.datetime") as clock:
            clock.now.return_value = instant
            first = Path(self.invoke(["--prepare-only"])["output"])
            second = Path(self.invoke(["--prepare-only"])["output"])
            self.config.write_text(self.config.read_text().replace('hutch="tmo"', 'hutch="rix"'))
            other_hutch = Path(self.invoke(["--prepare-only"])["output"])
        self.assertNotEqual(first, second)
        self.assertEqual(first.parent, self.root / "new-parent/agent-logs/tmo/2026/09")
        self.assertEqual(other_hutch.parent, self.root / "new-parent/agent-logs/rix/2026/09")
        for path in (first, second, other_hutch):
            manifest = json.loads((path / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "prepared_only")
            self.assertEqual(path.stat().st_mode & 0o777, 0o700)

    def test_configured_runtime_and_cli_overrides(self):
        with patch("daq_agent.cli.analyze_logs", return_value=self.root / "result") as analyze:
            self.invoke([])
            args = analyze.call_args.args
            self.assertEqual(args[5], self.root / "provider.json")
            self.assertEqual(args[6], str(self.root / "opencode"))
            self.invoke(["--provider-config", str(self.root / "other.json"),
                         "--opencode", "other-opencode", "--output", str(self.root / "chosen")])
            args = analyze.call_args.args
            self.assertEqual(args[4], self.root / "chosen")
            self.assertEqual(args[5], self.root / "other.json")
            self.assertEqual(args[6], "other-opencode")

    def test_default_root_uses_invoking_users_home(self):
        settings = Settings("tmo", 0, "America/Los_Angeles", "slac/example")
        path = default_output(settings)
        self.assertEqual(path.parent.parent.parent, Path.home() / "daq/agent-logs/tmo")


if __name__ == "__main__":
    unittest.main()
