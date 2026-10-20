# Transfer a report investigation to OpenCode or Claude

Status: implemented. Ordinary `daq-agent chat` still runs bounded,
validated question/answer turns. A task transfer opens a separate persistent
OpenCode investigation with the same report evidence and pinned diagnostic skills.
Claude Code is also supported. A transfer inherits the chat's selected runtime;
the packaged TMO default is centralized LCLS Claude.

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

## Use Claude Code

From chat, select Claude while preparing the handoff:

```text
/task-transfer --runtime claude Investigate whether F003 explains the transition failure
/task-transfer --prepare-only --runtime claude
```

The choice is saved in the handoff. You can also open an existing handoff with
Claude explicitly, without changing the source chat or report configuration:

```bash
daq-agent task-transfer /path/to/workspace --runtime claude
daq-agent task-transfer /path/to/workspace --runtime claude --resume
```

New Claude transfers inherit the executable, deployment, model, effort and cache
settings from their chat. The TMO defaults are the shared LCLS binary, `opus`,
medium effort and one-hour caching. The application calls the binary directly
with isolated configuration; it does not invoke the interactive shell function.
The LCLS deployment reads the shared credential file directly and selected
endpoint/model mappings from `~/.claude-lcls/settings.json`. Arbitrary shell
helpers, hooks and personal credentials are not imported. Personal API-token
configuration remains available through a custom chat configuration. See
[model runtimes](model-runtimes.md) for selection and credentials.

Legacy handoffs without deployment metadata retain the personal/sonnet behavior;
prepare a new handoff to adopt LCLS. Credentials are never written into handoff
or launch files. No OpenCode provider file is read for a Claude launch.

Each runtime keeps separate session history. Switching runtimes starts from the
retained handoff and current note, not the other runtime's subsequent messages.
Claude resumes the exact session ID recorded in `runtime/claude/session.json`;
resuming before the first Claude launch produces an error. Resume retains the
resolved model from the first launch even if a central alias changes. A new launch without
`--resume` creates a new session; the latest launch becomes the resume target.
Both runtimes share the handoff's assigned note and launch lock. The note's
`origin.answer_model` identifies the source chat model; Claude's selected model
and session ID are recorded separately in its runtime state. In-session model
changes are recorded by Claude's own history.

Claude's generic file, shell, web and delegation tools are disabled. Only its
question tool and two local MCP tools are exposed: `read_file` checks the retained
inventory and returns bounded numbered lines; `save_note` accepts text,
limitations and citations, validates them, and atomically replaces the assigned
note. It accepts no destination path or provenance fields. Pinned skills are read
with `read_file` from the same `.opencode/skills/` inventory. Personal/project
settings, plugins, skills and other MCP servers are not imported. These are
application/runtime tool boundaries, not an OS sandbox; administrator-managed
Claude policies still apply. The user may see Claude's normal first-run/trust UI.

Exit Claude to return to chat. Model calls use your configured API account and
its budget. Reports and ordinary chat can independently select Claude using
`--runtime claude`; see [model runtimes](model-runtimes.md).

## OpenCode session continuity

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
- `runtime/`: private state for the selected runtime, created when it runs.

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
service or production model run is required for those tests. Claude tests cover
credential isolation, exact-session resume, MCP handshakes, bounded reads,
rejected paths/symlinks and validation before note replacement. A separate offline
smoke check with Claude Code 2.1.270 and a loopback fake Anthropic API verified
tool discovery, handoff reading and note saving without paid model calls.

### Note permissions and failed saves

OpenCode 1.2 checks both `write` and `edit` using the `edit` permission and a
path relative to its project worktree. The launcher computes that exact note
path (non-Git workspaces use `/`; linked Git worktrees use the main checkout).
Read and external-directory rules remain absolute. Root detection failures and
wildcards in note permission paths fail closed; other notes are never writable.
Launch/resume regenerates the configuration, including for existing transfers.

The primary agent instructs OpenCode to stop after a denied save, report the
failure with its draft, and wait for repair. This instruction also applies when
resuming older transfers whose retained skill predates it. Each turn is capped
at 12 model steps. `continue_loop_on_deny` is explicitly false for user-rejected
requests; in OpenCode 1.2.10 it does not stop configured-rule denials by itself.
The step cap bounds those loops if the model ignores the stop instruction; it is
not a guarantee of exactly one save attempt. Failed tool inputs remain in the
private OpenCode history and are not published as notes.
