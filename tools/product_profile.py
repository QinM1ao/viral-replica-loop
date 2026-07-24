#!/usr/bin/env python3
import argparse
import csv
import json
import re
from pathlib import Path


PROFILE_CANDIDATES = [
    "output/{job_id}/product_profile.json",
    "output/{job_id}/visual-assets/product_profile.json",
]

RULES_ROOT = Path("rules/product-profiles")
GENERIC_RULE_ID = "generic_product"


def _read_json(path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_jobs(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def find_job(root, job_id):
    for row in read_jobs(root / "jobs.csv"):
        if row.get("id", "").strip() == job_id:
            return row
    return None


def profile_path(root, job_id, explicit=None):
    if explicit:
        path = Path(explicit)
        return path if path.is_absolute() else root / path
    for raw in PROFILE_CANDIDATES:
        path = root / raw.format(job_id=job_id)
        if path.exists():
            return path
    return root / PROFILE_CANDIDATES[0].format(job_id=job_id)


def rule_file(root, scope, rule_id):
    folders = {
        "generic": RULES_ROOT,
        "category": RULES_ROOT / "categories",
        "brand": RULES_ROOT / "brands",
        "sku": RULES_ROOT / "skus",
    }
    return root / folders[scope] / f"{rule_id}.json"


def load_rule(root, scope, rule_id):
    path = rule_file(root, scope, rule_id)
    if path.exists():
        return _read_json(path)
    return {}


def merge_unique(*groups):
    out = []
    seen = set()
    for group in groups:
        for item in group or []:
            key = json.dumps(item, ensure_ascii=False, sort_keys=True) if isinstance(item, dict) else str(item)
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
    return out


def merge_prompt_groups(*groups):
    by_name = {}
    order = []
    for group_list in groups:
        for group in group_list or []:
            if not isinstance(group, dict) or not group.get("name"):
                continue
            name = str(group["name"])
            if name not in by_name:
                by_name[name] = {"name": name, "patterns": []}
                order.append(name)
            by_name[name]["patterns"] = merge_unique(by_name[name].get("patterns", []), group.get("patterns", []))
    return [by_name[name] for name in order if by_name[name].get("patterns")]


def merge_dicts(*groups):
    out = {}
    for group in groups:
        if isinstance(group, dict):
            out.update(group)
    return out


def product_terms(product_name):
    terms = []
    value = str(product_name or "").strip()
    if value:
        terms.append(re.escape(value))
    for token in re.split(r"[\s,，/|]+", value):
        token = token.strip()
        if len(token) >= 2:
            terms.append(re.escape(token))
    return merge_unique(terms)


def infer_brand(job):
    product_name = str(job.get("product_name", ""))
    client_profile = str(job.get("client_profile", ""))
    notes = str(job.get("notes", ""))
    if client_profile == "kongfengchun" or "孔凤春" in product_name or "client_profile=kongfengchun" in notes:
        return "kongfengchun"
    return ""


def infer_category(job):
    text = " ".join(str(job.get(key, "")) for key in ("product_name", "notes")).lower()
    if re.search(r"(发酵水|精华水|爽肤水|化妆水|\btoner\b|\bessence toner\b)", text, re.IGNORECASE):
        return "toner", 0.95, "matched_toner_terms"
    if re.search(r"(清洁泥膜|泥膜|\bclay[- ]?mask\b|\bmud[- ]?mask\b)", text, re.IGNORECASE):
        return "clay_mask", 0.95, "matched_clay_mask_terms"
    return "unknown", 0.0, "no_confident_category_match"


def infer_sku(job, brand_id, category_id):
    product_name = str(job.get("product_name", ""))
    if brand_id == "kongfengchun" and category_id == "toner" and "发酵水" in product_name:
        return "kongfengchun_fermented_toner"
    if brand_id == "kongfengchun" and category_id == "clay_mask" and "泥膜" in product_name:
        return "kongfengchun_clean_mud_mask"
    return ""


def combine_checks(*rules):
    merged = {}
    for rule in rules:
        merged.update(rule.get("checks", {}) if isinstance(rule, dict) else {})
    return merged


def build_product_profile(root, job):
    brand_id = infer_brand(job)
    category_id, confidence, reason = infer_category(job)
    if confidence < 0.8:
        category_id = "unknown"
    sku_id = infer_sku(job, brand_id, category_id)

    generic_rule = load_rule(root, "generic", GENERIC_RULE_ID)
    category_rule = load_rule(root, "category", category_id) if category_id != "unknown" else {}
    brand_rule = load_rule(root, "brand", brand_id) if brand_id else {}
    sku_rule = load_rule(root, "sku", sku_id) if sku_id else {}

    loaded_rules = [f"generic:{GENERIC_RULE_ID}"]
    if category_rule:
        loaded_rules.append(f"category:{category_id}")
    if brand_rule:
        loaded_rules.append(f"brand:{brand_id}")
    if sku_rule:
        loaded_rules.append(f"sku:{sku_id}")

    product_name = str(job.get("product_name", "")).strip()
    prompt_groups = merge_prompt_groups(
        generic_rule.get("prompt_required_groups", []),
        category_rule.get("prompt_required_groups", []),
        sku_rule.get("prompt_required_groups", []),
    )
    visible_text_patterns = merge_unique(
        generic_rule.get("visible_text_patterns", []),
        category_rule.get("visible_text_patterns", []),
        brand_rule.get("visible_text_patterns", []),
        sku_rule.get("visible_text_patterns", []),
    )
    if visible_text_patterns:
        prompt_groups = merge_prompt_groups(
            prompt_groups,
            [{"name": "visible_product_text", "patterns": visible_text_patterns}],
        )
    for group in prompt_groups:
        if isinstance(group, dict) and group.get("name") == "target_product":
            group["patterns"] = merge_unique(group.get("patterns", []), product_terms(product_name))

    checks = combine_checks(generic_rule, category_rule, brand_rule, sku_rule)
    required_refs = merge_unique(
        generic_rule.get("required_ref_roles", []),
        category_rule.get("required_ref_roles", []),
        sku_rule.get("required_ref_roles", []),
    )
    optional_refs = merge_unique(
        generic_rule.get("optional_ref_roles", []),
        category_rule.get("optional_ref_roles", []),
        sku_rule.get("optional_ref_roles", []),
    )
    required_flags = merge_unique(
        generic_rule.get("required_review_flags", []),
        category_rule.get("required_review_flags", []),
        sku_rule.get("required_review_flags", []),
    )
    if visible_text_patterns:
        required_flags = merge_unique(required_flags, ["product_visible_text", "no_blank_label"])
    ref_order = (
        sku_rule.get("reference_order_prefix")
        or category_rule.get("reference_order_prefix")
        or generic_rule.get("reference_order_prefix")
        or []
    )
    tool_translation_groups = merge_unique(
        category_rule.get("tool_risk_translation_groups", []),
        sku_rule.get("tool_risk_translation_groups", []),
    )
    character_policy = merge_dicts(
        generic_rule.get("character_policy", {}),
        category_rule.get("character_policy", {}),
        brand_rule.get("character_policy", {}),
        sku_rule.get("character_policy", {}),
    )
    label_review_policy = merge_dicts(
        generic_rule.get("label_review_policy", {}),
        category_rule.get("label_review_policy", {}),
        brand_rule.get("label_review_policy", {}),
        sku_rule.get("label_review_policy", {}),
    )

    return {
        "version": 1,
        "job_id": job.get("id", ""),
        "product_name": product_name,
        "brand_id": brand_id,
        "category_id": category_id,
        "sku_id": sku_id,
        "classification": {
            "category_confidence": confidence,
            "category_reason": reason,
            "brand_source": "client_profile_or_product_name" if brand_id else "none",
        },
        "loaded_rules": loaded_rules,
        "reference_roles": {
            "required": required_refs,
            "optional": optional_refs,
            "order_prefix": ref_order,
        },
        "review_flags": {
            "required": required_flags,
        },
        "checks": checks,
        "prompt_required_groups": prompt_groups,
        "visible_text_patterns": visible_text_patterns,
        "label_review_policy": label_review_policy,
        "character_policy": character_policy,
        "tool_risk_translation_groups": tool_translation_groups,
        "source_storyboard_controls": generic_rule.get("source_storyboard_controls", []),
        "source_storyboard_must_not_control": generic_rule.get("source_storyboard_must_not_control", []),
        "usage_action": (
            sku_rule.get("usage_action")
            or category_rule.get("usage_action")
            or generic_rule.get("usage_action")
            or "replace source action with the current product's real usage action"
        ),
    }


def load_product_profile(root, job, explicit=None, create_if_missing=False):
    root = Path(root).resolve()
    path = profile_path(root, job.get("id", ""), explicit)
    exists = path.exists()
    if exists:
        profile = _read_json(path)
    else:
        profile = build_product_profile(root, job)
        if create_if_missing:
            _write_json(path, profile)
            exists = True
    profile.setdefault("job_id", job.get("id", ""))
    profile.setdefault("product_name", job.get("product_name", ""))
    return profile, path, exists


def write_product_profile(root, job, explicit=None):
    root = Path(root).resolve()
    profile = build_product_profile(root, job)
    path = profile_path(root, job.get("id", ""), explicit)
    _write_json(path, profile)
    return profile, path


def check_enabled(profile, key):
    return bool((profile or {}).get("checks", {}).get(key, False))


def required_ref_roles(profile):
    return set((profile or {}).get("reference_roles", {}).get("required", []))


def optional_ref_roles(profile):
    return set((profile or {}).get("reference_roles", {}).get("optional", []))


def profile_requires_afterwash_ref(profile):
    return "afterwash_face" in required_ref_roles(profile) or check_enabled(profile, "requires_afterwash_ref")


def profile_requires_mud_contract(profile):
    return check_enabled(profile, "requires_mud_checks")


def profile_requires_skincare_progression(profile):
    return check_enabled(profile, "requires_skincare_progression")


def rule_summary(profile):
    return {
        "profile_job_id": (profile or {}).get("job_id", ""),
        "brand_id": (profile or {}).get("brand_id", ""),
        "category_id": (profile or {}).get("category_id", "unknown"),
        "sku_id": (profile or {}).get("sku_id", ""),
        "loaded_rules": (profile or {}).get("loaded_rules", []),
    }


def main():
    parser = argparse.ArgumentParser(description="Create or inspect profile-driven product rules for loop jobs.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--job-id", action="append", default=[])
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    jobs = read_jobs(root / "jobs.csv")
    selected = set(args.job_id)
    if args.all:
        selected = {job.get("id", "") for job in jobs}
    if not selected:
        raise SystemExit("Provide --job-id or --all")

    out = []
    for job in jobs:
        if job.get("id", "") not in selected:
            continue
        profile, path = write_product_profile(root, job) if args.write else load_product_profile(root, job)[:2]
        out.append({"job_id": job.get("id", ""), "path": str(path), **rule_summary(profile)})
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
