#!/usr/bin/env python3
"""Block MiniMax H3 packs that do not bind changed speech to an approved master."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_dialogue(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", text)


def prompt_dialogue(prompt: str) -> str:
    chunks = re.findall(r"<d>\[Chinese\]\s*(.*?)</d>", prompt, flags=re.DOTALL)
    return normalized_dialogue("".join(chunks))


def probe_audio(path: Path) -> dict[str, object]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name,sample_rate,channels:format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def add(checks: list[dict[str, object]], name: str, passed: bool, detail: str) -> None:
    checks.append({"name": name, "status": "PASS" if passed else "FAIL", "detail": detail})


def validate(pack_root: Path) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    contract_path = pack_root / "audio_contract.json"
    if not contract_path.is_file():
        add(checks, "audio_contract_present", False, str(contract_path))
        return {"schema_version": 1, "status": "BLOCKED", "checks": checks}

    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    changed = contract.get("speech_change") == "changed"
    strategy = contract.get("strategy")
    add(checks, "changed_speech_uses_tts", not changed or strategy == "tts_approved_master", f"speech_change={contract.get('speech_change')}, strategy={strategy}")

    approval = contract.get("user_approval", {})
    approval_ok = (
        not changed
        or (
            approval.get("status") == "approved"
            and approval.get("method") == "direct_user_listening"
            and bool(approval.get("approved_at"))
        )
    )
    add(checks, "direct_user_listening_approval", approval_ok, f"status={approval.get('status')}, method={approval.get('method')}")

    postmix = contract.get("final_audio_policy", {})
    postmix_ok = (
        postmix.get("h3_guidance_relationship") == "fully_copy"
        and postmix.get("delivery_audio") == "approved_master"
        and postmix.get("postmix") == "replace_h3_audio_with_approved_master"
    )
    add(checks, "deterministic_postmix_policy", postmix_ok, json.dumps(postmix, ensure_ascii=False, sort_keys=True))

    units = contract.get("units")
    add(checks, "units_declared", isinstance(units, list) and bool(units), f"count={len(units) if isinstance(units, list) else 0}")
    for unit in units if isinstance(units, list) else []:
        unit_id = str(unit.get("unit_id", "missing-unit"))
        prefix = unit_id.replace("-", "_")
        unit_dir = pack_root / unit_id
        master_rel = unit.get("master_file")
        master = pack_root / str(master_rel) if master_rel else Path("/__missing_master__")
        exists = master.is_file()
        add(checks, f"{prefix}_master_present", exists, str(master))
        if not exists:
            continue

        actual_hash = sha256(master)
        add(checks, f"{prefix}_master_hash", actual_hash == unit.get("sha256"), f"actual={actual_hash}, expected={unit.get('sha256')}")
        try:
            probe = probe_audio(master)
            streams = probe.get("streams", [])
            duration = float(probe.get("format", {}).get("duration", 0.0))
            expected_duration = float(unit.get("duration_seconds", 0.0))
            media_ok = len(streams) == 1 and abs(duration - expected_duration) <= 0.03
            add(checks, f"{prefix}_master_media", media_ok, f"duration={duration:.6f}, expected={expected_duration:.6f}, streams={len(streams)}")
        except (subprocess.CalledProcessError, ValueError, KeyError, json.JSONDecodeError) as exc:
            add(checks, f"{prefix}_master_media", False, str(exc))

        generation_manifest = pack_root / str(unit.get("generation_manifest", ""))
        generation_ok = generation_manifest.is_file()
        add(checks, f"{prefix}_generation_provenance", generation_ok, str(generation_manifest))
        if generation_ok:
            generation = json.loads(generation_manifest.read_text(encoding="utf-8"))
            generation_ok = (
                (
                    generation.get("engine") == "VoxCPM2"
                    if changed
                    else generation.get("engine") == "ffmpeg_extract"
                )
                and generation.get("final_sha256") == actual_hash
                and normalized_dialogue(str(generation.get("target_text", ""))) == normalized_dialogue(str(unit.get("target_text", "")))
            )
            add(checks, f"{prefix}_generation_binding", generation_ok, f"engine={generation.get('engine')}, final_sha256={generation.get('final_sha256')}")

        manifest_path = unit_dir / "upload_manifest.json"
        manifest_ok = manifest_path.is_file()
        add(checks, f"{prefix}_upload_manifest_present", manifest_ok, str(manifest_path))
        if manifest_ok:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            audio_assets = [item for item in manifest.get("content_order", []) if item.get("role") == "reference_audio"]
            expected_unit_file = Path(str(master_rel)).name
            binding_ok = (
                len(audio_assets) == 1
                and audio_assets[0].get("file") == expected_unit_file
                and audio_assets[0].get("sha256") == actual_hash
                and manifest.get("reference_audio", {}).get("relationship") == "fully_copy"
                and manifest.get("reference_audio", {}).get("scope") == "complete_final_soundtrack"
            )
            add(checks, f"{prefix}_upload_audio_binding", binding_ok, json.dumps(audio_assets, ensure_ascii=False, sort_keys=True))

        prompt_path = unit_dir / "00_H3_Ref2VA_prompt.txt"
        prompt_ok = prompt_path.is_file()
        add(checks, f"{prefix}_prompt_present", prompt_ok, str(prompt_path))
        if prompt_ok:
            prompt = prompt_path.read_text(encoding="utf-8")
            dialogue_ok = prompt_dialogue(prompt) == normalized_dialogue(str(unit.get("target_text", "")))
            audio_prompt_ok = (
                "<Audio 1>: fully_copy" in prompt
                and "complete and only final soundtrack" in prompt
                and "Generate the exact target narration" not in prompt
                and "voice-style excerpt" not in prompt
                and "timbre-and-delivery reference" not in prompt
            )
            add(checks, f"{prefix}_prompt_dialogue_matches_master", dialogue_ok, f"prompt={prompt_dialogue(prompt)}, contract={normalized_dialogue(str(unit.get('target_text', '')))}")
            add(checks, f"{prefix}_prompt_uses_master", audio_prompt_ok, "requires fully_copy and forbids voice generation/reference-only wording")

    status = "PASS" if checks and all(item["status"] == "PASS" for item in checks) else "BLOCKED"
    return {"schema_version": 1, "status": status, "pack_root": str(pack_root), "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pack_root", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    pack_root = args.pack_root.resolve()
    report = validate(pack_root)
    report_path = args.report.resolve() if args.report else pack_root / "pre_generation_audio_gate.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
