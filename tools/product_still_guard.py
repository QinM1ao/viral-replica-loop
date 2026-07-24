#!/usr/bin/env python3
"""Detect and locally repair product-reference stills inserted into a video.

The guard looks for a product reference image geometrically dominating several
consecutive video frames.  A normal product shot may share label details with a
reference; it is not flagged unless the reference occupies a large, coherent
part of the frame with an unusually strong feature match.

Repair is deterministic and local-only: replace the flagged visual interval
with a clean, moving product interval from the same video, while stream-copying
the original audio.  If no safe interval exists, fail instead of guessing.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError as exc:  # pragma: no cover - exercised by operator environments
    cv2 = None
    np = None
    CV_IMPORT_ERROR = exc
else:
    CV_IMPORT_ERROR = None


DETECTOR_VERSION = "reference_dominance_v1"
DEFAULT_SAMPLE_FPS = 4.0
MIN_DIRECT_INLIERS = 50
MIN_DIRECT_INLIER_RATIO = 0.50
MIN_DIRECT_FRAME_COVERAGE = 0.10
MIN_CONSECUTIVE_DIRECT_SAMPLES = 2


class GuardError(ValueError):
    pass


def run(command):
    return subprocess.run(command, text=True, capture_output=True, check=False)


def require_runtime():
    missing = [name for name in ("ffmpeg", "ffprobe") if not shutil.which(name)]
    if missing:
        raise GuardError(f"missing required tools: {', '.join(missing)}")
    if cv2 is None or np is None:
        raise GuardError(
            "OpenCV is required for product still detection; "
            "install requirements.txt"
        ) from CV_IMPORT_ERROR


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def probe_video(path):
    result = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ]
    )
    if result.returncode != 0:
        raise GuardError(f"cannot read media {path}: {result.stderr.strip()}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GuardError(f"invalid ffprobe response for {path}: {exc}") from exc
    streams = data.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if video is None or audio is None:
        raise GuardError(f"media must contain video and audio streams: {path}")
    duration = float(data.get("format", {}).get("duration") or 0)
    if duration <= 0:
        raise GuardError(f"media has invalid duration: {path}")
    frame_rate_text = video.get("avg_frame_rate") or video.get("r_frame_rate") or "25/1"
    try:
        numerator, denominator = frame_rate_text.split("/", 1)
        fps = float(numerator) / float(denominator)
    except (ValueError, ZeroDivisionError):
        fps = 25.0
    return {
        "duration": duration,
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": fps,
    }


def audio_packet_sha256(path):
    result = run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-c",
            "copy",
            "-f",
            "hash",
            "-hash",
            "sha256",
            "-",
        ]
    )
    if result.returncode != 0:
        raise GuardError(f"cannot hash audio stream for {path}: {result.stderr.strip()}")
    line = result.stdout.strip()
    if "=" not in line:
        raise GuardError(f"unexpected audio hash output for {path}: {line}")
    return line.split("=", 1)[1].strip().lower()


def load_reference(path, max_dimension=1800):
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise GuardError(f"cannot read product reference image: {path}")
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.shape[2] == 4:
        alpha = image[:, :, 3:4].astype(np.float32) / 255.0
        image = (
            image[:, :, :3].astype(np.float32) * alpha
            + np.full_like(image[:, :, :3], 255, dtype=np.float32) * (1.0 - alpha)
        ).astype(np.uint8)
    scale = min(1.0, max_dimension / max(image.shape[:2]))
    if scale < 1:
        image = cv2.resize(
            image,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_AREA,
        )
    return image


def prepare_reference(path, sift):
    image = load_reference(path)
    grayscale = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    keypoints, descriptors = sift.detectAndCompute(grayscale, None)
    if descriptors is None or len(keypoints) < 12:
        raise GuardError(f"product reference lacks enough visual detail: {path}")
    return {
        "path": str(Path(path).resolve()),
        "sha256": file_sha256(path),
        "keypoints": keypoints,
        "descriptors": descriptors,
    }


def resize_for_scan(frame, width=360):
    if frame.shape[1] == width:
        return frame
    height = max(1, round(frame.shape[0] * width / frame.shape[1]))
    return cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)


def match_reference(frame_gray, frame_keypoints, frame_descriptors, reference, matcher):
    if frame_descriptors is None or len(frame_keypoints) < 4:
        return {
            "reference": reference["path"],
            "good_match_count": 0,
            "inlier_count": 0,
            "inlier_ratio": 0.0,
            "frame_coverage": 0.0,
        }
    good = []
    for pair in matcher.knnMatch(reference["descriptors"], frame_descriptors, k=2):
        if len(pair) == 2 and pair[0].distance < 0.70 * pair[1].distance:
            good.append(pair[0])
    inlier_count = 0
    inlier_ratio = 0.0
    frame_coverage = 0.0
    if len(good) >= 4:
        source_points = np.float32(
            [reference["keypoints"][item.queryIdx].pt for item in good]
        )
        frame_points = np.float32(
            [frame_keypoints[item.trainIdx].pt for item in good]
        )
        homography, mask = cv2.findHomography(
            source_points,
            frame_points,
            cv2.RANSAC,
            3.0,
        )
        if homography is not None and mask is not None:
            inliers = mask.ravel().astype(bool)
            inlier_count = int(inliers.sum())
            inlier_ratio = inlier_count / len(good)
            inlier_points = frame_points[inliers]
            if len(inlier_points) >= 3:
                hull = cv2.convexHull(inlier_points)
                frame_coverage = cv2.contourArea(hull) / (
                    frame_gray.shape[0] * frame_gray.shape[1]
                )
    return {
        "reference": reference["path"],
        "good_match_count": len(good),
        "inlier_count": inlier_count,
        "inlier_ratio": round(float(inlier_ratio), 6),
        "frame_coverage": round(float(frame_coverage), 6),
    }


def is_direct_reference_match(match):
    return (
        match["inlier_count"] >= MIN_DIRECT_INLIERS
        and match["inlier_ratio"] >= MIN_DIRECT_INLIER_RATIO
        and match["frame_coverage"] >= MIN_DIRECT_FRAME_COVERAGE
    )


def scan_video(video_path, reference_paths, sample_fps):
    require_runtime()
    if sample_fps <= 0:
        raise GuardError("sample_fps must be positive")
    video_path = Path(video_path).resolve()
    if not video_path.is_file():
        raise GuardError(f"input video does not exist: {video_path}")
    references = [Path(path).resolve() for path in reference_paths]
    if not references:
        raise GuardError("at least one product reference is required")
    for path in references:
        if not path.is_file():
            raise GuardError(f"product reference does not exist: {path}")

    media = probe_video(video_path)
    sift = cv2.SIFT_create(nfeatures=3000)
    prepared = [prepare_reference(path, sift) for path in references]
    matcher = cv2.BFMatcher()
    capture = cv2.VideoCapture(str(video_path))
    source_fps = capture.get(cv2.CAP_PROP_FPS) or media["fps"] or 25.0
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    sample_every = max(1, round(source_fps / sample_fps))
    samples = []
    previous_gray = None
    frame_index = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        if frame_index % sample_every != 0:
            frame_index += 1
            continue
        timestamp = frame_index / source_fps
        small = resize_for_scan(frame)
        grayscale = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        motion = (
            None
            if previous_gray is None
            else float(np.mean(cv2.absdiff(grayscale, previous_gray)))
        )
        previous_gray = grayscale
        frame_keypoints, frame_descriptors = sift.detectAndCompute(grayscale, None)
        matches = [
            match_reference(
                grayscale,
                frame_keypoints,
                frame_descriptors,
                reference,
                matcher,
            )
            for reference in prepared
        ]
        best = max(
            matches,
            key=lambda item: (
                item["inlier_count"],
                item["frame_coverage"],
                item["inlier_ratio"],
            ),
        )
        samples.append(
            {
                "time_seconds": round(timestamp, 6),
                "motion_score": None if motion is None else round(motion, 6),
                "best_match": best,
                "direct_reference_match": is_direct_reference_match(best),
            }
        )
        frame_index += 1
    capture.release()
    if not samples:
        raise GuardError(f"could not decode sampled frames from {video_path}")
    effective_sample_fps = source_fps / sample_every
    return {
        "video": video_path,
        "media": media,
        "references": [
            {"path": item["path"], "sha256": item["sha256"]}
            for item in prepared
        ],
        "sample_fps": effective_sample_fps,
        "frame_count": frame_count,
        "samples": samples,
    }


def group_suspicious_intervals(scan):
    sample_step = 1.0 / scan["sample_fps"]
    direct = [item for item in scan["samples"] if item["direct_reference_match"]]
    groups = []
    current = []
    for sample in direct:
        if (
            current
            and sample["time_seconds"] - current[-1]["time_seconds"] > sample_step * 1.6
        ):
            groups.append(current)
            current = []
        current.append(sample)
    if current:
        groups.append(current)

    intervals = []
    for group in groups:
        if len(group) < MIN_CONSECUTIVE_DIRECT_SAMPLES:
            continue
        pad = sample_step * 0.55
        start = max(0.0, group[0]["time_seconds"] - pad)
        end = min(scan["media"]["duration"], group[-1]["time_seconds"] + pad)
        peak = max(
            group,
            key=lambda item: item["best_match"]["inlier_count"],
        )
        intervals.append(
            {
                "start_seconds": round(start, 6),
                "end_seconds": round(end, 6),
                "duration_seconds": round(end - start, 6),
                "sample_count": len(group),
                "peak_time_seconds": peak["time_seconds"],
                "peak_inlier_count": peak["best_match"]["inlier_count"],
                "peak_inlier_ratio": peak["best_match"]["inlier_ratio"],
                "peak_frame_coverage": peak["best_match"]["frame_coverage"],
                "reference": peak["best_match"]["reference"],
                "finding_code": "product_reference_still_dominates_frame",
            }
        )
    return intervals


def public_analysis(scan):
    intervals = group_suspicious_intervals(scan)
    return {
        "detector_version": DETECTOR_VERSION,
        "sample_fps": round(scan["sample_fps"], 6),
        "thresholds": {
            "min_direct_inliers": MIN_DIRECT_INLIERS,
            "min_direct_inlier_ratio": MIN_DIRECT_INLIER_RATIO,
            "min_direct_frame_coverage": MIN_DIRECT_FRAME_COVERAGE,
            "min_consecutive_direct_samples": MIN_CONSECUTIVE_DIRECT_SAMPLES,
        },
        "sample_count": len(scan["samples"]),
        "direct_match_sample_count": sum(
            1 for item in scan["samples"] if item["direct_reference_match"]
        ),
        "suspicious_intervals": intervals,
    }


def analyze_video(video_path, reference_paths, sample_fps=DEFAULT_SAMPLE_FPS):
    return public_analysis(scan_video(video_path, reference_paths, sample_fps))


def overlaps(start, end, interval, margin=0.0):
    return not (
        end <= interval["start_seconds"] - margin
        or start >= interval["end_seconds"] + margin
    )


def select_replacement(scan, target, blocked_intervals):
    duration = target["duration_seconds"]
    sample_step = 1.0 / scan["sample_fps"]
    samples = scan["samples"]
    candidates = []
    for sample in samples:
        start = sample["time_seconds"]
        end = start + duration
        if end > scan["media"]["duration"] + 0.001:
            continue
        if any(overlaps(start, end, interval, margin=sample_step) for interval in blocked_intervals):
            continue
        window = [
            item
            for item in samples
            if start <= item["time_seconds"] < end
        ]
        if len(window) < max(2, round(duration * scan["sample_fps"] * 0.65)):
            continue
        if any(item["direct_reference_match"] for item in window):
            continue
        visible = [
            item
            for item in window
            if item["best_match"]["inlier_count"] >= 8
            and item["best_match"]["frame_coverage"] >= 0.005
        ]
        if len(visible) < max(2, round(len(window) * 0.5)):
            continue
        motions = [
            item["motion_score"]
            for item in window
            if item["motion_score"] is not None
        ]
        median_motion = float(np.median(motions)) if motions else 0.0
        if not 2.0 <= median_motion <= 65.0:
            continue
        mean_inliers = float(
            np.mean([item["best_match"]["inlier_count"] for item in visible])
        )
        mean_coverage = float(
            np.mean([item["best_match"]["frame_coverage"] for item in visible])
        )
        distance = abs(
            (start + end) / 2
            - (target["start_seconds"] + target["end_seconds"]) / 2
        )
        score = (
            mean_inliers
            + mean_coverage * 180.0
            + min(median_motion, 30.0) * 0.30
            - distance * 0.025
        )
        candidates.append(
            {
                "start_seconds": round(start, 6),
                "end_seconds": round(end, 6),
                "duration_seconds": round(duration, 6),
                "score": round(score, 6),
                "visible_sample_count": len(visible),
                "mean_inlier_count": round(mean_inliers, 6),
                "mean_frame_coverage": round(mean_coverage, 6),
                "median_motion_score": round(median_motion, 6),
                "strategy": "same_video_clean_moving_product_window",
            }
        )
    if not candidates:
        raise GuardError(
            "product reference still was detected, but no safe moving product "
            f"interval can replace {target['start_seconds']:.3f}s–"
            f"{target['end_seconds']:.3f}s"
        )
    return max(candidates, key=lambda item: item["score"])


def number(value):
    return f"{value:.6f}".rstrip("0").rstrip(".")


def render_visual_replacements(input_path, output_path, repairs, media):
    width = media["width"]
    height = media["height"]
    fps = media["fps"] or 25.0
    duration = media["duration"]
    chains = []
    labels = []
    cursor = 0.0
    segment_index = 0

    def add_segment(start, end):
        nonlocal segment_index
        if end - start <= 0.001:
            return
        label = f"v{segment_index}"
        chains.append(
            f"[0:v]trim=start={number(start)}:end={number(end)},"
            f"setpts=PTS-STARTPTS,scale={width}:{height},setsar=1,"
            f"fps={number(fps)},format=yuv420p[{label}]"
        )
        labels.append(f"[{label}]")
        segment_index += 1

    for repair in sorted(repairs, key=lambda item: item["target_start_seconds"]):
        target_start = repair["target_start_seconds"]
        target_end = repair["target_end_seconds"]
        add_segment(cursor, target_start)
        add_segment(repair["source_start_seconds"], repair["source_end_seconds"])
        cursor = target_end
    add_segment(cursor, duration)
    if not labels:
        raise GuardError("visual repair produced no video segments")
    chains.append("".join(labels) + f"concat=n={len(labels)}:v=1:a=0[vout]")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(input_path),
            "-filter_complex",
            ";".join(chains),
            "-map",
            "[vout]",
            "-map",
            "0:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    if result.returncode != 0:
        raise GuardError(f"ffmpeg visual repair failed: {result.stderr.strip()}")


def guard_video(
    input_video,
    reference_paths,
    output_video,
    report_path=None,
    sample_fps=DEFAULT_SAMPLE_FPS,
):
    require_runtime()
    input_video = Path(input_video).resolve()
    output_video = Path(output_video).resolve()
    if input_video == output_video:
        raise GuardError("input and output video paths must differ")
    scan = scan_video(input_video, reference_paths, sample_fps)
    analysis = public_analysis(scan)
    suspicious = analysis["suspicious_intervals"]
    audio_before = audio_packet_sha256(input_video)
    repairs = []
    output_video.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix="product-still-guard-",
        dir=output_video.parent,
    ) as temporary:
        temporary_output = Path(temporary) / output_video.name
        if suspicious:
            used_sources = []
            for target in suspicious:
                replacement = select_replacement(
                    scan,
                    target,
                    suspicious + used_sources,
                )
                used_sources.append(
                    {
                        "start_seconds": replacement["start_seconds"],
                        "end_seconds": replacement["end_seconds"],
                    }
                )
                repairs.append(
                    {
                        "finding_code": target["finding_code"],
                        "target_start_seconds": target["start_seconds"],
                        "target_end_seconds": target["end_seconds"],
                        "source_start_seconds": replacement["start_seconds"],
                        "source_end_seconds": replacement["end_seconds"],
                        "strategy": replacement["strategy"],
                        "candidate_score": replacement["score"],
                        "candidate_motion_score": replacement["median_motion_score"],
                    }
                )
            render_visual_replacements(
                input_video,
                temporary_output,
                repairs,
                scan["media"],
            )
            verification = analyze_video(
                temporary_output,
                reference_paths,
                sample_fps=sample_fps,
            )
            if verification["suspicious_intervals"]:
                raise GuardError(
                    "automatic visual repair still contains a reference-dominant "
                    "product interval"
                )
            status = "repaired"
        else:
            shutil.copy2(input_video, temporary_output)
            verification = analysis
            status = "clean"

        output_media = probe_video(temporary_output)
        duration_tolerance = max(0.12, 2 / max(output_media["fps"], 1))
        if abs(output_media["duration"] - scan["media"]["duration"]) > duration_tolerance:
            raise GuardError(
                "visual repair changed duration: "
                f"before={scan['media']['duration']:.3f}s "
                f"after={output_media['duration']:.3f}s"
            )
        audio_after = audio_packet_sha256(temporary_output)
        if audio_after != audio_before:
            raise GuardError("visual repair changed the original audio stream")
        os.replace(temporary_output, output_video)

    report = {
        "schema_version": 1,
        "overall": "PASS",
        "status": status,
        "detector_version": DETECTOR_VERSION,
        "input_video": str(input_video),
        "input_sha256": file_sha256(input_video),
        "output_video": str(output_video),
        "output_sha256": file_sha256(output_video),
        "input_duration_seconds": scan["media"]["duration"],
        "output_duration_seconds": probe_video(output_video)["duration"],
        "references": scan["references"],
        "analysis": analysis,
        "repairs": repairs,
        "verification": verification,
        "audio_packet_sha256_before": audio_before,
        "audio_packet_sha256_after": audio_after,
        "audio_preserved": True,
        "paid_tasks_submitted": 0,
    }
    if report_path is not None:
        write_json(report_path, report)
    return report


def parse_args():
    parser = argparse.ArgumentParser(
        description="Detect and locally repair product-reference still inserts."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan")
    scan_parser.add_argument("--input-video", type=Path, required=True)
    scan_parser.add_argument(
        "--product-reference",
        type=Path,
        action="append",
        required=True,
    )
    scan_parser.add_argument("--sample-fps", type=float, default=DEFAULT_SAMPLE_FPS)
    scan_parser.add_argument("--report", type=Path, required=True)

    repair_parser = subparsers.add_parser("repair")
    repair_parser.add_argument("--input-video", type=Path, required=True)
    repair_parser.add_argument(
        "--product-reference",
        type=Path,
        action="append",
        required=True,
    )
    repair_parser.add_argument("--output-video", type=Path, required=True)
    repair_parser.add_argument("--sample-fps", type=float, default=DEFAULT_SAMPLE_FPS)
    repair_parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        if args.command == "scan":
            analysis = analyze_video(
                args.input_video,
                args.product_reference,
                sample_fps=args.sample_fps,
            )
            report = {
                "schema_version": 1,
                "overall": (
                    "FAIL" if analysis["suspicious_intervals"] else "PASS"
                ),
                "input_video": str(args.input_video.resolve()),
                "input_sha256": file_sha256(args.input_video),
                "analysis": analysis,
            }
            write_json(args.report, report)
        else:
            guard_video(
                args.input_video,
                args.product_reference,
                args.output_video,
                report_path=args.report,
                sample_fps=args.sample_fps,
            )
    except GuardError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
