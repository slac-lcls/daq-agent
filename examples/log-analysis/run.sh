#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec python -m daq_agent analyze-logs \
  --config "$repo_dir/config/hutches/tmo.toml" \
  --from 2026-09-18 --to 2026-09-19 \
  --log "$repo_dir/evals/cases/configure-permission/control.log" \
  --log "$repo_dir/evals/cases/configure-permission/teb0.log" \
  --synthetic "$@"
