#!/usr/bin/env python3
"""Matpool GPT-Image-2 image generation/editing entrypoint.

This project intentionally supports only the current Matpool route for GPT
Image work. Deprecated GPT Image providers and gateway probes were removed so
loop runs cannot silently drift into old fallbacks.

Usage:
  python3 generate.py -p "prompt" [-f out.png] [-i ref.png] [options]

Environment:
  MATPOOL_API_KEY     Matpool token API key.
  MATPOOL_BASE_URL    Optional. Defaults to https://token.matpool.com/v1.
  MATPOOL_IMAGE_MODEL Optional. Defaults to GPT-Image-2.
"""

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import sys
import time
from pathlib import Path

import httpx


MATPOOL_BASE = "https://token.matpool.com/v1"
MATPOOL_MODEL = "GPT-Image-2"
DEFAULT_TIMEOUT = 350
QUALITY_LEVELS = ["low", "medium", "high", "auto"]

SIZE_SHORTCUTS = {
    "1k": "1024x1024",
    "2k": "2048x2048",
    "square": "1024x1024",
    "portrait": "1024x1536",
    "landscape": "1536x1024",
    "wide": "2048x1152",
    "tall": "2160x3840",
}

RATIO_TO_PIXEL = {
    "1:1": "1024x1024",
    "2:3": "1024x1536",
    "3:2": "1536x1024",
    "3:4": "1152x1536",
    "4:3": "1536x1152",
    "4:5": "1228x1536",
    "5:4": "1536x1228",
    "9:16": "864x1536",
    "16:9": "1536x864",
    "1:2": "768x1536",
    "2:1": "1536x768",
}
DEFAULT_REFERENCE_ROLES = [
    "source_storyboard",
    "product_front",
    "product_open_mud",
    "identity_ref",
    "afterwash_face",
]
DEFAULT_SOURCE_CONTROLS = ["layout", "shot_order", "framing", "action_rhythm", "scene_family"]
DEFAULT_SOURCE_EXCLUSIONS = [
    "old_product",
    "old_tool",
    "old_host_identity",
    "old_person_clothing",
    "old_mud_color",
    "subtitles",
]


def load_config():
    config_path = Path(__file__).parent.parent / "config" / "default.json"
    if config_path.exists():
        with config_path.open(encoding="utf-8") as f:
            return json.load(f)
    return {}


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, data):
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def split_csv(value, default=None):
    if not value:
        return list(default or [])
    return [item.strip() for item in str(value).replace(",", " ").split() if item.strip()]


def parse_review_flags(values):
    review = {}
    for raw in values or []:
        if "=" in raw:
            key, value = raw.split("=", 1)
            review[key.strip()] = value.strip().lower() in {"1", "true", "yes", "y", "pass", "ok"}
        else:
            review[raw.strip()] = True
    return review


def reference_entries(image_paths, roles):
    paths = local_ref_paths(image_paths)
    selected_roles = list(roles or [])
    if selected_roles and len(selected_roles) != len(paths):
        print("error: --reference-role count must match -i/--image count", file=sys.stderr)
        sys.exit(2)
    if not selected_roles:
        selected_roles = DEFAULT_REFERENCE_ROLES[:len(paths)]
    entries = []
    for role, path in zip(selected_roles, paths):
        entries.append({
            "role": role,
            "path": str(path),
            "sha256": sha256_file(path),
            "mime": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            "loaded_to_context": True,
        })
    return entries


def contract_part_id(value):
    raw = str(value or "").strip().lower()
    if not raw:
        return "part1"
    if raw.isdigit():
        return f"part{raw}"
    if raw.startswith("part"):
        return raw.replace(" ", "")
    return raw


def refs_loaded_map(entries):
    return {
        item["role"]: {
            "path": item["path"],
            "sha256": item["sha256"],
            "mime": item["mime"],
            "loaded_to_context": True,
        }
        for item in entries
    }


def first_ref_path(entries, role):
    for item in entries:
        if item["role"] == role:
            return item["path"]
    return ""


