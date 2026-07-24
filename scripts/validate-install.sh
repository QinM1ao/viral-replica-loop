#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

required=(
  README.md
  AGENTS.md
  LOOP.md
  STATE.md
  BRIEF.md
  BRIEF.example.md
  requirements.txt
  jobs.csv
  RUNNER_STATE.json
  COST_POLICY.md
  QC_RULES.md
  PRODUCT_CONSTRAINTS.md
  rules/STAGE_RULES.json
  scripts/new-task.py
  scripts/export-client-workspace.sh
  scripts/release-check.sh
  scripts/run-outer-loop.sh
  scripts/skill-release-check.py
  tools/run_next_loop_round.py
  tools/checker_review_qc.py
  tools/record_review_feedback.py
  tools/audio_duration_qc.py
  tools/codex_imagegen_contract_qc.py
  tools/cross_part_continuity_qc.py
  tools/skincare_progression_qc.py
  tools/storyboard_geometry_qc.py
  tools/visual_asset_manifest_qc.py
  workers/checker_worker.md
  .codex/agents/viral-replica-checker.toml
  .agents/skills/viral-replica/SKILL.md
  .agents/skills/viral-replica/manifest.json
  .agents/skills/viral-replica/agents/interface.yaml
  .agents/skills/viral-replica/evals/trigger_cases.json
  .agents/skills/viral-replica/evals/output_cases.json
  .agents/skills/viral-replica/references/loop-operating-contract.md
  .agents/skills/viral-replica/reports/skill_ir.md
  .agents/skills/viral-replica/reports/trust_report.md
  .agents/skills/viral-replica/reports/output_quality_scorecard.md
  .agents/skills/viral-replica-improver/SKILL.md
  .agents/skills/viral-replica-improver/manifest.json
  .agents/skills/viral-replica-improver/agents/interface.yaml
  .agents/skills/viral-replica-improver/evals/trigger_cases.json
  .agents/skills/viral-replica-improver/evals/output_cases.json
  .agents/skills/viral-replica-improver/references/outer-loop-contract.md
  .agents/skills/viral-replica-improver/reports/skill_ir.md
  .agents/skills/viral-replica-improver/reports/trust_report.md
  .agents/skills/viral-replica-improver/reports/output_quality_scorecard.md
  .agents/skills/viral-replica-improver/scripts/collect-improvement-evidence.py
  docs/review-feedback-ledger.md
  .agents/skills/video-replication/SKILL.md
  .agents/skills/video-replication/manifest.json
  .agents/skills/video-replication/agents/interface.yaml
  .agents/skills/video-replication/evals/trigger_cases.json
  .agents/skills/video-replication/evals/output_cases.json
  .agents/skills/video-replication/reports/trust_report.md
  .agents/skills/video-replication/reports/output_quality_scorecard.md
  .agents/skills/video-replication/references/codex-imagegen-direct.md
  .agents/skills/video-replication/references/skincare-beauty-replication.md
  .agents/skills/video-replication/references/seedance-20-prompt-standard.md
  .agents/skills/video-replication/references/source-script-lock.md
  .agents/skills/video-replication/references/storyboard-derived-identities.md
  .agents/skills/video-replication/references/seedance-qc-gates.md
  .agents/skills/video-subtitle-removal/SKILL.md
  .agents/skills/video-subtitle-removal/agents/interface.yaml
  .agents/skills/video-subtitle-removal/evals/semantic_config.json
  .agents/skills/video-subtitle-removal/evals/trigger_cases.json
  .agents/skills/video-subtitle-removal/references/visual-qc.md
  docs/client-workspace-handoff.md
)

missing=0
for file in "${required[@]}"; do
  if [[ ! -e "$ROOT/$file" ]]; then
    echo "Missing: $file"
    missing=1
  fi
done

if [[ "$missing" -ne 0 ]]; then
  exit 1
fi

python3 -m py_compile \
  "$ROOT"/tools/*.py \
  "$ROOT"/scripts/*.py \
  "$ROOT"/.agents/skills/viral-replica/scripts/*.py \
  "$ROOT"/.agents/skills/viral-replica-improver/scripts/*.py
python3 "$ROOT/scripts/skill-release-check.py" --root "$ROOT"

python3 - "$ROOT" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
for rel in ["rules/STAGE_RULES.json", "RUNNER_STATE.json"]:
    with (root / rel).open(encoding="utf-8") as f:
        json.load(f)

rules = json.loads((root / "rules/STAGE_RULES.json").read_text(encoding="utf-8"))
if not isinstance(rules.get("rules"), list):
    raise SystemExit("rules/STAGE_RULES.json must contain a rules list")

for rule in rules["rules"]:
    for key in ["worker_file", "gate", "script_file"]:
        value = rule.get(key)
        if value and value != "none" and not (root / value).exists():
            raise SystemExit(f"Rule {rule.get('id')} points to missing {key}: {value}")
    self_audit = rule.get("self_audit", {})
    if self_audit:
        for key in ["worker_file", "script_file", "checker_agent"]:
            value = self_audit.get(key)
            if value and value != "none" and not (root / value).exists():
                raise SystemExit(f"Rule {rule.get('id')} points to missing self_audit {key}: {value}")

print("Validation passed")
PY
