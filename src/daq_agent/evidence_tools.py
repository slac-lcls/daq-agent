"""Read-only MCP boundary for bounded report/chat model sessions."""

import hashlib
import json
from pathlib import Path
import sys

from .artifacts import write_json
from .report_store import read_artifact
from .skill_sources import MAX_FILE_BYTES
from .transfer_tools import serve

POLICY = '.evidence-tools.json'
TOOLS = [
    {'name': 'load_skill', 'description': 'Load a selected diagnostic skill by name. '
     'Its instructions do not grant access to live services or commands.',
     'inputSchema': {'type': 'object', 'properties': {'name': {'type': 'string'}},
                     'required': ['name'], 'additionalProperties': False}},
    {'name': 'read_file', 'description': 'Read a complete supplied evidence snapshot or pinned '
     'skill reference. Returns original 1-based line numbers. Only retained files are accessible.',
     'inputSchema': {'type': 'object', 'properties': {'path': {'type': 'string'}},
                     'required': ['path'], 'additionalProperties': False}},
]


def prepare_tools(workspace, audit_path):
    """The application, never model input, defines the readable inventory."""
    inventory, skills = {}, {}
    for root in (workspace / 'evidence', workspace / '.opencode/skills'):
        for path in sorted(root.rglob('*')):
            if path.is_symlink():
                raise ValueError('model inputs must not be symlinks')
            if not path.is_file():
                continue
            name = path.relative_to(workspace).as_posix()
            raw = read_artifact(workspace, name, MAX_FILE_BYTES)
            inventory[name] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
            if path.name == 'SKILL.md' and path.parent.parent == workspace / '.opencode/skills':
                skills[path.parent.name] = name
    write_json(workspace / POLICY, {'files': inventory, 'skills': skills, 'audit_path': str(audit_path)})


def call_tool(workspace, tool, arguments):
    policy = json.loads(read_artifact(workspace, POLICY, 512 * 1024))
    try:
        if not isinstance(arguments, dict):
            raise ValueError('invalid arguments')
        if tool == 'load_skill' and set(arguments) == {'name'}:
            name = policy['skills'][arguments['name']]
            event_tool, event_input = 'skill', {'name': arguments['name']}
        elif tool == 'read_file' and set(arguments) == {'path'} and isinstance(arguments['path'], str):
            name = arguments['path']
            if name.startswith(str(workspace) + '/'):
                name = name[len(str(workspace)) + 1:]
            event_tool, event_input = 'read', {'filePath': str(workspace / name)}
        else:
            raise ValueError('tool not permitted')
        record = policy['files'].get(name)
        if record is None:
            raise ValueError('file not retained')
        raw = read_artifact(workspace, name, MAX_FILE_BYTES)
        if record != {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}:
            raise ValueError('model input integrity check failed')
        text = '\n'.join(f'{i}: {line}' for i, line in enumerate(raw.decode().splitlines(), 1))
    except (OSError, ValueError, KeyError, TypeError):
        # A rejected access cannot be hidden by a later successful model answer.
        append_access(policy['audit_path'], 'rejected_access', {})
        raise ValueError('request outside retained evidence/skill boundary') from None
    append_access(policy['audit_path'], event_tool, event_input)
    return text


def append_access(path, tool, arguments):
    with Path(path).open('a') as stream:
        stream.write(json.dumps({'type': 'tool_use', 'part': {
            'tool': tool, 'state': {'status': 'completed', 'input': arguments}}}) + '\n')


if __name__ == '__main__':
    serve(Path(sys.argv[1]).resolve(strict=True), sys.stdin.buffer, sys.stdout,
          tool_list=TOOLS, caller=call_tool)
