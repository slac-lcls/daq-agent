# Chat with a saved report

Status: terminal chat implemented in 0.7.0; local notes added in 0.8.0. Generate a report first, then
ask questions about its retained findings and evidence:

```bash
daq-agent chat
daq-agent chat --hutch tmo
daq-agent chat /path/to/completed/report
```

The default is the latest valid completed report under `~/daq/agent-logs`, across
hutches. Chat shares the viewer's saved `output_root` preference. `--root` or
`--viewer-config` overrides that selection. Running, failed, preparation-only and
internal batch reports are excluded. If another report is still running, chat
selects the previous completed report and displays its historical window.

The selected report stays fixed throughout the conversation. Starting another
chat selects the latest again; an existing chat never switches automatically.
Chat reads saved artifacts only. It does not rescan the original DAQ logs or
regenerate a report. Every question still uses the configured model service and
has model latency and usage cost.

## Questions, commands and resume

At the prompt, ask questions such as:

```text
Explain finding 3. Which lines support it?
Could findings 2 and 3 describe the same incident?
What additional evidence would distinguish these hypotheses?
Draft a short DAQ meeting summary, including evidence gaps.
```

Local commands do not call the model. See [local notes](local-notes.md) for the
shared notes directory, natural-language forms and historical-context retrieval:

- `/report`: selected report, window, models and skill provenance.
- `/findings`: stable references such as F001 and the saved finding titles.
- `/sources`: retained snapshot IDs and source paths.
- `/note TEXT` or `Save this note: TEXT`: save your wording as a local note.
- `/note` or `Save this note`: save the last completed answer with citations and limitations.
- `/notes [ID or search]`: list, search or read same-hutch notes.
- `/exit`: exit the conversation. EOF also exits; Ctrl+C during a question cancels
  that turn and returns to the prompt.

Answers cite retained snapshot IDs, original snapshot line ranges and local paths.
Use `daq-agent view /path/to/report` for the existing browser evidence viewer.
Citation checks establish valid supplied locations, not semantic correctness.
General guidance or an explanation of missing evidence may have no citations.

Startup prints a conversation ID. Resume with:

```bash
daq-agent chat --resume CHAT_ID
```

Resume uses the original report even if newer reports exist. Changed or missing
report artifacts or diagnostic skills fail verification. Only one process may
write a conversation at a time. Failed/interrupted turns are retained for diagnosis
and excluded from accepted conversation history. Completed turn artifacts rebuild
the transcript after interruption.

For a single question without an interactive prompt:

```bash
daq-agent chat --hutch tmo --question 'Explain F001 and its evidence.'
```

## Models and pinned skills

A new conversation uses the current hutch profile's provider/model defaults.
`--config`, `--provider-config`, `--model` and `--opencode` can override them.
Resume retains the conversation's initial model unless `--model` overrides it;
provider access is resolved from the current configuration. The selected chat model
and the report's original model are both displayed and recorded per turn.

Diagnostic skills come from the report, **not the current configuration's branch
tip or revised pin**. Chat verifies the retained skill files and their recorded
hashes, and requires consistent provenance across all contributing report batches.
The configured `psana-daq` and `psana-daq-logs` skills are therefore available when
they were retained by that report. No fetching or upstream script execution occurs.
Reports explicitly generated with local guidance only remain local-guidance chats;
reports without retained provenance require regeneration.

Chat adds the packaged `report-chat` skill for follow-up interpretation and the
answer contract. Its bytes/hash are saved with the conversation and reused on
resume. Runtime traces must show loads of every required skill and reads of every
selected evidence snapshot. Skills provide guidance; shell, edits, new log scans,
Grafana, DAQ controls and unrelated tools remain unavailable. The runtime retains
application-level permissions, not an OS sandbox.

## Context selection and limits

Python selects evidence by explicit finding/source reference first, then lexical
matching of findings and retained source text. Short follow-ups can retain the
previous selected topic. Ask using an explicit F001 or log-1 reference to change
that topic precisely. Search examines all retained batches; source IDs remain the
combined report's IDs. Full selected snapshots preserve their original line numbers.

The shared scope document is supplied once where the collector retained it. Its
counts describe matching log lines, not deduplicated incidents, downtime or lost
events. Chat does not sum repeated batch scope counts or query a live run registry.

Per question, context is bounded to:

- 8 evidence documents and 256 KiB of evidence.
- 48 KiB of selected report context, including a summary excerpt and limitations.
- At most six recent accepted turns and 16 KiB of history.
- Up to three matching historical notes and 12 KiB of note context.
- 80 KiB of complete prompt text; 128 KiB of available skill files.
- 384 KiB of combined prompt, evidence and available skills; at most 600 seconds
  for the model subprocess, reducible with `--timeout`.

These are byte budgets, not guarantees about a provider's token context limit.
The runner also retains its model-step and output limits. Oversized explicit
requests fail before calling the model and can be split into narrower questions.
The application records selection/truncation and prints source/history coverage.
Selection is not exhaustive: absence from retrieved context is not evidence of
absence. A broad summary of a large report may need several focused questions.

The saved report itself contains sampled excerpts. Chat cannot recover omitted
log detail and should identify when new logs or metrics are needed. Earlier
answers and saved findings are interpretations, not independent observations.

## Private artifacts

Conversations live under `$XDG_STATE_HOME/daq-agent/chats/<chat-id>` or, by default,
`~/.local/state/daq-agent/chats/<chat-id>`. `--state-root` overrides that root; supply
the same override when resuming. The original completed report is never edited.

Each conversation contains a binding manifest, saved chat skill, transcript, and
`turns/NNNN/` with selected context, prompt, evidence, runtime trace, validated answer
and status. The report fingerprint detects changes relative to conversation
creation; it does not prove the report's prior authenticity. Provider credentials
are not copied into these artifacts. Directories/files are private; generated
content from real reports must stay out of public commits.

The first version uses a fresh restricted OpenCode session per question, with
bounded history replay. Browser chat, automatic history summarization, semantic
retrieval, multiple-report comparisons and explicit evidence expansion remain
future work. The implementation and tests establish orchestration and citation
integrity; diagnostic accuracy still requires human review.


## Integration check

On 2026-09-22, real OpenCode answered a question about a manually authored synthetic
saved report using the packaged chat skill and retained pinned DAQ skills. The
trace showed all three skill loads and both snapshot reads; returned citations
passed validation. This checks the runtime connection and artifact workflow, not
production diagnostic accuracy. Ordinary CI tests use a fake subprocess and need
no credentials or model service.
