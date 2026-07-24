#!/usr/bin/env python3
import argparse
import hashlib
import io
import json
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageChops


DETECTION_CLASSES = {"clean", "burned_in"}
REMOVAL_ACTIONS = {"skipped_clean", "mediakit_pro"}
STANDING_APPROVAL = "workflow_generated_hard_subtitle_v1"


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path, label, issues):
    if not path.is_file():
        issues.append(f"missing {label}: {path}")
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        issues.append(f"invalid {label}: {exc}")
        return {}
    if not isinstance(payload, dict):
        issues.append(f"invalid {label}: top level must be an object")
        return {}
    return payload


def referenced_path(value, report_path):
    path = Path(str(value or "")).expanduser()
    if path.is_absolute():
        return path.resolve()
    cwd_path = path.resolve()
    if cwd_path.exists():
        return cwd_path
    return (report_path.parent / path).resolve()


def is_within(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def check_bound_file(path, expected_hash, label, issues):
    if not path.is_file():
        issues.append(f"missing {label}: {path}")
        return
    if not expected_hash:
        issues.append(f"missing {label} hash: {path}")
        return
    if sha256_file(path) != expected_hash:
        issues.append(f"{label} hash does not match current file: {path}")


def probe_media(path):
    if not shutil.which("ffprobe"):
        return None, "ffprobe not found"
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return None, result.stderr.strip() or "ffprobe failed"
    try:
        return json.loads(result.stdout), ""
    except json.JSONDecodeError as exc:
        return None, f"invalid ffprobe JSON: {exc}"


def first_stream(probe, stream_type):
    return next(
        (
            stream
            for stream in probe.get("streams") or []
            if stream.get("codec_type") == stream_type
        ),
        {},
    )


def frame_matches_video(video_path, timestamp, frame_path):
    try:
        with Image.open(frame_path) as evidence_image:
            evidence = evidence_image.convert("RGB")
    except (OSError, ValueError) as exc:
        return False, f"unreadable image: {exc}"
    if not shutil.which("ffmpeg"):
        return False, "ffmpeg not found"
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            f"{timestamp:.6f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "-",
        ],
        capture_output=True,
    )
    if result.returncode != 0 or not result.stdout:
        return False, result.stderr.decode("utf-8", errors="replace").strip() or "frame extraction failed"
    try:
        with Image.open(io.BytesIO(result.stdout)) as extracted_image:
            extracted = extracted_image.convert("RGB")
    except (OSError, ValueError) as exc:
        return False, f"invalid extracted frame: {exc}"
    if evidence.size != extracted.size:
        return False, f"size mismatch: evidence={evidence.size}, extracted={extracted.size}"
    histogram = ImageChops.difference(evidence, extracted).histogram()
    total = max(1, evidence.width * evidence.height * 3)
    mean_absolute_error = sum(
        (value % 256) * count for value, count in enumerate(histogram)
    ) / total
    if mean_absolute_error > 8.0:
        return False, f"pixel difference is too large: mean_absolute_error={mean_absolute_error:.3f}"
    return True, ""


def media_integrity_issues(source_path, output_path):
    issues = []
    source_probe, source_error = probe_media(source_path)
    output_probe, output_error = probe_media(output_path)
    if source_probe is None:
        issues.append(f"source video probe failed: {source_error}")
    if output_probe is None:
        issues.append(f"output video probe failed: {output_error}")
    if source_probe is None or output_probe is None:
        return issues

    source_video = first_stream(source_probe, "video")
    output_video = first_stream(output_probe, "video")
    if not source_video or not output_video:
        issues.append("source and output must both contain a video stream")
    for field in ("width", "height", "avg_frame_rate"):
        if source_video.get(field) != output_video.get(field):
            issues.append(f"subtitle-removal output changed video {field}")
    source_audio_count = sum(
        stream.get("codec_type") == "audio"
        for stream in source_probe.get("streams") or []
    )
    output_audio_count = sum(
        stream.get("codec_type") == "audio"
        for stream in output_probe.get("streams") or []
    )
    if source_audio_count != output_audio_count:
        issues.append("subtitle-removal output changed the required audio stream count")
    output_subtitle_count = sum(
        stream.get("codec_type") == "subtitle"
        for stream in output_probe.get("streams") or []
    )
    if output_subtitle_count != 0:
        issues.append("active subtitle-removal output still has a subtitle stream")
    try:
        source_duration = float(source_probe.get("format", {}).get("duration") or 0)
        output_duration = float(output_probe.get("format", {}).get("duration") or 0)
    except (TypeError, ValueError):
        source_duration = output_duration = 0.0
    if source_duration <= 0 or output_duration <= 0:
        issues.append("source and output duration must be measurable")
    elif abs(source_duration - output_duration) > 0.10:
        issues.append("subtitle-removal output duration changed by more than 0.10 seconds")

    if not shutil.which("ffmpeg"):
        issues.append("ffmpeg not found for output decode verification")
    else:
        decode = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(output_path),
                "-f",
                "null",
                "-",
            ],
            text=True,
            capture_output=True,
        )
        if decode.returncode != 0:
            issues.append(f"subtitle-removal output decode failed: {decode.stderr.strip()}")
    return issues


