#!/usr/bin/env python3
import argparse
import csv
import datetime as dt
import fcntl
import re
from pathlib import Path


VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
JOB_FIELDS = [
    "id",
    "workflow_run_id",
    "status",
    "video_path",
    "product_name",
    "client_profile",
    "product_assets",
    "person_assets",
    "audio_assets",
    "target_duration",
    "handoff_mode",
    "notes",
    "output_dir",
    "last_artifact",
    "next_stage",
    "needs_user_confirmation",
]


def detect_client_profile(product_name, explicit_profile):
    if explicit_profile:
        return explicit_profile
    if "孔凤春" in product_name:
        return "kongfengchun"
    return ""


def read_jobs(path):
    if not path.exists():
        return [], JOB_FIELDS[:]
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader), list(reader.fieldnames or JOB_FIELDS)


def write_jobs(path, rows, fieldnames):
    merged_fields = fieldnames[:]
    for field in JOB_FIELDS:
        if field not in merged_fields:
            merged_fields.append(field)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=merged_fields)
        writer.writeheader()
        writer.writerows(rows)


def list_videos(video_dir):
    root = Path(video_dir).expanduser().resolve()
    if not root.exists():
        raise SystemExit(f"Video inbox not found: {root}")
    return [
        path.resolve()
        for path in sorted(root.iterdir())
        if path.is_file() and path.suffix.lower() in VIDEO_EXTS
    ]


def next_job_number(rows):
    numbers = []
    for row in rows:
        match = re.fullmatch(r"job-(\d+)", row.get("id", "").strip())
        if match:
            numbers.append(int(match.group(1)))
    return max(numbers, default=0) + 1


def build_notes(args, profile):
    parts = []
    if args.notes.strip():
        parts.append(args.notes.strip())
    if profile:
        parts.append(f"client_profile={profile}")
        parts.append(f"read client-profiles/{profile}/README.md")
    parts.append("model_policy=auto_by_source_gender_random")
    parts.append("during story_analysis, infer source host gender before selecting identity")
    parts.append("choose a gender-matched model from person_assets and avoid reusing the same identity when alternatives exist")
    return "; ".join(parts)


def append_missing_jobs(root, args):
    jobs_path = root / "jobs.csv"
    rows, fieldnames = read_jobs(jobs_path)
    existing_videos = {
        str(Path(row.get("video_path", "")).expanduser().resolve())
        for row in rows
        if row.get("video_path", "").strip()
    }
    videos = list_videos(args.video_dir)
    missing = [video for video in videos if str(video) not in existing_videos]
    if args.limit:
        missing = missing[: args.limit]

    profile = detect_client_profile(args.product_name, args.client_profile)
    if profile and not (root / "client-profiles" / profile).exists():
        raise SystemExit(f"Client profile not found: {root / 'client-profiles' / profile}")

    product_assets = Path(args.product_assets).expanduser().resolve()
    person_assets = Path(args.person_assets).expanduser().resolve()
    if not product_assets.exists():
        raise SystemExit(f"Product assets not found: {product_assets}")
    if not person_assets.exists():
        raise SystemExit(f"Person assets not found: {person_assets}")

    next_number = next_job_number(rows)
    new_rows = []
    for video in missing:
        job_id = f"job-{next_number:03d}"
        next_number += 1
        row = {
            "id": job_id,
            "workflow_run_id": f"{job_id}-{dt.datetime.now().strftime('%Y%m%dT%H%M%S')}",
            "status": "pending",
            "video_path": str(video),
            "product_name": args.product_name,
            "client_profile": profile,
            "product_assets": str(product_assets),
            "person_assets": str(person_assets),
            "audio_assets": args.audio_assets,
            "target_duration": args.target_duration,
            "handoff_mode": args.handoff_mode,
            "notes": build_notes(args, profile),
            "output_dir": f"output/{job_id}",
            "last_artifact": "",
            "next_stage": "source_blueprint",
            "needs_user_confirmation": "false",
        }
        rows.append(row)
        new_rows.append(row)

    if not args.dry_run and new_rows:
        write_jobs(jobs_path, rows, fieldnames)
        for row in new_rows:
            (root / row["output_dir"]).mkdir(parents=True, exist_ok=True)

    return videos, new_rows


def main():
    parser = argparse.ArgumentParser(description="Append new source videos to jobs.csv without overwriting existing jobs.")
    parser.add_argument("--root", default=".", help="Loop kit root.")
    parser.add_argument("--video-dir", required=True, help="Folder to scan for source videos.")
    parser.add_argument("--product-name", required=True)
    parser.add_argument("--product-assets", required=True)
    parser.add_argument("--person-assets", required=True)
    parser.add_argument("--audio-assets", default="extract_from_original")
    parser.add_argument("--target-duration", default="30s")
    parser.add_argument("--handoff-mode", choices=("web", "api", "both"), default="web")
    parser.add_argument("--client-profile", default="")
    parser.add_argument("--notes", default="基本全复刻，场景和节奏按原视频，只换目标产品和匹配性别模特；不需要最终视频；到 Seedance 生成视频前停；最终交付 Seedance 网页端素材图、音频和提示词。")
    parser.add_argument("--limit", type=int, default=0, help="Maximum number of new videos to append in this run. 0 means no limit.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    lock_path = root / ".sync-inbox-to-jobs.lock"
    with lock_path.open("w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        videos, new_rows = append_missing_jobs(root, args)

    print(f"Scanned videos: {len(videos)}")
    print(f"Added jobs: {len(new_rows)}")
    for row in new_rows:
        print(f"{row['id']}: {row['video_path']}")


if __name__ == "__main__":
    main()