def update_invocation_manifest(path, *, status, config=None, prompt_path=None, prompt_text="", refs=None,
                               outputs=None, args=None, started_at=None, finished_at=None,
                               duration_seconds=None, error=None, quality=None, size=None):
    refs = refs or []
    outputs = outputs or []
    data = {
        "schema_version": 1,
        "status": status,
        "image_route": "matpool_gpt_image_2_edit",
        "provider": "matpool",
        "endpoint": "images/edits" if refs else "images/generations",
        "model": (config or {}).get("model"),
        "base_url": (config or {}).get("base"),
        "prompt_path": str(prompt_path) if prompt_path else None,
        "prompt_sha256": sha256_file(prompt_path) if prompt_path and Path(prompt_path).exists() else None,
        "prompt_chars": len(prompt_text or ""),
        "quality": quality,
        "size": size,
        "format": getattr(args, "format", None) if args else None,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": duration_seconds,
        "inputs_attached_or_loaded": bool(refs),
        "actual_image_inputs_loaded": bool(refs),
        "matpool_uses_real_image_inputs": bool(refs),
        "references_loaded_before_call": refs,
        "actual_image_refs_loaded_before_generation": refs,
        "output_paths": outputs,
        "error": error,
        "deprecated_fallbacks_tried": [],
    }
    write_json(path, data)
    return data


def update_contract(path, *, args, prompt_path, prompt_text, refs, outputs, invocation_manifest,
                    quality, size):
    if not path or not args.job_id:
        return
    contract_file = Path(path)
    if contract_file.exists():
        try:
            contract = json.loads(contract_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            contract = {}
    else:
        contract = {}

    part = contract_part_id(args.part)
    reference_order = [item["role"] for item in refs]
    source_storyboard = first_ref_path(refs, "source_storyboard")
    candidate = outputs[0]["path"] if outputs else ""
    review = parse_review_flags(args.review_flag)
    translations = [{"target_action": item} for item in (args.required_translation or [])]

    contract.update({
        "job_id": args.job_id,
        "stage": args.stage,
        "image_route": "matpool_gpt_image_2_edit",
        "target_application_method": args.target_application_method,
        "source_storyboard_controls": split_csv(args.source_storyboard_controls, DEFAULT_SOURCE_CONTROLS),
        "source_storyboard_must_not_control": split_csv(args.source_storyboard_must_not_control, DEFAULT_SOURCE_EXCLUSIONS),
        "api_effect_baseline": {
            "source": "matpool_gpt_image_2_edit",
            "preserve_api_route": True,
            "reference_order": reference_order,
            "generation_settings": {
                "quality": quality,
                "resolution": args.contract_resolution,
                "ratio_source": source_storyboard or "source_storyboard",
            },
        },
        "preserve_api_route": True,
        "matpool_uses_real_image_inputs": bool(refs),
        "reference_order": reference_order,
        "codex_generation_settings": {
            "quality": quality,
            "resolution": args.contract_resolution,
            "ratio_source": source_storyboard or "source_storyboard",
            "reference_order": reference_order,
            "size": size,
        },
    })

    part_entry = {
        "part": part,
        "source_storyboard": source_storyboard,
        "candidate_path": candidate,
        "candidate_sha256": outputs[0]["sha256"] if outputs else None,
        "prompt_path": str(prompt_path) if prompt_path else None,
        "prompt_text": "" if prompt_path else prompt_text,
        "refs_loaded": refs_loaded_map(refs),
        "source_risks": args.source_risk or [],
        "required_translations": translations,
        "review": review,
        "reference_order": reference_order,
        "codex_generation_settings": {
            "quality": quality,
            "resolution": args.contract_resolution,
            "ratio_source": source_storyboard or "source_storyboard",
            "reference_order": reference_order,
            "size": size,
        },
        "invocation_manifest": str(invocation_manifest) if invocation_manifest else None,
        "asset_type": "AI改好分镜图",
    }
    parts = [item for item in contract.get("parts", []) if isinstance(item, dict) and contract_part_id(item.get("part")) != part]
    parts.append(part_entry)
    contract["parts"] = parts
    write_json(contract_file, contract)


def update_visual_manifest(path, *, args, refs, outputs):
    if not path or not args.update_visual_manifest or not outputs:
        return
    manifest_file = Path(path)
    if manifest_file.exists():
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}
    else:
        manifest = {}
    part = contract_part_id(args.part)
    manifest.setdefault("job_id", args.job_id)
    manifest.setdefault("part_storyboards", {})
    manifest["part_storyboards"][part] = {
        "path": outputs[0]["path"],
        "asset_type": "AI改好分镜图",
        "image_route": "matpool_gpt_image_2_edit",
        "contains_source_video_pixels": False,
        "source_reference": first_ref_path(refs, "source_storyboard"),
        "candidate_sha256": outputs[0]["sha256"],
    }
    write_json(manifest_file, manifest)


