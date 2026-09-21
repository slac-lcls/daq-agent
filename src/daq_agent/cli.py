"""CLI scaffold: inspect configuration and plan a historical report."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from . import __version__
from .config import load_settings
from .workflow import plan_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Experimental DAQ agent scaffold. No live or AI API calls are implemented."
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("config", help="validate and display non-secret configuration")
    inspect.add_argument("--config", type=Path, required=True)
    plan = commands.add_parser("plan-report", help="emit a report plan without collecting evidence")
    plan.add_argument("--config", type=Path, required=True)
    plan.add_argument("--from", dest="start", required=True, help="inclusive date or offset timestamp")
    plan.add_argument("--to", dest="end", required=True, help="exclusive date or offset timestamp")
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.config)
        result = asdict(settings) if args.command == "config" else plan_report(settings, args.start, args.end)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))
    return 0
