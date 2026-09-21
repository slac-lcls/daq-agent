# Deployment proposal

The implemented log-analysis example is a manually invoked subprocess workflow,
not an unattended service. Its [walkthrough](workflows/log-analysis.md) documents
its actual configuration and access limits.

## Locations and ownership

- Source: `slac-lcls/daq-agent`.
- Initial development checkout: `/sdf/home/m/monarin/daq-agent`.
- Future service: versioned installation in a group-managed location on an
  approved host, with a named operational owner. The exact host/path is undecided.
- Evidence, reports, incident state, and session history: separate restricted
  operational storage, with retention and backup decisions owned by the service.

Do not run the production service from a mutable personal checkout. Keep local
session databases on storage supported by the runtime; AMI's OpenCode launcher
already uses node-local storage to avoid network-filesystem SQLite problems.
Export durable application records separately from runtime scratch state.

## Model access

The LCLS shared OpenCode setup inspected on 2026-09-21 configures SLAC and Stanford
gateways with credential-file references and uses Sonnet 5 as its default. This
is an observed development setup, not a grant for a new unattended service.

Before deployment, confirm credential ownership, service use, available models,
quotas, billing/budget, and permitted handling of operational evidence with the
service owner. Prefer a dedicated project identity for scheduled use when
available. Never copy shared key values into source, examples, reports, or logs.

The hutch configuration contains a model identifier, provider configuration path,
OpenCode executable path, and output root; it contains no credentials. The TMO
example defaults to the shared LCLS development installation on SDF. CLI flags
can override those paths. Output defaults to the invoking user's
`~/daq/agent-logs/<hutch>/YYYY/MM/<unique-run-directory>`, grouped by launch time in the
configured timezone. Installation does not access credentials or services.
Explicit `report` execution imports one provider/model from the selected
OpenCode JSON file, preserving an external credential
reference. It does not modify the shared configuration or inherit its agents/MCP
servers. `--prepare-only` requires neither credentials nor an OpenCode installation.
When upstream skills are configured, first run `daq-agent sync-skills --config
config/hutches/tmo.toml`. This explicit network operation caches the exact pinned
revision. Subsequent analyses verify and retain those skill bytes without fetching.
Use `--local-skills-only` to explicitly omit upstream guidance, including in offline
CI preparation.

## Preflight and scheduling

Verify runtime version, pinned skills, tool inventory, source access and retention,
output-directory permissions, and selected hutch/partition before a real run.
Missing optional evidence must be reported; missing critical access must produce
a clear incomplete/failed result rather than a healthy report.

After manual reports are evaluated, schedule collection every couple of days and
cover operating periods since the last successfully processed boundary. Save
checkpoints only after outputs persist. Define retry/idempotency behavior to
avoid losing coverage or duplicating incidents.

A future service template must define resource limits, restart policy, environment
references, operational storage, and health visibility. No deployable service unit
is supplied until a runtime and host have been selected and validated.
