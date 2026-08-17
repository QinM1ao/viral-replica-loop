#!/usr/bin/env python3

import argparse
import json
import subprocess
from pathlib import Path


def probe(path: Path) -> dict:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type,width,height,r_frame_rate",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    data = json.loads(result.stdout)
    video = next(
        (stream for stream in data["streams"] if stream["codec_type"] == "video"),
        None,
    )
    if video is None:
        raise SystemExit(f"No video stream: {path}")
    numerator, denominator = video["r_frame_rate"].split("/", 1)
    return {
        "duration": float(data["format"]["duration"]),
        "width": int(video["width"]),
        "height": int(video["height"]),
        "fps": float(numerator) / float(denominator),
        "has_audio": any(
            stream["codec_type"] == "audio" for stream in data["streams"]
        ),
    }


def number(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replace one visual interval while preserving the master audio track."
    )
    parser.add_argument("--master", required=True)
    parser.add_argument("--patch", required=True)
    parser.add_argument("--start", required=True, type=float)
    parser.add_argument("--end", required=True, type=float)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    master = Path(args.master).resolve()
    patch = Path(args.patch).resolve()
    output = Path(args.output).resolve()
    if output in {master, patch}:
        raise SystemExit("Output must be a new file")
    if not master.is_file() or not patch.is_file():
        raise SystemExit("Master and patch must both exist")

    master_info = probe(master)
    patch_info = probe(patch)
    if not 0 <= args.start < args.end <= master_info["duration"] + 0.02:
        raise SystemExit("Replacement range must fit inside the master")
    master_ratio = master_info["width"] / master_info["height"]
    patch_ratio = patch_info["width"] / patch_info["height"]
    if abs(master_ratio - patch_ratio) > 0.001:
        raise SystemExit("Patch aspect ratio must match the master")

    slot_duration = args.end - args.start
    speed = patch_info["duration"] / slot_duration
    if not 0.5 <= speed <= 2.0:
        raise SystemExit(
            f"Required uniform speed {speed:.3f}x is outside the safe 0.5x–2.0x range"
        )

    width = master_info["width"]
    height = master_info["height"]
    fps = master_info["fps"] or 25.0
    chains = []
    labels = []

    if args.start > 0.001:
        chains.append(
            f"[0:v]trim=start=0:end={number(args.start)},"
            f"setpts=PTS-STARTPTS,scale={width}:{height},setsar=1,"
            f"fps={number(fps)},format=yuv420p[v0]"
        )
        labels.append("[v0]")

    patch_label = f"v{len(labels)}"
    chains.append(
        f"[1:v]trim=start=0:end={number(patch_info['duration'])},"
        f"setpts=(PTS-STARTPTS)/{number(speed)},"
        f"scale={width}:{height},setsar=1,"
        f"fps={number(fps)},format=yuv420p[{patch_label}]"
    )
    labels.append(f"[{patch_label}]")

    if args.end < master_info["duration"] - 0.001:
        tail_label = f"v{len(labels)}"
        chains.append(
            f"[0:v]trim=start={number(args.end)}:end={number(master_info['duration'])},"
            f"setpts=PTS-STARTPTS,scale={width}:{height},setsar=1,"
            f"fps={number(fps)},format=yuv420p[{tail_label}]"
        )
        labels.append(f"[{tail_label}]")

    if len(labels) == 1:
        chains.append(f"{labels[0]}null[vout]")
    else:
        chains.append(
            "".join(labels) + f"concat=n={len(labels)}:v=1:a=0[vout]"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(master),
        "-i",
        str(patch),
        "-filter_complex",
        ";".join(chains),
        "-map",
        "[vout]",
    ]
    if master_info["has_audio"]:
        command.extend(["-map", "0:a:0", "-c:a", "copy"])
    else:
        command.append("-an")
    command.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-t",
            number(master_info["duration"]),
            str(output),
        ]
    )
    subprocess.run(command, check=True)

    output_info = probe(output)
    if abs(output_info["duration"] - master_info["duration"]) > 0.12:
        raise SystemExit("Rendered output duration does not match the master")
    if master_info["has_audio"] and not output_info["has_audio"]:
        raise SystemExit("Rendered output lost the master audio")

    print(
        json.dumps(
            {
                "output": str(output),
                "replacement_start": args.start,
                "replacement_end": args.end,
                "visual_speed": speed,
                "master_duration": master_info["duration"],
                "output_duration": output_info["duration"],
                "master_audio_preserved": master_info["has_audio"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
