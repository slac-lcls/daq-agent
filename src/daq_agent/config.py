"""Load the non-secret settings needed to plan an investigation."""

from dataclasses import dataclass
from pathlib import Path
import re
import tomllib
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class Settings:
    hutch: str
    partition: int
    timezone: str
    model: str


def load_settings(path: Path) -> Settings:
    with path.open("rb") as stream:
        data = tomllib.load(stream)
    fields = {"hutch", "partition", "timezone", "model"}
    if set(data) != fields:
        raise ValueError("configuration must contain exactly: hutch, partition, timezone, model")
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
    return Settings(**data)
