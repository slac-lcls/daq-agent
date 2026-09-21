"""Validate the shape and source locations of model findings; render a draft."""

import json


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 16000:
        raise ValueError(f"{name} must be nonempty text of at most 16000 characters")


def validate_findings(text: str, sources: list[dict]) -> dict:
    text = text.strip()
    if text.startswith("```json\n") and text.endswith("```"):
        text = text[len("```json\n"):-3].strip()
    result = json.loads(text)
    if not isinstance(result, dict) or set(result) != {"summary", "findings", "limitations"}:
        raise ValueError("response must contain exactly summary, findings, and limitations")
    _text(result["summary"], "summary")
    if not isinstance(result["limitations"], list) or not 1 <= len(result["limitations"]) <= 20:
        raise ValueError("response must state limitations")
    for limitation in result["limitations"]:
        _text(limitation, "limitation")
    findings = result["findings"]
    if not isinstance(findings, list) or len(findings) > 20:
        raise ValueError("findings must be a list of at most 20 items")
    counts = {source["id"]: source["lines"] for source in sources}
    for finding in findings:
        fields = {"title", "observation", "hypothesis", "next_check", "evidence"}
        if not isinstance(finding, dict) or set(finding) != fields:
            raise ValueError("finding has missing or unexpected fields")
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


def render_report(result: dict, manifest: dict) -> str:
    settings = manifest["settings"]
    lines = [
        "# DAQ log analysis — draft", "",
        f"Hutch: {settings['hutch']}; partition: {settings['partition']}",
        f"Window: [{manifest['window']['start_inclusive']}, {manifest['window']['end_exclusive']})", "",
        f"Evidence kind: **{manifest['evidence_kind']}**. Only supplied excerpts were analyzed.",
        "Grafana: **not queried — integration unavailable in this workflow**.",
        "Citation locations were validated; diagnostic conclusions still need human review.", "",
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
    lines.extend(["## Limitations", ""])
    lines.extend(f"- {item}" for item in result["limitations"])
    lines.extend(["", "## Provenance", "", f"Model: `{settings['model']}`", "",
                  "See `manifest.json`, `events.jsonl`, and the retained evidence snapshots.", ""])
    return "\n".join(lines)
