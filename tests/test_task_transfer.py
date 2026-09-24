from contextlib import redirect_stdout
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from chat_fixtures import write_report, fake_chat_runtime
from daq_agent.chat import create_conversation, answer_question, load_conversation
from daq_agent.cli import main
from daq_agent.config import Settings
from daq_agent.notes import read_note, list_notes, select_notes
from daq_agent.report_store import load_report
from daq_agent.task_transfer import (AGENT, parse_transfer_request, prepare_transfer,
    load_transfer, transfer_config, launch_transfer, validate_transfer_note)


class TransferTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.report = load_report(write_report(self.root / 'reports', upstream=True))
        self.notes = self.root / 'notes'
        self.chat = create_conversation(self.report, 'example/test', self.root / 'chats', notes_root=self.notes)
        provider = self.root / 'provider.json'
        provider.write_text(json.dumps({'provider': {'example': {'npm': '@ai-sdk/anthropic',
            'models': {'test': {}}, 'options': {'apiKey': '{env:SYNTHETIC_KEY}',
                                            'baseURL': 'https://example.invalid/v1'}}}}))
        self.settings = Settings('tmo', 'UTC', 'example/test', provider_config=str(provider),
                                 opencode=str(fake_chat_runtime(self.root)))

    def test_preparation_preserves_pinned_bytes_all_evidence_and_complete_history(self):
        answer_question(self.chat, self.settings, 'Explain F001')
        answer_question(self.chat, self.settings, 'What evidence is missing?')
        failed = self.chat / 'turns/0003'
        failed.mkdir()
        (failed / 'manifest.json').write_text(json.dumps({'question': 'Failed question', 'status': 'failed'}))
        originals = {p: p.read_bytes() for p in self.report.directory.rglob('*') if p.is_file()}
        with patch('daq_agent.task_transfer.subprocess.run', side_effect=AssertionError('no model calls')):
            directory = prepare_transfer(self.chat, self.settings, 'Investigate the transition failure')
        _, metadata = load_transfer(directory)
        self.assertEqual(metadata['skill_provenance']['source']['revision'], 'a' * 40)
        self.assertEqual(json.loads((directory / 'brief.json').read_text())['accepted_turn_count'], 2)
        turns = json.loads((directory / 'transcript.json').read_text())
        self.assertEqual([t['question'] for t in turns], ['Explain F001', 'What evidence is missing?'])
        for source, raw in self.report.raw_evidence.items():
            self.assertEqual((directory / f'evidence/{source}.txt').read_bytes(), raw)
        upstream = load_conversation(self.chat)[2]
        for name, raw in upstream.items():
            self.assertEqual((directory / '.opencode/skills' / name).read_bytes(), raw)
        self.assertFalse(Path(metadata['note_path']).exists())
        self.assertIn(str(self.notes / 'tmo'), (directory / 'TASK.md').read_text())
        self.assertEqual(originals, {p: p.read_bytes() for p in self.report.directory.rglob('*') if p.is_file()})
        for path in (directory, *directory.rglob('*')):
            self.assertEqual(path.stat().st_mode & 0o077, 0, path)

    def test_no_goal_no_history_and_unique_note_destinations(self):
        first = prepare_transfer(self.chat, self.settings)
        second = prepare_transfer(self.chat, self.settings)
        self.assertNotEqual(load_transfer(first)[1]['note_path'], load_transfer(second)[1]['note_path'])
        brief = json.loads((first / 'brief.json').read_text())
        self.assertIsNone(brief['goal'])
        self.assertEqual(brief['accepted_turn_count'], 0)
        self.assertIn('No new goal supplied', (first / 'TASK.md').read_text())

    def test_batched_report_retains_later_sources(self):
        report = load_report(write_report(self.root / 'reports', 'batched', count=10, upstream=True))
        chat = create_conversation(report, 'example/test', self.root / 'chats', notes_root=self.notes)
        directory = prepare_transfer(chat, self.settings)
        self.assertEqual((directory / 'evidence/log-10.txt').read_bytes(), report.raw_evidence['log-10'])
        self.assertEqual(len(json.loads((directory / 'report.json').read_text())['findings']), 10)

    def test_permission_boundary_allows_only_assigned_note_edits(self):
        directory = prepare_transfer(self.chat, self.settings)
        _, meta = load_transfer(directory)
        config = transfer_config(directory, meta, {})
        permissions = config['permission']
        self.assertEqual(permissions['*'], 'deny')
        self.assertEqual(permissions['edit'], {'*': 'deny', meta['note_path']: 'allow'})
        self.assertEqual(permissions['read']['*'], 'deny')
        self.assertNotIn(str(directory / 'runtime'), permissions['read'])
        self.assertNotIn(str(directory / '.opencode/opencode.json'), permissions['read'])
        self.assertEqual(permissions['skill']['task-transfer'], 'allow')
        self.assertNotIn('report-chat', permissions['skill'])
        self.assertEqual(config['agent'][AGENT]['permission'], permissions)
        self.assertEqual(config['agent']['build'], {'disable': True})
        self.assertEqual(config['mcp'], {})
        self.assertEqual(config['plugin'], [])

    def test_integrity_and_note_symlink_fail_closed(self):
        directory = prepare_transfer(self.chat, self.settings)
        path = directory / 'evidence/log-1.txt'
        original = path.read_bytes()
        path.write_text('changed')
        with self.assertRaisesRegex(ValueError, 'integrity'):
            load_transfer(directory)
        path.write_bytes(original)
        _, meta = load_transfer(directory)
        Path(meta['note_path']).symlink_to(self.root / 'outside.json')
        with self.assertRaisesRegex(ValueError, 'regular file'):
            load_transfer(directory)

    def test_bounds_fail_before_creating_workspace(self):
        with patch('daq_agent.task_transfer.MAX_TRANSFER_BYTES', 1):
            with self.assertRaisesRegex(ValueError, 'bounded workspace'):
                prepare_transfer(self.chat, self.settings)
        self.assertFalse((self.chat / 'transfers').exists())

    def test_direct_opencode_note_is_reusable_and_validated(self):
        directory = prepare_transfer(self.chat, self.settings)
        _, meta = load_transfer(directory)
        note = json.loads((directory / 'note-template.json').read_text())
        note['text'] = 'SYNTHETIC issue_1 was observed. The cause remains unknown.'
        source = self.report.manifest['sources'][0]
        note['citations'] = [{k: source[k] for k in ('snapshot', 'sha256', 'lines')} |
                             {'source': 'log-1', 'line_start': 2, 'line_end': 2}]
        Path(meta['note_path']).write_text(json.dumps(note))
        self.assertEqual(validate_transfer_note(directory, meta), note)
        self.assertEqual(read_note(self.notes, 'tmo', meta['id'])['kind'], 'investigation_note')
        self.assertEqual(list_notes(self.notes, 'tmo')[0][0]['id'], meta['id'])
        matches = select_notes(self.notes, self.report, 'issue_1')
        self.assertEqual(matches['items'][0]['id'], meta['id'])
        note['citations'][0]['sha256'] = '0' * 64
        Path(meta['note_path']).write_text(json.dumps(note))
        with self.assertRaisesRegex(ValueError, 'retained evidence'):
            validate_transfer_note(directory, meta)
        note['origin']['report_fingerprint'] = '0' * 64
        Path(meta['note_path']).write_text(json.dumps(note))
        with self.assertRaisesRegex(ValueError, 'provenance'):
            validate_transfer_note(directory, meta)

    def test_interactive_launch_resume_isolation_and_private_note_creation(self):
        fake = self.root / 'fake-tui'
        fake.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
