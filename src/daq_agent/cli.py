"""CLI for configuration, report planning, and supplied-log analysis."""

import argparse
from dataclasses import asdict, replace
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo
import json
import os
from pathlib import Path
import subprocess

from . import __version__
from .config import Settings, load_settings
from .log_analysis import analyze_logs
from .workflow import plan_report
from .viewer import view_report


def default_output(settings: Settings) -> Path:
    """Group distinct runs by hutch and launch month in the configured timezone."""
    now = datetime.now(ZoneInfo(settings.timezone))
    run = f"{now:%dT%H%M%S}-{settings.hutch}-p{settings.partition}-{uuid4().hex[:12]}"
    return Path(settings.output_root).expanduser() / settings.hutch / f"{now:%Y}" / f"{now:%m}" / run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Experimental DAQ diagnostics: plan a report or analyze supplied log excerpts."
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("config", help="validate and display non-secret configuration")
    inspect.add_argument("--config", type=Path, required=True)
    plan = commands.add_parser("plan-report", help="emit a report plan without collecting evidence")
    plan.add_argument("--config", type=Path, required=True)
    plan.add_argument("--from", dest="start", required=True, help="inclusive date or offset timestamp")
    plan.add_argument("--to", dest="end", required=True, help="exclusive date or offset timestamp")
    analysis = commands.add_parser("analyze-logs", help="analyze supplied excerpts with OpenCode and save a draft")
    analysis.add_argument("--config", type=Path, required=True)
    analysis.add_argument("--from", dest="start", required=True)
    analysis.add_argument("--to", dest="end", required=True)
    analysis.add_argument("--log", type=Path, action="append", required=True, help="small UTF-8 excerpt; repeatable")
    analysis.add_argument("--output", type=Path, help="new private artifact directory (default: configured output_root/hutch/YYYY/MM/unique-run)")
    analysis.add_argument("--provider-config", type=Path, help="override configured OpenCode provider JSON path")
    analysis.add_argument("--opencode", help="override configured OpenCode executable or path")
    analysis.add_argument("--model", help="override configured provider/model")
    analysis.add_argument("--timeout", type=int, default=180, help="OpenCode timeout in seconds (maximum 600)")
    analysis.add_argument("--prepare-only", action="store_true", help="snapshot evidence and instructions without a model call")
    analysis.add_argument("--synthetic", action="store_true", help="label the supplied evidence as synthetic")
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
        settings = load_settings(args.config)
        if args.command == "analyze-logs":
            if args.model:
                if "/" not in args.model or not all(args.model.split("/", 1)) or any(c.isspace() for c in args.model):
                    raise ValueError("model must have the form provider/model")
                settings = replace(settings, model=args.model)
            provider_path = args.provider_config or settings.provider_config
            provider = Path(provider_path).expanduser() if provider_path else None
            executable = os.path.expanduser(args.opencode or settings.opencode)
            output = args.output.expanduser() if args.output else default_output(settings)
            directory = analyze_logs(settings, args.start, args.end, args.log, output,
                                     provider, executable, args.timeout,
                                     args.prepare_only, args.synthetic)
            result = {"status": "prepared_only" if args.prepare_only else "completed", "output": str(directory)}
        else:
            result = asdict(settings) if args.command == "config" else plan_report(settings, args.start, args.end)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))
    return 0
