#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from job_intake import (  # noqa: E402
    JobIntakeRequest,
    STORYBOARD_DERIVED_PERSON_ASSETS,
    create_jobs,
    discover_videos,
)


def append_missing_jobs(root, args):
    videos = discover_videos(args.video_dir)
    result = create_jobs(
        root,
        videos,
        JobIntakeRequest(
            product_name=args.product_name,
            product_assets=args.product_assets,
            person_assets=args.person_assets,
            audio_assets=args.audio_assets,
            target_duration=args.target_duration,
            handoff_mode=args.handoff_mode,
            notes=args.notes,
            client_profile=args.client_profile,
            duplicate_video_policy="skip",
            max_new_jobs=args.limit or None,
        ),
        dry_run=args.dry_run,
    )
    return list(result.scanned_videos), list(result.created_jobs)


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Append new source videos through the canonical Job Intake module."
        )
    )
    parser.add_argument("--root", default=".", help="Loop kit root.")
    parser.add_argument(
        "--video-dir",
        required=True,
        help="Folder to scan for source videos.",
    )
    parser.add_argument("--product-name", required=True)
    parser.add_argument("--product-assets", required=True)
    parser.add_argument(
        "--person-assets",
        default=STORYBOARD_DERIVED_PERSON_ASSETS,
    )
    parser.add_argument("--audio-assets", default="extract_from_original")
    parser.add_argument(
        "--target-duration",
        default=None,
        help=(
            "Explicit requested duration. Omit to preserve each source "
            "video's measured duration."
        ),
    )
    parser.add_argument(
        "--handoff-mode",
        choices=("auto", "web", "api", "both"),
        default="auto",
    )
    parser.add_argument("--client-profile", default="")
    parser.add_argument(
        "--notes",
        default=(
            "基本全复刻，场景和节奏按原视频，只换目标产品和匹配性别模特；"
            "不需要最终视频；到 Seedance 生成视频前停；最终交付 Seedance "
            "网页端素材图、音频和提示词。"
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum new videos after deduplication. 0 means no limit.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    try:
        videos, new_rows = append_missing_jobs(root, args)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    print(f"Scanned videos: {len(videos)}")
    print(f"Added jobs: {len(new_rows)}")
    for row in new_rows:
        print(f"{row['id']}: {row['video_path']}")


if __name__ == "__main__":
    main()
