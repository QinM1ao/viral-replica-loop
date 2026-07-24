#!/usr/bin/env python3
import argparse
import csv
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from hash_gated_visual_qc import active_image_hashes
from product_profile import (
    profile_requires_mud_contract,
    profile_requires_skincare_progression,
    required_ref_roles,
)
from qc_input_binding import (
    attach_input_binding,
    display_path,
    manifest_fingerprint,
    resolve_path,
    sha256_file,
)
from visual_asset_manifest_qc import (
    build_report as build_visual_manifest_report,
    resolve_path as resolve_manifest_path,
)


FAMILY_CHECKS = {
    "geometry_appearance": [
        "source_grid_and_shot_order_visually_preserved",
        "no_visible_squeeze_or_crop_drift",
        "no_recomposed_storyboard",
    ],
    "identity_product_material_integrity": [
        "approved_identity_and_wardrobe_preserved",
        "current_product_and_scale_appropriate_label_preserved",
        "material_and_usage_match_product_profile",
        "no_source_person_product_tool_or_subtitle_contamination",
    ],
    "cross_part_continuity": [
        "identity_wardrobe_scene_and_product_are_continuous",
    ],
    "skincare_progression": [
        "prewash_and_postwash_states_are_ordered",
        "visible_improvement_is_not_lighting_only",
        "real_skin_texture_is_preserved",
    ],
}

DEFAULT_LABEL_REVIEW_POLICY = {
    "storyboard_microtext_exact_required": False,
    "small_or_distant_product_text": "visual_match_only",
    "microtext_only_mismatch_outcome": "VISUAL_WARNING",
    "hero_closeup_major_label_required": True,
}


