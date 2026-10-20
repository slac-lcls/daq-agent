# Standalone Claude and Codex report investigations

Status: proposed, 2026-10-20. No commands or skill installation described below
have been implemented by this proposal.

## Intended experience

Start ordinary centralized `claude` or `codex` from any working directory and ask:
“Use the DAQ report investigation skill to inspect the latest completed TMO
report and investigate its findings.” No daq-agent chat or task transfer is
required first. The agent identifies the selected report and its time window,
reads retained evidence and diagnostic skills, and can use personal skills such
as `daq-troubleshoot` and `psana` when relevant.

Keep one interactive Claude installation on SDF: the existing central LCLS
wrapper. Use each native agent's own session history and resume mechanism.
DAQ Agent supplies report discovery, verified evidence and note validation.
It does not become another Claude/Codex process supervisor.

## Current state and installation gap

The SDF wrapper sets `CLAUDE_CONFIG_DIR=~/.claude-lcls` and executes the shared
binary. Inspection on 2026-10-20 found central skills in that configuration's
`skills/` directory, while personal `daq-troubleshoot` and `psana` links are in
`~/.claude/skills` and `~/.codex/skills`, backed by `~/agent-skills`.
The personal sync script already accepts `AGENT_SKILLS_TARGETS`; its defaults
do not include the central Claude configuration.

