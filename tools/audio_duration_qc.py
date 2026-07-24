#!/usr/bin/env python3
import argparse
import json
import subprocess
from pathlib import Path

from qc_input_binding import attach_input_binding


def duration(path):
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nk=1:nw=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None, result.stderr.strip() or "ffprobe failed"
    try:
        return float(result.stdout.strip()), ""
    except ValueError:
        return None, f"invalid duration: {result.stdout.strip()}"


def write_md(path, report):
    lines = [
        "# Audio Duration QC",
        "",
        f"- Overall: **{report['overall']}**",
        f"- Limit: `{report['limit_seconds']:.3f}s`",
        "",
        "## Files",
        "",
    ]
    for item in report["files"]:
        dur = item.get("duration_seconds")
        dur_text = "unknown" if dur is None else f"{dur:.6f}s"
        lines.append(f"- {item['status']}: `{item['path']}` - {dur_text} - {item['detail']}")
    lines.append("")
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Check audio files against a strict duration limit.")
    parser.add_argument("--audio", nargs="+", type=Path, required=True)
    parser.add_argument("--max-seconds", type=float, default=15.0)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    args = parser.parse_args()

    files = []
    for audio_path in args.audio:
        dur, error = duration(audio_path)
        if dur is None:
            status = "STOP"
            detail = error
        elif dur <= args.max_seconds:
            status = "PASS"
            detail = "within strict upload limit"
        else:
            status = "FAIL"
            detail = "exceeds strict upload limit"
        files.append({
            "path": str(audio_path),
            "duration_seconds": dur,
            "status": status,
            "detail": detail,
        })

    status_order = {"PASS": 0, "FAIL": 1, "STOP": 2}
    overall = max((item["status"] for item in files), key=lambda s: status_order[s])
    report = {
        "overall": overall,
        "limit_seconds": args.max_seconds,
        "files": files,
    }
    attach_input_binding(report, Path.cwd(), args.audio)

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_md(args.out_md, report)
    print(overall)


if __name__ == "__main__":
    main()
