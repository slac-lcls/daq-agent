"""Application-measured report scope and timing, independent of model prose."""

import math


def statistics_rows(manifest):
    """Older manifests remain readable without inventing missing measurements."""
    stats = manifest.get('generation_statistics', {})
    if not isinstance(stats, dict):
        stats = {}
    elapsed = stats.get('elapsed_seconds')
    if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
        duration = 'Not recorded'
    else:
        seconds = round(elapsed, 1)
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        duration = (f'{int(hours)}h ' if hours else '') + (f'{int(minutes)}m ' if minutes or hours else '') + f'{seconds:.1f}s'
    def count(value, fallback='Not recorded'):
        return str(value) if type(value) is int and value >= 0 else fallback
    supplied = stats.get('input_mode') == 'supplied-excerpts'
    unknown = 'Not determined (supplied excerpts)' if supplied else 'Not recorded'
    rows = [('Generation time', duration),
            ('Raw log files scanned', count(stats.get('raw_log_files_scanned'), unknown)),
            ('Launch groups included', count(stats.get('launch_groups'), unknown))]
    if supplied:
        rows.append(('Supplied log files', count(stats.get('supplied_log_files'))))
    rows += [('Evidence documents', count(stats.get('evidence_documents', len(manifest.get('sources', []))))),
             ('Model sessions completed', count(stats.get('model_sessions_completed'))),
             ('Numbered DAQ runs', 'Not determined')]
    return rows
