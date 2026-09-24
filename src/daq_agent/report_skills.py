"""Verify the diagnostic skills retained with a completed report, without fetching."""

import hashlib
import json

from .report_store import load_report, read_artifact
from .skill_sources import MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES, parse_source, validate_skill, valid_snapshot_path


def retained_skills(report):
    try:
        return _retained_skills(report)
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('invalid or missing retained diagnostic skills') from error


def _retained_skills(report):
    manifests = [(report.directory, report.manifest)]
    if report.manifest['schema_version'] == 2:
        manifests = []
        parent = {s['id']: s for s in report.manifest['sources']}
        assigned = set()
        for number, batch in enumerate(report.manifest['batches'], 1):
            if batch.get('number') != number or batch.get('directory') != f'batches/{number:03}':
                raise ValueError('invalid batch identity in report')
            child_path = (report.directory / batch['directory']).resolve(strict=True)
            if not child_path.is_relative_to(report.directory):
                raise ValueError('batch is outside the report')
            child = load_report(child_path)
            if child.manifest['window'] != report.manifest['window'] or child.manifest['settings']['hutch'] != report.manifest['settings']['hutch']:
                raise ValueError('batch scope differs from report')
            ids = batch.get('source_ids')
            if not isinstance(ids, list) or len(ids) != len(child.manifest['sources']):
                raise ValueError('invalid batch source mapping')
            for source, source_id in zip(child.manifest['sources'], ids):
                if source_id not in parent or any(source[k] != parent[source_id][k] for k in ('bytes', 'sha256', 'lines')):
                    raise ValueError('batch evidence differs from report')
            assigned.update(ids)
            manifests.append((child.directory, child.manifest))
        if assigned != set(parent):
            raise ValueError('batch mapping omits report evidence')
    expected, contents, identities = None, {}, []
    try:
        for directory, manifest in manifests:
            metadata = manifest.get('upstream_skills')
            if not isinstance(metadata, dict):
                raise ValueError('report has no retained skill provenance; generate a new report')
            status = metadata.get('status')
            if status in {'not_configured', 'disabled_by_request'}:
                if manifest.get('required_upstream_skills', []):
                    raise ValueError('required report skills were not retained')
                descriptor = {'status': status, 'skills': []}
                current = {}
            elif status == 'loaded_from_cache':
                source = parse_source(metadata['source'])
                if 'report-chat' in source.skills or manifest.get('required_upstream_skills') != list(source.skills):
                    raise ValueError('invalid retained skill selection')
                records = metadata['files']
                if metadata.get('schema_version') != 1 or not isinstance(records, dict) or not 1 <= len(records) <= MAX_FILES:
                    raise ValueError('invalid retained skill inventory')
                current, total = {}, 0
                for name, record in records.items():
                    if not isinstance(name, str) or not valid_snapshot_path(name, source.skills):
                        raise ValueError('invalid retained skill path')
                    raw = read_artifact(directory, f'upstream-skills/{name}', MAX_FILE_BYTES)
                    total += len(raw)
                    if total > MAX_TOTAL_BYTES or record != {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}:
                        raise ValueError('retained skill integrity check failed')
                    raw.decode('utf-8')
                    current[name] = raw
                for name in source.skills:
                    validate_skill(name, current[f'{name}/SKILL.md'])
                descriptor = {'status': status, 'source': metadata['source'], 'files': records, 'skills': list(source.skills)}
            else:
                raise ValueError('unsupported retained skill provenance')
            if expected is not None and descriptor != expected:
                raise ValueError('report batches have inconsistent diagnostic skills')
            expected, contents = descriptor, current
            identities.append(hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest())
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('invalid or missing retained diagnostic skills') from error
    return {**expected, 'report_manifest_hashes': identities}, contents
