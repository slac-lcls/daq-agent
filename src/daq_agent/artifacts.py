"""Private text and JSON artifacts shared by collectors and analysis."""

import json
from pathlib import Path


def write_private(path: Path, text: str) -> None:
    path.write_text(text)
    path.chmod(0o600)


def write_json(path: Path, value: dict) -> None:
    write_private(path, json.dumps(value, indent=2) + "\n")
