#!/usr/bin/env python3
import argparse
import csv
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from product_profile import write_product_profile  # noqa: E402


VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
STORYBOARD_DERIVED_PERSON_ASSETS = "storyboard_derived"
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


def validate_client_profile(root, profile):
    if not profile:
        return
    profile_dir = root / "client-profiles" / profile
    if not profile_dir.exists():
        raise SystemExit(f"Client profile not found: {profile_dir}")


def infer_handoff_mode(explicit_mode, notes):
    if explicit_mode != "auto":
        return explicit_mode
    text = str(notes or "")
    web_markers = ("生成视频前停", "Seedance 生成前停", "网页端", "素材图和提示词", "不需要最终视频")
    api_markers = ("直接出视频", "生成最终视频", "直接生成视频", "跑 Seedance")
    if any(marker in text for marker in web_markers):
        return "web"
    if any(marker in text for marker in api_markers):
        return "api"
    return "both"


def find_videos(video_dir, explicit_videos):
    if explicit_videos:
        return [Path(p).expanduser().resolve() for p in explicit_videos]

    root = Path(video_dir).expanduser().resolve()
    videos = [p for p in sorted(root.iterdir()) if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
    if not videos:
        raise SystemExit(f"No video files found in: {root}")
    return videos


def video_duration_seconds(path):
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"Could not read source video duration: {path}\n{result.stderr.strip()}")
    try:
        duration = float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not parse source video duration: {path}") from exc
    if duration <= 0:
        raise SystemExit(f"Source video duration must be positive: {path}")
    return duration


def formatted_duration(seconds):
    return f"{float(seconds):.3f}".rstrip("0").rstrip(".") + "s"


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_person_assets(value):
    raw = str(value or "").strip()
    if not raw or raw == STORYBOARD_DERIVED_PERSON_ASSETS:
        return STORYBOARD_DERIVED_PERSON_ASSETS
    return str(Path(raw).expanduser().resolve())


def read_existing_jobs(jobs_path):
    if not jobs_path.exists():
        return [], JOB_FIELDS[:]
    with jobs_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader), list(reader.fieldnames or JOB_FIELDS)


def next_job_number(root, rows):
    numbers = []
    for row in rows:
        match = re.fullmatch(r"job-(\d+)(?:-.+)?", row.get("id", "").strip())
        if match:
            numbers.append(int(match.group(1)))
    output_root = root / "output"
    if output_root.exists():
        for path in output_root.iterdir():
            if not path.is_dir():
                continue
            match = re.fullmatch(r"job-(\d+)(?:-.+)?", path.name)
            if match:
                numbers.append(int(match.group(1)))
    return max(numbers, default=0) + 1


def write_job_rows(jobs_path, rows, fieldnames):
    merged_fields = fieldnames[:]
    for field in JOB_FIELDS:
        if field not in merged_fields:
            merged_fields.append(field)
    with jobs_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=merged_fields)
        writer.writeheader()
        writer.writerows(rows)


def write_brief(root, args, videos):
    profile = args.client_profile or "none"
    profile_doc = (
        f"`client-profiles/{args.client_profile}/README.md`"
        if args.client_profile
        else "none"
    )
    lines = [
        "# Viral Replica Brief",
        "",
        "## Source Videos",
        "",
        f"- Source video folder: {Path(args.video_dir).expanduser().resolve() if args.video_dir else 'multiple explicit files'}",
        f"- Number of videos: {len(videos)}",
        (
            f"- Target duration: {args.target_duration} (explicit user request)"
            if args.target_duration is not None
            else "- Target duration: source duration for each video (default)"
        ),
        f"- Handoff mode: {args.handoff_mode}",
        "- Replication level: close",
        f"- Client profile: {profile}",
        f"- Profile docs: {profile_doc}",
        "",
        "## Product",
        "",
        f"- Product name: {args.product_name}",
        f"- Product asset folder: {Path(args.product_assets).expanduser().resolve()}",
        "- Product constraints: see `PRODUCT_CONSTRAINTS.md`",
        "- Product profile: generated under `output/<job-id>/product_profile.json`",
        "",
        "## Person / Host",
        "",
        f"- Person asset mode: {'storyboard_derived' if args.person_assets == STORYBOARD_DERIVED_PERSON_ASSETS else 'user_provided'}",
        f"- Person asset folder: {args.person_assets if args.person_assets == STORYBOARD_DERIVED_PERSON_ASSETS else Path(args.person_assets).expanduser().resolve()}",
        f"- Identity rule: {args.identity_rule}",
        "",
        "## Voice / Audio",
        "",
        f"- Voice source: {args.audio_assets}",
        "- Keep original subtitles as timing reference: yes",
        "- Generate audio in Seedance: yes unless the job is explicitly silent",
        "- BGM: no by default",
        "",
        "## Notes",
        "",
        f"- {args.notes or '(none; project replication defaults apply)'}",
        "",
    ]
    (root / "BRIEF.md").write_text("\n".join(lines), encoding="utf-8")


