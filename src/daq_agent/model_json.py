"""Parse model JSON with a narrow, content-preserving whitespace correction."""

import json


def load_model_json(text):
    text = text.strip()
    if text.startswith('```json\n') and text.endswith('```'):
        text = text[8:-3].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        if not error.msg.startswith('Invalid control character'):
            raise
    # Models occasionally emit literal whitespace inside a quoted string. Escape
    # only LF/CR/TAB, preserving their decoded values. Do not repair punctuation,
    # quotes, invalid escapes, truncation, or other control characters.
    escaped, quoted = False, False
    normalized = []
    whitespace = {'\n': '\\n', '\r': '\\r', '\t': '\\t'}
    for char in text:
        if quoted and not escaped and char in whitespace:
            normalized.append(whitespace[char])
            continue
        normalized.append(char)
        if escaped:
            escaped = False
        elif quoted and char == '\\':
            escaped = True
        elif char == '"':
            quoted = not quoted
    return json.loads(''.join(normalized))
