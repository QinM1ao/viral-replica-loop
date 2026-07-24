#!/usr/bin/env python3
import argparse
import csv
import json
import re
from pathlib import Path

from qc_input_binding import attach_input_binding, resolve_path as resolve_binding_path

from product_profile import (
    check_enabled,
    load_product_profile,
    optional_ref_roles,
    profile_requires_mud_contract,
    required_ref_roles,
    rule_summary,
)


IMAGE_CONTRACT_CANDIDATES = [
    "output/{job_id}/checks/{stage}_codex_imagegen_contract.json",
    "output/{job_id}/checks/codex_imagegen_contract.json",
    "output/{job_id}/image-batch/codex_imagegen_contract.json",
    "output/{job_id}/改图小样/codex_imagegen_contract.json",
    "output/{job_id}/codex_imagegen_contract.json",
]
VISUAL_MANIFEST_CANDIDATES = [
    "output/{job_id}/visual-assets/approved_visual_manifest.json",
    "output/{job_id}/seedance_web_final/manifests/approved_visual_manifest.json",
]
REQUIRED_SOURCE_CONTROLS = {"layout", "shot_order", "framing", "action_rhythm", "scene_family", "shot_labels"}
REQUIRED_SOURCE_EXCLUSIONS = {
    "old_product",
    "old_tool",
    "old_host_identity",
    "old_mud_color",
    "subtitles",
}
REQUIRED_REF_ROLES = {
    "source_storyboard",
    "product_front",
    "product_open_mud",
    "identity_ref",
}
OPTIONAL_REF_ROLES = {"afterwash_face"}
REQUIRED_REVIEW_FLAGS = {
    "layout_matches_source",
    "source_aspect_preserved",
    "same_identity_as_reference",
    "primary_identity_consistent",
    "primary_identity_only_on_target_role",
    "secondary_characters_keep_source_role_gender",
    "no_source_host_identity",
    "target_product_packaging",
    "target_product_label",
    "white_milky_thick_mud",
    "finger_or_fingertip_application",
    "no_tube_stick_brush_cotton_swatch",
    "no_arm_swatch",
    "no_old_product",
    "no_subtitles_or_text",
}
REQUIRED_BASELINE_SOURCES = {
    "matpool_gpt_image_2_edit",
    "matpool_gpt_image_2_edit_baseline",
}
ACCEPTED_IMAGE_ROUTES = {
    "matpool_gpt_image_2",
    "matpool_gpt_image_2_edit",
}
STORYBOARD_DERIVED_MODE = "storyboard_derived"
STORYBOARD_DERIVED_INITIAL_STRATEGY = "generate_from_source_roles_then_derive"
STORYBOARD_DERIVED_REUSE_STRATEGY = "reuse_storyboard_derived_roles"
REQUIRED_REF_ORDER_PREFIX = [
    "source_storyboard",
    "product_front",
    "product_open_mud",
    "identity_ref",
]
PROMPT_REQUIRED_GROUPS = [
    ("finger_application", [r"手指", r"指腹", r"\bfinger\b", r"\bfingertip\b", r"\bfingertips\b"]),
    ("open_jar", [r"罐", r"\bjar\b"]),
    ("white_thick_mud", [r"乳白", r"奶白", r"白色厚泥", r"白泥", r"milky[- ]white", r"white thick"]),
    ("target_product", [r"孔凤春", r"Kongfengchun", r"KOPHENIX"]),
]
PROMPT_FORBIDDEN_PATTERNS = [
    r"泥膜棒",
    r"棒状",
    r"刷头",
    r"管状",
    r"涂抹头",
    r"棉签",
    r"滚珠",
    r"手臂试色",
    r"前臂试色",
    r"\bapplicator\b",
    r"\bstick applicator\b",
    r"\bbrush head\b",
    r"\bcotton swab\b",
    r"\brollerball\b",
    r"\btube applicator\b",
    r"\barm swatch\b",
    r"\bforearm swatch\b",
]
TOOL_RISK_MARKERS = {
    "old_tool",
    "tube_applicator",
    "stick_applicator",
    "brush_head",
    "cotton_swab",
    "arm_swatch",
}
TONER_APPLICATION_METHODS = {
    "toner_pour_to_palm_and_pat_to_face",
    "toner_pour_or_pat_to_face",
    "pour_to_palm_and_pat_to_face",
}
TONER_PROMPT_REQUIRED_GROUPS = [
    ("toner_application", [r"轻拍", r"拍", r"倒", r"掌心", r"\bpat\b", r"\bpalm\b", r"\btoner\b"]),
    ("target_product", [r"孔凤春", r"发酵水", r"精华水", r"Kongfengchun", r"toner"]),
]


