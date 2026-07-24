#!/usr/bin/env python3
import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

from qc_input_binding import attach_input_binding, resolve_path as resolve_binding_path

from product_profile import load_product_profile, profile_requires_afterwash_ref, required_ref_roles, rule_summary


VALID_STORYBOARD_TYPE = "AI改好分镜图"
VALID_IMAGE_ROUTES = {"matpool_gpt_image_2_edit"}
VISUAL_MANIFEST_CANDIDATES = [
    "output/{job_id}/visual-assets/approved_visual_manifest.json",
    "output/{job_id}/approved_visual_manifest.json",
    "output/{job_id}/seedance/approved_visual_manifest.json",
    "output/{job_id}/checks/approved_visual_manifest.json",
]
FORBIDDEN_ACTIVE_DIRS = [
    "改图小样",
    "image-batch",
    "final-images",
    "seedance/seedance_refs",
    "seedance_web_final",
]
FORBIDDEN_ACTIVE_NAME_RE = re.compile(
    r"(source[-_ ]?rhythm|rhythm[-_ ]?board|source[-_ ]?frame|frame[-_ ]?board|"
    r"contact[-_ ]?sheet|python|pil|composite|validated[-_ ]?anchor|"
    r"\banchor\b|planning[-_ ]?mock|source[-_ ]?contaminat)",
    re.IGNORECASE,
)
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".flac"}


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
    except ValueError:
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


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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


def manifest_path(root, job_id, explicit=None):
    if explicit:
        return resolve_path(root, explicit)
    for raw in VISUAL_MANIFEST_CANDIDATES:
        path = resolve_path(root, raw.format(job_id=job_id))
        if path and path.exists():
            return path
    return resolve_path(root, VISUAL_MANIFEST_CANDIDATES[0].format(job_id=job_id))


def group_manifest_path(root, visual_manifest, group_kind):
    manifest_key = f"{group_kind}_manifest"
    group_id_key = f"{group_kind}_id"
    explicit = visual_manifest.get(manifest_key)
    if explicit:
        return resolve_path(root, explicit)

    group_id = visual_manifest.get(group_id_key, "")
    if not group_id:
        return None
    if group_kind == "product_group":
        return root / "output" / "shared" / "kongfengchun" / "products" / group_id / "manifest.json"
    if group_kind == "identity_group":
        return root / "output" / "shared" / "kongfengchun" / "identities" / group_id / "manifest.json"
    return None


def rel_manifest_asset(root, manifest_file, manifest, key):
    return resolve_path(root, manifest.get(key), base=manifest_file.parent)


def compatible_text_path(root, actual_raw, expected_raw):
    actual = resolve_path(root, actual_raw)
    expected = resolve_path(root, expected_raw)
    if same_path(actual, expected):
        return True
    return str(actual_raw).strip() == str(expected_raw).strip()


def validate_product_group(root, checks, job, visual_manifest, product_manifest, product_manifest_file, product_profile):
    add(
        checks,
        "product_group_type",
        "PASS" if product_manifest.get("asset_group_type") == "product_group" else "FAIL",
        product_manifest.get("asset_group_type", ""),
    )
    add(
        checks,
        "product_group_id",
        "PASS" if product_manifest.get("product_id") == visual_manifest.get("product_group_id") else "FAIL",
        f"manifest={product_manifest.get('product_id')} visual={visual_manifest.get('product_group_id')}",
    )
    job_product_name = job.get("product_name", "").strip()
    group_product_name = product_manifest.get("product_name", "").strip()
    add(
        checks,
        "product_name_binding",
        "PASS" if job_product_name and job_product_name == group_product_name else "FAIL",
        f"job={job_product_name} group={group_product_name}",
    )
    add(
        checks,
        "product_source_assets_binding",
        "PASS" if compatible_text_path(root, product_manifest.get("source_assets", ""), job.get("product_assets", "")) else "FAIL",
        f"group={product_manifest.get('source_assets', '')} job={job.get('product_assets', '')}",
    )
    front = rel_manifest_asset(root, product_manifest_file, product_manifest, "front_ref")
    open_mud = rel_manifest_asset(root, product_manifest_file, product_manifest, "open_mud_ref")
    label_detail = rel_manifest_asset(
        root,
        product_manifest_file,
        product_manifest,
        "label_detail_ref",
    )
    label_detail_declared = bool(
        str(product_manifest.get("label_detail_ref", "")).strip()
    )
    needs_open_mud = "product_open_mud" in required_ref_roles(product_profile)
    add(checks, "product_front_ref_exists", "PASS" if front and front.exists() else "STOP", display_path(root, front))
    if label_detail_declared:
        add(
            checks,
            "product_label_detail_ref_exists",
            "PASS" if label_detail and label_detail.is_file() else "STOP",
            display_path(root, label_detail),
        )
    if needs_open_mud:
        add(checks, "product_open_mud_ref_exists", "PASS" if open_mud and open_mud.exists() else "STOP", display_path(root, open_mud))
    elif open_mud and open_mud.exists():
        add(checks, "product_open_mud_ref_exists", "PASS", f"optional for loaded rules: {display_path(root, open_mud)}")
    else:
        add(checks, "product_open_mud_ref_exists", "PASS", "not required by product profile")
    reusable_refs = visual_manifest.get("reusable_refs", {}) if isinstance(visual_manifest.get("reusable_refs", {}), dict) else {}
    refs = {"product_front": front}
    if open_mud and open_mud.exists() and (needs_open_mud or reusable_refs.get("product_open")):
        refs["product_open"] = open_mud
    return refs, label_detail if label_detail_declared else None


