#!/usr/bin/env python3
import argparse
import json
import math
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


PAD = 12
GAP = 8
TITLE_H = 36
LABEL_H = 30


def run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "command failed")
    return result.stdout


def probe_video(path):
    data = json.loads(run([
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]))
    stream = next((s for s in data["streams"] if s.get("codec_type") == "video"), None)
    if not stream:
        raise RuntimeError(f"no video stream found: {path}")
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "duration": float(data["format"]["duration"]),
    }


def font():
    for candidate in [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
    ]:
        if Path(candidate).exists():
            return candidate
    return None


def thumb_size(source_w, source_h, long_edge):
    aspect = source_w / source_h
    if aspect >= 1:
        return long_edge, max(1, round(long_edge / aspect))
    return max(1, round(long_edge * aspect)), long_edge


def extract_frames(video_path, total_frames, tmp_dir):
    info = probe_video(video_path)
    fps = total_frames / info["duration"]
    frame_pattern = tmp_dir / "f_%04d.jpg"
    run([
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vf",
        f"fps={fps:.6f}",
        "-frames:v",
        str(total_frames),
        "-q:v",
        "2",
        str(frame_pattern),
    ])
    return sorted(tmp_dir.glob("f_*.jpg"))


def parse_storyboard_exclusion_ranges(rhythm, duration):
    exclusions = []
    for item in rhythm.get("storyboard_exclusion_ranges") or []:
        if not isinstance(item, dict):
            raise RuntimeError("storyboard exclusion range must be an object")
        start = item.get("start")
        end = item.get("end")
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, (int, float))
            or not isinstance(end, (int, float))
            or not 0 <= float(start) < float(end) <= duration
        ):
            raise RuntimeError(f"invalid storyboard exclusion range: {item}")
        exclusions.append(
            {
                **item,
                "start": round(float(start), 3),
                "end": round(float(end), 3),
            }
        )
    return exclusions


def time_is_excluded(value, exclusions):
    return any(item["start"] <= value <= item["end"] for item in exclusions)


def rhythm_frame_selections(rhythm_path, duration, total_frames, groups):
    rhythm = json.loads(rhythm_path.read_text(encoding="utf-8"))
    beats = rhythm.get("beats") or []
    if not beats:
        raise RuntimeError("source rhythm has no authored beats")
    exclusions = parse_storyboard_exclusion_ranges(rhythm, duration)
    per_group = math.ceil(total_frames / groups)
    required_by_group = [[] for _ in range(groups)]
    secondary_peaks_by_group = [[] for _ in range(groups)]
    for beat in beats:
        if beat.get("replication_priority") not in {"must_keep", "mergeable"}:
            continue
        beat_start = beat.get("source_start")
        beat_end = beat.get("source_end")
        if not isinstance(beat_start, (int, float)) or not isinstance(
            beat_end, (int, float)
        ):
            continue
        all_peaks = [
            float(value)
            for value in beat.get("action_peak_times") or []
            if isinstance(value, (int, float)) and 0 <= float(value) < duration
        ]
        peaks = [value for value in all_peaks if not time_is_excluded(value, exclusions)]
        if all_peaks and not peaks:
            raise RuntimeError(
                f"required beat {beat.get('id') or '<missing-id>'} has only excluded action peaks"
            )
        selected_time = peaks[0] if peaks else (float(beat_start) + float(beat_end)) / 2
        if time_is_excluded(selected_time, exclusions):
            raise RuntimeError(
                f"required beat {beat.get('id') or '<missing-id>'} selects an excluded frame"
            )
        group_index = min(int(selected_time / duration * groups), groups - 1)
        required_by_group[group_index].append(
            {
                "time": round(selected_time, 3),
                "source_beat_ids": [str(beat.get("id") or "")],
                "selection_reason": "action_peak" if peaks else "beat_midpoint",
            }
        )
        for peak in peaks[1:]:
            secondary_group_index = min(int(peak / duration * groups), groups - 1)
            secondary_peaks_by_group[secondary_group_index].append(
                {
                    "time": round(peak, 3),
                    "source_beat_ids": [],
                    "selection_reason": "secondary_action_peak",
                }
            )
    selections = []
    for group in range(groups):
        group_start = duration * group / groups
        group_end = duration * (group + 1) / groups
        group_budget = min(per_group, total_frames - group * per_group)
        required = required_by_group[group]
        if len(required) > group_budget:
            raise RuntimeError(
                f"Part {group + 1} has {len(required)} required rhythm beats but only "
                f"{group_budget} storyboard frames"
            )
        selected = list(required)
        for secondary in secondary_peaks_by_group[group]:
            if len(selected) >= group_budget:
                break
            if any(abs(secondary["time"] - item["time"]) < 0.04 for item in selected):
                continue
            selected.append(secondary)
        candidate_count = max(group_budget * 8, 1)
        candidates = [
            group_start
            + (index + 0.5) * ((group_end - group_start) / candidate_count)
            for index in range(candidate_count)
            if not time_is_excluded(
                group_start
                + (index + 0.5) * ((group_end - group_start) / candidate_count),
                exclusions,
            )
        ]
        while len(selected) < group_budget:
            viable = [
                candidate
                for candidate in candidates
                if not any(abs(candidate - item["time"]) < 0.04 for item in selected)
            ]
            if not viable:
                break
            if selected:
                candidate = max(
                    viable,
                    key=lambda value: min(
                        abs(value - item["time"]) for item in selected
                    ),
                )
            else:
                midpoint = (group_start + group_end) / 2
                candidate = min(viable, key=lambda value: abs(value - midpoint))
            selected.append(
                {
                    "time": round(candidate, 3),
                    "source_beat_ids": [],
                    "selection_reason": "coverage_fill",
                }
            )
        if len(selected) != group_budget:
            raise RuntimeError(f"could not fill Part {group + 1} storyboard frame budget")
        selections.append(sorted(selected, key=lambda item: item["time"]))
    return selections, exclusions


