#!/usr/bin/env python3
"""Migrate legacy image-sample holds back to the default image-batch route."""

import argparse
import csv
from pathlib import Path


def read_jobs(path):
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader), reader.fieldnames or []


def write_jobs(path, rows, fieldnames):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def should_migrate(row):
    return (
        row.get("status", "").strip() == "storyboard_passed"
        and row.get("next_stage", "").strip() == "sample_image_waiting_review"
        and row.get("needs_user_confirmation", "").strip().lower() in {"1", "true", "yes", "y"}
    )


def migrate_row(row):
    row["next_stage"] = "image_qc_passed"
    row["needs_user_confirmation"] = "false"
    clean_stale_notes(row)


def clean_stale_notes(row):
    notes = row.get("notes", "")
    original = notes
    stale_markers = [
        "改分镜步骤使用 Codex 内置 image2/image gen；",
        "direct_video_route=skip_codex_imagegen_skip_ai_storyboard；",
        "direct_video_route=skip_codex_imagegen_skip_ai_storyboard;",
    ]
    for marker in stale_markers:
        notes = notes.replace(marker, "")
    if "image_route=matpool_gpt_image_2_edit" not in notes:
        sep = "；" if "；" in notes else "; "
        notes = notes.rstrip("；; ") + f"{sep}image_route=matpool_gpt_image_2_edit"
    row["notes"] = notes
    return notes != original


def main():
    parser = argparse.ArgumentParser(description="Migrate legacy image-sample holds.")
    parser.add_argument("--root", default=".", help="Loop root")
    parser.add_argument("--job-id", action="append", default=[], help="Limit to one or more job ids")
    parser.add_argument("--clean-stale-notes", action="store_true", help="Also remove obsolete direct-video/Codex route notes")
    parser.add_argument("--apply", action="store_true", help="Write jobs.csv")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    jobs_path = root / "jobs.csv"
    rows, fieldnames = read_jobs(jobs_path)
    wanted = {item.strip() for raw in args.job_id for item in raw.split(",") if item.strip()}
    changed = []
    for row in rows:
        if wanted and row.get("id", "") not in wanted:
            continue
        if should_migrate(row):
            before = {
                "id": row.get("id", ""),
                "status": row.get("status", ""),
                "next_stage": row.get("next_stage", ""),
                "needs_user_confirmation": row.get("needs_user_confirmation", ""),
            }
            migrate_row(row)
            after = {
                "id": row.get("id", ""),
                "status": row.get("status", ""),
                "next_stage": row.get("next_stage", ""),
                "needs_user_confirmation": row.get("needs_user_confirmation", ""),
            }
            changed.append({"before": before, "after": after})
        elif args.clean_stale_notes:
            before_notes = row.get("notes", "")
            clean_stale_notes(row)
            if row.get("notes", "") != before_notes:
                changed.append({
                    "before": {"id": row.get("id", ""), "notes": before_notes},
                    "after": {"id": row.get("id", ""), "notes": row.get("notes", "")},
                })

    if args.apply and changed:
        write_jobs(jobs_path, rows, fieldnames)

    mode = "applied" if args.apply else "dry_run"
    print(f"{mode}: {len(changed)} job(s) would migrate" if not args.apply else f"{mode}: {len(changed)} job(s) migrated")
    for item in changed:
        print(f"- {item['before']} -> {item['after']}")


if __name__ == "__main__":
    main()
