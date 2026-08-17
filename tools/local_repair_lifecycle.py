#!/usr/bin/env python3
"""Promote a reviewed local video repair while retaining one rollback master."""

import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
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


def job_file(job_dir, raw, label):
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        if path.parts[:2] == ("output", job_dir.name):
            path = job_dir / Path(*path.parts[2:])
        else:
            path = job_dir / path
    path = path.resolve()
    try:
        path.relative_to(job_dir)
    except ValueError as exc:
        raise ValueError(f"{label} must be inside the Job") from exc
    if not path.is_file():
        raise ValueError(f"{label} does not exist: {path}")
    return path


def require_local_repair_path(job_dir, path, label):
    local_root = (job_dir / "local_repair").resolve()
    try:
        path.relative_to(local_root)
    except ValueError as exc:
        raise ValueError(f"{label} must be under the Job local_repair directory") from exc


def reject_symlinked_history_path(output_dir, path):
    current = output_dir
    for part in path.relative_to(output_dir).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"history path contains a symlink: {current}")


def report_binding(report, name):
    value = report.get(name) or {}
    return str(value.get("path") or ""), str(value.get("sha256") or "")


def publish_manifest(path, manifest):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def replace_master_and_publish(master, candidate, rollback, manifest_path, manifest):
    """Replace master and manifest as one recoverable local transaction."""

    temporary = master.with_name(f".{master.name}.repairing")
    previous_rollback = rollback.with_name(f".{rollback.name}.previous")
    if temporary.exists() or previous_rollback.exists():
        raise RuntimeError("unfinished local repair transaction requires inspection")
    rollback.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidate, temporary)
    moved_previous = False
    master_moved = False
    try:
        if rollback.exists():
            os.replace(rollback, previous_rollback)
            moved_previous = True
        os.replace(master, rollback)
        master_moved = True
        os.replace(temporary, master)
        publish_manifest(manifest_path, manifest)
    except BaseException:
        if master_moved:
            if master.exists():
                master.unlink()
            if rollback.exists():
                os.replace(rollback, master)
        if moved_previous and previous_rollback.exists():
            os.replace(previous_rollback, rollback)
        if temporary.exists():
            temporary.unlink()
        manifest_temporary = manifest_path.with_suffix(".json.tmp")
        if manifest_temporary.exists():
            manifest_temporary.unlink()
        raise
    if previous_rollback.exists():
        previous_rollback.unlink()
    try:
        candidate.unlink()
    except OSError:
        pass


def promote(job_dir, candidate, report_path, confirm_job_id):
    job_dir = Path(job_dir).resolve()
    if job_dir.parent.name != "output":
        raise ValueError("job_dir must be directly under an output directory")
    if confirm_job_id != job_dir.name:
        raise ValueError("promotion confirmation does not match the Job id")

    master = job_dir / "final" / "final_video.mp4"
    if not master.is_file():
        raise ValueError("current final master does not exist")
    candidate = job_file(job_dir, candidate, "candidate")
    report_path = job_file(job_dir, report_path, "report")
    require_local_repair_path(job_dir, candidate, "candidate")
    require_local_repair_path(job_dir, report_path, "report")
    if candidate == master:
        raise ValueError("candidate must not be the current final master")

    report = load_json(report_path)
    if str(report.get("overall") or report.get("decision") or "").upper() != "PASS":
        raise ValueError("repair report must record PASS")
    if report.get("paid_tasks_submitted") != 0:
        raise ValueError("local repair promotion requires paid_tasks_submitted=0")
    baseline_path_raw, baseline_hash = report_binding(report, "baseline")
    candidate_path_raw, candidate_hash = report_binding(report, "candidate")
    baseline_path = job_file(job_dir, baseline_path_raw, "baseline")
    bound_candidate = job_file(job_dir, candidate_path_raw, "candidate")
    if baseline_path != master or baseline_hash != sha256_file(master):
        raise ValueError("baseline binding is stale")
    if bound_candidate != candidate or candidate_hash != sha256_file(candidate):
        raise ValueError("candidate binding is stale")

    rollback = (
        job_dir.parent
        / ".history"
        / job_dir.name
        / "rollback"
        / "local_repair"
        / master.relative_to(job_dir)
    )
    manifest = {
        "version": 1,
        "job_id": job_dir.name,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "policy": "current_plus_one_rollback",
        "current": {
            "path": master.relative_to(job_dir).as_posix(),
            "sha256": candidate_hash,
        },
        "rollback": {
            "path": rollback.relative_to(job_dir.parent).as_posix(),
            "sha256": baseline_hash,
        },
        "source_candidate": {
            "path": candidate.relative_to(job_dir).as_posix(),
            "sha256": candidate_hash,
        },
        "review_report": {
            "path": report_path.relative_to(job_dir).as_posix(),
            "sha256": sha256_file(report_path),
        },
        "requires_delivery_revalidation": True,
    }
    manifest_path = (
        job_dir.parent
        / ".history"
        / job_dir.name
        / "manifests"
        / "local_repair_promotion_latest.json"
    )
    reject_symlinked_history_path(job_dir.parent, rollback)
    reject_symlinked_history_path(job_dir.parent, manifest_path)
    replace_master_and_publish(
        master,
        candidate,
        rollback,
        manifest_path,
        manifest,
    )
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    promote_parser = subparsers.add_parser("promote")
    promote_parser.add_argument("--job-dir", required=True, type=Path)
    promote_parser.add_argument("--candidate", required=True, type=Path)
    promote_parser.add_argument("--report", required=True, type=Path)
    promote_parser.add_argument("--confirm-job-id", required=True)
    args = parser.parse_args(argv)
    try:
        result = promote(
            args.job_dir,
            args.candidate,
            args.report,
            args.confirm_job_id,
        )
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
