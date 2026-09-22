# Review: upstream session snapshots and DAQ issue history

Status: historical review and integration proposal. The findings below describe
the reviewed revision, not the current dependency. Version 0.8.2 adopts the
corrected six-skill suite at `606038fed893ce788f1b865418ae6a569f66dc1d`
from upstream PR #131, with supporting references and the suite README.
See [current integration](../skills-integration.md) for implemented behavior and
remaining service/history limitations. The snapshot template remains readable
guidance; application output contracts are preserved.
Reviewed 2026-09-22 at upstream commit
`d6229a1d2e6395e3d67ac63b1c45096d9b523e82` on
`slac-lcls/lcls2:features/psana-daq-monitor` (also the head of PR #125).

## Dependency at the time of review

Both the repository TMO configuration and installed profile identify this branch
and `psana/psana/skills`, but execution remains pinned to
`198b6aa95229ef0e4ac5023c2a0d2e611124d46e`. The reviewed tip is five commits ahead.
Only `psana-daq` and `psana-daq-logs` are selected. Existing reports/chats retain
the skill bytes used originally; updating a deployment pin should not rewrite them.

The supplied URL had a trailing period; the reviewed directory is:
https://github.com/slac-lcls/lcls2/tree/d6229a1d2e6395e3d67ac63b1c45096d9b523e82/psana/psana/skills

## Snapshot skill: useful session-level composition

`psana-daq-snapshot` composes control, logs, metrics and implicated-detector ConfigDB
investigation into a ranked report for one live or historical session. It correctly
calls out reconstructed historical state and unavailable historical showPlatform
results. It also asks for progress narration at each investigation stage.

This complements the hutch/window report, but is not a drop-in replacement:

- DAQ Agent selects all candidate launches for the user-specified window; snapshot
  asks interactive scoping/session questions and investigates one session.
- Snapshot expects raw-log/service tools and sibling skills. DAQ Agent currently
  supplies retained evidence only and denies live service/shell/SSH access.
- Snapshot prescribes fixed Markdown headings. DAQ Agent validates a structured
  findings/citation contract. The snapshot file also says a future history reader
  will depend on its heading/field names, making an explicit schema adapter important.

Recommended integration: retain hutch/window orchestration and source identity in
DAQ Agent, and reuse upstream session-diagnostic guidance with explicit preselected
scope and available-evidence declarations. Return structured session findings and
combine them into the requested hutch-wide report. Do not add partition-specific
reporting or require repeated user session selection. Mark metrics/config/state
legs unavailable until their actual bounded read-only adapters exist.

Do not automatically load every diagnostic skill for every chat question. Reuse
saved session findings and retrieve relevant guidance/evidence to control latency.

## History skill: advertised, implementation absent at the reviewed tip

The new README lists `psana-daq-history` and describes:

- Search prior GitHub issues for the same failure mode before investigation.
- Reuse the snapshot investigation rather than duplicate its diagnostic methods.
- Record the outcome in GitHub after explicit human approval.
- Add a production-incident evidence tier.

However, the complete Git tree has no `psana-daq-history` directory or SKILL.md;
a direct contents request at the reviewed SHA returned 404. The snapshot file still
describes history integration as future work. Its actual issue repository, schema,
matching logic, permissions and update behavior therefore cannot yet be reviewed.
Obtain the published skill/commit before enabling it. The README alone is not a
loadable skill or proof that the history integration exists.

## Review findings to resolve before integration

1. **Missing history artifact.** The README advertises a loadable skill that is
   absent from the published tree. Add the file or label the entry as planned.
2. **Scope and output contracts conflict with unattended reporting.** Snapshot's
   claim of one question is followed by another session-selection handoff, and its
   fixed Markdown template differs from DAQ Agent's JSON contract. Accept an
   already-established hutch, historical window, session identity and tool inventory
   instead of re-asking; define an explicit structured-output contract.
3. **Evidence origin and causal confidence need separate fields.** Snapshot labels
   causes with tiers describing where evidence was read. Observing an error in
   production logs verifies an observation, not necessarily its proposed cause or
   a remedy. Track evidence basis separately from suspected/confirmed cause and
   proposed/tested/verified remedy before promoting results to durable issue history.
4. **The new non-RTPRIO count example filters too late.** In the logs skill's
   session-listing section, `grep -c '<[EC]>' | grep -v 'Inadequate RTPRIO'` counts
   before filtering, so the second command sees numbers rather than messages.
   A synthetic two-line test returns 2 instead of 1. Filter messages before counting;
   also use the documented zstd handling when counting compressed logs.
5. **Historical time attribution needs stronger boundaries.** Prefix and final
   file mtime are estimates of session coverage, not authoritative run boundaries;
   retain timezone/year/month and the user's window. The referenced ConfigDB skill
   also identifies an in-run history update as the active configuration: this can
   miss the configuration already active before run start, or mistake a mid-run
   update for what was actually loaded. Actual applied configuration identity must
   be corroborated; ConfigDB history alone does not establish it. That leaf skill
   explicitly says historical-key content retrieval is unverified.

The router/log changes otherwise improve explicit hutch handoff, header handling
when stderr precedes metadata, past-session scope, release-specific interpretation,
and recognition that repeated logging can inflate counts without representing
independent incidents. Keep RTPRIO messages available as evidence while deprioritizing
known startup noise rather than treating every future occurrence as universally benign.

## Knowledge ownership and proposed workflow

The upstream architecture supports the ownership split already discussed:

| Artifact | Role | Owner/location |
| --- | --- | --- |
| Reports, snapshots, conversations | Captured evidence and working analysis | Private application output |
| Local notes | Unreviewed observations, hypotheses and deferred questions | `<report-root>/notes/<hutch>/` |
| GitHub issue records | Shared failure modes, occurrences, investigation status and outcomes | DAQ-owned issue tracker, destination still to be confirmed |
| DAQ skills and references | Reusable investigation methods and reviewed lessons | Upstream DAQ-owned versioned skill source |
| DAQ Agent skills | Reporting/chat/note workflow and output contracts | DAQ Agent package |

Proposed flow: known-issue lookup -> scoped investigation -> local notes -> reviewed
issue draft -> publish or update an existing issue -> distill stable lessons into
DAQ skill/reference changes through code review.

Do not create one issue per log line or automatically turn every report into an
issue. Search for candidate failure modes, compare signatures and release/component
applicability, and have the reviewer decide whether an occurrence belongs to an
existing issue. Keep investigating, workaround available, verified fix and deferred
states explicit; issue closure alone does not establish a verified solution.

A useful shared record includes symptoms/signature, affected releases/components,
first/last occurrence, relevant hutch/session context, observations vs hypotheses,
workaround or fix plus verification evidence, unresolved questions, and evidence
references. Public issue text must not depend on inaccessible home-directory links
or silently publish private raw logs. Prepare a reviewable appropriately scoped
summary; keep private evidence references separate when needed.

DAQ Agent should own bounded GitHub reads/writes and credentials. The upstream
history skill should own diagnostic matching and record conventions. Cache issue
ID/URL, content, retrieval time and source update time with investigations so later
answers remain attributable even when issues change. Treat issue text as historical
evidence rather than instructions or automatically applicable current truth.

Saving `/note` remains private and local. A future explicit knowledge-proposal
operation should draft an issue/update and show its destination and content before
publication. This review does not authorize publishing any issue or changing DAQ.

## Suggested next steps

1. Obtain the missing history skill and resolve its issue destination/schema.
2. Review and test a new pin for the existing router/log skills separately from
   enabling new workflows; test historical supplied-evidence constraints.
3. Agree on machine-readable snapshot inputs/results and explicit unavailable legs.
4. Add read-only cached known-issue lookup and local issue drafting before issue writes.
5. Add separately scoped metrics/ConfigDB/live-state adapters as access becomes available.

## Source references

- [Compared commits](https://github.com/slac-lcls/lcls2/compare/198b6aa95229ef0e4ac5023c2a0d2e611124d46e...d6229a1d2e6395e3d67ac63b1c45096d9b523e82)
- [Skill README and advertised history workflow](https://github.com/slac-lcls/lcls2/blob/d6229a1d2e6395e3d67ac63b1c45096d9b523e82/psana/psana/skills/README.md#L15-L60)
- [Snapshot scope and investigation](https://github.com/slac-lcls/lcls2/blob/d6229a1d2e6395e3d67ac63b1c45096d9b523e82/psana/psana/skills/psana-daq-snapshot/SKILL.md#L26-L165)
- [Log session counting](https://github.com/slac-lcls/lcls2/blob/d6229a1d2e6395e3d67ac63b1c45096d9b523e82/psana/psana/skills/psana-daq-logs/SKILL.md#L65-L81)
- [ConfigDB historical correlation](https://github.com/slac-lcls/lcls2/blob/d6229a1d2e6395e3d67ac63b1c45096d9b523e82/psana/psana/skills/psana-configdb/SKILL.md#L96-L119)
