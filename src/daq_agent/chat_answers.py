"""Validate and render conversational answers with report snapshot citations."""

import json


def validate_answer(text, sources):
    if len(text.encode()) > 64 * 1024:
        raise ValueError('chat answer exceeds 64 KiB')
    text = text.strip()
    if text.startswith('```json\n') and text.endswith('```'):
        text = text[8:-3].strip()
    result = json.loads(text)
    if not isinstance(result, dict) or set(result) != {'answer', 'citations', 'limitations'}:
        raise ValueError('chat response requires answer, citations and limitations')
    if not isinstance(result['answer'], str) or not result['answer'].strip() or len(result['answer']) > 16000:
        raise ValueError('invalid chat answer text')
    limitations = result['limitations']
    if not isinstance(limitations, list) or not 1 <= len(limitations) <= 20 or any(not isinstance(s, str) or not s.strip() or len(s) > 2000 for s in limitations):
        raise ValueError('chat response must state bounded limitations')
    citations = result['citations']
    if not isinstance(citations, list) or len(citations) > 20:
        raise ValueError('invalid chat citations')
    counts = {s['id']: s['lines'] for s in sources}
    for cite in citations:
        if not isinstance(cite, dict) or set(cite) != {'source', 'line_start', 'line_end'}:
            raise ValueError('invalid chat citation fields')
        source, start, end = cite['source'], cite['line_start'], cite['line_end']
        if not isinstance(source, str) or source not in counts:
            raise ValueError('citation references evidence not supplied to this turn')
        if type(start) is not int or type(end) is not int or not 1 <= start <= end <= counts[source]:
            raise ValueError('citation line range is outside the supplied snapshot')
    return result


def terminal_text(text):
    # Avoid interpreting control/escape sequences from logs or generated prose.
    return ''.join(c for c in str(text) if c in '\n\t' or (ord(c) >= 32 and not 127 <= ord(c) <= 159))


def render_answer(result, report):
    lines = [result['answer']]
    for cite in result['citations']:
        path = report.directory / f"evidence/{cite['source']}.txt"
        lines.append(f"[{cite['source']}:{cite['line_start']}-{cite['line_end']}] {path}")
    lines.append('Limitations: ' + ' '.join(result['limitations']))
    return terminal_text('\n'.join(lines))
