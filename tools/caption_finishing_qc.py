#!/usr/bin/env python3
"""Register and validate the optional final caption-finishing stage."""

import argparse
import csv
import datetime as dt
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from subtitle_workflow_qc import first_stream, probe_media, removal_issues


REQUEST_MODE = "source_faithful"
REQUEST_SOURCE = "explicit_user_request"


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_path(root, value):
    path = Path(str(value or "")).expanduser()
    return path.resolve() if path.is_absolute() else (Path(root) / path).resolve()


def output_dir_for(root, job):
    configured = str(job.get("output_dir") or "").strip()
    if configured:
        return resolve_path(root, configured)
    return (Path(root) / "output" / str(job.get("id") or "")).resolve()


def request_path_for(root, job):
    return output_dir_for(root, job) / "caption_finishing" / "request.json"


def report_path_for(root, job):
    return output_dir_for(root, job) / "caption_finishing" / "caption_finishing_report.json"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_job(root, job_id):
    jobs_path = Path(root) / "jobs.csv"
    if not jobs_path.is_file():
        raise ValueError(f"missing jobs.csv: {jobs_path}")
    with jobs_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("id") == job_id:
                return row
    raise ValueError(f"job not found: {job_id}")


def caption_request_issues(root, job, *, required=False):
    path = request_path_for(root, job)
    if not path.is_file():
        return [f"missing explicit caption request: {path}"] if required else []
    try:
        request = load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"invalid caption request: {exc}"]

    issues = []
    if request.get("schema_version") != 1:
        issues.append("caption request schema_version must be 1")
    if request.get("requested") is not True:
        issues.append("caption request must set requested=true")
    if request.get("mode") != REQUEST_MODE:
        issues.append(f"caption request mode must be {REQUEST_MODE}")
    if request.get("request_source") != REQUEST_SOURCE:
        issues.append("caption request must come from an explicit user request")
    if request.get("job_id") != job.get("id"):
        issues.append("caption request job_id does not match the active job")
    return issues


def captions_requested(root, job):
    path = request_path_for(root, job)
    return path.is_file() and not caption_request_issues(root, job, required=True)


def _bound_file_issues(root, payload, path_key, hash_key, label):
    path = resolve_path(root, payload.get(path_key, ""))
    issues = []
    if not path.is_file():
        issues.append(f"missing {label}: {path}")
    elif payload.get(hash_key) != sha256(path):
        issues.append(f"{label} hash does not match the current file")
    return path, issues


def _active_final_input(root, job):
    output_dir = output_dir_for(root, job)
    removal_path = output_dir / "subtitle_removal" / "subtitle_removal_report.json"
    issues = removal_issues(removal_path)
    if issues:
        return None, None, [f"subtitle removal evidence: {issue}" for issue in issues]
    removal = load_json(removal_path)
    active_path = resolve_path(root, removal.get("output_video", ""))
    active_hash = str(removal.get("output_sha256") or "")

    final_qc_candidates = [
        output_dir / "final_qc" / "final_qc.json",
        output_dir / "final" / "final_qc.json",
    ]
    final_qc_path = next((path for path in final_qc_candidates if path.is_file()), final_qc_candidates[0])
    if not final_qc_path.is_file():
        return active_path, active_hash, [f"missing final QC report: {final_qc_path}"]
    try:
        final_qc = load_json(final_qc_path)
    except (OSError, json.JSONDecodeError) as exc:
        return active_path, active_hash, [f"invalid final QC report: {exc}"]

    bound_issues = []
    if final_qc.get("overall") != "PASS":
        bound_issues.append("final QC report is not PASS")
    videos = final_qc.get("videos") or []
    if len(videos) != 1:
        bound_issues.append("final QC must contain exactly one active final video")
    else:
        checked_path = resolve_path(root, videos[0].get("path", ""))
        if checked_path != active_path:
            bound_issues.append("final QC video is not the active subtitle-removal output")
        if videos[0].get("sha256") != active_hash:
            bound_issues.append("final QC hash does not match the active subtitle-removal output")
    return active_path, active_hash, bound_issues


