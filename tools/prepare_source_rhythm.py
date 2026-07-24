#!/usr/bin/env python3
import argparse
import array
import json
import math
import re
import shutil
import subprocess
from pathlib import Path


def run(command):
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "command failed")
    return result.stdout, result.stderr


def probe_video(video):
    stdout, _stderr = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(video),
        ]
    )
    payload = json.loads(stdout)
    video_stream = next(
        stream for stream in payload.get("streams", []) if stream.get("codec_type") == "video"
    )
    return {
        "duration": float(payload["format"]["duration"]),
        "width": int(video_stream["width"]),
        "height": int(video_stream["height"]),
    }


def detect_cuts(video, threshold):
    _stdout, stderr = run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(video),
            "-vf",
            f"select='gt(scene,{threshold})',metadata=print",
            "-an",
            "-f",
            "null",
            "-",
        ]
    )
    times = re.findall(r"pts_time:([0-9.]+)", stderr)
    scores = re.findall(r"lavfi\.scene_score=([0-9.]+)", stderr)
    return [
        {"time": round(float(time), 3), "score": round(float(score), 6)}
        for time, score in zip(times, scores)
    ]


def measure_audio_energy(video, duration, window_seconds=0.25, sample_rate=16000):
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-f",
            "s16le",
            "-",
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout:
        return {
            "method": "pcm_rms",
            "window_seconds": window_seconds,
            "available": False,
            "samples": [],
        }
    pcm = array.array("h")
    pcm.frombytes(result.stdout)
    window_size = max(1, round(sample_rate * window_seconds))
    rms_values = []
    for offset in range(0, len(pcm), window_size):
        window = pcm[offset : offset + window_size]
        if not window:
            continue
        rms_values.append(math.sqrt(sum(sample * sample for sample in window) / len(window)))
    peak = max(rms_values, default=0.0)
    samples = []
    for index, rms in enumerate(rms_values):
        start = index * window_seconds
        samples.append(
            {
                "start": round(start, 3),
                "end": round(min(duration, start + window_seconds), 3),
                "normalized_rms": round(rms / peak, 4) if peak else 0.0,
            }
        )
    return {
        "method": "pcm_rms",
        "window_seconds": window_seconds,
        "available": True,
        "samples": samples,
    }


def extract_evidence_frames(video, output_dir, fps, width, height):
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    scale = "320:-2" if width >= height else "-2:320"
    run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-vf",
            f"fps={fps},scale={scale}",
            "-q:v",
            "3",
            str(output_dir / "frame_%04d.jpg"),
        ]
    )
    return [
        {"time": round(index / fps, 3), "path": str(path)}
        for index, path in enumerate(sorted(output_dir.glob("frame_*.jpg")))
    ]


def prepare(video, threshold, evidence_dir, evidence_fps):
    info = probe_video(video)
    return {
        "schema_version": 3,
        "source_video": str(video),
        "duration": info["duration"],
        "frame_size": [info["width"], info["height"]],
        "cut_detection": {
            "method": "ffmpeg_scene_score",
            "threshold": threshold,
        },
        "actual_cut_points": detect_cuts(video, threshold),
        "audio_energy": measure_audio_energy(video, info["duration"]),
        "evidence_fps": evidence_fps,
        "evidence_frames": extract_evidence_frames(
            video,
            evidence_dir,
            evidence_fps,
            info["width"],
            info["height"],
        ),
        "source_evidence": {
            "asr_text": "",
            "subtitle_observations": [],
        },
        "beats": [],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scene-threshold", type=float, default=0.18)
    parser.add_argument("--evidence-fps", type=float, default=5.0)
    args = parser.parse_args()

    video = args.video.expanduser().resolve()
    if not video.is_file():
        raise FileNotFoundError(f"source video not found: {video}")
    output = args.output.expanduser().resolve()
    evidence_dir = output.parent / "source_rhythm_evidence"
    payload = prepare(video, args.scene_threshold, evidence_dir, args.evidence_fps)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