def stable_hash(value):
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_json(path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def find_job(root, job_id):
    jobs_path = root / "jobs.csv"
    if not jobs_path.exists():
        return None
    with jobs_path.open(newline="", encoding="utf-8") as handle:
        for job in csv.DictReader(handle):
            if str(job.get("id", "")).strip() == job_id:
                return job
    return None


def resolve_output(root, raw, default):
    path = Path(raw) if raw else default
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def add_check(checks, name, status, detail):
    checks.append({"name": name, "status": status, "detail": detail})


def checks_overall(checks):
    severity = {"PASS": 0, "FAIL": 1, "STOP": 2}
    if not checks:
        return "STOP"
    return max(checks, key=lambda item: severity.get(item.get("status"), 2))["status"]


def is_under(path, parent):
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (FileNotFoundError, ValueError):
        return False


def read_image(path):
    try:
        with Image.open(path) as opened:
            image = ImageOps.exif_transpose(opened)
            image.load()
            return {
                "readable": True,
                "size": [image.width, image.height],
                "orientation": "portrait" if image.height >= image.width else "landscape",
            }
    except (OSError, ValueError):
        return {"readable": False, "size": None, "orientation": None}


def expected_grid(orientation):
    return {"cols": 3, "rows": 4} if orientation == "landscape" else {"cols": 4, "rows": 3}


def bound_candidate_hash(root, report, candidate):
    direct = str(report.get("candidate_sha256", "")).strip()
    if len(direct) == 64:
        return direct
    binding = report.get("input_binding")
    if not isinstance(binding, dict):
        return None
    manifest = binding.get("manifest")
    if not isinstance(manifest, dict) or binding.get("fingerprint") != manifest_fingerprint(manifest):
        return None
    record = manifest.get(display_path(root, candidate))
    if not isinstance(record, dict) or record.get("kind") != "file":
        return None
    recorded = str(record.get("sha256", "")).strip()
    return recorded if len(recorded) == 64 else None


def load_input_object(root, path, label, checks):
    if not path.exists():
        add_check(checks, f"{label}_exists", "STOP", display_path(root, path))
        return None
    try:
        value = load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        add_check(checks, f"{label}_readable", "FAIL", str(exc))
        return None
    if not isinstance(value, dict):
        add_check(checks, f"{label}_object", "FAIL", f"expected object, got {type(value).__name__}")
        return None
    add_check(checks, f"{label}_readable", "PASS", display_path(root, path))
    return value


def validate_part_context(root, job_id, manifest, checks, inputs):
    parts = []
    job_dir = root / "output" / job_id
    for part, entry in sorted((manifest.get("part_storyboards") or {}).items()):
        if not isinstance(entry, dict):
            continue
        candidate = resolve_path(root, entry.get("path"))
        source = resolve_path(root, entry.get("source_reference"))
        metadata = entry.get("shot_label_metadata") or {}
        evidence_path = resolve_path(root, metadata.get("evidence"))
        hard_gate_path = resolve_path(root, entry.get("hard_gate"))
        inputs.extend([candidate, source, evidence_path, hard_gate_path])

        add_check(
            checks,
            f"{part}_current_job_source_reference",
            "PASS" if source and is_under(source, job_dir) else "FAIL",
            display_path(root, source),
        )
        if not candidate or not candidate.exists() or not source or not source.exists():
            continue
        candidate_info = read_image(candidate)
        source_info = read_image(source)
        add_check(
            checks,
            f"{part}_candidate_readable",
            "PASS" if candidate_info["readable"] else "FAIL",
            display_path(root, candidate),
        )
        add_check(
            checks,
            f"{part}_source_readable",
            "PASS" if source_info["readable"] else "FAIL",
            display_path(root, source),
        )
        if not candidate_info["readable"] or not source_info["readable"]:
            continue
        add_check(
            checks,
            f"{part}_orientation_matches_source",
            "PASS" if candidate_info["orientation"] == source_info["orientation"] else "FAIL",
            f"candidate={candidate_info['orientation']} source={source_info['orientation']}",
        )
        source_ratio = source_info["size"][0] / source_info["size"][1]
        candidate_ratio = candidate_info["size"][0] / candidate_info["size"][1]
        aspect_drift = abs(candidate_ratio - source_ratio) / source_ratio
        # Matpool commonly returns a nearby supported canvas rather than the
        # source board's exact pixel ratio.  Up to 3% relative drift keeps the
        # same orientation and panel geometry without treating a non-visible
        # canvas difference as a regeneration-worthy defect.
        max_canvas_aspect_drift = 0.03
        add_check(
            checks,
            f"{part}_canvas_aspect_matches_source",
            "PASS" if aspect_drift <= max_canvas_aspect_drift else "FAIL",
            f"drift={aspect_drift:.6f} limit={max_canvas_aspect_drift:.6f}",
        )
        candidate_sha = sha256_file(candidate)
        add_check(
            checks,
            f"{part}_manifest_candidate_hash",
            "PASS" if entry.get("candidate_sha256") == candidate_sha else "FAIL",
            f"manifest={entry.get('candidate_sha256')} promoted={candidate_sha}",
        )

        evidence = None
        if evidence_path and evidence_path.exists():
            try:
                loaded = load_json(evidence_path)
                evidence = loaded if isinstance(loaded, dict) else None
            except (OSError, json.JSONDecodeError):
                evidence = None
        add_check(
            checks,
            f"{part}_shot_metadata_grid",
            "PASS"
            if evidence and evidence.get("grid") == expected_grid(candidate_info["orientation"])
            else "FAIL",
            f"actual={(evidence or {}).get('grid')} expected={expected_grid(candidate_info['orientation'])}",
        )
        add_check(
            checks,
            f"{part}_shot_metadata_canvas",
            "PASS" if evidence and evidence.get("canvas") == candidate_info["size"] else "FAIL",
            f"actual={(evidence or {}).get('canvas')} expected={candidate_info['size']}",
        )
        hard_gate = None
        if hard_gate_path and hard_gate_path.exists():
            try:
                loaded = load_json(hard_gate_path)
                hard_gate = loaded if isinstance(loaded, dict) else None
            except (OSError, json.JSONDecodeError):
                hard_gate = None
        if hard_gate is None:
            add_check(checks, f"{part}_hard_gate_evidence", "STOP", display_path(root, hard_gate_path))
        else:
            gate_candidate = resolve_path(root, hard_gate.get("candidate"))
            add_check(
                checks,
                f"{part}_hard_gate_candidate_binding",
                "PASS" if gate_candidate and gate_candidate.resolve() == candidate.resolve() else "FAIL",
                f"gate={display_path(root, gate_candidate)} promoted={display_path(root, candidate)}",
            )
            gate_candidate_sha = bound_candidate_hash(root, hard_gate, candidate)
            if gate_candidate_sha != candidate_sha:
                detail = (
                    "unbound legacy report ignored; current candidate receives a full semantic review"
                    if gate_candidate_sha is None
                    else f"stale={gate_candidate_sha} current={candidate_sha}; stale result ignored"
                )
                add_check(checks, f"{part}_hard_gate_evidence_freshness", "PASS", detail)
            else:
                gate_status = str(hard_gate.get("overall", ""))
                add_check(
                    checks,
                    f"{part}_hard_gate_evidence_freshness",
                    gate_status if gate_status in {"PASS", "FAIL", "STOP"} else "STOP",
                    f"exact candidate hash={candidate_sha} result={gate_status}",
                )
        parts.append(
            {
                "part": part,
                "path": candidate,
                "source_reference": source,
                "candidate_sha256": candidate_sha,
            }
        )
    return parts


def selected_support_refs(root, manifest, profile):
    reusable = manifest.get("reusable_refs") or {}
    keys = ["product_front", "identity_ref"]
    if profile_requires_mud_contract(profile) or "product_open_mud" in required_ref_roles(profile):
        keys.append("product_open")
    if profile_requires_skincare_progression(profile) and reusable.get("afterwash_face"):
        keys.append("afterwash_face")
    refs = [
        {"role": key, "path": resolve_path(root, reusable.get(key))}
        for key in keys
        if reusable.get(key)
    ]
    group_path = resolve_path(root, manifest.get("product_group_manifest"))
    if group_path and group_path.is_file():
        try:
            group = load_json(group_path)
        except (OSError, json.JSONDecodeError):
            group = {}
        raw_detail = group.get("label_detail_ref") if isinstance(group, dict) else None
        if str(raw_detail or "").strip():
            detail_path = resolve_manifest_path(
                root,
                raw_detail,
                base=group_path.parent,
            )
            if detail_path and detail_path.is_file():
                refs.append({"role": "product_label_detail", "path": detail_path})
    return refs


def fit_image(path, size):
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    image.thumbnail(size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", size, "white")
    canvas.paste(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2))
    return canvas


def make_compare_context(root, parts, support_refs, output_path):
    items = []
    for part in parts:
        items.append((f"{part['part']} source", part["source_reference"]))
        items.append((f"{part['part']} promoted", part["path"]))
    items.extend((f"support {item['role']}", item["path"]) for item in support_refs)
    columns = min(3, max(1, len(items)))
    rows = (len(items) + columns - 1) // columns
    tile_w, tile_h, label_h, margin, gap = 640, 960, 38, 18, 14
    width = margin * 2 + columns * tile_w + max(0, columns - 1) * gap
    height = margin * 2 + rows * (label_h + tile_h) + max(0, rows - 1) * gap
    sheet = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (label, path) in enumerate(items):
        row, column = divmod(index, columns)
        x = margin + column * (tile_w + gap)
        y = margin + row * (label_h + tile_h + gap)
        draw.rectangle((x, y, x + tile_w, y + label_h - 2), fill=(242, 242, 242))
        draw.text((x + 8, y + 11), label, fill=(25, 25, 25))
        sheet.paste(fit_image(path, (tile_w, tile_h)), (x, y + label_h))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, "JPEG", quality=92)
    return {
        "role": "overview",
        "path": display_path(root, output_path),
        "sha256": sha256_file(output_path),
        "item_count": len(items),
        "source_artifacts": [
            {
                "label": label,
                "path": display_path(root, path),
                "sha256": sha256_file(path),
            }
            for label, path in items
        ],
    }


