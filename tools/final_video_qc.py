#!/usr/bin/env python3
import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


def run(cmd):
    return subprocess.run(cmd, text=True, capture_output=True)


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ffprobe(path):
    result = run([
        "ffprobe",
        "-v", "error",
        "-show_format",
        "-show_streams",
        "-of", "json",
        str(path),
    ])
    if result.returncode != 0:
        return None, result.stderr.strip()
    try:
        return json.loads(result.stdout), ""
    except json.JSONDecodeError as exc:
        return None, f"invalid ffprobe json: {exc}"


def video_metrics(path):
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "readable": False,
            "probe_error": "missing file",
            "duration": 0.0,
            "video_streams": 0,
            "audio_streams": 0,
        }
    data, error = ffprobe(path)
    if data is None:
        return {
            "path": str(path),
            "exists": True,
            "readable": False,
            "probe_error": error,
            "duration": 0.0,
            "video_streams": 0,
            "audio_streams": 0,
        }
    streams = data.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    duration = float(data.get("format", {}).get("duration", 0) or 0)
    first_video = video_streams[0] if video_streams else {}
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "exists": True,
        "readable": True,
        "probe_error": "",
        "duration": duration,
        "video_streams": len(video_streams),
        "audio_streams": len(audio_streams),
        "width": first_video.get("width"),
        "height": first_video.get("height"),
        "codec": first_video.get("codec_name"),
    }


def technical_detect(path, contact_sheet=None):
    if not shutil.which("ffmpeg"):
        unavailable = {
            "available": False,
            "events": [],
            "error": "ffmpeg not found",
        }
        return unavailable, dict(unavailable), 0
    filter_complex = (
        "[0:v]split=3[freeze_in][black_in][sheet_in];"
        "[freeze_in]freezedetect=n=-60dB:d=0.5[freeze_out];"
        "[black_in]blackdetect=d=0.5:pix_th=0.10[black_out];"
        "[sheet_in]fps=1/3,scale=180:-1,tile=5x4[sheet_out]"
        if contact_sheet is not None
        else (
            "[0:v]split=2[freeze_in][black_in];"
            "[freeze_in]freezedetect=n=-60dB:d=0.5[freeze_out];"
            "[black_in]blackdetect=d=0.5:pix_th=0.10[black_out]"
        )
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-nostats",
        "-i", str(path),
        "-filter_complex",
        filter_complex,
        "-map", "[freeze_out]",
        "-map", "[black_out]",
        "-f", "null",
        "-",
    ]
    if contact_sheet is not None:
        contact_sheet.parent.mkdir(parents=True, exist_ok=True)
        cmd.extend([
            "-map", "[sheet_out]",
            "-frames:v", "1",
            "-q:v", "3",
            str(contact_sheet),
        ])
    result = run(cmd)
    text = result.stderr + "\n" + result.stdout
    available = result.returncode == 0
    error = "" if available else result.stderr[-1000:]
    freeze_events = [
        line.strip()
        for line in text.splitlines()
        if "freezedetect" in line and "freeze_" in line
    ]
    black_events = [
        line.strip()
        for line in text.splitlines()
        if "blackdetect" in line and "black_" in line
    ]
    return (
        {"available": available, "events": freeze_events, "error": error},
        {"available": available, "events": black_events, "error": error},
        1,
    )


def low_motion_detect(path):
    if not shutil.which("ffmpeg"):
        return {"available": False, "events": [], "error": "ffmpeg not found"}
    result = run([
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i", str(path),
        "-vf", "freezedetect=n=0.02:d=0.5",
        "-f", "null",
        "-",
    ])
    text = result.stderr + "\n" + result.stdout
    events = [line.strip() for line in text.splitlines() if "freezedetect" in line and "freeze_start" in line]
    return {"available": True, "events": events, "error": "" if result.returncode == 0 else result.stderr[-1000:]}


def skipped_detector(reason, available=False):
    return {"available": available, "events": [], "error": reason}


