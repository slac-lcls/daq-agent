"""Portable HTML views of validated findings and their retained evidence."""

import base64
import hashlib
from html import escape
from pathlib import Path


LOG_SCRIPT = r"""function highlight() {
  const match = /^#L(\d{1,9})(?:-L?(\d{1,9}))?$/.exec(location.hash);
  if (!match) return;
  const start = Number(match[1]), end = Number(match[2] || match[1]);
  document.querySelectorAll('.line').forEach(line => {
    const n = Number(line.dataset.number);
    line.classList.toggle('selected', n >= start && n <= end);
  });
  const first = document.getElementById('L' + start);
  if (first) first.scrollIntoView({block: 'center'});
}
addEventListener('hashchange', highlight);
highlight();"""
SCRIPT_HASH = base64.b64encode(hashlib.sha256(LOG_SCRIPT.encode()).digest()).decode()
CSP = ("default-src 'none'; style-src 'unsafe-inline'; "
       f"script-src 'sha256-{SCRIPT_HASH}'; base-uri 'none'; form-action 'none'")
STYLE = """
:root { color-scheme: light dark; font-family: system-ui, sans-serif; }
body { max-width: 1000px; margin: 2rem auto; padding: 0 1.5rem; line-height: 1.6; }
h1,h2,h3 { line-height: 1.25; } h2 { margin-top: 2rem; }
a { color: #1263b5; } @media(prefers-color-scheme:dark) { a { color: #89c2ff; } }
.scope,article { border: 1px solid #8888; border-radius: 8px; padding: 1rem; margin: 1rem 0; }
.prose { white-space: pre-wrap; overflow-wrap: anywhere; }
.label { font-weight: 650; } .muted { opacity: .8; }
.log { font-family: monospace; font-size: .9rem; border: 1px solid #8888; }
.line { display: flex; scroll-margin-top: 2rem; }
.line:nth-child(even) { background: #8881; }
.number { flex: 0 0 4em; text-align: right; padding-right: 1em; user-select: none; }
.line code { white-space: pre-wrap; overflow-wrap: anywhere; min-width: 0; }
.line.selected,.line:target { background: #ffc857; color: #191919; }
.line.selected a,.line:target a { color: #124577; }
@media print { body { max-width: none; } article { break-inside: avoid; } }
"""


def page(title: str, body: str, *, log: bool = False) -> bytes:
    script = f"<script>{LOG_SCRIPT}</script>" if log else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="referrer" content="no-referrer">'
            f'<meta http-equiv="Content-Security-Policy" content="{escape(CSP, quote=True)}">'
            f'<title>{escape(title)}</title><style>{STYLE}</style></head>'
            f'<body>{body}{script}</body></html>').encode()


def paragraph(label: str, value: str) -> str:
    return f'<p class="prose"><span class="label">{escape(label)}</span> {escape(value)}</p>'


def html_bundle(findings: dict, manifest: dict, evidence: dict[str, str]) -> dict[str, bytes]:
    """Inputs are validated by the workflow or viewer before rendering."""
    settings, window = manifest["settings"], manifest["window"]
    sources = {source["id"]: source for source in manifest["sources"]}
    body = '<h1>DAQ log analysis — draft</h1><section class="scope">'
    body += paragraph("Hutch:", f'{settings["hutch"]}; partition: {settings["partition"]}')
    body += paragraph("Window:", f'[{window["start_inclusive"]}, {window["end_exclusive"]})')
    body += paragraph("Evidence:", f'{manifest["evidence_kind"]}; supplied excerpts only')
    body += paragraph("Grafana:", "Not queried — integration unavailable in this workflow.")
    body += '<p>Citation locations were validated; diagnostic conclusions need human review.</p></section>'
    body += '<nav><a href="report.md" download>Download Markdown</a> · '
    body += '<a href="findings.json" download>Download findings JSON</a></nav>'
    body += '<h2>Summary</h2>' + paragraph("", findings["summary"]) + '<h2>Findings</h2>'
    if not findings["findings"]:
        body += '<p>No findings returned; this does not establish healthy DAQ operation.</p>'
    for finding in findings["findings"]:
        body += f'<article><h3>{escape(finding["title"])}</h3>'
        for key, label in (("observation", "Observation:"), ("hypothesis", "Hypothesis:"),
                           ("next_check", "Next check:")):
            body += paragraph(label, finding[key])
        body += '<p class="label">Evidence — opens in a new tab:</p><ul>'
        for citation in finding["evidence"]:
            source = sources[citation["source"]]
            start, end = citation["line_start"], citation["line_end"]
            label = f'{Path(source["original_path"]).name} ({source["id"]}), lines {start}–{end}'
            href = f'logs/{source["id"]}.html#L{start}-L{end}'
            body += (f'<li><a href="{escape(href, quote=True)}" target="_blank" '
                     f'rel="noopener noreferrer">{escape(label)}</a></li>')
        body += '</ul></article>'
    body += '<h2>Limitations</h2><ul>'
    body += ''.join(f'<li class="prose">{escape(item)}</li>' for item in findings["limitations"])
    body += '</ul><h2>Provenance</h2>' + paragraph("Model:", settings["model"])
    body += paragraph("Run created:", manifest["created_at"])
    body += '<p><a href="manifest.json" download>Download manifest</a></p>'
    pages = {"report.html": page(f'DAQ report — {settings["hutch"]}', body)}
    for source_id, source in sources.items():
        name = Path(source["original_path"]).name
        body = f'<h1>{escape(name)}</h1><p><a href="../report.html">Back to report</a> · '
        body += f'<a href="../{escape(source["snapshot"], quote=True)}" download>Download raw snapshot</a></p>'
        body += paragraph("Original source:", source["original_path"])
        body += paragraph("Snapshot SHA-256:", source["sha256"])
        body += '<p>Line numbers refer to the retained excerpt used in this analysis.</p><div class="log">'
        for number, line in enumerate(evidence[source_id].splitlines(), 1):
            body += (f'<div class="line" id="L{number}" data-number="{number}">'
                     f'<a class="number" href="#L{number}">{number}</a><code>{escape(line)}</code></div>')
        body += '</div>'
        pages[f'logs/{source_id}.html'] = page(name, body, log=True)
    return pages


def write_html_bundle(output: Path, findings: dict, manifest: dict) -> None:
    evidence = {source["id"]: (output / source["snapshot"]).read_text()
                for source in manifest["sources"]}
    for name, content in html_bundle(findings, manifest, evidence).items():
        path = output / name
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(0o600)
