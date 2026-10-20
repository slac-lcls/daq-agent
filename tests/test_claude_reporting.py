from contextlib import redirect_stdout
from dataclasses import replace
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from claude_fixtures import fake_claude, fake_claude_env
from chat_fixtures import write_report
from daq_agent.chat import answer_question, create_conversation, load_conversation
from daq_agent.cli import main
from daq_agent.config import Settings, load_settings, runtime_settings
from daq_agent.evidence_tools import prepare_tools, call_tool
from daq_agent.log_analysis import analyze_logs
from daq_agent.reporting import generate_report
from daq_agent.report_store import load_report

REPORT = {'summary': 'Synthetic error observed; cause unknown.', 'limitations': ['Synthetic only.'],
          'findings': [{'title': 'Synthetic error', 'observation': 'An error appears.',
                        'hypothesis': 'Unknown cause.', 'next_check': 'Review more evidence.',
                        'evidence': [{'source': 'log-1', 'line_start': 1, 'line_end': 1}]}]}
ANSWER = {'answer': 'A synthetic error was observed; cause unknown.',
          'citations': [{'source': 'log-1', 'line_start': 2, 'line_end': 2}], 'limitations': ['Synthetic only.']}


class ClaudeReportingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.log = self.root / 'input.txt'
        self.log.write_text('SYNTHETIC error\n')
        self.auth_patch = patch.dict(os.environ, fake_claude_env(self.root))
        self.auth_patch.start()
        self.addCleanup(self.auth_patch.stop)
        self.settings = Settings('tmo', 'UTC', 'sonnet', runtime='claude',
                                 claude=fake_claude(self.root, REPORT), provider_config='/does/not/exist')

    def analyze(self, *, mode='normal', response=REPORT, timeout=10):
        output = self.root / ('analysis-' + mode)
        analyze_logs(self.settings, '2026-09-23', '2026-09-24', [self.log], output, None,
                     fake_claude(self.root, response, mode=mode), timeout, synthetic=True)
        return output

    def test_report_uses_personal_config_and_validates_real_tool_access(self):
        output = self.analyze()
        manifest = json.loads((output / 'manifest.json').read_text())
        self.assertEqual(manifest['settings']['runtime'], 'claude')
        self.assertEqual(manifest['runtime_details']['model'], 'synthetic-sonnet')
        self.assertEqual(manifest['runtime_details']['output_schema'], 'output-schema.json')
        self.assertTrue((output / 'output-schema.json').is_file())
        self.assertEqual(manifest['claude_version'], 'synthetic-claude')
        self.assertEqual(manifest['timeout_seconds'], 10)
        self.assertEqual(manifest['runtime_audit']['skills_loaded'], ['log-triage'])
        self.assertEqual(manifest['runtime_audit']['sources_read'], ['log-1'])
        self.assertEqual(load_report(output).findings, REPORT)
        for path in output.rglob('*'):
            if path.is_file():
                self.assertNotIn(b'SYNTHETIC_KEY', path.read_bytes())
                self.assertEqual(path.stat().st_mode & 0o077, 0, path)

    def test_structured_report_preserves_embedded_newlines(self):
        expected = json.loads(json.dumps(REPORT))
        expected['findings'][0]['observation'] = 'Synthetic observation\ncontinued on another line.'
        raw = '```json\n' + json.dumps(expected).replace('observation\\n', 'observation\n') + '\n```'
        output = self.analyze(response=raw)
        self.assertEqual(load_report(output).findings, expected)
        self.assertEqual(json.loads((output / 'response.txt').read_text()), expected)
        self.assertEqual(json.loads((output / 'findings.json').read_text()), expected)

    def test_missing_structured_result_and_schema_failure_are_not_accepted(self):
        for mode in ('unstructured', 'schema_error'):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.analyze(mode=mode)
            output = self.root / ('analysis-' + mode)
            self.assertEqual(json.loads((output / 'manifest.json').read_text())['status'], 'failed')
            self.assertFalse((output / 'report.html').exists())

    def test_structured_report_still_requires_valid_evidence(self):
        for mode in ('missing-evidence', 'empty-evidence', 'extra-field', 'unknown-source'):
            response = json.loads(json.dumps(REPORT))
            finding = response['findings'][0]
            if mode == 'missing-evidence':
                del finding['evidence']
            elif mode == 'empty-evidence':
                finding['evidence'] = []
            elif mode == 'extra-field':
                finding['unexpected'] = 'synthetic'
            else:
                finding['evidence'][0]['source'] = 'invented'
            with self.subTest(mode=mode), self.assertRaises(ValueError) as raised:
                self.analyze(mode=mode, response=response)
            output = self.root / ('analysis-' + mode)
            self.assertIn(str(output / 'response.txt'), str(raised.exception))
            if mode == 'missing-evidence':
                self.assertIn('finding 1', str(raised.exception))
                self.assertIn('missing evidence', str(raised.exception))
            self.assertFalse((output / 'report.html').exists())

    def test_report_requires_cli_schema_support_before_model_launch(self):
        path = Path(self.settings.claude)
        path.write_text(path.read_text().replace('--restricted --json-schema', '--restricted'))
        output = self.root / 'old-cli'
        with self.assertRaisesRegex(ValueError, '--json-schema support'):
            analyze_logs(self.settings, '2026-09-23', '2026-09-24', [self.log], output, None,
                         str(path), 10, synthetic=True)
        self.assertFalse((output / 'claude-events.jsonl').exists())

    def test_report_rejects_unread_evidence_denied_access_error_and_bad_citations(self):
        bad = json.loads(json.dumps(REPORT))
        bad['findings'][0]['evidence'][0]['line_end'] = 99
        for mode, response in [('skip', REPORT), ('denied', REPORT), ('error', REPORT), ('normal', bad)]:
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.analyze(mode=mode, response=response)
            output = self.root / ('analysis-' + mode)
            self.assertEqual(json.loads((output / 'manifest.json').read_text())['status'], 'failed')
            self.assertFalse((output / 'report.html').exists())

    def test_timeout_and_output_limit_fail_without_publishing(self):
        with self.assertRaises(TimeoutError) as raised:
            self.analyze(mode='delay', timeout=1)
        self.assertIn('1-second session timeout', str(raised.exception))
        self.assertIn(str(self.root / 'analysis-delay'), str(raised.exception))
        self.assertIn('new model calls', str(raised.exception))
        with patch('daq_agent.claude_runtime.MAX_RUNTIME_BYTES', 1024), self.assertRaisesRegex(ValueError, '8 MiB'):
            self.analyze(mode='overflow')
        self.assertFalse((self.root / 'analysis-delay/report.md').exists())

    def test_batches_use_claude_and_preserve_global_source_remapping(self):
        logs = []
        for i in range(9):
            path = self.root / f'log-{i}'
            path.write_text(f'SYNTHETIC error {i}\n')
            logs.append(path)
        output = self.root / 'batched'
        generate_report(self.settings, datetime(2026, 9, 23, tzinfo=timezone.utc),
                        datetime(2026, 9, 24, tzinfo=timezone.utc), output,
                        logs=logs, synthetic=True, local_skills_only=True, timeout=1800)
        report = load_report(output)
        self.assertEqual(report.manifest['timeout_seconds_per_batch'], 1800)
        self.assertEqual(report.manifest['generation_statistics']['model_sessions_completed'], 2)
        self.assertEqual([f['evidence'][0]['source'] for f in report.findings['findings']], ['log-1', 'log-9'])
        for batch in report.manifest['batches']:
            child = json.loads((output / batch['directory'] / 'manifest.json').read_text())
            self.assertEqual(child['claude_version'], 'synthetic-claude')
            self.assertEqual(child['timeout_seconds'], 1800)

    def test_chat_retry_retains_first_trace_and_audits_pinned_skills(self):
        report = load_report(write_report(self.root / 'reports', upstream=True))
        chat = create_conversation(report, 'sonnet', self.root / 'chats', runtime='claude', notes_root=self.root / 'notes')
        settings = replace(self.settings, claude=fake_claude(self.root, ANSWER, mode='retry'))
        answer, _ = answer_question(chat, settings, 'Explain F001')
        self.assertEqual(answer, ANSWER)
        turn = chat / 'turns/0001'
        status = json.loads((turn / 'manifest.json').read_text())
        self.assertEqual(status['runtime_audit']['attempts'], 2)
        self.assertEqual(status['runtime_audit']['skills_loaded'], ['psana-daq', 'psana-daq-logs', 'report-chat'])
        self.assertTrue((turn / 'rejected-attempt/claude-events.jsonl').is_file())
        self.assertEqual(load_conversation(chat)[0]['runtime'], 'claude')

    def test_cli_report_and_chat_resume_and_prepare_without_credentials(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['report', '--hutch', 'tmo', '--runtime', 'claude', '--claude-deployment', 'personal', '--model', 'sonnet', '--claude', self.settings.claude,
                                   '--last', '2d', '--log', str(self.log), '--synthetic', '--local-skills-only',
                                   '--output', str(self.root / 'cli-report')]), 0)
        report = write_report(self.root / 'reports')
        fake = fake_claude(self.root, ANSWER)
        args = ['--state-root', str(self.root / 'chats'), '--notes-root', str(self.root / 'notes'), '--claude', fake, '--claude-deployment', 'personal', '--model', 'sonnet']
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['chat', str(report), '--runtime', 'claude', '--question', 'Explain F001', *args]), 0)
            chat = next((self.root / 'chats').iterdir())
            self.assertEqual(main(['chat', '--resume', chat.name, '--question', 'Explain again', *args]), 0)
        self.assertEqual(load_conversation(chat)[0]['model'], 'sonnet')
        self.assertEqual(len(list((chat / 'turns').iterdir())), 2)
        with patch('daq_agent.claude_runtime.preflight_claude', side_effect=AssertionError('no runtime')), redirect_stdout(io.StringIO()):
            self.assertEqual(main(['report', '--hutch', 'tmo', '--runtime', 'claude', '--last', '2d',
                                   '--log', str(self.log), '--local-skills-only', '--prepare-only', '--timeout', '3600',
                                   '--output', str(self.root / 'prepared')]), 0)
        self.assertEqual(json.loads((self.root / 'prepared/manifest.json').read_text())['timeout_seconds'], 3600)

    def test_report_timeout_bounds_rejected_before_collection_or_runtime(self):
        for timeout in (0, 3601):
            with self.subTest(timeout=timeout), patch('daq_agent.reporting.collect_logs') as collect:
                with self.assertRaisesRegex(ValueError, '1 and 3600'):
                    generate_report(replace(self.settings, log_root='/synthetic'),
                                    datetime(2026, 9, 23, tzinfo=timezone.utc),
                                    datetime(2026, 9, 24, tzinfo=timezone.utc),
                                    self.root / 'invalid', timeout=timeout)
                collect.assert_not_called()
                with self.assertRaisesRegex(ValueError, '1 and 3600'):
                    self.analyze(timeout=timeout)
                self.assertFalse((self.root / 'invalid').exists())

    def test_config_runtime_defaults_and_model_validation(self):
        original = Settings('tmo', 'UTC', 'slac/example')
        self.assertEqual(runtime_settings(original).model, 'slac/example')
        self.assertEqual(runtime_settings(original, runtime='claude').model, 'sonnet')
        with self.assertRaisesRegex(ValueError, 'without a provider/'):
            runtime_settings(original, runtime='claude', model='slac/example')
        config = self.root / 'claude.toml'
        config.write_text('hutch="tmo"\ntimezone="UTC"\nruntime="claude"\nmodel="sonnet"\n')
        self.assertEqual(load_settings(config).runtime, 'claude')
        self.assertIsNone(load_settings(config).provider_config)

    def test_evidence_boundary_rejects_secret_paths_writes_and_tampering(self):
        workspace = self.root / 'workspace'
        (workspace / 'evidence').mkdir(parents=True)
        snapshot = workspace / 'evidence/log-1.txt'
        snapshot.write_text('SYNTHETIC\n')
        audit = self.root / 'audit.jsonl'
        prepare_tools(workspace, audit)
        self.assertEqual(call_tool(workspace, 'read_file', {'path': 'evidence/log-1.txt'}), '1: SYNTHETIC')
        for tool, args in [('read_file', {'path': '/etc/passwd'}), ('read_file', {'path': '.evidence-tools.json'}),
                           ('read_file', {'path': '../input.txt'}), ('save_note', {'text': 'no'}), ('Bash', {})]:
            with self.assertRaises(ValueError):
                call_tool(workspace, tool, args)
        snapshot.write_text('changed')
        with self.assertRaises(ValueError):
            call_tool(workspace, 'read_file', {'path': 'evidence/log-1.txt'})
        self.assertIn('rejected_access', audit.read_text())


if __name__ == '__main__':
    unittest.main()
