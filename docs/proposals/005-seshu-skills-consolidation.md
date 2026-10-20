# Consolidating Seshu's updated DAQ skills

Status: review and consolidation implemented 2026-10-19. The comparison below
records the starting state; the implementation record at the end describes the
adopted pin. History service integration remains proposed.

## Acquisition at the start of review

DAQ Agent reads `[daq_skills]` from `config/hutches/tmo.toml` or the installed
`src/daq_agent/profiles/tmo.toml`. Both selected
`slac-lcls/lcls2`, directory `psana/psana/skills`, at commit
`606038fed893ce788f1b865418ae6a569f66dc1d` from
[PR #131](https://github.com/slac-lcls/lcls2/pull/131).
The configured branch, `codex/psana-daq-skills-review`, is descriptive metadata;
only the full SHA determines fetched content.

`src/daq_agent/skill_sources.py` fetches that commit over HTTPS into a temporary
Git object store, without checking out or executing upstream code. It retains
the selected skill directories and optional suite README in a source-keyed cache,
validates frontmatter/file types/size limits, and records SHA-256 hashes. Reports
copy those verified bytes into their private artifacts. Chat and task transfer
reuse retained skills, so a new pin does not change existing investigations.
Personal `~/.codex/skills` and `~/.claude/skills` are not this dependency source.
AMI package discovery is also not the application's acquisition mechanism.
See [implemented integration](../skills-integration.md).

## Verified upstream state

GitHub API checks on the review date showed both PR #131 and
[Seshu's PR #125](https://github.com/slac-lcls/lcls2/pull/125) still open and
unmerged. PR #125's branch is `features/psana-daq-monitor`, with head
`37233b1b9c9441c75b0eec9dbd07331139a54a72`.
Its latest skill-changing commit is
`a8d4b4519be16e8e92365d9851c22e884f18ec25`; the one subsequent commit changes
logging code only. The skill-tree comparison below uses that exact skill commit.

| Change | Consequence for DAQ Agent |
| --- | --- |
| `9b4a2bf8b`: snapshot workflow folded into `psana-daq`; `psana-daq-snapshot` removed | Updating only the SHA fails validation because our selected snapshot skill no longer exists. |
| `5f2f9f48b`: history skill, issue/local-store search, case staging and repeated-finding condensation added | These require capabilities and evidence contracts that the application does not currently provide. |
| `b7a523235`: history setup and filing instructions corrected | Useful upstream guidance, but not authorization or an application tool implementation. |
| `a8d4b4519`: several PR #131 concerns independently fixed | Avoid reapplying already-resolved changes wholesale. |

Seshu's fixes cover stale hutch availability, filter-before-count ordering,
strict zstd decoding, logs continuing into their launch month after rollover,
the Grafana query parameter contract, and empty-series versus zero-rate handling.
The router also now separates conclusion confidence from evidence provenance.

Source: [exact upstream skill tree](https://github.com/slac-lcls/lcls2/tree/a8d4b4519be16e8e92365d9851c22e884f18ec25/psana/psana/skills),
[comparison with our pin](https://github.com/slac-lcls/lcls2/compare/606038fed893ce788f1b865418ae6a569f66dc1d...a8d4b4519be16e8e92365d9851c22e884f18ec25).
These branches diverged; files present only in PR #131 were not necessarily
deliberately deleted by Seshu.

## Remaining reconciliation work upstream

Preserve Seshu's router/sweep/history structure and port the remaining semantic
fixes from PR #131 into their new owning sections:

1. **Historical ConfigDB attribution.** The newer ConfigDB skill still says an
   entry dated inside a run identifies the active configuration. Carry forward
   the distinction between database edits, candidate configurations, recorded
   Configure content and hardware application. Include candidates predating
   Configure; a mid-run edit need not have been applied. Keep historical-key
   retrieval limitations explicit.
2. **Historical identity and coverage.** Retain full dated launch identity,
   timezone/offset and DST ambiguity; a day/time prefix is not globally unique.
   File mtime is approximate activity evidence, not an authoritative run end.
   Accept supplied hutch/window/launch scope and inspect all relevant launches
   without demanding an interactive single-session choice or today's config.
3. **Evidence-limited composition.** Accept caller-provided evidence and tool
   availability. Missing logs/services must remain unavailable evidence, not a
   healthy/idle verdict. Optional external skills must not become mandatory.
   A historical task must not depend on current state or mandatory live preflight.
4. **Reference and example correctness.** Preserve the distinction between a
   field not consumed by a specialized detector algorithm and a field absent
   from generic Configure dumps. Retain failure-aware count/read examples and
   the synthetic command/launcher tests from PR #131, adapted to the new layout.
   Its operational-check reference is also absent from Seshu's tree; review
   useful content for its owning upstream sections rather than copying it locally.

This is an integration review, not a complete validation of every upstream
diagnostic claim. No production command was executed to validate these changes.

## Proposed adoption sequence

1. Prepare an upstream reconciliation against a fixed revision of Seshu's
   branch. Update or supersede PR #131 around the remaining fixes above; do not
   mechanically merge its old standalone snapshot design back into the suite.
   Keep diagnostic guidance and synthetic example tests maintained in LCLS2.
2. Once reviewed, pin the resulting full SHA in **both** TMO configurations.
   Select the five diagnostic skills: `psana-daq`, `psana-daq-logs`,
   `psana-daq-control`, `psana-daq-monitor`, and `psana-configdb`.
   Remove `psana-daq-snapshot`; defer `psana-daq-history` to a separate capability
   integration. The existing source loader can represent this five-skill suite.
3. Update application instructions to explicitly mark issue/local-store lookup
   and history handoff unavailable. Retain the findings/citation JSON contract,
   current evidence coverage, and runtime tool restrictions. Prior issue pointers
   cannot replace current evidence or silently skip launches. Update pin/list
   assertions and documentation while preserving old-report compatibility.
4. Validate synchronization and synthetic `--prepare-only` reporting in a
   separate cache/output directory; verify report/chat/transfer retention,
   reference reads, permissions and budgets. Run
   `python -m unittest discover -s tests -v`, and verify built package data/profile
   contents for the dependency release. No live DAQ or paid-model tests are needed.
5. Add bounded read-only issue/store retrieval separately, with captured source
   identity, retrieval/update times and hashes. Match release/component/session
   applicability and retain current occurrence evidence. Treat historical text
   as evidence, never instructions. Shared case writes and public issue publication
   require their own explicit application tools and review workflow; loading a
   skill alone must not enable them.

Keep private reports and `/note` records in the existing application store.
Seshu's shared reports/cases store is a separate format and visibility boundary;
do not mirror private artifacts there automatically. Existing deterministic
known-condition rules are also distinct from upstream issue-based condensation.

## Compatibility checks performed

Read-only inspection compared exact Git objects and validated all upstream skill
frontmatter with the current application's validator. GitHub metadata confirmed
that the newer branch head has no additional skill changes.

The proposed five skills plus README and the current packaged report-chat skill
total **185,322 bytes**, within the **196,608-byte** chat skill limit. Including
the new history skill raises this to **209,611 bytes**, which exceeds that limit.
Thus replacing snapshot with history in the six-entry list would also break
chat creation, independent of missing service adapters. Recheck size after
reconciliation; do not raise limits merely to load an unused writer workflow.

The initial review made no dependency or runtime changes; the subsequent
implementation is recorded below.


## Implementation record

The user approved consolidation. An isolated LCLS2 checkout was based on
`37233b1b9c9441c75b0eec9dbd07331139a54a72`. Commit
`179b2bfbe73901f394222922571a0753e7ce9a06` on
`codex/daq-skills-consolidated-evidence` carries the remaining corrections in
[upstream draft PR #191](https://github.com/slac-lcls/lcls2/pull/191). It preserves
Seshu's router/sweep and history layout, including the Grafana parameter fix, and
restores the failure-aware examples, operational reference and nine offline tests.
The history writer itself is unchanged. PR #131 remains open; #191 is its
reconciliation successor, not a merge or rewrite of Seshu's branch.

Both DAQ Agent TMO configurations now pin that exact commit and select five
diagnostic skills. Runtime instructions for reporting, chat and transfer explicitly
exclude unavailable history search/handoff and preserve current-evidence citations.
The existing findings schema, batch aggregation and known-condition rules remain.

Report changes: add application-recorded service coverage for Grafana, ConfigDB,
live DAQ state and GitHub/shared-store history to root/batch manifests and both
Markdown/HTML. Pass it through chat context and transfer report metadata. This
states that sources were not queried without relying on model-written limitations.
Old manifests lacking these fields display unknown query coverage; old six-skill
reports remain usable with their retained dependency.

The adopted five-skill suite plus report-chat instructions totals 187,481 bytes,
within the unchanged 196,608-byte limit. No production commands, paid model calls,
issue-history integration, shared-store writes or automatic issue publication
were introduced.

Validation completed:

- Upstream: all nine synthetic diagnostic-example tests passed, including a
  loopback-only HTTP receiver; frontmatter, local references and whitespace checked.
- DAQ Agent: `python -m unittest discover -s tests -v` ran 145 tests: 144 passed,
  one optional real-OpenCode integration test skipped because `DAQ_TEST_OPENCODE`
  was not set. Both legacy six-skill and new five-skill retention/chat paths pass.
- The exact published commit synchronized over HTTPS into an isolated cache.
  The bundled synthetic example prepared successfully without a model call.
- Using that actual fetched suite, synthetic runtime events exercised completed
  reporting/citation audits and chat; both OpenCode and Claude transfers prepared
  with matching pinned bytes and coverage metadata. No real model was queried.
- Built and installed the wheel in the project's `.venv`; verified bundled
  profiles/skills and package code. The preexisting installation was not editable,
  so reinstalling was necessary for the CLI to use these source changes.
