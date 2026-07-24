#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image

from restore_storyboard_shot_labels import panel_content_sha256


FINGERPRINT_VERSION = 2
STATE_FILE = "visual_qc_reuse_state.json"
SNAPSHOT_FILE = "visual_qc_reuse_snapshot.json"
HEAVY_QC_REPORTS = {
    "codex_imagegen_contract": [
        "output/{job_id}/checks/image_batch_qc_codex_imagegen_contract_qc.json",
        "output/{job_id}/checks/image_batch_codex_imagegen_contract_qc.json",
        "output/{job_id}/checks/codex_imagegen_contract_qc.json",
    ],
    "storyboard_geometry": [
        "output/{job_id}/checks/image_batch_qc_storyboard_geometry_qc.json",
        "output/{job_id}/checks/image_batch_storyboard_geometry_qc.json",
        "output/{job_id}/checks/storyboard_geometry_qc.json",
    ],
    "cross_part_continuity": [
        "output/{job_id}/checks/image_batch_qc_cross_part_continuity_qc.json",
        "output/{job_id}/checks/image_batch_cross_part_continuity_qc.json",
        "output/{job_id}/checks/cross_part_continuity_qc.json",
    ],
    "skincare_progression": [
        "output/{job_id}/checks/image_batch_qc_skincare_progression_qc.json",
        "output/{job_id}/checks/image_batch_skincare_progression_qc.json",
        "output/{job_id}/checks/skincare_progression_qc.json",
    ],
}
VISUAL_DEFECT_FILES = [
    "output/{job_id}/checks/user_visible_defects.json",
    "output/{job_id}/checks/visible_defects.json",
    "output/{job_id}/visible_defects.json",
]
VISUAL_MANIFEST_CANDIDATES = [
    "output/{job_id}/visual-assets/approved_visual_manifest.json",
    "output/{job_id}/approved_visual_manifest.json",
    "output/{job_id}/seedance/approved_visual_manifest.json",
    "output/{job_id}/checks/approved_visual_manifest.json",
]
MATERIAL_ROLE_CANDIDATES = [
    "output/{job_id}/seedance/seedance_素材角色表.md",
    "output/{job_id}/seedance_web_final/manifests/upload_manifest.json",
]
PROMPT_ROLE_GLOBS = [
    "output/{job_id}/seedance_web_final/prompts/*",
    "output/{job_id}/seedance/prompts/*",
    "output/{job_id}/seedance/*prompt*.md",
    "output/{job_id}/seedance/*prompt*.txt",
]


