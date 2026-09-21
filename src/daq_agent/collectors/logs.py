"""Snapshot explicitly supplied log excerpts without truncating silently."""

import hashlib
from pathlib import Path
import stat

MAX_FILES = 8
MAX_FILE_BYTES = 64 * 1024
MAX_TOTAL_BYTES = 256 * 1024


def snapshot_logs(paths: list[Path], destination: Path, *, max_files: int = MAX_FILES,
                  max_total_bytes: int = MAX_TOTAL_BYTES) -> list[dict]:
    if not 1 <= len(paths) <= max_files:
        raise ValueError(f"supply between 1 and {max_files} log excerpts")
    records = []
    total = 0
    seen = set()
    # Validate all inputs before creating snapshots.
    for index, path in enumerate(paths, 1):
        path = path.resolve(strict=True)
        if path in seen:
            raise ValueError("the same log file was supplied more than once")
        seen.add(path)
        if not stat.S_ISREG(path.stat().st_mode):
            raise ValueError("log inputs must be regular files")
        with path.open("rb") as stream:
            content = stream.read(MAX_FILE_BYTES + 1)
        total += len(content)
        if len(content) > MAX_FILE_BYTES or total > max_total_bytes:
            raise ValueError(f"log excerpts exceed 64 KiB/file or {max_total_bytes // 1024} KiB total")
        text = content.decode("utf-8")
        if not text.strip() or "\x00" in text:
            raise ValueError("log inputs must be nonempty UTF-8 text")
        records.append(({
            "id": f"log-{index}",
            "original_path": str(path),
            "snapshot": f"evidence/log-{index}.txt",
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
            "lines": len(text.splitlines()),
        }, content))
    destination.mkdir(mode=0o700)
    for record, content in records:
        target = destination / Path(record["snapshot"]).name
        target.write_bytes(content)
        target.chmod(0o600)
    return [record for record, _ in records]
