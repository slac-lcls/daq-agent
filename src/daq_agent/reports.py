"""Validate the shape and source locations of model findings; render a draft."""

from .model_json import load_model_json
from .report_statistics import statistics_rows
from .known_conditions import sections as known_sections
from .service_coverage import service_coverage_rows

MAX_BATCHES = 16
MAX_BATCH_FINDINGS = 20


def findings_schema(sources: list[dict]) -> dict:
    """Runtime output contract; Python still validates bounds and citations."""
    text = {"type": "string", "minLength": 1, "maxLength": 16000}
    citation = {
        "type": "object", "additionalProperties": False,
        "required": ["source", "line_start", "line_end"],
        "properties": {
            "source": {"type": "string", "enum": [s["id"] for s in sources]},
            "line_start": {"type": "integer", "minimum": 1},
            "line_end": {"type": "integer", "minimum": 1},
        },
    }
    finding = {
        "type": "object", "additionalProperties": False,
        "required": ["title", "observation", "hypothesis", "next_check", "evidence"],
        "properties": {**{key: dict(text) for key in ("title", "observation", "hypothesis", "next_check")},
                       "evidence": {"type": "array", "minItems": 1, "maxItems": 20, "items": citation}},
    }
    return {
        "type": "object", "additionalProperties": False,
        "required": ["summary", "findings", "limitations"],
        "properties": {
            "summary": dict(text),
            "findings": {"type": "array", "maxItems": MAX_BATCH_FINDINGS, "items": finding},
            "limitations": {"type": "array", "minItems": 1, "maxItems": 20, "items": dict(text)},
        },
    }


def _text(value, name, limit=16000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{name} must be nonempty text of at most {limit} characters")


def validate_findings(text: str, sources: list[dict], *, combined=False) -> dict:
    result = load_model_json(text)
    if not isinstance(result, dict) or set(result) != {"summary", "findings", "limitations"}:
        raise ValueError("response must contain exactly summary, findings, and limitations")
    max_findings = MAX_BATCHES * MAX_BATCH_FINDINGS if combined else MAX_BATCH_FINDINGS
    max_limitations = 1 + MAX_BATCHES * 20 if combined else 20
    _text(result["summary"], "summary", (16000 + 64) * MAX_BATCHES if combined else 16000)
    if not isinstance(result["limitations"], list) or not 1 <= len(result["limitations"]) <= max_limitations:
        raise ValueError("response must state limitations")
    for limitation in result["limitations"]:
        _text(limitation, "limitation", 16032 if combined else 16000)
    findings = result["findings"]
    if not isinstance(findings, list) or len(findings) > max_findings:
        raise ValueError(f"findings must be a list of at most {max_findings} items")
    counts = {source["id"]: source["lines"] for source in sources}
    for index, finding in enumerate(findings, 1):
        fields = {"title", "observation", "hypothesis", "next_check", "evidence"}
        if not isinstance(finding, dict):
            raise ValueError(f"finding {index} must be an object")
        if set(finding) != fields:
            missing = ', '.join(sorted(fields - set(finding))) or 'none'
            # Do not echo arbitrary model-provided field names into the console.
            extra = len(set(finding) - fields)
            raise ValueError(f"finding {index} has missing or unexpected fields: missing {missing}; unexpected field count {extra}")
        for name in fields - {"evidence"}:
            _text(finding[name], name)
        if not isinstance(finding["evidence"], list) or not 1 <= len(finding["evidence"]) <= 20:
            raise ValueError("every finding needs evidence citations")
        for citation in finding["evidence"]:
            if not isinstance(citation, dict) or set(citation) != {"source", "line_start", "line_end"}:
                raise ValueError("invalid citation fields")
            source, start, end = (citation[name] for name in ("source", "line_start", "line_end"))
            if not isinstance(source, str) or source not in counts:
                raise ValueError("citation references an unknown source")
            if type(start) is not int or type(end) is not int or not 1 <= start <= end <= counts[source]:
                raise ValueError("citation line range is outside its source")
    return result


def scope_description(settings: dict) -> str:
    """Render current scope or the partition recorded in an older report."""
    partition = settings.get("partition")
    scope = "scope: hutch and time window" if partition is None else f"partition: {partition}"
    return f"{settings['hutch']}; {scope}"


def render_report(result: dict, manifest: dict) -> str:
    settings = manifest["settings"]
    lines = [
        "# DAQ log analysis — draft", "",
        f"Hutch: {scope_description(settings)}",
        f"Window: [{manifest['window']['start_inclusive']}, {manifest['window']['end_exclusive']})", "",
        f"Evidence kind: **{manifest['evidence_kind']}**. Only supplied excerpts were analyzed.",
        *[f"{label}: {status}" for label, status in service_coverage_rows(manifest)],
        "Citation locations were validated; diagnostic conclusions still need human review.", "",
        "## Generation and coverage", "",
        *[f"- **{label}:** {value}" for label, value in statistics_rows(manifest)], "",
        "Launch groups are not numbered DAQ runs. Counts describe retained input coverage, not confirmed activity throughout the window.", "",
        "## Summary", "", result["summary"], "", "## Findings", "",
    ]
    sources = {source["id"]: source for source in manifest["sources"]}
    if not result["findings"]:
        lines.extend(["No findings returned; this does not establish healthy DAQ operation.", ""])
    for finding in result["findings"]:
        lines.extend([
            f"### {finding['title']}", "",
            f"Observation: {finding['observation']}", "",
            f"Hypothesis: {finding['hypothesis']}", "",
            f"Next check: {finding['next_check']}", "", "Evidence:", "",
        ])
        for citation in finding["evidence"]:
            source = sources[citation["source"]]
            lines.append(f"- [{source['id']}, lines {citation['line_start']}–{citation['line_end']}]({source['snapshot']})")
        lines.append("")
    known = known_sections(manifest)
    if known:
        lines += ['## Known conditions — no model analysis', '',
                  'Deterministic counts and representative original source lines. Matches are deferred, not proof of healthy operation.', '']
        for title, text in known:
            lines += ['### ' + title, '', text, '']
    lines.extend(["## Limitations", ""])
    lines.extend(f"- {item}" for item in result["limitations"])
    lines.extend(["", "## Provenance", "", f"Model: `{settings['model']}`", "",
                  ("See `manifest.json`, `batches/*/manifest.json`, batch runtime traces, and the retained evidence snapshots."
                   if manifest.get("aggregation") else "See `manifest.json`, `events.jsonl`, and the retained evidence snapshots."), ""])
    return "\n".join(lines)
