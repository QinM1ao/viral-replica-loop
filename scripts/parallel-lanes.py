#!/usr/bin/env python3
import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from evidence_ledger import build_ledger  # noqa: E402


def read_jobs(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_lane(row, ledger_item, self_audit, stop_at):
    job_id = row["id"]
    args = ["./run-loop.sh"]
    if self_audit:
        args.append("--self-audit")
    args.extend(["--job-id", job_id])
    for item in stop_at:
        args.extend(["--stop-at", item])
    return {
        "job_id": job_id,
        "status": row.get("status", ""),
        "next_stage": row.get("next_stage", ""),
        "reason": ledger_item.get("reason", "runnable"),
        "blocking_qc": ledger_item.get("blocking_qc", []),
        "command": " ".join(args),
        "output_dir": row.get("output_dir", f"output/{job_id}"),
        "state_policy": "fixed job lane; run-loop serializes shared jobs.csv/RUNNER_STATE.json writes with .run-loop.lock",
    }


def main():
    parser = argparse.ArgumentParser(description="Plan fixed-job parallel lanes for viral-replica-loop.")
    parser.add_argument("--root", default=".", help="Loop root.")
    parser.add_argument("--max-workers", type=int, default=3)
    parser.add_argument("--self-audit", action="store_true")
    parser.add_argument("--stop-at", action="append", default=["seedance_inputs_prepared"])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    rows = read_jobs(root / "jobs.csv")
    ledger = {
        item["job_id"]: item
        for item in build_ledger(root, self_audit=args.self_audit)
    }
    runnable = []
    skipped = []
    for row in rows:
        item = ledger.get(row.get("id", ""), {})
        verdict = item.get("verdict", "missing")
        reason = item.get("reason", "missing from evidence ledger")
        item = {
            "job_id": row.get("id", ""),
            "status": row.get("status", ""),
            "next_stage": row.get("next_stage", ""),
            "reason": reason,
            "blocking_qc": item.get("blocking_qc", []),
        }
        if verdict == "runnable":
            runnable.append(build_lane(row, item, args.self_audit, args.stop_at))
        else:
            skipped.append(item)

    report = {
        "max_workers": args.max_workers,
        "lane_policy": "fixed_job_id_required",
        "shared_state_policy": "coordinator_serialized_by_run_loop_lock",
        "lanes": runnable[: args.max_workers],
        "queued": runnable[args.max_workers :],
        "skipped": skipped,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    print(f"Max workers: {args.max_workers}")
    print("Lane policy: fixed job id required; shared runner writes serialize through .run-loop.lock")
    print("Lanes:")
    for lane in report["lanes"]:
        print(f"- {lane['job_id']} [{lane['status']} -> {lane['next_stage']}]: {lane['command']}")
        print(f"  reason: {lane['reason']}")
        print(f"  state policy: {lane['state_policy']}")
        for failure in lane.get("blocking_qc", []):
            print(f"  repair evidence: {failure['path']}")
    print("Queued:")
    for lane in report["queued"]:
        print(f"- {lane['job_id']} [{lane['status']} -> {lane['next_stage']}]")
    print("Skipped:")
    for item in skipped:
        print(f"- {item['job_id']} [{item['status']} -> {item['next_stage']}]: {item['reason']}")


if __name__ == "__main__":
    main()
