#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$ROOT/tools/run_next_loop_round.py" --root "$ROOT" "$@"
