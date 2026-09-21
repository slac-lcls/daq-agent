# Documentation

Design baseline: 2026-09-21. This directory is the home for architecture,
proposals, implementation plans, and project decisions.

| Document | Purpose | Status |
| --- | --- | --- |
| [Architecture](architecture.md) | Boundaries, data flow, and repository organization | Design baseline |
| [Log-analysis workflow](workflows/log-analysis.md) | Python + skill + example + validation walkthrough | Implemented prototype |
| [Viewing reports](viewing-reports.md) | Browser reports, clickable evidence, NoMachine/SSH, and personal settings | Implemented |
| [Skills integration](skills-integration.md) | Sources, discovery, dependency checks, versioning | Proposed integration |
| [Reporting MVP](proposals/001-reporting-mvp.md) | First useful report and CLI contract | Proposed; planning CLI implemented |
| [Live troubleshooting](proposals/002-live-troubleshooting.md) | Watcher and incident-driven investigations | Future proposal |
| [Evaluation](evaluation.md) | Code tests and diagnostic-quality evaluation | Initial strategy |
| [Deployment](deployment.md) | Development, service installation, state, credentials | Proposed deployment |

Current choices: a standalone Python repository; OpenCode as the initial proposed
runtime; reusable diagnostic skills maintained upstream; historical TMO reports
first; read-only evidence tools; human review of findings.

Open decisions: operational host and owner, project credential/budget, reviewed
upstream skill revisions, validated source access/retention, distribution channel,
and repository license. Public visibility does not grant a software license;
choose one with the maintainers before treating this as a reusable release.

The CLI's `--help` and the root README are authoritative about what executes
today. `analyze-logs` operates on supplied excerpts; the full `report`, `chat`,
and `watch` interfaces remain proposals.
