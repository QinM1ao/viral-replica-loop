#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == "--job-run" ]]; then
  shift
  exec python3 "$ROOT/tools/job_run.py" "$@"
fi
python3 "$ROOT/tools/run_next_loop_round.py" --root "$ROOT" "$@"
