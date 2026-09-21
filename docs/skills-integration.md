# Skills integration proposal

## Existing sources

- [LCLS2 PR #125](https://github.com/slac-lcls/lcls2/pull/125) proposes the DAQ
  diagnostic suite under `psana/psana/skills/`. It was open during the initial
  design review; deployment must select an actual reviewed revision.
- [AMI skill discovery](https://github.com/slac-lcls/ami/blob/features/package-skill-discovery/ami/mcp_server.py)
  locates skill directories in installed `ami` and `psana` packages and copies
  complete directories into a session's `.opencode/skills/`.
- [OpenCode skill discovery](https://opencode.ai/docs/skills/) exposes names and
  descriptions, then loads full instructions through the native `skill` tool.

| Skill | Source | Use |
| --- | --- | --- |
| `robustness-report` | This package | Historical coverage, incident grouping, report contract |
| `psana-daq` | LCLS2 | Route general DAQ diagnosis |
| `psana-daq-control` | LCLS2 | State/transition diagnosis |
| `psana-daq-logs` | LCLS2 | Process-log evidence |
| `psana-daq-monitor` | LCLS2 | Grafana/Prometheus DAQ metrics |
| `psana-configdb` | LCLS2 | Read-only configuration evidence |
| `ami-performance-monitor` | AMI | AMI metrics/traces |

Some upstream skills reference additional skills such as `elog-search`. Inventory
and resolve these dependencies before claiming that the full workflow is usable.

## Proposed session assembly

1. Resolve an allowlist of skills from reviewed, pinned source revisions or
   installed packages with recorded provenance. Do not download branch tips on
   every investigation or import psana merely to discover Markdown resources.
2. Verify required frontmatter (`name`, `description`), unique names, referenced
   resources, and that installed distributions actually include the skill files.
3. Copy each full skill directory, including references/scripts, to a generated
   session workspace. Treat packaged executable helpers as reviewed code.
4. Explicitly load the reporting task instructions; make diagnostic skills
   available on demand. Avoid loading all manuals into every prompt.
5. Configure matching tools and check access. The existing Grafana skill requires
   specific MCP tools; log/control/configuration skills also assume commands,
   network routes, or libraries. Adapt those interfaces deliberately.
6. Record exact skill provenance and content hashes in the session manifest.

A generated deployment manifest will eventually lock upstream commit IDs and
skill paths. The initial scaffold does not pin or install an upstream dependency;
review and behavioral evaluation must happen first.

## Scope and permission integration

Historical tasks supply explicit hutch, partition, launch identities, timezone,
and time window. Override diagnostic defaults such as `now` and active-hutch
discovery when they conflict with the requested investigation. Today's state or
ConfigDB contents do not establish yesterday's state/configuration.

The initial workflow permits evidence reads and local report output only. Provide
bounded tools and runtime/OS permissions that enforce that boundary. Merely placing
"read-only" in a skill or hiding mutating skills is insufficient if arbitrary
shell commands still have operational privileges.

The shared LCLS OpenCode configuration is useful for development, but deployment
must explicitly resolve provider configuration, credentials, tool names, and
permission merging. Do not inherit unrelated global agents, skills, or tools
without review. Do not modify the shared configuration during application setup.

## Updates

Update a pinned skill revision through a normal pull request. Replay relevant
evaluation cases, compare evidence and conclusions, then release. Prefer fixes
in the source repository over locally divergent skill copies. Record known
limitations and deployed-release assumptions; upstream Markdown is diagnostic
guidance to validate, not infallible evidence.