def now_iso():
    import datetime as dt

    return dt.datetime.now().isoformat(timespec="seconds")


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


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_hash(value):
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def load_json(path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def qc_overall(path):
    try:
        data = load_json(path)
    except (OSError, json.JSONDecodeError):
        return None
    overall = data.get("overall")
    return str(overall).strip().upper() if overall is not None else None


def manifest_path(root, job_id, explicit=None):
    if explicit:
        return resolve_path(root, explicit)
    for raw in VISUAL_MANIFEST_CANDIDATES:
        path = resolve_path(root, raw.format(job_id=job_id))
        if path and path.exists():
            return path
    return resolve_path(root, VISUAL_MANIFEST_CANDIDATES[0].format(job_id=job_id))


def shot_label_metadata_proof(root, entry, image_path, image_sha256):
    metadata = entry.get("shot_label_metadata")
    if not isinstance(metadata, dict) or metadata.get("type") != "shot_label_metadata_only":
        return {"valid": False}
    evidence_path = resolve_path(root, metadata.get("evidence", ""))
    if not evidence_path or not evidence_path.exists():
        return {"valid": False}
    try:
        evidence = load_json(evidence_path)
        bands = [tuple(band) for band in evidence.get("label_bands", [])]
        valid_bands = bool(bands) and all(
            len(band) == 2 and 0 <= band[0] < band[1] for band in bands
        )
        before_hash = str(evidence.get("panel_content_sha256_before", ""))
        after_hash = str(evidence.get("panel_content_sha256_after", ""))
        contract_valid = (
            evidence.get("status") == "PASS"
            and evidence.get("postprocess_type") == "shot_label_metadata_only"
            and evidence.get("output_sha256") == image_sha256
            and evidence.get("outside_label_changed_pixels") == 0
            and evidence.get("panel_pixels_modified") is False
            and valid_bands
            and before_hash
            and before_hash == after_hash
        )
        if not contract_valid:
            return {"valid": False}
        with Image.open(image_path) as opened:
            image = opened.convert("RGB")
        current_content_hash = panel_content_sha256(image, bands)
        if current_content_hash != after_hash:
            return {"valid": False}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {"valid": False}
    return {
        "valid": True,
        "visual_content_sha256": current_content_hash,
        "label_bands": [[top, bottom] for top, bottom in bands],
        "evidence_path": display_path(root, evidence_path),
    }


def active_image_hashes(root, manifest, manifest_file):
    images = {}
    for part, entry in sorted((manifest.get("part_storyboards") or {}).items()):
        if not isinstance(entry, dict):
            continue
        path = resolve_path(root, entry.get("path", ""), base=manifest_file.parent)
        image_sha256 = sha256_file(path) if path and path.exists() else None
        metadata_proof = (
            shot_label_metadata_proof(root, entry, path, image_sha256)
            if path and path.exists()
            else {"valid": False}
        )
        images[part] = {
            "path": display_path(root, path),
            "sha256": image_sha256,
            "manifest_candidate_sha256": entry.get("candidate_sha256"),
            "visual_content_sha256": metadata_proof.get("visual_content_sha256", image_sha256),
            "shot_label_metadata_only_proof": metadata_proof.get("valid", False),
            "shot_label_bands": metadata_proof.get("label_bands"),
        }
    return images


def approved_visual_manifest_mapping(manifest):
    storyboards = {}
    for part, entry in sorted((manifest.get("part_storyboards") or {}).items()):
        if not isinstance(entry, dict):
            continue
        storyboards[part] = {
            "path": entry.get("path", ""),
            "asset_type": entry.get("asset_type", ""),
            "image_route": entry.get("image_route", ""),
            "contains_source_video_pixels": entry.get("contains_source_video_pixels"),
            "source_reference": entry.get("source_reference", ""),
            "prompt": entry.get("prompt", ""),
            "refs_manifest": entry.get("refs_manifest", ""),
            "hard_gate": entry.get("hard_gate", ""),
        }
    return {
        "job_id": manifest.get("job_id", ""),
        "product_group_id": manifest.get("product_group_id", ""),
        "product_group_manifest": manifest.get("product_group_manifest", ""),
        "identity_group_id": manifest.get("identity_group_id", ""),
        "identity_group_manifest": manifest.get("identity_group_manifest", ""),
        "reusable_refs": manifest.get("reusable_refs", {}),
        "part_storyboards": storyboards,
    }


def existing_candidate_files(root, job_id, candidates):
    paths = []
    for raw in candidates:
        path = resolve_path(root, raw.format(job_id=job_id))
        if path and path.exists() and path.is_file():
            paths.append(path)
    return sorted(set(paths))


def prompt_role_files(root, job_id):
    paths = []
    for raw in PROMPT_ROLE_GLOBS:
        paths.extend(resolve_path(root, raw.format(job_id=job_id)).parent.glob(Path(raw).name))
    return sorted({p for p in paths if p.exists() and p.is_file()})


def file_mapping(root, paths):
    files = {}
    for path in sorted(paths):
        files[display_path(root, path)] = sha256_file(path)
    return {"files": files, "hash": stable_hash(files) if files else None}


def current_fingerprint(root, job_id, manifest_arg=None):
    manifest_file = manifest_path(root, job_id, manifest_arg)
    if not manifest_file or not manifest_file.exists():
        raise FileNotFoundError(f"missing approved visual manifest for {job_id}: {manifest_file}")
    manifest = load_json(manifest_file)
    fingerprint = {
        "version": FINGERPRINT_VERSION,
        "job_id": job_id,
        "manifest_path": display_path(root, manifest_file),
        "active_final_image_hashes": active_image_hashes(root, manifest, manifest_file),
        "approved_visual_manifest_mapping": approved_visual_manifest_mapping(manifest),
        "material_role_mapping": file_mapping(root, existing_candidate_files(root, job_id, MATERIAL_ROLE_CANDIDATES)),
        "prompt_reference_roles": file_mapping(root, prompt_role_files(root, job_id)),
    }
    fingerprint["fingerprint_hash"] = stable_hash(fingerprint)
    return fingerprint


def passing_heavy_reports(root, job_id):
    reports = {}
    for kind, candidates in HEAVY_QC_REPORTS.items():
        for raw in candidates:
            path = resolve_path(root, raw.format(job_id=job_id))
            if path and path.exists() and qc_overall(path) == "PASS":
                reports[kind] = {"path": display_path(root, path), "sha256": sha256_file(path)}
                break
    return reports


def active_visible_defects(root, job_id):
    defects = []
    for raw in VISUAL_DEFECT_FILES:
        path = resolve_path(root, raw.format(job_id=job_id))
        if not path or not path.exists():
            continue
        try:
            data = load_json(path)
        except (OSError, json.JSONDecodeError):
            defects.append({"path": display_path(root, path), "reason": "unreadable defect file"})
            continue
        entries = data.get("defects", data if isinstance(data, list) else [])
        for entry in entries:
            if not isinstance(entry, dict):
                defects.append({"path": display_path(root, path), "reason": "non-object defect entry"})
                continue
            status = str(entry.get("status", entry.get("state", "open"))).strip().lower()
            if status not in {"resolved", "closed", "cleared", "dismissed"}:
                item = dict(entry)
                item["path"] = display_path(root, path)
                defects.append(item)
    return defects


def state_path(root, job_id):
    return root / "output" / job_id / "checks" / STATE_FILE


def load_state(root, job_id):
    path = state_path(root, job_id)
    if not path.exists():
        return None
    return load_json(path)


def compare_active_images(previous, current):
    if previous == current:
        return [], []
    if set(previous) != set(current):
        return ["active_final_image_hashes_changed"], []

    metadata_only_changes = []
    for part in sorted(previous):
        old = previous.get(part) or {}
        new = current.get(part) or {}
        if old.get("sha256") == new.get("sha256"):
            continue
        metadata_only = (
            old.get("path") == new.get("path")
            and old.get("manifest_candidate_sha256") == new.get("manifest_candidate_sha256")
            and old.get("shot_label_metadata_only_proof") is True
            and new.get("shot_label_metadata_only_proof") is True
            and old.get("visual_content_sha256")
            and old.get("visual_content_sha256") == new.get("visual_content_sha256")
            and old.get("shot_label_bands") == new.get("shot_label_bands")
        )
        if not metadata_only:
            return ["active_final_image_hashes_changed"], []
        metadata_only_changes.append(part)
    return [], metadata_only_changes


def compare_fingerprint(snapshot, current):
    invalidations = []
    image_invalidations, metadata_only_changes = compare_active_images(
        snapshot.get("active_final_image_hashes") or {},
        current.get("active_final_image_hashes") or {},
    )
    invalidations.extend(image_invalidations)
    if snapshot.get("approved_visual_manifest_mapping") != current.get("approved_visual_manifest_mapping"):
        invalidations.append("approved_visual_manifest_mapping_changed")

    for key, reason in (
        ("material_role_mapping", "material_role_mapping_changed"),
        ("prompt_reference_roles", "prompt_reference_roles_changed"),
    ):
        previous = snapshot.get(key) or {}
        if previous.get("files") and previous != current.get(key):
            invalidations.append(reason)
    return invalidations, metadata_only_changes


def report_paths_still_passing(root, reports):
    invalidations = []
    for kind, report in sorted((reports or {}).items()):
        path = resolve_path(root, report.get("path", ""))
        if not path or not path.exists():
            invalidations.append(f"{kind}_report_missing")
            continue
        if qc_overall(path) != "PASS":
            invalidations.append(f"{kind}_report_not_pass")
            continue
        if report.get("sha256") and sha256_file(path) != report.get("sha256"):
            invalidations.append(f"{kind}_report_hash_changed")
    return invalidations


def write_summary_md(path, summary):
    lines = [
        "# Hash-Gated Visual QC Reuse",
        "",
        f"- Overall: **{summary['overall']}**",
        f"- Job: `{summary['job_id']}`",
        f"- Stage: `{summary['stage']}`",
        f"- State: `{summary.get('state_path', '')}`",
        "",
        "## Reused Heavy QC",
        "",
    ]
    for kind, report in sorted(summary.get("reused_reports", {}).items()):
        lines.append(f"- `{kind}`: `{report.get('path', '')}`")
    if not summary.get("reused_reports"):
        lines.append("- None")
    lines.extend(["", "## Lightweight Checks", ""])
    for check in summary.get("lightweight_checks", []):
        lines.append(f"- `{check.get('name', '')}`: `{check.get('path', '')}`")
    if summary.get("invalidations"):
        lines.extend(["", "## Invalidations", ""])
        for reason in summary["invalidations"]:
            lines.append(f"- `{reason}`")
    if summary.get("metadata_only_changes"):
        lines.extend(["", "## Metadata-only Changes", ""])
        for part in summary["metadata_only_changes"]:
            lines.append(f"- `{part}`: Shot-label bars only; content QC reused")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def record_snapshot(root, job_id, stage="image_batch_qc", manifest_arg=None, write=True):
    fingerprint = current_fingerprint(root, job_id, manifest_arg)
    reports = passing_heavy_reports(root, job_id)
    snapshot = {
        "overall": "PASS" if reports else "STOP",
        "updated_at": now_iso(),
        "job_id": job_id,
        "stage": stage,
        "fingerprint": fingerprint,
        "reused_reports": reports,
        "source": "image_batch_pass",
    }
    checks_dir = root / "output" / job_id / "checks"
    snapshot["snapshot_path"] = display_path(root, checks_dir / SNAPSHOT_FILE)
    snapshot["state_path"] = display_path(root, checks_dir / STATE_FILE)
    if write:
        write_json(checks_dir / SNAPSHOT_FILE, snapshot)
        write_json(checks_dir / STATE_FILE, snapshot)
    return snapshot


def ensure_reuse_summary(
    root,
    job_id,
    stage,
    visual_qc_path=None,
    checker_qc_path=None,
    manifest_arg=None,
    write=True,
):
    previous = load_state(root, job_id)
    current = current_fingerprint(root, job_id, manifest_arg)
    checks_dir = root / "output" / job_id / "checks"
    invalidations = []
    metadata_only_changes = []
    if previous is None:
        invalidations.append("missing_visual_qc_reuse_state")
        reused_reports = {}
    else:
        fingerprint_invalidations, metadata_only_changes = compare_fingerprint(
            previous.get("fingerprint", {}), current
        )
        invalidations.extend(fingerprint_invalidations)
        reused_reports = previous.get("reused_reports", {})
        invalidations.extend(report_paths_still_passing(root, reused_reports))

    defects = active_visible_defects(root, job_id)
    if defects:
        invalidations.append("user_visible_defect_recorded")

    lightweight_checks = []
    if visual_qc_path:
        lightweight_checks.append({"name": "visual_asset_manifest_qc", "path": display_path(root, visual_qc_path)})
    if checker_qc_path:
        lightweight_checks.append({"name": "checker_review_qc", "path": display_path(root, checker_qc_path)})

    summary = {
        "overall": "PASS" if not invalidations else "STOP",
        "updated_at": now_iso(),
        "job_id": job_id,
        "stage": stage,
        "state_path": display_path(root, state_path(root, job_id)),
        "source_state_stage": previous.get("stage") if previous else None,
        "fingerprint": current,
        "reused_reports": reused_reports if not invalidations else {},
        "lightweight_checks": lightweight_checks,
        "invalidations": invalidations,
        "metadata_only_changes": metadata_only_changes,
        "visible_defects": defects,
    }
    out_json = checks_dir / f"{stage}_visual_qc_reuse_summary.json"
    out_md = checks_dir / f"{stage}_visual_qc_reuse_summary.md"
    summary["summary_path"] = display_path(root, out_json)

    if write:
        write_json(out_json, summary)
        write_summary_md(out_md, summary)
        if summary["overall"] == "PASS":
            next_state = dict(summary)
            next_state["source"] = "downstream_reuse"
            write_json(state_path(root, job_id), next_state)
    return summary


def main():
    parser = argparse.ArgumentParser(description="Record or check hash-gated heavy visual QC reuse.")
    parser.add_argument("--root", default=".", help="Loop root directory.")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--stage", default="image_batch_qc")
    parser.add_argument("--manifest")
    parser.add_argument("--record-snapshot", action="store_true")
    parser.add_argument("--check-reuse", action="store_true")
    parser.add_argument("--visual-qc")
    parser.add_argument("--checker-qc")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if args.record_snapshot:
        report = record_snapshot(root, args.job_id, args.stage, args.manifest)
    elif args.check_reuse:
        visual_qc = resolve_path(root, args.visual_qc) if args.visual_qc else None
        checker_qc = resolve_path(root, args.checker_qc) if args.checker_qc else None
        report = ensure_reuse_summary(root, args.job_id, args.stage, visual_qc, checker_qc, args.manifest)
    else:
        parser.error("choose --record-snapshot or --check-reuse")
    print(report["overall"])


if __name__ == "__main__":
    main()
