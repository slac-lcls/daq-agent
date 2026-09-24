"""Private, hutch-scoped notes with historical report and conversation provenance."""

from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import re
import tempfile
from uuid import uuid4

from .chat_answers import terminal_text
from .report_context import tokens

MAX_NOTE_BYTES = 256 * 1024
MAX_TEXT_BYTES = 64 * 1024
MAX_NOTES = 2000
MAX_SEARCH_BYTES = 16 * 1024 * 1024
MAX_CONTEXT_BYTES = 12 * 1024
NOTE_ID = r'[0-9a-f]{32}'


def parse_request(text):
    """Recognize only direct user requests; never parse model/evidence content."""
    text = text.strip()
    command = re.fullmatch(r'/note(?:\s+(.*))?', text, re.S | re.I)
    if command:
        return 'save', (command[1] or '').strip()
    command = re.fullmatch(r'/notes(?:\s+(.*))?', text, re.S | re.I)
    if command:
        return 'list', (command[1] or '').strip()
    prefix = r'(?:please\s+)?(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?'
    stem = r'(?:(?:save|record|keep)\s+(?:this|that|a|the)\s+note|(?:make|take)\s+a\s+note|(?:save|record|keep)\s+(?:this|that)\s+as\s+(?:a\s+)?note)'
    explicit = re.fullmatch(prefix + stem + r'(?:\s*:\s*|\s+that\s+)(.*)', text, re.I | re.S)
    if explicit:
        return 'save', explicit[1].strip()
    explicit = re.fullmatch(prefix + r'remember\s+(?:this\s*:\s*|that\s+)(.+)', text, re.I | re.S)
    if explicit:
        return 'save', explicit[1].strip()
    previous = r'(?:' + stem + r'|(?:save|record|keep)\s+(?:this|that|the\s+(?:last|previous)|your\s+(?:last|previous))(?:\s+(?:answer|response|finding))?(?:\s+as\s+(?:a\s+)?note)?|remember\s+this)'
    if re.fullmatch(prefix + previous + r'(?:,?\s+please)?[.!?]*', text, re.I):
        return 'save', ''
    return None


def hutch_directory(root, hutch):
    if not isinstance(hutch, str) or not re.fullmatch(r'[a-z]{3}', hutch):
        raise ValueError('notes require a three-letter hutch')
    root = Path(root).expanduser().absolute()
    directory = root / hutch
    if directory.is_symlink():
        raise ValueError('notes hutch directory must not be a symlink')
    return directory


