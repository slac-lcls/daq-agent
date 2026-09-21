"""CLI for configuration, report planning, and supplied-log analysis."""

import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
import subprocess

from . import __version__
from .config import load_settings
from .log_analysis import analyze_logs
from .workflow import plan_report


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
    analysis.add_argument("--output", type=Path, required=True, help="new private artifact directory")
    analysis.add_argument("--provider-config", type=Path, help="JSON OpenCode configuration containing credential references")
    analysis.add_argument("--opencode", default="opencode", help="OpenCode executable or absolute path")
    analysis.add_argument("--model", help="override configured provider/model")
    analysis.add_argument("--timeout", type=int, default=180, help="OpenCode timeout in seconds (maximum 600)")
    analysis.add_argument("--prepare-only", action="store_true", help="snapshot evidence and instructions without a model call")
    analysis.add_argument("--synthetic", action="store_true", help="label the supplied evidence as synthetic")
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.config)
        if args.command == "analyze-logs":
            if args.model:
                if "/" not in args.model or not all(args.model.split("/", 1)) or any(c.isspace() for c in args.model):
                    raise ValueError("model must have the form provider/model")
                settings = replace(settings, model=args.model)
            directory = analyze_logs(settings, args.start, args.end, args.log, args.output,
                                     args.provider_config, args.opencode, args.timeout,
                                     args.prepare_only, args.synthetic)
            result = {"status": "prepared_only" if args.prepare_only else "completed", "output": str(directory)}
        else:
            result = asdict(settings) if args.command == "config" else plan_report(settings, args.start, args.end)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))
    return 0
