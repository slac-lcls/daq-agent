# Diagnostic evaluation cases

This directory holds synthetic or reviewed sanitized cases and semantic review
expectations. No production incidents are bundled.

- `cases/configure-permission/`: synthetic control and TEB log excerpts.
- `expected/configure-permission.json`: observations to look for and unsupported
  conclusions to reject. This is an initial review rubric, not an expert-validated
  diagnosis of a real incident.

See [the evaluation strategy](../docs/evaluation.md) for the case contract and
metrics. Add `cases/` and `expected/` when the first reviewed fixture is ready.
Keep full operational snapshots outside the public repository.
