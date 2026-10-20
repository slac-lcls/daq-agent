"""Synthetic Claude CLI that exercises the real local evidence MCP server."""

import json
from pathlib import Path
import sys


def fake_claude(root, response, *, mode='normal', model='synthetic-sonnet',
                auth_name='ANTHROPIC_AUTH_TOKEN', auth_value='SYNTHETIC_KEY', lcls=False):
    executable = root / ('fake-claude-' + mode)
    executable.write_text(f'#!{sys.executable}\n' + '''
import json, os, subprocess, sys, time
from pathlib import Path
if '--help' in sys.argv:
    print('--restricted --json-schema'); sys.exit(0)
if '--version' in sys.argv:
    print('synthetic-claude'); sys.exit(0)
prompt = sys.stdin.read()
schema = json.loads(sys.argv[sys.argv.index('--json-schema') + 1]) if '--json-schema' in sys.argv else None
assert '--restricted' in sys.argv and '--strict-mcp-config' in sys.argv
assert sys.argv[sys.argv.index('--tools') + 1] == ''
assert sys.argv[sys.argv.index('--setting-sources') + 1] == ''
assert '--no-session-persistence' in sys.argv
''' + f'''
assert sys.argv[sys.argv.index('--model') + 1] == {model!r}
assert os.environ[{auth_name!r}] == {auth_value!r}
if {lcls!r}:
    assert 'ANTHROPIC_AUTH_TOKEN' not in os.environ
    assert json.loads(sys.argv[sys.argv.index('--settings') + 1]) == {{'autoMemoryEnabled': False, 'effortLevel': 'medium', 'promptCacheTtl': '1h'}}
mode = {mode!r}
response = {response!r}
''' + '''
if mode == 'delay':
    time.sleep(60)
if mode == 'overflow':
    print('x' * 10000); sys.exit(0)
config = json.loads(Path(sys.argv[sys.argv.index('--mcp-config') + 1]).read_text())
assert set(config['mcpServers']) == {'daq_evidence'}
server = config['mcpServers']['daq_evidence']
process = subprocess.Popen([server['command'], *server['args']], stdin=subprocess.PIPE,
                           stdout=subprocess.PIPE, text=True)
def request(method, params):
    process.stdin.write(json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params}) + '\\n')
    process.stdin.flush()
    result = json.loads(process.stdout.readline())['result']
    if mode != 'denied': assert not result.get('isError'), result
    return result
request('initialize', {'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'test','version':'1'}})
policy = json.loads(Path('.evidence-tools.json').read_text())
if schema is not None:
    assert schema['additionalProperties'] is False
    assert set(schema['required']) == {'summary', 'findings', 'limitations'}
    finding = schema['properties']['findings']['items']
    assert set(finding['required']) == {'title', 'observation', 'hypothesis', 'next_check', 'evidence'}
    assert finding['additionalProperties'] is False
    assert finding['properties']['evidence']['minItems'] == 1
    citation = finding['properties']['evidence']['items']
    assert set(citation['required']) == {'source', 'line_start', 'line_end'}
    assert citation['properties']['source']['enum'] == [Path(n).stem for n in policy['files'] if n.startswith('evidence/')]
for name in policy['skills']:
    request('tools/call', {'name':'load_skill','arguments':{'name':name}})
skip = mode == 'skip' or (mode == 'retry' and not (Path(policy['audit_path']).parent / 'rejected-attempt').exists())
if not skip:
    for name in policy['files']:
        if name.startswith('evidence/'):
            request('tools/call', {'name':'read_file','arguments':{'path':name}})
if mode == 'denied':
    result = request('tools/call', {'name':'read_file','arguments':{'path':'/etc/passwd'}})
    assert result['isError']
process.stdin.close()
process.wait(timeout=10)
assert process.returncode == 0
event = {'type':'result','subtype':'success','is_error':mode == 'error',
         'result':response if isinstance(response, str) else json.dumps(response),
         'usage':{'cache_creation':{'ephemeral_1h_input_tokens':100, 'ephemeral_5m_input_tokens':0}}}
if schema is not None and mode != 'unstructured':
    from daq_agent.model_json import load_model_json
    event['structured_output'] = load_model_json(response) if isinstance(response, str) else response
    event['result'] = 'Synthetic unstructured text must not be used as the report.'
if mode == 'schema_error':
    event.update(is_error=True, subtype='error_max_structured_output_retries')
print(json.dumps(event))
''')
    executable.chmod(0o700)
    return str(executable)


def fake_claude_env(root):
    auth = root / 'claude-auth'
    auth.mkdir(exist_ok=True)
    (auth / 'settings.json').write_text(json.dumps({'env': {
        'ANTHROPIC_AUTH_TOKEN': 'SYNTHETIC_KEY', 'ANTHROPIC_BASE_URL': 'https://example.invalid',
        'ANTHROPIC_DEFAULT_SONNET_MODEL': 'synthetic-sonnet'}}))
    return {'CLAUDE_CONFIG_DIR': str(auth), 'ANTHROPIC_AUTH_TOKEN': 'SYNTHETIC_KEY',
            'ANTHROPIC_DEFAULT_SONNET_MODEL': 'synthetic-sonnet',
            'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}
