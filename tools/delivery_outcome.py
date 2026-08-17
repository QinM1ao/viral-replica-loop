#!/usr/bin/env python3
"""Assemble one hash-bound delivery result from finishing, subtitle, and final QC."""

import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def resolve_path(root, raw):
    if not raw:
        return None
    path = Path(str(raw)).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def bound_output(root, report, path_key, hash_key, verify_files):
    path = resolve_path(root, report.get(path_key))
    expected_hash = str(report.get(hash_key) or "")
    valid = bool(path and path.is_file() and expected_hash)
    if valid and verify_files:
        valid = sha256_file(path) == expected_hash
    return path, expected_hash, valid


def matching_repair_reports(job_dir, output_hash):
    matches = []
    for repair_root in (
        job_dir / "local_repair",
        job_dir / "edit",
        job_dir / "quality_retake",
    ):
        if not repair_root.is_dir():
            continue
        for path in repair_root.rglob("*report.json"):
            report = load_json(path)
            candidate_hash = str(
                (report.get("candidate") or {}).get("sha256")
                or (report.get("output") or {}).get("final_video_sha256")
                or report.get("output_master_sha256")
                or ""
            )
            if (
                str(report.get("overall") or report.get("decision") or "").upper()
                == "PASS"
                and report.get("paid_tasks_submitted") in (None, 0, "0")
                and candidate_hash == output_hash
            ):
                matches.append(path.resolve())
    return matches


def local_repair_status(root, job_dir, output_path, output_hash, verify_files):
    evidence = matching_repair_reports(job_dir, output_hash)
    manifest_path = (
        job_dir.parent
        / ".history"
        / job_dir.name
        / "manifests"
        / "local_repair_promotion_latest.json"
    )
    manifest = load_json(manifest_path)
    if not evidence:
        return "NOT_APPLICABLE", manifest_path

    current = manifest.get("current") or {}
    rollback = manifest.get("rollback") or {}
    review = manifest.get("review_report") or {}
    current_path = resolve_path(job_dir, current.get("path"))
    review_path = resolve_path(job_dir, review.get("path"))
    rollback_path = resolve_path(job_dir.parent, rollback.get("path"))
    history_root = (
        job_dir.parent / ".history" / job_dir.name / "rollback"
    ).resolve()
    try:
        rollback_path.resolve().relative_to(history_root)
        rollback_is_safe = True
    except (AttributeError, ValueError):
        rollback_is_safe = False
    valid = (
        manifest.get("version") == 1
        and manifest.get("job_id") == job_dir.name
        and manifest.get("policy") == "current_plus_one_rollback"
        and current_path == output_path
        and current.get("sha256") == output_hash
        and review_path in evidence
        and rollback_is_safe
        and rollback_path.is_file()
        and bool(rollback.get("sha256"))
    )
    if valid and verify_files:
        valid = (
            sha256_file(review_path) == review.get("sha256")
            and sha256_file(rollback_path) == rollback.get("sha256")
        )
    return ("PASS" if valid else "FAIL"), manifest_path


