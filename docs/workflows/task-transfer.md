# Transfer a report investigation to OpenCode

Status: implemented in 0.9.0. Ordinary `daq-agent chat` still runs bounded,
validated question/answer turns. A task transfer opens a separate persistent
OpenCode investigation with the same report evidence and pinned diagnostic skills.

## Start from chat

```text
/task-transfer Investigate whether F003 explains the transition failure
```

An investigation goal is optional. Without one, the handoff says no new goal
was supplied; OpenCode can ask what to pursue next. Preparing the handoff makes
no model call. In an interactive terminal, the command then launches OpenCode
using the configured provider/model, which can incur normal model usage. Exit
OpenCode to return to daq-agent chat.

To prepare files without launching a model:

```text
/task-transfer --prepare-only Investigate F003
```

A `chat --question '/task-transfer ...'` invocation or noninteractive input also
prepares only. The output prints a command to open the workspace in a terminal:

```bash
daq-agent task-transfer /path/printed/by/the/command
```

Resume its OpenCode conversation later with:

```bash
daq-agent task-transfer /path/printed/by/the/command --resume
```

Each transfer has isolated OpenCode state. `--resume` uses OpenCode's `--continue`
within that state, not the user's unrelated global sessions. It resumes the latest
OpenCode session in this transfer workspace. Starting an additional session inside
OpenCode changes what “latest” means; its session picker can select an older one.
The original daq-agent chat remains separate; OpenCode answers do not automatically
enter its validated history. Repeating `/task-transfer` creates another workspace
and note destination. Concurrent launches of one transfer are locked out.

## Handoff contents

Workspaces are private directories under
`<chat-state>/<conversation-id>/transfers/<transfer-id>/`. They retain:

- `TASK.md`: report identity/window, optional next goal, skills and note instructions.
- `brief.json`: an extractive summary with up to six recent accepted turns within
  16 KiB and matching historical notes; it states how much older history exists.
- `transcript.json`: all accepted turns as of transfer, including their citations
  and limitations. Failed/interrupted turns are excluded.
- `report.json`: all report findings with stable F IDs, summary, limitations and
  evidence source index. Report prose remains interpretation, not independent proof.
- `evidence/`: all retained report snapshots, including sources from later batches.
- `.opencode/skills/`: the exact upstream files retained with the report, including
  references, plus the application `task-transfer` skill. The current config does
  not silently replace a report's skills.
- `note-template.json`: the new note identity, provenance and editable fields.
- `transfer.json`: file hashes, source provenance and non-secret launch settings.
- `runtime/`: private OpenCode state created when the investigation runs.

Preparation verifies the original report and skill integrity. Launch verifies the
copied handoff inventory. No original logs are rescanned. The workspace is bounded
to 12 MiB, with each generated file at most 4 MiB; oversized transfers fail rather
than silently omit history or evidence. Evidence is available for reading as needed;
it is not all inserted into every prompt. Context compaction can still require
rereading source files during a long investigation.

## OpenCode writes the note

The handoff gives OpenCode a unique absolute destination:
`<notes-root>/<hutch>/<transfer-id>.json`. By default this is under
`~/daq/agent-logs/notes/<hutch>/`. It explains the record format and how to write
findings, uncertainty, citations, and remaining investigation goals directly.
There is no separate `/note` implementation or note-writing service inside OpenCode.

The note has kind `investigation_note` and status `unreviewed`, with the originating
report/window/fingerprint, chat ID and transfer ID. OpenCode fills text, limitations
and citations while preserving the supplied identity/provenance. The timestamp
identifies the transfer, not a DAQ event. Preparation creates a template inside the
workspace; it does not publish an empty note. OpenCode may refine this transfer's
note, but cannot edit previous notes. Exit checks note structure, origin and source
metadata against the retained report. This validation cannot establish diagnostic
correctness. Malformed records are reported and remain on disk for correction;
ordinary note retrieval skips malformed records. A valid investigation note can be
listed/searched by `/notes` and reused as historical context in later chats.

## Tool boundaries and validation

OpenCode can read the handoff, selected skill files and retained evidence. File
modifications are permitted only for its assigned note path. Shell, web queries,
MCP services, delegation, production DAQ controls and edits to original report or
chat files remain denied. Build/plan agents are disabled in the transfer config.
These are OpenCode tool permissions, not an OS sandbox. Child processes inherit a
private umask; the application does not copy API credentials into the handoff.
Only the selected provider definition with credential references is used.

Unlike bounded chat, the interactive investigation is not subject to per-answer
JSON/citation audits or the 600-second question timeout. The task-transfer skill
instructs it to cite evidence and distinguish observations from hypotheses;
humans still review its conclusions. Existing `/note` and `/notes` behavior in
ordinary daq-agent chat is unchanged.

Deterministic tests cover immutable evidence/skills, accepted-history transfer,
size limits, path permissions, tampering, direct note compatibility and fake
interactive launch/resume. The installed OpenCode CLI's configuration and agent
permissions can be checked without sending evidence to a model. No live DAQ
service or production model run is required for those tests.
