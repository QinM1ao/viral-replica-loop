#!/usr/bin/env python3
"""Compile independent pre-Seedance Part packets and merge them once."""

import argparse
import hashlib
import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import stage_execution


MAX_WORKERS = 4


@dataclass(frozen=True)
class CompiledFile:
    relative_path: str
    sha256: str


@dataclass(frozen=True)
class CompiledPart:
    part_id: str
    metadata: dict
    files: tuple[CompiledFile, ...]


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _frozen_snapshot(paths):
    snapshot = {}
    for raw_path in paths:
        path = Path(raw_path)
        if not path.is_file():
            raise FileNotFoundError(f"frozen compiler input is missing: {path}")
        snapshot[path.resolve()] = _sha256(path)
    return snapshot


def _compile_packet(part_id, packet_dir, compile_one):
    metadata = compile_one(part_id, packet_dir)
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise TypeError(f"{part_id} compiler metadata must be a dict")
    files = tuple(
        CompiledFile(
            relative_path=path.relative_to(packet_dir).as_posix(),
            sha256=_sha256(path),
        )
        for path in sorted(packet_dir.rglob("*"))
        if path.is_file()
    )
    return CompiledPart(part_id=part_id, metadata=metadata, files=files)


def _validate_merge(job_dir, compiled_packets, packet_dirs):
    owners = {}
    merge_items = []
    for compiled, packet_dir in zip(compiled_packets, packet_dirs):
        for compiled_file in compiled.files:
            relative_path = Path(compiled_file.relative_path)
            owner = owners.get(relative_path)
            if owner is not None:
                raise ValueError(
                    "Part packet output collision: "
                    f"{relative_path} is owned by both {owner} and {compiled.part_id}"
                )
            owners[relative_path] = compiled.part_id
            destination = job_dir / relative_path
            if destination.exists():
                raise ValueError(f"Part packet destination already exists: {destination}")
            source = packet_dir / relative_path
            if not source.is_file() or _sha256(source) != compiled_file.sha256:
                raise RuntimeError(
                    f"Part packet output changed before merge: {source}"
                )
            merge_items.append((source, destination))
    return merge_items


def _rollback_created(job_dir, created):
    for path in reversed(created):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        parent = path.parent
        while parent != job_dir:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent


