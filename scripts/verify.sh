#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

bash "$ROOT/scripts/validate-install.sh"
(cd "$ROOT" && python3 -m unittest tests/test_timing_report.py)
python3 "$ROOT/tools/run_next_loop_round.py" --root "$ROOT" --dry-run >/tmp/viral-replica-loop-decision.txt
python3 "$ROOT/scripts/generate-report.py" --root "$ROOT" --out "$ROOT/output/loop-report.md" --last-decision /tmp/viral-replica-loop-decision.txt
python3 "$ROOT/tools/timing_report.py" --root "$ROOT" --out "$ROOT/output/timing-report.md" --job job-003 --job job-005 --job job-006

echo "Verify passed"
echo "Dry-run decision: /tmp/viral-replica-loop-decision.txt"
echo "Report: $ROOT/output/loop-report.md"
echo "Timing report: $ROOT/output/timing-report.md"