def cfg_value(cfg, flat_key, nested_key=None, default=None):
    if cfg.get(flat_key):
        return cfg.get(flat_key)
    if nested_key:
        section, key = nested_key
        nested = cfg.get(section) if isinstance(cfg.get(section), dict) else {}
        if nested.get(key):
            return nested.get(key)
    return default


def api_config():
    cfg = load_config()
    key = os.environ.get("MATPOOL_API_KEY") or cfg_value(cfg, "matpool_api_key", ("matpool", "api_key"))
    if not key:
        print("error: set MATPOOL_API_KEY before calling GPT Image", file=sys.stderr)
        sys.exit(2)
    base = (
        os.environ.get("MATPOOL_BASE_URL")
        or os.environ.get("MATPOOL_API_BASE_URL")
        or cfg_value(cfg, "matpool_base_url", ("matpool", "base_url"), MATPOOL_BASE)
    )
    model = os.environ.get("MATPOOL_IMAGE_MODEL") or cfg_value(cfg, "matpool_model", ("matpool", "model"), MATPOOL_MODEL)
    return {"base": str(base).rstrip("/"), "key": key, "model": model}


def resolve_size(size_str):
    value = str(size_str or "1024x1024").lower()
    if value in SIZE_SHORTCUTS:
        return SIZE_SHORTCUTS[value]
    if value in RATIO_TO_PIXEL:
        return RATIO_TO_PIXEL[value]
    return size_str


def local_ref_paths(image_paths):
    paths = []
    for raw in image_paths or []:
        if raw.startswith("http://") or raw.startswith("https://") or raw.startswith("data:"):
            print("error: Matpool GPT Image edits must use local reference files; do not pre-convert refs to URLs", file=sys.stderr)
            sys.exit(2)
        path = Path(raw)
        if not path.exists():
            print(f"error: image not found: {raw}", file=sys.stderr)
            sys.exit(2)
        paths.append(path)
    return paths


def decode_image(value):
    if value.startswith("data:") and "," in value:
        value = value.split(",", 1)[1]
    return base64.b64decode(value)


def save_images(result, output_path, fmt="png"):
    data_list = result.get("data", [])
    if not data_list:
        print("error: no image data in Matpool response", file=sys.stderr)
        sys.exit(1)

    paths = []
    for idx, item in enumerate(data_list):
        if item.get("b64_json"):
            img_bytes = decode_image(item["b64_json"])
        elif item.get("base64"):
            img_bytes = decode_image(item["base64"])
        elif item.get("url"):
            resp = httpx.get(item["url"], timeout=180, follow_redirects=True)
            if resp.status_code != 200:
                print(f"error: failed to download Matpool image URL ({resp.status_code})", file=sys.stderr)
                sys.exit(1)
            img_bytes = resp.content
        else:
            continue

        if len(data_list) > 1:
            stem = Path(output_path).stem
            suffix = Path(output_path).suffix or f".{fmt}"
            path = str(Path(output_path).parent / f"{stem}_{idx}{suffix}")
        else:
            path = output_path

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            f.write(img_bytes)
        paths.append(path)

    if not paths:
        print("error: Matpool response had data entries but no saveable image fields", file=sys.stderr)
        sys.exit(1)
    return paths