def detection_issues(report_path):
    report_path = Path(report_path).resolve()
    issues = []
    report = load_json(report_path, "subtitle detection report", issues)
    if not report:
        return issues
    if report.get("schema_version") != 2:
        issues.append("subtitle detection schema_version must be 2")
    if report.get("overall") != "PASS":
        issues.append("subtitle detection overall is not PASS")

    job_output_dir = report_path.parent.parent
    expected_report_path = (
        job_output_dir / "subtitle_removal" / "subtitle_detection.json"
    ).resolve()
    if report_path != expected_report_path:
        issues.append(f"subtitle detection must use current job report: {expected_report_path}")

    master_path = referenced_path(report.get("finishing_master"), report_path)
    expected_master_path = (job_output_dir / "final" / "final_video.mp4").resolve()
    if master_path != expected_master_path:
        issues.append(
            f"subtitle detection must inspect the exact finished video: {expected_master_path}"
        )
    check_bound_file(
        master_path,
        report.get("finishing_master_sha256"),
        "finishing master",
        issues,
    )

    try:
        duration = float(report.get("duration_seconds"))
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        issues.append("subtitle detection duration_seconds must be positive")

    if master_path.is_file():
        probe, probe_error = probe_media(master_path)
        if probe is None:
            issues.append(f"finishing master media probe failed: {probe_error}")
        else:
            if not first_stream(probe, "video"):
                issues.append("finishing master has no video stream")
            subtitle_stream_count = sum(
                stream.get("codec_type") == "subtitle"
                for stream in probe.get("streams") or []
            )
            if subtitle_stream_count:
                issues.append(
                    "Seedance/local-finishing output must not contain a separate subtitle stream"
                )
            try:
                measured_duration = float(probe.get("format", {}).get("duration") or 0)
            except (TypeError, ValueError):
                measured_duration = 0.0
            if measured_duration <= 0 or abs(measured_duration - duration) > 0.05:
                issues.append("subtitle detection duration_seconds does not match ffprobe")

    classification = report.get("classification")
    if classification not in DETECTION_CLASSES:
        issues.append("subtitle detection classification must be clean or burned_in")

    evidence = report.get("evidence_frames")
    timestamps = []
    evidence_paths = set()
    if not isinstance(evidence, list) or not evidence:
        issues.append("subtitle detection has no visual evidence frames")
    else:
        for index, frame in enumerate(evidence, start=1):
            if not isinstance(frame, dict):
                issues.append(f"subtitle detection evidence frame {index} must be an object")
                continue
            frame_path = referenced_path(frame.get("path"), report_path)
            if frame_path in evidence_paths:
                issues.append("subtitle detection contains a duplicate evidence frame path")
            evidence_paths.add(frame_path)
            if not is_within(frame_path, report_path.parent):
                issues.append(
                    f"subtitle detection evidence frame {index} is outside the current subtitle-removal directory"
                )
            check_bound_file(frame_path, frame.get("sha256"), "evidence frame", issues)
            try:
                timestamp = float(frame.get("timestamp_seconds"))
            except (TypeError, ValueError):
                issues.append(
                    f"subtitle detection evidence frame {index} has no numeric timestamp"
                )
                continue
            timestamps.append(timestamp)
            if frame_path.is_file() and master_path.is_file():
                matches, detail = frame_matches_video(
                    master_path,
                    timestamp,
                    frame_path,
                )
                if not matches:
                    issues.append(
                        f"subtitle detection evidence frame {index} is not the corresponding finishing-master frame: {detail}"
                    )

    if timestamps and duration > 0:
        ordered = sorted(timestamps)
        if ordered[0] > 0.25 or ordered[-1] < max(0.0, duration - 0.25):
            issues.append("subtitle detection evidence does not cover the full video timeline")
        if any(value < 0 or value > duration + 0.05 for value in ordered):
            issues.append("subtitle detection evidence timestamp is outside the video duration")
        if any(right - left > 0.75 for left, right in zip(ordered, ordered[1:])):
            issues.append("subtitle detection evidence sampling gap exceeds 0.75 seconds")

    intervals = report.get("subtitle_intervals")
    if not isinstance(intervals, list):
        issues.append("subtitle detection subtitle_intervals must be a list")
        intervals = []
    if classification == "burned_in" and not intervals:
        issues.append("burned-in result requires a subtitle interval")
    if classification == "clean" and intervals:
        issues.append("clean result cannot declare subtitle intervals")
    for index, interval in enumerate(intervals, start=1):
        if not isinstance(interval, dict):
            issues.append(f"subtitle interval {index} must be an object")
            continue
        try:
            start = float(interval.get("start"))
            end = float(interval.get("end"))
        except (TypeError, ValueError):
            issues.append(f"subtitle interval {index} is not numeric")
            continue
        if start < 0 or end <= start or (duration > 0 and end > duration + 0.05):
            issues.append(f"subtitle interval {index} is invalid")
    return issues