workspace = Path(sys.argv[1])
assert workspace == Path.cwd()
assert sys.argv[sys.argv.index('--agent')+1] == 'daq-investigation'
assert os.environ['XDG_DATA_HOME'] == str(workspace / 'runtime/data')
assert os.environ['OPENCODE_DISABLE_EXTERNAL_SKILLS'] == 'true'
config = json.loads((workspace / '.opencode/opencode.json').read_text())
meta = json.loads((workspace / 'transfer.json').read_text())
assert config['permission']['edit'] == {'*': 'deny', meta['note_path']: 'allow'}
assert config['permission']['*'] == 'deny'
assert config['mcp'] == {} and config['plugin'] == []
marker = workspace / 'fake-session.json'
if '--continue' in sys.argv:
    assert marker.exists()
else:
    assert '--prompt' in sys.argv
    marker.write_text('session')
note = json.loads((workspace / 'note-template.json').read_text())
note['text'] = 'Synthetic investigation conclusion; cause unknown.'
Path(meta['note_path']).write_text(json.dumps(note))
''')
        fake.chmod(0o700)
        directory = prepare_transfer(self.chat, replace(self.settings, opencode=str(fake)))
        with patch('sys.stdin.isatty', return_value=True), patch('sys.stdout.isatty', return_value=True):
            self.assertEqual(launch_transfer(directory), 0)
            self.assertEqual(launch_transfer(directory, resume=True), 0)
        _, meta = load_transfer(directory)
        self.assertEqual(Path(meta['note_path']).stat().st_mode & 0o777, 0o600)
        with patch('sys.stdin.isatty', return_value=False):
            with self.assertRaisesRegex(ValueError, 'interactive terminal'):
                launch_transfer(directory)

    def test_launch_interruption_retains_workspace(self):
        directory = prepare_transfer(self.chat, self.settings)
        with patch('sys.stdin.isatty', return_value=True), patch('sys.stdout.isatty', return_value=True), \
                patch('daq_agent.task_transfer.subprocess.run', side_effect=KeyboardInterrupt):
            self.assertEqual(launch_transfer(directory), 130)
        self.assertEqual(load_transfer(directory)[1]['id'], directory.name)

    def test_cli_prepare_only_and_command_parsing(self):
        self.assertEqual(parse_transfer_request('/task-transfer'), (False, ''))
        self.assertEqual(parse_transfer_request('/task-transfer --prepare-only inspect F001'), (True, 'inspect F001'))
        self.assertIsNone(parse_transfer_request('/task-transferred'))
        with self.assertRaises(ValueError):
            parse_transfer_request('/task-transfer --wrong')
        with self.assertRaises(ValueError):
            parse_transfer_request('/task-transfer ' + 'x' * 8193)
        with patch('daq_agent.task_transfer.launch_transfer') as launch, redirect_stdout(io.StringIO()):
            result = main(['chat', '--resume', self.chat.name, '--state-root', str(self.root / 'chats'),
                           '--question', '/task-transfer --prepare-only Check F001'])
        self.assertEqual(result, 0)
        launch.assert_not_called()
        directory = next((self.chat / 'transfers').iterdir())
        self.assertEqual(json.loads((directory / 'brief.json').read_text())['goal'], 'Check F001')
        with patch('daq_agent.task_transfer.launch_transfer', return_value=0) as launch:
            self.assertEqual(main(['task-transfer', str(directory), '--resume']), 0)
        launch.assert_called_once_with(directory, resume=True)


if __name__ == '__main__':
    unittest.main()
