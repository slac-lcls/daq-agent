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

With the package installed and the virtual environment activated, first prepare
the bundled **synthetic** Configure-failure example without contacting a model:

```bash
bash examples/log-analysis/run.sh --prepare-only --output artifacts/prepare-example
```

To launch OpenCode on SDF and produce actual model findings from those same
synthetic excerpts:

```bash
bash examples/log-analysis/run.sh \
  --provider-config /sdf/group/lcls/ds/dm/apps/dev/opencode/opencode.json \
  --opencode /sdf/group/lcls/ds/dm/apps/dev/code/.opencode/bin/opencode \
  --output artifacts/model-example
```

The output directory must be new. The model run uses the configured API service
and may incur usage charges. It writes `report.md`, `findings.json`, and evidence/
runtime artifacts in a private directory. Grafana is explicitly marked **not
queried**. Do not commit or publish output from real log excerpts.

See [the workflow walkthrough](docs/workflows/log-analysis.md) for what Python,
the skill, and the example script each do, and how to supply your own excerpts.

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
- [Skills integration](docs/skills-integration.md)
- [CLI and first reporting milestone](docs/proposals/001-reporting-mvp.md)
- [Future live troubleshooting](docs/proposals/002-live-troubleshooting.md)
- [Testing and agent evaluation](docs/evaluation.md)
- [Deployment and credentials](docs/deployment.md)

Maintainer: Mona Uervirojnangkoorn (@monarin). Initial scope: TMO. The design is
intended to support other hutches through configuration and shared diagnostics.
