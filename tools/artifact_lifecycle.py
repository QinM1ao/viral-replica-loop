#!/usr/bin/env python3
"""Keep active Job artifacts small and preview legacy cleanup safely."""

import argparse
import hashlib
import json
import re
import shutil
from collections import defaultdict
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path


SAFE_PREFIX = re.compile(r"[A-Za-z0-9_-]+")
ACTIVE_REPLACEMENTS = ContextVar("active_artifact_replacements", default=None)
MIB = 1024 * 1024


def _files_under(path):
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(child for child in path.rglob("*") if child.is_file())
    return []


def _path_bytes(path):
    return sum(child.stat().st_size for child in _files_under(path))


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _reject_symlink_components(base, path):
    base = Path(base).resolve()
    path = Path(path)
    current = base
    for part in path.relative_to(base).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"history path contains a symlink: {current}")


def _remove_path(path):
    if not path.exists():
        return
    shutil.rmtree(path) if path.is_dir() else path.unlink()


def _load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _job_path(job_dir, raw):
    if not raw:
        return None
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        if path.parts[:2] == ("output", job_dir.name):
            path = job_dir / Path(*path.parts[2:])
        else:
            path = job_dir / path
    try:
        path.resolve().relative_to(job_dir)
    except ValueError:
        return None
    return path.resolve()


def _declared_job_paths(job_dir, value):
    paths = set()
    if isinstance(value, dict):
        for child in value.values():
            paths.update(_declared_job_paths(job_dir, child))
    elif isinstance(value, list):
        for child in value:
            paths.update(_declared_job_paths(job_dir, child))
    elif isinstance(value, str):
        path = _job_path(job_dir, value)
        if path is not None:
            paths.add(path)
    return paths