def extract_frames_at_times(video_path, selected_frames, tmp_dir):
    frames = []
    for index, item in enumerate(selected_frames, start=1):
        frame_path = tmp_dir / f"f_{index:04d}.jpg"
        run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-ss",
                f"{item['time']:.3f}",
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(frame_path),
            ]
        )
        frames.append(frame_path)
    return frames


def build_grid(frame_paths, out_path, title, source_w, source_h, cols, long_edge, part_index):
    thumb_w, thumb_h = thumb_size(source_w, source_h, long_edge)
    rows = math.ceil(len(frame_paths) / cols)
    padded = list(frame_paths)
    while len(padded) < rows * cols:
        padded.append(frame_paths[-1])

    grid_w = PAD * 2 + cols * thumb_w + (cols - 1) * GAP
    grid_h = TITLE_H + PAD * 2 + rows * (thumb_h + LABEL_H) + (rows - 1) * GAP
    canvas = Image.new("RGB", (grid_w, grid_h), (24, 24, 24))
    draw = ImageDraw.Draw(canvas)

    font_path = font()
    if font_path:
        title_font = ImageFont.truetype(font_path, 17)
        label_font = ImageFont.truetype(font_path, 14)
    else:
        title_font = label_font = ImageFont.load_default()

    draw.text((PAD, 9), title, fill=(255, 255, 255), font=title_font)

    for idx, frame in enumerate(padded):
        row, col = divmod(idx, cols)
        x = PAD + col * (thumb_w + GAP)
        y = TITLE_H + PAD + row * (thumb_h + LABEL_H + GAP)
        img = Image.open(frame).convert("RGB").resize((thumb_w, thumb_h), Image.LANCZOS)
        canvas.paste(img, (x, y))
        label_y = y + thumb_h
        is_padding = idx >= len(frame_paths)
        draw.rectangle([x, label_y, x + thumb_w, label_y + LABEL_H], fill=(38, 38, 38))
        label = f"Shot {idx + 1:02d}" if not is_padding else f"Repeat {len(frame_paths):02d}"
        color = (0, 190, 255) if not is_padding else (150, 150, 150)
        draw.text((x + 8, label_y + 7), label, fill=color, font=label_font)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, quality=92)
    return {
        "part": part_index,
        "path": str(out_path),
        "size": [grid_w, grid_h],
        "ratio": grid_w / grid_h,
        "grid_cols": cols,
        "grid_rows": rows,
        "frame_count": len(frame_paths),
        "thumb_size": [thumb_w, thumb_h],
        "preserves_source_frame_aspect": True,
    }


