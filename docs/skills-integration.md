# Pinned DAQ skill integration

Status: implemented for automatic and supplied-log reporting. `report` loads the packaged
`log-triage` reporting instructions and the selected upstream DAQ skills. It
verifies or synchronizes the exact pinned revision first; it never follows a branch tip.

## Temporary upstream source

The TMO configuration temporarily uses the corrected revision from
[LCLS2 PR #131](https://github.com/slac-lcls/lcls2/pull/131), pending its merge into
`features/psana-daq-monitor`:

```toml
[daq_skills]
repository = "https://github.com/slac-lcls/lcls2"
branch = "codex/psana-daq-skills-review"
revision = "606038fed893ce788f1b865418ae6a569f66dc1d"
directory = "psana/psana/skills"
skills = [
  "psana-daq",
  "psana-daq-logs",
  "psana-daq-control",
  "psana-daq-monitor",
  "psana-configdb",
  "psana-daq-snapshot",
]
```

The branch identifies ongoing development; the full commit SHA selects the actual
bytes. Moving the skills later requires updating this source configuration, not
rewriting the workflow. GitHub Issues are not a supported skill source yet; they
could later provide separately captured troubleshooting knowledge.

## Synchronize, then analyze

From the repository, with the current package installed:

```bash
daq-agent sync-skills --config config/hutches/tmo.toml
bash examples/log-analysis/run.sh --prepare-only
bash examples/log-analysis/run.sh
daq-agent view
```

`sync-skills` requires Git and HTTPS access to the source repository. It fetches
the pinned commit into a temporary Git object store without checking out or
executing upstream code. It retains complete selected directories, including
supporting references, plus the optional suite-level `README.md`, under
`$XDG_CACHE_HOME/daq-agent/skills/<source-hash>`
(default `~/.cache/daq-agent/skills/`). It does not install or import psana.

It validates names/frontmatter, regular files, file counts, and size limits.
Symlinks and submodules are rejected. Each retained file has a SHA-256 hash and
byte count. Repeated synchronization verifies and reuses the same cache; it does
not follow the branch or refresh content silently. Change the configured revision
and synchronize to adopt a new revision. A damaged cache fails verification; use
an alternate `--skills-cache /path/to/cache` or remove that damaged cache entry and
synchronize again. Pass the same override when explicitly syncing and later reporting.

Analysis verifies the cache and copies its files into the private output's
`upstream-skills/`, then assembles the session's `.opencode/skills/`. The report
manifest records source repository, branch, commit, selected names, and all file
hashes. Its runtime audit must show actual loads of all selected skills as well
as reads of every supplied evidence snapshot. Retained skills allow inspection of
what was used even if the upstream branch disappears.

For an explicitly local-only run, pass `--local-skills-only`. The manifest records
that choice; there is no silent fallback when configured skills are missing.
Credential-free CI uses this option with synthetic fixtures, while dedicated
unit tests exercise synchronization against a local Git fixture.

## Workflow scope and tool availability

| Skill | Current use |
| --- | --- |
| `log-triage` | Packaged report contract, evidence handling, uncertainty |
| `psana-daq` | Pinned DAQ routing and release/session interpretation guidance |
| `psana-daq-logs` | Pinned log-header, component, severity, and session guidance |
| `psana-daq-control` | State/transition interpretation from retained evidence; live tools unavailable |
| `psana-daq-monitor` | Metrics interpretation and coverage guidance; Grafana adapter unavailable |
| `psana-configdb` | Configuration evidence and candidate/applied distinction; service adapter unavailable |
| `psana-daq-snapshot` | Composed diagnosis over the supplied scope; application JSON contract takes precedence |

Upstream skills describe live diagnostics, including commands, sibling skills,
and source-tree lookups. This application's task and primary-agent instructions
explicitly limit their use to interpreting supplied snapshots. Current DAQ state
cannot establish historical state. Untimestamped component lines must not be
assigned an event time merely from a launch filename. Skill examples are guidance,
not evidence about the selected launch.

OpenCode permits only selected skill loads, evidence reads, and reads of selected
skill reference files. Shell, edits, SSH, live state/control, Grafana, ConfigDB,
other skills, and delegation remain denied. Skills do not grant access. An
unexpected completed tool call invalidates the report. The session has at most
12 model steps with upstream skills (8 in local-only mode), plus the configured
wall-clock/output limits. These are application permissions, not an OS sandbox.

## Real TMO logs

See [the TMO walkthrough](workflows/tmo-logs.md) for scoped input preparation and
invocation. [Hutch-wide reporting](workflows/rolling-report.md) collects shared
log sessions automatically. Continuous monitoring and DAQ operations remain
future work.

## Future source and capability changes

Update the pin through a normal code review, inspect upstream instruction and
support-file changes, and replay evaluation cases. Preserve fixes upstream rather
than maintaining divergent local copies. A skill's presence is not proof that
its tools, host routes, or credentials work.

Add service adapters individually with explicit scope and read-only boundaries
before enabling live queries. Loading their guidance does not enable a service.
Historical tasks must continue to supply
hutch and an explicit window, with run/launch, platform and release metadata
where known. Platform is not a reporting boundary.
The source configuration can later point at a merged branch or a dedicated skill
repository. AMI's package-discovery approach remains another future source adapter.

`daq-agent report --hutch tmo --last 2d` performs pinned synchronization before
collection and analysis, reusing a verified cache when available. The collector
is application code; it does not execute upstream scripts or give the model
access to the shared source log tree. Each bounded OpenCode session loads and
audits the selected skills and its assigned evidence. Larger reports retain skill
snapshots and runtime audits in each `batches/NNN/` directory; the root manifest
maps those sessions to the combined report sources. Step and timeout limits apply
per session, with at most 16 sessions per report.


`chat` verifies and loads the diagnostic skills retained with its selected report,
including consistent copies across report batches. It adds the packaged
`report-chat` skill and audits every required skill load per question. The current
configuration selects provider/model access; it does not silently replace a saved
report's diagnostic skills. See [report chat](workflows/report-chat.md).


The application-owned `report-chat` skill also describes local note commands and
historical-note interpretation. Note files are stored by application code outside
the repository; model output cannot write or publish them. This does not change
the upstream DAQ skills. See [local notes](workflows/local-notes.md).


## Temporary PR #131 adoption

All six selected skills and their references are retained and verified for new
reports; existing reports and resumed chats retain their original skill bytes.
The suite is larger than the old chat skill budget: the skill-file limit is now
192 KiB, while the overall per-question input limit remains 384 KiB. Each question
still loads/audits all selected skills, so this change does not claim lower chat
latency. No live service or paid model call is part of deterministic validation.

The snapshot Markdown template is diagnostic guidance, not a parser input or a
replacement for application findings, chat answers or private notes. Missing
services must appear in limitations. No Grafana, DAQ control, ConfigDB or GitHub
history adapter is added here. `psana-daq-history` is absent, no issue schema is
supplied, and historical-key retrieval remains unsupported. Upstream helper
scripts are never executed by synchronization or by the model runtime.

After #131 merges, verify its resulting commit on `features/psana-daq-monitor`,
review any additional changes, and update both the checkout configuration and
packaged profile to that exact SHA. Do not switch to a moving branch tip.