def _candidate(job_dir, path):
    files = _files_under(path)
    fingerprint = [
        {
            "path": child.relative_to(path).as_posix() if path.is_dir() else child.name,
            "bytes": child.stat().st_size,
            "sha256": _sha256(child),
        }
        for child in files
    ]
    return {
        "path": path.relative_to(job_dir).as_posix(),
        "files": len(files),
        "bytes": sum(child.stat().st_size for child in files),
        "tree_digest": hashlib.sha256(
            json.dumps(
                fingerprint,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    }


def _family(candidates, retained=(), reason=""):
    return {
        "reason": reason,
        "retained": [str(path) for path in retained],
        "candidates": candidates,
        "reclaimable_bytes": sum(item["bytes"] for item in candidates),
    }


def _source_composition_family(job_dir):
    root = job_dir / "source-composition"
    rhythm = job_dir / "剧情分析" / "source_rhythm.json"
    if not root.is_dir() or not rhythm.is_file():
        return _family([], reason="no complete source-composition cache")

    current_hash = _sha256(rhythm)
    caches = []
    cache_paths = sorted(
        (child for child in root.iterdir() if child.is_dir()),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
    )
    for path in cache_paths:
        bundle = _load_json(path / "source_composition_bundle.json")
        caches.append(
            (
                path,
                str((bundle.get("source_rhythm") or {}).get("sha256") or ""),
                str(bundle.get("overall") or "").upper(),
            )
        )
    matching = [
        path for path, source_hash, overall in caches
        if source_hash == current_hash and overall == "PASS"
    ]
    plan = _load_json(root / "source_composition_plan.json")
    spec = _load_json(root / "source_composition_spec.json")
    planned = _job_path(job_dir, plan.get("output_root"))
    specified = _job_path(job_dir, spec.get("output_root"))
    bindings_agree = (
        planned is not None
        and planned == specified
        and plan.get("cache_key") == spec.get("cache_key")
        and str((plan.get("source_rhythm") or {}).get("sha256") or "")
        == str(spec.get("source_rhythm_sha256") or "")
        == current_hash
    )
    active = planned if bindings_agree and planned in matching else None
    if active is None:
        return _family(
            [],
            retained=[
                path.relative_to(job_dir).as_posix()
                for path, _source_hash, _overall in caches
            ],
            reason="source-composition plan/spec/current-rhythm bindings are not safe to clean",
        )
    rollback = next(
        (
            path
            for path, _source_hash, overall in reversed(caches)
            if path != active and overall == "PASS"
        ),
        None,
    )
    candidates = [
        _candidate(job_dir, path)
        for path, _source_hash, _overall in caches
        if path not in {active, rollback}
    ]
    retained = [active.relative_to(job_dir).as_posix()]
    if rollback is not None:
        retained.append(rollback.relative_to(job_dir).as_posix())
    return _family(
        candidates,
        retained=retained,
        reason="retain the active Source Rhythm cache plus one completed rollback",
    )


def _image_candidate_family(job_dir):
    candidate_root = job_dir / "image-batch" / "candidates"
    manifest = _load_json(
        job_dir / "visual-assets" / "approved_visual_manifest.json"
    )
    if not candidate_root.is_dir() or not manifest:
        return _family([], reason="no promoted storyboard manifest")

    protected = set()
    bindings_valid = True
    for part in (manifest.get("part_storyboards") or {}).values():
        active = _job_path(job_dir, part.get("synced_from_candidate"))
        promoted = _job_path(job_dir, part.get("path"))
        expected_hash = str(part.get("candidate_sha256") or "")
        if (
            active is None
            or promoted is None
            or not active.is_file()
            or not promoted.is_file()
            or not expected_hash
            or _sha256(active) != expected_hash
            or _sha256(promoted) != expected_hash
        ):
            bindings_valid = False
            break
        protected.add(active)
        evidence = _job_path(
            job_dir,
            (part.get("shot_label_metadata") or {}).get("evidence"),
        )
        evidence_report = _load_json(evidence) if evidence else {}
        if (
            str(evidence_report.get("status") or "").upper() == "PASS"
            and _job_path(job_dir, evidence_report.get("output")) == active
            and evidence_report.get("output_sha256") == expected_hash
        ):
            rollback = _job_path(job_dir, evidence_report.get("input"))
            if (
                rollback is not None
                and rollback.is_file()
                and _sha256(rollback)
                == evidence_report.get("input_sha256")
            ):
                protected.add(rollback)
    all_candidates = sorted(
        child for child in candidate_root.iterdir() if child.is_file()
    )
    if not bindings_valid:
        return _family(
            [],
            retained=[
                path.relative_to(job_dir).as_posix()
                for path in all_candidates
            ],
            reason="image promotion path/hash bindings are not safe to clean",
        )
    candidates = [
        _candidate(job_dir, path)
        for path in all_candidates
        if path.resolve() not in protected
    ]
    retained = [
        path.relative_to(job_dir).as_posix()
        for path in sorted(protected)
        if path.is_file()
    ]
    return _family(
        candidates,
        retained=retained,
        reason="retain each promoted candidate plus its label-only rollback input",
    )


def _generation_transient_family(job_dir):
    selected_path = job_dir / "generation" / "selected_outputs.json"
    selected = _load_json(selected_path)
    outputs = selected.get("outputs") or []
    if not selected_path.is_file() or not outputs:
        return _family([], reason="generation has no selected outputs")

    protected = _declared_job_paths(job_dir, selected)
    outputs_valid = bool(outputs) and all(
        (
            (path := _job_path(job_dir, item.get("path"))) is not None
            and path.is_file()
            and bool(item.get("sha256"))
            and _sha256(path) == item.get("sha256")
        )
        for item in outputs
    )
    retained = [
        path.relative_to(job_dir).as_posix()
        for path in sorted(protected)
        if path.exists()
    ]
    candidates = []
    for name in ("debug_preflight", "debug_preflight_bound"):
        path = job_dir / "generation" / name
        if not path.exists():
            continue
        if outputs_valid:
            candidates.append(_candidate(job_dir, path))
        else:
            retained.append(path.relative_to(job_dir).as_posix())
    return _family(
        candidates,
        retained=retained,
        reason=(
            "selected media stay protected; redundant preflight mirrors are reproducible"
            if outputs_valid
            else "selected output path/hash bindings are not safe to clean"
        ),
    )


def _subtitle_transient_family(job_dir):
    report = _load_json(
        job_dir / "subtitle_removal" / "subtitle_removal_report.json"
    )
    source = _job_path(job_dir, report.get("source_video"))
    output = _job_path(job_dir, report.get("output_video"))
    cache = (
        job_dir
        / "subtitle_removal"
        / "provider"
        / "normalization_tests"
    )
    source_hash = str(report.get("source_sha256") or "")
    output_hash = str(report.get("output_sha256") or "")
    report_is_stale = (
        str(report.get("overall") or "").upper() != "PASS"
        or source is None
        or output is None
        or not source.is_file()
        or not output.is_file()
        or not source_hash
        or not output_hash
        or _sha256(source) != source_hash
        or _sha256(output) != output_hash
    )
    if report_is_stale:
        migration = _load_json(
            job_dir.parent
            / ".history"
            / job_dir.name
            / "manifests"
            / "subtitle_cleanup_migration_latest.json"
        )
        source = _job_path(job_dir, (migration.get("source") or {}).get("path"))
        output = _job_path(job_dir, (migration.get("output") or {}).get("path"))
        migrated_report = _job_path(
            job_dir,
            (migration.get("legacy_report") or {}).get("path"),
        )
        migration_is_current = (
            migration.get("version") == 1
            and migration.get("job_id") == job_dir.name
            and migration.get("scope") == "subtitle_normalization_trials"
            and source is not None
            and output is not None
            and source.is_file()
            and output.is_file()
            and (migration.get("source") or {}).get("sha256") == _sha256(source)
            and (migration.get("output") or {}).get("sha256") == _sha256(output)
            and migrated_report
            == (job_dir / "subtitle_removal" / "subtitle_removal_report.json").resolve()
            and migrated_report.is_file()
            and (migration.get("legacy_report") or {}).get("sha256")
            == _sha256(migrated_report)
            and migration.get("cleanup_root")
            == "subtitle_removal/provider/normalization_tests"
        )
        if not migration_is_current:
            return _family(
                [],
                reason=(
                    "subtitle report is stale and no current explicit migration "
                    "unlocks its disposable trials"
                ),
            )
    candidates = []
    if cache.is_dir():
        candidates.append(_candidate(job_dir, cache))
    repair_analysis = job_dir / "subtitle_removal" / "local_label_repair_analysis"
    if repair_analysis.is_dir():
        candidates.extend(
            _candidate(job_dir, path)
            for path in sorted(repair_analysis.glob("*test*.mp4"))
            if path.is_file()
        )
    return _family(
        candidates,
        retained=[
            source.relative_to(job_dir).as_posix(),
            output.relative_to(job_dir).as_posix(),
        ],
        reason=(
            "retain current source/output and required proof; remove only named "
            "normalization/test encodes"
        ),
    )


def migrate_subtitle_cleanup(job_dir, source_video, output_video, confirm_job_id):
    """Bind current legacy delivery files before deleting disposable trial encodes."""

    job_dir = Path(job_dir).resolve()
    if job_dir.parent.name != "output":
        raise ValueError("job_dir must be directly under an output directory")
    if confirm_job_id != job_dir.name:
        raise ValueError("migration confirmation does not match the Job id")
    source = _job_path(job_dir, source_video)
    output = _job_path(job_dir, output_video)
    if source is None or not source.is_file():
        raise ValueError("source video must be a current file inside the Job")
    if output is None or not output.is_file():
        raise ValueError("output video must be a current file inside the Job")
    trials = (
        job_dir / "subtitle_removal" / "provider" / "normalization_tests"
    )
    if not trials.is_dir():
        raise ValueError("no legacy subtitle normalization trials to migrate")
    legacy_report = (
        job_dir / "subtitle_removal" / "subtitle_removal_report.json"
    )
    report = _load_json(legacy_report)
    if str(report.get("overall") or "").upper() != "PASS":
        raise ValueError("legacy subtitle report must record PASS")

    manifest = {
        "version": 1,
        "job_id": job_dir.name,
        "scope": "subtitle_normalization_trials",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "path": source.relative_to(job_dir).as_posix(),
            "sha256": _sha256(source),
        },
        "output": {
            "path": output.relative_to(job_dir).as_posix(),
            "sha256": _sha256(output),
        },
        "legacy_report": {
            "path": legacy_report.relative_to(job_dir).as_posix(),
            "sha256": _sha256(legacy_report),
        },
        "cleanup_root": trials.relative_to(job_dir).as_posix(),
    }
    path = (
        job_dir.parent
        / ".history"
        / job_dir.name
        / "manifests"
        / "subtitle_cleanup_migration_latest.json"
    )
    _reject_symlink_components(job_dir.parent, path)
    _write_json(path, manifest)
    return manifest


def _local_repair_family(job_dir):
    final_video = job_dir / "final" / "final_video.mp4"
    if not final_video.is_file():
        return _family([], reason="no final master")
    final_hash = _sha256(final_video)
    lifecycle = _load_json(
        job_dir.parent
        / ".history"
        / job_dir.name
        / "manifests"
        / "local_repair_promotion_latest.json"
    )
    if lifecycle:
        current = _job_path(job_dir, (lifecycle.get("current") or {}).get("path"))
        candidate = _job_path(
            job_dir,
            (
                lifecycle.get("source_candidate")
                or lifecycle.get("candidate")
                or {}
            ).get("path"),
        )
        report_path = _job_path(
            job_dir,
            (lifecycle.get("review_report") or {}).get("path"),
        )
        rollback_raw = str((lifecycle.get("rollback") or {}).get("path") or "")
        rollback = (job_dir.parent / rollback_raw).resolve()
        history_root = (
            job_dir.parent / ".history" / job_dir.name / "rollback"
        ).resolve()
        try:
            rollback.relative_to(history_root)
            rollback_is_safe = True
        except ValueError:
            rollback_is_safe = False
        lifecycle_is_current = (
            lifecycle.get("version") == 1
            and lifecycle.get("job_id") == job_dir.name
            and lifecycle.get("policy") == "current_plus_one_rollback"
            and current == final_video.resolve()
            and current.is_file()
            and (lifecycle.get("current") or {}).get("sha256") == final_hash
            and report_path is not None
            and report_path.is_file()
            and (lifecycle.get("review_report") or {}).get("sha256")
            == _sha256(report_path)
            and rollback_is_safe
            and rollback.is_file()
            and (lifecycle.get("rollback") or {}).get("sha256")
            == _sha256(rollback)
        )
        if not lifecycle_is_current:
            return _family(
                [],
                reason="local repair lifecycle manifest is stale; cleanup stays locked",
            )
        protected = {
            final_video.resolve(),
            rollback,
            report_path,
        }
        report = _load_json(report_path)
        generated_patch = _job_path(
            job_dir,
            (report.get("generated_patch") or {}).get("path"),
        )
        if generated_patch is not None and generated_patch.is_file():
            protected.add(generated_patch)
        candidates = []
        candidate_record = (
            lifecycle.get("source_candidate")
            or lifecycle.get("candidate")
            or {}
        )
        if (
            candidate is not None
            and candidate.is_file()
            and candidate_record.get("sha256") == _sha256(candidate) == final_hash
        ):
            candidates.append(_candidate(job_dir, candidate))
        local_root = job_dir / "local_repair"
        if local_root.is_dir():
            candidates.extend(
                _candidate(job_dir, path)
                for path in sorted(local_root.rglob("*.mp4"))
                if path.resolve() not in protected
                and path.resolve() != (candidate.resolve() if candidate else None)
            )
        return _family(
            candidates,
            retained=[
                path.relative_to(job_dir).as_posix()
                if path.is_relative_to(job_dir)
                else path.relative_to(job_dir.parent).as_posix()
                for path in sorted(protected)
                if path.is_file()
            ],
            reason=(
                "current_plus_one_rollback: retain the master, one rollback, "
                "review, and chosen patch"
            ),
        )

    active = None
    for report_path in sorted(
        job_dir.glob("quality_retake/*/edit/*report.json"),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    ):
        report = _load_json(report_path)
        candidate = report.get("candidate") or {}
        baseline = report.get("baseline") or {}
        candidate_path = _job_path(job_dir, candidate.get("path"))
        rollback_path = _job_path(
            job_dir,
            report.get("rollback") or baseline.get("path"),
        )
        if (
            str(report.get("decision") or "").upper() == "PASS"
            and candidate_path is not None
            and rollback_path is not None
            and candidate_path.is_file()
            and rollback_path.is_file()
            and candidate.get("sha256") == final_hash
            and _sha256(candidate_path) == final_hash
            and baseline.get("sha256") == _sha256(rollback_path)
        ):
            active = (report_path, report, candidate_path, rollback_path)
            break
    if active is None:
        return _family([], reason="no hash-bound passing local retake for the current master")

    report_path, report, candidate_path, rollback_path = active
    protected = {
        final_video.resolve(),
        rollback_path.resolve(),
        report_path.resolve(),
    }
    generated_patch = _job_path(
        job_dir,
        (report.get("generated_patch") or {}).get("path"),
    )
    if generated_patch is not None and generated_patch.is_file():
        protected.add(generated_patch.resolve())

    candidates = []
    if candidate_path.resolve() != final_video.resolve():
        candidates.append(_candidate(job_dir, candidate_path))
    archive = job_dir / "final" / "archive"
    if archive.is_dir():
        candidates.extend(
            _candidate(job_dir, path)
            for path in sorted(archive.glob("*.mp4"))
            if path.resolve() not in protected
        )

    baseline_hash = _sha256(rollback_path)
    for prior_report_path in job_dir.glob("edit/*/*repair_report.json"):
        prior = _load_json(prior_report_path)
        if (
            str(prior.get("overall") or "").upper() != "PASS"
            or prior.get("output_master_sha256") != baseline_hash
        ):
            continue
        for path in sorted(prior_report_path.parent.glob("*.mp4")):
            if "replacement" in path.name:
                protected.add(path.resolve())
            elif path.resolve() not in protected:
                candidates.append(_candidate(job_dir, path))

    retained = [
        path.relative_to(job_dir).as_posix()
        for path in sorted(protected)
        if path.is_file()
    ]
    return _family(
        candidates,
        retained=retained,
        reason="retain current master, one rollback, chosen repair interval, and reports",
    )


def managed_families(job_dir):
    return {
        "source_composition_cache": _source_composition_family(job_dir),
        "image_candidates": _image_candidate_family(job_dir),
        "generation_debug": _generation_transient_family(job_dir),
        "subtitle_normalization": _subtitle_transient_family(job_dir),
        "local_repair_media": _local_repair_family(job_dir),
    }


class _BoundedReplacement:
    def __init__(self, job_dir, paths, prefix, history_root, history_base, job_id):
        self.job_dir = job_dir
        self.paths = paths
        self.prefix = prefix
        self.job_id = job_id
        self.history_root = history_root
        self.history_base = history_base
        _reject_symlink_components(self.history_base, self.history_root)
        self.rollback_path = self.history_root / "rollback" / prefix
        self.pending_path = self.history_root / ".pending" / prefix
        self.entries = []

    def begin(self):
        if self.pending_path.exists():
            raise RuntimeError(
                f"unfinished artifact replacement requires inspection: {self.pending_path}"
            )
        moved = []
        try:
            for path in self.paths:
                if not path.exists():
                    continue
                relative = path.relative_to(self.job_dir)
                files = _files_under(path)
                self.entries.append(
                    {
                        "path": relative.as_posix(),
                        "files": len(files),
                        "bytes": sum(child.stat().st_size for child in files),
                    }
                )
                destination = self.pending_path / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(destination))
                moved.append((path, destination))
        except BaseException:
            for original, destination in reversed(moved):
                original.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(destination), str(original))
            _remove_path(self.pending_path)
            raise

    def rollback(self):
        for path in self.paths:
            _remove_path(path)
        for entry in self.entries:
            original = self.job_dir / entry["path"]
            staged = self.pending_path / entry["path"]
            if staged.exists():
                original.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(staged), str(original))
        _remove_path(self.pending_path)
        try:
            self.pending_path.parent.rmdir()
        except OSError:
            pass

    def commit(self):
        previous = self.history_root / ".previous" / self.prefix
        if previous.exists():
            raise RuntimeError(
                f"unfinished rollback rotation requires inspection: {previous}"
            )
        self.rollback_path.parent.mkdir(parents=True, exist_ok=True)
        if self.rollback_path.exists():
            previous.parent.mkdir(parents=True, exist_ok=True)
            self.rollback_path.rename(previous)
        try:
            self.pending_path.rename(self.rollback_path)
        except BaseException:
            if previous.exists():
                previous.rename(self.rollback_path)
            raise
        _remove_path(previous)
        try:
            previous.parent.rmdir()
        except OSError:
            pass
        try:
            self.pending_path.parent.rmdir()
        except OSError:
            pass

        _write_json(
            self.history_root / "manifests" / f"{self.prefix}_latest.json",
            {
                "version": 1,
                "job_id": self.job_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "retained_versions": 1,
                "rollback_path": self.rollback_path.relative_to(
                    self.history_base
                ).as_posix(),
                "entries": self.entries,
                "total_files": sum(entry["files"] for entry in self.entries),
                "total_bytes": sum(entry["bytes"] for entry in self.entries),
            },
        )


