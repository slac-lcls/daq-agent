# DAQ Agent

Experimental assistance for LCLS DAQ and AMI operations. The first milestone is
an evidence-backed TMO robustness report covering an explicit historical window,
for review by the hutch robustness monitor and the DAQ group.

**Status: project scaffold.** Configuration inspection and report planning work.
Evidence collection, model invocation, report generation, interactive diagnosis,
and continuous monitoring are not implemented yet. This version makes no DAQ,
Grafana, or AI API calls.

## Quick start

Use Python 3.11 or newer in a virtual environment:

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
- [Skills integration](docs/skills-integration.md)
- [CLI and first reporting milestone](docs/proposals/001-reporting-mvp.md)
- [Future live troubleshooting](docs/proposals/002-live-troubleshooting.md)
- [Testing and agent evaluation](docs/evaluation.md)
- [Deployment and credentials](docs/deployment.md)

Maintainer: Mona Uervirojnangkoorn (@monarin). Initial scope: TMO. The design is
intended to support other hutches through configuration and shared diagnostics.
