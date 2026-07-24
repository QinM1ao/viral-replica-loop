#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path


def repo_root():
    return Path(__file__).resolve().parents[4]


def main():
    parser = argparse.ArgumentParser(description="Prepare source-video reference materials for viral replica loop jobs.")
    parser.add_argument("--video", required=True, help="Source video path.")
    parser.add_argument("--out-dir", required=True, help="Output directory.")
    parser.add_argument("--run-asr", action="store_true", help="Run local ASR through the root preparation script.")
    args = parser.parse_args()

    root = repo_root()
    script = root / "tools" / "prepare_story_analysis.py"
    cmd = [
        sys.executable,
        str(script),
        "--video",
        args.video,
        "--out-dir",
        args.out_dir,
    ]
    if args.run_asr:
        cmd.append("--run-asr")

    raise SystemExit(subprocess.call(cmd, cwd=root))


if __name__ == "__main__":
    main()
