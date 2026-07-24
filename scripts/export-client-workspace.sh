#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT=""
FORCE=0
ZIP=0
REFERENCE_JOB=""

usage() {
  cat <<'EOF'
Usage:
  scripts/export-client-workspace.sh --out /path/to/client-workspace [--force] [--zip]
  scripts/export-client-workspace.sh --out /path/to/client-workspace --include-reference-job job-008

Creates a clean client handoff copy from the current Git-managed working tree.
It does not modify the current working directory.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --out)
      OUT="${2:-}"
      shift 2
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --zip)
      ZIP=1
      shift
      ;;
    --include-reference-job)
      REFERENCE_JOB="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$OUT" ]]; then
  usage >&2
  exit 2
fi

OUT="$(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")"
if [[ -e "$OUT" ]]; then
  if [[ "$FORCE" -ne 1 ]]; then
    echo "Output already exists: $OUT" >&2
    echo "Use --force to replace it." >&2
    exit 1
  fi
  rm -rf "$OUT"
fi

mkdir -p "$OUT"
FILE_LIST="$(mktemp)"
trap 'rm -f "$FILE_LIST"' EXIT
(cd "$ROOT" && git ls-files -z --cached --others --exclude-standard) > "$FILE_LIST"
python3 - "$ROOT" "$OUT" "$FILE_LIST" <<'PY'
import shutil
import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
file_list = Path(sys.argv[3])

for raw in file_list.read_bytes().split(b"\0"):
    if not raw:
        continue
    rel = Path(raw.decode("utf-8"))
    src = root / rel
    dst = out / rel
    if not src.is_file():
        continue
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
PY

mkdir -p "$OUT/output" "$OUT/logs" "$OUT/references/screenshots" "$OUT/references/source-notes"
find "$OUT/output" -mindepth 1 ! -name ".gitkeep" -exec rm -rf {} +
find "$OUT/logs" -mindepth 1 ! -name ".gitkeep" -exec rm -rf {} +
touch "$OUT/output/.gitkeep" "$OUT/logs/.gitkeep" \
  "$OUT/references/screenshots/.gitkeep" "$OUT/references/source-notes/.gitkeep"
touch "$OUT/logs/loop_events.jsonl" "$OUT/logs/review_feedback.jsonl"

cp "$OUT/BRIEF.example.md" "$OUT/BRIEF.md"
cp "$OUT/STATE.example.md" "$OUT/STATE.md"
printf '%s\n' 'id,status,video_path,product_name,client_profile,product_assets,person_assets,audio_assets,target_duration,notes,output_dir,last_artifact,next_stage,needs_user_confirmation' > "$OUT/jobs.csv"
cat > "$OUT/RUNNER_STATE.json" <<'EOF'
{
  "version": 1,
  "retry_limit": 2,
  "updated_at": null,
  "jobs": {}
}
EOF
rm -f "$OUT/RUNNER_LAST_DECISION.md" "$OUT/RUNNER_LAST_TRANSITION.md"
rm -f "$OUT/.run-loop.lock" "$OUT/.sync-inbox-to-jobs.lock"

if [[ -n "$REFERENCE_JOB" ]]; then
  python3 - "$ROOT" "$OUT" "$REFERENCE_JOB" <<'PY'
import shutil
import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
job_id = sys.argv[3]
src_root = root / "output" / job_id
dst_root = out / "output" / job_id

if not src_root.exists():
    raise SystemExit(f"Reference job not found: {src_root}")

items = [
    "product_profile.json",
    "seedance_web_final",
    "final-images",
    "prompt_validation_source_speaker_20260706",
    "visual-assets/approved_visual_manifest.json",
    "checks/pre_seedance_pack_gate_review.md",
    "checks/pre_seedance_pack_gate_review_qc.md",
    "checks/pre_seedance_pack_seedance_prompt_contract_qc.md",
    "checks/pre_seedance_pack_visual_asset_manifest_qc.md",
]

for rel in items:
    src = src_root / rel
    if not src.exists():
        continue
    dst = dst_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)

readme = dst_root / "README_REFERENCE_ONLY.md"
readme.parent.mkdir(parents=True, exist_ok=True)
readme.write_text(
    "# Reference Job\n\n"
    f"This is a reference-only artifact snapshot copied from `{job_id}`.\n"
    "It is not queued in `jobs.csv` and does not affect new client runs.\n"
    "Use it as a known-good Kongfengchun handoff example for asset layout, prompts, manifests, and QC shape.\n",
    encoding="utf-8",
)
PY
fi

find "$OUT" -name ".DS_Store" -delete
chmod +x "$OUT/run-loop.sh" "$OUT/reset-loop.sh" "$OUT/install.sh" "$OUT"/scripts/*.sh 2>/dev/null || true

if [[ "$ZIP" -eq 1 ]]; then
  ZIP_PATH="${OUT%/}.zip"
  rm -f "$ZIP_PATH"
  (cd "$(dirname "$OUT")" && zip -qr "$ZIP_PATH" "$(basename "$OUT")")
  echo "Client workspace zip: $ZIP_PATH"
fi

echo "Client workspace exported: $OUT"
echo "Next in exported copy: ./install.sh"
