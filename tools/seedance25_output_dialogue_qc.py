#!/usr/bin/env python3
"""Compare generated-video ASR with the transcript locked at Seedance 2.5 preflight."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


def normalize(text: str) -> str:
    return re.sub(r"[\s，。！？、；：,.!?;:'\"“”‘’（）()\-—…]", "", text or "")


def timeline_text(timeline: dict) -> str:
    return "".join(
        str(item.get("text") or "")
        for item in timeline.get("words") or []
        if isinstance(item, dict) and item.get("type") in {None, "word"}
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-fidelity-qc", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--asr-request-manifest", type=Path, required=True)
    parser.add_argument("--asr-timeline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    fidelity = json.loads(args.source_fidelity_qc.read_text(encoding="utf-8"))
    asr_manifest = json.loads(args.asr_request_manifest.read_text(encoding="utf-8"))
    timeline = json.loads(args.asr_timeline.read_text(encoding="utf-8"))
    expected = normalize(str(fidelity.get("expected_transcript") or ""))
    actual = normalize(timeline_text(timeline))
    exact = bool(expected) and actual == expected
    ending = bool(expected) and actual.endswith(expected[-min(20, len(expected)) :])
    video_hash = hashlib.sha256(args.video.read_bytes()).hexdigest()
    asr_bound = asr_manifest.get("source_sha256") == video_hash
    report = {
        "schema_version": 1,
        "overall": "PASS" if exact and ending and asr_bound else "FAIL",
        "source_fidelity_qc": str(args.source_fidelity_qc.resolve()),
        "source_fidelity_qc_sha256": hashlib.sha256(args.source_fidelity_qc.read_bytes()).hexdigest(),
        "asr_timeline": str(args.asr_timeline.resolve()),
        "asr_timeline_sha256": hashlib.sha256(args.asr_timeline.read_bytes()).hexdigest(),
        "video": str(args.video.resolve()),
        "video_sha256": video_hash,
        "asr_request_manifest": str(args.asr_request_manifest.resolve()),
        "asr_request_manifest_sha256": hashlib.sha256(args.asr_request_manifest.read_bytes()).hexdigest(),
        "expected_transcript": expected,
        "actual_transcript": actual,
        "checks": [
            {
                "name": "asr_binds_generated_video",
                "status": "PASS" if asr_bound else "FAIL",
                "detail": f"video={video_hash}, asr_source={asr_manifest.get('source_sha256')!r}",
            },
            {
                "name": "generated_dialogue_exact",
                "status": "PASS" if exact else "FAIL",
                "detail": f"expected_chars={len(expected)}, actual_chars={len(actual)}",
            },
            {
                "name": "generated_dialogue_ending_complete",
                "status": "PASS" if ending else "FAIL",
                "detail": f"expected_ending={expected[-20:]!r}, actual_ending={actual[-20:]!r}",
            },
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Seedance 2.5 output dialogue {report['overall']}: {args.output}")
    return 0 if report["overall"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
