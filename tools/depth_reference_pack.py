#!/usr/bin/env python3
"""Build a Part-bound pure-grayscale depth reference at a 720p long edge."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


LONG_EDGE = 1280
DEPTH_RENDERER = (
    Path(__file__).resolve().parents[1]
    / ".agents"
    / "skills"
    / "video-shot-refinement"
    / "scripts"
    / "render_depth_reference.py"
)


def probe_video(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=index,codec_type,width,height,r_frame_rate:format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def video_stream(probe: dict) -> dict:
    return next(
        stream
        for stream in probe.get("streams") or []
        if stream.get("codec_type") == "video"
    )


def even_dimension(value: float) -> int:
    rounded = max(2, int(round(value)))
    if rounded % 2:
        lower = rounded - 1
        upper = rounded + 1
        rounded = lower if abs(lower - value) <= abs(upper - value) else upper
    return rounded


def target_dimensions(
    width: int,
    height: int,
    long_edge: int = LONG_EDGE,
) -> tuple[int, int]:
    if min(width, height, long_edge) <= 0:
        raise ValueError("video dimensions and long edge must be positive")
    if width >= height:
        return long_edge, even_dimension(long_edge * height / width)
    return even_dimension(long_edge * width / height), long_edge


def build_depth_reference(
    source: Path,
    output: Path,
    *,
    source_start: float,
    source_end: float,
    target_duration: float,
    long_edge: int = LONG_EDGE,
    runner=subprocess.run,
) -> dict:
    if source_end <= source_start or target_duration <= 0:
        raise ValueError("depth source interval and target duration must be positive")
    source_probe = probe_video(source)
    stream = video_stream(source_probe)
    source_width = int(stream["width"])
    source_height = int(stream["height"])
    width, height = target_dimensions(source_width, source_height, long_edge)
    source_duration = source_end - source_start
    speed_factor = target_duration / source_duration
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="shotloom-depth-") as tmp:
        tmp_dir = Path(tmp)
        segment = tmp_dir / "source_interval_retimed.mp4"
        raw_depth = tmp_dir / "depth_raw.mp4"
        runner(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{source_start:.6f}",
                "-t",
                f"{source_duration:.6f}",
                "-i",
                str(source),
                "-vf",
                f"setpts={speed_factor:.12f}*PTS",
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(segment),
            ],
            check=True,
        )
        runner(
            [
                sys.executable,
                str(DEPTH_RENDERER),
                str(segment),
                str(raw_depth),
                "--width",
                str(width),
                "--height",
                str(height),
            ],
            check=True,
        )
        runner(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(raw_depth),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-an",
                str(output),
            ],
            check=True,
        )

    result_probe = probe_video(output)
    result_stream = video_stream(result_probe)
    result_width = int(result_stream["width"])
    result_height = int(result_stream["height"])
    audio_streams = sum(
        stream.get("codec_type") == "audio"
        for stream in result_probe.get("streams") or []
    )
    result_duration = float(result_probe.get("format", {}).get("duration") or 0)
    source_ratio = source_width / source_height
    result_ratio = result_width / result_height
    if max(result_width, result_height) != long_edge:
        raise RuntimeError(f"depth reference long edge is not {long_edge} pixels")
    if abs(result_ratio - source_ratio) / source_ratio > 0.005:
        raise RuntimeError("depth reference aspect ratio differs from the source")
    if audio_streams:
        raise RuntimeError("depth reference must not contain audio")
    if abs(result_duration - target_duration) > 0.10:
        raise RuntimeError("depth reference duration differs from the target Part")
    return {
        "source": str(source),
        "source_sha256": file_sha256(source),
        "source_interval": [source_start, source_end],
        "source_dimensions": [source_width, source_height],
        "output": str(output),
        "output_sha256": file_sha256(output),
        "output_dimensions": [result_width, result_height],
        "long_edge": long_edge,
        "duration_seconds": result_duration,
        "audio_streams": audio_streams,
        "generation_chain": (
            "original_source_interval_to_depth; no smaller depth intermediate"
        ),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-start", type=float, required=True)
    parser.add_argument("--source-end", type=float, required=True)
    parser.add_argument("--target-duration", type=float, required=True)
    parser.add_argument("--long-edge", type=int, default=LONG_EDGE)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args(argv)
    report = build_depth_reference(
        args.source.expanduser().resolve(),
        args.output.expanduser().resolve(),
        source_start=args.source_start,
        source_end=args.source_end,
        target_duration=args.target_duration,
        long_edge=args.long_edge,
    )
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(
            json.dumps(
                {"overall": "PASS", **report},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
