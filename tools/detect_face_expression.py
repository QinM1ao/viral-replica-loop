#!/usr/bin/env python3
"""Extract a reusable, frame-accurate face-expression timeline from a video."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np


MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_landmarker/face_landmarker/float16/1/face_landmarker.task"
)
MODEL_SHA256 = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"


EYE_CONTOURS = {
    "left": (362, 385, 387, 263, 373, 380),
    "right": (33, 160, 158, 133, 153, 144),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--model")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--closed-threshold", type=float, default=0.50)
    parser.add_argument("--open-threshold", type=float, default=0.38)
    parser.add_argument("--closed-ear-max", type=float, default=0.10)
    parser.add_argument("--open-ear-min", type=float, default=0.12)
    parser.add_argument("--min-closed-frames", type=int, default=2)
    parser.add_argument("--write-annotated-video", action="store_true")
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def category_map(categories) -> dict[str, float]:
    return {item.category_name: float(item.score) for item in categories}


def eye_aspect_ratio(landmarks, indices: tuple[int, ...]) -> float:
    points = np.array(
        [[landmarks[index].x, landmarks[index].y] for index in indices],
        dtype=np.float64,
    )
    horizontal = np.linalg.norm(points[0] - points[3])
    if horizontal <= 1e-9:
        return 0.0
    vertical_1 = np.linalg.norm(points[1] - points[5])
    vertical_2 = np.linalg.norm(points[2] - points[4])
    return float((vertical_1 + vertical_2) / (2.0 * horizontal))


def median_smooth(values: list[float | None], radius: int = 1) -> list[float | None]:
    output: list[float | None] = []
    for index in range(len(values)):
        window = [
            value
            for value in values[max(0, index - radius) : index + radius + 1]
            if value is not None
        ]
        output.append(float(np.median(window)) if window else None)
    return output


def hysteresis_states(
    values: list[float | None],
    ear_values: list[float | None],
    closed_threshold: float,
    open_threshold: float,
    closed_ear_max: float,
    open_ear_min: float,
) -> list[str]:
    states: list[str] = []
    previous = "unknown"
    for value, ear in zip(values, ear_values):
        if value is None or ear is None:
            state = "unknown"
        elif value >= closed_threshold and ear <= closed_ear_max:
            state = "closed"
        elif value <= open_threshold or ear >= open_ear_min:
            state = "open"
        elif previous in {"closed", "open"}:
            state = previous
        else:
            state = "transition"
        states.append(state)
        previous = state
    return states


def combined_state(left: str, right: str) -> str:
    if left == "unknown" or right == "unknown":
        return "unknown"
    if left == "closed" and right == "closed":
        return "both_closed"
    if left == "open" and right == "open":
        return "both_open"
    if left == "closed" and right == "open":
        return "left_closed"
    if left == "open" and right == "closed":
        return "right_closed"
    return "transition"


def contiguous_runs(values: list[str]) -> list[tuple[int, int, str]]:
    if not values:
        return []
    runs: list[tuple[int, int, str]] = []
    start = 0
    for index in range(1, len(values)):
        if values[index] != values[start]:
            runs.append((start, index - 1, values[start]))
            start = index
    runs.append((start, len(values) - 1, values[start]))
    return runs


def closure_events(
    frames: list[dict], min_closed_frames: int
) -> list[dict]:
    events: list[dict] = []
    states = [frame["eye_state"] for frame in frames]
    runs = contiguous_runs(states)
    for run_index, (start, end, state) in enumerate(runs):
        if state != "both_closed" or end - start + 1 < min_closed_frames:
            continue
        before_open = any(
            item[2] == "both_open" for item in runs[max(0, run_index - 2) : run_index]
        )
        after_open = any(
            item[2] == "both_open"
            for item in runs[run_index + 1 : run_index + 3]
        )
        event_type = (
            "blink"
            if before_open and after_open
            else "initial_closed_then_open"
            if start == 0 and after_open
            else "closed_interval"
        )
        peak_index = max(
            range(start, end + 1),
            key=lambda index: (
                frames[index]["blink_left_smooth"]
                + frames[index]["blink_right_smooth"]
            ),
        )
        events.append(
            {
                "type": event_type,
                "start_frame": start,
                "peak_frame": peak_index,
                "end_frame": end,
                "start_seconds": frames[start]["time_seconds"],
                "peak_seconds": frames[peak_index]["time_seconds"],
                "end_seconds": frames[end]["time_seconds"],
                "peak_blink_left": frames[peak_index]["blink_left_smooth"],
                "peak_blink_right": frames[peak_index]["blink_right_smooth"],
            }
        )
    return events


def expression_summary(scores: dict[str, float]) -> dict[str, float]:
    return {
        "smile": (
            scores.get("mouthSmileLeft", 0.0) + scores.get("mouthSmileRight", 0.0)
        )
        / 2.0,
        "brow_raise": (
            scores.get("browOuterUpLeft", 0.0)
            + scores.get("browOuterUpRight", 0.0)
            + scores.get("browInnerUp", 0.0)
        )
        / 3.0,
        "brow_down": (
            scores.get("browDownLeft", 0.0) + scores.get("browDownRight", 0.0)
        )
        / 2.0,
        "jaw_open": scores.get("jawOpen", 0.0),
    }


def resolve_model(model_arg: str | None, out_dir: Path) -> tuple[Path, bool]:
    if model_arg:
        model = Path(model_arg).expanduser().resolve()
        if not model.is_file():
            raise FileNotFoundError(f"face landmarker model not found: {model}")
        return model, False
    model_dir = out_dir / ".model_cache"
    model_dir.mkdir(parents=True, exist_ok=True)
    model = model_dir / "face_landmarker.task"
    if not model.is_file() or file_sha256(model) != MODEL_SHA256:
        temporary = model.with_suffix(".download")
        urllib.request.urlretrieve(MODEL_URL, temporary)
        if file_sha256(temporary) != MODEL_SHA256:
            temporary.unlink(missing_ok=True)
            raise RuntimeError("downloaded face landmarker model checksum mismatch")
        temporary.replace(model)
    return model, True


def make_landmarker(model: Path):
    import mediapipe as mp
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision

    options = vision.FaceLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=str(model)),
        running_mode=vision.RunningMode.VIDEO,
        num_faces=1,
        output_face_blendshapes=True,
        output_facial_transformation_matrixes=True,
        min_face_detection_confidence=0.5,
        min_face_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    return vision.FaceLandmarker.create_from_options(options)


def collect_metrics(video: Path, model: Path) -> tuple[list[dict], dict]:
    import mediapipe as mp

    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise RuntimeError(f"cannot open video: {video}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frames: list[dict] = []
    started = time.perf_counter()
    with make_landmarker(model) as landmarker:
        frame_index = 0
        while True:
            ok, bgr = capture.read()
            if not ok:
                break
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            timestamp_ms = int(round(frame_index * 1000.0 / fps))
            result = landmarker.detect_for_video(image, timestamp_ms)
            row = {
                "frame": frame_index,
                "time_seconds": round(frame_index / fps, 6),
                "face_detected": bool(result.face_landmarks),
                "blink_left": None,
                "blink_right": None,
                "ear_left": None,
                "ear_right": None,
                "smile": None,
                "brow_raise": None,
                "brow_down": None,
                "jaw_open": None,
            }
            if result.face_landmarks and result.face_blendshapes:
                scores = category_map(result.face_blendshapes[0])
                row["blink_left"] = scores.get("eyeBlinkLeft")
                row["blink_right"] = scores.get("eyeBlinkRight")
                row["ear_left"] = eye_aspect_ratio(
                    result.face_landmarks[0], EYE_CONTOURS["left"]
                )
                row["ear_right"] = eye_aspect_ratio(
                    result.face_landmarks[0], EYE_CONTOURS["right"]
                )
                row.update(expression_summary(scores))
                row["_eye_points"] = {
                    side: [
                        [
                            int(result.face_landmarks[0][index].x * width),
                            int(result.face_landmarks[0][index].y * height),
                        ]
                        for index in indices
                    ]
                    for side, indices in EYE_CONTOURS.items()
                }
            frames.append(row)
            frame_index += 1
    capture.release()
    metadata = {
        "fps": fps,
        "width": width,
        "height": height,
        "frame_count": len(frames),
        "duration_seconds": len(frames) / fps,
        "processing_seconds": time.perf_counter() - started,
    }
    return frames, metadata


def classify_frames(
    frames: list[dict],
    closed_threshold: float,
    open_threshold: float,
    closed_ear_max: float,
    open_ear_min: float,
) -> None:
    for side in ("left", "right"):
        smooth = median_smooth([frame[f"blink_{side}"] for frame in frames])
        states = hysteresis_states(
            smooth,
            [frame[f"ear_{side}"] for frame in frames],
            closed_threshold,
            open_threshold,
            closed_ear_max,
            open_ear_min,
        )
        for frame, value, state in zip(frames, smooth, states):
            frame[f"blink_{side}_smooth"] = value
            frame[f"eye_{side}_state"] = state
    for frame in frames:
        frame["eye_state"] = combined_state(
            frame["eye_left_state"], frame["eye_right_state"]
        )


def write_csv(path: Path, frames: list[dict]) -> None:
    fields = [key for key in frames[0] if not key.startswith("_")]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(
            {
                key: "" if value is None else value
                for key, value in frame.items()
                if not key.startswith("_")
            }
            for frame in frames
        )


def write_plot(path: Path, frames: list[dict], events: list[dict]) -> None:
    import matplotlib.pyplot as plt

    times = [frame["time_seconds"] for frame in frames]
    left = [
        math.nan if frame["blink_left_smooth"] is None else frame["blink_left_smooth"]
        for frame in frames
    ]
    right = [
        math.nan
        if frame["blink_right_smooth"] is None
        else frame["blink_right_smooth"]
        for frame in frames
    ]
    figure, axis = plt.subplots(figsize=(12, 4))
    axis.plot(times, left, label="left eye closure", linewidth=1.5)
    axis.plot(times, right, label="right eye closure", linewidth=1.5)
    for event in events:
        axis.axvspan(
            event["start_seconds"],
            event["end_seconds"],
            alpha=0.18,
            color="red" if event["type"] == "blink" else "orange",
        )
    axis.set(xlabel="source seconds", ylabel="closure score", ylim=(0, 1))
    axis.grid(alpha=0.2)
    axis.legend(loc="upper right")
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)


def write_annotated_video(
    video: Path, path: Path, frames: list[dict], metadata: dict
) -> None:
    capture = cv2.VideoCapture(str(video))
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        metadata["fps"],
        (metadata["width"], metadata["height"]),
    )
    for row in frames:
        ok, image = capture.read()
        if not ok:
            break
        for points in row.get("_eye_points", {}).values():
            cv2.polylines(
                image, [np.array(points, dtype=np.int32)], True, (0, 255, 255), 2
            )
        lines = [
            f"{row['time_seconds']:.3f}s  {row['eye_state']}",
            f"L {row['blink_left_smooth'] or 0:.2f}  R {row['blink_right_smooth'] or 0:.2f}",
        ]
        for line_index, text in enumerate(lines):
            y = 42 + line_index * 34
            cv2.putText(
                image,
                text,
                (20, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.75,
                (0, 0, 0),
                4,
                cv2.LINE_AA,
            )
            cv2.putText(
                image,
                text,
                (20, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.75,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
        writer.write(image)
    capture.release()
    writer.release()


def write_contact_sheet(
    video: Path, path: Path, frames: list[dict], events: list[dict]
) -> None:
    chosen = {0, len(frames) - 1}
    chosen.update(event["peak_frame"] for event in events)
    runs = contiguous_runs([frame["eye_state"] for frame in frames])
    chosen.update(start for start, _, _ in runs)
    chosen.update(end for _, end, _ in runs)
    chosen = sorted(index for index in chosen if 0 <= index < len(frames))
    if len(chosen) > 24:
        chosen = chosen[:24]
    capture = cv2.VideoCapture(str(video))
    tiles = []
    for index in chosen:
        capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, image = capture.read()
        if not ok:
            continue
        scale = 300.0 / image.shape[0]
        tile = cv2.resize(image, None, fx=scale, fy=scale)
        label = f"{frames[index]['time_seconds']:.3f}s {frames[index]['eye_state']}"
        cv2.rectangle(tile, (0, 0), (tile.shape[1], 28), (0, 0, 0), -1)
        cv2.putText(
            tile,
            label,
            (4, 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        tiles.append(tile)
    capture.release()
    if not tiles:
        return
    columns = 6
    rows = math.ceil(len(tiles) / columns)
    tile_height, tile_width = tiles[0].shape[:2]
    canvas = np.full((rows * tile_height, columns * tile_width, 3), 245, np.uint8)
    for index, tile in enumerate(tiles):
        y = (index // columns) * tile_height
        x = (index % columns) * tile_width
        canvas[y : y + tile_height, x : x + tile_width] = tile
    cv2.imwrite(str(path), canvas)


def main() -> int:
    args = parse_args()
    video = Path(args.video).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    model, temporary_model = resolve_model(args.model, out_dir)
    frames, metadata = collect_metrics(video, model)
    if not frames:
        raise RuntimeError("video contained no readable frames")
    classify_frames(
        frames,
        args.closed_threshold,
        args.open_threshold,
        args.closed_ear_max,
        args.open_ear_min,
    )
    events = closure_events(frames, args.min_closed_frames)
    public_frames = [
        {key: value for key, value in frame.items() if not key.startswith("_")}
        for frame in frames
    ]
    timeline = {
        "schema_version": 1,
        "source_video": str(video),
        "source_sha256": file_sha256(video),
        "detector": {
            "name": "mediapipe_face_landmarker",
            "model_source": str(model) if args.model else MODEL_URL,
            "model_sha256": file_sha256(model),
            "closed_threshold": args.closed_threshold,
            "open_threshold": args.open_threshold,
            "closed_ear_max": args.closed_ear_max,
            "open_ear_min": args.open_ear_min,
            "min_closed_frames": args.min_closed_frames,
        },
        "video": metadata,
        "face_detection_coverage": sum(
            frame["face_detected"] for frame in frames
        )
        / len(frames),
        "eye_events": events,
        "state_intervals": [
            {
                "state": state,
                "start_frame": start,
                "end_frame": end,
                "start_seconds": frames[start]["time_seconds"],
                "end_seconds": frames[end]["time_seconds"],
            }
            for start, end, state in contiguous_runs(
                [frame["eye_state"] for frame in frames]
            )
        ],
        "frames": public_frames,
    }
    (out_dir / "face_expression_timeline.json").write_text(
        json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_csv(out_dir / "frame_metrics.csv", frames)
    write_plot(out_dir / "eye_closure_curve.png", frames, events)
    if args.write_annotated_video:
        write_annotated_video(
            video, out_dir / "face_expression_annotated.mp4", frames, metadata
        )
    write_contact_sheet(
        video, out_dir / "face_expression_contact_sheet.jpg", frames, events
    )
    if temporary_model:
        model.unlink(missing_ok=True)
        model.parent.rmdir()
    print(out_dir / "face_expression_timeline.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