def load_text(path):
    if not path:
        return ""
    p = Path(path)
    return p.read_text(encoding="utf-8") if p.exists() else ""


def write_md(path, report):
    lines = [
        "# Final Video Technical QC",
        "",
        f"- Overall: **{report['overall']}**",
        f"- Target duration: `{report['target_duration']}`",
        f"- Duration tolerance: `{report['duration_tolerance']}`",
        "",
        "## Checks",
        "",
    ]
    for check in report["checks"]:
        lines.append(f"- {check['status']}: `{check['name']}` - {check['detail']}")
    lines.extend(["", "## Videos", ""])
    for item in report["videos"]:
        lines.append(f"### `{item['path']}`")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(item, ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")
    if report.get("contact_sheet"):
        lines.extend(["## Contact Sheet", "", f"`{report['contact_sheet']}`", ""])
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Run technical QC for final/generated videos.")
    parser.add_argument("--videos", nargs="+", type=Path, required=True)
    parser.add_argument("--target-duration", type=float, default=30.0)
    parser.add_argument("--duration-tolerance", type=float, default=3.0)
    parser.add_argument("--source-video", type=Path)
    parser.add_argument("--max-extra-low-motion-holds", type=int, default=0)
    parser.add_argument("--brand-term", action="append", default=[])
    parser.add_argument("--asr-md", type=Path)
    parser.add_argument(
        "--contact-sheet",
        action="store_true",
        help="Deprecated compatibility flag; the technical scan always emits the required sheet.",
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    checks = []
    video_reports = []

    if not shutil.which("ffprobe"):
        checks.append({"name": "ffprobe_available", "status": "STOP", "detail": "ffprobe not found"})
    else:
        checks.append({"name": "ffprobe_available", "status": "PASS", "detail": "ffprobe found"})

    contact_sheet = args.out_dir / "contact_sheet.jpg"
    contact_sheet.unlink(missing_ok=True)
    contact_sheet_requested = True
    total_duration = 0.0
    for video in args.videos:
        metrics = video_metrics(video)
        if metrics.get("readable") and metrics.get("video_streams", 0) > 0:
            sheet_path = (
                contact_sheet
                if contact_sheet_requested and not contact_sheet.exists()
                else None
            )
            freeze, black, scan_passes = technical_detect(video, sheet_path)
            if sheet_path is not None:
                contact_sheet_requested = False
        elif metrics.get("readable"):
            freeze = skipped_detector("skipped: video has no video stream", available=True)
            black = skipped_detector("skipped: video has no video stream", available=True)
            scan_passes = 0
        else:
            freeze = skipped_detector("skipped: video is missing, unreadable, or has no video stream")
            black = skipped_detector("skipped: video is missing, unreadable, or has no video stream")
            scan_passes = 0
        metrics["freeze"] = freeze
        metrics["black"] = black
        metrics["technical_scan"] = {
            "passes": scan_passes,
            "detectors": ["freeze", "black"],
        }
        video_reports.append(metrics)
        total_duration += float(metrics.get("duration", 0) or 0)

    missing = [v["path"] for v in video_reports if not v.get("exists")]
    unreadable = [v["path"] for v in video_reports if v.get("exists") and not v.get("readable")]
    checks.append({
        "name": "video_files_exist",
        "status": "PASS" if not missing else "STOP",
        "detail": f"missing={missing}",
    })
    checks.append({
        "name": "video_files_readable",
        "status": "PASS" if not unreadable else "STOP",
        "detail": f"unreadable={unreadable}",
    })
    checks.append({
        "name": "video_stream_present",
        "status": "PASS" if all(v.get("video_streams", 0) > 0 for v in video_reports) else "FAIL",
        "detail": f"video_stream_counts={[v.get('video_streams', 0) for v in video_reports]}",
    })
    checks.append({
        "name": "audio_stream_present",
        "status": "PASS" if all(v.get("audio_streams", 0) > 0 for v in video_reports) else "FAIL",
        "detail": f"audio_stream_counts={[v.get('audio_streams', 0) for v in video_reports]}",
    })
    duration_ok = abs(total_duration - args.target_duration) <= args.duration_tolerance
    checks.append({
        "name": "duration",
        "status": "PASS" if duration_ok else "FAIL",
        "detail": f"total={total_duration:.2f}s target={args.target_duration:.2f}s tolerance={args.duration_tolerance:.2f}s",
    })
    freeze_events = [e for v in video_reports for e in v.get("freeze", {}).get("events", [])]
    freeze_unavailable = [v["path"] for v in video_reports if not v.get("freeze", {}).get("available")]
    checks.append({
        "name": "freeze_detect",
        "status": "STOP" if freeze_unavailable else "PASS" if not freeze_events else "FAIL",
        "detail": f"events={len(freeze_events)} unavailable={freeze_unavailable}",
    })
    black_events = [e for v in video_reports for e in v.get("black", {}).get("events", [])]
    black_unavailable = [v["path"] for v in video_reports if not v.get("black", {}).get("available")]
    checks.append({
        "name": "black_detect",
        "status": "STOP" if black_unavailable else "PASS" if not black_events else "FAIL",
        "detail": f"events={len(black_events)} unavailable={black_unavailable}",
    })

    source_report = None
    if args.source_video:
        source_report = video_metrics(args.source_video)
        source_low_motion = skipped_detector("skipped: source video is missing, unreadable, or has no video stream")
        if source_report.get("readable") and source_report.get("video_streams", 0) > 0:
            source_low_motion = low_motion_detect(args.source_video)
        source_report["low_motion"] = source_low_motion

        generated_low_motion = []
        for video, metrics in zip(args.videos, video_reports):
            detector = skipped_detector("skipped: generated video is missing, unreadable, or has no video stream")
            if metrics.get("readable") and metrics.get("video_streams", 0) > 0:
                detector = low_motion_detect(video)
            metrics["low_motion"] = detector
            generated_low_motion.append(detector)

        detectors = [source_low_motion, *generated_low_motion]
        unavailable = [index for index, detector in enumerate(detectors) if not detector.get("available")]
        source_count = len(source_low_motion.get("events", []))
        generated_count = sum(len(detector.get("events", [])) for detector in generated_low_motion)
        allowed = source_count + args.max_extra_low_motion_holds
        checks.append({
            "name": "source_rhythm_low_motion",
            "status": "STOP" if unavailable else "PASS" if generated_count <= allowed else "FAIL",
            "detail": (
                f"source={source_count} generated={generated_count} "
                f"allowed_extra={args.max_extra_low_motion_holds} unavailable={unavailable}"
            ),
        })

    asr_text = load_text(args.asr_md)
    for term in args.brand_term:
        checks.append({
            "name": f"asr_contains:{term}",
            "status": "PASS" if term in asr_text else "FAIL",
            "detail": "term found in ASR text" if term in asr_text else "term missing from ASR text",
        })

    ok = contact_sheet.is_file()
    detail = str(contact_sheet) if ok else "contact sheet was not produced by the technical scan"
    checks.append({
        "name": "contact_sheet",
        "status": "PASS" if ok else "FAIL",
        "detail": detail,
    })

    status_order = {"PASS": 0, "FAIL": 1, "STOP": 2}
    overall = max((c["status"] for c in checks), key=lambda s: status_order[s])
    report = {
        "overall": overall,
        "target_duration": args.target_duration,
        "duration_tolerance": args.duration_tolerance,
        "checks": checks,
        "videos": video_reports,
        "source_video": source_report,
        "contact_sheet": str(contact_sheet) if contact_sheet.exists() else "",
    }

    out_json = args.out_dir / "final_qc.json"
    out_md = args.out_dir / "final_qc.md"
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_md(out_md, report)
    print(overall)
    print(out_md)


if __name__ == "__main__":
    main()
