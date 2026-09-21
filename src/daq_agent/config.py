"""Load the non-secret settings needed to plan an investigation."""

from dataclasses import dataclass
from pathlib import Path
import re
import tomllib
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .skill_sources import SkillSource, parse_source


@dataclass(frozen=True)
class Settings:
    hutch: str
    partition: int
    timezone: str
    model: str
    provider_config: str | None = None
    opencode: str = "opencode"
    output_root: str = "~/daq/agent-logs"
    daq_skills: SkillSource | None = None
    log_root: str | None = None


def load_settings(path: Path) -> Settings:
    with path.open("rb") as stream:
        data = tomllib.load(stream)
    fields = {"hutch", "partition", "timezone", "model"}
    optional = {"provider_config", "opencode", "output_root", "log_root"}
    if not fields <= set(data) or set(data) - fields - optional - {"daq_skills"}:
        raise ValueError("configuration requires hutch, partition, timezone, model; "
                         "optional fields: provider_config, opencode, output_root, log_root, daq_skills")
    for name in optional & set(data):
        if not isinstance(data[name], str) or not data[name].strip():
            raise ValueError(f"{name} must be a nonempty string")
    if not isinstance(data["hutch"], str) or not re.fullmatch(r"[a-z]{3}", data["hutch"]):
        raise ValueError("hutch must be a lowercase three-letter code")
    if type(data["partition"]) is not int or not 0 <= data["partition"] <= 7:
        raise ValueError("partition must be an integer from 0 to 7")
    if not isinstance(data["timezone"], str):
        raise ValueError("timezone must be an IANA timezone name")
    try:
        ZoneInfo(data["timezone"])
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError("timezone must be an available IANA timezone name") from error
    model = data["model"]
    if not isinstance(model, str) or not re.fullmatch(r"[^\s/]+/[^\s]+", model):
        raise ValueError("model must have the form provider/model")
    if "daq_skills" in data:
        data["daq_skills"] = parse_source(data["daq_skills"])
    return Settings(**data)
