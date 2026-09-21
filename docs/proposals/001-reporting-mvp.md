# Proposal 001: TMO robustness reporting

Status: full reporting workflow proposed; configuration, planning, and a narrower
[log-excerpt analysis workflow](../workflows/log-analysis.md) implemented.
Date: 2026-09-21.

## Outcome

Produce one useful, verifiable report over a selected historical TMO operating
window. Support the hutch monitor's regular review of recurring DAQ/AMI failures
and presentation to the DAQ group. Distribution remains a separate action.

## Command interface

Implemented today:

```bash
daq-agent config --config config/hutches/tmo.toml
daq-agent plan-report --config config/hutches/tmo.toml \
  --from 2026-09-18 --to 2026-09-20
```

Planned interfaces (not executable yet):

```bash
daq-agent report --hutch tmo --partition 0 --from 2026-09-18 --to 2026-09-20
daq-agent chat --hutch tmo --partition 0
daq-agent chat --hutch tmo --model slac/us.anthropic.claude-fable-5-1
```

`report` should run without a terminal conversation, save validated findings and a
Markdown report, and return artifact locations. `chat` should prepare the same
skills/tools and open OpenCode with a selected default model. The configuration
and source-access resolution for these commands remains to be implemented.

Dates are local midnight in a named timezone. Timestamps require explicit offsets.
Interpret intervals as inclusive start, exclusive end, and persist UTC instants.
Confirm the intended partition; a sample value is not live discovery.

## Report contract

- Scope and coverage: hutch, partition, operating exposure, sessions/releases,
  source availability, query bounds, and missing/truncated evidence.
- Ranked incident families: distinct occurrences, affected components/runs,
  measured impact or an explicit unknown, and comparison with a prior window.
- Per-finding observations, hypotheses, confirmed causes when supported,
  evidence references, and smallest useful next check.
- Baseline/new/recurring/reviewed-resolved status with the basis for comparison.
- Provenance: application/runtime/model/skill versions and evidence references.

Use deterministic calculations for counts and rates. Document the grouping rule;
one failure producing many messages must not dominate recurrence ranking.
Where available, normalize comparisons by operating hours, runs, or transitions.

## Implementation sequence

1. Choose one known operating window and establish expected findings with Mona.
2. Review/pin diagnostic skills and inventory required source/tool dependencies.
3. Implement bounded historical evidence collection and snapshot records.
4. Integrate OpenCode with explicit provider, skill, and permission configuration.
5. Validate structured findings and citations; render/save the draft report.
6. Replay evaluation cases and review missed incidents/false positives.
7. Add interactive entry, then scheduling once manual reports are useful.

## Acceptance

The first report identifies the known incident(s), links to verifiable evidence,
does not invent causes or impact, handles missing data explicitly, and performs
no production mutation. Capture cost, duration, tool failures, and reviewer
corrections. Set quality thresholds after establishing the first baseline.

No dashboard, vector database, model training, or multi-agent orchestration is
required for the initial milestone.

The log-analysis prototype is a first executable slice. It does not establish
complete historical coverage, operating exposure, recurrence ranking, or upstream
skill integration, so it is not yet the full robustness report described above.
