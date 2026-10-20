# Diagnostic evaluation cases

This directory holds synthetic or reviewed sanitized cases and semantic review
expectations. No production incidents are bundled.

- `cases/configure-permission/`: initial Configure failure; later outcome unknown.
- `cases/configure-recovered/`: initial failure followed by a successful retry.
- `cases/known-reset-only/`: two known reset lines; initial report needs no model.
- `cases/mixed-reset-timing/`: known reset plus an unresolved timing error.
- `expected/*.json`: observations, unknowns, unsupported conclusions and original
  citation targets. These are engineering rubrics, not expert-validated diagnoses.
- `baseline-inputs.json`: fixed scope, input hashes, rule selections and skill pin.

See [the evaluation strategy](../docs/evaluation.md) for the case contract and
metrics and [the comparison baseline](../docs/evaluation/report-baseline.md) for
model-free preparation commands and the retained comparison results.
Keep full operational snapshots outside the public repository.
