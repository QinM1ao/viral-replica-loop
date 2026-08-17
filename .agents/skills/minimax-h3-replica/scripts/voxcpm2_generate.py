#!/usr/bin/env python3
"""Generate full-unit VoxCPM2 masters from a JSON plan in one model session."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from voxcpm import VoxCPM


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def conform(raw: Path, final: Path, target: float, speech_target: float) -> dict[str, object]:
    raw_duration = duration(raw)
    filters: list[str] = []
    tempo = raw_duration / max(speech_target, 0.1)
    action = "tempo_fit_then_pad"
    if abs(tempo - 1.0) > 0.005:
        while tempo > 2.0:
            filters.append("atempo=2.0")
            tempo /= 2.0
        while tempo < 0.5:
            filters.append("atempo=0.5")
            tempo /= 0.5
        filters.append(f"atempo={tempo:.8f}")
    else:
        action = "pad_tail"
    filters.extend(["volume=-1dB", f"apad=pad_dur={target:.6f}", f"atrim=0:{target:.6f}"])
    final.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw), "-af", ",".join(filters), "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(final)],
        check=True,
    )
    return {
        "raw_duration_seconds": raw_duration,
        "speech_target_duration_seconds": speech_target,
        "conform_action": action,
        "filters": filters,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", type=Path)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--device", default="mps")
    parser.add_argument("--conform-only", action="store_true")
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    seed = int(plan.get("seed", 42))
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)

    model = None
    if not args.conform_only:
        model_started = time.monotonic()
        model = VoxCPM.from_pretrained(
            str(args.model_path),
            load_denoiser=False,
            local_files_only=True,
            optimize=False,
            device=args.device,
        )
        print(json.dumps({"event": "model_loaded", "seconds": time.monotonic() - model_started}), flush=True)

    reference = str(Path(plan["reference_wav"]).resolve())
    prompt_text = str(plan["prompt_text"])
    for unit in plan["units"]:
        unit_started = time.monotonic()
        raw = Path(unit["raw_file"]).resolve()
        final = Path(unit["final_file"]).resolve()
        metadata = Path(unit["generation_manifest"]).resolve()
        raw.parent.mkdir(parents=True, exist_ok=True)
        if not args.conform_only:
            assert model is not None
            wav = model.generate(
                text=str(unit["target_text"]),
                prompt_wav_path=reference,
                prompt_text=prompt_text,
                reference_wav_path=reference,
                cfg_value=float(plan.get("cfg_value", 2.0)),
                inference_timesteps=int(plan.get("inference_timesteps", 10)),
                normalize=False,
                denoise=False,
            )
            sf.write(raw, wav, model.tts_model.sample_rate, subtype="PCM_16")
        elif not raw.is_file():
            raise FileNotFoundError(f"conform-only raw file missing: {raw}")
        conform_info = conform(
            raw,
            final,
            float(unit["duration_seconds"]),
            float(unit.get("speech_duration_seconds", unit["duration_seconds"] - 0.08)),
        )
        existing = json.loads(metadata.read_text(encoding="utf-8")) if args.conform_only and metadata.is_file() else {}
        payload = {
            **existing,
            "schema_version": 1,
            "engine": "VoxCPM2",
            "model_path": str(args.model_path),
            "device": args.device,
            "seed": seed,
            "cfg_value": float(plan.get("cfg_value", 2.0)),
            "inference_timesteps": int(plan.get("inference_timesteps", 10)),
            "reference_wav": reference,
            "reference_sha256": sha256(Path(reference)),
            "prompt_text": prompt_text,
            "target_text": str(unit["target_text"]),
            "target_duration_seconds": float(unit["duration_seconds"]),
            "speech_target_duration_seconds": float(unit.get("speech_duration_seconds", unit["duration_seconds"] - 0.08)),
            "raw_file": str(raw),
            "raw_sha256": sha256(raw),
            "final_file": str(final),
            "final_sha256": sha256(final),
            "final_duration_seconds": duration(final),
            "generation_seconds": existing.get("generation_seconds", time.monotonic() - unit_started),
            **conform_info,
        }
        metadata.parent.mkdir(parents=True, exist_ok=True)
        metadata.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"event": "unit_complete", "unit_id": unit["unit_id"], "final_file": str(final), "seconds": payload["generation_seconds"]}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
