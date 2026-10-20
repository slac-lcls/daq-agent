# Post-merge saved-report workflow check

Status: checked locally on 2026-10-20 against merged PR #7,
`ab75ff65f0a34d06216a76373053531d1c8f4915`, installed version 0.9.2.

## Results

The full deterministic suite passed: **160 tests**, including the optional
installed OpenCode integration with
`DAQ_TEST_OPENCODE` set. Fake model subprocesses, the local Claude MCP boundary
and offline OpenCode permission inspection were used. No paid model calls or
production DAQ operations were performed.

A separate check loaded the latest completed saved TMO report and both retained
synthetic comparison reports through the installed package:

| Check | Result |
| --- | --- |
| Latest saved report evidence integrity | 39 retained sources validated |
| Viewer links and line targets | 8,233 references resolved through loopback HTTP; the same number resolved in portable HTML |
| Known-condition follow-up | Three appendices reconstructed from saved metadata, with valid citation paths |
| Chat state | Newly prepared local verification chats reloaded against the same report fingerprint |
| Transfers | Claude and OpenCode handoffs prepared and reloaded; every copied source hash validated |
| Original artifacts | Every original report file remained byte-identical |
| Retained synthetic reports | Both reloaded; 20 and 21 link references respectively passed HTTP and portable-file checks |

Link totals include line-number self-links and navigation, not just finding
citations. The check parsed HTML, requested every distinct referenced HTTP asset,
verified range endpoint IDs, and checked corresponding on-disk targets.
No application correction was necessary.

Known-condition answer/note citations and transfer save operations passed the
existing synthetic tests. Runtime-specific model selection, failed selection,
exact Claude session resume and OpenCode retained selection passed simulated
interactive launches. The saved real report was only loaded, served locally and
copied into private verification artifacts; no diagnostic prose was generated
or committed.

## What this does and does not establish

The server, saved evidence, portable links, known-condition appendices and
handoff integrity work on SDF. The known-condition section in the report itself
is inline text; its citable appendices belong to follow-up chats/transfers.
No generated report was rewritten.

This was not a visual browser or JavaScript execution test, nor a laptop SSH
tunnel test. A live human terminal's native resume UI was not exercised. Those
remain separate end-to-end user-environment checks; the automated tests cover
their application launch/state contracts. A stopped viewer, expired viewer URL,
or tunnel reaching a different host can still make a laptop citation unreachable.

## Repeatable checks

```bash
DAQ_TEST_OPENCODE=/path/to/installed/opencode \
  python -m unittest discover -s tests -v
daq-agent view /path/to/completed/report --ssh-host sdfiana --port 0
```

Use the exact host, port and URL printed by the viewer. From a laptop, keep its
printed SSH tunnel running and open a finding citation, the raw snapshot download
and the return-to-report link. For portable viewing, copy the complete report
directory and open `report.html`; copying just that file omits evidence targets.

The most relevant automated checks are `test_viewer`,
`test_known_condition_followup`, `test_transfer_models`,
`test_task_transfer_claude` and `test_task_transfer_opencode`.
See [viewing reports](../viewing-reports.md) and
[task transfer](../workflows/task-transfer.md) for supported operations.
