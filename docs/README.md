# Documentation

Design baseline: 2026-09-21. This directory is the home for architecture,
proposals, implementation plans, and project decisions.

| Document | Purpose | Status |
| --- | --- | --- |
| [Architecture](architecture.md) | Boundaries, data flow, and repository organization | Design baseline |
| [Log-analysis workflow](workflows/log-analysis.md) | Python + skill + example + validation walkthrough | Implemented prototype |
| [One-command reporting](workflows/rolling-report.md) | Collect shared logs and produce one hutch/window report | Implemented prototype |
| [Known conditions](workflows/known-conditions.md) | Deterministic counts and exclusions before model analysis | Implemented; enabled for TMO |
| [Real TMO logs](workflows/tmo-logs.md) | Scoped input preparation and pinned-skill analysis | Manual workflow |
| [Viewing reports](viewing-reports.md) | Browser reports, clickable evidence, NoMachine/SSH, and personal settings | Implemented |
| [Skills integration](skills-integration.md) | Pinned source, explicit synchronization, runtime loading | Implemented for supplied and collected excerpts |
| [Seshu skill consolidation](proposals/005-seshu-skills-consolidation.md) | Compare the current pin with Seshu's newer suite and preserve remaining review fixes | Implemented 2026-10-19; upstream PR pending |
| [Reporting MVP](proposals/001-reporting-mvp.md) | First useful report and CLI contract | Partial: planning and shared-log reports implemented |
| [Report chat](workflows/report-chat.md) | Ask cited follow-up questions about a saved report | Implemented terminal prototype |
| [Local notes](workflows/local-notes.md) | Private hutch-scoped notes reused across chats/reports | Implemented |
| [Task transfer](workflows/task-transfer.md) | Continue in OpenCode or Claude with private note writing | Implemented |
| [Model runtimes](workflows/model-runtimes.md) | Select OpenCode or Claude for reports, chat and investigations | Implemented |
| [Chat design](proposals/003-report-chat.md) | Accepted design and future extensions | First terminal implementation complete |
| [Live troubleshooting](proposals/002-live-troubleshooting.md) | Watcher and incident-driven investigations | Future proposal |
| [Evaluation](evaluation.md) | Code tests and diagnostic-quality evaluation | Initial strategy |
| [Report comparison baseline](evaluation/report-baseline.md) | Fixed synthetic cases, semantic rubric and retained runtime comparison | Baseline established; broader model evaluation pending |
| [Post-merge workflow check](evaluation/post-merge-workflow-check.md) | Saved report links, known-condition evidence and transfer verification | Local checks passed 2026-10-20 |
| [Standalone report investigations](proposals/007-standalone-report-investigation.md) | Independent central Claude/Codex sessions with report and personal skills | Proposed; not implemented |
| [Deployment](deployment.md) | Development, service installation, state, credentials | Proposed deployment |

Current choices: a standalone Python repository; centralized Claude for TMO
with OpenCode also supported; reusable diagnostic skills maintained upstream;
historical TMO reports first; read-only evidence tools; human review of findings.

Open decisions: operational host and owner, project credential/budget, reviewed
future upstream skill home, validated source access/retention, distribution channel,
and repository license. Public visibility does not grant a software license;
choose one with the maintainers before treating this as a reusable release.

The CLI's `--help` and the root README are authoritative about what executes
today. `report` collects shared logs; `report --log` accepts supplied excerpts.
`chat` uses saved report evidence. `watch` and the full incident-report contract
remain proposals.
