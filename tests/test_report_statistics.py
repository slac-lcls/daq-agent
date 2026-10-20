from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fake_runtime import write_fake_runtime
from chat_fixtures import write_report
from daq_agent.config import Settings
from daq_agent.collectors.session_logs import collect_logs
from daq_agent.log_analysis import analyze_logs
from daq_agent.reporting import generate_report
from daq_agent.report_statistics import statistics_rows
from daq_agent.report_store import load_report
from daq_agent.viewer import report_assets


class ReportStatisticsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.start = datetime(2026, 9, 1, tzinfo=timezone.utc)
        self.end = self.start + timedelta(days=1)
        self.log_root = self.root / 'logs'
        self.month = self.log_root / '2026/09'
        self.month.mkdir(parents=True)
        provider = self.root / 'provider.json'
        provider.write_text(json.dumps({'provider': {'example': {'npm': '@ai-sdk/anthropic',
            'models': {'test': {}}, 'options': {'apiKey': '{env:SYNTHETIC_KEY}',
                                            'baseURL': 'https://example.invalid/v1'}}}}))
        runtime = write_fake_runtime(self.root, {'summary': 'Synthetic report.', 'findings': [],
                                                'limitations': ['Synthetic evidence only.']})
        self.settings = Settings('tmo', 'UTC', 'example/test', provider_config=str(provider),
                                 opencode=str(runtime), log_root=str(self.log_root))
        self.output = self.root / 'report'

    def log(self, hour, component='control', platform=0):
        path = self.month / f'01_{hour:02}:00:00_node:{component}.log'
        path.write_text(f'# PLATFORM: {platform}\n# ID: {component}\nERROR synthetic example\n')
        os.utime(path, (self.start.timestamp(), self.start.timestamp()))
        return path

    def run_report(self, **kwargs):
        generate_report(self.settings, self.start, self.end, self.output, **kwargs)
        return json.loads((self.output / 'manifest.json').read_text())

    def test_collected_counts_timing_and_both_renderings(self):
        self.log(0)
        self.log(0, 'teb', platform=6)
        self.log(1)
        clock = [100.0]
        def collect(*args, **kwargs):
            clock[0] += 20
            return collect_logs(*args, **kwargs)
        def analyze(*args, **kwargs):
            result = analyze_logs(*args, **kwargs)
            # Rendering has finished, but the report is not yet published.
            manifest = json.loads((self.output / 'manifest.json').read_text())
            self.assertEqual(manifest['status'], 'running')
            self.assertNotIn('completed_at', manifest)
            clock[0] += 40
            return result
        with patch('daq_agent.reporting.time', SimpleNamespace(monotonic=lambda: clock[0])), \
                patch('daq_agent.reporting.collect_logs', side_effect=collect), \
                patch('daq_agent.reporting.analyze_logs', side_effect=analyze):
            manifest = self.run_report()
        stats = manifest['generation_statistics']
        self.assertEqual(stats['elapsed_seconds'], 60.0)
        self.assertLessEqual(stats['started_at'], manifest['created_at'])
        self.assertLessEqual(stats['measured_through'], manifest['completed_at'])
        self.assertEqual(stats['raw_log_files_scanned'], 3)
        self.assertEqual(stats['launch_groups'], 2)
        self.assertEqual(stats['evidence_documents'], 3)
        self.assertEqual(stats['model_sessions_completed'], 1)
        self.assertIsNone(stats['numbered_daq_runs'])
        assets = report_assets(load_report(self.output))
        for name in ('report.md', 'report.html'):
            text = (self.output / name).read_text()
            self.assertIn('Generation and coverage', text)
            self.assertIn('1m 0.0s', text)
            self.assertIn('Raw log files scanned', text)
            self.assertIn('Numbered DAQ runs', text)
            self.assertIn('Not determined', text)
            self.assertEqual(assets[name][0].decode(), text)

    def test_batched_counts_do_not_duplicate_shared_scope(self):
        for hour in range(8):
            self.log(hour)
        manifest = self.run_report()
        stats = manifest['generation_statistics']
        self.assertEqual(stats['raw_log_files_scanned'], 8)
        self.assertEqual(stats['launch_groups'], 8)
        self.assertEqual(stats['evidence_documents'], 9)
        self.assertEqual(stats['model_sessions_completed'], 2)
        self.assertEqual(sum(len(b['source_ids']) for b in manifest['batches']), 10)
        self.assertEqual(manifest['status'], 'completed')

    def test_supplied_excerpts_do_not_claim_raw_file_or_launch_totals(self):
        logs = [self.log(0), self.log(1)]
        manifest = self.run_report(logs=logs, synthetic=True)
        stats = manifest['generation_statistics']
        self.assertIsNone(stats['raw_log_files_scanned'])
        self.assertIsNone(stats['launch_groups'])
        self.assertEqual(stats['supplied_log_files'], 2)
        rows = dict(statistics_rows(manifest))
        self.assertEqual(rows['Raw log files scanned'], 'Not determined (supplied excerpts)')
        self.assertEqual(rows['Supplied log files'], '2')

    def test_preparation_has_no_completed_model_sessions(self):
        for hour in range(8):
            self.log(hour)
        with patch('daq_agent.log_analysis.run_opencode') as model:
            manifest = self.run_report(prepare_only=True)
            model.assert_not_called()
        stats = manifest['generation_statistics']
        self.assertEqual(stats['model_sessions_completed'], 0)
        self.assertEqual(stats['model_sessions_planned'], 2)
        self.assertEqual(manifest['status'], 'prepared_only')
        self.assertNotIn('completed_at', manifest)
        self.assertFalse((self.output / 'report.html').exists())

    def test_final_render_failure_does_not_publish_complete_report(self):
        self.log(0)
        with patch('daq_agent.reporting.write_html_bundle', side_effect=OSError('synthetic disk failure')):
            with self.assertRaisesRegex(OSError, 'disk failure'):
                self.run_report()
        manifest = json.loads((self.output / 'manifest.json').read_text())
        self.assertEqual(manifest['status'], 'failed')
        self.assertNotIn('completed_at', manifest)
        with self.assertRaisesRegex(ValueError, 'completed report'):
            load_report(self.output)

    def test_legacy_report_unknown_duration_is_not_analysis_only_difference(self):
        directory = write_report(self.root / 'legacy')
        report = load_report(directory)
        original = (directory / 'manifest.json').read_bytes()
        rows = dict(statistics_rows(report.manifest))
        self.assertEqual(rows['Generation time'], 'Not recorded')
        self.assertEqual(rows['Raw log files scanned'], 'Not recorded')
        self.assertEqual(rows['Evidence documents'], '2')
        self.assertEqual(rows['Numbered DAQ runs'], 'Not determined')
        for name in ('report.md', 'report.html'):
            self.assertIn(b'Not recorded', report_assets(report)[name][0])
        self.assertEqual((directory / 'manifest.json').read_bytes(), original)

    def test_duration_formatting_and_invalid_metadata(self):
        manifest = {'sources': [], 'generation_statistics': {'elapsed_seconds': 3661.25}}
        self.assertEqual(dict(statistics_rows(manifest))['Generation time'], '1h 1m 1.2s')
        for value in (-1, float('nan'), float('inf'), True, 'wrong'):
            manifest['generation_statistics']['elapsed_seconds'] = value
            self.assertEqual(dict(statistics_rows(manifest))['Generation time'], 'Not recorded')


if __name__ == '__main__':
    unittest.main()