def build_delivery_manifest(root, job_id, *, write=True, verify_files=True):
    root = Path(root).resolve()
    job_dir = root / "output" / job_id
    final_dir = job_dir / "final"
    finish_report_path = final_dir / "finish_report.json"
    subtitle_report_path = (
        job_dir / "subtitle_removal" / "subtitle_removal_report.json"
    )
    final_qc_path = final_dir / "final_qc.json"

    finish = load_json(finish_report_path)
    finish_path, finish_hash, finish_bound = bound_output(
        root,
        finish,
        "output",
        "output_sha256",
        verify_files,
    )
    finishing_status = (
        "PASS"
        if str(finish.get("overall") or "").upper() == "PASS" and finish_bound
        else "FAIL"
        if finish
        else "PENDING"
    )

    subtitle = load_json(subtitle_report_path)
    subtitle_path, subtitle_hash, subtitle_bound = bound_output(
        root,
        subtitle,
        "output_video",
        "output_sha256",
        verify_files,
    )
    subtitle_source = resolve_path(root, subtitle.get("source_video"))
    subtitle_source_hash = str(subtitle.get("source_sha256") or "")
    legacy_source_bound = bool(
        not finish
        and subtitle_source
        and subtitle_source.is_file()
        and subtitle_source_hash
        and (
            not verify_files
            or sha256_file(subtitle_source) == subtitle_source_hash
        )
    )
    subtitle_status = (
        "PASS"
        if (
            str(subtitle.get("overall") or "").upper() == "PASS"
            and subtitle_bound
            and (
                (
                    finish_hash
                    and subtitle_source == finish_path
                    and subtitle_source_hash == finish_hash
                )
                or legacy_source_bound
            )
        )
        else "FAIL"
        if subtitle
        else "PENDING"
    )

    active_path = subtitle_path if subtitle_status == "PASS" else finish_path
    active_hash = subtitle_hash if subtitle_status == "PASS" else finish_hash
    final_qc = load_json(final_qc_path)
    legacy_final = None
    if active_path is None and len(final_qc.get("videos") or []) == 1:
        legacy_final = final_qc["videos"][0]
        active_path = resolve_path(root, legacy_final.get("path"))
        active_hash = str(legacy_final.get("sha256") or "")
        if (
            verify_files
            and active_path
            and active_path.is_file()
            and active_hash
            and sha256_file(active_path) != active_hash
        ):
            active_path = None
            active_hash = ""
    bound_videos = [
        item
        for item in final_qc.get("videos") or []
        if (
            resolve_path(root, item.get("path")) == active_path
            and item.get("sha256") == active_hash
        )
    ]
    final_status = (
        "PASS"
        if (
            str(final_qc.get("overall") or "").upper() == "PASS"
            and len(bound_videos) == 1
        )
        else "FAIL"
        if final_qc
        else "PENDING"
    )
    repair_status, repair_manifest_path = local_repair_status(
        root,
        job_dir,
        finish_path,
        finish_hash,
        verify_files,
    )

    statuses = {
        "finishing": finishing_status,
        "local_repair": repair_status,
        "subtitle_removal": subtitle_status,
        "final_qc": final_status,
    }
    if "FAIL" in statuses.values():
        overall = "FAIL"
    elif final_status == "PASS":
        overall = "PASS"
    else:
        overall = "IN_PROGRESS"
    next_action = (
        "finishing"
        if finishing_status != "PASS"
        else "register_local_repair"
        if repair_status == "FAIL"
        else "subtitle_removal"
        if subtitle_status != "PASS"
        else "final_qc"
        if final_status != "PASS"
        else "done"
    )
    manifest = {
        "schema_version": 1,
        "job_id": job_id,
        "compatibility_mode": (
            "legacy_final_qc"
            if legacy_final is not None
            else "legacy_subtitle_chain"
            if not finish and subtitle_status == "PASS"
            else "full_delivery_chain"
        ),
        "overall": overall,
        "next_action": next_action,
        "active_output": (
            {
                "path": str(active_path),
                "sha256": active_hash,
            }
            if active_path and active_hash
            else None
        ),
        "delivery_path": str(active_path) if overall == "PASS" else None,
        "stages": {
            "finishing": {
                "status": finishing_status,
                "report": str(finish_report_path),
                "output_sha256": finish_hash or None,
            },
            "local_repair": {
                "status": repair_status,
                "manifest": str(repair_manifest_path),
            },
            "subtitle_removal": {
                "status": subtitle_status,
                "report": str(subtitle_report_path),
                "action": subtitle.get("action"),
                "paid_tasks_submitted": subtitle.get("paid_tasks_submitted"),
                "output_sha256": subtitle_hash or None,
            },
            "final_qc": {
                "status": final_status,
                "report": str(final_qc_path),
            },
        },
    }
    if write:
        path = final_dir / "delivery_manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    manifest = build_delivery_manifest(
        args.root,
        args.job_id,
        write=not args.no_write,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if manifest["overall"] != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