def identity_allowed_for_job(root, job, identity_manifest, identity_manifest_file):
    allowed = identity_manifest.get("allowed_when", {}).get("person_asset", "")
    allowed_path = resolve_path(root, allowed, base=identity_manifest_file.parent)
    person_root = resolve_path(root, job.get("person_assets", ""))
    notes = job.get("notes", "")
    if same_path(allowed_path, person_root):
        return True, allowed
    if allowed_path and person_root and person_root.exists() and is_under(allowed_path, person_root):
        return True, allowed
    if allowed and allowed in notes:
        return True, allowed
    return False, allowed


def validate_identity_group(root, checks, job, visual_manifest, identity_manifest, identity_manifest_file, product_profile):
    add(
        checks,
        "identity_group_type",
        "PASS" if identity_manifest.get("asset_group_type") == "identity_group" else "FAIL",
        identity_manifest.get("asset_group_type", ""),
    )
    add(
        checks,
        "identity_group_id",
        "PASS" if identity_manifest.get("identity_id") == visual_manifest.get("identity_group_id") else "FAIL",
        f"manifest={identity_manifest.get('identity_id')} visual={visual_manifest.get('identity_group_id')}",
    )
    source_gender = str(visual_manifest.get("source_presenter_gender", "")).strip().lower()
    target_gender = str(visual_manifest.get("target_presenter_gender", "")).strip().lower()
    identity_gender = str(identity_manifest.get("presenter_gender", "")).strip().lower()
    gender_ok = (
        source_gender in {"male", "female"}
        and target_gender in {"male", "female"}
        and identity_gender in {"male", "female"}
        and source_gender == target_gender == identity_gender
    )
    add(
        checks,
        "presenter_gender_binding",
        "PASS" if gender_ok else "FAIL",
        f"source={source_gender} target={target_gender} identity={identity_gender}",
    )
    allowed_ok, allowed = identity_allowed_for_job(root, job, identity_manifest, identity_manifest_file)
    add(
        checks,
        "identity_person_asset_binding",
        "PASS" if allowed_ok else "FAIL",
        f"allowed={allowed} job_person_assets={job.get('person_assets', '')}",
    )
    identity = rel_manifest_asset(root, identity_manifest_file, identity_manifest, "identity_ref")
    afterwash = rel_manifest_asset(root, identity_manifest_file, identity_manifest, "afterwash_face_ref")
    add(checks, "identity_ref_exists", "PASS" if identity and identity.exists() else "STOP", display_path(root, identity))
    if profile_requires_afterwash_ref(product_profile):
        add(checks, "afterwash_face_ref_exists", "PASS" if afterwash and afterwash.exists() else "STOP", display_path(root, afterwash))
    elif afterwash and afterwash.exists():
        add(checks, "afterwash_face_ref_exists", "PASS", f"optional for loaded rules: {display_path(root, afterwash)}")
    else:
        add(checks, "afterwash_face_ref_exists", "PASS", "optional for this product")
    reusable_refs = visual_manifest.get("reusable_refs", {}) if isinstance(visual_manifest.get("reusable_refs", {}), dict) else {}
    refs = {"identity_ref": identity}
    if afterwash and afterwash.exists() and (profile_requires_afterwash_ref(product_profile) or reusable_refs.get("afterwash_face")):
        refs["afterwash_face"] = afterwash
    return refs


