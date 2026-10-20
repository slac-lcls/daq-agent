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

from fake_runtime import write_fake_runtime
from daq_agent.cli import main
from daq_agent.collectors.session_logs import collect_logs
from daq_agent.known_conditions import RULES, classify_lines
from daq_agent.report_skills import retained_skills
from daq_agent.report_store import load_report
from daq_agent.reporting import generate_report, report_settings
from daq_agent.viewer import report_assets

RESET = '2026-09-01T01:00:00Z ERR pvxs.tcp.io connection to Client synthetic closed with socket error 104 : Connection reset by peer'
SHUTDOWN = 'Shutting down on TERM signal'
FREE = 'free(): double free detected in tcache 2'


class KnownConditionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.start = datetime(2026, 9, 1, tzinfo=timezone.utc)
        self.end = self.start + timedelta(days=1)
        self.logs = self.root / 'logs'
        self.settings = replace(report_settings('tmo'), timezone='UTC', log_root=str(self.logs),
                                opencode='not-installed', provider_config='/not/a/provider')

    def log(self, component, body, hour=0):
        path = self.logs / '2026/09' / f'01_{hour:02}:00:00_node:{component}.log'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'# ID: {component}\n# PLATFORM: 0\n# TESTRELDIR: /synthetic/release\n' + body + '\n')
        os.utime(path, (self.start.timestamp(), self.start.timestamp()))
        return path

    def fake_settings(self):
        provider = self.root / 'provider.json'
        provider.write_text(json.dumps({'provider': {'example': {'npm': '@ai-sdk/anthropic',
            'models': {'test': {}}, 'options': {'apiKey': '{env:SYNTHETIC_KEY}', 'baseURL': 'https://example.invalid'}}}}))
        runtime = write_fake_runtime(self.root, {'summary': 'Synthetic unknown error.', 'findings': [], 'limitations': ['Synthetic only.']})
        return replace(self.settings, model='example/test', runtime='opencode', provider_config=str(provider), opencode=str(runtime), daq_skills=None)

    def test_rules_require_shutdown_component_and_actual_recovery(self):
        enabled = tuple(RULES)
        self.assertFalse(classify_lines([FREE], 'drp', enabled))
        self.assertFalse(classify_lines([SHUTDOWN] + ['normal'] * 6 + [FREE], 'drp', enabled))
        self.assertEqual(classify_lines([SHUTDOWN, FREE], 'drp', enabled)[1][0], 'daq-teardown-double-free')
        self.assertFalse(classify_lines([RESET], 'control', enabled))
        self.assertEqual(classify_lines([RESET], 'pyxpm-feh-2', enabled)[0][0], 'pyxpm-connection-reset')
        self.assertFalse(classify_lines(['ERROR:root:CuTiming not locked'], 'pyxpm-14', enabled))
        error = 'Error connecting myTrFd socket (will retry): Connection refused'
        self.assertFalse(classify_lines([error, 'Opened queue synthetic', 'Connecting to XtcMonitor server'], 'ami', enabled))
        self.assertEqual(classify_lines([error, 'Connected to XtcMonitor server'], 'ami', enabled)[0][0], 'ami-recovered-connection')
        self.assertFalse(classify_lines([error, 'Connected to XtcMonitor server'], 'control', enabled))

    def test_known_only_report_needs_no_runtime_credentials_or_skill_fetch(self):
        self.log('drp', SHUTDOWN + '\n' + FREE)
        self.log('pyxpm-feh-2', RESET, hour=1)
        for runtime, model in [('opencode', 'example/test'), ('claude', 'sonnet')]:
            output = self.root / runtime
            with patch('daq_agent.reporting.sync_skills', side_effect=AssertionError('no skill fetch')), \
                    patch('daq_agent.reporting.select_provider', side_effect=AssertionError('no provider')), \
                    patch('daq_agent.claude_runtime.preflight_claude', side_effect=AssertionError('no Claude')):
                generate_report(replace(self.settings, runtime=runtime, model=model), self.start, self.end, output)
            report = load_report(output)
            self.assertEqual(report.manifest['generation_statistics']['model_sessions_completed'], 0)
            self.assertEqual(report.manifest['generation_statistics']['model_sessions_planned'], 0)
            self.assertEqual(report.manifest['known_conditions']['matching_lines'], 2)
            self.assertEqual(len(report.manifest['sources']), 1)
            self.assertEqual(retained_skills(report)[0]['status'], 'not_required_no_model')
            self.assertEqual(report.findings['findings'], [])
            for content in report.evidence.values():
                self.assertNotIn(FREE, content)
                self.assertNotIn('Connection reset by peer', content)
            assets = report_assets(report)
            for name in ('report.md', 'report.html'):
                self.assertIn('Known conditions', assets[name][0].decode())
                self.assertIn('double free', assets[name][0].decode())
                self.assertIn('Recovery is not established', assets[name][0].decode())
            self.assertFalse((output / 'events.jsonl').exists())

    def test_mixed_logs_remove_known_context_and_counts_but_preserve_other_errors(self):
        self.log('pyxpm-feh-2', RESET + '\nERROR:root:CuTiming not locked')
        self.log('drp', SHUTDOWN + '\n' + FREE, hour=1)
        output = self.root / 'mixed'
        generate_report(self.fake_settings(), self.start, self.end, output)
        report = load_report(output)
        self.assertEqual(report.manifest['generation_statistics']['model_sessions_completed'], 1)
        self.assertEqual(len(report.manifest['sources']), 2)  # Scope and unresolved launch only.
        for raw in report.evidence.values():
            self.assertNotIn(FREE, raw)
            self.assertNotIn('Connection reset by peer', raw)
        self.assertIn('CuTiming not locked', '\n'.join(report.evidence.values()))
        metadata = json.loads((output / 'collection/collection.json').read_text())
        record = next(r for r in metadata['files'] if r['headers']['ID'] == 'pyxpm-feh-2')
        self.assertEqual(record['matches']['network_error|inside'], 1)
        self.assertNotIn('network_error|inside', record['analysis_matches'])
        self.assertEqual(record['known_conditions']['pyxpm-connection-reset|inside'], 1)

    def test_time_buckets_original_identity_and_sensitive_content(self):
        original = self.log('pyxpm-14', RESET.replace('2026-09-01', '2026-08-31') + '\n' +
                            RESET.replace('2026-09-01T01:00:00Z ', '').replace('synthetic', '<script> Authorization: secret'))
        inputs = collect_logs(self.logs, self.root / 'collected', 'tmo', self.start, self.end, 'UTC', known_conditions=tuple(RULES))
        summary = json.loads((self.root / 'collected/collection.json').read_text())['known_conditions']
        item = summary['items'][0]
        self.assertEqual(item['time_buckets'], {'outside': 1, 'untimed_or_unparsed': 1})
        self.assertEqual(item['examples'][0]['sha256'], hashlib.sha256(original.read_bytes()).hexdigest())
        self.assertEqual(item['examples'][0]['line'], 4)
        self.assertEqual(item['examples'][1]['context'][0]['text'], '[REDACTED sensitive field]')
        self.assertEqual(len(inputs), 1)

    def test_supplied_excerpts_preserve_lines_and_original_provenance(self):
        path = self.log('pyxpm-14', RESET + '\nERROR synthetic new fault')
        output = self.root / 'supplied'
        generate_report(self.fake_settings(), self.start, self.end, output, logs=[path])
        report = load_report(output)
        self.assertEqual(report.manifest['sources'][0]['original_path'], str(path))
        self.assertEqual(report.evidence['log-1'].splitlines()[3], '[omitted]')
        self.assertEqual(report.evidence['log-1'].splitlines()[4], 'ERROR synthetic new fault')
        original = json.loads((output / 'known-condition-inputs.json').read_text())['files'][0]
        self.assertEqual(original['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(report.manifest['known_conditions']['matching_lines'], 1)
        self.assertEqual(report.manifest['generation_statistics']['supplied_log_files'], 1)

    def test_supplied_known_only_and_prepare_only_skip_runtime(self):
        path = self.log('drp', SHUTDOWN + '\n' + FREE)
        output = self.root / 'supplied-known'
        generate_report(self.settings, self.start, self.end, output, logs=[path])
        self.assertEqual(load_report(output).manifest['generation_statistics']['model_sessions_completed'], 0)
        prepared = self.root / 'prepared'
        generate_report(self.settings, self.start, self.end, prepared, logs=[path], prepare_only=True)
        self.assertEqual(json.loads((prepared / 'manifest.json').read_text())['status'], 'prepared_only')

    def test_supplied_batches_keep_original_paths_and_exclude_known_lines(self):
        paths = [self.log('pyxpm-14', RESET + '\nERROR synthetic remaining fault', hour=i)
                 for i in range(9)]
        output = self.root / 'batched'
        generate_report(self.fake_settings(), self.start, self.end, output, logs=paths)
        report = load_report(output)
        self.assertEqual(report.manifest['generation_statistics']['model_sessions_completed'], 2)
        self.assertEqual(report.manifest['known_conditions']['matching_lines'], 9)
        self.assertEqual({s['original_path'] for s in report.manifest['sources']}, {str(p) for p in paths})
        for batch in sorted((output / 'batches').iterdir()):
            child = load_report(batch)
            self.assertTrue({s['original_path'] for s in child.manifest['sources']} <= {str(p) for p in paths})
            for text in child.evidence.values():
                self.assertNotIn('Connection reset by peer', text)
                self.assertIn('ERROR synthetic remaining fault', text)

    def test_cli_opt_out_restores_known_signature_to_evidence(self):
        self.log('drp', SHUTDOWN + '\n' + FREE)
        output = self.root / 'opt-out'
        with redirect_stdout(io.StringIO()):
            main(['report', '--hutch', 'tmo', '--log-root', str(self.logs), '--from', '2026-08-31',
                  '--to', '2026-09-03', '--prepare-only', '--local-skills-only', '--no-known-conditions', '--output', str(output)])
        evidence = '\n'.join(p.read_text() for p in (output / 'evidence').iterdir())
        self.assertIn(FREE, evidence)
        self.assertNotIn('known_conditions', json.loads((output / 'manifest.json').read_text()))


if __name__ == '__main__':
    unittest.main()