Current [OpenAI skill documentation](https://learn.chatgpt.com/docs/build-skills)
lists `~/.agents/skills` for user discovery and supports symlinked skill folders.
That directory is absent on this SDF account. Preserve the existing `.codex`
links for the installed environment and verify discovery in the actual native
CLI before adding the documented target. Do not assume that the CLI and this
editor session use identical discovery rules.

Proposed installation: extend the personal sync targets to include the effective
central Claude skill directory and the verified native Codex directory. Keep
`~/agent-skills` as the single personal source. Inventory name collisions first;
never overwrite central skills, plugin skills, or unrelated existing paths.
Test discovery after a central installer refresh as well as a fresh agent start.
No credentials or central configuration migration is needed.

## Ownership and skill composition

Create one agent-neutral personal entry skill, `daq-report-investigation`, in
`~/agent-skills`. It calls the model-free report interface and reads the
application's workflow documentation. It contains no copied upstream diagnostic
content. Application contracts and tests remain in this repository.

For a selected report, expose its retained upstream router, diagnostic leaves
and supporting references using their verified hashes and exact revision.
Do not replace these with a current branch, the current installed profile, or a
similarly named personal skill. Old reports keep their old skill inventory;
known-only reports may legitimately have no retained upstream suite.

Reuse application reporting concepts through the entry skill and verified
inspection output. Do not globally install `log-triage`, `report-chat`, or
`task-transfer` unchanged: they assume application-specific schemas, tools and
permissions that an ordinary native session does not provide.

Personal skills remain available as supplementary guidance. Record the paths,
repository revisions when available, content hashes and dirty status of skills
actually used in a saved investigation. Personal guidance must not silently
change the identity of the report's pinned diagnostic suite. A baseline replay
uses the pinned report suite alone; a run using additional personal skills is
labelled a separate comparison condition.

## Model-free report interface

Proposed CLI contracts:

```bash
daq-agent reports list --hutch tmo --limit 10 --json
daq-agent reports inspect /absolute/path/to/report --json
```

Both use the existing viewer root preference, with `--root` as an explicit
override, and work outside the source checkout. No model, provider credential,
live log scan, service query or skill fetch is needed.

`list` returns a versioned JSON object with completed reports, absolute paths,
hutch, window, completion time and application version. Sort by completion time
using the existing legacy fallback. Exclude internal batches and prepared/failed
runs. Bound traversal and return a truncation indicator and validation failures;
an incomplete scan must not silently claim to have found the globally latest
report. Reuse the existing report loader and integrity rules.

`inspect` verifies the chosen report, evidence and retained skills before
returning a versioned inventory: report fingerprint, F IDs, summary/findings,
limitations, source hashes and retained line counts, known-condition metadata,
coverage, runtime/model provenance, and skill paths/hashes. Never return
credentials or unrelated runtime transcripts. Large text remains in retained
files with explicit limits rather than an unbounded JSON dump.

The native agent announces the report path, hutch and exact window before
investigation. Resolve “latest” once and bind the investigation to the resulting
fingerprint. A new report appearing later must not move the active session.
Disambiguate requests that conflict with the selected hutch/window. An unavailable
or corrupt artifact is missing evidence, not a clean report.

## Investigation workspace and notes

Propose a model-free preparation operation accepting a report directly, without
creating a dummy chat. It creates a private investigation directory under the
configured report root, separate from completed reports and chats. Retain:

- Report fingerprint and scope, selected F IDs and optional goal.
- Verified source/skill inventory with hashes and explicit size limits.
- Known-condition appendices derived from saved metadata, including original
  source identity and the representative-sample limitation.
- A context document readable by either agent and a separate draft note.

Reuse the existing appendix, identity and integrity helpers. Do not manufacture
ephemeral HTTP URLs as durable citations. Use retained source IDs, hashes,
line ranges and artifact paths; `daq-agent view REPORT` opens browser evidence
when needed. The viewer and SSH tunnel must remain running for its URLs to work.

Native agents may draft notes in the investigation workspace. A proposed
explicit note-import operation validates schema, fixed report identity, hashes
and citation bounds before writing an `unreviewed` investigation note under
`<report-root>/notes/<hutch>/`. The tool chooses the destination and provenance;
the model cannot override them. Failed imports preserve the draft and explain
the failure. Import does not alter findings, complete a human review, or publish
to an issue tracker/shared store.

Native sessions do not fabricate daq-agent chat IDs, accepted turns or task
transfer IDs. If supporting them requires a new note-origin schema, version it
and retain compatibility with existing notes. Record runtime/model as reported
by the native session, or explicitly unknown; do not infer a resolved model
from an alias.

## Runtime boundaries

Existing report/chat/task-transfer sessions keep their bounded application
tools and retained skill rules. The native session uses its configured
permissions and may have broader tools and personal skills. A Markdown skill is
not an enforcement boundary. The deterministic report/inspection/note tools
must remain bounded regardless of which agent calls them.

Investigating saved reports grants no production DAQ operations. A request for
additional live evidence uses the applicable operational skill and separately
authorized tools. Record newly collected evidence separately, with scope and
time, without retroactively adding it to the original report. No automatic
shared publication or cross-runtime transcript import is included.

## Implementation order and acceptance

1. Implement and test `reports list/inspect`: latest selection, legacy reports,
   corrupt snapshots/skills, bounded scans, batches, custom roots and execution
   outside the checkout. Verify wheel resources.
2. Add direct-report workspace preparation and validated native-note origin.
   Reuse known-condition appendices; test no source mutation, tamper rejection
   and old note compatibility.
3. Create the personal entry skill and update symlink targets with collision
   handling. Verify actual native discovery of that skill, `daq-troubleshoot`
   and `psana` in both central Claude and Codex, from outside this repository.
4. Run offline workflow checks, then separately scheduled model comparisons
   using the [comparison baseline](../evaluation/report-baseline.md). Test
   native restart/resume and note import. Record client versions and tool
   availability; do not compare finding counts or wording as equivalence.

Acceptance requires a user starting either agent independently to locate the
same selected report, retrieve cited evidence including known conditions, use
the pinned suite alongside explicitly identified personal skills, resume the
same investigation, and save a validated separate note. Original report files
must remain byte-identical. Browser access and semantic diagnosis quality are
separate checks.

The initial implementation need not add a launcher, MCP server, model selector,
scheduled service, or new production access capability.
