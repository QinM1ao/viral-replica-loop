#!/usr/bin/env python3
"""Build a Seedance 2.5 taskCode 2509 request with explicit audio and depth modes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from seedance_request_contract import (
    SEEDANCE25_MODEL,
    SEEDANCE25_TASK_CODE,
    build_taskcode_request,
    inspect_taskcode_request,
)


ALLOWED_AUDIO_MODES = {"generated_voiceover", "original_master_postmix"}
DEFAULT_ROUTE = Path(__file__).resolve().parents[1] / "rules" / "SEEDANCE_25_MODEL.json"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_source_fidelity_qc(path: Path, prompt: str, audio_mode: str) -> dict:
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("overall") != "PASS":
        raise ValueError(f"Source fidelity QC is not PASS: {path}")
    expected_prompt_hash = hashlib.sha256(prompt.strip().encode("utf-8")).hexdigest()
    if report.get("prompt_sha256") != expected_prompt_hash:
        raise ValueError("Source fidelity QC is stale for the current prompt")
    if report.get("audio_mode") != audio_mode:
        raise ValueError(
            f"Audio mode differs from source fidelity QC: request={audio_mode!r}, "
            f"qc={report.get('audio_mode')!r}"
        )
    if not report.get("expected_transcript"):
        raise ValueError("Source fidelity QC has no expected transcript")
    return report


def load_active_assets(path: Path) -> list[dict]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("overall") != "PASS":
        raise ValueError(f"Pixmax report is not PASS: {path}")
    items = report.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("Pixmax report has no items")
    normalized = []
    for item in items:
        if not isinstance(item, dict) or item.get("status") != "Active":
            raise ValueError("Every Pixmax item must have status=Active")
        asset_type = item.get("asset_type") or "Image"
        if asset_type not in {"Image", "Video"}:
            raise ValueError(f"Unsupported Pixmax asset type: {asset_type!r}")
        asset_ref = item.get("asset_ref")
        if not isinstance(asset_ref, str) or not asset_ref.startswith("asset://asset-"):
            raise ValueError(f"Invalid Active asset ref: {asset_ref!r}")
        normalized.append({**item, "asset_type": asset_type})
    video_count = sum(item["asset_type"] == "Video" for item in normalized)
    if video_count > 1:
        raise ValueError(f"Seedance 2.5 route accepts at most one depth video, found {video_count}")
    if video_count == 1:
        first_video = next(index for index, item in enumerate(normalized) if item["asset_type"] == "Video")
        if any(item["asset_type"] == "Image" for item in normalized[first_video + 1:]):
            raise ValueError("Pixmax report order must be images first, then optional depth video")
    return normalized


def build_seedance25_request(
    *,
    prompt: str,
    assets: list[dict],
    duration: int,
    audio_mode: str,
    audio_url: str = "",
    ratio: str = "9:16",
    resolution: str = "720p",
    source_fidelity_qc: dict | None = None,
    source_fidelity_qc_sha256: str = "",
) -> tuple[dict, dict, dict]:
    if audio_mode not in ALLOWED_AUDIO_MODES:
        raise ValueError(f"Unsupported audio mode: {audio_mode!r}")
    if audio_mode == "original_master_postmix" and audio_url:
        raise ValueError("original_master_postmix excludes reference audio from the provider request")
    video_assets = [item for item in assets if item["asset_type"] == "Video"]
    if source_fidelity_qc is not None:
        expected_depth = bool(source_fidelity_qc.get("depth_reference_enabled"))
        if expected_depth != bool(video_assets):
            raise ValueError(
                f"Depth decision differs from source fidelity QC: expected={expected_depth}, "
                f"videos={len(video_assets)}"
            )
        if expected_depth:
            expected_hash = str(source_fidelity_qc.get("depth_output_sha256") or "")
            actual_hash = str(video_assets[0].get("source_sha256") or "")
            if not expected_hash or actual_hash != expected_hash:
                raise ValueError(
                    f"Pixmax depth asset does not bind the accepted depth output: "
                    f"expected={expected_hash!r}, actual={actual_hash!r}"
                )

    content = [{"type": "text", "text": prompt.strip()}]
    for item in assets:
        if item["asset_type"] == "Image":
            content.append({
                "type": "image_url",
                "image_url": {"url": item["asset_ref"]},
                "role": "reference_image",
            })
        else:
            content.append({
                "type": "video_url",
                "video_url": {"url": item["asset_ref"]},
                "role": "reference_video",
            })
    if audio_url:
        content.append({
            "type": "audio_url",
            "audio_url": {"url": audio_url},
            "role": "reference_audio",
        })

    param = {
        "model": SEEDANCE25_MODEL,
        "content": content,
        "generate_audio": audio_mode == "generated_voiceover",
        "ratio": ratio,
        "duration": duration,
        "resolution": resolution,
        "watermark": False,
        "omni_reference_task_type": "reference",
    }
    metadata = {
        "model_family": "Seedance 2.5",
        "audio_mode": audio_mode,
        "postmix_required": audio_mode == "original_master_postmix",
        "submission_policy": "exactly_one_create_request_no_retry",
        "prompt_sha256": hashlib.sha256(prompt.strip().encode("utf-8")).hexdigest(),
    }
    if source_fidelity_qc is not None:
        metadata.update({
            "source_fidelity_qc_sha256": source_fidelity_qc_sha256,
            "source_rhythm_sha256": source_fidelity_qc.get("source_rhythm_sha256"),
            "expected_transcript_sha256": hashlib.sha256(
                str(source_fidelity_qc.get("expected_transcript") or "").encode("utf-8")
            ).hexdigest(),
            "depth_reference_enabled": bool(source_fidelity_qc.get("depth_reference_enabled")),
        })
    request = build_taskcode_request(param, task_code=SEEDANCE25_TASK_CODE, metadata=metadata)
    manifest = {
        "overall": "PASS",
        "model_family": "Seedance 2.5",
        "audio_mode": audio_mode,
        "depth_reference_enabled": bool(video_assets),
        "visual_assets": [
            {
                "role": item.get("role") or "",
                "asset_type": item["asset_type"],
                "asset_ref": item["asset_ref"],
                "status": "Active",
                "source_sha256": item.get("source_sha256") or "",
            }
            for item in assets
        ],
    }
    if source_fidelity_qc is not None:
        manifest["source_fidelity"] = {
            "qc_sha256": source_fidelity_qc_sha256,
            "source_rhythm_sha256": source_fidelity_qc.get("source_rhythm_sha256"),
            "prompt_sha256": source_fidelity_qc.get("prompt_sha256"),
        }
    qc = inspect_taskcode_request(
        request,
        for_submission=True,
        require_active_visual_assets=True,
        require_seedance_prompt_format=True,
    )
    return request, manifest, qc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--pixmax-assets", type=Path, required=True)
    parser.add_argument("--source-fidelity-qc", type=Path, required=True)
    parser.add_argument("--audio-mode", choices=sorted(ALLOWED_AUDIO_MODES), required=True)
    parser.add_argument("--duration", type=int, required=True)
    parser.add_argument("--audio-url", default="")
    parser.add_argument("--ratio", default="9:16")
    parser.add_argument("--resolution", default="720p")
    parser.add_argument("--route", type=Path, default=DEFAULT_ROUTE)
    parser.add_argument("--out-request", type=Path, required=True)
    parser.add_argument("--out-manifest", type=Path, required=True)
    parser.add_argument("--out-qc", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    route = json.loads(args.route.read_text(encoding="utf-8"))
    if route.get("model") != SEEDANCE25_MODEL or route.get("task_code") != SEEDANCE25_TASK_CODE:
        raise SystemExit(f"Seedance 2.5 route config is invalid: {args.route}")
    assets = load_active_assets(args.pixmax_assets)
    prompt = args.prompt.read_text(encoding="utf-8")
    try:
        fidelity = load_source_fidelity_qc(args.source_fidelity_qc, prompt, args.audio_mode)
        request, manifest, qc = build_seedance25_request(
            prompt=prompt,
            assets=assets,
            duration=args.duration,
            audio_mode=args.audio_mode,
            audio_url=args.audio_url,
            ratio=args.ratio,
            resolution=args.resolution,
            source_fidelity_qc=fidelity,
            source_fidelity_qc_sha256=file_sha256(args.source_fidelity_qc),
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    for path, payload in (
        (args.out_request, request),
        (args.out_manifest, manifest),
        (args.out_qc, qc),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if qc["overall"] != "PASS":
        raise SystemExit(f"Seedance 2.5 request QC failed: {args.out_qc}")
    print(f"Seedance 2.5 request PASS: {args.out_request}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
