# Report consistency baseline

Status: initial synthetic baseline and replay rubric established 2026-10-20.
This is not a claim of equivalent model quality or completed operational
validation. Baseline source: merged PR #7, commit
`ab75ff65f0a34d06216a76373053531d1c8f4915`, application 0.9.2.

## Fixed inputs

[baseline-inputs.json](../../evals/baseline-inputs.json) records the hutch,
explicit UTC window, source hashes, application reporting skill hash, selected
upstream skills and exact upstream commit
`179b2bfbe73901f394222922571a0753e7ce9a06`.
Use the same inputs and known-condition policy for each comparison.
Retain generated reports privately, outside the repository.

| Case | Question tested | Current evidence |
| --- | --- | --- |
| `configure-permission` | Failed Configure and nearby queue-access error; later outcome unknown | One retained live run per runtime, re-reviewed below |
| `configure-recovered` | Preserve the initial failure and the later successful Configure; do not invent successful data taking | Both runtime preparations verified; model evaluation pending |
| `known-reset-only` | Two matched lines, unknown recovery, no model call; evidence available in follow-up | Both runtime preparations and zero-model completed reports verified |
| `mixed-reset-timing` | Exclude the known reset from initial model inputs but preserve an unresolved timing error | Both runtime preparations and exclusion/count assertions verified; model evaluation pending |

All cases are synthetic and explicitly labelled. Expected observations,
unsupported claims and original citation targets are in `evals/expected/`.
Citation targets identify supporting input lines; they are not necessarily the
source IDs or line numbers of generated follow-up appendices. Map through the
saved inventory. The new fixtures are engineering rubrics, not expert-approved
operational incident diagnoses.

## Retained live comparison

The two previously authorized synthetic runs on 2026-10-20 used identical
control/teb0 bytes, reporting skill and five-skill upstream inventory. Source
hashes match the checked-in `configure-permission` inputs. Both used the UTC
window `[2026-09-18T00:00:00Z, 2026-09-19T00:00:00Z)`, with known-condition
filtering disabled and external services unavailable.

These are historical runs made before the merged checkpoint. Their manifests
record application version **0.9.1**, not 0.9.2; they do not retain an immutable
application Git revision. Do not relabel them as fresh runs of merged main.
Current code successfully reloads their evidence and skills. This review
performed no new model calls.

| Criterion | OpenCode 1.2.10 / requested Sonnet 5 | Central Claude 2.1.285 / resolved Opus 5.5 `[1m]`, medium |
| --- | --- | --- |
| Failed Configure + Results queue permission denial | Present | Present |
| Hutch, partition, launch and timestamp attribution | Preserved | Preserved |
| Queue-access link expressed as hypothesis | Yes | Yes |
| Queue owner/stale queue not asserted as proven | Yes | Yes |
| Later recovery explicitly unknown throughout report | Pass in reviewed output | **Fail:** summary and a limitation overstate the launch outcome, despite a finding acknowledging unknown recovery |
| External services/history marked not queried | Yes | Yes |
| Citation locations valid and supporting the stated errors | Yes | Yes |
| Incident grouping | One combined finding | Two related findings for the same episode |
| Overall semantic rubric | Pass for this case only | **Fail for scope overstatement** |

The Opus claim that the launch never reached configured extends beyond the
three-second control excerpt. The permissible claim is that this Configure
attempt failed and later recovery is unknown. Review the summary and limitations
as carefully as findings; contradictory uncertainty elsewhere does not cancel
an unsupported assertion.

Artifact identities for locating the private retained synthetic results:

| Artifact | SHA-256 |
| --- | --- |
| OpenCode findings JSON | `d7ff4d0d5fd468bdf8c4e3f9825a75bc760eb6d8c5f7239283bf527ef4e646a5` |
| Claude findings JSON | `2b84df767a5098a871019b855a104ee85690251d2452b91802385f46632d60c4` |
| OpenCode manifest | `d8de23583691bafce6a1b5a0db0022d417d58f49420707be6f5b737b7c839d77` |
| Claude manifest | `0dfdf0268e1223367ce5091f405abbb59fafb658b3f8dad0a7cb82e0d5700beb` |

The retained upstream file-inventory digest is
`38100f4d892b4e36543b609075a0d9894ab1cc83c7439c78d98460bddb890eec`
(SHA-256 of `json.dumps(upstream_skills["files"], sort_keys=True).encode()`).
Agent review established this table; independent domain-expert review is pending.
Raw model outputs and transcripts remain outside version control.

## Review contract for future comparisons

Record application Git revision and installed wheel identity, input hashes and
scope, preprocessing rules/version, actual retained skill files/hashes, runtime
version, requested/resolved model, effort, tool availability, returned usage
and elapsed time. Unknown resolved identities must remain unknown. Runtime and
model both differ in the historical comparison, so it cannot isolate which
caused a difference.

Evaluate each required observation and unknown as present, missing or
contradicted, citing the output field and retained evidence. Evaluate every
unsupported claim across summary, findings, limitations and saved follow-up
answers. Count independent incident episodes separately from finding objects.
Document splits/merges and deduplication explicitly.

Require all critical observations, correct scope and evidence citations, and
no unsupported root-cause, recovery, health or service-query assertions for a
case to pass. Exact prose and finding counts are not gates. A deterministic
schema/citation-location pass alone is not a semantic pass.

For subsequent skill consolidation, compare the current pin and a separately
reviewed candidate pin with the same model/runtime and evidence first. Then
compare runtimes/models while holding the skill pin fixed. Save both inventories;
never point deployed sessions at a moving branch or replace an old report's
retained skills. Native sessions using personal skills are another explicitly
labelled condition, not equivalent to the bounded reporting baseline.

For every model-bearing case, schedule at least three independent runs per
condition, preserving all failures and retries. This is a proposed minimum
variability check, not a statistical equivalence guarantee. Add reviewed
operational cases before claiming representative production quality.

## Repeat preparation without model calls

From the repository root with the tested installed environment:

```bash
daq-agent sync-skills --config config/hutches/tmo.toml
baseline_output=$(mktemp -d /tmp/daq-baseline.XXXXXX)
for case in configure-permission configure-recovered known-reset-only mixed-reset-timing; do
  logs=()
  for path in "evals/cases/$case/"*.log; do logs+=(--log "$path"); done
  policy=()
  case "$case" in configure-*) policy=(--no-known-conditions);; esac
  for runtime in claude opencode; do
    model=opus
    if [ "$runtime" = opencode ]; then model=slac/us.anthropic.claude-sonnet-5; fi
    daq-agent report --hutch tmo --config config/hutches/tmo.toml \
      --from 2026-09-18T00:00:00+00:00 --to 2026-09-19T00:00:00+00:00 \
      --runtime "$runtime" --model "$model" --synthetic --prepare-only \
      "${logs[@]}" "${policy[@]}" --output "$baseline_output/$case-$runtime"
  done
done
```

This is Bash. Before replay, verify fixture, skill and pin hashes against
`evals/baseline-inputs.json`; if they differ, label a new baseline condition.
`sync-skills` fetches the pinned dependency but makes no model calls. Preparation
does not verify model entitlement. Use fresh output directories for a separately
scheduled live replay, removing `--prepare-only` only when model usage is intended.
Do not use `--local-skills-only` for a pinned-suite comparison.

## Next evaluation work

The first priority is the scope-overstatement failure: test any reporting
instruction change against both Configure cases, including the full summary.
Then complete repeated live runs on the mixed case and known-condition follow-up.
The current baseline supports feature development; it does not certify semantic
equivalence across runtimes or with Seshu's independent report workflow.
