"""Bounded model batches combined into one cited hutch-wide report."""

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys

from . import __version__
from .artifacts import write_json, write_private
from .collectors.logs import MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES, snapshot_logs
from .html_reports import write_html_bundle
from .log_analysis import analyze_logs
from .reports import MAX_BATCHES, render_report, validate_findings
from .workflow import plan_report

MAX_REPORT_FILES = MAX_BATCHES * MAX_FILES
MAX_REPORT_BYTES = MAX_BATCHES * MAX_TOTAL_BYTES
MAX_FINDINGS_BYTES = 8 * 1024 * 1024


def plan_batches(logs: list[Path], *, shared_scope=False) -> list[list[int]]:
    """Return source indexes, repeating collected scope in each model batch.

    Every other source appears exactly once. No source is silently truncated or
    omitted when a file/count/overall execution budget is exceeded.
    """
    if not logs or len(logs) > MAX_REPORT_FILES:
        raise ValueError(f"report requires 1–{MAX_REPORT_FILES} evidence documents")
    sizes = [path.stat().st_size for path in logs]
    if any(size > MAX_FILE_BYTES for size in sizes) or sum(sizes) > MAX_REPORT_BYTES:
        raise ValueError("report evidence exceeds 64 KiB/document or 4 MiB total")
    prefix = [0] if shared_scope else []
    batches, current = [], prefix.copy()
    total = sum(sizes[i] for i in current)
    for index in range(1 if shared_scope else 0, len(logs)):
        if len(current) == MAX_FILES or total + sizes[index] > MAX_TOTAL_BYTES:
            if current == prefix:
                raise ValueError("a scope/launch pair exceeds the per-session evidence budget")
            batches.append(current)
            current = prefix.copy()
            total = sum(sizes[i] for i in current)
        current.append(index)
        total += sizes[index]
    if current:
        batches.append(current)
    if len(batches) > MAX_BATCHES:
        raise ValueError(f"report needs more than {MAX_BATCHES} model batches; choose a shorter window")
    return batches


def combine_findings(output: Path, manifest: dict) -> dict:
    """Keep every validated finding and remap local citations to global sources."""
    findings, summaries = [], []
    limitations = [
        "This report combines independent evidence batches. Findings may overlap; "
        "no cross-batch incident deduplication or causal synthesis was performed. "
        "Shared scope counts are counted once, not added across batches."
    ]
    sources = {source["id"]: source for source in manifest["sources"]}
    for batch in manifest["batches"]:
        directory = output / batch["directory"]
        child = json.loads((directory / "manifest.json").read_text())
        if child["status"] != "completed":
            raise ValueError("cannot combine an incomplete batch")
        id_map = {f"log-{i}": source_id for i, source_id in enumerate(batch["source_ids"], 1)}
        if len(child["sources"]) != len(id_map):
            raise ValueError("batch source inventory changed")
        for source in child["sources"]:
            original = sources[id_map[source["id"]]]
            if any(source[key] != original[key] for key in ("sha256", "bytes", "lines")):
                raise ValueError("batch evidence differs from retained report evidence")
        result = validate_findings((directory / "findings.json").read_text(), child["sources"])
        number = batch["number"]
        summaries.append(f"Evidence batch {number}:\n{result['summary']}")
        limitations.extend(f"Batch {number}: {item}" for item in result["limitations"])
        for finding in result["findings"]:
            for citation in finding["evidence"]:
                citation["source"] = id_map[citation["source"]]
            findings.append(finding)
    result = {
        "summary": f"Combined hutch report from {len(manifest['batches'])} evidence batches.\n\n" + "\n\n".join(summaries),
        "findings": findings, "limitations": limitations,
    }
    encoded = json.dumps(result)
    if len(encoded.encode()) > MAX_FINDINGS_BYTES:
        raise ValueError("combined findings exceed the report output budget")
    return validate_findings(encoded, manifest["sources"], combined=True)


def analyze_batches(settings, start, end, logs, output, provider, executable, timeout,
                    prepare_only, synthetic, *, batches, collected_inputs=None,
                    skills_cache=None, local_skills_only=False):
    """Retain all evidence, run bounded sessions, then publish one complete report."""
    plan = plan_report(settings, start, end)
    output = output.absolute()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    manifest = {
        "schema_version": 2, "workflow": "report", "application_version": __version__,
        "scope": {"kind": "hutch"}, "settings": plan["settings"], "window": plan["window"],
        "aggregation": "independent-batches", "status": "preparing",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "evidence_kind": "synthetic" if synthetic else ("collected-log-summaries" if collected_inputs else "user-supplied"),
        "grafana": {"status": "not_configured", "queried": False},
        "coverage": "all prepared documents assigned to batches; raw-log coverage and sampling limits remain",
        "timeout_seconds_per_batch": timeout, "sources": [], "batches": [],
    }
    try:
        if collected_inputs is not None:
            shutil.copytree(collected_inputs, output / "collection")
            manifest["collection"] = "collection/collection.json"
            logs = [output / "collection" / path.name for path in logs]
        manifest["sources"] = snapshot_logs(logs, output / "evidence",
                                             max_files=MAX_REPORT_FILES, max_total_bytes=MAX_REPORT_BYTES)
        for number, indexes in enumerate(batches, 1):
            manifest["batches"].append({
                "number": number, "directory": f"batches/{number:03}", "status": "pending",
                "source_ids": [manifest["sources"][i]["id"] for i in indexes],
            })
        manifest["status"] = "preparing" if prepare_only else "running"
        write_json(output / "manifest.json", manifest)
        for batch, indexes in zip(manifest["batches"], batches):
            action = "Preparing" if prepare_only else "Analyzing"
            print(f"{action} evidence batch {batch['number']}/{len(batches)} ({len(indexes)} documents)...", file=sys.stderr, flush=True)
            batch["status"] = "running"
            write_json(output / "manifest.json", manifest)
            paths = [output / manifest["sources"][i]["snapshot"] for i in indexes]
            try:
                analyze_logs(settings, start, end, paths, output / batch["directory"], provider,
                             executable, timeout, prepare_only, synthetic,
                             skills_cache=skills_cache, local_skills_only=local_skills_only,
                             batch_context={"number": batch["number"], "total": len(batches),
                                            "shared_scope": collected_inputs is not None})
            except BaseException:
                batch["status"] = "failed"
                raise
            batch["status"] = "prepared_only" if prepare_only else "completed"
            write_json(output / "manifest.json", manifest)
        if prepare_only:
            manifest["status"] = "prepared_only"
            return output
        findings = combine_findings(output, manifest)
        write_json(output / "findings.json", findings)
        write_private(output / "report.md", render_report(findings, manifest))
        write_html_bundle(output, findings, manifest)
        manifest["status"] = "completed"
        manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
        manifest["validation"] = "each batch passed skill/evidence audit and citation validation; findings concatenated with remapped citations"
        return output
    except BaseException as error:
        manifest["status"] = "failed"
        manifest["failure_type"] = type(error).__name__
        raise
    finally:
        write_json(output / "manifest.json", manifest)