def validate_storyboard_derived_identities(root, checks, job, visual_manifest):
    job_dir = root / "output" / job["id"]
    storyboards = visual_manifest.get("part_storyboards") or {}
    role_map_file = resolve_path(root, visual_manifest.get("role_map", ""))
    role_map_exists = bool(role_map_file and role_map_file.exists())
    add(
        checks,
        "storyboard_derived_role_map",
        "PASS" if role_map_exists else "STOP",
        display_path(root, role_map_file),
    )
    if not role_map_exists:
        return {}, [], role_map_file
    try:
        role_map = load_json(role_map_file)
    except (OSError, json.JSONDecodeError) as exc:
        add(checks, "storyboard_derived_role_map_readable", "FAIL", str(exc))
        return {}, [], role_map_file
    roles = {
        str(item.get("id", "")).strip(): item
        for item in role_map.get("roles") or []
        if isinstance(item, dict) and str(item.get("id", "")).strip()
    }
    add(
        checks,
        "storyboard_derived_role_map_job",
        "PASS" if role_map.get("job_id") == job["id"] else "FAIL",
        f"role_map={role_map.get('job_id')} expected={job['id']}",
    )
    add(
        checks,
        "storyboard_derived_roles_present",
        "PASS" if roles else "STOP",
        json.dumps(sorted(roles), ensure_ascii=False),
    )

    role_manifest_values = visual_manifest.get("identity_role_manifests") or {}
    part_identity_roles = visual_manifest.get("part_identity_roles") or {}
    part_refs = visual_manifest.get("part_reusable_refs") or {}
    derived_refs = {}
    manifest_files = []
    for role_id, role in roles.items():
        if not role.get("identity_required", False):
            continue
        manifest_file = resolve_path(root, role_manifest_values.get(role_id, ""))
        manifest_files.append(manifest_file)
        exists = bool(manifest_file and manifest_file.exists())
        add(
            checks,
            f"storyboard_derived_{role_id}_manifest",
            "PASS" if exists else "STOP",
            display_path(root, manifest_file),
        )
        if not exists:
            continue
        try:
            identity_manifest = load_json(manifest_file)
        except (OSError, json.JSONDecodeError) as exc:
            add(checks, f"storyboard_derived_{role_id}_manifest_readable", "FAIL", str(exc))
            continue
        source_part = str(identity_manifest.get("source_part", "")).strip()
        source_storyboard = resolve_path(root, identity_manifest.get("source_storyboard", ""))
        expected_storyboard = resolve_path(root, (storyboards.get(source_part) or {}).get("path", ""))
        identity_ref = rel_manifest_asset(root, manifest_file, identity_manifest, "identity_ref")
        provenance_ok = (
            identity_manifest.get("asset_group_type") == "identity_group"
            and identity_manifest.get("identity_id") == role_id
            and identity_manifest.get("role_id") == role_id
            and identity_manifest.get("origin") == "storyboard_derived"
            and identity_manifest.get("source_job_id") == job["id"]
            and source_part in storyboards
            and same_path(source_storyboard, expected_storyboard)
            and identity_ref is not None
            and identity_ref.exists()
            and is_under(identity_ref, job_dir)
        )
        add(
            checks,
            f"storyboard_derived_{role_id}_provenance",
            "PASS" if provenance_ok else "FAIL",
            (
                f"source_part={source_part} source_storyboard={display_path(root, source_storyboard)} "
                f"identity_ref={display_path(root, identity_ref)}"
            ),
        )
        gender = str(identity_manifest.get("presenter_gender", "")).strip().lower()
        add(
            checks,
            f"storyboard_derived_{role_id}_gender",
            "PASS" if gender in {"male", "female"} and gender == str(role.get("gender", "")).lower() else "FAIL",
            f"role={role.get('gender')} identity={gender}",
        )
        assigned_parts = [
            part_id
            for part_id, assigned_roles in part_identity_roles.items()
            if role_id in (assigned_roles or [])
        ]
        expected_parts = sorted(str(part_id) for part_id in role.get("parts") or [])
        add(
            checks,
            f"storyboard_derived_{role_id}_part_binding",
            "PASS" if sorted(assigned_parts) == expected_parts else "FAIL",
            f"role_map={expected_parts} manifest={sorted(assigned_parts)}",
        )
        for part_id in assigned_parts:
            role_key = f"identity_{role_id}"
            actual_ref = resolve_path(root, (part_refs.get(part_id) or {}).get(role_key, ""))
            ref_ok = part_id in storyboards and same_path(actual_ref, identity_ref)
            add(
                checks,
                f"storyboard_derived_{role_id}_{part_id}_ref",
                "PASS" if ref_ok else "FAIL",
                f"actual={display_path(root, actual_ref)} expected={display_path(root, identity_ref)}",
            )
            if ref_ok:
                derived_refs.setdefault(part_id, {})[role_key] = identity_ref
    return derived_refs, manifest_files, role_map_file


