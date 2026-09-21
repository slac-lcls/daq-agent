# Pinned DAQ skill integration

Status: implemented for automatic and supplied-log reporting. `report` loads the packaged
`log-triage` reporting instructions and the selected upstream DAQ skills. It
verifies or synchronizes the exact pinned revision first; it never follows a branch tip.

## Temporary upstream source

The TMO configuration uses the accepted revision of
[LCLS2 PR #125](https://github.com/slac-lcls/lcls2/pull/125):

```toml
[daq_skills]
repository = "https://github.com/slac-lcls/lcls2"
branch = "features/psana-daq-monitor"
revision = "198b6aa95229ef0e4ac5023c2a0d2e611124d46e"
directory = "psana/psana/skills"
skills = ["psana-daq", "psana-daq-logs"]
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
supporting references, under `$XDG_CACHE_HOME/daq-agent/skills/<source-hash>`
(default `~/.cache/daq-agent/skills/`). It does not install or import psana.

It validates names/frontmatter, regular files, file counts, and size limits.
Symlinks and submodules are rejected. Each retained file has a SHA-256 hash and
byte count. Repeated synchronization verifies and reuses the same cache; it does
not follow the branch or refresh content silently. Change the configured revision
and synchronize to adopt a new revision. A damaged cache fails verification; use
an alternate `--skills-cache /path/to/cache` or remove that damaged cache entry and
synchronize again. The override must be passed to both sync and analysis.

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
| `psana-daq-control` | Not selected; live DAQ state/control tools unavailable |
| `psana-daq-monitor` | Not selected; Grafana tools/access unavailable |
| `psana-configdb` | Not selected; ConfigDB tools unavailable |
| `robustness-report` | Broader reporting workflow remains future work |

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

Add live tools individually with explicit scope and read-only boundaries before
enabling the corresponding skills. Historical tasks must continue to supply
hutch and an explicit window, with run/launch, platform and release metadata
where known. Platform is not a reporting boundary.
The source configuration can later point at a merged branch or a dedicated skill
repository. AMI's package-discovery approach remains another future source adapter.

`daq-agent report --hutch tmo --last 2d` performs pinned synchronization before
collection and analysis, reusing a verified cache when available. The collector
is application code; it does not execute upstream scripts or give the model
access to the shared source log tree. One OpenCode analysis loads and audits
the selected skills across all prepared hutch/window evidence.
