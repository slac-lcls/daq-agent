from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from chat_fixtures import write_report
from daq_agent.chat import create_conversation
from daq_agent.claude_transfer import claude_environment
from daq_agent.cli import main
from daq_agent.config import Settings
from daq_agent.report_store import load_report
from daq_agent.task_transfer import (prepare_transfer, load_transfer, launch_transfer,
                                     parse_transfer_request, validate_transfer_note)
from daq_agent.transfer_tools import call_tool


class ClaudeTransferTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        report = load_report(write_report(self.root / 'reports', upstream=True))
        self.chat = create_conversation(report, 'example/test', self.root / 'chats', notes_root=self.root / 'notes')
        self.settings = Settings('tmo', 'UTC', 'example/test')
        self.workspace = prepare_transfer(self.chat, self.settings, 'Investigate issue_1', runtime='claude')
        _, self.metadata = load_transfer(self.workspace)
        self.auth = self.root / 'personal-claude'
        self.auth.mkdir()
        (self.auth / 'settings.json').write_text(json.dumps({
            'env': {'ANTHROPIC_AUTH_TOKEN': 'SYNTHETIC_PRIVATE_TOKEN',
                    'ANTHROPIC_BASE_URL': 'https://example.invalid',
                    'ANTHROPIC_DEFAULT_SONNET_MODEL': 'synthetic-sonnet',
                    'UNTRUSTED': 'not-imported'},
            'hooks': {'SessionStart': [{'command': 'must not run'}]}}))
        self.env = {'PATH': os.environ['PATH'], 'CLAUDE_CONFIG_DIR': str(self.auth),
                    'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}
        self.fields = {'text': 'Synthetic issue_1 observed; cause unknown.',
                       'limitations': ['Synthetic evidence only; not independently reviewed.'], 'citations': []}

    def test_selection_goal_and_old_workspace_compatibility(self):
        for flags in ('--prepare-only --runtime claude', '--runtime claude --prepare-only'):
            self.assertEqual(parse_transfer_request('/task-transfer ' + flags + ' Is F001 "related"?'),
                             (True, 'Is F001 "related"?', 'claude'))
        self.assertEqual(parse_transfer_request('/task-transfer --runtime claude'), (False, '', 'claude'))
        for value in ('--runtime', '--runtime nope', '--runtime claude --unknown'):
            with self.assertRaises(ValueError):
                parse_transfer_request('/task-transfer ' + value)
        with patch('daq_agent.task_transfer.launch_transfer', return_value=0) as launch:
            self.assertEqual(main(['task-transfer', str(self.workspace), '--runtime', 'claude', '--resume']), 0)
        launch.assert_called_once_with(self.workspace, runtime='claude', resume=True)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['chat', '--resume', self.chat.name, '--state-root', str(self.root / 'chats'),
                                   '--question', '/task-transfer --prepare-only --runtime claude']), 0)
        newest = [p for p in (self.chat / 'transfers').iterdir() if p != self.workspace][0]
        self.assertEqual(load_transfer(newest)[1]['runtime'], 'claude')
        self.assertIsNone(json.loads((newest / 'brief.json').read_text())['goal'])
        old = prepare_transfer(self.chat, self.settings)
        data = json.loads((old / 'transfer.json').read_text())
        data.pop('runtime')
        (old / 'transfer.json').write_text(json.dumps(data))
        with patch('sys.stdin.isatty', return_value=True), patch('sys.stdout.isatty', return_value=True):
            with self.assertRaisesRegex(ValueError, 'provider_config'):
                launch_transfer(old)

    def test_auth_is_selective_and_environment_wins(self):
        with patch.dict(os.environ, self.env | {'ANTHROPIC_AUTH_TOKEN': 'SYNTHETIC_OVERRIDE',
                                               'CLAUDE_CODE_SAFE_MODE': '1'}, clear=True):
            env = claude_environment(self.workspace)
        self.assertEqual(env['ANTHROPIC_AUTH_TOKEN'], 'SYNTHETIC_OVERRIDE')
        self.assertEqual(env['ANTHROPIC_DEFAULT_SONNET_MODEL'], 'synthetic-sonnet')
        self.assertNotIn('UNTRUSTED', env)
        self.assertNotIn('CLAUDE_CODE_SAFE_MODE', env)
        self.assertEqual(env['CLAUDE_CONFIG_DIR'], str(self.workspace / 'runtime/claude/config'))
        (self.auth / 'settings.json').write_text('{}')
        with patch.dict(os.environ, self.env, clear=True):
            with self.assertRaisesRegex(ValueError, 'OAuth/apiKeyHelper'):
                claude_environment(self.workspace)

    def test_read_boundary_pagination_and_integrity(self):
        result = json.loads(call_tool(self.workspace, 'read_file', {'path': 'evidence/log-1.txt', 'line_count': 1}))
        self.assertEqual(result['lines'], ['1: SYNTHETIC launch 1'])
        self.assertEqual(result['next_line'], 2)
        for path in ('../transfer.json', 'transfer.json', 'runtime/claude/session.json',
                     str(self.auth / 'settings.json'), str(Path(self.metadata['note_path']).with_name('other.json'))):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'read denied'):
                call_tool(self.workspace, 'read_file', {'path': path})
        evidence = self.workspace / 'evidence/log-1.txt'
        evidence.write_text('corrupted')
        with self.assertRaisesRegex(ValueError, 'integrity'):
            call_tool(self.workspace, 'read_file', {'path': 'TASK.md'})

    def test_note_save_rejects_paths_bad_provenance_citations_and_symlinks(self):
        target = Path(self.metadata['note_path'])
        call_tool(self.workspace, 'save_note', self.fields)
        before = target.read_bytes()
        self.assertEqual(validate_transfer_note(self.workspace, self.metadata)['text'], self.fields['text'])
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        cases = [self.fields | {'path': str(self.root / 'other')}, self.fields | {'origin': {}},
                 self.fields | {'text': ''}, self.fields | {'citations': [{'source': 'log-999'}]},
                 self.fields | {'text': 'x' * (64 * 1024 + 1)}]
        for fields in cases:
            with self.assertRaises(ValueError):
                call_tool(self.workspace, 'save_note', fields)
            self.assertEqual(target.read_bytes(), before)
        call_tool(self.workspace, 'save_note', self.fields | {'text': 'Updated synthetic conclusion.'})
        self.assertIn('Updated', call_tool(self.workspace, 'read_file', {'path': str(target)}))
        outside = self.root / 'outside'
        outside.write_text('unchanged')
        target.unlink()
        target.symlink_to(outside)
        with self.assertRaises(ValueError):
            call_tool(self.workspace, 'save_note', self.fields)
        self.assertEqual(outside.read_text(), 'unchanged')

    def test_mcp_subprocess_handshake_tools_and_rejected_capabilities(self):
        requests = [
            {'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-03-26'}},
            {'method': 'notifications/initialized'}, {'id': 2, 'method': 'tools/list'},
            {'id': 3, 'method': 'tools/call', 'params': {'name': 'read_file', 'arguments': {'path': 'TASK.md'}}},
            {'id': 4, 'method': 'tools/call', 'params': {'name': 'Bash', 'arguments': {'command': 'id'}}},
            {'id': 5, 'method': 'tools/call', 'params': {'name': 'save_note', 'arguments': self.fields}},
        ]
        result = subprocess.run([sys.executable, '-m', 'daq_agent.transfer_tools', str(self.workspace)],
                                input=''.join(json.dumps({'jsonrpc': '2.0', **r}) + '\n' for r in requests),
                                capture_output=True, text=True, env=os.environ | self.env, timeout=20, check=True)
        replies = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(replies), 5)
        self.assertEqual(replies[0]['result']['protocolVersion'], '2024-11-05')
        self.assertEqual({t['name'] for t in replies[1]['result']['tools']}, {'read_file', 'save_note'})
        self.assertIn('Investigate issue_1', replies[2]['result']['content'][0]['text'])
        self.assertTrue(replies[3]['result']['isError'])
        self.assertIn('Saved investigation note', replies[4]['result']['content'][0]['text'])

    def test_launcher_isolation_exact_resume_and_no_credentials_in_artifacts(self):
        fake = self.root / 'claude'
        fake.write_text(f'#!{sys.executable}\n' + '''
import json, os, sys
from pathlib import Path
if '--help' in sys.argv:
    print('--restricted'); sys.exit(0)
if '--version' in sys.argv:
    print('synthetic-claude'); sys.exit(0)
assert os.environ['ANTHROPIC_AUTH_TOKEN'] == 'SYNTHETIC_PRIVATE_TOKEN'
assert os.environ['CLAUDE_CONFIG_DIR'] == str(Path.cwd() / 'runtime/claude/config')
assert '--restricted' in sys.argv and '--strict-mcp-config' in sys.argv
assert sys.argv[sys.argv.index('--tools')+1] == 'AskUserQuestion'
assert sys.argv[sys.argv.index('--setting-sources')+1] == ''
assert sys.argv[sys.argv.index('--permission-mode')+1] == 'dontAsk'
state = Path('runtime/claude/observed.json')
if '--resume' in sys.argv:
    assert json.loads(state.read_text())['id'] == sys.argv[sys.argv.index('--resume')+1]
else:
    state.write_text(json.dumps({'id': sys.argv[sys.argv.index('--session-id')+1]}))
from daq_agent.transfer_tools import call_tool
call_tool(Path.cwd(), 'save_note', {'text': 'Synthetic result', 'limitations': ['Synthetic only'], 'citations': []})
''')
        fake.chmod(0o700)
        with patch.dict(os.environ, self.env | {'PATH': str(self.root) + os.pathsep + os.environ['PATH']}, clear=True), \
                patch('sys.stdin.isatty', return_value=True), patch('sys.stdout.isatty', return_value=True):
            with self.assertRaisesRegex(ValueError, 'no Claude session'):
                launch_transfer(self.workspace, resume=True)
            self.assertEqual(launch_transfer(self.workspace), 0)
            self.assertEqual(launch_transfer(self.workspace, resume=True), 0)
        self.assertEqual(load_transfer(self.workspace)[1]['model'], 'example/test')
        for path in self.workspace.rglob('*'):
            if path.is_file():
                self.assertNotIn(b'SYNTHETIC_PRIVATE_TOKEN', path.read_bytes())
        self.assertEqual(json.loads((self.workspace / 'runtime/claude/session.json').read_text())['model'], 'synthetic-sonnet')


if __name__ == '__main__':
    unittest.main()
