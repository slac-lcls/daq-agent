"""Deterministic, versioned known-condition rules applied before model input."""

from collections import Counter
import hashlib
from pathlib import Path
import re
from zoneinfo import ZoneInfo

RULE_VERSION = 1
RULES = {
    'daq-teardown-double-free': {
        'title': 'Known double-free during DAQ teardown',
        'reason': 'User-maintained known Python/C++ teardown issue; deferred from model analysis.',
        'criteria': 'Double-free signature on or within five lines after an explicit TERM/INT shutdown or Slurm signal cancellation.',
        'recovery': 'Shutdown context established; this is not evidence of healthy operation.'},
    'pyxpm-connection-reset': {
        'title': 'Known pyXPM pvxs connection reset',
        'reason': 'User-maintained known pyXPM connection-reset signature; counted without model analysis.',
        'criteria': 'pyxpm component; pvxs.tcp.io socket error 104 and Connection reset by peer.',
        'recovery': 'Recovery is not established by this message; classified as known/deferred, not recovered.'},
    'ami-recovered-connection': {
        'title': 'Recovered AMI monitor connection failure',
        'reason': 'User-maintained transient AMI connection issue with an explicit connection-success message.',
        'criteria': 'AMI myTrFd socket connection-refused retry followed within twenty lines by Connected to XtcMonitor server.',
        'recovery': 'Transport connection recovery observed; restored data flow is not established.'},
}
SHUTDOWN = re.compile(r'Shutting down on (?:TERM|INT) signal|CANCELLED.*DUE TO SIGNAL (?:Terminated|Interrupt)', re.I)
MEMORY = re.compile(r'(?:free\(\):\s*double free detected in tcache\s+\d+|double free or corruption(?:\s*\([^\r\n)]*\))?)\s*$', re.I)
RESET = re.compile(r'pvxs\.tcp\.io.*closed with socket error 104\s*:\s*Connection reset by peer\s*$', re.I)
AMI_ERROR = re.compile(r'Error connecting myTrFd socket \(will retry\): Connection refused\s*$', re.I)
AMI_CONNECTED = re.compile(r'\bConnected to XtcMonitor server\b', re.I)


def validate_rules(value):
    if (not isinstance(value, (list, tuple)) or any(not isinstance(v, str) or v not in RULES for v in value)
            or len(set(value)) != len(value)):
        raise ValueError('known_conditions must be a unique list of supported rule IDs: ' + ', '.join(RULES))
    return tuple(value)


def classify_lines(lines, component, enabled):
    """Return exact matched lines and the evidence supporting each classification."""
    enabled = set(enabled)
    if not enabled:
        return {}
    pyxpm = re.fullmatch(r'pyxpm(?:[-_][\w-]+)?', component, re.I) is not None
    ami = re.fullmatch(r'ami(?:[-_][\w-]+)?', component, re.I) is not None
    matches = {}
    last_shutdown = -100
    for i, line in enumerate(lines):
        if SHUTDOWN.search(line):
            last_shutdown = i
        if ('daq-teardown-double-free' in enabled and i - last_shutdown <= 5 and MEMORY.search(line)
                and not re.search(r'Segmentation fault|\bFATAL\b|out of memory', line, re.I)):
            matches[i] = ('daq-teardown-double-free', sorted({last_shutdown, i}))
        elif pyxpm and 'pyxpm-connection-reset' in enabled and RESET.search(line):
            matches[i] = ('pyxpm-connection-reset', [i])
        elif ami and 'ami-recovered-connection' in enabled and AMI_ERROR.search(line):
            for j in range(i + 1, min(len(lines), i + 21)):
                if AMI_ERROR.search(lines[j]) or SHUTDOWN.search(lines[j]):
                    break
                if AMI_CONNECTED.search(lines[j]):
                    matches[i] = ('ami-recovered-connection', [i, j])
                    break
    return matches


def component_id(path, headers):
    return headers.get('ID') or path.stem.rsplit(':', 1)[-1]


