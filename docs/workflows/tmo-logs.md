# Analyze supplied real TMO log excerpts

Status: the application supports supplied-log analysis with pinned DAQ guidance.
For automatic collection use [one-command reporting](rolling-report.md).
This page describes manual selection and excerpt preparation. This does
not start, stop, configure, or otherwise control the DAQ.

## Prepare the application

```bash
cd /sdf/home/m/monarin/daq-agent
source .venv/bin/activate
python -m pip install -e .
daq-agent sync-skills --config config/hutches/tmo.toml
```

The TMO configuration selects the SLAC provider and pinned
`psana-daq`/`psana-daq-logs` skills. Platform values in headers are retained as
source metadata. The report covers the hutch and supplied time window. Skill synchronization does not require model
credentials. A real analysis uses the configured model service.

## Select evidence from one launch

On SDF, check whether the operator log directory is readable:

```bash
ls /sdf/home/t/tmoopr/daq/logs/YYYY/MM/
```

Files from one launch share a `DD_HH:MM:SS_` prefix. Select the control log, relevant
TEB log, and a participant/MEB log from that same prefix. Preserve header fields
such as component ID, platform, host, job ID, and `TESTRELDIR`/release. Readable
shared files do not require SSH to the hutch, and the model never needs hutch shell
access for this workflow.

Supply UTF-8 excerpts, each at most 64 KiB. Each model session handles up to
8 files and 256 KiB; larger sets are batched automatically, up to 128 files,
4 MiB and 16 sessions per report. For larger individual logs, prepare explicit
excerpts in a private directory outside the repository.
Record original paths, retained original line ranges, collection time, launch
prefix, and any omissions/redactions. Keep useful header and surrounding context.
Never concatenate separated ranges without marking the gap. A head/tail sample
is a smoke test, not a complete incident search or operating-window survey.

`report --log` does not automatically truncate, decompress, redact, or time-filter
its supplied inputs. Review selected inputs for credentials before sending them to the configured
service. Rotated `.zst` files need explicit decompression and scoping first.
Citations refer to the retained excerpt's line numbers; preserve the original-line
mapping in its text if it is needed for further investigation.

## Run the analysis

Replace the dates and paths with the chosen launch and excerpts. Supply an explicit
end time; a launch timestamp alone does not timestamp all component messages.

```bash
daq-agent report --hutch tmo --config config/hutches/tmo.toml \
  --from 2026-09-20T19:05:09-07:00 --to 2026-09-21T12:00:00-07:00 \
  --log /path/to/private/control-excerpt.log \
  --log /path/to/private/teb0-excerpt.log \
  --log /path/to/private/meb1-excerpt.log \
  --timeout 300

daq-agent view --hutch tmo
```

Omit `--synthetic` for real logs. Use `--prepare-only` to inspect retained evidence,
skills, and prompt before a model call. The default output is a unique private run
under `~/daq/agent-logs/tmo/YYYY/MM/`. An explicit `--output` must name a new directory.

Review `manifest.json` (or each `batches/NNN/manifest.json` for a batched report)
for the pinned skill revision and `runtime_audit.skills_loaded`;
it must list `log-triage`, `psana-daq`, and `psana-daq-logs`. The browser viewer can
show the draft and cited evidence. Findings must distinguish observed messages
from cause hypotheses and acknowledge missing Grafana/live-state evidence.
