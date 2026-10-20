# Known conditions excluded from model analysis

Status: implemented. The packaged TMO profile enables three deterministic rules.
They apply to both OpenCode and Claude reports, before evidence selection and
batching. Other profiles and custom configurations must opt in explicitly.

| Rule ID | Required evidence |
| --- | --- |
| `daq-teardown-double-free` | `free(): double free detected in tcache N` or `double free or corruption`, on or within five lines after explicit TERM/INT shutdown or Slurm signal cancellation |
| `pyxpm-connection-reset` | A pyxpm component emitting `pvxs.tcp.io` socket error 104, `Connection reset by peer` |
| `ami-recovered-connection` | An AMI component emitting `Error connecting myTrFd socket (will retry): Connection refused`, followed within twenty lines by `Connected to XtcMonitor server`, without another matching retry or shutdown in between |

These rules record known conditions; they do not establish healthy operation.
The pyXPM reset rule makes no recovery claim. The AMI rule establishes transport
reconnection only, not restored data flow. Opening queues or saying “Connecting”
does not establish recovery. Double-free without nearby shutdown evidence and
other pyXPM failures, including timing-lock errors, remain eligible for analysis.

Matched lines are counted in a separate **Known conditions — no model analysis**
section in Markdown and HTML, with up to four representative examples per rule.
Examples retain original paths, line numbers, component, partition, launch,
release and captured-prefix hashes. Counts distinguish inside-window,
outside-window and untimed matches; they count lines, not independent incidents.
The manifest records rule IDs, rule version, criteria and counts. Automatically
collected reports also retain original and remaining pattern counts per file in
`collection/collection.json`.

Known lines are removed from model excerpts, including neighboring context for
other errors. The model receives only the remaining evidence. When all detected
error signatures are known conditions, the report completes deterministically
with zero model sessions, no runtime/credential requirement, and no skill fetch.
Missing evidence remains a limitation; this is not a clean-health assessment.
Reports with no known matches follow the usual analysis path.

Explicit `--log` inputs are filtered too, with line positions preserved. Original
paths, hashes, headers and counts are retained in `known-condition-inputs.json`;
the report evidence contains filtered snapshots. Supplied excerpts are treated
conservatively: any nonempty, nonheader line outside the known match and its
supporting context keeps model analysis enabled.

Configure a subset in the hutch TOML file:

```toml
known_conditions = ["daq-teardown-double-free", "pyxpm-connection-reset", "ami-recovered-connection"]
```

Omit this field or use `[]` to disable filtering. Unsupported or duplicate rule
IDs are rejected. To disable it for one report, add `--no-known-conditions`:

```bash
daq-agent report --hutch tmo --from 2026-09-23 --to 2026-09-25 \
  --runtime claude --no-known-conditions
```

Existing reports are unchanged. This policy governs report generation; an
explicit follow-up chat or task transfer can still start a model session.

Follow-up chat creates private, line-numbered evidence appendices from the
report's saved known-condition counts and representative examples. Each rule
gets a source ID after the original report sources; the original source IDs,
report files, generation statistics and skill provenance are unchanged. This
also works for existing reports and conversations that already retain
`known_conditions` in their manifest.

Appendices preserve the saved rule/version, time buckets, launch/component/
partition/release identity, original line labels and captured-prefix hashes.
They are derived from the saved manifest, not a new log scan or classification.
They contain at most the representative examples originally captured (four per
rule); omitted raw lines cannot be recovered. Each appendix is limited to 64 KiB,
and ordinary chat evidence count/byte limits still apply. Resume compares the
appendix bytes against the bound report; changed files fail verification.

Answers cite appendix line numbers, with `original-line` labels identifying the
captured source locations. Chat citations point to its private `known-conditions/`
files; transfers copy the appendices into their own read-only `evidence/` inventory.
Saved notes retain the corresponding citation path and hash. These appendices
are available only to follow-up investigations; automatic report analysis still
receives filtered inputs, and known-only reports still use zero model sessions.
