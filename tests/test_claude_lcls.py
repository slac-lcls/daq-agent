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

from claude_fixtures import fake_claude
from chat_fixtures import write_report
from test_claude_reporting import REPORT, ANSWER
from daq_agent.claude_config import claude_environment, executable_path, options
from daq_agent.config import Settings, load_settings, validate_model, runtime_settings
from daq_agent.log_analysis import analyze_logs
from daq_agent.chat import create_conversation, answer_question, load_conversation
from daq_agent.cli import main
from daq_agent.report_store import load_report
from daq_agent.task_transfer import prepare_transfer, load_transfer
from daq_agent.claude_transfer import launch_claude


class LCLSClaudeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = self.root / '.claude-lcls'
        self.config.mkdir()
        self.key = self.root / 'shared-key'
        self.key.write_text('SYNTHETIC_SHARED_KEY\n')
        (self.config / 'settings.json').write_text(json.dumps({
            'env': {'ANTHROPIC_BASE_URL': 'https://gateway.example.invalid',
                    'ANTHROPIC_DEFAULT_OPUS_MODEL': 'synthetic-opus[1m]',
                    'ANTHROPIC_AUTH_TOKEN': 'MUST_NOT_IMPORT'},
            'apiKeyHelper': 'touch /must-not-execute', 'hooks': {'SessionStart': []},
            'permissions': {'defaultMode': 'auto'}}))
        for context in (
            patch('pathlib.Path.home', return_value=self.root),
            patch('daq_agent.claude_config.LCLS_KEY_FILE', str(self.key)),
            patch.dict(os.environ, {'ANTHROPIC_AUTH_TOKEN': 'PERSONAL_MUST_NOT_IMPORT',
                                    'ANTHROPIC_BASE_URL': 'https://wrong.example.invalid',
                                    'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}),
        ):
            context.start()
            self.addCleanup(context.stop)
        self.settings = Settings('tmo', 'UTC', 'opus', runtime='claude', claude_deployment='lcls')

    def fake(self, response):
        return fake_claude(self.root, response, model='synthetic-opus[1m]',
                           auth_name='ANTHROPIC_API_KEY', auth_value='SYNTHETIC_SHARED_KEY', lcls=True)

    def test_shared_key_is_explicit_no_helper_execution_or_personal_fallback(self):
        env = claude_environment(self.root, 'lcls')
        self.assertEqual(env['ANTHROPIC_API_KEY'], 'SYNTHETIC_SHARED_KEY')
        self.assertNotIn('ANTHROPIC_AUTH_TOKEN', env)
        self.assertEqual(env['ANTHROPIC_BASE_URL'], 'https://gateway.example.invalid')
        self.assertEqual(env['CLAUDE_CONFIG_DIR'], str(self.root / 'runtime/claude/config'))
        self.key.unlink()
        with self.assertRaisesRegex(ValueError, 'ps-users'):
            claude_environment(self.root, 'lcls')
        self.key.write_text('two tokens\n')
        with self.assertRaisesRegex(ValueError, 'Invalid shared'):
            claude_environment(self.root, 'lcls')

    def test_direct_binary_resolution_survives_current_symlink_change(self):
        first, second, current = (self.root / p for p in ('first', 'second', 'current'))
        for path in (first, second):
            path.write_text('#!/bin/sh\nexit 0\n')
            path.chmod(0o700)
        current.symlink_to(first)
        with patch('daq_agent.claude_config.LCLS_BINARY', str(current)):
            resolved = executable_path('claude-lcls', 'lcls')
            current.unlink()
            current.symlink_to(second)
            self.assertEqual(resolved, str(first))
            self.assertEqual(executable_path('claude', 'lcls'), str(second))
        wrapper = self.root / 'wrapper'
        wrapper.write_text('#!/bin/sh\n# Central LCLS Claude;\n')
        wrapper.chmod(0o700)
        with self.assertRaisesRegex(ValueError, 'interactive launcher'):
            executable_path(str(wrapper), 'personal')

    def test_profile_model_validation_and_selected_settings(self):
        profile = load_settings(Path('config/hutches/tmo.toml'))
        self.assertEqual((profile.runtime, profile.model, profile.claude_deployment), ('claude', 'opus', 'lcls'))
        validate_model('us.anthropic.claude-opus-5-5[1m]', 'claude')
        for model in ('opus[bad]', 'opus;echo', 'provider/opus', 'opus[1m][1m]'):
            with self.assertRaises(ValueError):
                validate_model(model, 'claude')
        for kwargs in ({'claude_deployment': 'unknown'}, {'claude_effort': 'arbitrary'},
                       {'claude_cache_ttl': 'forever'}):
            with self.assertRaises(ValueError):
                runtime_settings(profile, **kwargs)

    def test_report_and_chat_enforce_isolation_and_record_cache_provenance(self):
        log = self.root / 'input.txt'
        log.write_text('SYNTHETIC error\n')
        output = self.root / 'report'
        executable = self.fake(REPORT)
        analyze_logs(self.settings, '2026-09-23', '2026-09-24', [log], output, None, executable, synthetic=True)
        report = load_report(output)
        details = report.manifest['runtime_details']
        self.assertEqual(details['deployment'], 'lcls')
        self.assertEqual(details['effort'], 'medium')
        self.assertEqual(details['prompt_cache_ttl'], '1h')
        self.assertEqual(details['model'], 'synthetic-opus[1m]')
        self.assertEqual(details['usage']['cache_creation']['ephemeral_1h_input_tokens'], 100)
        report = load_report(write_report(self.root / 'reports', upstream=True))
        settings = replace(self.settings, claude=self.fake(ANSWER))
        chat = create_conversation(report, 'opus', self.root / 'chats', runtime='claude',
                                   claude_options=options(settings), notes_root=self.root / 'notes')
        answer, _ = answer_question(chat, settings, 'Explain F001')
        self.assertEqual(answer, ANSWER)
        # Resume must use saved deployment and executable, even though CLI defaults differ.
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['chat', '--resume', chat.name, '--state-root', str(self.root / 'chats'),
                                   '--question', 'Explain F001 again']), 0)
        self.assertEqual(load_conversation(chat)[0]['claude'], settings.claude)
        for path in self.root.rglob('*'):
            if path.is_file() and any(parent.name in ('report', 'chats') for parent in path.parents):
                self.assertNotIn(b'SYNTHETIC_SHARED_KEY', path.read_bytes())

    def test_transfer_inherits_model_and_retains_resolved_model_on_resume(self):
        report = load_report(write_report(self.root / 'reports', upstream=True))
        executable = self.fake(REPORT)
        settings = replace(self.settings, claude=executable)
        chat = create_conversation(report, 'opus', self.root / 'chats', runtime='claude', notes_root=self.root / 'notes')
        transfer = prepare_transfer(chat, settings)
        _, metadata = load_transfer(transfer)
        self.assertEqual(metadata['claude_model'], 'opus')
        self.assertEqual(metadata['claude_deployment'], 'lcls')
        commands = []
        def run(command, **kwargs):
            if '--help' in command:
                return subprocess.CompletedProcess(command, 0, '--restricted', '')
            if '--version' in command:
                return subprocess.CompletedProcess(command, 0, 'synthetic-claude', '')
            commands.append(command)
            self.assertNotIn('ANTHROPIC_AUTH_TOKEN', kwargs['env'])
            return subprocess.CompletedProcess(command, 0)
        with redirect_stdout(io.StringIO()), patch('daq_agent.claude_transfer.subprocess.run', side_effect=run), \
                patch('sys.stdin.isatty', return_value=True), patch('sys.stdout.isatty', return_value=True):
            launch_claude(transfer, metadata)
            data = json.loads((self.config / 'settings.json').read_text())
            data['env']['ANTHROPIC_DEFAULT_OPUS_MODEL'] = 'new-model'
            (self.config / 'settings.json').write_text(json.dumps(data))
            launch_claude(transfer, metadata, resume=True)
        for command in commands:
            self.assertEqual(command[command.index('--model') + 1], 'synthetic-opus[1m]')
            self.assertEqual(json.loads(command[command.index('--settings') + 1])['effortLevel'], 'medium')
        self.assertIn('--resume', commands[1])
