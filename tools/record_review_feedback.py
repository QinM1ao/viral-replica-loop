#!/usr/bin/env python3
"""Append a human review feedback entry to the outer-loop ledger."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path


OUTCOMES = {
    "accepted_unchanged",
    "edited_accepted",
    "rejected",
    "pending",
    "manual_override",
    "visual_warning_accepted",
    "web_validated",
}

CLASSIFICATIONS = {
    "skill_boundary",
    "gate_gap",
    "eval_gap",
    "worker_contract",
    "checker_contract",
    "prompt_quality",
    "handoff_governance",
    "approval_safety",
    "automation_drift",
    "context_gap",
    "human_judgment",
    "report_only",
}

SURFACES = {
    "none",
    "report_only",
    "eval",
    "skill",
    "reference",
    "worker",
    "gate",
    "script",
    "memory",
}


def split_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    items: list[str] = []
    for value in values:
        for part in value.split(","):
            part = part.strip()
            if part:
                items.append(part)
    return items


def make_entry(args: argparse.Namespace) -> dict[str, object]:
    return {
        "id": f"review-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}",
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
        "job_id": args.job_id,
        "stage": args.stage,
        "artifact_before": args.artifact_before,
        "artifact_after": args.artifact_after,
        "review_outcome": args.outcome,
        "user_feedback": args.feedback,
        "meaning": args.meaning,
        "context_to_preserve": split_list(args.context_to_preserve),
        "classification": args.classification,
        "suggested_surface": args.suggested_surface,
        "apply_status": args.apply_status,
        "evidence_paths": split_list(args.evidence_path),
        "notes": args.notes,
    }


def validate_entry(entry: dict[str, object]) -> list[str]:
    errors: list[str] = []
    if entry["review_outcome"] not in OUTCOMES:
        errors.append(f"invalid review_outcome: {entry['review_outcome']}")
    if entry["classification"] and entry["classification"] not in CLASSIFICATIONS:
        errors.append(f"invalid classification: {entry['classification']}")
    if entry["suggested_surface"] not in SURFACES:
        errors.append(f"invalid suggested_surface: {entry['suggested_surface']}")
    if not str(entry["user_feedback"]).strip():
        errors.append("user_feedback is required")
    if not str(entry["meaning"]).strip():
        errors.append("meaning is required")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--ledger", default="logs/review_feedback.jsonl", help="Ledger path")
    parser.add_argument("--job-id", required=True, help="Job id or scope")
    parser.add_argument("--stage", required=True, help="Stage or review point")
    parser.add_argument("--outcome", required=True, choices=sorted(OUTCOMES), help="Review outcome")
    parser.add_argument("--feedback", required=True, help="What the user changed, accepted, rejected, or noticed")
    parser.add_argument("--meaning", required=True, help="What the feedback means for future runs")
    parser.add_argument("--artifact-before", help="Artifact before review")
    parser.add_argument("--artifact-after", help="Artifact after review")
    parser.add_argument("--context-to-preserve", action="append", help="Reusable context, comma-separated or repeated")
    parser.add_argument("--classification", choices=sorted(CLASSIFICATIONS), help="Outer-loop classification")
    parser.add_argument("--suggested-surface", default="report_only", choices=sorted(SURFACES), help="Likely durable surface")
    parser.add_argument("--apply-status", default="proposal_only", help="proposal_only, accepted, applied, rejected, or superseded")
    parser.add_argument("--evidence-path", action="append", help="Evidence path, comma-separated or repeated")
    parser.add_argument("--notes", help="Optional operator note")
    parser.add_argument("--dry-run", action="store_true", help="Print entry without writing")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    ledger = Path(args.ledger)
    if not ledger.is_absolute():
        ledger = root / ledger

    entry = make_entry(args)
    errors = validate_entry(entry)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    line = json.dumps(entry, ensure_ascii=False, sort_keys=True)
    if args.dry_run:
        print(line)
        return 0

    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(f"Wrote {ledger}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
