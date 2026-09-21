"""Report planning shared by future batch and interactive entry points."""

from dataclasses import asdict
from datetime import date, datetime, time, timezone
import re
from zoneinfo import ZoneInfo

from .config import Settings


def parse_boundary(value: str, timezone_name: str) -> datetime:
    """Accept local calendar dates or timestamps with explicit UTC offsets."""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        local = datetime.combine(date.fromisoformat(value), time(), ZoneInfo(timezone_name))
        # Reject local midnights skipped by a timezone offset change.
        round_trip = local.astimezone(timezone.utc).astimezone(local.tzinfo)
        if round_trip.replace(tzinfo=None) != local.replace(tzinfo=None):
            raise ValueError("date has no local midnight; use a timestamp with a UTC offset")
        if local.replace(fold=1).utcoffset() != local.utcoffset():
            raise ValueError("date has an ambiguous midnight; use a timestamp with a UTC offset")
        return local.astimezone(timezone.utc)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamps must include a UTC offset; dates use the configured timezone")
    return parsed.astimezone(timezone.utc)


def plan_report(settings: Settings, start: str, end: str) -> dict:
    start_time = parse_boundary(start, settings.timezone)
    end_time = parse_boundary(end, settings.timezone)
    if end_time <= start_time:
        raise ValueError("end must be later than start")
    return {
        "schema_version": 1,
        "status": "planned_only",
        "execution_implemented": False,
        "settings": asdict(settings),
        "window": {
            "start_inclusive": start_time.isoformat(),
            "end_exclusive": end_time.isoformat(),
        },
        "entry_skill": "robustness-report",
        "evidence_access": "not_checked",
        "model_access": "not_checked",
    }
