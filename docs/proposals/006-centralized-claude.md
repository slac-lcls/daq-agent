# Centralized LCLS Claude deployment

Status: implemented, 2026-10-20.

## Decision

The TMO profile uses the centrally managed LCLS Claude binary, `opus` (currently
Opus 5.5), medium effort and one-hour prompt caching. OpenCode and explicit
personal Claude deployments remain available for other configurations and
comparison. There is no automatic credential/runtime fallback.

Interactive `claude` can launch the same installation as `claude-lcls`. Application
sessions invoke the underlying binary directly: the interactive function sets a
shared per-user configuration directory, which would override DAQ Agent's
isolated configuration. The shared binary's `current` symlink is resolved once
per invocation and the actual path/version are retained. Central upgrades can
change later calls, so recorded runtime identity matters for comparisons.

The LCLS adapter reads selected model/endpoint mappings from the user's LCLS
settings and the authorized shared key file directly. It does not execute a
settings-supplied shell helper, import personal auth overrides, or copy secrets
into artifacts. Missing installation/key access is an actionable error. The
central deployment's general skills, hooks, MCP servers and permission mode do
not enter report/chat/transfer sessions. The reviewed DAQ skill pin is unchanged.

New chats retain deployment settings for resume. New transfers inherit them and
the selected model rather than independently choosing a PATH executable and
Sonnet. Transfer resume retains the first launch's resolved model even if a
central alias changes. Legacy records retain their previous selection; a new
handoff adopts the new deployment. Reports are immutable.

Runtime provenance adds deployment, actual executable, effort, requested cache
TTL and returned cache/token counters. Report schema, evidence access auditing,
citation validation and bounded tools remain unchanged. Requested cache TTL is
not proof that a gateway honored it; actual counters are retained separately.

## Validation

- Deterministic suite: 150 tests, 149 passed and one optional OpenCode integration
  test skipped. Added checks cover shared-key selection, no personal fallback,
  model suffixes, symlink resolution, report/chat isolation, saved chat settings,
  and exact-model transfer resume. No live model calls occur in these tests.
- The user installation's live completion succeeded with central Claude 2.1.285.
- A separate approved live comparison replayed two retained **synthetic**
  Configure-failure excerpts, using identical scope, evidence and five pinned
  upstream skills at `179b2bfbe73901f394222922571a0753e7ce9a06`.
- OpenCode/Sonnet 5 produced one combined finding. LCLS Claude/Opus 5.5 produced
  two findings. Both identified the failed Configure, teb0's Results-queue
  permission denial, and the possible causal connection without establishing
  queue ownership or stale-queue root cause. Both acknowledged unavailable
  services and passed mandatory skill/evidence reads and citation validation.
- Opus's summary contained a launch-wide assertion about never reaching
  configured, broader than the supplied excerpts support; its findings also
  acknowledged unknown later recovery. This remains a human-review limitation.
  The comparison establishes basic synthetic-case agreement, not equivalent
  diagnosis quality or complete report equivalence.
- The Opus result reported 35,710 cache-write tokens in the one-hour bucket and
  zero in the five-minute bucket. This verifies TTL delivery for that call, not
  a general cost-saving guarantee.
- Built and installed 0.9.2 in the existing virtual environment. All 37 packaged
  source/resource files matched the checkout and wheel; the installed package
  passed the same 150-test suite (one optional skip).
- Installed CLI chat, run outside the checkout, completed a cited answer using
  the same Opus/medium configuration and one-hour cache writes. It correctly
  stated that later Configure success cannot be determined from the excerpts.
  A prepared transfer inherited the central executable, deployment, model,
  effort and TTL. Interactive transfer launch/resume was covered by deterministic
  tests, not a live operator session.

Generated reports, transcripts, credentials and user shell backups remain
outside the repository. Future evaluations should include representative
reviewed operational cases and compare incident identity, facts, hypotheses,
coverage and citations rather than finding counts or exact wording.
