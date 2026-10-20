"""Bounded noninteractive Claude execution for validated reports and chat."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from .artifacts import write_json, write_private
from .claude_config import claude_environment, executable_path, isolated_settings, resolved_model, provenance
from .evidence_tools import prepare_tools
from .runtime import DIAGNOSTIC_GUIDANCE, MAX_RUNTIME_BYTES


def preflight_claude(executable, workspace, deployment='personal'):
    return executable_path(executable, deployment), claude_environment(workspace, deployment)


def run_claude(executable, workspace, prompt, model, output, timeout, *, task='report', output_schema=None,
               deployment='personal', effort=None, cache_ttl=None):
    """Emit the common audited event format while retaining Claude's raw stream."""
    settings = isolated_settings(deployment, effort, cache_ttl)
    path, env = preflight_claude(executable, workspace, deployment)
    deadline = time.monotonic() + timeout
    help_result = subprocess.run([path, '--help'], env=env, capture_output=True, text=True,
                                 timeout=max(0.1, min(15, deadline - time.monotonic())), check=True)
    if '--restricted' not in help_result.stdout:
        raise ValueError('Claude requires a version with --restricted support')
    if output_schema is not None and '--json-schema' not in help_result.stdout:
        raise ValueError('Claude reports require a version with --json-schema support')
    version = subprocess.run([path, '--version'], env=env, capture_output=True, text=True,
                             timeout=max(0.1, min(15, deadline - time.monotonic())), check=True).stdout.strip()
    selected = resolved_model(model, env)
    runtime = provenance(path, version, model, env, deployment, settings)
    if output_schema is not None:
        write_json(output / 'output-schema.json', output_schema)
        runtime['output_schema'] = 'output-schema.json'
    write_json(output / 'runtime.json', runtime)
    state = Path(env['CLAUDE_CONFIG_DIR'])
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    events = output / 'events.jsonl'
    raw_events, stderr_path = output / 'claude-events.jsonl', output / 'runtime.stderr.log'
    for target in (events, raw_events, stderr_path):
        write_private(target, '')
    prepare_tools(workspace, events)
    mcp = {'mcpServers': {'daq_evidence': {'type': 'stdio', 'command': sys.executable,
           'args': ['-m', 'daq_agent.evidence_tools', str(workspace)]}}}
    config_path = workspace / 'claude-mcp.json'
    write_json(config_path, mcp)
    command = [path, '--print', '--verbose', '--output-format', 'stream-json',
               '--no-session-persistence', '--restricted', '--setting-sources', '',
               '--settings', json.dumps(settings), '--strict-mcp-config',
               '--mcp-config', str(config_path), '--tools', '', '--permission-mode', 'dontAsk',
               '--allowedTools', 'mcp__daq_evidence__load_skill,mcp__daq_evidence__read_file',
               '--disable-slash-commands', '--no-chrome', '--model', selected,
               '--append-system-prompt', 'Use mcp__daq_evidence__load_skill for every requested skill '
               'and mcp__daq_evidence__read_file for every listed snapshot. These are your only tools. '
               'Return only the task JSON object after reading evidence. ' + DIAGNOSTIC_GUIDANCE]
    if output_schema is not None:
        command += ['--json-schema', json.dumps(output_schema)]
    with raw_events.open('wb') as stdout, stderr_path.open('wb') as stderr:
        process = subprocess.Popen(command, cwd=workspace, env=env, stdin=subprocess.PIPE,
                                   stdout=stdout, stderr=stderr, start_new_session=True, umask=0o077)
        try:
            # communicate feeds even a large prompt without blocking timeout checks.
            pending = prompt.encode()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Claude exceeded the configured timeout')
                if any(p.stat().st_size > MAX_RUNTIME_BYTES for p in (events, raw_events, stderr_path)):
                    raise ValueError('Claude runtime output exceeded 8 MiB')
                try:
                    process.communicate(input=pending, timeout=min(0.1, remaining))
                    break
                except subprocess.TimeoutExpired:
                    pending = None
            if process.returncode:
                raise ValueError('Claude failed; inspect runtime.stderr.log in the private output directory')
        finally:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
    if any(p.stat().st_size > MAX_RUNTIME_BYTES for p in (events, raw_events, stderr_path)):
        raise ValueError('Claude runtime output exceeded 8 MiB')
    result = None
    for line in raw_events.read_text().splitlines():
        event = json.loads(line)
        if event.get('type') == 'result':
            if event.get('is_error') or event.get('subtype') != 'success':
                raise ValueError('Claude returned an error; inspect the private runtime artifacts')
            runtime['usage'] = cache_usage(event.get('usage', {}))
            runtime['model_usage'] = {name: cache_usage(usage) for name, usage in event.get('modelUsage', {}).items()}
            write_json(output / 'runtime.json', runtime)
            if output_schema is not None:
                structured = event.get('structured_output')
                if not isinstance(structured, dict):
                    raise ValueError('Claude returned no structured report; inspect claude-events.jsonl in the private output directory')
                result = json.dumps(structured)
            else:
                result = event.get('result')
    if not isinstance(result, str) or not result.strip():
        raise ValueError('Claude returned no final text')
    with events.open('a') as stream:
        stream.write(json.dumps({'type': 'text', 'part': {'text': result}}) + '\n')
    if events.stat().st_size > MAX_RUNTIME_BYTES:
        raise ValueError('Claude runtime output exceeded 8 MiB')
    return version


def cache_usage(usage):
    """Retain numeric token counters only, including actual cache TTL buckets."""
    if not isinstance(usage, dict):
        return {}
    names = {'input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens',
             'inputTokens', 'outputTokens', 'cacheReadInputTokens', 'cacheCreationInputTokens',
             'ephemeral_1h_input_tokens', 'ephemeral_5m_input_tokens'}
    result = {k: v for k, v in usage.items() if k in names and type(v) in (int, float) and v >= 0}
    if isinstance(usage.get('cache_creation'), dict):
        result['cache_creation'] = cache_usage(usage['cache_creation'])
    return result
