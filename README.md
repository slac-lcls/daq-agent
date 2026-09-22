# DAQ Agent

Experimental assistance for LCLS DAQ and AMI operations. The first milestone is
an evidence-backed TMO robustness report covering an explicit historical window,
for review by the hutch robustness monitor and the DAQ group.

**Status: runnable reporting prototype.** `report` collects recent shared TMO
logs and runs OpenCode with pinned DAQ skills to produce one report for the
hutch and time window. Optional `report --log` accepts supplied excerpts.
Reports contain cited findings, Markdown, and HTML. `chat` answers follow-up
questions about a saved report. Grafana queries, live diagnosis, and continuous
monitoring remain unimplemented. `--prepare-only` makes no model calls.

## Quick start

Use Python 3.11 or newer in a virtual environment (SDF's default `python3` may be
older; use the existing project `.venv` or an appropriate Python installation):

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
daq-agent --help
daq-agent config --config config/hutches/tmo.toml
daq-agent plan-report --config config/hutches/tmo.toml \
  --from 2026-09-18 --to 2026-09-20
```

The last command emits a JSON plan, **not a report**. Dates represent midnight
in the configuration's timezone; the start is inclusive and the end exclusive.
Timestamps must include an explicit UTC offset. Planning does not contact the
model or confirm access to evidence sources.

The sample model is a configured LCLS gateway model, not a tested entitlement.
Credentials are supplied by deployment configuration and never stored here.

## Generate a TMO report

On SDF, with the installed environment activated:

```bash
daq-agent report --hutch tmo --last 2d
```

This collects candidate logs for the last 48 elapsed hours, synchronizes the exact
pinned skills if needed, and generates one draft for the entire hutch/window.
Larger inputs are split automatically into bounded OpenCode sessions, then their
findings are combined with citations preserved. The
packaged TMO profile works from any directory; no interactive model selection is
needed. To use the existing home installation without activating it:

```bash
~/daq-agent/.venv/bin/daq-agent report --hutch tmo --last 2d
```

Reports are saved under `~/daq/agent-logs/tmo/YYYY/MM/<unique-run>-report/`.
Use `daq-agent view --hutch tmo` to open the latest completed hutch report.
Add `--prepare-only` to collect inputs without calling the model. These are
AI drafts requiring review, not automatically verified incident reports. See
[one-command reporting](docs/workflows/rolling-report.md) for collection bounds,
time assumptions and override options.

Platform values remain source metadata and do not split reports. The earlier
`analyze-logs` subcommand is replaced by optional `report --log` input selection;
the normal command above collects logs automatically.

## Run the example workflow

With the package installed and the virtual environment activated, synchronize
the pinned upstream skills, then prepare
the bundled **synthetic** Configure-failure example without contacting a model:

```bash
daq-agent sync-skills --config config/hutches/tmo.toml
bash examples/log-analysis/run.sh --prepare-only
```

To launch OpenCode on SDF and produce actual model findings from those same
synthetic excerpts:

```bash
bash examples/log-analysis/run.sh
```

The TMO configuration supplies the shared LCLS provider/executable paths and
pins all six DAQ diagnostic skills from the temporary PR #131 revision.
`sync-skills` needs Git and HTTPS access;
reporting verifies or synchronizes that exact revision before analysis. For an
example without upstream access, pass `--local-skills-only` explicitly.

Override the provider/executable defaults with `--provider-config` and `--opencode` when needed. Output defaults
to `$HOME/daq/agent-logs/<hutch>/YYYY/MM/<unique-run-directory>` for the user running the
command, using the launch date in the configured timezone. Missing directories
are created and the resulting path is printed. Set `output_root` in the config
to change the base directory, or `--output` to choose an exact new run directory.

The model run uses the configured API service
and may incur usage charges. It writes `report.md`, `findings.json`, and evidence/
runtime artifacts in a private directory. Grafana is explicitly marked **not
queried**. Do not commit or publish output from real log excerpts.

See [the workflow walkthrough](docs/workflows/log-analysis.md) for what Python,
the skill, and the example script each do, and how to supply your own excerpts.

## View reports

Start the viewer for your most recent completed report:

```bash
daq-agent view
```

It defaults to port 8765 and searches `~/daq/agent-logs` across hutches. It prints
copy-paste instructions for a laptop SSH tunnel and the browser URL. For a laptop
SSH alias that already handles your jump host, save it once:

```bash
daq-agent view --ssh-host sdfiana --save-settings
```

Use `--hutch tmo` to select a hutch, or supply a run directory explicitly.
Citations open line-numbered logs in a new tab and highlight the cited range.
New analyses also produce portable HTML for offline viewing. See
[viewing reports](docs/viewing-reports.md) for NoMachine, SSH, personal settings,
and access details. Viewing an existing report makes no model calls.

## Chat with a report

```bash
daq-agent chat --hutch tmo
```

Chat selects the latest completed report and displays its window. Ask a question
such as "Explain finding 3 and its evidence." Use `/findings`, `/sources`, `/report`
and `/exit` for local navigation. `/note TEXT` or `Save this note: TEXT` saves a
local note; `/note` saves the last answer with citations. `/notes` retrieves notes. `daq-agent chat /path/to/report` selects a
specific report; `daq-agent chat --resume CHAT_ID` continues a saved conversation.

Chat reuses saved evidence and the report's pinned diagnostic skills without
rescanning logs. Answers use the configured model service and retain citations.
Conversations stay attached to their original report and are saved privately,
separately from it. See [report chat](docs/workflows/report-chat.md) for context
limits, model overrides and provenance. [Local notes](docs/workflows/local-notes.md)
are saved under `~/daq/agent-logs/notes/<hutch>/` and can inform later chats.

## Development

```bash
python -m unittest discover -s tests -v
```

Keep architecture, proposals, decisions, and operating guidance in `docs/`.
Store operational evidence, reports, and session history outside the repository.
Only reviewed synthetic or sanitized fixtures belong in `evals/`.

## Documentation

- [Documentation index](docs/README.md)
- [Software architecture](docs/architecture.md)
- [Runnable log-analysis workflow](docs/workflows/log-analysis.md)
- [One-command TMO reports](docs/workflows/rolling-report.md)
- [Real TMO log analysis](docs/workflows/tmo-logs.md)
- [Viewing reports](docs/viewing-reports.md)
- [Chat with a report](docs/workflows/report-chat.md)
- [Local investigation notes](docs/workflows/local-notes.md)
- [Skills integration](docs/skills-integration.md)
- [CLI and first reporting milestone](docs/proposals/001-reporting-mvp.md)
- [Future live troubleshooting](docs/proposals/002-live-troubleshooting.md)
- [Testing and agent evaluation](docs/evaluation.md)
- [Deployment and credentials](docs/deployment.md)

Maintainer: Mona Uervirojnangkoorn (@monarin). Initial scope: TMO. The design is
intended to support other hutches through configuration and shared diagnostics.