def matpool_call(config, prompt, size, quality, n, image_paths=None,
                 background=None, moderation=None, output_format=None, user=None):
    refs = local_ref_paths(image_paths)
    payload = {"model": config["model"], "prompt": prompt}
    if size:
        payload["size"] = size
    if quality:
        payload["quality"] = quality
    if n:
        payload["n"] = str(n) if refs else n
    if background:
        payload["background"] = background
    if moderation:
        payload["moderation"] = moderation
    if output_format:
        payload["output_format"] = output_format
    if user:
        payload["user"] = user

    headers = {"Authorization": f"Bearer {config['key']}"}
    if refs:
        files = []
        handles = []
        try:
            for idx, path in enumerate(refs, start=1):
                mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                suffix = path.suffix.lower() or ".png"
                handle = path.open("rb")
                handles.append(handle)
                files.append(("image", (f"reference-{idx}{suffix}", handle, mime)))
            resp = httpx.post(
                f"{config['base']}/images/edits",
                headers=headers,
                data=payload,
                files=files,
                timeout=DEFAULT_TIMEOUT,
            )
        finally:
            for handle in handles:
                handle.close()
    else:
        resp = httpx.post(
            f"{config['base']}/images/generations",
            headers={**headers, "Content-Type": "application/json"},
            json=payload,
            timeout=DEFAULT_TIMEOUT,
        )

    if resp.status_code != 200:
        print(f"error: {resp.status_code} from Matpool API: {resp.text[:2000]}", file=sys.stderr)
        sys.exit(1)
    return resp.json()


