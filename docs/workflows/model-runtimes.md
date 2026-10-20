# Model runtimes

Status: implemented. `report`, `chat`, and `task-transfer` support OpenCode and
Claude Code. The packaged TMO profile defaults to the centralized LCLS Claude deployment,
Opus 5.5 through the `opus` mapping, medium effort, and one-hour prompt caching. `config`, `plan-report`,
`view`, `sync-skills`, chat navigation, and local note commands do not call a model.

## Select Claude

```bash
daq-agent report --hutch tmo --last 2d --runtime claude
daq-agent report --hutch tmo --from 2026-09-23 --to 2026-09-25 --runtime claude
daq-agent chat --hutch tmo --runtime claude
daq-agent chat --resume CHAT_ID
```

Selecting Claude from an OpenCode profile defaults to `opus` for the LCLS deployment
and `sonnet` for a personal deployment. Use
`--model opus`, `--model haiku`, or a native model ID to override it. Claude model
names do not use OpenCode's `provider/model` prefix; the `[1m]` context suffix is supported. Use `--claude /path/to/claude`
for an executable outside PATH. A saved chat remembers its runtime and model;
`--runtime` and `--model` can override them on resume. Switching a Claude chat back
to OpenCode requires an explicit OpenCode `--model provider/model` value.

The ordinary chat workflow still starts a fresh bounded model session per answer
and passes validated recent history. `/task-transfer [goal]` inherits the chat's
runtime and opens a separate interactive investigation. An explicit
`/task-transfer --runtime claude [goal]` selects Claude. Switching a Claude handoff
to OpenCode requires `/task-transfer --runtime opencode --model provider/model`.
An existing handoff can select that model at launch with the same flags.
Transfers retain separate runtime model choices; transfer `--resume` uses the
saved choice and cannot be combined with `--model`. See
[task transfer](task-transfer.md) for its independent session history and note tool.

To make Claude the default for a custom hutch configuration, retain the existing
hutch, timezone, log/output roots and pinned `daq_skills` section, and set:

```toml
runtime = "claude"
model = "opus"
claude_deployment = "lcls"
claude_effort = "medium"
claude_cache_ttl = "1h"
claude = "/sdf/group/lcls/ds/dm/apps/dev/claude/bin/current"
```

Pass that file using `--config`. No shared profile or user Claude configuration
is changed by selecting a runtime. `--prepare-only` requires neither runtime nor
credentials, and makes no model call.

## Credentials and model identity

The LCLS deployment requires the user installation of `claude-lcls`. It reads
only selected endpoint/model environment values from `~/.claude-lcls/settings.json`
and reads the authorized shared key file directly. It does not execute
`apiKeyHelper`, import personal credentials, or fall back to another account.
Failure to read the shared key is an error identifying the `ps-users` access
requirement. Credentials stay in the child environment, never in application
artifacts. The team account's usage/budget applies.

The interactive `claude-lcls` shell function is not an application executable.
DAQ Agent invokes the shared binary directly, resolves its `current` symlink once
per model call, and retains its own isolated `CLAUDE_CONFIG_DIR`. This preserves
the application tool boundary. The central installation's skills, permission
mode, hooks and plugins are not imported. The pinned DAQ skill dependency remains
independent of central binary upgrades.

The personal deployment remains available through `--claude-deployment personal`
(or `claude_deployment = "personal"` in a custom configuration), with an actual
Claude binary supplied using `--claude` when the normal command is an interactive
LCLS launcher. It accepts `ANTHROPIC_AUTH_TOKEN` or `ANTHROPIC_API_KEY` from the
environment or the `env` section of `CLAUDE_CONFIG_DIR/settings.json` (otherwise
`~/.claude/settings.json`); environment values take precedence. OAuth and arbitrary
`apiKeyHelper` commands remain unsupported. No OpenCode provider file is read by
either Claude deployment.