class KnownConditions:
    """Bounded report summaries; collection records retain per-file counts."""
    def __init__(self, enabled, start, end, zone):
        self.enabled = validate_rules(enabled)
        self.start, self.end, self.zone = start, end, zone
        self.counts = {r: Counter() for r in self.enabled}
        self.files = {r: set() for r in self.enabled}
        self.launches = {r: set() for r in self.enabled}
        self.examples = {r: [] for r in self.enabled}

    def record(self, lines, path, headers, launch, sha256):
        from .collectors.session_logs import safe, time_bucket
        matches = classify_lines(lines, component_id(path, headers), self.enabled)
        counts = Counter()
        for index, (rule, support) in matches.items():
            bucket = time_bucket(lines[index], self.start, self.end, self.zone)
            self.counts[rule][bucket] += 1
            self.files[rule].add(str(path))
            self.launches[rule].add(launch)
            counts[f'{rule}|{bucket}'] += 1
            if len(self.examples[rule]) < 4:
                self.examples[rule].append({
                    'path': str(path), 'line': index + 1, 'launch': launch, 'time_bucket': bucket,
                    'component': component_id(path, headers), 'partition': headers.get('PLATFORM'),
                    'release': headers.get('TESTRELDIR'), 'sha256': sha256,
                    'context': [{'line': j + 1, 'text': safe(lines[j])} for j in support]})
        return matches, dict(counts)

    def summary(self):
        return {'schema_version': 1, 'rule_version': RULE_VERSION, 'enabled_rules': list(self.enabled),
                'matching_lines': sum(sum(c.values()) for c in self.counts.values()),
                'count_semantics': 'Matching lines, not independent incidents. Outside-window and untimed matches retain their time buckets.',
                'items': [{'id': rule, **RULES[rule], 'matching_lines': sum(self.counts[rule].values()),
                           'time_buckets': dict(self.counts[rule]), 'affected_files': len(self.files[rule]),
                           'launch_groups': len(self.launches[rule]), 'examples': self.examples[rule]}
                          for rule in self.enabled if self.counts[rule]]}


def filter_supplied(logs, target, settings, start, end):
    """Filter supplied excerpts while retaining original path/hash/line identity."""
    from .artifacts import write_json, write_private
    from .collectors.logs import snapshot_logs
    from .collectors.session_logs import safe
    from .batches import MAX_REPORT_FILES, MAX_REPORT_BYTES
    target.mkdir(mode=0o700)
    records = snapshot_logs(logs, target / 'originals', max_files=MAX_REPORT_FILES, max_total_bytes=MAX_REPORT_BYTES)
    known = KnownConditions(settings.known_conditions, start, end, ZoneInfo(settings.timezone))
    filtered, origins, inputs = [], {}, []
    remaining = 0
    for record in records:
        original = Path(record['original_path'])
        lines = (target / record['snapshot'].replace('evidence/', 'originals/')).read_text().splitlines()
        headers = {}
        for line in lines[:40]:
            match = re.match(r'#\s*(PLATFORM|HOST|ID|SLURM_JOB_ID|TESTRELDIR|GIT_DESCRIBE):\s*(.*)', line)
            if match:
                headers[match[1]] = safe(match[2])
        # Supplied excerpts may lack launch identity; do not infer a launch from a temporary name.
        excluded, counts = known.record(lines, original, headers, 'unknown (supplied excerpt)', record['sha256'])
        support = {i for _, indexes in excluded.values() for i in indexes}
        remaining += sum(1 for i, line in enumerate(lines) if i not in support
                         and line.strip() and not line.startswith('#'))
        text = '\n'.join('[omitted]' if i in excluded else line for i, line in enumerate(lines)) + '\n'
        path = target / (record['id'] + '.log')
        write_private(path, text)
        filtered.append(path)
        origins[str(path)] = str(original)
        inputs.append({**record, 'headers': headers, 'known_conditions': counts,
                       'filtered_sha256': hashlib.sha256(text.encode()).hexdigest()})
    write_json(target / 'known-condition-inputs.json', {'files': inputs, 'known_conditions': known.summary()})
    return filtered, origins, known.summary(), remaining


def sections(manifest):
    """Plain text for both report renderers, kept separate from model findings."""
    known = manifest.get('known_conditions', {})
    result = []
    for item in known.get('items', []):
        text = [item['reason'], item['recovery'],
                f"Matching lines: {item['matching_lines']}; affected files: {item['affected_files']}; launch groups: {item['launch_groups']}.",
                'Time buckets: ' + ', '.join(f'{key}={value}' for key, value in item['time_buckets'].items()),
                f"Rule: {item['id']} (version {known['rule_version']}). {item['criteria']}"]
        for example in item['examples']:
            text += [f"Source: {example['path']}, original line {example['line']} ({example['time_bucket']})",
                     f"Launch: {example['launch']}; component: {example['component']}; platform: {example['partition']}; release: {example['release']}",
                     f"Captured prefix SHA-256: {example['sha256']}"]
            text += [f"original-line={line['line']}: {line['text']}" for line in example['context']]
        result.append((item['title'], '\n'.join(text)))
    return result
