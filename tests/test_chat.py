from contextlib import redirect_stdout
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from chat_fixtures import fake_chat_runtime, write_report
from daq_agent.chat import (answer_question, completed_turns, conversation_lock, conversation_path,
                            create_conversation, load_conversation, state_root)
from daq_agent.chat_answers import validate_answer
from daq_agent.cli import main
from daq_agent.config import Settings
from daq_agent.report_context import MAX_HISTORY_BYTES, recent_history, select_context
from daq_agent.report_skills import retained_skills
from daq_agent.report_store import latest_report, load_report


class ChatTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.reports = self.root / 'reports'
        self.state = self.root / 'chats'
        self.path = write_report(self.reports)
        self.report = load_report(self.path)
        provider = self.root / 'provider.json'
        provider.write_text(json.dumps({'provider': {'example': {'npm': '@ai-sdk/anthropic', 'models': {'test': {}},
                            'options': {'apiKey': '{env:SYNTHETIC_KEY}', 'baseURL': 'https://example.invalid/v1'}}}}))
        executable = fake_chat_runtime(self.root)
        self.settings = Settings('tmo', 'UTC', 'example/test', provider_config=str(provider), opencode=str(executable))

    def create(self, report=None):
        return create_conversation(report or self.report, self.settings.model, self.state)

    def turn(self, directory, question='Explain finding 1'):
        with conversation_lock(directory):
            return answer_question(directory, self.settings, question)

    def test_two_questions_resume_citations_and_report_unchanged(self):
        originals = {p: p.read_bytes() for p in self.path.rglob('*') if p.is_file()}
        directory = self.create()
        answer, context = self.turn(directory)
        self.assertEqual(answer['citations'][0]['source'], 'log-1')
        self.assertIn('log-1', [s['id'] for s in context['sources']])
        recovered = conversation_path(directory.name, self.state)
        self.assertEqual(recovered, directory)
        self.turn(recovered, 'What would help establish its cause?')
        turns = completed_turns(directory, self.report)
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[1]['finding_ids'], ['F001'])
        prompt = (directory / 'turns/0002/prompt.txt').read_text()
        self.assertIn('Explain finding 1', prompt)
        self.assertNotIn('provider.json', prompt)
        self.assertEqual(len((directory / 'transcript.jsonl').read_text().splitlines()), 2)
        self.assertEqual(originals, {p: p.read_bytes() for p in self.path.rglob('*') if p.is_file()})
        for path in directory.rglob('*'):
            self.assertEqual(path.stat().st_mode & 0o077, 0, path)

    def test_latest_skips_running_and_chat_stays_bound(self):
        running = write_report(self.reports, 'running', day=22)
        manifest = json.loads((running / 'manifest.json').read_text())
        manifest['status'] = 'running'
        (running / 'manifest.json').write_text(json.dumps(manifest))
        self.assertEqual(latest_report(self.reports).directory, self.path)
        directory = self.create()
        manifest['status'] = 'completed'
        (running / 'manifest.json').write_text(json.dumps(manifest))
        self.assertEqual(latest_report(self.reports).directory, running)
        self.assertEqual(load_conversation(directory)[1].directory, self.path)

    def test_batched_report_later_source_and_pinned_skills(self):
        report = load_report(write_report(self.reports, 'large', count=10, upstream=True))
        directory = self.create(report)
        fake_chat_runtime(self.root, source='log-10')
        answer, context = self.turn(directory, 'Explain F010')
        self.assertEqual(answer['citations'][0]['source'], 'log-10')
        metadata = json.loads((directory / 'turns/0001/manifest.json').read_text())
        self.assertEqual(metadata['runtime_audit']['skills_loaded'], ['psana-daq', 'psana-daq-logs', 'report-chat'])
        self.assertIn('Retained version one.', load_conversation(directory)[2]['psana-daq/SKILL.md'].decode())
        child = report.directory / 'batches/001'
        with self.assertRaisesRegex(ValueError, 'internal analysis batch'):
            self.create(load_report(child))

    def test_skill_tampering_and_inconsistent_batches_fail(self):
        report = load_report(write_report(self.reports, 'skills', count=9, upstream=True))
        directory = self.create(report)
        skill = report.directory / 'batches/002/upstream-skills/psana-daq/SKILL.md'
        raw = skill.read_bytes()
        skill.write_bytes(raw + b'changed')
        with self.assertRaisesRegex(ValueError, 'integrity'):
            load_conversation(directory)
        skill.write_bytes(raw)
        child = report.directory / 'batches/002/manifest.json'
        metadata = json.loads(child.read_text())
        metadata['upstream_skills']['source']['revision'] = 'b' * 40
        child.write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, 'inconsistent'):
            retained_skills(report)

    def test_missing_skill_provenance_does_not_follow_current_config(self):
        manifest = self.report.manifest
        manifest.pop('upstream_skills')
        with self.assertRaisesRegex(ValueError, 'no retained skill'):
            self.create()

    def test_resume_rejects_changed_findings_or_snapshot(self):
        directory = self.create()
        path = self.path / 'findings.json'
        original = path.read_bytes()
        modified = json.loads(original)
        modified['summary'] = 'Changed report'
        path.write_text(json.dumps(modified))
        with self.assertRaisesRegex(ValueError, 'changed'):
            load_conversation(directory)
        path.write_bytes(original)
        (self.path / 'evidence/log-1.txt').write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'integrity'):
            load_conversation(directory)

    def test_out_of_scope_or_out_of_range_citations_rejected(self):
        context, _ = select_context(self.report, 'F001')
        for citation in ({'source': 'log-2', 'line_start': 1, 'line_end': 1},
                         {'source': 'log-1', 'line_start': 0, 'line_end': 2},
                         {'source': 'log-1', 'line_start': 2, 'line_end': 400}):
            result = {'answer': 'Synthetic.', 'citations': [citation], 'limitations': ['Synthetic.']}
            with self.assertRaises(ValueError):
                validate_answer(json.dumps(result), context['sources'])
        valid = {'answer': 'The retained evidence is insufficient.', 'citations': [], 'limitations': ['Need additional logs.']}
        self.assertEqual(validate_answer(json.dumps(valid), [])['citations'], [])

    def test_runtime_denied_tool_or_missing_skill_does_not_accept_turn(self):
        for options in ({'bad_tool': True}, {'skip_skill': True}, {'source': 'log-2'}):
            with self.subTest(options=options):
                directory = self.create()
                fake_chat_runtime(self.root, **options)
                with self.assertRaises(ValueError):
                    self.turn(directory, 'F001')
                self.assertEqual(completed_turns(directory, self.report), [])
                self.assertFalse((directory / 'turns/0001/answer.json').exists())
                metadata = json.loads((directory / 'turns/0001/manifest.json').read_text())
                self.assertEqual(metadata['status'], 'failed')

    def test_cancelled_turn_is_retained_and_next_turn_works(self):
        directory = self.create()
        with patch('daq_agent.chat.run_opencode', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            self.turn(directory)
        metadata = json.loads((directory / 'turns/0001/manifest.json').read_text())
        self.assertEqual(metadata['status'], 'interrupted')
        self.turn(directory)
        self.assertEqual([t['number'] for t in completed_turns(directory, self.report)], [2])

    def test_conversation_lock_and_path_traversal(self):
        directory = self.create()
        with conversation_lock(directory):
            with self.assertRaisesRegex(ValueError, 'already open'):
                with conversation_lock(directory):
                    pass
        for value in ('../report', '/tmp/abc', 'not-a-conversation'):
            with self.assertRaises(ValueError):
                conversation_path(value, self.state)

    def test_retrieval_limits_and_explicit_references(self):
        report = load_report(write_report(self.reports, 'large', count=10))
        context, sources = select_context(report, 'Explain findings 9 and 10')
        self.assertEqual(set(sources), {'log-9', 'log-10'})
        self.assertEqual([f['id'] for f in context['findings']], ['F009', 'F010'])
        context, sources = select_context(report, 'component_10')
        self.assertIn('log-10', sources)
        self.assertNotIn('log-1', sources)
        with self.assertRaisesRegex(ValueError, 'fewer findings'):
            select_context(report, 'Compare ' + ' '.join(f'F{i:03}' for i in range(1, 11)))
        for question in ('F999', 'log-999', '', 'x' * 8193):
            with self.assertRaises(ValueError):
                select_context(report, question)

    def test_history_budget_and_global_scope_counted_once(self):
        turns = [{'question': 'question', 'response': {'answer': 'x' * 4000}, 'finding_ids': []} for _ in range(12)]
        history, omitted = recent_history(turns)
        self.assertLessEqual(len(json.dumps(history).encode()), MAX_HISTORY_BYTES + 12)
        self.assertEqual(omitted, 12-len(history))
        self.report.manifest['collection'] = 'collection/collection.json'
        context, sources = select_context(self.report, 'Which issue happened most often?')
        self.assertEqual(sum(s['id'] == 'log-1' for s in context['sources']), 1)
        self.assertEqual(list(sources).count('log-1'), 1)

    def test_total_context_budget_rejects_before_model_call(self):
        directory = self.create()
        with patch('daq_agent.chat.MAX_INPUT_BYTES', 10), patch('daq_agent.chat.run_opencode') as run:
            with self.assertRaisesRegex(ValueError, 'context budget'):
                self.turn(directory)
            run.assert_not_called()
        self.assertEqual(list((directory / 'turns').iterdir()), [])

    def test_byte_budget_limits_whole_snapshots(self):
        report = load_report(write_report(self.reports, 'bytes', count=8))
        for source in report.raw_evidence:
            report.raw_evidence[source] = b'x' * (60 * 1024)
        with self.assertRaisesRegex(ValueError, 'fewer findings'):
            select_context(report, 'Explain findings 1, 2, 3, 4 and 5')
        context, sources = select_context(report, 'Explain findings 1 and 2')
        self.assertLessEqual(sum(map(len, sources.values())), 256 * 1024)

    def test_large_findings_and_no_matching_evidence(self):
        self.report.findings['findings'][0]['observation'] = 'x' * 16000
        self.report.findings['findings'][0]['hypothesis'] = 'x' * 16000
        self.report.findings['findings'][0]['next_check'] = 'x' * 16000
        self.report.findings['summary'] = 'x' * 8000
        with self.assertRaisesRegex(ValueError, 'context budget'):
            select_context(self.report, 'F001')
        self.report.findings['findings'] = []
        context, sources = select_context(self.report, 'Is calibration current?')
        self.assertEqual(sources, {})
        self.assertEqual(context['coverage']['selected_sources'], 0)

    def test_saved_chat_skill_changed_on_resume(self):
        directory = self.create()
        (directory / 'skill.md').write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'chat skill integrity'):
            load_conversation(directory)

    def test_change_during_model_call_does_not_accept_answer(self):
        directory = self.create()
        from daq_agent.runtime import run_opencode
        def run(*args, **kwargs):
            version = run_opencode(*args, **kwargs)
            path = self.path / 'findings.json'
            findings = json.loads(path.read_text())
            findings['summary'] = 'Changed while the model was answering'
            path.write_text(json.dumps(findings))
            return version
        with patch('daq_agent.chat.run_opencode', side_effect=run):
            with self.assertRaisesRegex(ValueError, 'changed'):
                self.turn(directory)
        self.assertFalse((directory / 'turns/0001/answer.json').exists())

    def test_cli_default_root_and_local_commands_without_model(self):
        config = self.root / 'viewer.toml'
        config.write_text(f'output_root={json.dumps(str(self.reports))}\n')
        output = io.StringIO()
        with patch('builtins.input', side_effect=['/findings', '/sources', '/exit']), patch('daq_agent.chat.run_opencode') as run, redirect_stdout(output):
            self.assertEqual(main(['chat', '--viewer-config', str(config), '--state-root', str(self.state)]), 0)
            run.assert_not_called()
        self.assertIn('F001', output.getvalue())
        self.assertIn(str(self.path), output.getvalue())
        chat_id = next(self.state.iterdir()).name
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['chat', '--resume', chat_id, '--state-root', str(self.state), '--question', '/report']), 0)
        with patch.dict(os.environ, {'XDG_STATE_HOME': str(self.root / 'state')}):
            self.assertEqual(state_root(), self.root / 'state/daq-agent/chats')


if __name__ == '__main__':
    unittest.main()
