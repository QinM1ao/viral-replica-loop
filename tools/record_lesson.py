#!/usr/bin/env python3
import argparse
import datetime as dt
import json
from pathlib import Path

from evidence_ledger import build_ledger


PROFILE_BY_NAME = {
    "kongfengchun": Path("client-profiles/kongfengchun"),
}
RETRY_VARIABLE_BY_QC = {
    "cross_part_continuity": "cross_part_continuity",
    "skincare_progression": "skin_progression",
    "storyboard_geometry": "storyboard_geometry",
    "codex_imagegen_contract": "codex_imagegen_contract",
}


def load_json(path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def write_jsonl(path, item):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")


def already_recorded(path, item):
    if not path.exists():
        return False
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                existing = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                existing.get("job_id") == item["job_id"]
                and existing.get("source_qc") == item["source_qc"]
                and existing.get("evidence_path") == item["evidence_path"]
            ):
                return True
    return False


def append_failed_case(path, item):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "",
        f"## Lesson {item['id']}",
        "",
        f"- Job: `{item['job_id']}`",
        f"- Source QC: `{item['source_qc']}`",
        f"- Failure type: `{item['failure_type']}`",
        f"- Retry variable: `{item['retry_variable']}`",
        f"- Evidence: `{item['evidence_path']}`",
        "",
        "以后处理：",
        "",
        f"- {item['action']}",
        "",
    ]
    with path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines))


def read_failure_detail(root, evidence_path):
    path = root / evidence_path
    if not path.exists():
        return {}
    try:
        data = load_json(path)
    except json.JSONDecodeError:
        return {}
    return {
        "overall": data.get("overall") or data.get("status") or data.get("result"),
        "failed_flags": data.get("failed_flags", []),
        "missing_flags": data.get("missing_flags", []),
    }


def default_action(source_qc):
    if "cross_part_continuity" in source_qc:
        return "Before promotion, compare Part images side by side and repair wardrobe, scene, lighting, or identity drift."
    if "skincare_progression" in source_qc:
        return "Before promotion, keep pre-wash skin believable and reserve after-wash brightness until wash/wipe proof."
    if "storyboard_geometry" in source_qc:
        return "Before promotion, preserve the source storyboard canvas, panel geometry, and shot order."
    if "codex_imagegen_contract" in source_qc:
        return "Before promotion, prove GPT Image used Matpool source/product/identity refs and settings."
    return "Before promotion, repair the failed QC evidence and rerun the linked gate."


def default_retry_variable(source_qc):
    for marker, retry_variable in RETRY_VARIABLE_BY_QC.items():
        if marker in source_qc:
            return retry_variable
    return source_qc


def infer_profile(row):
    return row.get("client_profile", "").strip() or "kongfengchun"


def find_job_row(root, job_id):
    import csv

    with (root / "jobs.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("id", "").strip() == job_id:
                return row
    raise SystemExit(f"unknown job id: {job_id}")


def build_lesson(root, job_id, source_qc="auto", failure_type="", retry_variable="", action=""):
    row = find_job_row(root, job_id)
    ledger = {item["job_id"]: item for item in build_ledger(root, self_audit=True)}
    item = ledger.get(job_id, {})
    blocking = item.get("blocking_qc", [])
    if source_qc == "auto":
        if not blocking:
            raise SystemExit(f"job {job_id} has no blocking QC evidence")
        selected = blocking[0]
        source_qc = selected["stage"]
        evidence_path = selected["path"]
    else:
        matches = [failure for failure in blocking if source_qc in failure["stage"] or source_qc in failure["path"]]
        evidence_path = matches[0]["path"] if matches else f"output/{job_id}/checks/{source_qc}.json"
    detail = read_failure_detail(root, evidence_path)
    now = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    profile = infer_profile(row)
    return {
        "id": f"{now}-{job_id}-{source_qc}",
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "job_id": job_id,
        "product_name": row.get("product_name", ""),
        "client_profile": profile,
        "source_qc": source_qc,
        "evidence_path": evidence_path,
        "failure_type": failure_type or source_qc,
        "retry_variable": retry_variable or default_retry_variable(source_qc),
        "qc_detail": detail,
        "action": action or default_action(source_qc),
    }


def main():
    parser = argparse.ArgumentParser(description="Record a failed loop case as a reusable lesson.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--from-qc", default="auto")
    parser.add_argument("--failure-type", default="")
    parser.add_argument("--retry-variable", default="")
    parser.add_argument("--action", default="")
    parser.add_argument("--append-failed-case", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    lesson = build_lesson(
        root,
        args.job_id,
        source_qc=args.from_qc,
        failure_type=args.failure_type,
        retry_variable=args.retry_variable,
        action=args.action,
    )
    profile_dir = PROFILE_BY_NAME.get(lesson["client_profile"], PROFILE_BY_NAME["kongfengchun"])
    registry_path = root / profile_dir / "lesson-registry.jsonl"
    duplicate = already_recorded(registry_path, lesson)
    if not duplicate or args.force:
        write_jsonl(registry_path, lesson)
    if args.append_failed_case:
        append_failed_case(root / profile_dir / "failed-cases.md", lesson)
    if args.json:
        print(json.dumps(lesson, ensure_ascii=False, indent=2))
    else:
        print(f"{'Already recorded' if duplicate and not args.force else 'Wrote'}: {registry_path}")
        if args.append_failed_case:
            print(f"Updated: {root / profile_dir / 'failed-cases.md'}")


if __name__ == "__main__":
    main()