def validate_reusable_refs(root, checks, visual_manifest, expected_refs):
    refs = visual_manifest.get("reusable_refs", {})
    for key, expected in expected_refs.items():
        actual = resolve_path(root, refs.get(key, ""))
        actual_exists = actual.exists() if actual else False
        same = same_path(actual, expected)
        status = "PASS" if actual_exists and same else "FAIL"
        add(
            checks,
            f"reusable_ref_{key}",
            status,
            f"actual={display_path(root, actual)} expected={display_path(root, expected)}",
        )


def route_is_allowed(entry):
    route = str(entry.get("image_route", "")).strip()
    return route in VALID_IMAGE_ROUTES


def validate_shot_label_metadata(root, checks, part, entry, storyboard_path, required):
    """Validate the only allowed deterministic edit after Matpool generation."""
    prefix = f"part_storyboard_{part}_shot_label"
    metadata = entry.get("shot_label_metadata")
    if not isinstance(metadata, dict):
        add(
            checks,
            f"{prefix}_metadata_present",
            "FAIL" if required else "PASS",
            "required for visual manifest schema v2" if required else "legacy schema; not required",
        )
        return

    add(checks, f"{prefix}_metadata_present", "PASS", "shot_label_metadata")
    add(
        checks,
        f"{prefix}_metadata_type",
        "PASS" if metadata.get("type") == "shot_label_metadata_only" else "FAIL",
        str(metadata.get("type", "")),
    )
    add(
        checks,
        f"{prefix}_manifest_panel_pixels_unchanged",
        "PASS" if metadata.get("panel_pixels_modified") is False else "FAIL",
        str(metadata.get("panel_pixels_modified")),
    )

    evidence_path = resolve_path(root, metadata.get("evidence", ""))
    evidence_exists = bool(evidence_path and evidence_path.exists())
    add(
        checks,
        f"{prefix}_evidence_exists",
        "PASS" if evidence_exists else "STOP",
        display_path(root, evidence_path),
    )
    if not evidence_exists:
        return

    try:
        evidence = load_json(evidence_path)
    except (OSError, json.JSONDecodeError) as exc:
        add(checks, f"{prefix}_evidence_readable", "FAIL", str(exc))
        return

    add(checks, f"{prefix}_evidence_readable", "PASS", display_path(root, evidence_path))
    add(
        checks,
        f"{prefix}_evidence_contract",
        "PASS"
        if evidence.get("status") == "PASS"
        and evidence.get("postprocess_type") == "shot_label_metadata_only"
        else "FAIL",
        f"status={evidence.get('status')} type={evidence.get('postprocess_type')}",
    )
    expected_labels = [f"Shot {index:02d}" for index in range(1, 13)]
    add(
        checks,
        f"{prefix}_ordered_labels",
        "PASS" if evidence.get("labels") == expected_labels else "FAIL",
        json.dumps(evidence.get("labels", []), ensure_ascii=False),
    )
    zero_panel_changes = (
        evidence.get("outside_label_changed_pixels") == 0
        and evidence.get("panel_pixels_modified") is False
    )
    add(
        checks,
        f"{prefix}_zero_panel_changes",
        "PASS" if zero_panel_changes else "FAIL",
        (
            f"outside_label_changed_pixels={evidence.get('outside_label_changed_pixels')} "
            f"panel_pixels_modified={evidence.get('panel_pixels_modified')}"
        ),
    )
    content_hash_before = str(evidence.get("panel_content_sha256_before", ""))
    content_hash_after = str(evidence.get("panel_content_sha256_after", ""))
    add(
        checks,
        f"{prefix}_panel_content_fingerprint",
        "PASS"
        if content_hash_before and content_hash_before == content_hash_after
        else "FAIL",
        f"before={content_hash_before} after={content_hash_after}",
    )

    output_hash = str(evidence.get("output_sha256", "")).strip()
    actual_hash = sha256(storyboard_path) if storyboard_path and storyboard_path.exists() else ""
    add(
        checks,
        f"{prefix}_output_hash",
        "PASS" if output_hash and output_hash == actual_hash else "FAIL",
        f"evidence={output_hash} promoted={actual_hash}",
    )


