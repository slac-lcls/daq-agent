# One report for a hutch and time window

Status: implemented in 0.5.0. Run on SDF with access to the shared hutch logs,
configured OpenCode executable, and model provider credentials:

```bash
daq-agent report --hutch tmo --last 2d
```

The command prepares evidence across the candidate DAQ log sessions and produces
**one hutch-wide report**. Platform/partition values remain source metadata; they
do not filter files, split reports, or select separate OpenCode sessions. Missing
platform headers do not exclude a log.

`--last 2d` means 48 elapsed hours ending when the command starts. For two complete
calendar dates, use `--from 2026-09-19 --to 2026-09-21` instead. Dates use the hutch
timezone; timestamps require an explicit offset. The end is exclusive.

The installed TMO profile works from any directory. It selects shared LCLS
OpenCode/provider paths, the pinned `psana-daq` and `psana-daq-logs` skills, and
`/sdf/home/t/tmoopr/daq/logs`. The command verifies the cached skill revision or
fetches that exact SHA if absent. It never follows a branch tip.

## One public reporting command

The earlier `analyze-logs` CLI command has been replaced by `report --log` for
explicit excerpts. Ordinary monitoring needs only the hutch and time window:

```bash
# Normal automatic collection and analysis.
daq-agent report --hutch tmo --last 2d

# Optional supplied excerpts, for a focused investigation or synthetic test.
daq-agent report --hutch tmo --from 2026-09-19 --to 2026-09-21 \
  --log /path/to/control-excerpt.log --log /path/to/participant-excerpt.log

# Collect evidence and retain skills without calling the model.
daq-agent report --hutch tmo --last 2d --prepare-only
```

`--log` bypasses discovery and uses the files exactly as supplied. The internal
Python `analyze_logs()` function remains shared implementation, not a second
operator workflow. `--synthetic` is available only with explicit `--log` inputs.
`--local-skills-only` explicitly disables upstream synchronization/loading.

`--config` overrides the packaged profile; its hutch must match `--hutch`.
`--log-root`, `--output`, `--provider-config`, `--opencode`, `--model`, and
`--skills-cache` override their corresponding defaults. The OpenCode timeout is
600 seconds, reducible with `--timeout`. A legacy `partition` config field is
accepted for compatibility but does not restrict reporting. There is no
`report --partition` option.

## Implementation

1. `reporting.py` resolves one hutch/window scope.
2. `collectors/session_logs.py` discovers candidate log launches, scans captured
   file prefixes, counts patterns, and prepares bounded context with original
   paths and line numbers. Files are associated by their launch prefix; platform
   headers remain in each source record.
3. `log_analysis.py` retains the collection and invokes **one** restricted
   OpenCode session using all prepared evidence documents and the pinned skills.
4. Schema and citation-location checks run before one Markdown/HTML report and
   structured findings are written. Conclusions still require human review.

A launch prefix is a log-session identity, **not a numbered data-taking run**.
A launch can span multiple runs. Explicit run references in retained context
remain evidence, but this implementation does not query an authoritative run
registry or establish complete coverage of every numbered run. Discovery gaps
are recorded as limitations, not treated as healthy operation.

## Output and viewing

The command prints a new private directory under
`~/daq/agent-logs/tmo/YYYY/MM/<unique-run>-report/`:

```text
manifest.json                 # hutch/window scope, provenance, status
collection/collection.json    # captured source inventory, headers, hashes, counts
collection/*.log              # scope and per-launch evidence documents
evidence/log-N.txt            # stable snapshots actually read by OpenCode
findings.json                 # structured draft findings
report.md / report.html       # one report covering the hutch/window
```

`daq-agent view --hutch tmo` opens the latest completed report. An explicit report
path works too. Older per-partition reports remain viewable without modification.
The browser does not expose the private collection inventory or runtime records;
citations open retained evidence snapshots.

Collection failures abort before analysis. Once analysis starts, failures retain
a failed manifest and evidence; no successful report is claimed. Preparation
saves evidence but makes no model call and is not selected by the viewer.

## Coverage and bounds

Discovery includes launches before the end where either the assumed local launch
time or a member file's modification time is at/after the start. Older carry-in
logs provide context. File mtime is a heuristic, not an event timestamp or proof
of operation. Bare timestamps are classified conditionally using the configured
timezone; ambiguous clock-change timestamps and untimed messages remain unassigned.
Explicit-offset timestamps are classified directly.

The scan captures each file's initial byte prefix, not an atomic DAQ snapshot.
Hashes identify those prefixes; retained excerpts remain available even if the
original files change. Deleted, relocated or differently named files are outside
coverage. Basic sensitive-field patterns are masked and clipped lines marked;
arbitrary credentials cannot be reliably detected. Evidence stays outside the
repository and excerpts go to the configured model service.

Limits: at most 7 days, 20,000 discovery entries, 2,000 candidate logs,
32 MiB/file and 512 MiB/collection, with at most seven launch groups in the
hutch/window. Candidate symlinks, `.zst` files, invalid UTF-8, and oversized scans
fail explicitly. Narrow the window or supply scoped/decompressed excerpts with
`report --log`. Larger-window chunking and report synthesis remain future work.

The model receives one scope summary plus per-launch documents within the
existing 8-file, 64 KiB/file, 256 KiB total limits. Counts cover captured prefixes;
the model sees selected contexts, not every message. Sampling and omissions are
explicit; tracebacks retain up to 64 lines. Matching-line and launch counts are
not incident counts, run counts, downtime or lost-event measurements. Grafana
and live-state evidence are unavailable in this workflow.
