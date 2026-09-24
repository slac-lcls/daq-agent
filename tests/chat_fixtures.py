"""Synthetic saved reports and fake runtime for chat regression tests."""
import hashlib
import json
from pathlib import Path


def write_report(root, name='report', count=2, upstream=False, day=21):
    directory = root / 'tmo/2026/09' / name
    (directory / 'evidence').mkdir(parents=True)
    sources, findings = [], []
    for i in range(1, count + 1):
        raw = f'SYNTHETIC launch {i}\nERROR issue_{i} in component_{i}\ncontext for launch {i}\n'.encode()
        (directory / f'evidence/log-{i}.txt').write_bytes(raw)
        sources.append({'id': f'log-{i}', 'snapshot': f'evidence/log-{i}.txt', 'original_path': f'/synthetic/launch-{i}.log',
                        'lines': 3, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
        findings.append({'title': f'Issue {i}', 'observation': f'issue_{i} in component_{i}', 'hypothesis': 'Unknown.',
                         'next_check': 'Inspect additional evidence.', 'evidence': [{'source': f'log-{i}', 'line_start': 2, 'line_end': 2}]})
    manifest = {'schema_version': 1, 'workflow': 'report', 'scope': {'kind': 'hutch'}, 'status': 'completed',
                'created_at': f'2026-09-{day:02}T12:00:00+00:00', 'evidence_kind': 'synthetic',
                'settings': {'hutch': 'tmo', 'model': 'example/test'},
                'window': {'start_inclusive': '2026-09-19T00:00:00+00:00', 'end_exclusive': '2026-09-21T00:00:00+00:00'},
                'sources': sources, 'upstream_skills': {'status': 'disabled_by_request'}, 'required_upstream_skills': []}
    if upstream:
        records = {}
        for skill in ('psana-daq', 'psana-daq-logs'):
            path = directory / f'upstream-skills/{skill}/SKILL.md'
            path.parent.mkdir(parents=True)
            raw = f'---\nname: {skill}\ndescription: Synthetic diagnostic guidance\n---\nRetained version one.\n'.encode()
            path.write_bytes(raw)
            records[f'{skill}/SKILL.md'] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        source = {'repository': 'https://example.invalid/org/repo', 'branch': 'dev', 'revision': 'a' * 40,
                  'directory': 'skills', 'skills': ['psana-daq', 'psana-daq-logs']}
        manifest['upstream_skills'] = {'status': 'loaded_from_cache', 'schema_version': 1, 'source': source, 'files': records}
        manifest['required_upstream_skills'] = source['skills']
    if count > 8:
        manifest['schema_version'] = 2
        manifest['aggregation'] = 'independent-batches'
        manifest['batches'] = []
        for batch_number, offset in enumerate(range(0, count, 8), 1):
            subset = sources[offset:offset+8]
            child = write_report(directory / '_staging', name=f'child-{batch_number}', count=len(subset), upstream=upstream)
            target = directory / f'batches/{batch_number:03}'
            target.parent.mkdir(exist_ok=True)
            child.rename(target)
            cm = json.loads((target / 'manifest.json').read_text())
            cm['batch_context'] = {'number': batch_number, 'total': (count+7)//8, 'shared_scope': False}
            for local, original in zip(cm['sources'], subset):
                raw = (directory / original['snapshot']).read_bytes()
                (target / local['snapshot']).write_bytes(raw)
                local.update({k: original[k] for k in ('bytes', 'sha256', 'lines')})
            (target / 'manifest.json').write_text(json.dumps(cm))
            manifest['batches'].append({'number': batch_number, 'directory': f'batches/{batch_number:03}', 'status': 'completed',
                                        'source_ids': [s['id'] for s in subset]})
        import shutil
        shutil.rmtree(directory / '_staging')
    (directory / 'manifest.json').write_text(json.dumps(manifest))
    (directory / 'findings.json').write_text(json.dumps({'summary': 'Synthetic report summary.', 'findings': findings,
                                                     'limitations': ['Synthetic excerpts only.']}))
    return directory


def fake_chat_runtime(root, *, source='log-1', bad_tool=False, skip_skill=False):
    path = root / 'fake-chat-opencode'
    response = {'answer': 'The retained evidence records an error. Its cause remains unknown.',
                'citations': [{'source': source, 'line_start': 2, 'line_end': 2}], 'limitations': ['Synthetic retained evidence only.']}
    path.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
if '--version' in sys.argv:
    print('synthetic-chat-runtime'); sys.exit(0)
prompt = sys.stdin.read()
assert 'report-chat' in prompt
assert sys.argv[sys.argv.index('--agent')+1] == 'daq-report-chat'
config = json.loads((Path(os.environ['OPENCODE_CONFIG_DIR'])/'opencode.json').read_text())
assert config['permission']['*'] == 'deny'
assert config['mcp'] == {} and config['plugin'] == []
def event(tool, args):
    print(json.dumps({'type': 'tool_use', 'part': {'tool': tool, 'state': {'status': 'completed', 'input': args}}}))
''' + ('' if skip_skill else '''for name, rule in config['permission']['skill'].items():
    if rule == 'allow': event('skill', {'name': name})
''') + '''for p in (Path.cwd()/'evidence').glob('*.txt'):
    event('read', {'filePath': str(p)})
''' + ("event('bash', {'command': 'forbidden synthetic command'})\n" if bad_tool else '') +
                    f"print(json.dumps({{'type': 'text', 'part': {{'text': {json.dumps(response)!r}}}}}))\n")
    path.chmod(0o700)
    return path