def artifact_replacement_scope(function):
    """Commit staged replacements on success and restore them on failure."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        replacements = []
        token = ACTIVE_REPLACEMENTS.set(replacements)
        try:
            result = function(*args, **kwargs)
        except BaseException:
            for replacement in reversed(replacements):
                replacement.rollback()
            raise
        finally:
            ACTIVE_REPLACEMENTS.reset(token)
        for replacement in replacements:
            replacement.commit()
        return result

    return wrapped


def stage_bounded_replacement(job_dir, paths, prefix):
    """Stage current outputs for one rollback version inside an active scope."""

    job_dir = Path(job_dir).resolve()
    if job_dir.parent.name == "output":
        job_id = job_dir.name
        history_base = job_dir.parent
        history_root = history_base / ".history" / job_id
    elif job_dir.name == "work" and job_dir.parent.name.startswith("job-"):
        job_id = job_dir.parent.name
        history_base = job_dir.parents[2]
        history_root = (
            history_base
            / ".viral-replica"
            / "state"
            / "artifact-history"
            / job_id
        )
    else:
        raise ValueError(
            "job_dir must be output/<job-id> or jobs/<job-id>/work"
        )
    if not SAFE_PREFIX.fullmatch(prefix):
        raise ValueError("rollback prefix must be a safe name")
    replacements = ACTIVE_REPLACEMENTS.get()
    if replacements is None:
        raise RuntimeError("bounded replacement requires artifact_replacement_scope")

    managed_paths = [Path(path).resolve() for path in paths]
    existing = [path for path in managed_paths if path.exists()]
    if not existing:
        return None
    for path in managed_paths:
        try:
            path.relative_to(job_dir)
        except ValueError as exc:
            raise ValueError(f"managed output is outside the Job: {path}") from exc

    replacement = _BoundedReplacement(
        job_dir,
        managed_paths,
        prefix,
        history_root,
        history_base,
        job_id,
    )
    replacement.begin()
    replacements.append(replacement)
    return replacement.rollback_path


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def preview_job(job_dir, exclude_paths=(), diagnose_duplicates=False):
    job_dir = Path(job_dir).resolve()
    if not job_dir.is_dir():
        raise FileNotFoundError(f"Job directory does not exist: {job_dir}")

    excluded = {Path(path).resolve() for path in exclude_paths if path}
    files = sorted(
        path
        for path in job_dir.rglob("*")
        if path.is_file() and path.resolve() not in excluded
    )
    duplicate_groups = []
    if diagnose_duplicates:
        by_size = defaultdict(list)
        for path in files:
            by_size[path.stat().st_size].append(path)
        for size, candidates in by_size.items():
            if not size or len(candidates) < 2:
                continue
            by_hash = defaultdict(list)
            for path in candidates:
                by_hash[_sha256(path)].append(path)
            for digest, matches in by_hash.items():
                if len(matches) < 2:
                    continue
                duplicate_groups.append(
                    {
                        "sha256": digest,
                        "bytes_each": size,
                        "copies": len(matches),
                        "reclaimable_bytes": size * (len(matches) - 1),
                        "paths": [
                            path.relative_to(job_dir).as_posix() for path in matches
                        ],
                    }
                )

    deprecated = job_dir / "deprecated"
    archives = (
        sorted(
            (
                path
                for path in deprecated.iterdir()
                if path.name.startswith("pre_seedance_pack_")
            ),
            key=lambda path: (path.stat().st_mtime_ns, path.name),
        )
        if deprecated.is_dir()
        else []
    )
    keep = archives[-1] if archives else None
    reclaim = archives[:-1]
    duplicate_groups.sort(
        key=lambda group: group["reclaimable_bytes"],
        reverse=True,
    )
    archive_sizes = {path: _path_bytes(path) for path in archives}
    families = managed_families(job_dir)
    managed_reclaimable = sum(
        family["reclaimable_bytes"] for family in families.values()
    )
    completed = (job_dir / "final" / "final_video.mp4").is_file()
    budget_bytes = (250 if completed else 150) * MIB
    return {
        "version": 2,
        "mode": "dry_run",
        "job_dir": str(job_dir),
        "total_files": len(files),
        "total_bytes": sum(path.stat().st_size for path in files),
        "legacy_pack_archives": {
            "found": len(archives),
            "keep": keep.relative_to(job_dir).as_posix() if keep else None,
            "candidates": [
                {
                    "path": path.relative_to(job_dir).as_posix(),
                    "bytes": archive_sizes[path],
                }
                for path in reclaim
            ],
            "reclaimable_bytes": sum(archive_sizes[path] for path in reclaim),
        },
        "exact_duplicates": {
            "mode": "diagnostic" if diagnose_duplicates else "not_scanned",
            "groups_total": len(duplicate_groups),
            "groups": duplicate_groups,
            "reclaimable_bytes": sum(
                group["reclaimable_bytes"] for group in duplicate_groups
            ),
        },
        "managed_families": families,
        "managed_reclaimable_bytes": managed_reclaimable,
        "storage_budget": {
            "class": "completed" if completed else "pre_generation",
            "budget_bytes": budget_bytes,
            "current_bytes": sum(path.stat().st_size for path in files),
            "projected_bytes_after_cleanup": (
                sum(path.stat().st_size for path in files)
                - sum(archive_sizes[path] for path in reclaim)
                - managed_reclaimable
            ),
        },
        "changes_made": False,
    }


def clean_from_preview(job_dir, preview_path, confirm_job_id):
    job_dir = Path(job_dir).resolve()
    preview_path = Path(preview_path).resolve()
    if confirm_job_id != job_dir.name:
        raise ValueError("cleanup confirmation does not match the Job id")
    report = json.loads(preview_path.read_text(encoding="utf-8"))
    if (
        report.get("mode") != "dry_run"
        or report.get("changes_made") is not False
        or Path(report.get("job_dir", "")).resolve() != job_dir
    ):
        raise ValueError("cleanup preview does not match the requested Job")

    current = preview_job(job_dir, exclude_paths=(preview_path,))
    expected = report["legacy_pack_archives"]
    actual = current["legacy_pack_archives"]
    expected_paths = [item["path"] for item in expected["candidates"]]
    actual_paths = [item["path"] for item in actual["candidates"]]
    if (
        expected.get("keep") != actual.get("keep")
        or expected_paths != actual_paths
        or expected.get("reclaimable_bytes") != actual.get("reclaimable_bytes")
        or report.get("managed_families", {}) != current.get("managed_families", {})
    ):
        raise ValueError("cleanup preview is stale; generate a new preview")

    keep = expected.get("keep")
    targets = []
    for relative in expected_paths:
        relative_path = Path(relative)
        if (
            len(relative_path.parts) != 2
            or relative_path.parts[0] != "deprecated"
            or not relative_path.name.startswith("pre_seedance_pack_")
            or relative == keep
        ):
            raise ValueError(f"unsafe cleanup target in preview: {relative}")
        target = (job_dir / relative_path).resolve()
        if target.parent != (job_dir / "deprecated").resolve() or not target.is_dir():
            raise ValueError(f"cleanup target is missing or outside deprecated: {relative}")
        targets.append(target)

    managed_targets = []
    for family_name, family in (report.get("managed_families") or {}).items():
        for item in family.get("candidates") or []:
            relative = Path(item.get("path") or "")
            target = (job_dir / relative).resolve()
            try:
                target.relative_to(job_dir)
            except ValueError as exc:
                raise ValueError(
                    f"managed cleanup target escapes the Job: {relative}"
                ) from exc
            safe = False
            if family_name == "source_composition_cache":
                safe = (
                    len(relative.parts) == 2
                    and relative.parts[0] == "source-composition"
                    and target.parent
                    == (job_dir / "source-composition").resolve()
                    and target.is_dir()
                )
            elif family_name == "image_candidates":
                safe = (
                    len(relative.parts) == 3
                    and relative.parts[:2] == ("image-batch", "candidates")
                    and target.parent
                    == (job_dir / "image-batch" / "candidates").resolve()
                    and target.is_file()
                )
            elif family_name == "generation_debug":
                safe = (
                    relative.as_posix()
                    in {
                        "generation/debug_preflight",
                        "generation/debug_preflight_bound",
                    }
                    and target.is_dir()
                )
            elif family_name == "subtitle_normalization":
                normalization = (
                    job_dir
                    / "subtitle_removal"
                    / "provider"
                    / "normalization_tests"
                ).resolve()
                repair_analysis = (
                    job_dir
                    / "subtitle_removal"
                    / "local_label_repair_analysis"
                ).resolve()
                safe = (
                    target == normalization
                    and target.is_dir()
                ) or (
                    target.parent == repair_analysis
                    and target.is_file()
                    and "test" in target.name
                    and target.suffix.lower() == ".mp4"
                )
            elif family_name == "local_repair_media":
                safe = (
                    target.is_file()
                    and target.suffix.lower() == ".mp4"
                    and (
                        target.parent
                        == (job_dir / "final" / "archive").resolve()
                        or (
                            relative.parts[0] == "edit"
                            and len(relative.parts) >= 3
                        )
                        or (
                            relative.parts[0] == "quality_retake"
                            and len(relative.parts) >= 4
                        )
                        or (
                            relative.parts[0] == "local_repair"
                            and len(relative.parts) >= 2
                        )
                    )
                )
            if not safe:
                raise ValueError(
                    f"unsafe {family_name} cleanup target: {relative}"
                )
            managed_targets.append(target)

    removed_bytes = int(expected.get("reclaimable_bytes") or 0) + sum(
        int(item.get("bytes") or 0)
        for family in (report.get("managed_families") or {}).values()
        for item in family.get("candidates") or []
    )
    for target in targets:
        shutil.rmtree(target)
    for target in managed_targets:
        _remove_path(target)
    result = {
        "version": 1,
        "mode": "cleanup",
        "job_id": job_dir.name,
        "removed_directories": len(targets) + len(managed_targets),
        "removed_bytes": removed_bytes,
        "kept": keep,
        "removed_managed_paths": [
            target.relative_to(job_dir).as_posix()
            for target in managed_targets
        ],
        "changes_made": True,
    }
    audit_path = (
        job_dir.parent
        / ".history"
        / job_dir.name
        / "manifests"
        / "cleanup_latest.json"
    )
    _reject_symlink_components(job_dir.parent, audit_path)
    _write_json(
        audit_path,
        {
            **result,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    preview = subparsers.add_parser("preview")
    preview.add_argument("--job-dir", required=True, type=Path)
    preview.add_argument("--out", type=Path)
    preview.add_argument("--diagnose-duplicates", action="store_true")
    preview.add_argument("--fail-on-budget", action="store_true")
    cleanup = subparsers.add_parser("cleanup")
    cleanup.add_argument("--job-dir", required=True, type=Path)
    cleanup.add_argument("--preview", required=True, type=Path)
    cleanup.add_argument("--confirm-job-id", required=True)
    migration = subparsers.add_parser("migrate-subtitle-cleanup")
    migration.add_argument("--job-dir", required=True, type=Path)
    migration.add_argument("--source-video", required=True, type=Path)
    migration.add_argument("--output-video", required=True, type=Path)
    migration.add_argument("--confirm-job-id", required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "preview":
            report = preview_job(
                args.job_dir,
                exclude_paths=(args.out,),
                diagnose_duplicates=args.diagnose_duplicates,
            )
        elif args.command == "cleanup":
            report = clean_from_preview(
                args.job_dir,
                args.preview,
                args.confirm_job_id,
            )
        else:
            report = migrate_subtitle_cleanup(
                args.job_dir,
                args.source_video,
                args.output_video,
                args.confirm_job_id,
            )
    except (FileNotFoundError, KeyError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.command == "preview" and args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if (
        args.command == "preview"
        and args.fail_on_budget
        and report["storage_budget"]["projected_bytes_after_cleanup"]
        > report["storage_budget"]["budget_bytes"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
