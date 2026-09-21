"""One hutch/time-window report, with automatic collection or supplied excerpts."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from importlib.resources import as_file, files
from pathlib import Path
import re
import shutil
import sys
import tempfile

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
    """Collect evidence once, then run a single hutch-wide OpenCode analysis."""
    settings = replace(settings, partition=None)
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
        action = "Preparing" if prepare_only else "Analyzing"
        print(f"{action} one {settings.hutch} report ({len(logs)} evidence documents)...", file=sys.stderr, flush=True)
        analyze_logs(settings, start.isoformat(), end.isoformat(), logs, output, provider,
                     str(Path(settings.opencode).expanduser()), timeout, prepare_only, synthetic,
                     skills_cache=skills_cache, local_skills_only=local_skills_only,
                     collected_inputs=collected)
    return {"status": "prepared_only" if prepare_only else "completed", "output": str(output)}