def save_note(root, report, conversation, *, text=None, turn=None):
    """Explicit user wording stays uncited; saved answers retain exact limitations."""
    if text is None:
        if turn is None:
            raise ValueError('no completed answer to save; use /note YOUR TEXT')
        text = turn['response']['answer']
        citations = turn['response']['citations']
        limitations = turn['response']['limitations']
        kind = 'saved_chat_answer'
    else:
        citations, limitations, kind = [], ['User-authored note; not independently verified.'], 'user_note'
    if not isinstance(text, str) or not text.strip() or len(text.encode()) > MAX_TEXT_BYTES:
        raise ValueError('note text must be nonempty and at most 64 KiB')
    hutch = report.manifest['settings']['hutch']
    sources = {s['id']: s for s in report.manifest['sources']}
    evidence = []
    for citation in citations:
        source = sources[citation['source']]
        evidence.append({**citation, 'snapshot': source['snapshot'], 'sha256': source['sha256'], 'lines': source['lines']})
    note = {
        'schema_version': 1, 'id': uuid4().hex, 'hutch': hutch,
        'created_at': datetime.now(timezone.utc).isoformat(), 'saved_by': getpass.getuser(),
        'kind': kind, 'review_status': 'unreviewed', 'text': text,
        'limitations': limitations, 'citations': evidence,
        'origin': {'report': str(report.directory), 'report_fingerprint': conversation['report_fingerprint'],
                   'window': report.manifest['window'], 'conversation_id': conversation['id'],
                   'turn': turn['number'] if turn else None,
                   'answer_model': turn.get('model') if turn and kind == 'saved_chat_answer' else None,
                   'turn_relation': 'saved_answer' if kind == 'saved_chat_answer' else 'conversation_context_only'},
    }
    encoded = (json.dumps(note, ensure_ascii=False, indent=2) + '\n').encode()
    if len(encoded) > MAX_NOTE_BYTES:
        raise ValueError('note exceeds the storage budget')
    directory = hutch_directory(root, hutch)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = directory / f"{note['id']}.json"
    fd, temporary = tempfile.mkstemp(prefix='.note-', dir=directory)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        # Publish a complete record without overwriting a prior note.
        os.link(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return target, note


def read_note(root, hutch, note_id):
    if not re.fullmatch(NOTE_ID, note_id):
        raise ValueError('invalid note ID')
    path = hutch_directory(root, hutch) / f'{note_id}.json'
    if path.is_symlink() or not path.is_file():
        raise ValueError('note is missing or is not a regular file')
    with path.open('rb') as stream:
        raw = stream.read(MAX_NOTE_BYTES + 1)
    if len(raw) > MAX_NOTE_BYTES:
        raise ValueError('note exceeds the storage budget')
    try:
        note = json.loads(raw)
        if (note['schema_version'] != 1 or note['id'] != note_id or note['hutch'] != hutch
                or note['kind'] not in {'user_note', 'saved_chat_answer'} or note['review_status'] != 'unreviewed'):
            raise ValueError('unsupported note metadata')
        if not isinstance(note['text'], str) or not note['text'].strip() or len(note['text'].encode()) > MAX_TEXT_BYTES:
            raise ValueError('invalid note text')
        if datetime.fromisoformat(note['created_at']).utcoffset() is None:
            raise ValueError('note timestamp requires a timezone')
        if not isinstance(note['saved_by'], str) or not note['saved_by']:
            raise ValueError('invalid note author')
        origin = note['origin']
        if (not isinstance(origin['report'], str) or not Path(origin['report']).is_absolute()
                or not re.fullmatch(r'[0-9a-f]{64}', origin['report_fingerprint'])
                or not re.fullmatch(NOTE_ID, origin['conversation_id'])
                or (origin['turn'] is not None and (type(origin['turn']) is not int or not 1 <= origin['turn'] <= 1000))
                or origin['turn_relation'] not in {'saved_answer', 'conversation_context_only'}):
            raise ValueError('invalid note provenance')
        for key in ('start_inclusive', 'end_exclusive'):
            if datetime.fromisoformat(origin['window'][key]).utcoffset() is None:
                raise ValueError('invalid note window')
        if (not isinstance(note['limitations'], list) or not 1 <= len(note['limitations']) <= 20
                or any(not isinstance(s, str) or not s.strip() or len(s) > 2000 for s in note['limitations'])):
            raise ValueError('invalid note limitations')
        if not isinstance(note['citations'], list) or len(note['citations']) > 20:
            raise ValueError('invalid note citations')
        for citation in note['citations']:
            if (not re.fullmatch(r'log-[1-9][0-9]{0,2}', citation['source'])
                    or citation['snapshot'] != f"evidence/{citation['source']}.txt"
                    or not re.fullmatch(r'[0-9a-f]{64}', citation['sha256'])
                    or any(type(citation[k]) is not int for k in ('line_start', 'line_end', 'lines'))
                    or not 1 <= citation['line_start'] <= citation['line_end'] <= citation['lines']):
                raise ValueError('invalid note citation')
        if note['kind'] == 'user_note' and note['citations']:
            raise ValueError('user notes cannot inherit answer citations')
        return note
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('invalid note record') from error


def list_notes(root, hutch, query=''):
    directory = hutch_directory(root, hutch)
    if not directory.exists():
        return [], 0
    notes, invalid, seen, scanned_bytes = [], 0, 0, 0
    words = tokens(query)
    for path in directory.iterdir():
        seen += 1
        if seen > MAX_NOTES:
            raise ValueError('notes directory exceeds 2000 entries; archive older notes before searching')
        if not re.fullmatch(NOTE_ID + r'\.json', path.name):
            continue
        if not path.is_symlink() and path.is_file():
            scanned_bytes += min(path.stat().st_size, MAX_NOTE_BYTES + 1)
            if scanned_bytes > MAX_SEARCH_BYTES:
                raise ValueError('notes search exceeds 16 MiB; archive older notes or read an explicit note ID')
        try:
            note = read_note(root, hutch, path.stem)
        except (OSError, ValueError):
            invalid += 1
            continue
        score = len(words & tokens(note['text']))
        if not query or score or note['id'] in query.lower():
            notes.append((score, note['created_at'], note['id'], note))
    notes.sort(reverse=True, key=lambda item: item[:3])
    return [n[-1] for n in notes], invalid


def select_notes(root, report, question, report_fingerprint=None):
    matches, invalid = list_notes(root, report.manifest['settings']['hutch'], question)
    selected = []
    for note in matches[:3]:
        # Old source IDs are deliberately omitted: they are not current-report citations.
        item = {k: note[k] for k in ('id', 'hutch', 'created_at', 'kind', 'review_status')}
        item.update(text_excerpt=note['text'][:1800], limitations_excerpt=[s[:400] for s in note['limitations'][:3]],
                    origin_report=Path(note['origin']['report']).name, origin_window=note['origin']['window'],
                    same_report=(note['origin']['report'] == str(report.directory) and note['origin']['report_fingerprint'] == report_fingerprint),
                    truncated=len(note['text']) > 1800 or len(note['limitations']) > 3 or any(len(s) > 400 for s in note['limitations'][:3]))
        if len(json.dumps([*selected, item]).encode()) > MAX_CONTEXT_BYTES:
            continue
        selected.append(item)
    return {'items': selected, 'matched': len(matches), 'invalid_skipped': invalid,
            'coverage': 'bounded lexical matches in this hutch; historical unreviewed notes, not current evidence'}


def render_note(note):
    origin = note['origin']
    lines = [f"Note {note['id']} ({note['hutch']}, {note['review_status']}, {note['kind']})",
             f"Saved: {note['created_at']} by {note['saved_by']}", note['text'],
             'Limitations: ' + ' '.join(note['limitations']), f"Report: {origin['report']}",
             f"Window: {origin['window']['start_inclusive']} to {origin['window']['end_exclusive']}",
             f"Conversation: {origin['conversation_id']}; turn: {origin['turn']} ({origin['turn_relation']})"]
    for cite in note['citations']:
        lines.append(f"[{cite['source']}:{cite['line_start']}-{cite['line_end']}] {Path(origin['report']) / cite['snapshot']}")
    if note['citations']:
        lines.append('Citations belong to the originating report; evidence availability has not been rechecked.')
    return terminal_text('\n'.join(lines))
