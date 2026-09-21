# One-command TMO reports

Status: implemented in 0.4.0. Run on an SDF host with access to the shared TMO
logs, configured OpenCode executable, and model provider credentials.
After installing the package and activating its environment:

```bash
daq-agent report --hutch tmo --last 2d
```

This captures a rolling **48 elapsed hours**, ending when the command starts.
`--last 48h` is equivalent. It is not the previous two calendar dates. For a
fixed window, use `--from 2026-09-19 --to 2026-09-21` instead: dates are local
midnights in the hutch timezone, with inclusive start and exclusive end.

The installed package contains a TMO profile, so the command works from any
working directory. It selects the shared LCLS OpenCode/provider configuration,
Seshu's pinned `psana-daq` and `psana-daq-logs` skills, and the shared log root
`/sdf/home/t/tmoopr/daq/logs`. It verifies the pinned skill cache and fetches that
exact revision if absent; it never follows the branch tip. No interactive model
selection is needed. Use `--model provider/model` to override the profile.

## What Python and skills do

1. Python resolves the window once, discovers candidate launch groups across
   `YYYY/MM` directories, and reads bounded log file prefixes.
2. Python extracts partition and release headers, hashes each captured prefix,
   counts overlapping message patterns, and prepares bounded excerpts with
   original line mappings. It keeps launch and partition identities separate.
3. One restricted OpenCode analysis runs per discovered partition, with the
   packaged log-triage skill and the two pinned upstream skills. The model can
   read supplied evidence and skill references. It cannot access the source log
   directory, SSH, shell commands, DAQ controls, or Grafana.
4. The existing analyzer checks returned JSON and citation locations, then saves
   draft findings, Markdown, portable HTML, and runtime evidence records.

The collector is application Python in `collectors/session_logs.py`;
`batch_report.py` coordinates collection and analyses. Skills provide diagnostic
interpretation rather than filesystem discovery or permissions. This command
creates AI drafts. It does **not** reproduce a separate human/source-reviewed
summary or establish incident causes automatically.

## Outputs and viewing

The command prints a new batch directory under
`~/daq/agent-logs/tmo/YYYY/MM/<unique-run>-report/`:

```text
batch.json                 # window, per-partition status and output paths
inputs/collection.json     # source inventory, hashes, headers and exact counts
inputs/partition-0/*.log   # bounded counts and original-line contexts
partition-0/               # normal analysis artifacts and report.html/report.md
partition-6/               # separate report if this partition was discovered
```

`daq-agent view --hutch tmo` finds the latest valid completed partition report,
including reports in these batch directories. Supply a printed partition output
path to view a different one. The viewer still displays one partition at a time.
Partition 0 is analyzed last when present. If an analysis fails, the batch exits
nonzero and records failure; completed reports from other partitions are retained.
Prepared-only and failed runs are not selected by the viewer.

## Options

```bash
# Capture inputs and skills without a model call (first use can fetch pinned skills).
daq-agent report --hutch tmo --last 2d --prepare-only

# Also disable upstream fetching/loading for an offline collection check.
daq-agent report --hutch tmo --last 2d --prepare-only --local-skills-only

# Limit analysis to partition 0. No candidate logs is an error, not a clean bill of health.
daq-agent report --hutch tmo --last 2d --partition 0

# Override packaged defaults; configuration hutch must match --hutch.
daq-agent report --hutch tmo --last 2d --config /path/to/tmo.toml
```

`--partition` is repeatable. By default all discovered header partitions are
analyzed independently, even though the profile's supplied-log default is 0.
`--log-root` overrides the shared root; `--output` selects a new batch directory.
`--provider-config`, `--opencode`, `--model`, and `--skills-cache` override their
normal defaults. The model timeout defaults to 600 seconds **per partition**;
`--timeout` may reduce it. Model calls are sequential and can take several minutes.

## Coverage and bounds

Discovery selects launches before the end, where either the assumed local launch
time or a member file's modification time is at/after the start. It includes old
carry-in groups. File mtime is a heuristic, not proof of operation or event timing.
Bare timestamps are classified conditionally using the hutch timezone; ambiguous
clock-change timestamps and untimed messages cannot be assigned to the window.
Explicit-offset timestamps are classified directly. Counts include separate
inside, outside, conditional, and untimed categories, rather than quietly dropping
carry-in context.

The collector scans complete byte prefixes captured at initial file size, not an
atomic snapshot of the DAQ. It retains hashes and selected context; full original
logs remain at their original locations and may later change. Missing/deleted or
differently named files are outside coverage. Basic sensitive-field patterns are
masked and long context lines are marked when clipped; this is not a guarantee
that arbitrary credentials can be detected. Generated artifacts remain private
and outside the repository, and excerpts go to the configured model service.

Limits: window at most 7 days; discovery at most 20,000 entries; at most 2,000
candidate logs, 32 MiB per file and 512 MiB total; at most six selected launches
per partition. Unknown partition headers, candidate symlinks, `.zst` candidates,
invalid UTF-8, and oversized scans fail explicitly. Use a narrower window or
prepare scoped decompressed excerpts for `analyze-logs`. A partition filter
limits analysis, but candidate file scanning and its bounds still apply.

Each partition supplies a scope summary plus one document per launch, with at
most 8 files, 64 KiB/file and 256 KiB total. Counts cover scanned prefixes; the
model sees selected contexts, not every matching message. Sampling keeps up to
four component/message signatures per category/time bucket, prioritizes error
contexts, and marks additional omissions. Tracebacks retain up to 64 lines to
include their exception terminator where possible. Repeated messages and mirrored
component logs are not independent incidents. Time uncertainty, sampling gaps,
missing Grafana evidence, and required human review remain explicit.
