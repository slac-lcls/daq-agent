# Documentation

Design baseline: 2026-09-21. This directory is the home for architecture,
proposals, implementation plans, and project decisions.

| Document | Purpose | Status |
| --- | --- | --- |
| [Architecture](architecture.md) | Boundaries, data flow, and repository organization | Design baseline |
| [Log-analysis workflow](workflows/log-analysis.md) | Python + skill + example + validation walkthrough | Implemented prototype |
| [One-command reporting](workflows/rolling-report.md) | Collect rolling-window shared logs and analyze partitions | Implemented prototype |
| [Real TMO logs](workflows/tmo-logs.md) | Scoped input preparation and pinned-skill analysis | Manual workflow |
| [Viewing reports](viewing-reports.md) | Browser reports, clickable evidence, NoMachine/SSH, and personal settings | Implemented |
| [Skills integration](skills-integration.md) | Pinned source, explicit synchronization, runtime loading | Implemented for supplied and collected excerpts |
| [Reporting MVP](proposals/001-reporting-mvp.md) | First useful report and CLI contract | Partial: planning and shared-log reports implemented |
| [Live troubleshooting](proposals/002-live-troubleshooting.md) | Watcher and incident-driven investigations | Future proposal |
| [Evaluation](evaluation.md) | Code tests and diagnostic-quality evaluation | Initial strategy |
| [Deployment](deployment.md) | Development, service installation, state, credentials | Proposed deployment |

Current choices: a standalone Python repository; OpenCode as the current
runtime; reusable diagnostic skills maintained upstream; historical TMO reports
first; read-only evidence tools; human review of findings.

Open decisions: operational host and owner, project credential/budget, reviewed
future upstream skill home, validated source access/retention, distribution channel,
and repository license. Public visibility does not grant a software license;
choose one with the maintainers before treating this as a reusable release.

The CLI's `--help` and the root README are authoritative about what executes
today. `report` collects shared logs; `analyze-logs` operates on supplied excerpts.
`chat`, `watch`, and the full incident-report contract remain proposals.