def main():
    parser = argparse.ArgumentParser(description="Matpool GPT-Image-2 image generator/editor")
    parser.add_argument("-p", "--prompt", default=None, help="Text prompt")
    parser.add_argument("--prompt-file", default=None, help="Text prompt file")
    parser.add_argument("-f", "--file", default=None, help="Output path")
    parser.add_argument("-i", "--image", action="append", default=None, help="Local reference image; repeat for multi-ref edits")
    parser.add_argument("--reference-role", action="append", default=None, help="Role for each -i image, in the same order")
    parser.add_argument("--model", default=None, help="Override model ID. Defaults to GPT-Image-2")
    parser.add_argument("--provider", default="matpool", choices=["matpool"], help="Only matpool is supported")
    parser.add_argument("--size", default="1024x1024", help="Image size or ratio, e.g. 1024x1024, 3:4, portrait")
    parser.add_argument("--quality", default="medium", choices=QUALITY_LEVELS, help="Generation quality")
    parser.add_argument("-n", "--n", type=int, default=1, help="Number of images")
    parser.add_argument("--format", default="png", choices=["png", "jpeg", "webp"], help="Output format")
    parser.add_argument("--background", default=None, help="Background: auto or opaque")
    parser.add_argument("--moderation", default=None, help="Moderation: auto or low")
    parser.add_argument("--user", default=None, help="End-user identifier")
    parser.add_argument("--no-retry", action="store_true", help="Disable quality downgrade retry")
    parser.add_argument("--job-id", default="", help="Loop job id for contract evidence")
    parser.add_argument("--stage", default="image_batch_qc", help="Loop stage for contract evidence")
    parser.add_argument("--part", default="part1", help="Part id, e.g. part1")
    parser.add_argument("--invocation-manifest", default="", help="Write Matpool invocation evidence JSON")
    parser.add_argument("--contract", default="", help="Write/update codex_imagegen_contract.json")
    parser.add_argument("--visual-manifest", default="", help="Write/update approved_visual_manifest.json")
    parser.add_argument("--update-visual-manifest", action="store_true", help="Update the visual manifest with this candidate")
    parser.add_argument("--contract-resolution", default="1K", help="Resolution label for contract QC")
    parser.add_argument("--source-storyboard-controls", default=",".join(DEFAULT_SOURCE_CONTROLS))
    parser.add_argument("--source-storyboard-must-not-control", default=",".join(DEFAULT_SOURCE_EXCLUSIONS))
    parser.add_argument("--target-application-method", default="", help="Product profile application method for contract QC")
    parser.add_argument("--source-risk", action="append", default=[], help="Source risk carried into the contract")
    parser.add_argument("--required-translation", action="append", default=[], help="Required source-risk translation note")
    parser.add_argument("--review-flag", action="append", default=[], help="Checker review flag, e.g. layout_matches_source=true")
    args = parser.parse_args()
    if args.prompt_file:
        prompt_path = Path(args.prompt_file)
        prompt = prompt_path.read_text(encoding="utf-8").strip()
    else:
        prompt_path = None
        prompt = (args.prompt or "").strip()
    if not prompt:
        print("error: provide --prompt or --prompt-file", file=sys.stderr)
        sys.exit(2)

    output_path = args.file
    if not output_path:
        ts = time.strftime("%Y%m%d-%H%M%S")
        slug = prompt[:30].replace(" ", "_").replace("/", "-")
        output_path = f"fig/{ts}-{slug}.{args.format}"
        Path("fig").mkdir(exist_ok=True)

    quality_levels = [args.quality]
    if not args.no_retry:
        if args.quality == "high":
            quality_levels.extend(["medium", "low"])
        elif args.quality == "medium":
            quality_levels.append("low")

    started = time.time()
    started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    refs = []
    config = {}
    last_error = None
    try:
        refs = reference_entries(args.image, args.reference_role)
        config = api_config()
        if args.model:
            config["model"] = args.model
        for quality in quality_levels:
            try:
                size = resolve_size(args.size)
                result = matpool_call(
                    config,
                    prompt,
                    size,
                    quality,
                    args.n,
                    image_paths=args.image,
                    background=args.background,
                    moderation=args.moderation,
                    output_format=args.format,
                    user=args.user,
                )
                outputs = []
                for path in save_images(result, output_path, args.format):
                    output = {
                        "path": path,
                        "sha256": sha256_file(path),
                        "bytes": Path(path).stat().st_size,
                    }
                    outputs.append(output)
                    print(path)
                finished_at = time.strftime("%Y-%m-%dT%H:%M:%S")
                duration = round(time.time() - started, 3)
                update_invocation_manifest(
                    args.invocation_manifest,
                    status="PASS",
                    config=config,
                    prompt_path=prompt_path,
                    prompt_text=prompt,
                    refs=refs,
                    outputs=outputs,
                    args=args,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_seconds=duration,
                    quality=quality,
                    size=size,
                )
                update_contract(
                    args.contract,
                    args=args,
                    prompt_path=prompt_path,
                    prompt_text=prompt,
                    refs=refs,
                    outputs=outputs,
                    invocation_manifest=args.invocation_manifest,
                    quality=quality,
                    size=size,
                )
                update_visual_manifest(args.visual_manifest, args=args, refs=refs, outputs=outputs)
                return
            except SystemExit:
                raise
            except Exception as exc:
                last_error = exc
                if quality != quality_levels[-1]:
                    print(f"warning: quality {quality} failed ({exc}), retrying", file=sys.stderr)
    except SystemExit as exc:
        finished_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        update_invocation_manifest(
            args.invocation_manifest,
            status="STOP" if exc.code == 2 else "FAIL",
            config=config,
            prompt_path=prompt_path,
            prompt_text=prompt,
            refs=refs,
            outputs=[],
            args=args,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=round(time.time() - started, 3),
            error=f"exit_code={exc.code}",
            quality=args.quality,
            size=resolve_size(args.size),
        )
        raise
    except Exception as exc:
        last_error = exc

    finished_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    update_invocation_manifest(
        args.invocation_manifest,
        status="FAIL",
        config=config,
        prompt_path=prompt_path,
        prompt_text=prompt,
        refs=refs,
        outputs=[],
        args=args,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=round(time.time() - started, 3),
        error=str(last_error),
        quality=quality_levels[-1],
        size=resolve_size(args.size),
    )
    print(f"error: all Matpool attempts failed: {last_error}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