`--claude-effort` and `--claude-cache-ttl` override the configured values. LCLS
sessions default to medium and `1h` when unspecified; personal sessions leave
unspecified values to the CLI. One-hour caching can cost more for a cold, short
session; savings depend on subsequent reuse. The runtime records requested TTL
and actual returned cache token counters separately.

Reports, chat and transfers use the same deployment configuration. New chats save
the executable, deployment, effort and cache settings for resume; old chats without
these fields retain legacy personal/OpenCode behavior. Select LCLS explicitly when
migrating a legacy Claude chat. New transfers inherit the selected model and
runtime settings; resume retains the model resolved at their first launch, even
if central alias mappings subsequently change. Prepare a new handoff to migrate
an old personal transfer. Existing reports remain immutable.

Claude needs `--restricted` and reports also need `--json-schema`; the centralized
integration was verified with 2.1.285. Each model session records the actual
executable path, CLI version, deployment, requested and resolved model, effort,
requested cache TTL, and returned token/cache counters in `runtime.json` and the
manifest's `runtime_details`. Skills retain their existing commit/hash provenance.
Task transfers record launch settings and the exact session ID separately in
`runtime/claude/session.json`.

To explicitly run the previous OpenCode/Sonnet configuration:

```bash
daq-agent report --hutch tmo --last 2d --runtime opencode --model slac/us.anthropic.claude-sonnet-5
```

## Evidence access and output validation

The model receives only local MCP tools for loading the selected pinned skills
and reading retained evidence/reference files. There are no generic file-write,
shell, web, delegation, note-save or production DAQ tools in report/chat sessions.
Claude runs with restricted mode, isolated configuration, no imported personal
plugins or other MCP servers, and no persistent Claude session for ordinary
report/chat calls. Administrator-managed Claude policies still apply. This is
a runtime/tool boundary, not an OS sandbox.

The local tool server checks an application-generated inventory and file hashes.
It writes the evidence-access audit independently of the model's response.
Every required skill and supplied snapshot must be accessed before an answer is
accepted. Rejected access, malformed output or invalid citation locations cannot
publish a completed report or accepted chat turn. Chat retains its existing one
retry for missing reads, within the original timeout; a forbidden access is not
retried. Model conclusions still require human review.

Claude reports pass an explicit JSON Schema through `--json-schema`, including
the required nonempty `evidence` array in every finding and the batch's allowed
source IDs. The adapter consumes `structured_output` from the final successful
result, not the ordinary prose `result` field. See the
[Claude Code structured-output documentation](https://code.claude.com/docs/en/headless#get-structured-output).
Each batch retains `output-schema.json`. Missing structured output or a schema
failure rejects the run; there is no fallback to uncited prose. Python still
validates field sets, size limits and citation line ranges, independently of the
runtime. These checks validate locations, not whether evidence supports a claim.
Chat continues using its existing answer validator.

Responses rejected by the report validator remain in `response.txt`, with the
path printed in the error. Missing citations are not automatically inferred from
prose. Existing failed reports are unchanged, and a later batch is not started
when validation fails.

Both runtimes use the existing batch sizing, report formats, source remapping,
chat context limits and citation validation. Reports default to a 600-second
timeout per model session; `--timeout` accepts 1–3600 seconds for either runtime.
Chat retains its 1–600 second limit. Both use an 8 MiB limit per runtime output file, with process-group
cleanup on failure/cancellation. Private `claude-events.jsonl` contains the raw
Claude stream; `events.jsonl` contains the normalized access audit and final text.
Rejected chat attempts retain both traces. No paid calls or live DAQ access are
part of ordinary unit tests.

Model JSON parsing tolerates literal LF, CR and tab characters inside quoted
strings by escaping them without changing their decoded text. This handles
occasional formatting errors in otherwise complete model responses. It does not
repair missing quotes/brackets, invalid escapes or other control characters;
schema, evidence-access and citation checks still apply. Raw responses remain
unchanged in the private runtime artifacts.