def detection_summary(report_path):
    report_path = Path(report_path).resolve()
    issues = detection_issues(report_path)
    if issues:
        return {"valid": False, "burned_in": False, "issues": issues}
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return {
        "valid": True,
        "burned_in": report.get("classification") == "burned_in",
        "subtitle_intervals": report.get("subtitle_intervals") or [],
        "issues": [],
    }


def repair_qc_issues(
    qc_path,
    source_hash,
    output_hash,
    output_path,
    require_visual,
    detected_intervals=None,
):
    issues = []
    qc = load_json(qc_path, "subtitle removal visual QC", issues)
    if not qc:
        return issues
    if qc.get("overall") != "PASS":
        issues.append("subtitle removal visual QC overall is not PASS")
    if qc.get("source_sha256") != source_hash:
        issues.append("subtitle removal visual QC source hash does not match")
    if qc.get("output_sha256") != output_hash:
        issues.append("subtitle removal visual QC output hash does not match")
    for field in ("decode_passed", "required_audio_preserved"):
        if qc.get(field) is not True:
            issues.append(f"subtitle removal visual QC requires {field}=true")
    if require_visual:
        for field in (
            "subtitles_absent",
            "valid_scene_text_preserved",
            "foreground_subjects_undamaged",
            "temporally_stable",
        ):
            if qc.get(field) is not True:
                issues.append(f"subtitle removal visual QC requires {field}=true")
        reviewed_intervals = qc.get("subtitle_intervals_reviewed") or []
        if not reviewed_intervals:
            issues.append("subtitle removal visual QC has no reviewed subtitle intervals")
        for detected in detected_intervals or []:
            try:
                detected_start = float(detected.get("start"))
                detected_end = float(detected.get("end"))
            except (AttributeError, TypeError, ValueError):
                issues.append("subtitle removal visual QC received an invalid detected interval")
                continue
            covered = False
            for reviewed in reviewed_intervals:
                try:
                    reviewed_start = float(reviewed.get("start"))
                    reviewed_end = float(reviewed.get("end"))
                except (AttributeError, TypeError, ValueError):
                    continue
                if reviewed_start <= detected_start and reviewed_end >= detected_end:
                    covered = True
                    break
            if not covered:
                issues.append(
                    f"subtitle removal visual QC did not cover detected interval {detected_start}-{detected_end}"
                )
        high_risk_windows = qc.get("high_risk_windows") or []
        if len(high_risk_windows) < 2:
            issues.append("subtitle removal visual QC requires at least two high-risk windows")
        for window_index, window in enumerate(high_risk_windows, start=1):
            try:
                window_start = float(window.get("start"))
                window_end = float(window.get("end"))
            except (AttributeError, TypeError, ValueError):
                issues.append(f"high-risk window {window_index} has invalid times")
                continue
            if window_end <= window_start:
                issues.append(f"high-risk window {window_index} has invalid times")
                continue
            frame_evidence = window.get("frame_evidence") or []
            minimum_frames = max(2, int((window_end - window_start) * 8) + 1)
            if len(frame_evidence) < minimum_frames:
                issues.append(
                    f"high-risk window {window_index} has fewer than 8fps frame evidence"
                )
            valid_frame_paths = []
            valid_timestamps = []
            for frame_index, frame in enumerate(frame_evidence, start=1):
                if not isinstance(frame, dict):
                    issues.append(
                        f"high-risk window {window_index} frame {frame_index} must be an object"
                    )
                    continue
                frame_path = referenced_path(frame.get("path"), qc_path)
                if not is_within(frame_path, qc_path.parent):
                    issues.append(
                        f"high-risk window {window_index} frame {frame_index} is outside the current subtitle-removal directory"
                    )
                check_bound_file(
                    frame_path,
                    frame.get("sha256"),
                    "high-risk visual QC frame",
                    issues,
                )
                valid_frame_paths.append(str(frame_path))
                try:
                    timestamp = float(frame.get("timestamp_seconds"))
                except (TypeError, ValueError):
                    issues.append(
                        f"high-risk window {window_index} frame {frame_index} has no numeric timestamp"
                    )
                    continue
                if timestamp < window_start or timestamp > window_end:
                    issues.append(
                        f"high-risk window {window_index} frame {frame_index} is outside its window"
                    )
                    continue
                valid_timestamps.append(timestamp)
                if frame_path.is_file() and output_path.is_file():
                    matches, detail = frame_matches_video(
                        output_path,
                        timestamp,
                        frame_path,
                    )
                    if not matches:
                        issues.append(
                            f"high-risk window {window_index} frame {frame_index} is not the corresponding repair-output frame: {detail}"
                        )
            if len(valid_frame_paths) != len(set(valid_frame_paths)):
                issues.append(
                    f"high-risk window {window_index} repeats a frame path"
                )
            if len(valid_timestamps) != len(set(valid_timestamps)):
                issues.append(
                    f"high-risk window {window_index} repeats a frame timestamp"
                )
            if valid_timestamps and valid_timestamps != sorted(valid_timestamps):
                issues.append(
                    f"high-risk window {window_index} frame timestamps are not ordered"
                )
            if valid_timestamps:
                coverage_points = [window_start, *valid_timestamps, window_end]
                maximum_gap = max(
                    later - earlier
                    for earlier, later in zip(coverage_points, coverage_points[1:])
                )
                if maximum_gap > 0.125001:
                    issues.append(
                        f"high-risk window {window_index} frame evidence has a gap greater than 0.125s"
                    )
    return issues