def captioned_media_issues(input_path, output_path):
    issues = []
    input_probe, input_error = probe_media(input_path)
    output_probe, output_error = probe_media(output_path)
    if input_probe is None:
        issues.append(f"caption input probe failed: {input_error}")
    if output_probe is None:
        issues.append(f"captioned output probe failed: {output_error}")
    if input_probe is None or output_probe is None:
        return issues
    input_video = first_stream(input_probe, "video")
    output_video = first_stream(output_probe, "video")
    if not input_video or not output_video:
        issues.append("caption input and output must both contain video")
    for field in ("width", "height"):
        if input_video.get(field) != output_video.get(field):
            issues.append(f"captioned output changed video {field}")
    input_audio = sum(
        stream.get("codec_type") == "audio"
        for stream in input_probe.get("streams") or []
    )
    output_audio = sum(
        stream.get("codec_type") == "audio"
        for stream in output_probe.get("streams") or []
    )
    if input_audio == 0 or output_audio != input_audio:
        issues.append("captioned output did not preserve required audio streams")
    if any(
        stream.get("codec_type") == "subtitle"
        for stream in output_probe.get("streams") or []
    ):
        issues.append("captioned output must use burned-in pixels, not a subtitle stream")
    try:
        input_duration = float(input_probe.get("format", {}).get("duration") or 0)
        output_duration = float(output_probe.get("format", {}).get("duration") or 0)
    except (TypeError, ValueError):
        input_duration = output_duration = 0.0
    if input_duration <= 0 or output_duration <= 0:
        issues.append("caption input and output duration must be measurable")
    elif abs(input_duration - output_duration) > 0.10:
        issues.append("captioned output duration changed by more than 0.10 seconds")
    if not shutil.which("ffmpeg"):
        issues.append("ffmpeg not found for captioned output decode verification")
    else:
        decoded = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(output_path), "-f", "null", "-"],
            text=True,
            capture_output=True,
        )
        if decoded.returncode != 0:
            issues.append(f"captioned output decode failed: {decoded.stderr.strip()}")
    return issues


def caption_report_issues(root, job):
    issues = caption_request_issues(root, job, required=True)
    report_path = report_path_for(root, job)
    if not report_path.is_file():
        return issues + [f"missing caption finishing report: {report_path}"]
    try:
        report = load_json(report_path)
    except (OSError, json.JSONDecodeError) as exc:
        return issues + [f"invalid caption finishing report: {exc}"]

    if report.get("schema_version") != 1:
        issues.append("caption finishing report schema_version must be 1")
    if report.get("overall") != "PASS":
        issues.append("caption finishing report overall is not PASS")
    if report.get("engine") != "source-faithful-captions+hyperframes@0.7.64":
        issues.append("caption finishing report uses an unapproved engine")
    if report.get("captions_generated_in_seedance") is not False:
        issues.append("captions must be added after generation, not inside Seedance")

    request_path, request_issues = _bound_file_issues(
        root, report, "request", "request_sha256", "caption request"
    )
    issues.extend(request_issues)
    if request_path != request_path_for(root, job):
        issues.append("caption finishing report points to a different request")

    active_path, active_hash, active_issues = _active_final_input(root, job)
    issues.extend(active_issues)
    input_path, input_issues = _bound_file_issues(
        root, report, "input_video", "input_sha256", "caption input video"
    )
    issues.extend(input_issues)
    if active_path and input_path != active_path:
        issues.append("caption input is not the final-QC-approved active video")
    if active_hash and report.get("input_sha256") != active_hash:
        issues.append("caption input hash does not match the final-QC-approved video")

    source_path, source_issues = _bound_file_issues(
        root, report, "source_video", "source_sha256", "source video"
    )
    issues.extend(source_issues)
    expected_source = resolve_path(root, job.get("video_path", ""))
    if source_path != expected_source:
        issues.append("caption source video does not match the job source video")

    artifact_fields = (
        ("caption_blueprint", "caption_blueprint_sha256", "caption blueprint"),
        ("caption_timeline", "caption_timeline_sha256", "caption timeline"),
        ("hyperframes_check", "hyperframes_check_sha256", "HyperFrames check"),
        ("visual_review", "visual_review_sha256", "caption visual review"),
        ("caption_qc", "caption_qc_sha256", "caption QC"),
        ("output_video", "output_sha256", "captioned output video"),
    )
    bound_paths = {}
    for path_key, hash_key, label in artifact_fields:
        bound_path, bound_issues = _bound_file_issues(root, report, path_key, hash_key, label)
        bound_paths[path_key] = bound_path
        issues.extend(bound_issues)

    caption_qc_path = bound_paths.get("caption_qc")
    if caption_qc_path and caption_qc_path.is_file():
        try:
            caption_qc = load_json(caption_qc_path)
            if caption_qc.get("status") != "PASS":
                issues.append("source-faithful caption QC is not PASS")
            qc_artifact = resolve_path(root, caption_qc.get("artifact", ""))
            if qc_artifact != bound_paths.get("output_video"):
                issues.append("caption QC artifact is not the reported output video")
        except (OSError, json.JSONDecodeError) as exc:
            issues.append(f"invalid caption QC: {exc}")

    hyperframes_path = bound_paths.get("hyperframes_check")
    if hyperframes_path and hyperframes_path.is_file():
        try:
            if load_json(hyperframes_path).get("ok") is not True:
                issues.append("HyperFrames check is not PASS")
        except (OSError, json.JSONDecodeError) as exc:
            issues.append(f"invalid HyperFrames check: {exc}")

    visual_path = bound_paths.get("visual_review")
    if visual_path and visual_path.is_file():
        try:
            visual = load_json(visual_path)
            visual_checks = visual.get("checks") or {}
            if (
                visual.get("status") != "PASS"
                or not visual_checks
                or not all(visual_checks.values())
            ):
                issues.append("caption visual review is not PASS")
        except (OSError, json.JSONDecodeError) as exc:
            issues.append(f"invalid caption visual review: {exc}")

    if bound_paths.get("output_video") == input_path:
        issues.append("captioned output must be a distinct file from the immutable input")
    output_video = bound_paths.get("output_video")
    if input_path.is_file() and output_video and output_video.is_file():
        issues.extend(captioned_media_issues(input_path, output_video))
    return issues