def _is_within(path, parent):
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def validate_compilation_manifest(job_dir, manifest_path=None):
    job_dir = Path(job_dir).resolve()
    manifest_path = (
        Path(manifest_path).resolve()
        if manifest_path
        else job_dir / "seedance" / "part_compilation_manifest.json"
    )
    issues = []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "overall": "FAIL",
            "manifest": str(manifest_path),
            "issues": [f"manifest unavailable: {exc}"],
        }
    if manifest.get("version") != 1:
        issues.append("manifest version must be 1")
    director_plan = job_dir / "seedance" / "director_plan.json"
    try:
        director = json.loads(director_plan.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        director = {}
        issues.append(f"director plan unavailable: {exc}")
    else:
        if manifest.get("director_plan_sha256") != _sha256(director_plan):
            issues.append("director plan hash does not match compilation")

    expected_parts = [
        str(item.get("id") or "")
        for item in director.get("parts") or []
    ]
    actual_parts = [
        str(item.get("part_id") or "")
        for item in manifest.get("parts") or []
    ]
    if not expected_parts or actual_parts != expected_parts:
        issues.append("compiled Part order does not match director plan")

    seen_files = set()
    for frozen in manifest.get("frozen_inputs") or []:
        path = Path(str(frozen.get("path") or ""))
        if not path.is_absolute():
            path = job_dir.parents[1] / path
        path = path.resolve()
        if not path.is_file() or _sha256(path) != frozen.get("sha256"):
            issues.append(f"frozen input changed or is missing: {path}")

    for part in manifest.get("parts") or []:
        part_id = str(part.get("part_id") or "")
        declared = set()
        for item in part.get("files") or []:
            relative = Path(str(item.get("path") or ""))
            path = (job_dir / relative).resolve()
            if (
                relative.is_absolute()
                or not _is_within(path, job_dir)
                or not path.is_file()
                or _sha256(path) != item.get("sha256")
            ):
                issues.append(f"{part_id} compiled file changed or is invalid: {relative}")
                continue
            relative_name = relative.as_posix()
            if relative_name in seen_files:
                issues.append(f"compiled file is owned by multiple Parts: {relative_name}")
            seen_files.add(relative_name)
            declared.add(relative_name)
        metadata = part.get("metadata") or {}
        required = [
            metadata.get("prompt_path"),
            metadata.get("audio_path"),
            metadata.get("request_path"),
        ]
        required.extend(
            f"seedance_web_final/{value}"
            for value in metadata.get("web_uploads") or []
        )
        for relative_name in filter(None, required):
            if relative_name not in declared:
                issues.append(
                    f"{part_id} metadata path is not hash-bound in files: {relative_name}"
                )

    return {
        "overall": "PASS" if not issues else "FAIL",
        "manifest": str(manifest_path),
        "director_plan": str(director_plan),
        "parts": actual_parts,
        "issues": issues,
    }


def compile_and_merge(
    job_dir,
    part_ids,
    compile_one,
    *,
    max_workers=MAX_WORKERS,
    frozen_inputs=(),
):
    """Compile each Part in isolation, then merge successful packets in stable order."""

    job_dir = Path(job_dir)
    ordered_part_ids = list(part_ids)
    if not ordered_part_ids:
        return []
    if len(set(ordered_part_ids)) != len(ordered_part_ids):
        raise ValueError("Part ids must be unique")
    if any(
        not isinstance(part_id, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", part_id)
        for part_id in ordered_part_ids
    ):
        raise ValueError("Part ids must be safe nonempty names")
    worker_count = min(max(1, int(max_workers)), MAX_WORKERS, len(ordered_part_ids))
    frozen_inputs = tuple(frozen_inputs)
    frozen_before = _frozen_snapshot(frozen_inputs)
    job_dir = job_dir.resolve()
    if job_dir.parent.name != "output":
        raise ValueError("job_dir must be under the workspace output directory")
    root = job_dir.parents[1]
    staging_parent = job_dir / ".pre_seedance_pack_staging"
    staging_parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix="run_", dir=staging_parent))
    try:
        packet_dirs = [
            staging_root / "packets" / f"{index:04d}_{part_id}"
            for index, part_id in enumerate(ordered_part_ids, start=1)
        ]
        packets = [
            {
                "packet_id": part_id,
                "executor_kind": "agent",
                "task": f"Compile only the sealed Pre-Seedance packet for {part_id}.",
                "depends_on": [],
                "allowed_write_roots": [str(packet_dir)],
                "completion_path": str(
                    staging_root / "completions" / f"{part_id}.json"
                ),
            }
            for part_id, packet_dir in zip(ordered_part_ids, packet_dirs)
        ]
        plan = stage_execution.seal_plan(
            root,
            {
                "schema_version": 1,
                "job_id": job_dir.name,
                "stage": "pre_seedance_part_compile",
                "packets": packets,
            },
        )
        compiled_by_part = {}

        def dispatch(packet):
            part_id = packet["packet_id"]
            packet_dir = Path(packet["allowed_write_roots"][0])
            compiled = _compile_packet(
                part_id,
                packet_dir,
                compile_one,
            )
            compiled_by_part[part_id] = compiled
            return {
                "status": "PASS",
                "outputs": [
                    packet_dir / item.relative_path
                    for item in compiled.files
                ],
            }

        report = stage_execution.execute_plan(
            root,
            plan,
            dispatcher=dispatch,
            max_workers=worker_count,
        )
        if report["overall"] != "PASS":
            errors = "; ".join(
                str(item.get("error") or f"{item['packet_id']} {item['status']}")
                for item in report["completions"]
                if item["status"] != "PASS"
            )
            frozen_paths = tuple(
                str(path)
                for raw_path in frozen_inputs
                for path in (
                    Path(raw_path).absolute(),
                    Path(raw_path).resolve(),
                )
            )
            if any(path in errors for path in frozen_paths):
                raise RuntimeError(
                    "frozen input changed during Part compilation "
                    f"(write blocked): {errors}"
                )
            raise RuntimeError(f"Part compilation failed: {errors}")
        compiled_packets = [
            compiled_by_part[part_id]
            for part_id in ordered_part_ids
        ]
        merge_items = _validate_merge(job_dir, compiled_packets, packet_dirs)
        if _frozen_snapshot(frozen_inputs) != frozen_before:
            raise RuntimeError("frozen input changed during Part compilation")
        created = []
        try:
            for source, destination in merge_items:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                created.append(destination)
            if _frozen_snapshot(frozen_inputs) != frozen_before:
                raise RuntimeError("frozen input changed during Part merge")
        except Exception:
            _rollback_created(job_dir, created)
            raise
        return compiled_packets
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)
        try:
            staging_parent.rmdir()
        except OSError:
            pass


def main():
    parser = argparse.ArgumentParser(
        description="Validate a hash-bound Pre-Seedance Part compilation manifest."
    )
    parser.add_argument("--job-dir", required=True, type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--out-json", required=True, type=Path)
    parser.add_argument("--out-md", required=True, type=Path)
    args = parser.parse_args()
    report = validate_compilation_manifest(args.job_dir, args.manifest)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Pre-Seedance Part Compilation QC",
        "",
        f"- Overall: **{report['overall']}**",
        f"- Manifest: `{report['manifest']}`",
        "",
        "## Issues",
        "",
    ]
    lines.extend(
        f"- {issue}" for issue in report["issues"]
    )
    if not report["issues"]:
        lines.append("- None.")
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if report["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
