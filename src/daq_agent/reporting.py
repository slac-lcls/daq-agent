"""One hutch/time-window report, with automatic collection or supplied excerpts."""

from datetime import datetime, timedelta, timezone
from importlib.resources import as_file, files
from pathlib import Path
import re
import json
import time
import shutil
import sys
import tempfile

from .artifacts import write_json, write_private
from .html_reports import write_html_bundle
from .reports import render_report
from .batches import analyze_batches, plan_batches
from .collectors.session_logs import collect_logs
from .config import load_settings
from .log_analysis import analyze_logs
from .runtime import select_provider
from .skill_sources import sync_skills
from .workflow import parse_boundary


def report_settings(hutch: str, config: Path | None = None):
    if not re.fullmatch(r"[a-z]{3}", hutch):
        raise ValueError("hutch must be a lowercase three-letter code")
    if config is not None:
        settings = load_settings(config)
    else:
        profile = files("daq_agent").joinpath(f"profiles/{hutch}.toml")
        if not profile.is_file():
            raise ValueError(f"no packaged profile for {hutch}; supply --config")
        with as_file(profile) as path:
            settings = load_settings(path)
    if settings.hutch != hutch:
        raise ValueError("--hutch must match the configuration")
    return settings


def report_window(last, start, end, timezone_name, *, now=None):
    if last is not None:
        if start is not None or end is not None:
            raise ValueError("use either --last or both --from and --to")
        match = re.fullmatch(r"([1-9][0-9]*)([dh])", last)
        if not match:
            raise ValueError("--last must be an integer duration such as 2d or 48h (maximum 7d)")
        hours = int(match[1]) * (24 if match[2] == "d" else 1)
        if hours > 168:
            raise ValueError("report window is limited to 7 days; narrow --last")
        end_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        start_time = end_time - timedelta(hours=hours)
    else:
        if start is None or end is None:
            raise ValueError("supply --last 2d or both --from and --to")
        start_time = parse_boundary(start, timezone_name)
        end_time = parse_boundary(end, timezone_name)
        if not timedelta(0) < end_time - start_time <= timedelta(days=7):
            raise ValueError("report window must be positive and at most 7 days")
    return start_time, end_time


def generate_report(settings, start, end, output: Path, *, logs=None, synthetic=False,
                    prepare_only=False, local_skills_only=False, skills_cache=None, timeout=600):
    """Collect evidence once and produce one report using bounded model sessions."""
    started_at = datetime.now(timezone.utc).isoformat()
    started_clock = time.monotonic()
    automatic_collection = logs is None
    if logs is None and not settings.log_root:
        raise ValueError("set log_root in the hutch configuration or pass --log-root")
    if synthetic and logs is None:
        raise ValueError("--synthetic requires explicitly supplied --log inputs")
    if not 1 <= timeout <= 600:
        raise ValueError("timeout must be between 1 and 600 seconds")
    provider = Path(settings.provider_config).expanduser() if settings.provider_config else None
    if not prepare_only:
        if provider is None:
            raise ValueError("provider_config is required for a model call")
        select_provider(provider, settings.model)
        if shutil.which(str(Path(settings.opencode).expanduser())) is None:
            raise ValueError("OpenCode executable not found; configure opencode or pass --opencode")
    output = output.expanduser().absolute()
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    if settings.daq_skills is not None and not local_skills_only:
        # Exact pinned revision; validates/reuses an existing cache offline.
        sync_skills(settings.daq_skills, skills_cache)
    with tempfile.TemporaryDirectory(prefix="daq-agent-collection-") as directory:
        collected = None
        if logs is None:
            print(f"Collecting {settings.hutch} logs for {start.isoformat()} to {end.isoformat()}...", file=sys.stderr, flush=True)
            collected = Path(directory) / "inputs"
            logs = collect_logs(Path(settings.log_root), collected, settings.hutch, start, end, settings.timezone)
        batches = plan_batches(logs, shared_scope=collected is not None)
        action = "Preparing" if prepare_only else "Analyzing"
        session_label = "session" if len(batches) == 1 else "sessions"
        print(f"{action} one {settings.hutch} report ({len(logs)} evidence documents; {len(batches)} model {session_label})...", file=sys.stderr, flush=True)
        analyzer = analyze_logs if len(batches) == 1 else analyze_batches
        options = {} if len(batches) == 1 else {"batches": batches}
        analyzer(settings, start.isoformat(), end.isoformat(), logs, output, provider,
                 str(Path(settings.opencode).expanduser()), timeout, prepare_only, synthetic,
                 skills_cache=skills_cache, local_skills_only=local_skills_only,
                 collected_inputs=collected, defer_completion=True, **options)
    # The root remains in-progress until deterministic statistics and both report
    # formats are ready. Do not publish a completed manifest then rewrite it.
    manifest = json.loads((output / "manifest.json").read_text())
    try:
        raw_files = launch_groups = None
        if automatic_collection:
            collection = json.loads((output / "collection/collection.json").read_text())
            raw_files = len(collection["files"])
            launch_groups = len({record["launch"] for record in collection["files"]})
        manifest["generation_statistics"] = {
            "schema_version": 1,
            "started_at": started_at,
            "measured_through": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(time.monotonic() - started_clock, 3),
            "timing_scope": "report entry through initial report assembly; excludes final statistics publication",
            "input_mode": "automatic-collection" if automatic_collection else "supplied-excerpts",
            "raw_log_files_scanned": raw_files,
            "launch_groups": launch_groups,
            "supplied_log_files": None if automatic_collection else len(manifest["sources"]),
            "evidence_documents": len(manifest["sources"]),
            "model_sessions_completed": 0 if prepare_only else len(batches),
            "model_sessions_planned": len(batches),
            "numbered_daq_runs": None,
        }
        if not prepare_only:
            findings = json.loads((output / "findings.json").read_text())
            write_private(output / "report.md", render_report(findings, manifest))
            write_html_bundle(output, findings, manifest)
            manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
            manifest["status"] = "completed"
    except BaseException as error:
        manifest["status"] = "failed"
        manifest["failure_type"] = type(error).__name__
        raise
    finally:
        write_json(output / "manifest.json", manifest)
    return {"status": "prepared_only" if prepare_only else "completed", "output": str(output)}
