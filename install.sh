#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$ROOT/output" "$ROOT/logs" "$ROOT/references/screenshots" "$ROOT/references/source-notes"
touch "$ROOT/output/.gitkeep" "$ROOT/logs/.gitkeep" "$ROOT/references/screenshots/.gitkeep" "$ROOT/references/source-notes/.gitkeep"

chmod +x "$ROOT/run-loop.sh" "$ROOT/reset-loop.sh" "$ROOT/scripts/verify.sh" "$ROOT/scripts/validate-install.sh" "$ROOT/scripts/generate-report.py" "$ROOT/scripts/new-task.py" "$ROOT/.agents/skills/viral-replica/scripts/extract-reference.py" 2>/dev/null || true

if ! command -v python3 >/dev/null 2>&1; then
  echo "Missing python3"
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "Warning: ffmpeg is not installed. Story/video QC scripts will be limited."
fi

if ! command -v ffprobe >/dev/null 2>&1; then
  echo "Warning: ffprobe is not installed. Final video QC will be limited."
fi

python3 - "$ROOT/requirements.txt" <<'PY'
import importlib.util
import sys

requirements_path = sys.argv[1]
missing = [
    name for name in ("httpx", "PIL")
    if importlib.util.find_spec(name) is None
]
if missing:
    print("Missing Python packages: " + ", ".join(missing))
    print(f"Install them with: python3 -m pip install -r {requirements_path}")
    sys.exit(1)
PY

"$ROOT/scripts/validate-install.sh"

echo "Loop kit installed: $ROOT"
