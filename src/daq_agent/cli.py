"""CLI for configuration, shared-log reports, supplied-log analysis, and viewing."""

import argparse
from dataclasses import asdict, replace
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo
import json
from pathlib import Path
import subprocess

from . import __version__
from .config import Settings, load_settings, validate_model
from .workflow import plan_report
from .viewer import view_report
from .skill_sources import sync_skills
from .reporting import generate_report, report_settings, report_window


def default_output(settings: Settings) -> Path:
    """Group distinct runs by hutch and launch month in the configured timezone."""
    now = datetime.now(ZoneInfo(settings.timezone))
    run = f"{now:%dT%H%M%S}-{settings.hutch}-{uuid4().hex[:12]}-report"
    return Path(settings.output_root).expanduser() / settings.hutch / f"{now:%Y}" / f"{now:%m}" / run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Experimental DAQ diagnostics: collect shared logs or analyze supplied excerpts."
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("config", help="validate and display non-secret configuration")
    inspect.add_argument("--config", type=Path, required=True)
    plan = commands.add_parser("plan-report", help="emit a report plan without collecting evidence")
    plan.add_argument("--config", type=Path, required=True)
    plan.add_argument("--from", dest="start", required=True, help="inclusive date or offset timestamp")
    plan.add_argument("--to", dest="end", required=True, help="exclusive date or offset timestamp")
    report = commands.add_parser("report", help="generate one report for a hutch and time window")
    report.add_argument("--hutch", required=True, help="hutch profile (currently tmo is packaged)")
    report.add_argument("--config", type=Path, help="override the packaged hutch profile")
    report.add_argument("--last", help="rolling elapsed window, e.g. 2d or 48h; maximum 7d")
    report.add_argument("--from", dest="start", help="alternative explicit inclusive boundary")
    report.add_argument("--to", dest="end", help="alternative explicit exclusive boundary")
    report.add_argument("--log", type=Path, action="append", help="optional supplied excerpt; repeat to bypass automatic collection")
    report.add_argument("--synthetic", action="store_true", help="label supplied --log inputs as synthetic")
    report.add_argument("--log-root", help="override the shared YYYY/MM log root")
    report.add_argument("--output", type=Path, help="new private report directory")
    report.add_argument("--provider-config", type=Path)
    report.add_argument("--opencode")
    report.add_argument("--model")
    report.add_argument("--timeout", type=int, default=600, help="OpenCode timeout in seconds per model session; maximum 600")
    report.add_argument("--prepare-only", action="store_true", help="prepare report evidence without a model call")
    report.add_argument("--skills-cache", type=Path)
    report.add_argument("--local-skills-only", action="store_true", help="explicitly disable upstream skills")
    sync = commands.add_parser("sync-skills", help="fetch configured skills at the pinned commit; no model call")
    sync.add_argument("--config", type=Path, required=True)
    sync.add_argument("--skills-cache", type=Path)
    viewer = commands.add_parser("view", help="browse the latest completed report or a supplied run")
    viewer.add_argument("run", nargs="?", type=Path, help="completed run directory (default: latest valid report)")
    viewer.add_argument("--root", type=Path, help="report search root (default: ~/daq/agent-logs or personal settings)")
    viewer.add_argument("--hutch", help="select the latest report for this hutch")
    viewer.add_argument("--port", type=int, help="local viewer port (default: 8765; 0 selects an available port)")
    viewer.add_argument("--ssh-host", help="laptop SSH alias used in printed tunnel instructions")
    viewer.add_argument("--viewer-config", type=Path, help="personal viewer TOML configuration path")
    viewer.add_argument("--save-settings", action="store_true", help="save root, port, and SSH alias as personal defaults")
    args = parser.parse_args(argv)
    try:
        if args.command == "view":
            return view_report(args)
        if args.command == "report":
            settings = report_settings(args.hutch, args.config)
            overrides = {name: str(getattr(args, name)) for name in
                         ("log_root", "provider_config", "opencode", "model") if getattr(args, name) is not None}
            settings = replace(settings, **overrides)
            validate_model(settings.model)
            start, end = report_window(args.last, args.start, args.end, settings.timezone)
            output = args.output or default_output(settings)
            result = generate_report(settings, start, end, output, logs=args.log, synthetic=args.synthetic,
                                     prepare_only=args.prepare_only, local_skills_only=args.local_skills_only,
                                     skills_cache=args.skills_cache, timeout=args.timeout)
            print(json.dumps(result, indent=2))
            return 0
        settings = load_settings(args.config)
        if args.command == "sync-skills":
            if settings.daq_skills is None:
                raise ValueError("configuration has no daq_skills source")
            directory = sync_skills(settings.daq_skills, args.skills_cache)
            print(json.dumps({"status": "synced", "revision": settings.daq_skills.revision, "cache": str(directory)}, indent=2))
            return 0
        result = asdict(settings) if args.command == "config" else plan_report(settings, args.start, args.end)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))
    return 0
