#!/usr/bin/env python3
"""Run face-expression detection in a stable project-local Python environment."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path


MEDIAPIPE_VERSION = "0.10.21"
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_landmarker/face_landmarker/float16/1/face_landmarker.task"
)
MODEL_SHA256 = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"
PROBE_CODE = (
    "import cv2,json,mediapipe,numpy;"
    "print(json.dumps({"
    "'mediapipe':mediapipe.__version__,"
    "'opencv':cv2.__version__,"
    "'numpy':numpy.__version__"
    "}))"
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_runtime(python: Path) -> dict | None:
    if not python.is_file():
        return None
    result = subprocess.run(
        [str(python), "-c", PROBE_CODE],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("mediapipe") != MEDIAPIPE_VERSION:
        return None
    return payload


def ensure_runtime(root: Path, bootstrap: bool = True) -> tuple[Path, dict]:
    root = root.resolve()
    runtime_python = root / ".venv-face-expression" / "bin" / "python"
    payload = probe_runtime(runtime_python)
    if payload is not None:
        return runtime_python, payload
    if not bootstrap:
        raise RuntimeError(
            "face-expression runtime is unavailable; run "
            f"{sys.executable} {Path(__file__).resolve()} --check"
        )

    requirements = root / "requirements.txt"
    if not requirements.is_file():
        raise RuntimeError(f"requirements file is missing: {requirements}")
    if not runtime_python.is_file():
        subprocess.run(
            [sys.executable, "-m", "venv", str(runtime_python.parents[1])],
            check=True,
        )
    subprocess.run(
        [
            str(runtime_python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-r",
            str(requirements),
        ],
        check=True,
    )
    payload = probe_runtime(runtime_python)
    if payload is None:
        raise RuntimeError(
            f"face-expression runtime failed dependency validation: {runtime_python}"
        )
    return runtime_python, payload


def ensure_model(root: Path, bootstrap: bool = True) -> Path:
    model = root.resolve() / ".cache" / "face-expression" / "face_landmarker.task"
    if model.is_file() and file_sha256(model) == MODEL_SHA256:
        return model
    if not bootstrap:
        raise RuntimeError(
            "face-expression model cache is unavailable; run "
            f"{sys.executable} {Path(__file__).resolve()} --prepare"
        )

    model.parent.mkdir(parents=True, exist_ok=True)
    download = model.with_suffix(".download")
    try:
        urllib.request.urlretrieve(MODEL_URL, download)
        if file_sha256(download) != MODEL_SHA256:
            raise RuntimeError("downloaded face-expression model hash is invalid")
        download.replace(model)
    finally:
        download.unlink(missing_ok=True)
    return model


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--no-bootstrap", action="store_true")
    args, detector_args = parser.parse_known_args()

    try:
        runtime_python, versions = ensure_runtime(
            args.runtime_root,
            bootstrap=not args.no_bootstrap,
        )
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Face-expression runtime error: {exc}", file=sys.stderr)
        return 2

    if args.check:
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "python": str(runtime_python),
                    **versions,
                },
                ensure_ascii=False,
            )
        )
        return 0

    try:
        model = ensure_model(
            args.runtime_root,
            bootstrap=not args.no_bootstrap,
        )
    except (OSError, RuntimeError) as exc:
        print(f"Face-expression model error: {exc}", file=sys.stderr)
        return 2

    if args.prepare:
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "python": str(runtime_python),
                    "model": str(model),
                    "model_sha256": MODEL_SHA256,
                    **versions,
                },
                ensure_ascii=False,
            )
        )
        return 0

    detector = Path(__file__).resolve().with_name("detect_face_expression.py")
    if not detector.is_file():
        print(f"Face-expression detector is missing: {detector}", file=sys.stderr)
        return 2
    os.execv(
        str(runtime_python),
        [
            str(runtime_python),
            str(detector),
            *(["--model", str(model)] if "--model" not in detector_args else []),
            *detector_args,
        ],
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