def main():
    parser = argparse.ArgumentParser(description="Build Part storyboard refs without changing source frame aspect.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--total-frames", type=int, default=24)
    parser.add_argument("--groups", type=int, default=2)
    parser.add_argument(
        "--cols",
        type=int,
        default=0,
        help="Storyboard columns. Defaults to 3 for landscape sources and 4 for portrait sources.",
    )
    parser.add_argument("--thumb-long-edge", type=int, default=360)
    parser.add_argument(
        "--source-rhythm",
        type=Path,
        help="Authored source_rhythm.json. When present, select must-keep action peaks before coverage frames.",
    )
    args = parser.parse_args()

    info = probe_video(args.input)
    source_orientation = "landscape" if info["width"] > info["height"] else "portrait"
    cols = args.cols or (3 if source_orientation == "landscape" else 4)
    args.output.mkdir(parents=True, exist_ok=True)
    parts = []

    selection_mode = "source_rhythm" if args.source_rhythm else "uniform"
    rhythm_selections = None
    storyboard_exclusions = []
    if args.source_rhythm:
        rhythm_selections, storyboard_exclusions = rhythm_frame_selections(
            args.source_rhythm,
            info["duration"],
            args.total_frames,
            args.groups,
        )

    with tempfile.TemporaryDirectory(prefix="frames_", dir=args.output) as tmp:
        tmp_root = Path(tmp)
        if rhythm_selections is None:
            frames = extract_frames(args.input, args.total_frames, tmp_root)
            if not frames:
                raise RuntimeError("no frames extracted")
            per_group = math.ceil(len(frames) / args.groups)
            interval = info["duration"] / len(frames)
        for group in range(args.groups):
            if rhythm_selections is None:
                start = group * per_group
                end = min(start + per_group, len(frames))
                group_frames = frames[start:end]
                time_start = start * interval
                time_end = end * interval
                selected_frames = []
            else:
                selected_frames = rhythm_selections[group]
                group_tmp = tmp_root / f"part_{group + 1}"
                group_tmp.mkdir()
                group_frames = extract_frames_at_times(
                    args.input,
                    selected_frames,
                    group_tmp,
                )
                time_start = info["duration"] * group / args.groups
                time_end = info["duration"] * (group + 1) / args.groups
            if not group_frames:
                continue
            part = group + 1
            out_path = args.output / f"source_storyboard_part{part}.jpg"
            title = f"Part {part} | {time_start:.1f}-{time_end:.1f}s | source {info['width']}x{info['height']}"
            part_manifest = build_grid(
                group_frames,
                out_path,
                title,
                info["width"],
                info["height"],
                cols,
                args.thumb_long_edge,
                part,
            )
            if selected_frames:
                part_manifest["selected_frames"] = selected_frames
            parts.append(part_manifest)

            frame_dir = args.output / f"source_frames_part{part}"
            frame_dir.mkdir(exist_ok=True)
            for idx, src in enumerate(group_frames, start=1):
                img = Image.open(src).convert("RGB")
                img.save(frame_dir / f"frame_{idx:02d}.jpg", quality=92)

    manifest = {
        "video": str(args.input),
        "source_width": info["width"],
        "source_height": info["height"],
        "source_aspect_ratio": info["width"] / info["height"],
        "source_orientation": source_orientation,
        "duration": info["duration"],
        "total_frames": args.total_frames,
        "groups": args.groups,
        "grid_cols": cols,
        "grid_rule": "landscape_3x4_portrait_4x3_default" if args.cols == 0 else "explicit_cols",
        "preserve_source_frame_aspect": True,
        "selection_mode": selection_mode,
        "parts": parts,
    }
    if storyboard_exclusions:
        manifest["storyboard_exclusion_ranges"] = storyboard_exclusions
    (args.output / "source_storyboard_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