def reusable_compare_context(
    root,
    request_path,
    compare_path,
    active_fingerprint,
    prior_request=None,
):
    if not compare_path.exists():
        return None
    requests = [prior_request]
    if request_path.exists():
        try:
            requests.append(load_json(request_path))
        except (OSError, json.JSONDecodeError):
            pass
    for request in requests:
        if not isinstance(request, dict) or request.get("active_input_fingerprint") != active_fingerprint:
            continue
        context = request.get("canonical_compare_context")
        if not isinstance(context, dict):
            continue
        recorded_path = resolve_path(root, context.get("path"))
        if not recorded_path or recorded_path.resolve() != compare_path.resolve():
            continue
        if context.get("sha256") == sha256_file(compare_path):
            return context
    return None


def profile_expectations(profile):
    visible_text_patterns = profile.get("visible_text_patterns") or []
    label_review_policy = {
        **DEFAULT_LABEL_REVIEW_POLICY,
        **(profile.get("label_review_policy") or {}),
    }
    if not visible_text_patterns:
        label_review_policy["hero_closeup_major_label_required"] = False
    return {
        "loaded_rules": profile.get("loaded_rules") or [],
        "required_review_flags": (profile.get("review_flags") or {}).get("required") or [],
        "visible_text_patterns": visible_text_patterns,
        "label_review_policy": label_review_policy,
        "usage_action": profile.get("usage_action", ""),
        "checks": profile.get("checks") or {},
        "character_policy": profile.get("character_policy") or {},
    }


