from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from chat_fixtures import fake_chat_runtime
from claude_fixtures import fake_claude, fake_claude_env
from fake_runtime import write_fake_runtime
from daq_agent.chat import answer_question, completed_turns, create_conversation, load_conversation
from daq_agent.chat_answers import render_answer, validate_answer
from daq_agent.config import Settings
from daq_agent.investigation_evidence import with_known_conditions
from daq_agent.notes import read_note, render_note, save_note
from daq_agent.report_context import select_context
from daq_agent.report_skills import retained_skills
from daq_agent.report_store import load_report
from daq_agent.reporting import generate_report
from daq_agent.task_transfer import prepare_transfer, load_transfer, transfer_config
from daq_agent.transfer_tools import call_tool


RESET = 'pvxs.tcp.io connection to Client synthetic closed with socket error 104 : Connection reset by peer'


class KnownConditionFollowupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.start = datetime(2026, 9, 1, tzinfo=timezone.utc)
        self.end = self.start + timedelta(days=1)
        provider = self.root / 'provider.json'
        provider.write_text(json.dumps({'provider': {'example': {'npm': '@ai-sdk/anthropic',
            'models': {'test': {}}, 'options': {'apiKey': '{env:SYNTHETIC_KEY}',
            'baseURL': 'https://example.invalid'}}}}))
        self.settings = Settings('tmo', 'UTC', 'example/test',
                                 provider_config=str(provider), opencode='not-installed',
                                 known_conditions=('pyxpm-connection-reset',),
                                 log_root=str(self.root / 'logs'))

    def report(self, name='report', *, automatic=False, count=1, mixed=False):
        logs = []
        for i in range(count):
            path = self.root / f'logs/2026/09/01_{i:02}:00:00_node:pyxpm.log'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# ID: pyxpm\n# PLATFORM: 0\n# TESTRELDIR: /synthetic/release\n'
                            + '2026-09-01T01:00:00Z ' + RESET + '\n'
                            + ('ERROR synthetic unrelated failure\n' if mixed else ''))
            os.utime(path, (self.start.timestamp(), self.start.timestamp()))
            logs.append(path)
        settings = self.settings
        if mixed:
            runtime = write_fake_runtime(self.root, {'summary': 'Synthetic remaining failure.',
                'findings': [], 'limitations': ['Synthetic only.']})
            settings = replace(settings, opencode=str(runtime))
        generate_report(settings, self.start, self.end, self.root / name,
                        logs=None if automatic else logs, synthetic=not automatic)
        # Follow-up must work without live access to the original files.
        for path in logs:
            path.unlink()
        return load_report(self.root / name)

    def chat(self, report):
        return create_conversation(report, self.settings.model, self.root / 'chats',
                                   notes_root=self.root / 'notes')

    def bytes_in(self, directory):
        return {str(p.relative_to(directory)): p.read_bytes()
                for p in directory.rglob('*') if p.is_file()}

    def test_existing_known_only_reports_gain_citable_followup_without_rewriting_report(self):
        for automatic in (False, True):
            with self.subTest(automatic=automatic):
                report = self.report(str(automatic), automatic=automatic)
                before = self.bytes_in(report.directory)
                self.assertEqual(report.manifest['generation_statistics']['model_sessions_completed'], 0)
                self.assertNotIn(RESET, ''.join(report.evidence.values()))
                chat = self.chat(report)
                # No new report fields/migration are needed for pre-fix reports/chats.
                self.assertFalse((chat / 'known-conditions').exists())
                metadata, investigation, _, _ = load_conversation(chat)
                source = investigation.manifest['sources'][-1]
                context, evidence = select_context(investigation, 'Explain the pyXPM connection reset')
                self.assertIn(source['id'], evidence)
                raw = evidence[source['id']]
                self.assertIn(RESET.encode(), raw)
                self.assertIn(b'Matching lines: 1', raw)
                self.assertIn(b'original-line=4:', raw)
                self.assertIn(b'platform: 0; release: /synthetic/release', raw)
                self.assertIn(b'not the complete original logs', raw)
                self.assertEqual(source['sha256'], hashlib.sha256(raw).hexdigest())
                self.assertEqual(context['known_condition_sources'][0]['source'], source['id'])
                self.assertIn(source['id'], select_context(investigation, 'Summarize this report')[1])
                self.assertEqual(Path(source['citation_path']).read_bytes(), raw)
                self.assertEqual(Path(source['citation_path']).stat().st_mode & 0o777, 0o600)
                self.assertEqual(metadata, load_conversation(chat)[0])
                self.assertEqual(before, self.bytes_in(report.directory))

    def test_both_chat_runtimes_audit_appendix_and_keep_working_saved_note_citations(self):
        report = self.report()
        before = self.bytes_in(report.directory)
        for runtime in ('opencode', 'claude'):
            with self.subTest(runtime=runtime), patch.dict(os.environ, fake_claude_env(self.root)):
                chat = self.chat(report)
                metadata, investigation, _, _ = load_conversation(chat)
                source = investigation.manifest['sources'][-1]
                source_id = source['id']
                line = next(i for i, text in enumerate(investigation.evidence[source_id].splitlines(), 1)
                            if RESET in text)
                response = {'answer': 'One pyXPM connection reset was retained; recovery is unknown.',
                            'citations': [{'source': source_id, 'line_start': line, 'line_end': line}],
                            'limitations': ['Only a captured representative example is available.']}
                settings = (replace(self.settings, opencode=str(fake_chat_runtime(self.root, source=source_id)))
                            if runtime == 'opencode' else
                            replace(self.settings, runtime='claude', model='sonnet',
                                    claude=fake_claude(self.root, response)))
                answer, context = answer_question(chat, settings, 'Explain the pyXPM connection reset')
                turn = chat / 'turns/0001'
                audit = json.loads((turn / 'manifest.json').read_text())['runtime_audit']
                self.assertIn(source_id, audit['sources_read'])
                self.assertIn(source_id, {s['id'] for s in context['sources']})
                self.assertEqual((turn / f'evidence/{source_id}.txt').read_bytes(),
                                 investigation.raw_evidence[source_id])
                resumed = load_conversation(chat)[1]
                accepted = completed_turns(chat, resumed)
                self.assertEqual(accepted[0]['response'], answer)
                _, note = save_note(self.root / 'notes', resumed, metadata, turn=accepted[0])
                self.assertIn(source['citation_path'], render_note(note))
                self.assertIn(source['citation_path'], render_answer(answer, resumed))
                self.assertEqual(read_note(self.root / 'notes', 'tmo', note['id']), note)
                bad = {**answer, 'citations': [{'source': source_id, 'line_start': 1,
                                              'line_end': source['lines'] + 1}]}
                with self.assertRaisesRegex(ValueError, 'outside'):
                    validate_answer(json.dumps(bad), context['sources'])
        self.assertEqual(before, self.bytes_in(report.directory))

    def test_transfer_reads_appendix_and_saves_validated_note_for_either_runtime(self):
        report = self.report()
        before = self.bytes_in(report.directory)
        chat = self.chat(report)
        for runtime in ('claude', 'opencode'):
            directory = prepare_transfer(chat, self.settings, 'Explain pyXPM resets', runtime=runtime)
            _, metadata = load_transfer(directory)
            source = json.loads((directory / 'report.json').read_text())['sources'][-1]
            self.assertEqual(source['citation_path'], str(directory / source['snapshot']))
            path = Path(source['citation_path'])
            self.assertIn(RESET, path.read_text())
            result = call_tool(directory, 'read_file', {'path': source['snapshot']})
            self.assertIn(RESET, result)
            config = transfer_config(directory, metadata, {})
            self.assertEqual(config['permission']['read'][str(path)], 'allow')
            self.assertNotIn(str(path), config['permission']['edit'])
            citation = {k: source[k] for k in ('snapshot', 'sha256', 'lines', 'citation_path')}
            citation.update(source=source['id'], line_start=1, line_end=source['lines'])
            content = {'text': 'Captured reset; recovery remains unknown.',
                       'limitations': ['Representative retained evidence only.'], 'citations': [citation]}
            with self.assertRaisesRegex(ValueError, 'citation path'):
                call_tool(directory, 'save_note', {**content, 'citations': [
                    {**citation, 'citation_path': str(self.root / 'wrong.txt')}]})
            call_tool(directory, 'save_note', content)
            note = read_note(self.root / 'notes', 'tmo', metadata['id'])
            self.assertIn(str(path), render_note(note))
            with self.assertRaises(ValueError):
                call_tool(directory, 'read_file', {'path': str(self.root / 'unrelated')})
        self.assertEqual(before, self.bytes_in(report.directory))

    def test_mixed_batched_reports_keep_mapping_and_excluded_initial_inputs(self):
        report = self.report(count=9, mixed=True)
        before = self.bytes_in(report.directory)
        provenance = retained_skills(report)[0]
        self.assertEqual(report.manifest['generation_statistics']['model_sessions_completed'], 2)
        self.assertNotIn(RESET, ''.join(report.evidence.values()))
        chat = self.chat(report)
        metadata, investigation, _, _ = load_conversation(chat)
        self.assertEqual(metadata['skills'], provenance)
        self.assertEqual(investigation.manifest['sources'][-1]['id'], 'log-10')
        context, evidence = select_context(investigation, 'Explain known pyXPM connection resets')
        self.assertIn(b'Matching lines: 9', evidence['log-10'])
        self.assertLessEqual(len(evidence), 8)
        transfer = prepare_transfer(chat, self.settings)
        self.assertEqual((transfer / 'evidence/log-9.txt').read_bytes(), report.raw_evidence['log-9'])
        self.assertEqual((transfer / 'evidence/log-10.txt').read_bytes(), evidence['log-10'])
        self.assertEqual(before, self.bytes_in(report.directory))

    def test_appendix_tampering_symlinks_and_oversized_metadata_fail_closed(self):
        report = self.report()
        chat = self.chat(report)
        _, investigation, _, _ = load_conversation(chat)
        path = Path(investigation.manifest['sources'][-1]['citation_path'])
        original = path.read_bytes()
        path.write_text('invented evidence')
        with self.assertRaisesRegex(ValueError, 'integrity'):
            load_conversation(chat)
        path.unlink()
        other = self.root / 'other'
        other.write_bytes(original)
        path.symlink_to(other)
        with self.assertRaisesRegex(ValueError, 'integrity'):
            load_conversation(chat)
        path.unlink()
        path.write_bytes(original)
        report.manifest['known_conditions']['items'][0]['examples'][0]['context'][0]['text'] = 'x' * 65536
        with self.assertRaisesRegex(ValueError, '64 KiB'):
            with_known_conditions(report, self.chat(load_report(report.directory)))