def validate_storyboards(root, checks, job_id, visual_manifest):
    part_paths = {}
    storyboards = visual_manifest.get("part_storyboards", {})
    if not isinstance(storyboards, dict) or not storyboards:
        add(checks, "part_storyboards_present", "STOP", "missing or empty")
        return part_paths

    job_dir = root / "output" / job_id
    try:
        require_shot_label_metadata = int(visual_manifest.get("schema_version", 1)) >= 2
    except (TypeError, ValueError):
        require_shot_label_metadata = True
    for part, entry in sorted(storyboards.items()):
        prefix = f"part_storyboard_{part}"
        if not isinstance(entry, dict):
            add(checks, prefix, "FAIL", "entry is not an object")
            continue
        path = resolve_path(root, entry.get("path", ""))
        part_paths[part] = path
        add(
            checks,
            f"{prefix}_asset_type",
            "PASS" if entry.get("asset_type") == VALID_STORYBOARD_TYPE else "FAIL",
            str(entry.get("asset_type", "")),
        )
        add(
            checks,
            f"{prefix}_route",
            "PASS" if route_is_allowed(entry) else "FAIL",
            str(entry.get("image_route", "")),
        )
        add(
            checks,
            f"{prefix}_no_source_pixels_flag",
            "PASS" if entry.get("contains_source_video_pixels") is False else "FAIL",
            str(entry.get("contains_source_video_pixels")),
        )
        add(checks, f"{prefix}_path_exists", "PASS" if path and path.exists() else "STOP", display_path(root, path))
        add(
            checks,
            f"{prefix}_under_active_job",
            "PASS" if path and is_under(path, job_dir) else "FAIL",
            display_path(root, path),
        )
        if path and FORBIDDEN_ACTIVE_NAME_RE.search(path.name):
            add(checks, f"{prefix}_filename_not_forbidden", "FAIL", path.name)
        else:
            add(checks, f"{prefix}_filename_not_forbidden", "PASS", path.name if path else "")
        validate_shot_label_metadata(
            root,
            checks,
            part,
            entry,
            path,
            required=require_shot_label_metadata,
        )
    return part_paths


def active_scan_dirs(root, job_id):
    job_dir = root / "output" / job_id
    return [job_dir / Path(raw) for raw in FORBIDDEN_ACTIVE_DIRS]


def has_deprecated_segment(path):
    return any("deprecated" in part.lower() or "废稿" in part for part in path.parts)


def scan_forbidden_active_files(root, checks, job_id):
    failures = []
    for scan_dir in active_scan_dirs(root, job_id):
        if not scan_dir.exists():
            continue
        for path in scan_dir.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            if has_deprecated_segment(path) and "seedance_web_final" not in path.parts:
                continue
            if FORBIDDEN_ACTIVE_NAME_RE.search(path.name):
                failures.append(display_path(root, path))
    add(
        checks,
        "active_dirs_no_forbidden_visual_names",
        "PASS" if not failures else "FAIL",
        json.dumps(failures, ensure_ascii=False),
    )


def find_prefix_file(part_dir, prefix, suffixes):
    matches = [
        p for p in sorted(part_dir.iterdir())
        if p.is_file() and p.name.startswith(prefix) and p.suffix.lower() in suffixes
    ] if part_dir.exists() else []
    return matches