def integrity_profile_expectations(expectations):
    skincare_terms = ("skin", "afterwash", "prewash", "postwash", "progression")

    def is_skincare_only(name):
        lowered = str(name).lower()
        return any(term in lowered for term in skincare_terms)

    return {
        "required_review_flags": [
            flag
            for flag in expectations["required_review_flags"]
            if not is_skincare_only(flag)
        ],
        "visible_text_patterns": expectations["visible_text_patterns"],
        "label_review_policy": expectations["label_review_policy"],
        "usage_action": expectations["usage_action"],
        "checks": {
            key: value
            for key, value in expectations["checks"].items()
            if not is_skincare_only(key)
        },
        "character_policy": expectations["character_policy"],
    }


def select_families(root, manifest, manifest_path, parts, support_refs, profile):
    active_hashes = active_image_hashes(root, manifest, manifest_path)
    part_visuals = {
        part["part"]: {
            "visual_content_sha256": active_hashes.get(part["part"], {}).get("visual_content_sha256"),
            "source_sha256": sha256_file(part["source_reference"]),
        }
        for part in parts
    }
    support_hashes = {item["role"]: sha256_file(item["path"]) for item in support_refs}
    integrity_support_hashes = {
        role: value
        for role, value in support_hashes.items()
        if role in {
            "product_front",
            "product_open",
            "product_label_detail",
            "identity_ref",
        }
    }
    expectations = profile_expectations(profile)
    payloads = {
        "geometry_appearance": {"parts": part_visuals},
        "identity_product_material_integrity": {
            "parts": part_visuals,
            "support_refs": integrity_support_hashes,
            "product_group_id": manifest.get("product_group_id", ""),
            "identity_group_id": manifest.get("identity_group_id", ""),
            "profile_expectations": integrity_profile_expectations(expectations),
        },
        "cross_part_continuity": {
            "parts": {
                name: value["visual_content_sha256"] for name, value in part_visuals.items()
            },
            "product_group_id": manifest.get("product_group_id", ""),
            "identity_group_id": manifest.get("identity_group_id", ""),
        },
        "skincare_progression": {
            "parts": {
                name: value["visual_content_sha256"] for name, value in part_visuals.items()
            },
            "afterwash_ref": support_hashes.get("afterwash_face"),
            "skincare_checks": {
                key: value
                for key, value in expectations["checks"].items()
                if "skin" in key or "afterwash" in key
            },
        },
    }
    names = ["geometry_appearance", "identity_product_material_integrity"]
    if len(parts) > 1:
        names.append("cross_part_continuity")
    if profile_requires_skincare_progression(profile):
        names.append("skincare_progression")
    return [
        {
            "name": name,
            "fingerprint_hash": stable_hash(
                {"version": 1, "family": name, "relevant_inputs": payloads[name]}
            ),
            "required_checks": FAMILY_CHECKS[name],
        }
        for name in names
    ]


