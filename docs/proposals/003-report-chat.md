# Chat with a completed report

Status: accepted design; terminal implementation added in 0.7.0. Design date: 2026-09-22.
See [the implemented workflow](../workflows/report-chat.md) for exact behavior,
context budgets and remaining limitations.

## Purpose

Generate a historical hutch report once, then ask follow-up questions using its
saved findings, evidence and diagnostic skills. The normal chat path does not
repeat shared-log discovery, scan the original logs, or regenerate the report.
Each answer still uses a model call and therefore has latency and usage cost.

## Proposed operator interface

The following interface is implemented in 0.7.0:

```bash
daq-agent chat                         # latest valid completed report across hutches
daq-agent chat --hutch tmo             # latest valid completed TMO report
daq-agent chat /path/to/report         # explicitly selected report
daq-agent chat --root /another/tree    # alternate report root
daq-agent chat --resume CHAT_ID        # resume a conversation on its original report
```

Default report root: `~/daq/agent-logs`, consistent with `view`. An explicit
`--root` overrides the saved personal report-root preference. Share the preference
resolver with the viewer; do not create a second conflicting default.

On startup, display the selected report path, hutch, historical window, completion
time, chat model and skill provenance. Selection uses completion time and the
same validity rules as `view`, excluding failed/prepared reports and internal
analysis batches. A report currently being generated is not eligible. If the
previous completed report is selected, its displayed window makes that clear.
If none exists, explain that the operator must finish generating a report first.

Bind the conversation to the selected report at startup. A newer report finishing
during chat does not silently change the evidence. Starting another chat selects
the latest again; `--resume` always returns to the original report.

Minimal interactive commands: `/report` shows scope and provenance; `/sources`
shows retained source IDs; `/exit` saves and exits. Display a conversation ID for
resuming. Browser chat can later use the same application service.

Example questions:

- Explain finding 3 in plain language. Which lines support it?
- Does the evidence establish a cause, or only a correlation?
- Are these two findings potentially the same issue across different launches?
- Which additional logs or metrics would distinguish these hypotheses?
- Draft a short summary of the findings for the DAQ meeting.

Assign stable report-local finding references such as F001 at chat initialization
without modifying the original findings. These identify findings, not incidents.

## Reuse existing application boundaries

The current implementation provides useful pieces but needs a chat-specific
contract; calling `analyze_logs()` for every message would regenerate a report.

| Component | Proposed responsibility |
| --- | --- |
| `report_store.py` | Extract report loading, integrity checks and latest selection from `viewer.py`; shared by view and chat |
| `chat.py` | CLI loop, report binding, question handling, conversation persistence and cancellation |
| `report_context.py` | Bounded local search of saved findings/evidence, stable source mappings and context selection |
| `runtime.py` | Reuse provider selection, isolation, subprocess limits and tool auditing; parameterize the agent/task contract |
| `chat_answers.py` | Validate answer structure and citations, then render conversational text |
| `skills/report-chat/SKILL.md` | Follow-up interpretation, citation and uncertainty instructions |
| `tests/test_chat.py` | Synthetic orchestration, selection, retrieval and failure regression cases |

Keep existing reporting behavior unchanged when extracting shared functions.
The current runner/auditor hardcodes `log-triage`, the report JSON contract and
reads of every assigned source. Make those explicit task parameters, with strict
report defaults retained. A chat turn audits the selected context and required
skills, rather than requiring a reread of every source from every report batch.

## Evidence and question handling

1. Load and validate the completed report locally. Compute a conversation binding
   fingerprint over its manifest, findings and recorded evidence identities. The
   fingerprint detects later changes relative to chat startup; it does not prove
   the report was authentic before startup.
2. Build a local index of finding references, source IDs, launch/component labels
   and retained evidence text. Begin with deterministic text search and citation
   lookup. A hosted vector database or embedding service is unnecessary for the
   first version.
3. Resolve explicit finding/source references first. Add relevant findings and
   evidence with nearby lines for other questions. Search across all retained
   batches; map citations to the combined report's global source IDs.
4. Send the question, bounded recent conversation, relevant report context,
   selected evidence and skills to OpenCode. Apply explicit budgets to the whole
   prompt, including history, skills and findings, not just evidence files.
   Retain the current evidence ceiling of 8 documents / 256 KiB per model session
   and reject or narrow an oversized question rather than silently losing scope.
5. Validate the returned answer and citations before displaying it. Record the
   context actually supplied, retrieval omissions, model/runtime/skill identity,
   tool audit and timing with the turn.

The report's generated prose is a prior interpretation. Historical claims should
cite original retained evidence where available; quoting a report finding alone
does not independently verify it. General diagnostic explanations should be
identified as guidance. Previous chat answers are conversation context, not
additional observations.

