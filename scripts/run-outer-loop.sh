#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 "$ROOT/.agents/skills/viral-replica-improver/scripts/collect-improvement-evidence.py" --root "$ROOT"
python3 "$ROOT/scripts/skill-release-check.py" --root "$ROOT" --skill viral-replica-improver --strict
python3 "$ROOT/scripts/skill-release-check.py" --root "$ROOT" --skill viral-replica --strict

echo "Outer loop proposal generated and skill checks passed"