def write_jobs(root, args, videos):
    jobs_path = root / "jobs.csv"
    rows, fieldnames = read_existing_jobs(jobs_path) if args.append else ([], JOB_FIELDS[:])
    existing_videos = {
        str(Path(row.get("video_path", "")).expanduser().resolve())
        for row in rows
        if row.get("video_path", "").strip()
    }
    next_number = next_job_number(root, rows) if args.append else 1
    new_rows = []
    for index, video in enumerate(videos, start=1):
        if args.append and str(video) in existing_videos:
            continue
        job_id = f"job-{next_number:03d}" if args.append else f"job-{index:03d}"
        next_number += 1
        target_duration = args.target_duration or formatted_duration(
            video_duration_seconds(video)
        )
        new_rows.append(
            {
                "id": job_id,
                "workflow_run_id": f"{job_id}-{dt.datetime.now().strftime('%Y%m%dT%H%M%S')}",
                "status": "pending",
                "video_path": str(video),
                "product_name": args.product_name,
                "client_profile": args.client_profile,
                "product_assets": str(Path(args.product_assets).expanduser().resolve()),
                "person_assets": normalized_person_assets(args.person_assets),
                "audio_assets": args.audio_assets,
                "target_duration": target_duration,
                "handoff_mode": args.handoff_mode,
                "notes": build_notes(args),
                "output_dir": f"output/{job_id}",
                "last_artifact": "",
                "next_stage": "source_blueprint",
                "needs_user_confirmation": "false",
            }
        )
    rows.extend(new_rows)

    write_job_rows(jobs_path, rows, fieldnames)

    for row in new_rows:
        output_dir = root / row["output_dir"]
        output_dir.mkdir(parents=True, exist_ok=True)
        evidence = None
        if args.target_duration is not None:
            evidence = {
                "source": "intake",
                "quote": f"--target-duration {args.target_duration}",
            }
        (output_dir / "intake.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "job_id": row["id"],
                    "source_video": {
                        "path": row["video_path"],
                        "sha256": file_sha256(Path(row["video_path"])),
                    },
                    "target_duration": {
                        "value": row["target_duration"],
                        "explicitly_requested": args.target_duration is not None,
                        "request_evidence": evidence,
                    },
                    "user_request": {
                        "notes": args.notes,
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        write_product_profile(root, row)
    return new_rows


def write_state(root, args, videos, rows):
    profile_line = (
        f"- Client profile: `client-profiles/{args.client_profile}/README.md`"
        if args.client_profile
        else "- Client profile: none"
    )
    profile_attempt = (
        f" Client profile: `client-profiles/{args.client_profile}/README.md`."
        if args.client_profile
        else " Client profile: none."
    )
    lines = [
        "# Loop State",
        "",
        "## Goal",
        "",
        f"Replicate {len(videos)} source video(s) for `{args.product_name}` while preserving source story rhythm, shot order, and sales function.",
        profile_line,
        "",
        "## Acceptance",
        "",
        "- One row exists in `jobs.csv` for each source video.",
        "- Every round selects the pinned current job.",
        "- Every stage writes artifacts under `output/<job-id>/`.",
        "- Every stage runs its linked gate before advancing.",
        "- GPT Image samples, paid generation, and subjective final review stop for approval.",
        "- Every job has a product profile under `output/<job-id>/product_profile.json`; generic rules load by default and category/SKU rules load only from that profile.",
        "",
        "## Current Round",
        "",
        "- Date:",
        f"- Current task: not started for `{rows[0]['id'] if rows else 'none'}`",
        "- Current stage: pending",
        f"- This round did: {'appended' if args.append else 'created'} task queue from simple user intake",
        "- Artifacts: `BRIEF.md`, `jobs.csv`",
        f"- Verification: run `./run-loop.sh --job-id {rows[0]['id'] if rows else '<job-id>'}`",
        f"- Next: source blueprint for `{rows[0]['id'] if rows else '<job-id>'}`",
        "- Needs user confirmation: no",
        "",
        "## Attempts",
        "",
        f"- Intake created from user-provided video/product/person paths.{profile_attempt}",
        "",
        "## Stop Rules",
        "",
        "- Stop when there are no runnable jobs.",
        "- Stop before paid or batch generation.",
        "- Stop when subjective visual judgment is required.",
        "- Stop after repeated failure or no effective progress.",
        "",
    ]
    (root / "STATE.md").write_text("\n".join(lines), encoding="utf-8")


def build_notes(args):
    notes = args.notes
    if args.client_profile:
        suffix = f"client_profile={args.client_profile}; read client-profiles/{args.client_profile}/README.md"
        return f"{notes}; {suffix}" if notes else suffix
    return notes


def main():
    parser = argparse.ArgumentParser(description="Create a viral replica loop task from simple paths.")
    parser.add_argument("--root", default=".", help="Loop kit root.")
    parser.add_argument("--video-dir", default="", help="Folder containing source videos.")
    parser.add_argument("--video", action="append", default=[], help="Explicit source video path. Can be repeated.")
    parser.add_argument("--product-name", required=True)
    parser.add_argument("--product-assets", required=True)
    parser.add_argument(
        "--person-assets",
        default=STORYBOARD_DERIVED_PERSON_ASSETS,
        help="Person/model asset path. Omit to derive role identities from approved storyboards.",
    )
    parser.add_argument("--audio-assets", default="extract_from_original")
    parser.add_argument(
        "--target-duration",
        default=None,
        help="Explicit requested total duration. Omit to preserve each source video's duration.",
    )
    parser.add_argument("--handoff-mode", choices=("auto", "web", "api", "both"), default="auto", help="Build web upload files, API requests, or both. Auto infers from the stop/delivery notes.")
    parser.add_argument("--identity-rule", default="single model unless user says otherwise")
    parser.add_argument("--client-profile", default="", help="Optional client profile folder under client-profiles/. Auto-detects kongfengchun from product name.")
    parser.add_argument(
        "--notes",
        default="",
        help="Optional verbatim user instructions. Project replication defaults apply when omitted.",
    )
    parser.add_argument("--append", action="store_true", help="Append new jobs without overwriting existing rows or output directories.")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    args.client_profile = detect_client_profile(args.product_name, args.client_profile)
    args.person_assets = normalized_person_assets(args.person_assets)
    args.handoff_mode = infer_handoff_mode(args.handoff_mode, args.notes)
    validate_client_profile(root, args.client_profile)
    if not args.video and not args.video_dir:
        raise SystemExit("Provide --video-dir or one or more --video paths.")

    videos = find_videos(args.video_dir, args.video)
    write_brief(root, args, videos)
    rows = write_jobs(root, args, videos)
    write_state(root, args, videos, rows)

    print(f"Created {len(rows)} job(s)")
    for row in rows:
        print(f"{row['id']}: {row['video_path']}")
    print(root / "BRIEF.md")
    print(root / "jobs.csv")
    print(root / "STATE.md")


if __name__ == "__main__":
    main()
