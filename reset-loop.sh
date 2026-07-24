#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${1:-}" != "--yes" ]]; then
  echo "This resets STATE.md, jobs.csv, RUNNER_STATE.json, and runner decision files."
  echo "Run: ./reset-loop.sh --yes"
  echo "Optional: ./reset-loop.sh --yes --with-output"
  exit 1
fi

cp "$ROOT/STATE.example.md" "$ROOT/STATE.md"
printf '%s\n' 'id,status,video_path,product_name,client_profile,product_assets,person_assets,audio_assets,target_duration,notes,output_dir,last_artifact,next_stage,needs_user_confirmation' > "$ROOT/jobs.csv"
printf '%s\n' '{' '  "version": 1,' '  "retry_limit": 2,' '  "updated_at": null,' '  "jobs": {}' '}' > "$ROOT/RUNNER_STATE.json"
rm -f "$ROOT/RUNNER_LAST_DECISION.md" "$ROOT/RUNNER_LAST_TRANSITION.md"
rm -f "$ROOT/logs/loop_events.jsonl"
touch "$ROOT/logs/.gitkeep"

if [[ "${2:-}" == "--with-output" ]]; then
  find "$ROOT/output" -mindepth 1 ! -name ".gitkeep" -exec rm -rf {} +
fi

echo "Loop state reset."
