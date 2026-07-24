#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from evidence_ledger import build_ledger


REPAIR_HINTS = {
    "cross_part_continuity": {
        "retry_variable": "cross_part_continuity",
        "preferred_prompt_globs": ["image-batch/prompts/*cross_part*repair_required.md"],
        "focus": "Repair the Part image that breaks identity, wardrobe, scene, lighting, or seam continuity.",
    },
    "skincare_progression": {
        "retry_variable": "skin_progression",
        "preferred_prompt_globs": ["image-batch/prompts/*skin_progression*repair_required.md"],
        "focus": "Repair the pre-wash or after-wash image so the before/after effect reads in the right order.",
    },
    "storyboard_geometry": {
        "retry_variable": "storyboard_geometry",
        "preferred_prompt_globs": ["image-batch/prompts/*geometry*repair_required.md", "image-batch/prompts/*contract*repair*.md"],
        "focus": "Repair the promoted storyboard so it keeps the source Part canvas, 12-panel geometry, and shot order.",
    },
    "codex_imagegen_contract": {
        "retry_variable": "codex_imagegen_contract",
        "preferred_prompt_globs": ["image-batch/prompts/*contract*repair*.md"],
        "focus": "Repair the GPT Image contract or rerun using Matpool refs and settings.",
    },
}


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_markdown(path, plan):
    lines = [
        "# Image Batch Run Plan",
        "",
        f"- Job: `{plan['job_id']}`",
        f"- Repair: `{plan['repair']}`",
        f"- Retry variable: `{plan['retry_variable']}`",
        f"- Focus: {plan['focus']}",
        "",
        "## Evidence",
        "",
    ]
    for item in plan["evidence"]:
        lines.append(f"- `{item}`")
    if not plan["evidence"]:
        lines.append("- No blocking evidence found.")

    lines.extend(["", "## Prompt Inputs", ""])
    for item in plan["prompt_inputs"]:
        lines.append(f"- `{item}`")
    if not plan["prompt_inputs"]:
        lines.append("- No repair prompt found yet; write one before generating or repairing images.")

    lines.extend(["", "## Required QC After Repair", ""])
    for command in plan["qc_commands"]:
        lines.append(f"- `{command}`")

    lines.extend([
        "",
        "## Continue Command",
        "",
        f"`{plan['continue_command']}`",
        "",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def infer_repair(blocking_qc):
    for item in blocking_qc:
        stage = item.get("stage", "")
        for key in REPAIR_HINTS:
            if key in stage:
                return key
    return "codex_imagegen_contract"


def find_prompt_inputs(root, job_id, repair):
    job_dir = root / "output" / job_id
    hints = REPAIR_HINTS.get(repair, REPAIR_HINTS["codex_imagegen_contract"])
    found = []
    for pattern in hints["preferred_prompt_globs"]:
        found.extend(sorted(job_dir.glob(pattern)))
    return [str(path.relative_to(root)) for path in found]


def qc_commands_for_job(job_id):
    return [
        f"python3 tools/codex_imagegen_contract_qc.py --root . --job-id {job_id} --stage image_batch_qc",
        f"python3 tools/visual_asset_manifest_qc.py --root . --job-id {job_id} --stage image_batch_qc",
        f"python3 tools/qc_risk_ledger.py --root . --job-id {job_id} --stage image_batch_qc",
    ]


def plan_for_job(root, job_id, repair="auto"):
    ledger = {item["job_id"]: item for item in build_ledger(root, self_audit=True)}
    item = ledger.get(job_id)
    if item is None:
        raise SystemExit(f"unknown job id: {job_id}")
    blocking_qc = item.get("blocking_qc", [])
    selected_repair = infer_repair(blocking_qc) if repair == "auto" else repair
    hints = REPAIR_HINTS.get(selected_repair, REPAIR_HINTS["codex_imagegen_contract"])
    evidence = [failure["path"] for failure in blocking_qc]
    prompt_inputs = find_prompt_inputs(root, job_id, selected_repair)
    qc_commands = qc_commands_for_job(job_id)
    return {
        "job_id": job_id,
        "repair": selected_repair,
        "retry_variable": hints["retry_variable"],
        "focus": hints["focus"],
        "evidence": evidence,
        "prompt_inputs": prompt_inputs,
        "qc_commands": qc_commands,
        "continue_command": f"./run-loop.sh --self-audit --job-id {job_id} --stop-at seedance_inputs_prepared",
    }


def main():
    parser = argparse.ArgumentParser(description="Create a single repair plan for an image batch job.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--repair", default="auto", choices=sorted(["auto", *REPAIR_HINTS.keys()]))
    parser.add_argument("--out-dir", help="Default: output/<job-id>/image-batch/run-plan")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    plan = plan_for_job(root, args.job_id, repair=args.repair)
    out_dir = Path(args.out_dir) if args.out_dir else root / "output" / args.job_id / "image-batch" / "run-plan"
    if not out_dir.is_absolute():
        out_dir = root / out_dir
    json_path = out_dir / "image_batch_run_plan.json"
    md_path = out_dir / "image_batch_run_plan.md"
    write_json(json_path, plan)
    write_markdown(md_path, plan)
    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    else:
        print(f"Wrote: {json_path}")
        print(f"Wrote: {md_path}")


if __name__ == "__main__":
    main()
