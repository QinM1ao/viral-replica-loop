#!/usr/bin/env python3

import argparse
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image
from transformers import pipeline


def choose_device(requested: str):
    if requested != "auto":
        return requested
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return 0
    return -1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render a silent grayscale depth reference while preserving source timing."
    )
    parser.add_argument("input_video")
    parser.add_argument("output_video")
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument(
        "--model",
        default="depth-anything/Depth-Anything-V2-Small-hf",
    )
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()

    if (args.width is None) != (args.height is None):
        parser.error("--width and --height must be supplied together")

    capture = cv2.VideoCapture(args.input_video)
    if not capture.isOpened():
        raise SystemExit(f"Cannot open input video: {args.input_video}")

    source_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    source_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    width = args.width or source_width
    height = args.height or source_height
    if min(source_width, source_height, width, height) <= 0:
        raise SystemExit("Input and output dimensions must be positive")
    if abs(source_width / source_height - width / height) > 0.001:
        raise SystemExit("Output dimensions must preserve the source aspect ratio")

    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    Path(args.output_video).parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        args.output_video,
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        raise SystemExit(f"Cannot open output video: {args.output_video}")

    depth_pipe = pipeline(
        "depth-estimation",
        model=args.model,
        device=choose_device(args.device),
    )

    index = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if (width, height) != (source_width, source_height):
                frame = cv2.resize(
                    frame,
                    (width, height),
                    interpolation=cv2.INTER_AREA,
                )
            image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            depth = np.asarray(depth_pipe(image)["depth"])
            if depth.dtype != np.uint8:
                minimum = float(depth.min())
                maximum = float(depth.max())
                scale = maximum - minimum
                depth = (
                    np.zeros_like(depth, dtype=np.uint8)
                    if scale <= 0
                    else ((depth - minimum) * 255.0 / scale).astype(np.uint8)
                )
            depth = cv2.resize(
                depth,
                (width, height),
                interpolation=cv2.INTER_LINEAR,
            )
            writer.write(cv2.cvtColor(depth, cv2.COLOR_GRAY2BGR))
            index += 1
            if index % 15 == 0 or index == total:
                print(f"depth {index}/{total}", flush=True)
    finally:
        capture.release()
        writer.release()

    if index == 0:
        raise SystemExit("Input video contained no decodable frames")


if __name__ == "__main__":
    main()
