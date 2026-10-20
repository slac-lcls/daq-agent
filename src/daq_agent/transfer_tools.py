"""Local stdio MCP tools with no arbitrary filesystem or command capability.

Only the immutable transfer inventory and assigned note are readable. The save
tool takes content fields, never a destination or provenance, and validates before
atomically replacing the assigned note. No network service is exposed.
"""

import json
import os
from pathlib import Path
import sys
import tempfile

from . import __version__
from .notes import MAX_NOTE_BYTES, validate_note_record
from .report_store import read_artifact
from .task_transfer import load_transfer, MAX_TRANSFER_FILE, validate_investigation_note

TOOLS = [
    {'name': 'read_file', 'description': 'Read a retained handoff/skill/evidence file or the assigned note. '
     'Use workspace-relative paths (TASK.md, brief.json, report.json, transcript.json, '
     'note-template.json, .opencode/skills/<name>/SKILL.md, evidence/<source>.txt). '
     'Returns numbered lines, with a bounded page and next line when truncated.',
     'inputSchema': {'type': 'object', 'properties': {
         'path': {'type': 'string'}, 'start_line': {'type': 'integer', 'minimum': 1},
         'line_count': {'type': 'integer', 'minimum': 1, 'maximum': 500}},
         'required': ['path'], 'additionalProperties': False}},
    {'name': 'save_note', 'description': 'Save or replace only this investigation note. '
     'Preserves identity/provenance from note-template.json; validates citations against report.json. '
     'Provide the entire current text, limitations and citations on every save.',
     'inputSchema': {'type': 'object', 'properties': {
         'text': {'type': 'string'}, 'limitations': {'type': 'array', 'items': {'type': 'string'}},
         'citations': {'type': 'array', 'items': {'type': 'object'}}},
         'required': ['text', 'limitations', 'citations'], 'additionalProperties': False}},
]


def call_tool(directory, name, arguments):
    directory, metadata = load_transfer(directory)
    if not isinstance(arguments, dict):
        raise ValueError('tool arguments must be an object')
    if name == 'read_file':
        if set(arguments) - {'path', 'start_line', 'line_count'}:
            raise ValueError('unsupported read arguments')
        path = arguments.get('path')
        if not isinstance(path, str):
            raise ValueError('path must be a string')
        if path == metadata['note_path']:
            target = Path(path)
            if not target.exists():
                raise ValueError('this investigation note has not been saved')
            raw = read_artifact(target.parent, target.name, MAX_NOTE_BYTES)
        else:
            # Accept absolute in-inventory paths without accepting traversal or aliases.
            if path.startswith(str(directory) + '/'):
                path = path[len(str(directory)) + 1:]
            if path not in metadata['files']:
                raise ValueError('read denied: path is not a retained handoff file or assigned note')
            raw = read_artifact(directory, path, MAX_TRANSFER_FILE)
        start, count = arguments.get('start_line', 1), arguments.get('line_count', 200)
        if type(start) is not int or type(count) is not int or start < 1 or not 1 <= count <= 500:
            raise ValueError('invalid line range')
        lines = raw.decode().splitlines()
        selected, size = [], 0
        for index in range(start - 1, min(start - 1 + count, len(lines))):
            line = f'{index + 1}: {lines[index]}'
            size += len(line.encode())
            if size > 128 * 1024:
                if not selected:
                    raise ValueError('single line exceeds the 128 KiB read budget')
                break
            selected.append(line)
        following = start + len(selected)
        return json.dumps({'path': path, 'total_lines': len(lines), 'lines': selected,
                           'next_line': following if following <= len(lines) else None})
    if name != 'save_note':
        raise ValueError('unknown tool')
    if set(arguments) != {'text', 'limitations', 'citations'}:
        raise ValueError('provide only text, limitations and citations')
    note = json.loads(read_artifact(directory, 'note-template.json', MAX_NOTE_BYTES))
    note.update(arguments)
    validate_note_record(note, metadata['hutch'], metadata['id'])
    validate_investigation_note(directory, metadata, note)
    target = Path(metadata['note_path'])
    fd, temporary = tempfile.mkstemp(prefix='.investigation-', dir=target.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(note, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        # Recheck integrity/symlinks immediately before publishing the note.
        load_transfer(directory)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return f'Saved investigation note: {target}'


def serve(directory, input_stream, output_stream, *, tool_list=TOOLS, caller=call_tool):
    """Small tools-only MCP stdio server; no resources, prompts, or sampling."""
    while True:
        raw = input_stream.readline(1024 * 1024 + 1)
        if not raw:
            return
        if len(raw) > 1024 * 1024:
            return  # Close an oversized message without buffering its remainder.
        request_id = None
        try:
            request = json.loads(raw)
            if not isinstance(request, dict) or request.get('jsonrpc') != '2.0':
                raise ValueError('invalid request')
            if 'id' not in request:
                continue
            request_id = request['id']
            method, params = request.get('method'), request.get('params', {})
            if method == 'initialize':
                result = {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}},
                          'serverInfo': {'name': 'daq-transfer', 'version': __version__}}
            elif method == 'ping':
                result = {}
            elif method == 'tools/list':
                result = {'tools': tool_list}
            elif method == 'tools/call':
                try:
                    content = caller(directory, params.get('name'), params.get('arguments', {}))
                    result = {'content': [{'type': 'text', 'text': content}]}
                except (OSError, ValueError, TypeError, KeyError, AttributeError):
                    # Do not echo input, host configuration or private path error details.
                    result = {'isError': True, 'content': [{'type': 'text', 'text':
                        'Tool request rejected: check the allowed tool, arguments, retained path and '
                        'input integrity. A rejected write did not save anything.'}]}
            else:
                raise ValueError('unsupported method')
            response = {'jsonrpc': '2.0', 'id': request_id, 'result': result}
        except (ValueError, TypeError, AttributeError):
            response = {'jsonrpc': '2.0', 'id': request_id,
                        'error': {'code': -32600, 'message': 'Invalid or unsupported request'}}
        output_stream.write(json.dumps(response) + '\n')
        output_stream.flush()


if __name__ == '__main__':
    workspace, _ = load_transfer(sys.argv[1])
    serve(workspace, sys.stdin.buffer, sys.stdout)
