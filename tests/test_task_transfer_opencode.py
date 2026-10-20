"""Opt-in real OpenCode tool checks; synthetic data, no model/API calls.

DAQ_TEST_OPENCODE=/path/to/opencode python -m unittest discover -s tests -p test_task_transfer_opencode.py -v
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from chat_fixtures import write_report
from daq_agent.artifacts import write_json
from daq_agent.chat import create_conversation
from daq_agent.config import Settings
from daq_agent.report_store import load_report
from daq_agent.runtime import runtime_environment
from daq_agent.task_transfer import prepare_transfer, load_transfer, transfer_config, AGENT


@unittest.skipUnless(os.environ.get('DAQ_TEST_OPENCODE'), 'set DAQ_TEST_OPENCODE for offline runtime checks')
class OpenCodeTransferTests(unittest.TestCase):
    def test_real_write_edit_and_denied_targets(self):
        with tempfile.TemporaryDirectory(prefix='daq-transfer-runtime-') as temporary:
            root = Path(temporary)
            report = load_report(write_report(root / 'reports', count=1))
            chat = create_conversation(report, 'example/test', root / 'chats', notes_root=root / 'notes')
            directory = prepare_transfer(chat, Settings('tmo', 'UTC', 'example/test'), 'Inspect synthetic issue_1')
            _, meta = load_transfer(directory)
            provider = {'example': {'npm': '@ai-sdk/anthropic',
                'options': {'baseURL': 'https://example.invalid', 'apiKey': 'unused-synthetic-key'},
                'models': {'test': {'name': 'Synthetic offline test', 'limit': {'context': 200000, 'output': 4096}}}}}
            config = transfer_config(directory, meta, provider)
            config['lsp'] = False
            config['formatter'] = False
            def configure(value):
                write_json(directory / '.opencode/opencode.json', value)
            configure(config)
            def tool(name, params, success=True):
                result = subprocess.run([os.environ['DAQ_TEST_OPENCODE'], 'debug', 'agent', AGENT,
                    '--tool', name, '--params', json.dumps(params)], cwd=directory,
                    env=runtime_environment(directory), capture_output=True, text=True, timeout=45)
                if success:
                    self.assertEqual(result.returncode, 0, result.stderr)
                else:
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertIn('prevents you', result.stderr)
                return result
            note = Path(meta['note_path'])
            self.assertFalse(note.exists())
            # Reproduce the original bug with the actual runtime first.
            for permissions in (config['permission'], config['agent'][AGENT]['permission']):
                permissions['edit'] = {'*': 'deny', str(note): 'allow'}
            configure(config)
            tool('write', {'filePath': str(note), 'content': 'original bug'}, success=False)
            self.assertFalse(note.exists())
            config = transfer_config(directory, meta, provider)
            config.update({'lsp': False, 'formatter': False})
            configure(config)
            tool('write', {'filePath': str(note), 'content': 'synthetic first save'})
            self.assertEqual(note.read_text(), 'synthetic first save')
            # Empty oldString exercises edit's create/replace branch without a
            # prior-read requirement (debug commands each create a new session).
            tool('edit', {'filePath': str(note), 'oldString': '', 'newString': 'synthetic updated save'})
            self.assertEqual(note.read_text(), 'synthetic updated save')
            other = note.with_name('other.json')
            tool('write', {'filePath': str(other), 'content': 'forbidden'}, success=False)
            self.assertFalse(other.exists())
            for target in (directory / 'report.json', directory / 'evidence/log-1.txt'):
                before = target.read_bytes()
                tool('edit', {'filePath': str(target), 'oldString': '', 'newString': 'forbidden'}, success=False)
                self.assertEqual(target.read_bytes(), before)