def status_rank(status):
    return {"PASS": 0, "FAIL": 1, "STOP": 2}.get(status, 2)


def resolve_path(root, raw, base=None):
    if raw is None:
        return None
    raw = str(raw).strip()
    if not raw:
        return None
    path = Path(raw)
    if path.is_absolute():
        return path
    if base is not None:
        candidate = base / path
        if candidate.exists():
            return candidate
    if raw.startswith(root.name + "/"):
        return root.parent / path
    return root / path


def display_path(root, path):
    if path is None:
        return ""
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except (FileNotFoundError, ValueError):
        return str(path)


def same_path(a, b):
    if a is None or b is None:
        return False
    try:
        return a.resolve() == b.resolve()
    except FileNotFoundError:
        return a.absolute() == b.absolute()


def is_under(child, parent):
    if child is None or parent is None:
        return False
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (FileNotFoundError, ValueError):
        try:
            child.absolute().relative_to(parent.absolute())
            return True
        except ValueError:
            return False


def load_json(path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def read_jobs(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def find_job(root, job_id):
    for row in read_jobs(root / "jobs.csv"):
        if row.get("id", "").strip() == job_id:
            return row
    return None


def add(checks, name, status, detail, **extra):
    item = {"name": name, "status": status, "detail": detail}
    item.update(extra)
    checks.append(item)
    return status == "PASS"


def contract_path(root, job_id, stage, explicit=None):
    if explicit:
        return resolve_path(root, explicit)
    for raw in IMAGE_CONTRACT_CANDIDATES:
        path = resolve_path(root, raw.format(job_id=job_id, stage=stage))
        if path and path.exists():
            return path
    return resolve_path(root, IMAGE_CONTRACT_CANDIDATES[0].format(job_id=job_id, stage=stage))


def visual_manifest_path(root, job_id):
    for raw in VISUAL_MANIFEST_CANDIDATES:
        path = resolve_path(root, raw.format(job_id=job_id))
        if path and path.exists():
            return path
    return None


def visual_manifest_part_paths(root, visual_manifest):
    paths = {}
    storyboards = visual_manifest.get("part_storyboards", {})
    if not isinstance(storyboards, dict):
        return paths
    for part, entry in storyboards.items():
        if isinstance(entry, dict):
            paths[str(part)] = resolve_path(root, entry.get("path", ""))
    return paths


def listish(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(item).strip() for item in str(value).replace(",", " ").split() if str(item).strip()]


def refs_map(refs):
    if isinstance(refs, dict):
        out = {}
        for key, value in refs.items():
            if isinstance(value, dict):
                out[str(key)] = value.get("path") or value.get("image") or value.get("file")
            else:
                out[str(key)] = value
        return out
    if isinstance(refs, list):
        out = {}
        for item in refs:
            if not isinstance(item, dict):
                continue
            role = item.get("role") or item.get("name")
            path = item.get("path") or item.get("image") or item.get("file")
            if role:
                out[str(role)] = path
        return out
    return {}


def refs_entries(refs):
    if isinstance(refs, dict):
        out = {}
        for role, value in refs.items():
            if isinstance(value, dict):
                entry = dict(value)
                entry.setdefault("role", str(role))
            else:
                entry = {"role": str(role), "path": value}
            out[str(role)] = entry
        return out
    if isinstance(refs, list):
        out = {}
        for item in refs:
            if not isinstance(item, dict):
                continue
            role = item.get("role") or item.get("name")
            if role:
                out[str(role)] = item
        return out
    return {}


def nested_get(obj, path, default=None):
    cur = obj
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def truthy(value):
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "y", "1", "是"}
    return False


def iter_values(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from iter_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_values(item)
    else:
        yield value


def collect_paths(root, value):
    paths = []
    for item in iter_values(value):
        if not isinstance(item, str):
            continue
        if "/" not in item and "\\" not in item:
            continue
        path = resolve_path(root, item)
        if path:
            paths.append(path)
    return paths


def invocation_ref_lists(invocation):
    lists = []
    for key in (
        "references_loaded_before_call",
        "source_images_loaded_before_generation",
        "actual_images_loaded_before_generation",
        "actual_refs_loaded_before_generation",
        "actual_image_refs_loaded_before_generation",
        "loaded_reference_paths",
        "refs_loaded",
    ):
        value = invocation.get(key)
        if isinstance(value, (list, dict)):
            lists.append(value)
    return lists


def has_attachment_flag(invocation):
    for key in (
        "inputs_attached_or_loaded",
        "actual_image_inputs_loaded",
        "loaded_via_view_image_before_imagegen",
        "local_inputs_loaded_with_view_image",
    ):
        if truthy(invocation.get(key)):
            return True
    return False


def baseline_obj(contract):
    baseline = contract.get("api_effect_baseline") or contract.get("api_baseline") or {}
    if isinstance(baseline, str):
        return {"source": baseline}
    if isinstance(baseline, dict):
        return baseline
    return {}


def reference_order(contract, part=None):
    values = []
    if part:
        values.extend([
            part.get("codex_reference_order"),
            part.get("api_reference_order"),
            part.get("reference_order"),
            nested_get(part, ["codex_generation_settings", "reference_order"]),
            nested_get(part, ["api_effect_baseline", "reference_order"]),
        ])
    values.extend([
        contract.get("codex_reference_order"),
        contract.get("api_reference_order"),
        contract.get("reference_order"),
        nested_get(contract, ["codex_generation_settings", "reference_order"]),
        nested_get(contract, ["api_effect_baseline", "reference_order"]),
    ])
    for value in values:
        order = listish(value)
        if order:
            return order
    return []


def generation_settings(contract, part=None):
    merged = {}
    for source in [
        contract.get("codex_generation_settings"),
        contract.get("generation_settings"),
        nested_get(contract, ["api_effect_baseline", "generation_settings"]),
    ]:
        if isinstance(source, dict):
            merged.update(source)
    if part:
        for source in [
            part.get("codex_generation_settings"),
            part.get("generation_settings"),
            nested_get(part, ["api_effect_baseline", "generation_settings"]),
        ]:
            if isinstance(source, dict):
                merged.update(source)
    for key in ("quality", "resolution", "ratio"):
        if part and part.get(key) is not None:
            merged[key] = part.get(key)
        if contract.get(key) is not None:
            merged.setdefault(key, contract.get(key))
    return merged


def check_api_baseline_contract(checks, contract):
    baseline = baseline_obj(contract)
    source = str(baseline.get("source") or "").strip()
    add(
        checks,
        "api_effect_baseline_source",
        "PASS" if source in REQUIRED_BASELINE_SOURCES else "FAIL",
        f"source={source!r} required={sorted(REQUIRED_BASELINE_SOURCES)}",
    )
    preserve = baseline.get("preserve_api_route")
    if preserve is None:
        preserve = contract.get("preserve_api_route")
    add(
        checks,
        "api_effect_baseline_preserve_api_route",
        "PASS" if truthy(preserve) else "FAIL",
        f"preserve_api_route={preserve!r}",
    )
    add(
        checks,
        "matpool_uses_real_image_inputs",
        "PASS" if truthy(contract.get("matpool_uses_real_image_inputs") or contract.get("codex_must_match_api_inputs")) else "FAIL",
        (
            f"matpool_uses_real_image_inputs={contract.get('matpool_uses_real_image_inputs')!r} "
            f"codex_must_match_api_inputs={contract.get('codex_must_match_api_inputs')!r}"
        ),
    )


def part_id(part):
    raw = str(part.get("part") or part.get("id") or "").strip().lower()
    if raw:
        if re.fullmatch(r"\d+", raw):
            return f"part{raw}"
        match = re.fullmatch(r"part\s*[-_ ]?\s*(\d+)", raw)
        if match:
            return f"part{match.group(1)}"
        return raw
    index = part.get("index")
    if index is not None:
        return f"part{index}"
    return ""


def read_prompt_text(root, contract_file, part):
    prompt_text = str(part.get("prompt_text") or "").strip()
    prompt_path = resolve_path(root, part.get("prompt_path") or part.get("prompt"), base=contract_file.parent)
    if prompt_path and prompt_path.exists():
        prompt_text = prompt_path.read_text(encoding="utf-8")
    return prompt_text, prompt_path


def has_any_pattern(text, patterns):
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def pattern_hits(text, patterns):
    return [pattern for pattern in patterns if re.search(pattern, text, flags=re.IGNORECASE)]


def report_overall(checks):
    worst = max((status_rank(c["status"]) for c in checks), default=2)
    for status, rank in {"PASS": 0, "FAIL": 1, "STOP": 2}.items():
        if rank == worst:
            return status
    return "STOP"


def check_source_contract(checks, contract, product_profile):
    required_controls = set(product_profile.get("source_storyboard_controls") or REQUIRED_SOURCE_CONTROLS)
    required_exclusions = set(product_profile.get("source_storyboard_must_not_control") or REQUIRED_SOURCE_EXCLUSIONS)
    controls = set(listish(contract.get("source_storyboard_controls")))
    exclusions = set(listish(contract.get("source_storyboard_must_not_control")))
    add(
        checks,
        "source_storyboard_controls_contract",
        "PASS" if required_controls.issubset(controls) else "FAIL",
        f"required={sorted(required_controls)} actual={sorted(controls)}",
    )
    add(
        checks,
        "source_storyboard_exclusion_contract",
        "PASS" if required_exclusions.issubset(exclusions) else "FAIL",
        f"required={sorted(required_exclusions)} actual={sorted(exclusions)}",
    )


def prompt_required_groups(product_profile):
    groups = product_profile.get("prompt_required_groups", [])
    normalized = []
    for group in groups:
        if isinstance(group, dict) and group.get("name"):
            patterns = [str(item) for item in group.get("patterns", []) if str(item)]
            if patterns:
                normalized.append((str(group["name"]), patterns))
    if normalized:
        return normalized
    return PROMPT_REQUIRED_GROUPS if profile_requires_mud_contract(product_profile) else TONER_PROMPT_REQUIRED_GROUPS


def check_prompt(checks, prompt_text, label, product_profile):
    add(
        checks,
        f"{label}_prompt_text_present",
        "PASS" if prompt_text.strip() else "STOP",
        f"chars={len(prompt_text.strip())}",
    )
    if not prompt_text.strip():
        return
    for name, patterns in prompt_required_groups(product_profile):
        add(
            checks,
            f"{label}_prompt_requires_{name}",
            "PASS" if has_any_pattern(prompt_text, patterns) else "FAIL",
            f"patterns={patterns}",
        )
    hits = pattern_hits(prompt_text, PROMPT_FORBIDDEN_PATTERNS)
    add(
        checks,
        f"{label}_prompt_no_old_tool_anchor_words",
        "PASS" if not hits else "FAIL",
        f"forbidden_hits={hits}",
    )


def check_review_flags(
    checks,
    review,
    label,
    product_profile,
    storyboard_derived_initial=False,
):
    if not isinstance(review, dict):
        add(checks, f"{label}_review_object", "STOP", "missing or not object")
        return
    required_flags = set(product_profile.get("review_flags", {}).get("required", []))
    if not required_flags:
        required_flags = set(REQUIRED_REVIEW_FLAGS)
    if storyboard_derived_initial:
        required_flags.discard("same_identity_as_reference")
        required_flags.update(
            {
                "new_people_are_photoreal",
                "source_role_gender_preserved",
                "same_role_repeats_consistently",
            }
        )
    missing = sorted(flag for flag in required_flags if flag not in review)
    add(
        checks,
        f"{label}_review_required_flags",
        "PASS" if not missing else "FAIL",
        f"missing={missing}",
    )
    false_flags = sorted(flag for flag in required_flags if review.get(flag) is not True)
    add(
        checks,
        f"{label}_review_flags_true",
        "PASS" if not false_flags else "FAIL",
        f"not_true={false_flags}",
    )


def check_part_refs(
    root,
    checks,
    contract_file,
    part,
    label,
    product_profile,
    required_roles=None,
):
    refs = refs_map(part.get("refs_loaded") or part.get("refs") or part.get("reference_images"))
    required_roles = set(required_roles or required_ref_roles(product_profile))
    optional_roles = optional_ref_roles(product_profile)
    missing_roles = sorted(role for role in required_roles if not refs.get(role))
    add(
        checks,
        f"{label}_required_ref_roles",
        "PASS" if not missing_roles else "FAIL",
        f"missing={missing_roles}",
    )
    for role in sorted(required_roles | optional_roles):
        raw = refs.get(role)
        if not raw:
            continue
        path = resolve_path(root, raw, base=contract_file.parent)
        add(
            checks,
            f"{label}_ref_{role}_exists",
            "PASS" if path and path.exists() else "STOP",
            display_path(root, path),
        )
    return refs


def check_ref_loading_evidence(
    root,
    checks,
    contract_file,
    contract,
    part,
    refs,
    label,
    product_profile,
    required_roles=None,
):
    entries = refs_entries(part.get("refs_loaded") or part.get("refs") or part.get("reference_images"))
    required_roles = set(required_roles or required_ref_roles(product_profile))
    missing_loaded_flags = sorted(
        role for role in required_roles
        if not truthy(entries.get(role, {}).get("loaded_to_context"))
    )
    if not missing_loaded_flags:
        add(
            checks,
            f"{label}_actual_image_inputs_loaded",
            "PASS",
            "all required refs have loaded_to_context=true in contract",
        )
        return

    invocation_paths = [
        part.get("invocation_manifest"),
        part.get("imagegen_invocation_manifest"),
        contract.get("invocation_manifest"),
        contract.get("imagegen_invocation_manifest"),
    ]
    if part.get("refs_manifest"):
        invocation_paths.append(part.get("refs_manifest"))
    invocations = []
    loaded_files = []
    for raw in invocation_paths:
        path = resolve_path(root, raw, base=contract_file.parent)
        if not path or not path.exists() or path in loaded_files:
            continue
        try:
            invocations.append(load_json(path))
            loaded_files.append(path)
        except json.JSONDecodeError:
            continue

    evidence_paths = []
    has_attached_flag = False
    for invocation in invocations:
        has_attached_flag = has_attached_flag or has_attachment_flag(invocation)
        for ref_list in invocation_ref_lists(invocation):
            evidence_paths.extend(collect_paths(root, ref_list))

    missing_paths = []
    for role in required_roles:
        raw = refs.get(role)
        ref_path = resolve_path(root, raw, base=contract_file.parent)
        if not ref_path:
            missing_paths.append(role)
            continue
        if not any(same_path(ref_path, candidate) for candidate in evidence_paths):
            missing_paths.append(role)

    passed = not missing_paths and (has_attached_flag or bool(evidence_paths))
    add(
        checks,
        f"{label}_actual_image_inputs_loaded",
        "PASS" if passed else "FAIL",
        (
            f"invocation_files={[display_path(root, p) for p in loaded_files]} "
            f"has_attached_flag={has_attached_flag} missing_loaded_ref_paths={missing_paths}"
        ),
    )


def translation_groups(product_profile):
    groups = product_profile.get("tool_risk_translation_groups", [])
    out = []
    for group in groups:
        if isinstance(group, dict) and group.get("name"):
            patterns = [str(item) for item in group.get("patterns", []) if str(item)]
            if patterns:
                out.append((str(group["name"]), patterns))
    return out


def check_required_translation(checks, part, label, product_profile):
    risks = set(listish(part.get("source_risks") or part.get("old_source_risks")))
    translations = part.get("required_translations") or []
    if not isinstance(translations, list):
        translations = []
    needs_translation = bool(risks.intersection(TOOL_RISK_MARKERS))
    if not needs_translation:
        add(checks, f"{label}_tool_risk_translation", "PASS", "no old tool risk declared")
        return
    haystack = json.dumps(translations, ensure_ascii=False)
    groups = translation_groups(product_profile)
    if not groups:
        add(checks, f"{label}_tool_risk_translation", "PASS", "no category-specific translation group required")
        return
    missing = [name for name, patterns in groups if not has_any_pattern(haystack, patterns)]
    add(checks, f"{label}_tool_risk_translation", "PASS" if not missing else "FAIL", f"missing={missing} translations={haystack}")


def check_reference_order(
    checks,
    contract,
    part,
    label,
    product_profile,
    required_prefix=None,
):
    order = reference_order(contract, part)
    required_prefix = list(
        required_prefix
        or product_profile.get("reference_roles", {}).get("order_prefix", [])
        or REQUIRED_REF_ORDER_PREFIX
    )
    preserves_required_order = False
    if required_prefix and order and order[0] == required_prefix[0]:
        index = 0
        for role in order:
            if index < len(required_prefix) and role == required_prefix[index]:
                index += 1
        preserves_required_order = index == len(required_prefix)
    add(
        checks,
        f"{label}_reference_order_matches_api_baseline",
        "PASS" if preserves_required_order else "FAIL",
        f"required_prefix={required_prefix} actual={order}",
    )


def storyboard_derived_contract_state(root, job, contract, contract_file, part, refs):
    job_mode = str(job.get("person_assets", "")).strip()
    contract_mode = str(contract.get("person_asset_mode", "")).strip()
    part_mode = str(part.get("person_asset_mode", contract_mode)).strip()
    strategy = str(part.get("identity_strategy", contract.get("identity_strategy", ""))).strip()
    derived_roles = [role for role in refs if str(role).startswith("identity_role_")]
    lacks_identity = not refs.get("identity_ref") and not derived_roles
    initial_claim = strategy == STORYBOARD_DERIVED_INITIAL_STRATEGY
    initial_candidate = job_mode == STORYBOARD_DERIVED_MODE and lacks_identity
    role_map = resolve_path(root, part.get("role_map"), base=contract_file.parent)
    role_map_ready = bool(
        role_map
        and role_map.exists()
        and truthy(part.get("role_map_loaded_to_context"))
    )
    initial_ok = bool(
        initial_candidate
        and contract_mode == STORYBOARD_DERIVED_MODE
        and part_mode == STORYBOARD_DERIVED_MODE
        and initial_claim
        and role_map_ready
    )
    reuse_ok = bool(
        job_mode == STORYBOARD_DERIVED_MODE
        and contract_mode == STORYBOARD_DERIVED_MODE
        and part_mode == STORYBOARD_DERIVED_MODE
        and strategy == STORYBOARD_DERIVED_REUSE_STRATEGY
        and derived_roles
    )
    return {
        "initial_candidate": initial_candidate,
        "initial_ok": initial_ok,
        "reuse_ok": reuse_ok,
        "strategy": strategy,
        "role_map": role_map,
        "role_map_ready": role_map_ready,
        "derived_roles": derived_roles,
    }


def check_generation_settings(checks, contract, part, label):
    settings = generation_settings(contract, part)
    quality = str(settings.get("quality") or "").strip().lower()
    resolution = str(settings.get("resolution") or "").strip().lower()
    ratio = settings.get("ratio")
    ratio_source = settings.get("ratio_source") or settings.get("expected_ratio_from_image")
    add(
        checks,
        f"{label}_quality_matches_api_baseline",
        "PASS" if quality == "medium" else "FAIL",
        f"quality={settings.get('quality')!r}",
    )
    add(
        checks,
        f"{label}_resolution_matches_api_baseline",
        "PASS" if resolution in {"1k", "1024", "1024px"} else "FAIL",
        f"resolution={settings.get('resolution')!r}",
    )
    add(
        checks,
        f"{label}_ratio_declared",
        "PASS" if ratio or ratio_source else "FAIL",
        f"ratio={ratio!r} ratio_source={ratio_source!r}",
    )


def build_report(root, job_id, stage, explicit_contract=None, explicit_manifest=None):
    checks = []
    job = find_job(root, job_id)
    add(checks, "job_exists", "PASS" if job else "STOP", job_id)
    if not job:
        return {"overall": report_overall(checks), "job_id": job_id, "stage": stage, "checks": checks, "inputs": {}}

    product_profile, product_profile_file, product_profile_exists = load_product_profile(root, job)
    add(checks, "product_profile_exists", "PASS" if product_profile_exists else "STOP", display_path(root, product_profile_file))
    add(
        checks,
        "product_profile_loads_generic_rule",
        "PASS" if "generic:generic_product" in product_profile.get("loaded_rules", []) else "FAIL",
        json.dumps(rule_summary(product_profile), ensure_ascii=False),
    )

    cpath = contract_path(root, job_id, stage, explicit_contract)
    add(checks, "codex_imagegen_contract_exists", "PASS" if cpath and cpath.exists() else "STOP", display_path(root, cpath))
    if not cpath or not cpath.exists():
        return {
            "overall": report_overall(checks),
            "job_id": job_id,
            "stage": stage,
            "contract_path": display_path(root, cpath),
            "checks": checks,
            "inputs": {"job": job, "product_profile": product_profile},
        }

    contract = load_json(cpath)
    add(
        checks,
        "contract_job_id",
        "PASS" if contract.get("job_id") == job_id else "FAIL",
        f"contract={contract.get('job_id')} expected={job_id}",
    )
    add(
        checks,
        "contract_stage",
        "PASS" if str(contract.get("stage", stage)).strip() == stage else "FAIL",
        f"contract={contract.get('stage')} expected={stage}",
    )
    image_route = str(contract.get("image_route") or contract.get("route") or "").strip()
    route_ok = image_route in ACCEPTED_IMAGE_ROUTES
    add(
        checks,
        "contract_route_edit_reference",
        "PASS" if route_ok else "FAIL",
        (
            f"route={image_route!r} accepted={sorted(ACCEPTED_IMAGE_ROUTES)} "
            f"fallback_route_used={contract.get('fallback_route_used')!r}"
        ),
    )
    method = str(contract.get("target_application_method", ""))
    if check_enabled(product_profile, "requires_finger_jar_application"):
        add(
            checks,
            "profile_application_method",
            "PASS" if method == "finger_from_open_jar_to_face" else "FAIL",
            f"actual={method} expected=finger_from_open_jar_to_face",
        )
    elif product_profile.get("category_id") == "toner":
        add(
            checks,
            "profile_application_method",
            "PASS" if method in TONER_APPLICATION_METHODS else "FAIL",
            f"actual={method} expected={sorted(TONER_APPLICATION_METHODS)}",
        )
    else:
        add(checks, "profile_application_method", "PASS", f"category={product_profile.get('category_id', 'unknown')}")
    check_api_baseline_contract(checks, contract)
    check_source_contract(checks, contract, product_profile)

    visual_file = resolve_path(root, explicit_manifest) if explicit_manifest else visual_manifest_path(root, job_id)
    visual_manifest = {}
    manifest_part_paths = {}
    if visual_file and visual_file.exists():
        visual_manifest = load_json(visual_file)
        manifest_part_paths = visual_manifest_part_paths(root, visual_manifest)
        add(checks, "approved_visual_manifest_exists", "PASS", display_path(root, visual_file))
    else:
        add(checks, "approved_visual_manifest_exists", "STOP", "missing")

    parts = contract.get("parts")
    if not isinstance(parts, list) or not parts:
        add(checks, "contract_parts_present", "STOP", "missing or empty")
    else:
        add(checks, "contract_parts_present", "PASS", f"count={len(parts)}")

    job_dir = root / "output" / job_id
    for index, part in enumerate(parts or [], start=1):
        if not isinstance(part, dict):
            add(checks, f"part{index}_object", "FAIL", "part is not an object")
            continue
        pid = part_id(part) or f"part{index}"
        label = re.sub(r"[^a-zA-Z0-9_]+", "_", pid)
        source = resolve_path(root, part.get("source_storyboard"), base=cpath.parent)
        candidate = resolve_path(root, part.get("candidate_path") or part.get("candidate"), base=cpath.parent)
        add(checks, f"{label}_source_storyboard_exists", "PASS" if source and source.exists() else "STOP", display_path(root, source))
        add(checks, f"{label}_candidate_exists", "PASS" if candidate and candidate.exists() else "STOP", display_path(root, candidate))
        add(
            checks,
            f"{label}_candidate_under_job",
            "PASS" if candidate and is_under(candidate, job_dir) else "FAIL",
            display_path(root, candidate),
        )
        expected_candidate = manifest_part_paths.get(pid)
        if expected_candidate:
            add(
                checks,
                f"{label}_candidate_matches_visual_manifest",
                "PASS" if same_path(candidate, expected_candidate) else "FAIL",
                f"candidate={display_path(root, candidate)} manifest={display_path(root, expected_candidate)}",
            )
        else:
            add(checks, f"{label}_candidate_in_visual_manifest", "FAIL", f"part={pid}")
        raw_refs = refs_map(part.get("refs_loaded") or part.get("refs") or part.get("reference_images"))
        identity_state = storyboard_derived_contract_state(
            root,
            job,
            contract,
            cpath,
            part,
            raw_refs,
        )
        if identity_state["initial_candidate"]:
            add(
                checks,
                f"{label}_storyboard_derived_initial_edit",
                "PASS" if identity_state["initial_ok"] else "FAIL",
                (
                    f"strategy={identity_state['strategy']} "
                    f"role_map={display_path(root, identity_state['role_map'])} "
                    f"role_map_loaded={identity_state['role_map_ready']}"
                ),
            )
        if identity_state["derived_roles"]:
            add(
                checks,
                f"{label}_storyboard_derived_identity_reuse",
                "PASS" if identity_state["reuse_ok"] else "FAIL",
                (
                    f"strategy={identity_state['strategy']} "
                    f"roles={identity_state['derived_roles']}"
                ),
            )

        required_roles = set(required_ref_roles(product_profile))
        required_prefix = list(
            product_profile.get("reference_roles", {}).get("order_prefix", [])
            or REQUIRED_REF_ORDER_PREFIX
        )
        if identity_state["initial_ok"]:
            required_roles.discard("identity_ref")
            required_prefix = [role for role in required_prefix if role != "identity_ref"]
        elif identity_state["reuse_ok"]:
            required_roles.discard("identity_ref")
            required_roles.update(identity_state["derived_roles"])
            replacement_prefix = []
            for role in required_prefix:
                if role == "identity_ref":
                    replacement_prefix.extend(identity_state["derived_roles"])
                else:
                    replacement_prefix.append(role)
            required_prefix = replacement_prefix

        refs = check_part_refs(
            root,
            checks,
            cpath,
            part,
            label,
            product_profile,
            required_roles,
        )
        check_ref_loading_evidence(
            root,
            checks,
            cpath,
            contract,
            part,
            refs,
            label,
            product_profile,
            required_roles,
        )
        check_reference_order(
            checks,
            contract,
            part,
            label,
            product_profile,
            required_prefix,
        )
        check_generation_settings(checks, contract, part, label)
        prompt_text, prompt_path = read_prompt_text(root, cpath, part)
        add(
            checks,
            f"{label}_prompt_path_exists",
            "PASS" if prompt_path and prompt_path.exists() else ("PASS" if prompt_text else "STOP"),
            display_path(root, prompt_path),
        )
        check_prompt(checks, prompt_text, label, product_profile)
        check_required_translation(checks, part, label, product_profile)
        check_review_flags(
            checks,
            part.get("review") or part.get("checker_visual_review"),
            label,
            product_profile,
            identity_state["initial_ok"],
        )

    return {
        "overall": report_overall(checks),
        "job_id": job_id,
        "stage": stage,
        "contract_path": display_path(root, cpath),
        "visual_manifest_path": display_path(root, visual_file),
        "checks": checks,
        "inputs": {
            "job": job,
            "product_profile": product_profile,
            "contract": contract,
            "visual_manifest": visual_manifest,
        },
    }


def write_md(path, report):
    lines = [
        "# GPT Image Contract QC",
        "",
        f"- Overall: **{report['overall']}**",
        f"- Job: `{report['job_id']}`",
        f"- Stage: `{report['stage']}`",
        f"- Contract: `{report.get('contract_path', '')}`",
        f"- Visual manifest: `{report.get('visual_manifest_path', '')}`",
        "",
        "## Checks",
        "",
    ]
    for check in report["checks"]:
        lines.append(f"- {check['status']}: `{check['name']}` - {check['detail']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Validate GPT Image edit/reference contract evidence.")
    parser.add_argument("--root", default=".", help="Loop root directory.")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--stage", default="image_batch_qc")
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--out-json", type=Path)
    parser.add_argument("--out-md", type=Path)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    default_dir = root / "output" / args.job_id / "checks"
    out_json = args.out_json or default_dir / f"{args.stage}_codex_imagegen_contract_qc.json"
    out_md = args.out_md or default_dir / f"{args.stage}_codex_imagegen_contract_qc.md"
    report = build_report(root, args.job_id, args.stage, args.contract, args.manifest)
    attach_input_binding(
        report,
        root,
        [
            resolve_binding_path(root, report.get("contract_path")),
            resolve_binding_path(root, report.get("visual_manifest_path")),
        ],
    )
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_md(out_md, report)
    print(report["overall"])


if __name__ == "__main__":
    main()