def compare_file_hash(root, checks, name, actual, expected):
    if actual is None or expected is None or not actual.exists() or not expected.exists():
        add(checks, name, "STOP", f"actual={display_path(root, actual)} expected={display_path(root, expected)}")
        return
    same = sha256(actual) == sha256(expected)
    add(
        checks,
        name,
        "PASS" if same else "FAIL",
        f"actual={display_path(root, actual)} expected={display_path(root, expected)}",
    )


def derived_identity_uploads(part_refs):
    uploads = []
    next_extra = 7
    for index, (_role, path) in enumerate((part_refs or {}).items()):
        if index == 0:
            upload_index = 4
        elif index == 1:
            upload_index = 5
        else:
            upload_index = next_extra
            next_extra += 1
        uploads.append((f"{upload_index:02d}_", path))
    return uploads


def validate_final_upload_dir(
    root,
    checks,
    job_id,
    part_paths,
    expected_refs,
    derived_identity_refs=None,
):
    final_dir = root / "output" / job_id / "seedance_web_final"
    add(checks, "final_upload_dir_exists", "PASS" if final_dir.exists() else "STOP", display_path(root, final_dir))
    if not final_dir.exists():
        return

    deprecated = [display_path(root, p) for p in final_dir.rglob("*") if has_deprecated_segment(p)]
    add(
        checks,
        "final_upload_no_deprecated_drafts",
        "PASS" if not deprecated else "FAIL",
        json.dumps(deprecated, ensure_ascii=False),
    )

    handoff_mode_path = root / "output" / job_id / "seedance" / "handoff_mode.json"
    audio_parts = None
    if handoff_mode_path.exists():
        try:
            handoff = load_json(handoff_mode_path)
            if isinstance(handoff.get("audio_parts"), list):
                audio_parts = set(handoff["audio_parts"])
        except (OSError, json.JSONDecodeError):
            audio_parts = None

    part_dirs = {}
    for part in sorted(part_paths):
        match = re.search(r"(\d+)$", part, re.IGNORECASE)
        label = f"Part{match.group(1)}" if match else part
        part_dirs[part] = final_dir / f"{label}_上传素材"
    for part, part_dir in part_dirs.items():
        add(checks, f"final_{part}_dir_exists", "PASS" if part_dir.exists() else "STOP", display_path(root, part_dir))
        if not part_dir.exists():
            continue

        expected_storyboard = part_paths.get(part)
        expected_by_prefix = {
            "01_": expected_storyboard,
            "02_": expected_refs.get("product_front"),
        }
        part_derived_refs = (derived_identity_refs or {}).get(part) or {}
        if part_derived_refs:
            expected_by_prefix.update(derived_identity_uploads(part_derived_refs))
        else:
            expected_by_prefix["04_"] = expected_refs.get("identity_ref")
        if expected_refs.get("product_open"):
            expected_by_prefix["03_"] = expected_refs.get("product_open")
        if expected_refs.get("afterwash_face"):
            expected_by_prefix["05_"] = expected_refs.get("afterwash_face")
        for prefix, expected in expected_by_prefix.items():
            matches = find_prefix_file(part_dir, prefix, IMAGE_SUFFIXES)
            add(
                checks,
                f"final_{part}_{prefix}single_image",
                "PASS" if len(matches) == 1 else "FAIL",
                json.dumps([m.name for m in matches], ensure_ascii=False),
            )
            if len(matches) == 1:
                compare_file_hash(root, checks, f"final_{part}_{prefix}matches_manifest", matches[0], expected)

        audio_matches = find_prefix_file(part_dir, "06_", AUDIO_SUFFIXES)
        audio_required = audio_parts is None or part in audio_parts
        audio_ok = len(audio_matches) == 1 if audio_required else len(audio_matches) == 0
        add(
            checks,
            f"final_{part}_06_audio_present",
            "PASS" if audio_ok else "FAIL",
            (
                json.dumps([m.name for m in audio_matches], ensure_ascii=False)
                if audio_required
                else "not required; no stale audio present"
            ),
        )


