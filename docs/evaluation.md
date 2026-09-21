# Testing and diagnostic evaluation

## Software tests

Run `python -m unittest discover -s tests -v`. Initial tests cover time windows
(including daylight-saving changes), explicit timestamp offsets, partition/model
configuration validation, honest plan status, and packaged skill resources.
CI builds and installs the wheel before running tests on Python 3.11 and 3.13.

The log-analysis tests exercise a fake OpenCode subprocess through the real
orchestration path, including failed citations, timeout handling, credential
reference validation, restricted session configuration, and output preservation.
CI also prepares the example without a model call. A successful fake-runtime test
does not establish actual model or gateway compatibility.

`evals/cases/configure-permission/` contains a synthetic two-file example, with
semantic expectations in `evals/expected/configure-permission.json`. The manual
example command invokes real OpenCode; assess its report against those expectations.

Add meaningful tests with new behavior: evidence truncation, restart identity,
counter resets, grouping, citation validation, queue retry limits, and forbidden
tool actions. Unit tests use fixtures, not production DAQ or paid model calls.

Viewer tests cover completed-report selection across hutches, legacy layouts,
snapshot integrity, HTML escaping, citation links, private personal settings, and
a real loopback HTTP server with token and asset-access checks. No model calls
are needed for report viewing or these checks.

## Agent evaluations

Each case should have a fixed scope, synthetic or reviewed sanitized evidence,
expert-reviewed expected observations, supported hypotheses, known unknowns,
required citations, and assertions about actions that must not occur.

Evaluate correctness and evidence grounding, not exact prose. Track missed
incidents, false alarms, unsupported causes, citation accuracy, coverage honesty,
cost, elapsed time, and reviewer effort. Compare models on the same evidence and
tool/runtime configuration. Treat repeated-run variability as part of evaluation.

Suggested first cases: a failed Configure, repeated messages from one incident,
an AMI input-delivery interruption, an idle window, and a metrics collection gap.
These are proposed cases, not incidents observed by this application.

Skill/runtime/model updates should replay relevant cases before deployment.
Historical log timestamps and release differences must be represented rather
than cleaned away so thoroughly that the difficult operational cases disappear.

Pinned skill tests use a local Git fixture to verify exact-commit selection after
a branch advances, supporting-file retention, offline reuse, tamper detection,
invalid metadata/symlink rejection, and required runtime skill loads. Normal CI
uses `--local-skills-only` for its preparation smoke test and makes no network or
model calls for skill integration tests.
