# Testing and diagnostic evaluation

## Software tests

Run `python -m unittest discover -s tests -v`. Initial tests cover time windows
(including daylight-saving changes), explicit timestamp offsets, partition/model
configuration validation, honest plan status, and packaged skill resources.
CI builds and installs the wheel before running tests on Python 3.11 and 3.13.

Add meaningful tests with new behavior: evidence truncation, restart identity,
counter resets, grouping, citation validation, queue retry limits, and forbidden
tool actions. Unit tests use fixtures, not production DAQ or paid model calls.

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