def initial_report(job_id, stage, checks, mode):
    preflight = {"overall": checks_overall(checks), "checks": checks}
    return {
        "version": 1,
        "job_id": job_id,
        "stage": stage,
        "mode": mode,
        "overall": preflight["overall"],
        "reason": "deterministic preflight did not pass",
        "deterministic_preflight": preflight,
        "semantic_family_selection": [],
        "canonical_compare_context": None,
        "semantic_review": {"status": "NOT_REQUESTED", "request_path": None},
    }


def inspect_acceptance_inputs(root, job, stage, manifest_path, profile_path):
    checks = []
    inputs = [manifest_path, profile_path]
    manifest = load_input_object(root, manifest_path, "approved_visual_manifest", checks)
    profile = load_input_object(root, profile_path, "product_profile", checks)
    parts = []
    support_refs = []
    if manifest is not None and profile is not None:
        try:
            contract = build_visual_manifest_report(
                root,
                job["id"],
                stage,
                manifest_arg=str(manifest_path),
            )
            checks.extend(contract.get("checks") or [])
            inputs.extend(
                [
                    resolve_path(root, contract.get("product_group_manifest")),
                    resolve_path(root, contract.get("identity_group_manifest")),
                ]
            )
        except (AttributeError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            add_check(checks, "visual_manifest_contract", "FAIL", str(exc))
        parts = validate_part_context(root, job["id"], manifest, checks, inputs)
        support_refs = selected_support_refs(root, manifest, profile)
        inputs.extend(item["path"] for item in support_refs)
    return {
        "checks": checks,
        "inputs": inputs,
        "manifest": manifest,
        "profile": profile,
        "parts": parts,
        "support_refs": support_refs,
    }


def current_semantic_family_selection(root, job, stage="image_batch_qc"):
    root = Path(root).resolve()
    output = root / "output" / job["id"]
    manifest_path = output / "visual-assets" / "approved_visual_manifest.json"
    inspected = inspect_acceptance_inputs(
        root,
        job,
        stage,
        manifest_path,
        output / "product_profile.json",
    )
    if checks_overall(inspected["checks"]) != "PASS":
        return [], "current storyboard inputs failed deterministic preflight"
    return select_families(
        root,
        inspected["manifest"],
        manifest_path,
        inspected["parts"],
        inspected["support_refs"],
        inspected["profile"],
    ), ""


def planned_compare_context(root, parts, support_refs, output_path):
    items = []
    for part in parts:
        items.append((f"{part['part']} source", part["source_reference"]))
        items.append((f"{part['part']} promoted", part["path"]))
    items.extend((f"support {item['role']}", item["path"]) for item in support_refs)
    return {
        "role": "overview",
        "path": display_path(root, output_path),
        "sha256": None,
        "item_count": len(items),
        "planned_only": True,
        "source_artifacts": [
            {
                "label": label,
                "path": display_path(root, path),
                "sha256": sha256_file(path),
            }
            for label, path in items
        ],
    }


def build_acceptance(
    root,
    job,
    stage,
    manifest_path,
    profile_path,
    report_path,
    request_path,
    compare_path,
    mode="shadow",
    write_request=True,
    prior_request=None,
    write_artifacts=True,
):
    inspected = inspect_acceptance_inputs(root, job, stage, manifest_path, profile_path)
    checks = inspected["checks"]
    inputs = inspected["inputs"]
    manifest = inspected["manifest"]
    profile = inspected["profile"]
    parts = inspected["parts"]
    support_refs = inspected["support_refs"]
    report = initial_report(job["id"], stage, checks, mode)
    attach_input_binding(report, root, inputs)
    if report["deterministic_preflight"]["overall"] != "PASS":
        if write_artifacts:
            request_path.unlink(missing_ok=True)
            write_json(report_path, report)
        return report

    families = select_families(root, manifest, manifest_path, parts, support_refs, profile)
    active_fingerprint = stable_hash(
        {
            "version": 1,
            "semantic_families": [
                {
                    "name": family["name"],
                    "fingerprint_hash": family["fingerprint_hash"],
                }
                for family in families
            ],
        }
    )
    compare_context = reusable_compare_context(
        root,
        request_path,
        compare_path,
        active_fingerprint,
        prior_request=prior_request,
    )
    compare_generation_count = 0
    if compare_context is None:
        if write_artifacts:
            compare_context = make_compare_context(root, parts, support_refs, compare_path)
            compare_generation_count = 1
        else:
            compare_context = planned_compare_context(root, parts, support_refs, compare_path)
    request = {
        "version": 1,
        "request_type": "storyboard_visual_acceptance",
        "job_id": job["id"],
        "stage": stage,
        "mode": mode,
        "required": True,
        "invocation_count": 1,
        "active_input_fingerprint": active_fingerprint,
        "deterministic_input_fingerprint": report["input_binding"]["fingerprint"],
        "canonical_compare_context": compare_context,
        "profile_expectations": profile_expectations(profile),
        "families": families,
    }
    request["request_id"] = stable_hash(request)
    if write_artifacts and write_request:
        write_json(request_path, request)
    report.update(
        {
            "overall": "STOP",
            "reason": "semantic review required",
            "semantic_family_selection": families,
            "canonical_compare_context": compare_context,
            "semantic_review": {
                "status": "REVIEW_REQUIRED",
                "request_path": display_path(root, request_path),
                "request_id": request["request_id"],
                "invocation_count": 1,
                "request_payload": request,
            },
            "metrics": {"compare_generation_count": compare_generation_count},
        }
    )
    if write_artifacts:
        write_json(report_path, report)
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Prepare one shadow-mode Storyboard Visual Acceptance request."
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--stage", default="image_batch_qc")
    parser.add_argument("--mode", choices=("shadow", "active"), default="shadow")
    parser.add_argument("--manifest")
    parser.add_argument("--out-json")
    parser.add_argument("--request-out")
    parser.add_argument("--compare-out")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    job = find_job(root, args.job_id)
    if job is None:
        parser.error(f"job not found: {args.job_id}")
    checks_dir = root / "output" / args.job_id / "checks"
    manifest_path = resolve_output(
        root,
        args.manifest,
        root / "output" / args.job_id / "visual-assets" / "approved_visual_manifest.json",
    )
    profile_path = (root / "output" / args.job_id / "product_profile.json").resolve()
    report_path = resolve_output(
        root,
        args.out_json,
        checks_dir / f"{args.stage}_storyboard_visual_acceptance.json",
    )
    request_path = resolve_output(
        root,
        args.request_out,
        checks_dir / f"{args.stage}_storyboard_visual_acceptance_request.json",
    )
    compare_path = resolve_output(
        root,
        args.compare_out,
        checks_dir / "storyboard_visual_acceptance_compare.jpg",
    )
    report = build_acceptance(
        root,
        job,
        args.stage,
        manifest_path,
        profile_path,
        report_path,
        request_path,
        compare_path,
        mode=args.mode,
    )
    print(
        json.dumps(
            {
                "overall": report["overall"],
                "deterministic_preflight": report["deterministic_preflight"]["overall"],
                "acceptance": display_path(root, report_path),
                "request": report["semantic_review"].get("request_path"),
                "compare": (report.get("canonical_compare_context") or {}).get("path"),
            },
            ensure_ascii=False,
        )
    )
    raise SystemExit(0 if report["deterministic_preflight"]["overall"] == "PASS" else 1)


if __name__ == "__main__":
    main()
