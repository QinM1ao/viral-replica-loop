#!/usr/bin/env python3
import argparse
import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def run(cmd):
    return subprocess.run(cmd, text=True, capture_output=True)


def ffprobe(video):
    result = run([
        "ffprobe",
        "-v", "error",
        "-show_format",
        "-show_streams",
        "-of", "json",
        str(video),
    ])
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip())
    return json.loads(result.stdout)


def make_contact_sheet(video, out_path, fps):
    if not shutil.which("ffmpeg"):
        return False, "ffmpeg not found"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result = run([
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-nostats",
        "-i", str(video),
        "-vf", f"fps={fps},scale=180:-1,tile=5x6",
        "-frames:v", "1",
        str(out_path),
    ])
    return result.returncode == 0 and out_path.exists(), result.stderr[-1000:]


def run_asr(video, out_dir):
    script = Path(__file__).resolve().parent / "asr_transcribe.py"
    if not script.exists():
        return None, "asr_transcribe.py not found"
    result = run([sys.executable, str(script), str(video), "--out-dir", str(out_dir / "asr")])
    if result.returncode != 0:
        return None, result.stderr[-1000:] or result.stdout[-1000:]
    return result.stdout.strip().splitlines()[-1], ""


def run_video_understanding(
    video,
    out_dir,
    mode="full",
    fps=None,
    start_seconds=0,
    duration_seconds=None,
):
    script = Path(__file__).resolve().parent / "video_understanding.py"
    if not script.exists():
        return None, "video_understanding.py not found"
    understanding_dir = out_dir / "video_understanding"
    if mode == "rapid_hook":
        understanding_dir = understanding_dir / "hook_review"
    command = [
        sys.executable,
        str(script),
        "--video",
        str(video),
        "--out-dir",
        str(understanding_dir),
        "--mode",
        mode,
    ]
    if fps is not None:
        command.extend(["--fps", str(fps)])
    if duration_seconds is not None:
        command.extend(
            [
                "--start-seconds",
                str(start_seconds),
                "--duration-seconds",
                str(duration_seconds),
            ]
        )
    result = run(command)
    if result.returncode != 0:
        return None, result.stderr[-2000:] or result.stdout[-2000:]
    return str(understanding_dir / "analysis.json"), ""


def write_md(
    path,
    video,
    probe_path,
    contact_sheet,
    asr_path,
    understanding_path,
    hook_review_path,
    notes,
):
    lines = [
        "# Story Analysis Materials",
        "",
        f"- Source video: `{video}`",
        f"- Probe JSON: `{probe_path}`",
        f"- Contact sheet: `{contact_sheet or ''}`",
        f"- ASR markdown: `{asr_path or ''}`",
        f"- Seed 2.0 Mini analysis: `{understanding_path or ''}`",
        f"- Seed 2.0 Mini rapid hook review: `{hook_review_path or ''}`",
        "",
        "## Evidence Contract",
        "",
        "Use Seed 2.0 Mini as the primary semantic reading, then verify every important claim against:",
        "",
        "- measured cut points and 5fps frames",
        "- visible subtitle/product text",
        "- raw ASR spans and speaker mode",
        "- source pixels for action peaks and physical changes",
        "",
        "For rapid hooks, use the 5fps hook review for action order, the aligned timeline for measured boundaries, and Qwen ASR for words.",
        "",
        "Model analysis is not allowed to override contradictory pixel, subtitle, or ASR evidence.",
        "",
        "## Notes",
        "",
    ]
    lines.extend(f"- {note}" for note in notes)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Prepare source video materials for story analysis.")
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--contact-fps", default="1/2")
    parser.add_argument("--run-asr", action="store_true")
    parser.add_argument(
        "--skip-video-understanding",
        action="store_true",
        help="Explicit offline/debug escape hatch. Source-blueprint gates do not accept this mode.",
    )
    parser.add_argument("--rapid-hook-seconds", type=float, default=3.0)
    parser.add_argument("--rapid-hook-fps", type=float, default=5.0)
    args = parser.parse_args()

    if args.rapid_hook_seconds < 0:
        parser.error("--rapid-hook-seconds must be zero or greater")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    notes = []

    probe = ffprobe(args.video)
    probe_path = args.out_dir / "video_probe.json"
    probe_path.write_text(json.dumps(probe, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    contact_sheet = args.out_dir / "contact_sheet.jpg"
    run_hook_review = (
        not args.skip_video_understanding and args.rapid_hook_seconds > 0
    )
    worker_count = (
        1
        + int(args.run_asr)
        + int(not args.skip_video_understanding)
        + int(run_hook_review)
    )
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        contact_future = executor.submit(make_contact_sheet, args.video, contact_sheet, args.contact_fps)
        asr_future = executor.submit(run_asr, args.video, args.out_dir) if args.run_asr else None
        understanding_future = (
            executor.submit(
                run_video_understanding,
                args.video,
                args.out_dir,
                "full",
            )
            if not args.skip_video_understanding
            else None
        )
        hook_review_future = (
            executor.submit(
                run_video_understanding,
                args.video,
                args.out_dir,
                "rapid_hook",
                args.rapid_hook_fps,
                0,
                args.rapid_hook_seconds,
            )
            if run_hook_review
            else None
        )

        ok, detail = contact_future.result()
        asr_result = asr_future.result() if asr_future else (None, None)
        understanding_result = (
            understanding_future.result() if understanding_future else (None, None)
        )
        hook_review_result = (
            hook_review_future.result() if hook_review_future else (None, None)
        )
    if not ok:
        notes.append(f"contact sheet failed: {detail}")

    asr_path, error = asr_result
    if error:
        notes.append(f"ASR failed: {error}")

    understanding_path, understanding_error = understanding_result
    hook_review_path, hook_review_error = hook_review_result
    if args.skip_video_understanding:
        notes.append("Seed 2.0 Mini video understanding explicitly skipped; gate must not pass.")
    elif understanding_error:
        notes.append(f"Seed 2.0 Mini video understanding failed: {understanding_error}")
    if run_hook_review and hook_review_error:
        notes.append(f"Seed 2.0 Mini rapid hook review failed: {hook_review_error}")

    md_path = args.out_dir / "story_analysis_materials.md"
    write_md(
        md_path,
        args.video,
        probe_path,
        contact_sheet if contact_sheet.exists() else "",
        asr_path,
        understanding_path,
        hook_review_path,
        notes,
    )
    print(md_path)
    if not args.skip_video_understanding and understanding_error:
        raise SystemExit(1)
    if run_hook_review and hook_review_error:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
