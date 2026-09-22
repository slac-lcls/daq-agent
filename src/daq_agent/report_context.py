"""Bounded deterministic retrieval over saved report findings and snapshots."""

import json
import re

from .collectors.logs import MAX_FILES, MAX_TOTAL_BYTES

MAX_QUESTION_BYTES = 8192
MAX_CONTEXT_BYTES = 48 * 1024
MAX_HISTORY_BYTES = 16 * 1024
STOP_WORDS = set('a an and are as at be by can could do does explain for from how i in is it me of on or please report show that the these this to was were what when which why with would you'.split())


def tokens(text):
    return set(re.findall(r'[a-z0-9_:-]{2,}', text.lower())) - STOP_WORDS


def recent_history(turns):
    history, total = [], 0
    for turn in reversed(turns):
        entry = {'question': turn['question'], 'answer': turn['response'], 'finding_ids': turn['finding_ids']}
        size = len(json.dumps(entry).encode())
        if len(history) == 6 or total + size > MAX_HISTORY_BYTES:
            break
        history.insert(0, entry)
        total += size
    return history, len(turns) - len(history)


def select_context(report, question, history=()):
    if not isinstance(question, str) or not question.strip() or len(question.encode()) > MAX_QUESTION_BYTES:
        raise ValueError('question must be nonempty and at most 8 KiB')
    findings = report.findings['findings']
    explicit = {int(n) for n in re.findall(r'\bF0*(\d+)\b', question, re.I)}
    for match in re.finditer(r'\bfindings?\s+#?([0-9]+(?:\s*(?:,|and|&)\s*#?[0-9]+)*)', question, re.I):
        explicit.update(int(n) for n in re.findall(r'\d+', match[1]))
    if any(not 1 <= n <= len(findings) for n in explicit):
        raise ValueError('unknown finding reference; use /findings to list valid IDs')
    requested_sources = set(re.findall(r'\blog-[0-9]+\b', question.lower()))
    if requested_sources - report.evidence.keys():
        raise ValueError('unknown source reference; use /sources to list valid IDs')
    # Carry the prior topic for short follow-ups, but explicit references start a new selection.
    query = question
    if history and not explicit and not requested_sources:
        query += ' ' + history[-1]['question']
        explicit = {int(ref[1:]) for ref in history[-1]['finding_ids']}
    words = tokens(query)
    ranked = sorted(range(1, len(findings) + 1),
                    key=lambda n: (-len(words & tokens(json.dumps(findings[n-1]))), n))
    chosen = sorted(explicit)
    for n in ranked:
        if len(chosen) >= 6:
            break
        if n not in chosen and (not words or words & tokens(json.dumps(findings[n-1]))):
            chosen.append(n)
    if not chosen and not requested_sources:
        chosen = ranked[:3]
    required = set(requested_sources)
    for n in explicit:
        required.update(c['source'] for c in findings[n-1]['evidence'])
    # The collector's scope document carries counts once, across all analysis batches.
    scope = 'log-1' if report.manifest.get('collection') and 'log-1' in report.evidence else None
    priorities = ([scope] if scope else []) + sorted(required, key=lambda s: int(s[4:]))
    for n in chosen:
        priorities.extend(c['source'] for c in findings[n-1]['evidence'])
    ranked_sources = sorted(report.evidence, key=lambda s: (-len(words & tokens(report.evidence[s])), int(s[4:])))
    priorities.extend(s for s in ranked_sources if words & tokens(report.evidence[s]))
    priorities = list(dict.fromkeys(priorities))
    selected, size = [], 0
    for source in priorities:
        count = len(report.raw_evidence[source])
        if len(selected) >= MAX_FILES or size + count > MAX_TOTAL_BYTES:
            if source in required or source == scope:
                raise ValueError('referenced evidence exceeds one chat turn; ask about fewer findings or sources')
            continue
        selected.append(source)
        size += count
    if required - set(selected):
        raise ValueError('referenced evidence exceeds one chat turn; narrow the question')
    cards = [{'id': f'F{n:03}', **findings[n-1]} for n in chosen
             if all(c['source'] in selected for c in findings[n-1]['evidence'])]
    context = {
        'hutch': report.manifest['settings']['hutch'], 'window': report.manifest['window'],
        'summary_excerpt': report.findings['summary'][:8000],
        'report_limitations': [s[:2000] for s in report.findings['limitations'][:8]],
        'findings': cards,
        'coverage': {'total_findings': len(findings), 'selected_findings': len(cards),
                     'total_sources': len(report.evidence), 'selected_sources': len(selected),
                     'summary_truncated': len(report.findings['summary']) > 8000,
                     'limitations_truncated': len(report.findings['limitations']) > 8 or any(len(s) > 2000 for s in report.findings['limitations'][:8]),
                     'retrieval': 'explicit references and lexical matching; selection is not exhaustive',
                     'count_semantics': 'shared scope counts are supplied once; matching lines are not incidents'},
        'sources': [s for s in report.manifest['sources'] if s['id'] in selected],
    }
    # Do not place original filesystem paths or provider settings in model context.
    context['sources'] = [{k: s[k] for k in ('id', 'snapshot', 'lines')} for s in context['sources']]
    if len(json.dumps(context).encode()) > MAX_CONTEXT_BYTES:
        raise ValueError('selected findings exceed the chat context budget; ask about fewer findings')
    return context, {s: report.raw_evidence[s] for s in selected}
