from contextlib import redirect_stdout
from dataclasses import replace
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
from claude_fixtures import fake_claude_env
from daq_agent.chat import create_conversation
from daq_agent.cli import main
from daq_agent.config import Settings
from daq_agent.report_store import load_report
from daq_agent.task_transfer import prepare_transfer, load_transfer, launch_transfer, parse_transfer_request


class TransferModelTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        provider = self.root / 'provider.json'
        provider.write_text(json.dumps({'provider': {'example': {'npm': '@ai-sdk/anthropic',
            'models': {'test': {}, 'other': {}}, 'options': {'apiKey': '{env:SYNTHETIC_KEY}',
            'baseURL': 'https://example.invalid'}}}}))
        self.settings = Settings('tmo', 'UTC', 'opus', runtime='claude',
                                 provider_config=str(provider), opencode=sys.executable,
                                 claude=sys.executable)
        report = load_report(write_report(self.root / 'reports'))
        self.chat = create_conversation(report, 'opus', self.root / 'chats', runtime='claude',
                                        notes_root=self.root / 'notes')
        for context in (redirect_stdout(io.StringIO()),
                        patch('sys.stdin.isatty', return_value=True),
                        patch('sys.stdout.isatty', return_value=True)):
            context.__enter__()
            self.addCleanup(context.__exit__, None, None, None)

    def run_opencode(self, directory, *, expected, resume=False, model=None):
        def run(command, **kwargs):
            self.assertEqual(command[command.index('--model') + 1], expected)
            config = json.loads((directory / '.opencode/opencode.json').read_text())
            self.assertEqual(config['model'], expected)
            self.assertEqual(config['small_model'], expected)
            self.assertEqual('--continue' in command, resume)
            return subprocess.CompletedProcess(command, 0)
        with patch('daq_agent.task_transfer.subprocess.run', side_effect=run) as process:
            self.assertEqual(launch_transfer(directory, runtime='opencode', model=model, resume=resume), 0)
        process.assert_called_once()

    def test_prepare_switch_validates_model_before_creating_handoff_and_preserves_chat_identity(self):
        for model in (None, 'opus', '--invalid'):
            with self.subTest(model=model), self.assertRaisesRegex(ValueError, 'model'):
                prepare_transfer(self.chat, self.settings, runtime='opencode', model=model)
            self.assertFalse((self.chat / 'transfers').exists())
            self.assertFalse((self.root / 'notes').exists())
        directory = prepare_transfer(self.chat, self.settings, runtime='opencode', model='example/test')
        _, metadata = load_transfer(directory)
        self.assertEqual(metadata['opencode_model'], 'example/test')
        self.assertEqual(metadata['claude_model'], 'opus')
        self.assertEqual(metadata['model'], 'opus')
        note = json.loads((directory / 'note-template.json').read_text())
        self.assertEqual(note['origin']['answer_model'], 'opus')
        self.run_opencode(directory, expected='example/test')
        self.run_opencode(directory, expected='example/test', resume=True)

    def test_existing_claude_handoff_requires_explicit_model_and_remembers_it_on_resume(self):
        directory = prepare_transfer(self.chat, self.settings)
        path = directory / 'transfer.json'
        metadata = json.loads(path.read_text())
        metadata.pop('opencode_model')  # Before the model-selection fix.
        path.write_text(json.dumps(metadata))
        original = path.read_bytes()
        with patch('daq_agent.task_transfer.subprocess.run') as process:
            with self.assertRaisesRegex(ValueError, '--model provider/model'):
                launch_transfer(directory, runtime='opencode')
            with self.assertRaisesRegex(ValueError, 'absent'):
                launch_transfer(directory, runtime='opencode', model='example/missing')
            process.assert_not_called()
        self.assertFalse((directory / 'runtime/opencode/selection.json').exists())
        self.run_opencode(directory, expected='example/other', model='example/other')
        self.run_opencode(directory, expected='example/other', resume=True)
        self.assertEqual(path.read_bytes(), original)
        record = directory / 'runtime/opencode/selection.json'
        self.assertEqual(json.loads(record.read_text()), {'model': 'example/other'})
        self.assertEqual(record.stat().st_mode & 0o777, 0o600)
        with self.assertRaisesRegex(ValueError, 'retains the saved model'):
            launch_transfer(directory, runtime='opencode', resume=True, model='example/test')
        record.write_text('{"model": "opus"}')
        with self.assertRaisesRegex(ValueError, 'OpenCode requires'):
            launch_transfer(directory, runtime='opencode', resume=True)

    def test_legacy_opencode_resume_and_new_model_override(self):
        settings = replace(self.settings, runtime='opencode', model='example/test')
        directory = prepare_transfer(self.chat, settings)
        path = directory / 'transfer.json'
        metadata = json.loads(path.read_text())
        for name in ('opencode_model', 'runtime', 'claude_model'):
            metadata.pop(name)
        path.write_text(json.dumps(metadata))
        self.run_opencode(directory, expected='example/test', resume=True)
        self.run_opencode(directory, expected='example/other', model='example/other')
        self.run_opencode(directory, expected='example/other', resume=True)

    def test_reverse_switch_supports_claude_model_override_and_exact_session_resume(self):
        settings = replace(self.settings, runtime='opencode', model='example/test')
        directory = prepare_transfer(self.chat, settings, runtime='claude', model='sonnet')
        _, metadata = load_transfer(directory)
        self.assertEqual(metadata['opencode_model'], 'example/test')
        self.assertEqual(metadata['claude_model'], 'sonnet')
        with self.assertRaisesRegex(ValueError, 'without a provider'):
            prepare_transfer(self.chat, settings, runtime='claude', model='example/test')
        commands = []
        def run(command, **kwargs):
            if '--help' in command:
                return subprocess.CompletedProcess(command, 0, '--restricted', '')
            if '--version' in command:
                return subprocess.CompletedProcess(command, 0, 'synthetic-claude', '')
            commands.append(command)
            return subprocess.CompletedProcess(command, 0)
        with patch.dict(os.environ, fake_claude_env(self.root)), \
                patch('daq_agent.claude_transfer.subprocess.run', side_effect=run):
            launch_transfer(directory, runtime='claude', model='haiku')
            launch_transfer(directory, runtime='claude', resume=True)
        self.assertEqual([c[c.index('--model') + 1] for c in commands], ['haiku', 'haiku'])
        self.assertEqual(commands[0][commands[0].index('--session-id') + 1],
                         commands[1][commands[1].index('--resume') + 1])
        self.assertEqual(load_transfer(directory)[1]['claude_model'], 'sonnet')
        with self.assertRaisesRegex(ValueError, 'retains the saved model'):
            launch_transfer(directory, runtime='claude', resume=True, model='opus')

    def test_slash_command_and_cli_route_model_without_changing_source_chat(self):
        for flags in ('--runtime opencode --model example/test --prepare-only',
                      '--model example/test --prepare-only --runtime opencode'):
            self.assertEqual(parse_transfer_request('/task-transfer ' + flags + ' Is F001 "related"?'),
                             (True, 'Is F001 "related"?', 'opencode', 'example/test'))
        for suffix in ('--model', '--model --runtime opencode'):
            with self.assertRaisesRegex(ValueError, '--model requires'):
                parse_transfer_request('/task-transfer ' + suffix)
        self.assertEqual(main(['chat', '--resume', self.chat.name, '--state-root', str(self.root / 'chats'),
                               '--provider-config', self.settings.provider_config,
                               '--opencode', self.settings.opencode,
                               '--question', '/task-transfer --prepare-only --runtime opencode --model example/test']), 0)
        directory = next((self.chat / 'transfers').iterdir())
        self.assertEqual(load_transfer(directory)[1]['opencode_model'], 'example/test')
        self.assertEqual(json.loads((self.chat / 'manifest.json').read_text())['model'], 'opus')
        with patch('daq_agent.task_transfer.launch_transfer', return_value=0) as launch:
            self.assertEqual(main(['task-transfer', str(directory), '--runtime', 'opencode',
                                   '--model', 'example/other']), 0)
        launch.assert_called_once_with(directory, runtime='opencode', model='example/other', resume=False)