def write_request(root, job_id, note, explicit_user_request):
    if not explicit_user_request:
        raise ValueError("--explicit-user-request is required; final captions are opt-in")
    job = load_job(root, job_id)
    path = request_path_for(root, job)
    if path.exists():
        existing_issues = caption_request_issues(root, job, required=True)
        if existing_issues:
            raise ValueError("existing caption request is invalid: " + "; ".join(existing_issues))
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "job_id": job_id,
        "requested": True,
        "mode": REQUEST_MODE,
        "request_source": REQUEST_SOURCE,
        "requested_at": dt.datetime.now().isoformat(timespec="seconds"),
        "note": str(note or "").strip(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def write_report(root, job, artifacts):
    request_path = request_path_for(root, job)
    request_issues = caption_request_issues(root, job, required=True)
    if request_issues:
        raise ValueError("invalid caption request: " + "; ".join(request_issues))
    active_path, active_hash, active_issues = _active_final_input(root, job)
    if active_issues:
        raise ValueError("invalid final caption input: " + "; ".join(active_issues))

    source_path = resolve_path(root, job.get("video_path", ""))
    paths = {key: resolve_path(root, value) for key, value in artifacts.items()}
    missing = [f"{key}: {path}" for key, path in paths.items() if not path.is_file()]
    if not source_path.is_file():
        missing.append(f"source_video: {source_path}")
    if missing:
        raise ValueError("missing caption artifacts: " + "; ".join(missing))

    report = {
        "schema_version": 1,
        "overall": "PASS",
        "engine": "source-faithful-captions+hyperframes@0.7.64",
        "captions_generated_in_seedance": False,
        "request": str(request_path.resolve()),
        "request_sha256": sha256(request_path),
        "source_video": str(source_path),
        "source_sha256": sha256(source_path),
        "input_video": str(active_path),
        "input_sha256": active_hash,
    }
    for key, path in paths.items():
        report[key] = str(path)
        report[f"{key}_sha256" if key != "output_video" else "output_sha256"] = sha256(path)
    path = report_path_for(root, job)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    issues = caption_report_issues(root, job)
    if issues:
        raise ValueError("caption report failed validation: " + "; ".join(issues))
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    request_parser = subparsers.add_parser("request", help="Record an explicit opt-in request.")
    request_parser.add_argument("--root", default=".")
    request_parser.add_argument("--job-id", required=True)
    request_parser.add_argument("--explicit-user-request", action="store_true")
    request_parser.add_argument("--note", default="")

    check_parser = subparsers.add_parser("check", help="Validate the completed caption stage.")
    check_parser.add_argument("--root", default=".")
    check_parser.add_argument("--job-id", required=True)
    check_parser.add_argument("--json-out")

    report_parser = subparsers.add_parser("report", help="Write the bound stage report.")
    report_parser.add_argument("--root", default=".")
    report_parser.add_argument("--job-id", required=True)
    report_parser.add_argument("--caption-blueprint", required=True)
    report_parser.add_argument("--caption-timeline", required=True)
    report_parser.add_argument("--hyperframes-check", required=True)
    report_parser.add_argument("--visual-review", required=True)
    report_parser.add_argument("--caption-qc", required=True)
    report_parser.add_argument("--output-video", required=True)

    args = parser.parse_args()
    root = Path(args.root).resolve()
    if args.command == "request":
        path = write_request(root, args.job_id, args.note, args.explicit_user_request)
        print(path)
        return

    job = load_job(root, args.job_id)
    if args.command == "report":
        path = write_report(
            root,
            job,
            {
                "caption_blueprint": args.caption_blueprint,
                "caption_timeline": args.caption_timeline,
                "hyperframes_check": args.hyperframes_check,
                "visual_review": args.visual_review,
                "caption_qc": args.caption_qc,
                "output_video": args.output_video,
            },
        )
        print(path)
        return

    issues = caption_report_issues(root, job)
    result = {
        "overall": "PASS" if not issues else "FAIL",
        "report": str(report_path_for(root, job)),
        "issues": issues,
    }
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if not issues else 1)


if __name__ == "__main__":
    main()
