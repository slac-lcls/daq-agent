"""Load the non-secret settings needed to plan an investigation."""

from dataclasses import dataclass, replace
from pathlib import Path
import re
import tomllib
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .skill_sources import SkillSource, parse_source
from .known_conditions import validate_rules


@dataclass(frozen=True)
class Settings:
    hutch: str
    timezone: str
    model: str
    provider_config: str | None = None
    opencode: str = "opencode"
    output_root: str = "~/daq/agent-logs"
    daq_skills: SkillSource | None = None
    log_root: str | None = None
    runtime: str = "opencode"
    claude: str = "claude"
    known_conditions: tuple[str, ...] = ()
    claude_deployment: str = "personal"
    claude_effort: str | None = None
    claude_cache_ttl: str | None = None


def validate_model(model: str, runtime: str = "opencode") -> None:
    if runtime not in {"opencode", "claude"}:
        raise ValueError("runtime must be opencode or claude")
    if runtime == "claude":
        if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}(?:\[1m\])?", model):
            raise ValueError("Claude model must be an alias (sonnet, opus, haiku) or native model ID, without a provider/ prefix")
        return
    if not isinstance(model, str) or not re.fullmatch(r"[^\s/]+/[^\s]+", model):
        raise ValueError("model must have the form provider/model")


def runtime_settings(settings, *, runtime=None, model=None, **overrides):
    """Select a runtime without carrying an OpenCode model ID into Claude."""
    selected = runtime or settings.runtime
    deployment = overrides.get('claude_deployment', settings.claude_deployment)
    if model is None:
        model = ('opus' if deployment == 'lcls' else 'sonnet') if selected == 'claude' and settings.runtime != 'claude' else settings.model
    validate_model(model, selected)
    result = replace(settings, runtime=selected, model=model, **overrides)
    from .claude_config import validate_options
    validate_options(result.claude_deployment, result.claude_effort, result.claude_cache_ttl)
    return result


def load_settings(path: Path) -> Settings:
    with path.open("rb") as stream:
        data = tomllib.load(stream)
    fields = {"hutch", "timezone", "model"}
    optional = {"provider_config", "opencode", "output_root", "log_root", "runtime", "claude",
                "claude_deployment", "claude_effort", "claude_cache_ttl"}
    if not fields <= set(data) or set(data) - fields - optional - {"daq_skills", "partition", "known_conditions"}:
        raise ValueError("configuration requires hutch, timezone, model; "
                         "optional fields: provider_config, opencode, runtime, claude, claude_deployment, claude_effort, claude_cache_ttl, output_root, log_root, daq_skills, known_conditions, legacy partition")
    for name in optional & set(data):
        if not isinstance(data[name], str) or not data[name].strip():
            raise ValueError(f"{name} must be a nonempty string")
    if not isinstance(data["hutch"], str) or not re.fullmatch(r"[a-z]{3}", data["hutch"]):
        raise ValueError("hutch must be a lowercase three-letter code")
    if "partition" in data and (type(data["partition"]) is not int or not 0 <= data["partition"] <= 7):
        raise ValueError("partition must be an integer from 0 to 7")
    # Accept old configs without carrying obsolete reporting scope forward.
    data.pop("partition", None)
    if not isinstance(data["timezone"], str):
        raise ValueError("timezone must be an IANA timezone name")
    try:
        ZoneInfo(data["timezone"])
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError("timezone must be an available IANA timezone name") from error
    validate_model(data["model"], data.get("runtime", "opencode"))
    if "daq_skills" in data:
        data["daq_skills"] = parse_source(data["daq_skills"])
    if 'known_conditions' in data:
        data['known_conditions'] = validate_rules(data['known_conditions'])
    return runtime_settings(Settings(**data))
