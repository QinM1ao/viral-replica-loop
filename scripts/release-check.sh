#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 "$ROOT/scripts/scan-secrets.py" --root "$ROOT"
"$ROOT/scripts/validate-install.sh"

if [[ "${STRICT_SKILL_CHECK:-0}" == "1" ]]; then
  python3 "$ROOT/scripts/skill-release-check.py" --root "$ROOT" --strict
fi

(cd "$ROOT" && python3 -m unittest discover -s tests)
python3 "$ROOT/tools/run_next_loop_round.py" --root "$ROOT" --dry-run >/tmp/viral-replica-loop-release-decision.txt

echo "Release check passed"
echo "Dry-run decision: /tmp/viral-replica-loop-release-decision.txt"
