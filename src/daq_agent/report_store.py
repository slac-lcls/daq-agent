"""Shared completed-report selection and artifact integrity validation."""

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

from .batches import MAX_BATCHES, MAX_REPORT_FILES, MAX_REPORT_BYTES, MAX_FINDINGS_BYTES
from .collectors.logs import MAX_FILE_BYTES, MAX_TOTAL_BYTES
from .reports import validate_findings


@dataclass
class Report:
    directory: Path
    manifest: dict
    findings: dict
    evidence: dict[str, str]
    raw_evidence: dict[str, bytes]


def read_artifact(directory: Path, name: str, limit: int) -> bytes:
    path = directory / name
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(directory) or not resolved.is_file():
        raise ValueError(f"artifact is not a file within the run directory: {name}")
    with resolved.open("rb") as stream:
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise ValueError(f"artifact is too large: {name}")
    return content


def read_manifest(directory: Path) -> dict:
    raw = read_artifact(directory, "manifest.json", 1024 * 1024)
    manifest = json.loads(raw)
    if not isinstance(manifest, dict) or manifest.get("status") != "completed":
        raise ValueError("run is not a completed report")
    version = manifest.get("schema_version")
    if manifest.get("workflow") not in {"analyze-logs", "report"} or type(version) is not int or version not in {1, 2}:
        raise ValueError("unsupported report workflow or schema")
    if version == 1 and len(raw) > 128 * 1024:
        raise ValueError("report manifest is too large")
    if version == 2:
        batches = manifest.get("batches")
        if (manifest.get("workflow") != "report" or manifest.get("aggregation") != "independent-batches"
                or not isinstance(batches, list) or not 2 <= len(batches) <= MAX_BATCHES
                or any(not isinstance(batch, dict) or batch.get("status") != "completed" for batch in batches)):
            raise ValueError("invalid or incomplete combined report")
    return manifest


def report_time(manifest: dict) -> datetime:
    value = manifest.get("completed_at", manifest.get("created_at"))
    if not isinstance(value, str):
        raise ValueError("report must have a timestamp")
    timestamp = datetime.fromisoformat(value)
    if timestamp.utcoffset() is None:
        raise ValueError("report timestamp must include a UTC offset")
    return timestamp


def load_report(directory: Path) -> Report:
    directory = directory.expanduser().resolve(strict=True)
    try:
        manifest = read_manifest(directory)
        report_time(manifest)
        settings = manifest["settings"]
        if not re.fullmatch(r"[a-z]{3}", settings["hutch"]):
            raise ValueError("invalid report hutch")
        partition = settings.get("partition")
        if partition is None:
            if manifest.get("scope") != {"kind": "hutch"}:
                raise ValueError("report without a partition must explicitly declare hutch scope")
        elif type(partition) is not int or not 0 <= partition <= 7:
            raise ValueError("invalid report partition")
        for value in (settings["model"], manifest["created_at"], manifest["evidence_kind"],
                      manifest["window"]["start_inclusive"], manifest["window"]["end_exclusive"]):
            if not isinstance(value, str):
                raise ValueError("invalid report metadata")
        combined = manifest["schema_version"] == 2
        max_files = MAX_REPORT_FILES if combined else 8
        max_bytes = MAX_REPORT_BYTES if combined else MAX_TOTAL_BYTES
        sources = manifest["sources"]
        if not isinstance(sources, list) or not 1 <= len(sources) <= max_files:
            raise ValueError(f"report must contain 1–{max_files} sources")
        raw, evidence, total = {}, {}, 0
        for source in sources:
            source_id = source["id"]
            if (not isinstance(source_id, str) or not re.fullmatch(r"log-[1-9][0-9]{0,2}", source_id)
                    or int(source_id[4:]) > max_files or source_id in evidence):
                raise ValueError("invalid or duplicate source ID")
            if source["snapshot"] != f"evidence/{source_id}.txt":
                raise ValueError("invalid evidence snapshot path")
            if not isinstance(source["original_path"], str):
                raise ValueError("invalid original source path")
            content = read_artifact(directory, source["snapshot"], MAX_FILE_BYTES)
            total += len(content)
            text = content.decode("utf-8")
            if not text.strip() or "\x00" in text or total > max_bytes:
                raise ValueError("invalid or oversized evidence")
            if (source["sha256"] != hashlib.sha256(content).hexdigest()
                    or type(source["bytes"]) is not int or source["bytes"] != len(content)
                    or type(source["lines"]) is not int or source["lines"] != len(text.splitlines())):
                raise ValueError(f"evidence integrity check failed: {source_id}")
            raw[source_id], evidence[source_id] = content, text
        findings = validate_findings(read_artifact(directory, "findings.json",
                                                  MAX_FINDINGS_BYTES if combined else 3 * 1024 * 1024).decode(),
                                     sources, combined=combined)
        return Report(directory, manifest, findings, evidence, raw)
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError(f"invalid report metadata in {directory}") from error


def latest_report(root: Path, hutch: str | None = None) -> Report:
    root = root.expanduser().resolve()
    if hutch is not None and not re.fullmatch(r"[a-z]{3}", hutch):
        raise ValueError("hutch must be a lowercase three-letter code")
    candidates = []
    # Batch partition runs, current hutch/year/month/run, and earlier year/month/run.
    for pattern in ("*/*/*/*/*/manifest.json", "*/*/*/*/manifest.json", "*/*/*/manifest.json"):
        for path in root.glob(pattern):
            try:
                directory = path.parent.resolve(strict=True)
                if not directory.is_relative_to(root):
                    continue
                manifest = read_manifest(directory)
                if manifest.get("batch_context") is not None:
                    continue
                if hutch is None or manifest.get("settings", {}).get("hutch") == hutch:
                    candidates.append((report_time(manifest), str(directory), directory))
            except (OSError, ValueError, TypeError, AttributeError):
                continue
    for _, _, directory in sorted(candidates, reverse=True):
        try:
            return load_report(directory)
        except (OSError, ValueError):
            continue
    raise ValueError(f"no valid completed reports found under {root}; run report first "
                     "or supply an explicit run directory")