def removal_issues(report_path):
    report_path = Path(report_path).resolve()
    issues = []
    report = load_json(report_path, "subtitle removal report", issues)
    if not report:
        return issues
    if report.get("schema_version") != 1:
        issues.append("subtitle removal schema_version must be 1")
    if report.get("overall") != "PASS":
        issues.append("subtitle removal overall is not PASS")

    detection_path = referenced_path(report.get("detection_report"), report_path)
    job_output_dir = report_path.parent.parent
    expected_detection_path = (
        job_output_dir / "subtitle_removal" / "subtitle_detection.json"
    ).resolve()
    if detection_path != expected_detection_path:
        issues.append(
            "subtitle removal must use the current job detection report: "
            f"expected {expected_detection_path}, got {detection_path}"
        )
    check_bound_file(
        detection_path,
        report.get("detection_sha256"),
        "subtitle detection report",
        issues,
    )
    summary = detection_summary(detection_path) if detection_path.is_file() else {
        "valid": False,
        "burned_in": False,
        "issues": [],
    }
    issues.extend(f"detection evidence: {issue}" for issue in summary["issues"])

    source_path = referenced_path(report.get("source_video"), report_path)
    output_path = referenced_path(report.get("output_video"), report_path)
    expected_source_path = (job_output_dir / "final" / "final_video.mp4").resolve()
    if source_path != expected_source_path:
        issues.append(
            f"subtitle removal source must be the current finished video: {expected_source_path}"
        )
    if not is_within(output_path, (job_output_dir / "final").resolve()):
        issues.append("subtitle removal output must stay in the current job final directory")
    source_hash = report.get("source_sha256")
    output_hash = report.get("output_sha256")
    check_bound_file(source_path, source_hash, "source video", issues)
    check_bound_file(output_path, output_hash, "output video", issues)
    if source_path.is_file() and output_path.is_file():
        issues.extend(media_integrity_issues(source_path, output_path))

    action = report.get("action")
    if action not in REMOVAL_ACTIONS:
        issues.append(f"subtitle removal action must be one of {sorted(REMOVAL_ACTIONS)}")
        return issues
    paid_tasks = report.get("paid_tasks_submitted")
    if report.get("final_subtitle_streams") != 0:
        issues.append("active subtitle-removal output must have final_subtitle_streams=0")

    if summary["burned_in"]:
        if action != "mediakit_pro":
            issues.append("burned-in subtitle detection requires action=mediakit_pro")
        if paid_tasks != 1:
            issues.append("burned-in subtitle removal requires exactly one paid task")
        if not report.get("task_id"):
            issues.append("MediaKit subtitle removal requires a task_id")
        if report.get("standing_approval") != STANDING_APPROVAL:
            issues.append("MediaKit subtitle removal is missing the workflow standing approval")
        if report.get("automatic_retry_allowed") is not False:
            issues.append("automatic paid subtitle-removal retry must be false")
        try:
            attempt_number = int(report.get("attempt_number") or 1)
        except (TypeError, ValueError):
            attempt_number = 0
        if attempt_number < 1:
            issues.append("MediaKit subtitle removal attempt_number must be positive")
        if attempt_number > 1 and report.get("retry_approval") != "explicit_user_targeted_retry":
            issues.append("MediaKit subtitle retry is missing explicit targeted approval")
        attempt_path = referenced_path(report.get("paid_attempt_record"), report_path)
        attempt_filename = (
            "paid_attempt.json"
            if attempt_number == 1
            else f"paid_attempt_{attempt_number}.json"
        )
        expected_attempt_path = (report_path.parent / attempt_filename).resolve()
        if attempt_path != expected_attempt_path:
            issues.append(
                f"MediaKit subtitle removal must use current paid attempt record: {expected_attempt_path}"
            )
        check_bound_file(
            attempt_path,
            report.get("paid_attempt_sha256"),
            "MediaKit paid attempt record",
            issues,
        )
        attempt = load_json(attempt_path, "MediaKit paid attempt record", issues)
        if attempt:
            if (
                attempt.get("schema_version") != 1
                or attempt.get("attempt_number") != attempt_number
            ):
                issues.append(
                    "MediaKit paid attempt record must use schema 1 and match attempt_number"
                )
            if attempt.get("standing_approval") != STANDING_APPROVAL:
                issues.append("MediaKit paid attempt record has the wrong standing approval")
            if attempt.get("source_sha256") != source_hash:
                issues.append("MediaKit paid attempt source hash does not match")
            if attempt.get("task_id") != report.get("task_id"):
                issues.append("MediaKit paid attempt task_id does not match the removal report")
            if attempt.get("status") != "completed":
                issues.append("MediaKit paid attempt did not complete")
    else:
        if action == "mediakit_pro":
            issues.append("MediaKit cannot run without burned-in subtitle detection")
        if paid_tasks != 0:
            issues.append("clean subtitle handling must submit zero paid tasks")

    if action == "skipped_clean":
        if source_path != output_path:
            issues.append("skipped_clean must keep the original final video as output")
    else:
        if source_path == output_path:
            issues.append("subtitle repair output must be distinct from the source video")
        qc_path = referenced_path(report.get("visual_qc_report"), report_path)
        issues.extend(
            repair_qc_issues(
                qc_path,
                source_hash,
                output_hash,
                output_path,
                require_visual=action == "mediakit_pro",
                detected_intervals=summary.get("subtitle_intervals") or [],
            )
        )
    return issues


def main():
    parser = argparse.ArgumentParser(description="Validate generated-subtitle workflow evidence.")
    parser.add_argument("mode", choices=("detection", "removal"))
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    issues = detection_issues(args.report) if args.mode == "detection" else removal_issues(args.report)
    result = {"overall": "PASS" if not issues else "FAIL", "issues": issues}
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if not issues else 1)


if __name__ == "__main__":
    main()