Preserve source line numbers if retrieving excerpts: carry an explicit mapping to
the retained snapshot and validate citations against both the snapshot and the
ranges actually supplied. Do not accept a citation to a valid but unseen range.
An insufficient match should produce an evidence limitation or a clarifying
question; absence in retrieved context is not proof of absence in the report.

For global questions such as "what happened most often?", use validated captured
counts where available and describe what they count. Parse any collection data
through bounded application code; do not expose the entire private inventory as
unrestricted model context. Never sum duplicated shared scope documents across
batches, or equate matching lines with incidents, downtime or lost events. If the
retained data cannot support the requested comparison, say so. Cross-batch
similarities may be proposed as hypotheses, not asserted as deduplicated incidents.

Report evidence contains sampled contexts rather than every original log line.
Chat can explore those saved contexts but cannot recover omitted detail. A
request needing new raw logs, Grafana or current DAQ state should identify the
missing input. Explicit evidence expansion is a later workflow with its own
scope and provenance.

## Conversation state and runtime choice

For the first version, DAQ Agent owns the durable conversation. Invoke a fresh
restricted OpenCode session per question with selected recent history and the
current evidence context. This reuses the existing subprocess lifecycle without
depending on undocumented native session restoration behavior. It also permits
different evidence selections on successive turns.

This choice repeats skill/context loading and model prefill. It avoids repeating
the expensive original log scan, but does not guarantee instant responses or
provider-side prompt caching. Measure answer latency and usage before deciding
whether a persistent OpenCode session/server is worthwhile.

Keep the full transcript locally; bound the history sent to the model. If older
turns are omitted, report that fact and preserve explicit references needed for
the current question. Add validated conversation summaries later if necessary.
Use one active writer per conversation; interrupted turns remain incomplete and
are not promoted to accepted answers. Resume checks the bound report fingerprint
and refuses changed or missing artifacts rather than silently substituting a
newer report.

Proposed state layout, separate from completed report artifacts:

```text
~/.local/state/daq-agent/chats/<chat-id>/
  manifest.json       # bound report, fingerprint, model, skill provenance, status
  transcript.jsonl    # user questions and validated answers
  turns/0001/         # selected context, prompt, response, audit and runtime trace
```

Honor `XDG_STATE_HOME`, use private directory/file permissions, and keep state out
of Git. Capture only necessary validated report metadata; do not persist provider
credentials. Report and chat models may differ: default to the current hutch's
configured provider/model and show both identities. A model change is not a report
regeneration.

## Skills and tools

Use the upstream diagnostic skill bytes retained with the report, verifying the
recorded hashes. For a batched report, inspect each contributing batch's skill
provenance and require a consistent supported set for the initial implementation.
Fail clearly on missing, changed or inconsistent skills; do not silently replace
them with a branch tip. A future explicit local-only mode can document reduced
guidance for older reports.

Add a small application-owned `report-chat` skill for answering questions; the
existing `log-triage` skill is oriented toward emitting a complete report. Keep
DAQ diagnostic knowledge in the pinned upstream skills. Record the new chat
skill's version/hash separately from the skills originally used for reporting.

Permit only assigned context reads and approved skill/reference reads. Retain the
runtime's existing denied shell, edits, external queries and DAQ controls. These
are application permissions, not an OS sandbox. Treat report text, logs and
transcripts as potentially untrusted content. Starting chat uses the configured
model service for the selected evidence just as reporting does.

## Delivery and acceptance

First implementation: terminal chat, explicit/latest report selection, report
binding, bounded retrieval, cited answers, durable transcript and resume. Model
responses use a small structured contract (answer, citations and limitations),
rendered as normal prose; no complete report JSON is required per question.

Before release, use synthetic tests to verify:

- Latest selection skips a running report and internal batches; a conversation
  stays bound when a newer report completes.
- Single-session and combined reports work, including citations to later batches.
- Explicit finding follow-ups and source excerpts preserve citation identity.
- Missing evidence produces limitations; unknown, out-of-range or unseen
  citations are rejected.
- Evidence tampering, skill mismatch and changed reports on resume fail clearly.
- History and retrieval budgets are enforced; global counts are not duplicated.
- Cancellation/model failure retains an incomplete turn without changing the report.
- Model tool auditing rejects unexpected operations and verifies required skills.
- Report generation and the existing viewer still pass their regression tests.

Then perform an explicitly authorized model integration check. Compare answer
latency and relevance with regenerating a report; require evidence support and
honest coverage statements rather than exact wording.

Later stages: browser chat alongside the report and clickable citations,
comparison across explicitly selected reports, and separately scoped retrieval of
additional evidence. Live diagnosis and DAQ operations remain separate capabilities.
