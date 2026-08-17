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
    infer_handoff_mode,
)


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
        (
            "- Source video folder: "
            f"{Path(args.video_dir).expanduser().resolve()}"
            if args.video_dir
            else "- Source video folder: multiple explicit files"
        ),
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
        (
            "- Product asset folder: "
            f"{Path(args.product_assets).expanduser().resolve()}"
        ),
        "- Product constraints: see `PRODUCT_CONSTRAINTS.md`",
        (
            "- Product profile: generated under "
            "`output/<job-id>/product_profile.json`"
        ),
        "",
        "## Person / Host",
        "",
        (
            "- Person asset mode: "
            f"{'storyboard_derived' if args.person_assets == STORYBOARD_DERIVED_PERSON_ASSETS else 'user_provided'}"
        ),
        (
            f"- Person asset folder: {args.person_assets}"
            if args.person_assets == STORYBOARD_DERIVED_PERSON_ASSETS
            else (
                "- Person asset folder: "
                f"{Path(args.person_assets).expanduser().resolve()}"
            )
        ),
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


def write_state(root, args, videos, rows, existing_job_count):
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
    first_job = rows[0]["id"] if rows else "none"
    lines = [
        "# Loop State",
        "",
        "## Goal",
        "",
        (
            f"Replicate {len(videos)} source video(s) for "
            f"`{args.product_name}` while preserving source story rhythm, "
            "shot order, and sales function."
        ),
        profile_line,
        "",
        "## Acceptance",
        "",
        "- One row exists in `jobs.csv` for each source video.",
        "- Every round selects the pinned current job.",
        "- Every stage writes artifacts under `output/<job-id>/`.",
        "- Every stage runs its linked gate before advancing.",
        "- Paid video generation stops for approval.",
        (
            "- Every job has a product profile under "
            "`output/<job-id>/product_profile.json`."
        ),
        "",
        "## Current Round",
        "",
        "- Date:",
        f"- Current task: not started for `{first_job}`",
        "- Current stage: pending",
        (
            "- This round did: "
            f"{'appended to' if existing_job_count else 'created'} "
            "the task queue from simple user intake"
        ),
        "- Artifacts: `BRIEF.md`, `jobs.csv`, per-Job `intake.json`",
        f"- Verification: run `./run-loop.sh --job-id {first_job}`",
        f"- Next: source blueprint for `{first_job}`",
        "- Needs user confirmation: no",
        "",
        "## Attempts",
        "",
        (
            "- Intake created from user-provided video/product/person paths."
            f"{profile_attempt}"
        ),
        "",
        "## Stop Rules",
        "",
        "- Stop when there are no runnable jobs.",
        "- Stop before paid or batch generation.",
        "- Stop after repeated hard failure or no effective progress.",
        "",
    ]
    (root / "STATE.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(
        description="Create a viral replica loop task from simple paths."
    )
    parser.add_argument("--root", default=".", help="Loop kit root.")
    parser.add_argument(
        "--video-dir",
        default="",
        help="Folder containing source videos.",
    )
    parser.add_argument(
        "--video",
        action="append",
        default=[],
        help="Explicit source video path. Can be repeated.",
    )
    parser.add_argument("--product-name", required=True)
    parser.add_argument("--product-assets", required=True)
    parser.add_argument(
        "--person-assets",
        default=STORYBOARD_DERIVED_PERSON_ASSETS,
        help=(
            "Person/model asset path. Omit to derive role identities from "
            "approved storyboards."
        ),
    )
    parser.add_argument("--audio-assets", default="extract_from_original")
    parser.add_argument(
        "--target-duration",
        default=None,
        help=(
            "Explicit requested total duration. Omit to preserve each source "
            "video's duration."
        ),
    )
    parser.add_argument(
        "--handoff-mode",
        choices=("auto", "web", "api", "both"),
        default="auto",
        help=(
            "Build web upload files, API requests, or both. Auto chooses only "
            "the delivery surface implied by the notes."
        ),
    )
    parser.add_argument(
        "--identity-rule",
        default="single model unless user says otherwise",
    )
    parser.add_argument(
        "--client-profile",
        default="",
        help=(
            "Optional client profile folder under client-profiles/. "
            "Auto-detects kongfengchun from product name."
        ),
    )
    parser.add_argument(
        "--notes",
        default="",
        help=(
            "Optional verbatim user instructions. Project replication "
            "defaults apply when omitted."
        ),
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help=(
            "Compatibility flag: skip videos already in jobs.csv. Existing "
            "Jobs are never overwritten with or without this flag."
        ),
    )
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not args.video and not args.video_dir:
        raise SystemExit("Provide --video-dir or one or more --video paths.")
    try:
        videos = discover_videos(args.video_dir, args.video)
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
                duplicate_video_policy="skip" if args.append else "allow",
            ),
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    args.client_profile = result.request.client_profile
    args.person_assets = result.request.person_assets
    args.product_assets = result.request.product_assets
    args.handoff_mode = result.request.handoff_mode
    rows = list(result.created_jobs)
    if result.existing_job_count == 0 and rows:
        write_brief(root, args, videos)
        write_state(
            root,
            args,
            videos,
            rows,
            result.existing_job_count,
        )

    print(f"Created {len(rows)} job(s)")
    for row in rows:
        print(f"{row['id']}: {row['video_path']}")
    print(root / "BRIEF.md")
    print(root / "jobs.csv")
    print(root / "STATE.md")


if __name__ == "__main__":
    main()
