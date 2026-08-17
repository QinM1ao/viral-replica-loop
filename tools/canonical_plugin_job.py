#!/usr/bin/env python3
"""Create or resume one Canonical Plugin Job in an explicit Workspace."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any

from canonical_execution_context import (
    CanonicalExecutionContext,
    ExecutionContextError,
    build_workflow_contract,
    paths_overlap,
)
from job_intake import (
    JOB_FIELDS,
    STORYBOARD_DERIVED_PERSON_ASSETS,
    discover_videos,
    file_sha256,
    formatted_duration,
    infer_handoff_mode,
    video_duration_seconds,
)
from product_profile import build_product_profile
from asr_transcribe import check_asr_provider


ALLOWED_WORKSPACE_ENTRIES = {
    ".viral-replica",
    "deliveries",
    "jobs",
    "references",
    "workspace.yaml",
}
WORKSPACE_MARKER = {
    "schema_version": "1",
    "workspace_kind": "viral-replica",
}
JOB_DIRECTORY_NAMES = {"input", "work", "qc", "delivery"}
SYSTEM_DIRECTORY_NAMES = {"README.md", "state", "cache", "runtime"}


class CanonicalLaunchError(ValueError):
    pass


@dataclass(frozen=True)
class ImportedReference:
    path: Path
    sha256: str


def _stable_json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _write_json_atomic(path: Path, payload: Any) -> None:
    _write_bytes_atomic(path, _stable_json_bytes(payload))


def _write_text_atomic(path: Path, text: str) -> None:
    _write_bytes_atomic(path, (text.rstrip("\n") + "\n").encode("utf-8"))


def _parse_workspace_marker(path: Path) -> dict[str, str]:
    marker = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise CanonicalLaunchError(
            f"Workspace marker is unreadable: {path}"
        ) from exc
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition(":")
        if not separator:
            raise CanonicalLaunchError(
                f"Workspace marker contains an unrecognized line: {line}"
            )
        marker[key.strip()] = value.strip()
    return marker


def _mode_is_writable(path: Path) -> bool:
    return bool(stat.S_IMODE(path.stat().st_mode) & 0o222)


def _validate_job_tree(workspace_root: Path) -> None:
    jobs_root = workspace_root / "jobs"
    if not jobs_root.exists():
        return
    if not jobs_root.is_dir() or jobs_root.is_symlink():
        raise CanonicalLaunchError(
            f"Workspace contains unrecognized content: {jobs_root}"
        )
    for entry in jobs_root.iterdir():
        if entry.name == "README.md":
            continue
        if (
            entry.is_dir()
            and not entry.is_symlink()
            and entry.name.startswith(".job-")
            and entry.name.endswith(".staging")
            and entry.name[5:-8].isdigit()
        ):
            continue
        if (
            not entry.is_dir()
            or entry.is_symlink()
            or not entry.name.startswith("job-")
            or not entry.name[4:].isdigit()
        ):
            raise CanonicalLaunchError(
                f"Workspace contains unrecognized content: {entry}"
            )
        unknown = {child.name for child in entry.iterdir()} - JOB_DIRECTORY_NAMES
        if unknown:
            raise CanonicalLaunchError(
                "Workspace contains unrecognized content: "
                + ", ".join(
                    str(entry / name) for name in sorted(unknown)
                )
            )
        for name in JOB_DIRECTORY_NAMES:
            child = entry / name
            if child.exists() and (
                not child.is_dir() or child.is_symlink()
            ):
                raise CanonicalLaunchError(
                    f"Workspace contains unrecognized content: {child}"
                )


def _validate_system_tree(workspace_root: Path) -> None:
    system_root = workspace_root / ".viral-replica"
    if not system_root.exists():
        return
    if not system_root.is_dir() or system_root.is_symlink():
        raise CanonicalLaunchError(
            f"Workspace contains unrecognized content: {system_root}"
        )
    unknown = {
        child.name for child in system_root.iterdir()
    } - SYSTEM_DIRECTORY_NAMES
    if unknown:
        raise CanonicalLaunchError(
            "Workspace contains unrecognized content: "
            + ", ".join(
                str(system_root / name) for name in sorted(unknown)
            )
        )
    readme = system_root / "README.md"
    if readme.exists() and (not readme.is_file() or readme.is_symlink()):
        raise CanonicalLaunchError(
            f"Workspace contains unrecognized content: {readme}"
        )
    for name in ("state", "cache", "runtime"):
        child = system_root / name
        if child.exists() and (
            not child.is_dir() or child.is_symlink()
        ):
            raise CanonicalLaunchError(
                f"Workspace contains unrecognized content: {child}"
            )


def _validate_reference_tree(workspace_root: Path) -> None:
    reference_root = workspace_root / "references"
    if not reference_root.exists():
        return
    if not reference_root.is_dir() or reference_root.is_symlink():
        raise CanonicalLaunchError(
            f"Workspace contains unrecognized content: {reference_root}"
        )
    for path in reference_root.rglob("*"):
        if path.is_symlink():
            raise CanonicalLaunchError(
                f"Workspace contains unrecognized content: {path}"
            )


def _validate_mutable_directories(workspace_root: Path) -> None:
    for relative in (
        "jobs",
        "deliveries",
        "references",
        "references/products",
        "references/people",
        "references/videos",
        "references/audio",
        ".viral-replica",
        ".viral-replica/state",
        ".viral-replica/cache",
        ".viral-replica/runtime",
    ):
        path = workspace_root / relative
        if not path.exists():
            continue
        if (
            not path.is_dir()
            or path.is_symlink()
            or not _mode_is_writable(path)
        ):
            raise CanonicalLaunchError(
                f"Workspace is not writable: {path}"
            )


def validate_workspace(plugin_root: Path, workspace_root: Path) -> bool:
    workspace_root = Path(workspace_root).expanduser()
    if not workspace_root.exists():
        raise CanonicalLaunchError(
            f"Workspace does not exist: {workspace_root}"
        )
    if not workspace_root.is_dir() or workspace_root.is_symlink():
        raise CanonicalLaunchError(
            f"Workspace must be one real directory: {workspace_root}"
        )
    workspace_root = workspace_root.resolve()
    if paths_overlap(plugin_root, workspace_root):
        raise CanonicalLaunchError(
            "Workspace overlaps Plugin Root; choose a separate directory"
        )
    for path in workspace_root.iterdir():
        if path.is_symlink():
            raise CanonicalLaunchError(
                f"Workspace contains unrecognized content: {path}"
            )
    entries = {path.name for path in workspace_root.iterdir()}
    unknown = entries - ALLOWED_WORKSPACE_ENTRIES
    if unknown:
        raise CanonicalLaunchError(
            "Workspace contains unrecognized content: "
            + ", ".join(sorted(unknown))
        )
    marker_path = workspace_root / "workspace.yaml"
    if entries and not marker_path.is_file():
        raise CanonicalLaunchError(
            "non-empty Workspace has no canonical workspace.yaml marker"
        )
    if marker_path.is_file():
        marker = _parse_workspace_marker(marker_path)
        for key, expected in WORKSPACE_MARKER.items():
            if marker.get(key) != expected:
                raise CanonicalLaunchError(
                    f"Workspace marker {key} must be {expected}"
                )
    _validate_job_tree(workspace_root)
    _validate_system_tree(workspace_root)
    _validate_reference_tree(workspace_root)
    _validate_mutable_directories(workspace_root)
    if not _mode_is_writable(workspace_root):
        raise CanonicalLaunchError(
            f"Workspace is not writable: {workspace_root}"
        )
    probe = workspace_root / ".viral-replica-workspace-write-probe"
    try:
        descriptor = os.open(
            probe,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        os.close(descriptor)
        probe.unlink()
    except OSError as exc:
        if probe.exists():
            probe.unlink()
        raise CanonicalLaunchError(
            f"Workspace is not writable: {workspace_root}"
        ) from exc
    return not entries


def initialize_workspace(plugin_root: Path, workspace_root: Path) -> None:
    template_root = plugin_root / "workspace-template"
    if not template_root.is_dir():
        raise CanonicalLaunchError(
            f"missing plugin resource: {template_root}; root fallback is forbidden"
        )
    for source in sorted(template_root.rglob("*")):
        relative = source.relative_to(template_root)
        target = workspace_root / relative
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            _write_bytes_atomic(target, source.read_bytes())
        else:
            raise CanonicalLaunchError(
                f"unsupported Workspace template resource: {source}"
            )
    for relative in (
        ".viral-replica/state",
        ".viral-replica/cache",
        ".viral-replica/runtime",
        "jobs",
        "deliveries",
        "references/products",
        "references/people",
        "references/videos",
        "references/audio",
    ):
        (workspace_root / relative).mkdir(parents=True, exist_ok=True)


def _reference_sha256(source: Path) -> str:
    source = Path(source)
    if source.is_symlink():
        raise CanonicalLaunchError(
            f"reference input cannot be a symbolic link: {source}"
        )
    if source.is_file():
        return file_sha256(source)
    if not source.is_dir():
        raise CanonicalLaunchError(f"reference input is unavailable: {source}")
    digest = hashlib.sha256()
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise CanonicalLaunchError(
                f"reference input cannot contain a symbolic link: {path}"
            )
        relative = path.relative_to(source).as_posix()
        if path.is_dir():
            digest.update(f"dir\0{relative}\0".encode("utf-8"))
        elif path.is_file():
            digest.update(f"file\0{relative}\0".encode("utf-8"))
            digest.update(bytes.fromhex(file_sha256(path)))
        else:
            raise CanonicalLaunchError(
                f"reference input contains unsupported content: {path}"
            )
    return digest.hexdigest()


def _import_reference(
    workspace_root: Path,
    collection: str,
    source: Path,
) -> ImportedReference:
    source = Path(source)
    digest = _reference_sha256(source)
    collection_root = workspace_root / "references" / collection
    collection_root.mkdir(parents=True, exist_ok=True)
    if (
        source.resolve().parent == collection_root.resolve()
        and source.name.startswith(f"{digest}-")
    ):
        return ImportedReference(source.resolve(), digest)

    target = collection_root / f"{digest}-{source.name}"
    if target.exists():
        if target.is_symlink() or _reference_sha256(target) != digest:
            raise CanonicalLaunchError(
                f"reference version conflicts with existing content: {target}"
            )
        return ImportedReference(target.resolve(), digest)

    staging = collection_root / f".{target.name}.staging"
    if staging.exists():
        if staging.is_dir() and not staging.is_symlink():
            shutil.rmtree(staging)
        else:
            staging.unlink()
    try:
        if source.is_dir():
            shutil.copytree(source, staging)
        else:
            shutil.copyfile(source, staging)
        if _reference_sha256(staging) != digest:
            raise CanonicalLaunchError(
                f"reference import verification failed: {source}"
            )
        os.replace(staging, target)
    finally:
        if staging.exists():
            if staging.is_dir() and not staging.is_symlink():
                shutil.rmtree(staging)
            else:
                staging.unlink()
    return ImportedReference(target.resolve(), digest)


def _read_jobs(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_jobs(path: Path, rows: list[dict[str, str]]) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        prefix=f".{path.name}.",
        dir=path.parent,
        delete=False,
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=JOB_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = handle.name
    try:
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _next_job_id(workspace_root: Path, rows: list[dict[str, str]]) -> str:
    numbers = []
    for row in rows:
        value = str(row.get("id") or "")
        if value.startswith("job-") and value[4:].isdigit():
            numbers.append(int(value[4:]))
    for path in (workspace_root / "jobs").glob("job-*"):
        if path.name[4:].isdigit():
            numbers.append(int(path.name[4:]))
    return f"job-{max(numbers, default=0) + 1:03d}"


def _intake_fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_stable_json_bytes(payload)).hexdigest()


def _resume_fingerprint(payload: dict[str, Any]) -> str:
    return _intake_fingerprint(payload)


def _resume_payload_from_intake(intake: dict[str, Any]) -> dict[str, Any]:
    target = intake.get("target_duration") or {}
    return {
        "source_video": intake.get("source_video") or {},
        "product_name": str(intake.get("product_name") or ""),
        "product_assets": str(intake.get("product_assets") or ""),
        "person_assets": str(intake.get("person_assets") or ""),
        "audio_assets": str(intake.get("audio_assets") or ""),
        "target_duration": (
            target.get("value") if target.get("explicitly_requested") else None
        ),
        "handoff_mode": str(intake.get("handoff_mode") or ""),
        "notes": str(intake.get("notes") or ""),
        "client_profile": str(intake.get("client_profile") or ""),
    }


def _existing_job_for_fingerprint(
    workspace_root: Path,
    fingerprint: str,
) -> tuple[str, Path] | None:
    for intake_path in sorted(
        (workspace_root / "jobs").glob("job-*/input/intake.json")
    ):
        try:
            intake = json.loads(intake_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        stored = intake.get("resume_fingerprint")
        if not stored:
            stored = _resume_fingerprint(_resume_payload_from_intake(intake))
        if stored == fingerprint:
            return intake_path.parents[1].name, intake_path.parents[1]
    return None


def _job_provenance(job_root: Path) -> dict[str, Any]:
    provenance_path = job_root / "input" / "job_provenance.json"
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise CanonicalLaunchError(
            f"existing Job provenance is unreadable: {provenance_path}"
        ) from exc
    if not str(provenance.get("plugin_version") or "").strip():
        raise CanonicalLaunchError(
            f"existing Job provenance has no plugin version: {provenance_path}"
        )
    if not str(provenance.get("workflow_contract_sha256") or "").strip():
        raise CanonicalLaunchError(
            f"existing Job provenance has no workflow contract: {provenance_path}"
        )
    return provenance


def _is_versioned_codex_cache(path: Path) -> bool:
    parts = Path(path).resolve().parts
    marker = (".codex", "plugins", "cache")
    return any(parts[index:index + len(marker)] == marker for index in range(len(parts)))


def _load_stable_resume_context(context_path: Path, job_root: Path):
    context = CanonicalExecutionContext.load(context_path)
    if _is_versioned_codex_cache(context.plugin_root):
        raise CanonicalLaunchError(
            "existing Job context uses an ephemeral Codex cache; "
            "resume requires a stable managed or compat plugin root"
        )
    provenance = _job_provenance(job_root)
    contract = context.workflow_contract
    if (
        provenance["plugin_version"] != contract.get("plugin_version")
        or provenance["workflow_contract_sha256"] != contract.get("sha256")
    ):
        raise CanonicalLaunchError(
            "existing Job context does not match its immutable provenance"
        )
    return context


def _initial_runner_state() -> dict[str, Any]:
    return {
        "version": 1,
        "retry_limit": 2,
        "updated_at": None,
        "jobs": {},
    }


def _write_initial_control_files(
    state_root: Path,
    job: dict[str, str],
) -> None:
    brief_path = state_root / "BRIEF.md"
    if not brief_path.exists():
        _write_text_atomic(
            brief_path,
            "\n".join(
                [
                    "# Viral Replica Brief",
                    "",
                    f"- Current Job: `{job['id']}`",
                    f"- Product: {job['product_name']}",
                    f"- Source: {job['video_path']}",
                    "- Workspace mode: Canonical Plugin Job",
                ]
            ),
        )
    state_path = state_root / "STATE.md"
    if not state_path.exists():
        _write_text_atomic(
            state_path,
            "\n".join(
                [
                    "# Loop State",
                    "",
                    "## Current Round",
                    "",
                    f"- Current task: `{job['id']}`",
                    "- Current stage: pending",
                    "- User-visible stage: 看懂原片",
                    "- Next: source blueprint",
                ]
            ),
        )
    runner_state_path = state_root / "RUNNER_STATE.json"
    if not runner_state_path.exists():
        _write_json_atomic(runner_state_path, _initial_runner_state())


def _canonical_intake(
    *,
    plugin_root: Path,
    workspace_root: Path,
    source_reference: ImportedReference,
    product_name: str,
    product_reference: ImportedReference,
    person_reference: ImportedReference | None,
    audio_reference: ImportedReference | None,
    target_duration: str | None,
    handoff_mode: str,
    notes: str,
    client_profile: str,
    workflow_contract: dict[str, Any],
) -> tuple[dict[str, str], bool]:
    state_root = workspace_root / ".viral-replica" / "state"
    jobs_path = state_root / "jobs.csv"
    source_video = source_reference.path
    source_digest = source_reference.sha256
    product_assets = product_reference.path
    person_assets = (
        str(person_reference.path)
        if person_reference
        else STORYBOARD_DERIVED_PERSON_ASSETS
    )
    audio_assets = (
        str(audio_reference.path)
        if audio_reference
        else "extract_from_original"
    )
    duration_value = (
        str(target_duration).strip()
        if target_duration is not None
        else formatted_duration(video_duration_seconds(source_video))
    )
    resume_payload = {
        "source_video": {
            "path": str(source_video),
            "sha256": source_digest,
        },
        "product_name": product_name,
        "product_assets": str(product_assets),
        "person_assets": person_assets,
        "audio_assets": audio_assets,
        "target_duration": target_duration,
        "handoff_mode": handoff_mode,
        "notes": notes,
        "client_profile": client_profile,
    }
    fingerprint_payload = {
        **resume_payload,
        "workflow_contract_sha256": workflow_contract["sha256"],
    }
    fingerprint = _intake_fingerprint(fingerprint_payload)
    resume_fingerprint = _resume_fingerprint(resume_payload)
    rows = _read_jobs(jobs_path)
    existing = _existing_job_for_fingerprint(
        workspace_root,
        resume_fingerprint,
    )
    if existing:
        job_id, job_root = existing
        _job_provenance(job_root)
        matching_rows = [row for row in rows if row.get("id") == job_id]
        if len(matching_rows) > 1:
            raise CanonicalLaunchError(
                f"Workspace has duplicate state rows for {job_id}"
            )
        if matching_rows:
            return matching_rows[0], True
    else:
        job_id = _next_job_id(workspace_root, rows)
        job_root = workspace_root / "jobs" / job_id

    row = {
        "id": job_id,
        "workflow_run_id": f"canonical-{job_id}",
        "status": "pending",
        "video_path": str(source_video),
        "product_name": product_name,
        "client_profile": client_profile,
        "product_assets": str(product_assets),
        "person_assets": person_assets,
        "audio_assets": audio_assets,
        "target_duration": duration_value,
        "handoff_mode": handoff_mode,
        "notes": notes,
        "output_dir": str(job_root / "work"),
        "last_artifact": "",
        "next_stage": "source_blueprint",
        "needs_user_confirmation": "false",
    }
    if existing:
        rows.append(row)
        _write_jobs(jobs_path, rows)
        return row, True

    staging_root = workspace_root / "jobs" / f".{job_id}.staging"
    if staging_root.exists():
        shutil.rmtree(staging_root)
    for relative in ("input", "work", "qc", "delivery"):
        (staging_root / relative).mkdir(parents=True, exist_ok=True)
    intake = {
        "schema_version": 1,
        "job_id": job_id,
        "intake_fingerprint": fingerprint,
        "resume_fingerprint": resume_fingerprint,
        "source_video": {
            "path": str(source_video),
            "sha256": source_digest,
        },
        "product_name": product_name,
        "product_assets": str(product_assets),
        "person_assets": person_assets,
        "audio_assets": audio_assets,
        "target_duration": {
            "value": duration_value,
            "explicitly_requested": target_duration is not None,
            "evidence": (
                {"source": "intake", "value": target_duration}
                if target_duration is not None
                else {
                    "source": "ffprobe",
                    "source_video_sha256": source_digest,
                }
            ),
        },
        "handoff_mode": handoff_mode,
        "notes": notes,
    }
    _write_json_atomic(staging_root / "input" / "intake.json", intake)
    profile = build_product_profile(plugin_root / "engine", row)
    _write_json_atomic(
        staging_root / "input" / "product_profile.json",
        profile,
    )
    _write_json_atomic(
        staging_root / "input" / "job_provenance.json",
        {
            "schema_version": 1,
            "plugin_version": workflow_contract["plugin_version"],
            "workflow_contract_sha256": workflow_contract["sha256"],
            "loaded_rules": profile["loaded_rules"],
            "reference_binding": {
                "source_video": {
                    "path": str(source_video),
                    "sha256": source_digest,
                },
                "product_assets": {
                    "path": str(product_assets),
                    "sha256": product_reference.sha256,
                },
                "person_assets": (
                    {"mode": STORYBOARD_DERIVED_PERSON_ASSETS}
                    if person_reference is None
                    else {
                        "path": person_assets,
                        "sha256": person_reference.sha256,
                    }
                ),
                "audio_assets": (
                    {"mode": "extract_from_original"}
                    if audio_reference is None
                    else {
                        "path": audio_assets,
                        "sha256": audio_reference.sha256,
                    }
                ),
            },
        },
    )
    os.replace(staging_root, job_root)
    rows.append(row)
    _write_jobs(jobs_path, rows)
    return row, False


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one Canonical Plugin Job in an explicit Workspace."
    )
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--prepare-runtime", action="store_true")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--video")
    source.add_argument("--video-dir")
    parser.add_argument("--product-name")
    parser.add_argument("--product-assets")
    parser.add_argument(
        "--person-assets",
        default=STORYBOARD_DERIVED_PERSON_ASSETS,
    )
    parser.add_argument("--audio-assets", default="extract_from_original")
    parser.add_argument("--target-duration")
    parser.add_argument(
        "--handoff-mode",
        choices=("auto", "web", "api", "both"),
        default="auto",
    )
    parser.add_argument("--notes", default="")
    parser.add_argument("--client-profile", default="")
    return parser


def run(plugin_root: Path, args: argparse.Namespace) -> int:
    plugin_root = Path(plugin_root).resolve()
    workspace_argument = Path(args.workspace).expanduser()
    if workspace_argument.is_symlink():
        raise CanonicalLaunchError(
            f"Workspace must be one real directory: {workspace_argument}"
        )
    workspace_root = workspace_argument.resolve()
    workflow_contract = build_workflow_contract(plugin_root)
    clean_workspace = validate_workspace(plugin_root, workspace_root)

    if args.prepare_runtime:
        if clean_workspace:
            initialize_workspace(plugin_root, workspace_root)
        else:
            (workspace_root / ".viral-replica" / "runtime").mkdir(
                parents=True,
                exist_ok=True,
            )
        print("首次准备：正在检查 ElevenLabs ASR 凭证配置…")
        provider = check_asr_provider()
        print(f"首次准备完成：{provider}；无需下载本地 ASR 模型")
        return 0

    if not (args.video or args.video_dir):
        raise CanonicalLaunchError("one source video is required")
    if not args.product_assets:
        raise CanonicalLaunchError("product assets are required")

    videos = discover_videos(
        args.video_dir or "",
        [args.video] if args.video else [],
    )
    if len(videos) != 1:
        raise CanonicalLaunchError(
            "the MVP launcher requires exactly one source video"
        )
    source_video = videos[0]
    product_name = str(args.product_name or "").strip()
    if not product_name:
        raise CanonicalLaunchError("product name is required")
    product_assets = Path(args.product_assets).expanduser().resolve()
    if not product_assets.exists():
        raise CanonicalLaunchError(
            f"product assets are unavailable: {product_assets}"
        )
    person_assets = str(args.person_assets or "").strip()
    if person_assets != STORYBOARD_DERIVED_PERSON_ASSETS:
        person_path = Path(person_assets).expanduser().resolve()
        if not person_path.exists():
            raise CanonicalLaunchError(
                f"person assets are unavailable: {person_path}"
            )
        person_assets = str(person_path)
    audio_assets = str(args.audio_assets or "").strip()
    if audio_assets != "extract_from_original":
        audio_path = Path(audio_assets).expanduser().resolve()
        if not audio_path.exists():
            raise CanonicalLaunchError(
                f"audio assets are unavailable: {audio_path}"
            )
        audio_assets = str(audio_path)
    if args.target_duration is not None and not args.target_duration.strip():
        raise CanonicalLaunchError("target duration cannot be empty")

    if clean_workspace:
        initialize_workspace(plugin_root, workspace_root)
    else:
        for relative in (
            ".viral-replica/state",
            ".viral-replica/cache",
            ".viral-replica/runtime",
            "jobs",
            "deliveries",
        ):
            (workspace_root / relative).mkdir(parents=True, exist_ok=True)

    state_root = workspace_root / ".viral-replica" / "state"
    lock_path = state_root / "launch.lock"
    with lock_path.open("w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        source_reference = _import_reference(
            workspace_root,
            "videos",
            source_video,
        )
        product_reference = _import_reference(
            workspace_root,
            "products",
            product_assets,
        )
        person_reference = None
        if person_assets != STORYBOARD_DERIVED_PERSON_ASSETS:
            person_reference = _import_reference(
                workspace_root,
                "people",
                Path(person_assets),
            )
        audio_reference = None
        if audio_assets != "extract_from_original":
            audio_reference = _import_reference(
                workspace_root,
                "audio",
                Path(audio_assets),
            )
        job, resumed = _canonical_intake(
            plugin_root=plugin_root,
            workspace_root=workspace_root,
            source_reference=source_reference,
            product_name=product_name,
            product_reference=product_reference,
            person_reference=person_reference,
            audio_reference=audio_reference,
            target_duration=args.target_duration,
            handoff_mode=infer_handoff_mode(
                args.handoff_mode,
                args.notes,
            ),
            notes=args.notes,
            client_profile=args.client_profile,
            workflow_contract=workflow_contract,
        )
        _write_initial_control_files(state_root, job)
        context = CanonicalExecutionContext(
            plugin_root=plugin_root,
            workspace_root=workspace_root,
            state_root=state_root,
            job_root=workspace_root / "jobs" / job["id"],
            job_id=job["id"],
            workflow_contract=workflow_contract,
        )
        context.validate()
        context_path = (
            state_root / f"execution-context-{job['id']}.json"
        )
        context_payload = context.as_dict()
        if context_path.exists():
            try:
                existing_context = json.loads(
                    context_path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError) as exc:
                raise CanonicalLaunchError(
                    f"existing Job context is unreadable: {context_path}"
                ) from exc
            if existing_context != context_payload:
                if not resumed:
                    raise CanonicalLaunchError(
                        f"existing Job context changed: {context_path}"
                    )
                context = _load_stable_resume_context(context_path, context.job_root)
        else:
            if resumed:
                provenance = _job_provenance(context.job_root)
                if (
                    provenance["plugin_version"]
                    != workflow_contract.get("plugin_version")
                    or provenance["workflow_contract_sha256"]
                    != workflow_contract.get("sha256")
                ):
                    raise CanonicalLaunchError(
                        "existing Job has no compatible execution context"
                    )
            _write_json_atomic(context_path, context_payload)

        runner = context.plugin_root / "engine" / "tools" / "run_next_loop_round.py"
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [
                sys.executable,
                str(runner),
                "--execution-context",
                str(context_path),
            ],
            text=True,
            capture_output=True,
            env=environment,
        )
    if result.stdout:
        print(result.stdout.rstrip())
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr.rstrip(), file=sys.stderr)
        print(
            "STOP: runner did not produce the first decision; "
            f"inspect {context_path}",
            file=sys.stderr,
        )
        return 2
    action = "Resumed" if resumed else "Created"
    print(f"{action} {job['id']}")
    print(f"Job input: {context.job_root / 'input' / 'intake.json'}")
    print(f"Runner decision: {state_root / 'RUNNER_LAST_DECISION.md'}")
    return 0


def main(plugin_root: Path, argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return run(plugin_root, args)
    except (
        CanonicalLaunchError,
        ExecutionContextError,
        OSError,
        ValueError,
    ) as exc:
        workspace = Path(args.workspace).expanduser().resolve()
        print(f"STOP: {exc}", file=sys.stderr)
        print(f"Inspection: {workspace}", file=sys.stderr)
        return 2
