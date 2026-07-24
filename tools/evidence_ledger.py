#!/usr/bin/env python3
import argparse
import csv
import json
from pathlib import Path

from qc_outcomes import blocker_category, outcome_for_result


STOP_STATUSES = {"seedance_inputs_prepared", "generation_approved", "done", "blocked"}
SELF_AUDIT_REVIEW_STATUSES = {"sample_image_waiting_review", "afterwash_ref_waiting_review"}
BLOCKING_QC_SUFFIXES = (
    "_visual_asset_manifest_qc.json",
    "_codex_imagegen_contract_qc.json",
    "_storyboard_geometry_qc.json",
    "_cross_part_continuity_qc.json",
    "_skincare_progression_qc.json",
)


def read_jobs(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def truthy(value):
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是"}


def load_qc_overall(path):
    data = load_qc_data(path)
    value = data.get("overall") or data.get("status") or data.get("result")
    return str(value).strip().upper() if value is not None else None


def load_qc_data(path):
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def qc_stage_name(path):
    name = path.name
    for suffix in BLOCKING_QC_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return path.stem


def latest_stage_statuses(checks_dir):
    statuses = {}
    if not checks_dir.exists():
        return statuses
    for path in sorted(checks_dir.glob("*.json")):
        if not any(path.name.endswith(suffix) for suffix in BLOCKING_QC_SUFFIXES):
            continue
        stage = path.stem
        data = load_qc_data(path)
        overall = load_qc_overall(path)
        if overall:
            outcome = data.get("outcome_type") or outcome_for_result(overall, text=json.dumps(data, ensure_ascii=False))
            statuses[stage] = {
                "overall": overall,
                "path": path,
                "outcome_type": outcome,
                "blocker_category": data.get("blocker_category") or blocker_category(outcome),
                "why_not_fail": data.get("why_not_fail"),
            }
    return statuses


def blocking_qc_failures(root, job_id):
    checks_dir = root / "output" / job_id / "checks"
    failures = []
    for stage, item in latest_stage_statuses(checks_dir).items():
        if item["overall"] in {"FAIL", "STOP"}:
            failures.append({
                "stage": stage,
                "path": str(item["path"].relative_to(root)),
                "overall": item["overall"],
                "outcome_type": item.get("outcome_type"),
                "blocker_category": item.get("blocker_category"),
                "why_not_fail": item.get("why_not_fail"),
            })
    return failures


def classify_job(root, row, self_audit=False, allow_paid=False):
    job_id = row.get("id", "").strip()
    status = row.get("status", "").strip()
    needs_confirmation = truthy(row.get("needs_user_confirmation", ""))
    failures = blocking_qc_failures(root, job_id)

    if status in STOP_STATUSES and not (allow_paid and status == "seedance_inputs_prepared"):
        if failures:
            return {
                "job_id": job_id,
                "status": status,
                "next_stage": row.get("next_stage", ""),
                "verdict": "blocked_by_evidence",
                "reason": (
                    f"stop point has {failures[0].get('blocker_category') or 'evidence'} "
                    f"QC blocker: {failures[0]['stage']}"
                ),
                "blocking_qc": failures,
            }
        return {
            "job_id": job_id,
            "status": status,
            "next_stage": row.get("next_stage", ""),
            "verdict": "stop_point",
            "reason": "already at stop/terminal status",
            "blocking_qc": [],
        }

    if needs_confirmation and not (self_audit and status in SELF_AUDIT_REVIEW_STATUSES):
        return {
            "job_id": job_id,
            "status": status,
            "next_stage": row.get("next_stage", ""),
            "verdict": "needs_user_confirmation",
            "reason": "needs user confirmation",
            "blocking_qc": [],
        }

    return {
        "job_id": job_id,
        "status": status,
        "next_stage": row.get("next_stage", ""),
        "verdict": "runnable",
        "reason": (
            f"runnable; repair {failures[0].get('blocker_category') or 'evidence'} "
            f"blocker: {failures[0]['stage']}"
        ) if failures else "runnable",
        "blocking_qc": failures,
    }


def build_ledger(root, self_audit=False, allow_paid=False):
    root = Path(root).resolve()
    rows = read_jobs(root / "jobs.csv")
    return [classify_job(root, row, self_audit=self_audit, allow_paid=allow_paid) for row in rows]


def suggested_command(item, self_audit=False):
    args = ["./run-loop.sh"]
    if self_audit:
        args.append("--self-audit")
    args.extend(["--job-id", item["job_id"], "--stop-at", "seedance_inputs_prepared"])
    return " ".join(args)


def render_markdown_report(ledger, self_audit=False):
    runnable = [item for item in ledger if item["verdict"] == "runnable"]
    skipped = [item for item in ledger if item["verdict"] != "runnable"]
    lines = [
        "# Evidence Ledger Report",
        "",
        "## Today Run These",
        "",
    ]
    if not runnable:
        lines.append("- None. No runnable jobs found.")
    for item in runnable:
        lines.extend([
            f"- `{item['job_id']}`: `{item['status']}` -> `{item['next_stage']}`",
            f"  - Why: {item['reason']}",
            f"  - Command: `{suggested_command(item, self_audit=self_audit)}`",
        ])
        for failure in item.get("blocking_qc", []):
            lines.append(
                f"  - Repair evidence: `{failure['path']}` "
                f"({failure.get('blocker_category')}, {failure.get('outcome_type')})"
            )

    lines.extend(["", "## Skip For Now", ""])
    if not skipped:
        lines.append("- None.")
    for item in skipped:
        lines.append(f"- `{item['job_id']}`: {item['reason']} (`{item['status']}` -> `{item['next_stage']}`)")
        for failure in item.get("blocking_qc", []):
            lines.append(
                f"  - Blocking evidence: `{failure['path']}` "
                f"({failure.get('blocker_category')}, {failure.get('outcome_type')})"
            )

    lines.extend([
        "",
        "## Summary",
        "",
        f"- Runnable jobs: `{len(runnable)}`",
        f"- Skipped jobs: `{len(skipped)}`",
        "",
    ])
    return "\n".join(lines)


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")


def select_job_id(root, requested_job_id="", self_audit=False, allow_paid=False):
    root = Path(root).resolve()
    rows = read_jobs(root / "jobs.csv")
    ledger = {item["job_id"]: item for item in build_ledger(root, self_audit=self_audit, allow_paid=allow_paid)}
    if requested_job_id:
        return requested_job_id if requested_job_id in ledger else None
    for row in rows:
        item = ledger.get(row.get("id", "").strip())
        if item and item["verdict"] == "runnable":
            return item["job_id"]
    return None


def main():
    parser = argparse.ArgumentParser(description="Summarize job readiness from jobs.csv plus blocking QC evidence.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--self-audit", action="store_true")
    parser.add_argument("--allow-paid", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--report-md", help="Write a human-readable Markdown report.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    ledger = build_ledger(root, self_audit=args.self_audit, allow_paid=args.allow_paid)
    if args.report_md:
        report_path = Path(args.report_md)
        if not report_path.is_absolute():
            report_path = root / report_path
        write_text(report_path, render_markdown_report(ledger, self_audit=args.self_audit))
    if args.json:
        print(json.dumps({"jobs": ledger}, ensure_ascii=False, indent=2))
        return

    for item in ledger:
        print(f"{item['job_id']}: {item['verdict']} - {item['reason']}")
        for failure in item["blocking_qc"]:
            print(f"  - {failure['path']} ({failure.get('blocker_category')}, {failure.get('outcome_type')})")


if __name__ == "__main__":
    main()
