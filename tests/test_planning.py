from datetime import timedelta
from importlib.resources import files
from pathlib import Path
import tempfile
import unittest

from daq_agent.config import Settings, load_settings
from daq_agent.workflow import parse_boundary, plan_report


class PlanningTests(unittest.TestCase):
    settings = Settings("tmo", 0, "America/Los_Angeles", "slac/example-model")

    def test_calendar_window_tracks_dst(self):
        start = parse_boundary("2026-03-08", self.settings.timezone)
        end = parse_boundary("2026-03-09", self.settings.timezone)
        self.assertEqual(end - start, timedelta(hours=23))

    def test_offset_timestamps_identify_same_instant(self):
        self.assertEqual(
            parse_boundary("2026-09-18T00:00:00-07:00", self.settings.timezone),
            parse_boundary("2026-09-18T07:00:00Z", self.settings.timezone),
        )

    def test_naive_timestamp_rejected(self):
        with self.assertRaisesRegex(ValueError, "UTC offset"):
            parse_boundary("2026-11-01T01:30:00", self.settings.timezone)

    def test_empty_and_reversed_windows_rejected(self):
        for end in ("2026-09-18", "2026-09-17"):
            with self.subTest(end=end), self.assertRaises(ValueError):
                plan_report(self.settings, "2026-09-18", end)

    def test_plan_preserves_scope_and_does_not_claim_execution(self):
        plan = plan_report(self.settings, "2026-09-18", "2026-09-20")
        self.assertEqual(plan["settings"]["partition"], 0)
        self.assertEqual(plan["window"]["end_exclusive"], "2026-09-20T07:00:00+00:00")
        self.assertFalse(plan["execution_implemented"])
        self.assertEqual(plan["evidence_access"], "not_checked")

    def test_config_validation(self):
        valid = 'hutch="tmo"\npartition=0\ntimezone="America/Los_Angeles"\nmodel="slac/example-model"\n'
        invalid = [
            valid.replace("partition=0", "partition=8"),
            valid.replace("partition=0", "partition=true"),
            valid.replace("America/Los_Angeles", "Unknown/Timezone"),
            valid.replace("slac/example-model", "example-model"),
            valid + 'api_key="not-a-real-key"\n',
            valid + 'opencode=""\n',
            valid + 'provider_config=42\n',
            valid + 'output_root=[]\n',
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.toml"
            path.write_text(valid)
            self.assertEqual(load_settings(path), self.settings)
            path.write_text(valid.replace("partition=0\n", ""))
            self.assertIsNone(load_settings(path).partition)
            for content in invalid:
                path.write_text(content)
                with self.subTest(content=content), self.assertRaises(ValueError):
                    load_settings(path)

    def test_reporting_skill_is_packaged(self):
        skill = files("daq_agent").joinpath("skills/robustness-report/SKILL.md")
        self.assertTrue(skill.is_file())


if __name__ == "__main__":
    unittest.main()
