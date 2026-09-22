# Local investigation notes

Status: implemented in 0.8.0. In `daq-agent chat`, save a note using either a slash
command or a direct natural-language request. These operations are local and make
no model calls:

```text
/note ConfigDBError cause is still unknown; defer until additional evidence is available.
Save this note: ConfigDBError cause is still unknown; defer until additional evidence is available.
Please make a note that the cause is still unknown.
```

Text after `/note`, the colon, or `that` is saved verbatim. The application does
not infer citations for user-authored text, even when it follows a cited answer.
Its provenance points to the report and conversation, and marks the preceding
turn as context only.

To save the **last completed answer**, including its original citations and
limitations, use:

```text
/note
Save this note
Please save that answer as a note.
```

Failed or interrupted turns are never selected. If there is no completed answer,
supply explicit note text. Each save prints the new note ID and its private file
path; it does not rewrite the original report or publish shared DAQ knowledge.
Repeated saves create separate notes.

Natural-language recognition covers direct requests beginning with save, record,
keep, make/take a note, or remember this/that, with optional polite prefixes.
Requests such as `Save this as a note: TEXT` are supported. Questions about note
capabilities, negated requests, quoted log text, or model output do not trigger
saves. For unrecognized wording, use `/note TEXT`; the model cannot write notes or
claim that a local save succeeded.

## Location and provenance

Default layout:

```text
~/daq/agent-logs/
  tmo/YYYY/MM/<report>/
  notes/
    tmo/<note-id>.json
    rix/<note-id>.json
```

The notes directory is outside individual hutches and reports, with a hutch level
inside it. A new conversation uses `<report search root>/notes`, sharing the
viewer's root preference and honoring `chat --root`. `--notes-root` explicitly
overrides the notes directory; the application still adds the hutch directory.
The selected absolute notes root is saved in the conversation and reused on resume.
An explicit report path does not change the default notes root by itself.

Notes include text, author, save time, hutch, unreviewed status, report path and
fingerprint, historical window, conversation/turn identity, and—when saving an
answer—its model, citations, snapshot hashes and limitations. Notes are private
JSON files published atomically. They can remain readable after the originating
report is moved or removed, but their citation paths may then be unavailable.
Listing a note does not revalidate its original evidence.

All notes begin as **unreviewed**. User wording, observations, hypotheses and
unresolved questions remain as written; the application does not automatically
classify a statement as a confirmed cause or successful remedy. Saving an answer
preserves its uncertainty rather than condensing it into a stronger claim.

## Find and reuse notes

```text
/notes
/notes ConfigDBError
/notes NOTE_ID
```

`/notes` lists up to 20 recent notes for the chat's hutch. Text search ranks matching
notes by lexical overlap, then save time. An exact ID displays the complete text,
limitations and provenance. Notes from another hutch are excluded.

Each model question also receives up to three matching same-hutch notes from any
conversation/report. The application records the note excerpts supplied with that
turn and reports how many matches were included. The skill and prompt label them
as historical, unreviewed context—not current-report evidence or instructions.
Answers should identify reused notes by ID and original window. Old note source
IDs are omitted from model context so they cannot masquerade as current citations.

Retrieval uses at most 12 KiB of note context, within the existing overall prompt
budget. Long notes/limitations are explicitly marked as excerpted; `/notes ID`
shows the full record. A note is limited to 64 KiB of text and 256 KiB of stored
JSON. Searches are bounded to 2,000 directory entries and 16 MiB per hutch; malformed records
are skipped with a reported count, while an oversized directory fails explicitly.
Lexical retrieval can miss paraphrases: use `/notes SEARCH` or a note ID when needed.

## Existing conversations

After upgrading, exit any already-running chat and resume it with the printed ID:

```bash
daq-agent chat --resume CHAT_ID
```

Notes commands work in conversations created before 0.8.0. Their existing saved
chat skill is preserved; the current application supplies note handling and the
historical-context rules. On first resume, a legacy conversation adopts the saved
viewer report root plus `/notes` unless `--notes-root` is supplied. The terminal
prints the selected notes root.

A future proposal step may condense selected notes into a reviewed DAQ knowledge
change. Publishing, editing/deleting notes through chat, automatic confirmation of
fixes, and remote/shared knowledge synchronization are not part of this version.