def report_overall(checks):
    worst = max((status_rank(c["status"]) for c in checks), default=2)
    for status, rank in {"PASS": 0, "FAIL": 1, "STOP": 2}.items():
        if rank == worst:
            return status
    return "STOP"


def write_md(path, report):
    lines = [
        "# Visual Asset Manifest QC",
        "",
        f"- Overall: **{report['overall']}**",
        f"- Job: `{report['job_id']}`",
        f"- Stage: `{report['stage']}`",
        f"- Manifest: `{report.get('manifest_path', '')}`",
        "",
        "## Checks",
        "",
    ]
    for check in report["checks"]:
        lines.append(f"- {check['status']}: `{check['name']}` - {check['detail']}")
    lines.extend(["", "## Inputs", "", "```json", json.dumps(report["inputs"], ensure_ascii=False, indent=2), "```", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def build_report(root, job_id, stage, manifest_arg=None, check_final_dir=False):
    checks = []
    job = find_job(root, job_id)
    add(checks, "job_exists", "PASS" if job else "STOP", job_id)
    if not job:
        return {"overall": report_overall(checks), "job_id": job_id, "stage": stage, "checks": checks, "inputs": {}}

    product_profile, product_profile_file, product_profile_exists = load_product_profile(root, job)
    add(
        checks,
        "product_profile_exists",
        "PASS" if product_profile_exists else "STOP",
        display_path(root, product_profile_file),
    )
    add(
        checks,
        "product_profile_job_id",
        "PASS" if product_profile.get("job_id") == job_id else "FAIL",
        f"profile={product_profile.get('job_id')} expected={job_id}",
    )
    add(
        checks,
        "product_profile_loads_generic_rule",
        "PASS" if "generic:generic_product" in product_profile.get("loaded_rules", []) else "FAIL",
        json.dumps(rule_summary(product_profile), ensure_ascii=False),
    )

    visual_manifest_file = manifest_path(root, job_id, manifest_arg)
    add(
        checks,
        "approved_visual_manifest_exists",
        "PASS" if visual_manifest_file and visual_manifest_file.exists() else "STOP",
        display_path(root, visual_manifest_file),
    )
    if not visual_manifest_file or not visual_manifest_file.exists():
        return {
            "overall": report_overall(checks),
            "job_id": job_id,
            "stage": stage,
            "manifest_path": display_path(root, visual_manifest_file),
            "checks": checks,
            "inputs": {"job": job},
        }

    visual_manifest = load_json(visual_manifest_file)
    try:
        visual_schema_version = int(visual_manifest.get("schema_version", 1))
    except (TypeError, ValueError):
        visual_schema_version = 0
    shot_label_policy_required = stage in {"image_sample", "image_sample_review", "image_batch_qc"}
    add(
        checks,
        "shot_label_metadata_policy",
        "PASS" if not shot_label_policy_required or visual_schema_version >= 2 else "FAIL",
        (
            f"schema_version={visual_schema_version} required>=2"
            if shot_label_policy_required
            else f"schema_version={visual_schema_version} checked at image promotion"
        ),
    )
    add(
        checks,
        "visual_manifest_job_id",
        "PASS" if visual_manifest.get("job_id") == job_id else "FAIL",
        f"manifest={visual_manifest.get('job_id')} expected={job_id}",
    )

    person_asset_mode = str(visual_manifest.get("person_asset_mode", "")).strip()
    if not person_asset_mode:
        person_asset_mode = (
            "storyboard_derived"
            if job.get("person_assets", "").strip() == "storyboard_derived"
            else "user_provided"
        )
    add(
        checks,
        "person_asset_mode",
        "PASS" if person_asset_mode in {"user_provided", "storyboard_derived"} else "FAIL",
        person_asset_mode,
    )
    product_manifest_file = group_manifest_path(root, visual_manifest, "product_group")
    identity_manifest_file = (
        None
        if person_asset_mode == "storyboard_derived"
        else group_manifest_path(root, visual_manifest, "identity_group")
    )
    add(
        checks,
        "product_group_manifest_exists",
        "PASS" if product_manifest_file and product_manifest_file.exists() else "STOP",
        display_path(root, product_manifest_file),
    )
    add(
        checks,
        "identity_group_manifest_exists",
        "PASS"
        if person_asset_mode == "storyboard_derived" or (identity_manifest_file and identity_manifest_file.exists())
        else "STOP",
        (
            "replaced by identity_role_manifests"
            if person_asset_mode == "storyboard_derived"
            else display_path(root, identity_manifest_file)
        ),
    )

    expected_refs = {}
    product_manifest = {}
    product_label_detail = None
    identity_manifest = {}
    derived_identity_refs = {}
    derived_identity_manifest_files = []
    role_map_file = None
    if product_manifest_file and product_manifest_file.exists():
        product_manifest = load_json(product_manifest_file)
        product_refs, product_label_detail = validate_product_group(
            root,
            checks,
            job,
            visual_manifest,
            product_manifest,
            product_manifest_file,
            product_profile,
        )
        expected_refs.update(product_refs)
    if identity_manifest_file and identity_manifest_file.exists():
        identity_manifest = load_json(identity_manifest_file)
        expected_refs.update(validate_identity_group(root, checks, job, visual_manifest, identity_manifest, identity_manifest_file, product_profile))
    elif person_asset_mode == "storyboard_derived":
        (
            derived_identity_refs,
            derived_identity_manifest_files,
            role_map_file,
        ) = validate_storyboard_derived_identities(root, checks, job, visual_manifest)

    if expected_refs:
        validate_reusable_refs(root, checks, visual_manifest, expected_refs)
    part_paths = validate_storyboards(root, checks, job_id, visual_manifest)
    scan_forbidden_active_files(root, checks, job_id)

    if check_final_dir or stage == "request_qc":
        validate_final_upload_dir(
            root,
            checks,
            job_id,
            part_paths,
            expected_refs,
            derived_identity_refs,
        )

    return {
        "overall": report_overall(checks),
        "job_id": job_id,
        "stage": stage,
        "manifest_path": display_path(root, visual_manifest_file),
        "product_group_manifest": display_path(root, product_manifest_file),
        "product_label_detail": display_path(root, product_label_detail),
        "identity_group_manifest": display_path(root, identity_manifest_file),
        "storyboard_derived_role_map": display_path(root, role_map_file),
        "storyboard_derived_identity_manifests": [
            display_path(root, path) for path in derived_identity_manifest_files if path
        ],
        "checks": checks,
        "inputs": {
            "job": job,
            "product_profile": product_profile,
            "visual_manifest": visual_manifest,
            "product_manifest": product_manifest,
            "identity_manifest": identity_manifest,
            "derived_identity_refs": {
                part_id: {role: display_path(root, path) for role, path in refs.items()}
                for part_id, refs in derived_identity_refs.items()
            },
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Validate visual asset type manifests for viral replica jobs.")
    parser.add_argument("--root", default=".", help="Loop root directory.")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--stage", default="image_batch_qc")
    parser.add_argument("--manifest", help="Approved per-job visual manifest path.")
    parser.add_argument("--check-final-dir", action="store_true")
    parser.add_argument("--out-json", type=Path)
    parser.add_argument("--out-md", type=Path)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    default_dir = root / "output" / args.job_id / "checks"
    out_json = args.out_json or default_dir / f"{args.stage}_visual_asset_manifest_qc.json"
    out_md = args.out_md or default_dir / f"{args.stage}_visual_asset_manifest_qc.md"
    report = build_report(root, args.job_id, args.stage, args.manifest, args.check_final_dir)
    binding_inputs = [
        resolve_binding_path(root, report.get("manifest_path")),
        resolve_binding_path(root, report.get("product_group_manifest")),
        resolve_binding_path(root, report.get("product_label_detail")),
        resolve_binding_path(root, report.get("identity_group_manifest")),
        root / "output" / args.job_id / "product_profile.json",
    ]
    binding_inputs.append(resolve_binding_path(root, report.get("storyboard_derived_role_map")))
    for value in report.get("storyboard_derived_identity_manifests") or []:
        binding_inputs.append(resolve_binding_path(root, value))
    visual_manifest = (report.get("inputs") or {}).get("visual_manifest") or {}
    for item in (visual_manifest.get("part_storyboards") or {}).values():
        if isinstance(item, dict):
            binding_inputs.append(resolve_binding_path(root, item.get("path")))
    attach_input_binding(report, root, binding_inputs)

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_md(out_md, report)
    print(report["overall"])


if __name__ == "__main__":
    main()
