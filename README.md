# DAQ Agent

Experimental assistance for LCLS DAQ and AMI operations. The first milestone is
an evidence-backed TMO robustness report covering an explicit historical window,
for review by the hutch robustness monitor and the DAQ group.

**Status: runnable log-analysis prototype.** Configuration inspection, report
planning, and OpenCode analysis of explicitly supplied log excerpts work.
`analyze-logs` produces cited draft findings and a Markdown report. Automatic DAQ
log discovery, Grafana queries, interactive diagnosis, and continuous monitoring
are not implemented. Model execution is explicit; `--prepare-only` makes no API calls.

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
pins Seshu's DAQ routing/log skills. `sync-skills` needs Git and HTTPS access;
analysis then uses the verified cache without fetching updates. For a packaged-skill
example without upstream access, pass `--local-skills-only` explicitly.

The TMO configuration supplies the shared LCLS provider and executable paths.
Override them with `--provider-config` and `--opencode` when needed. Output defaults
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
- [Real TMO log analysis](docs/workflows/tmo-logs.md)
- [Viewing reports](docs/viewing-reports.md)
- [Skills integration](docs/skills-integration.md)
- [CLI and first reporting milestone](docs/proposals/001-reporting-mvp.md)
- [Future live troubleshooting](docs/proposals/002-live-troubleshooting.md)
- [Testing and agent evaluation](docs/evaluation.md)
- [Deployment and credentials](docs/deployment.md)

Maintainer: Mona Uervirojnangkoorn (@monarin). Initial scope: TMO. The design is
intended to support other hutches through configuration and shared diagnostics.
