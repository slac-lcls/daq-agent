"""One-command rolling-window log collection and separate partition analyses."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from importlib.resources import as_file, files
from pathlib import Path
import re
import shutil
import subprocess
import sys

from . import __version__
from .collectors.session_logs import collect_logs
from .config import load_settings
from .log_analysis import analyze_logs, write_json
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


def generate_report(settings, start, end, output: Path, *, partitions=None,
                    prepare_only=False, local_skills_only=False, skills_cache=None, timeout=600):
    if not settings.log_root:
        raise ValueError("set log_root in the hutch configuration or pass --log-root")
    if not 1 <= timeout <= 600:
        raise ValueError("timeout must be between 1 and 600 seconds")
    if partitions is not None and (not partitions or any(type(p) is not int or not 0 <= p <= 7 for p in partitions)):
        raise ValueError("partitions must be integers from 0 to 7")
    provider = Path(settings.provider_config).expanduser() if settings.provider_config else None
    if not prepare_only:
        if provider is None:
            raise ValueError("provider_config is required for a model call")
        select_provider(provider, settings.model)
        if shutil.which(str(Path(settings.opencode).expanduser())) is None:
            raise ValueError("OpenCode executable not found; configure opencode or pass --opencode")
    output = output.expanduser().absolute()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    batch = {"schema_version": 1, "application_version": __version__, "workflow": "report", "status": "collecting", "hutch": settings.hutch,
             "window": {"start_inclusive": start.isoformat(), "end_exclusive": end.isoformat()},
             "created_at": datetime.now(timezone.utc).isoformat(), "reports": [],
             "review": "AI drafts; conclusions require human review; no reviewed-summary is generated"}
    write_json(output / "batch.json", batch)
    try:
        if settings.daq_skills is not None and not local_skills_only:
            # Exact pinned revision; validates/reuses an existing cache offline.
            sync_skills(settings.daq_skills, skills_cache)
        print(f"Collecting {settings.hutch} logs for {start.isoformat()} to {end.isoformat()}...", file=sys.stderr, flush=True)
        inputs = collect_logs(Path(settings.log_root), output / "inputs", settings.hutch,
                              start, end, settings.timezone, partitions)
        batch["collection"] = "inputs/collection.json"
        batch["status"] = "analyzing" if not prepare_only else "preparing"
        write_json(output / "batch.json", batch)
        for partition, logs in sorted(inputs.items(), reverse=True):
            report = {"partition": partition, "output": f"partition-{partition}", "status": "running"}
            batch["reports"].append(report)
            write_json(output / "batch.json", batch)
            action = "Preparing" if prepare_only else "Analyzing"
            print(f"{action} {settings.hutch} partition {partition} ({len(logs)} evidence documents)...", file=sys.stderr, flush=True)
            try:
                analyze_logs(replace(settings, partition=partition), start.isoformat(), end.isoformat(),
                             logs, output / report["output"], provider, str(Path(settings.opencode).expanduser()),
                             timeout, prepare_only, skills_cache=skills_cache, local_skills_only=local_skills_only)
                report["status"] = "prepared_only" if prepare_only else "completed"
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                report.update(status="failed", failure_type=type(error).__name__)
                # Preserve other independent partition results; never claim full success.
            write_json(output / "batch.json", batch)
        if any(report["status"] == "failed" for report in batch["reports"]):
            raise ValueError(f"one or more partition analyses failed; inspect {output / 'batch.json'} and partition artifacts")
        batch["status"] = "prepared_only" if prepare_only else "completed"
        batch["completed_at"] = datetime.now(timezone.utc).isoformat()
    except BaseException as error:
        batch["status"] = "failed"
        batch["failure_type"] = type(error).__name__
        raise
    finally:
        write_json(output / "batch.json", batch)
    return {"status": batch["status"], "output": str(output), "reports": batch["reports"]}
