#!/usr/bin/env python3
"""Run the installed Thin Parity Plugin through one clean no-spend smoke."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from typing import Any


PROGRESS = [
    "看懂原片",
    "改好分镜",
    "写视频脚本",
    "生成视频",
    "质检交付",
]
ADAPTER_ENTRIES = (
    "assets",
    "jobs.csv",
    "output",
    "rules",
    "run_outer_sandbox_tool.py",
    "tools",
)
STATE_ADAPTER_BRIDGES = (
    "assets",
    "output",
    "references",
)


class SmokeStop(RuntimeError):
    pass


def _load_smoke_engine(plugin_root: Path) -> Any:
    path = (
        plugin_root
        / "engine"
        / "smoke"
        / "pre_seedance_no_spend.py"
    )
    spec = importlib.util.spec_from_file_location(
        "viral_replica_pre_seedance_no_spend",
        path,
    )
    if spec is None or spec.loader is None:
        raise SmokeStop(f"private no-spend engine is unavailable: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_projection(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _supported_host() -> dict[str, Any]:
    missing: list[str] = []
    if platform.system() != "Darwin":
        missing.append("macOS")
    if platform.machine().lower() not in {"arm64", "aarch64"}:
        missing.append("Apple Silicon")
    commands: dict[str, str] = {}
    for name in ("codex", "ffmpeg", "ffprobe"):
        resolved = shutil.which(name)
        if resolved is None:
            missing.append(name)
        else:
            commands[name] = str(Path(resolved).resolve())
    sandbox = Path("/usr/bin/sandbox-exec")
    if not sandbox.is_file():
        missing.append("macOS sandbox-exec")
    try:
        import PIL
    except ImportError:
        missing.append("Pillow in the active Python runtime")
        pillow_version = None
    else:
        pillow_version = str(PIL.__version__)
    if missing:
        raise SmokeStop(
            "Supported Host dependency check failed: "
            + ", ".join(missing)
            + ". Install or authorize the missing host capability before "
            "running a real Job; this smoke never installs dependencies."
        )
    return {
        "system": platform.system(),
        "architecture": platform.machine(),
        "python": sys.version.split()[0],
        "pillow": pillow_version,
        "commands": commands,
        "sandbox_exec": str(sandbox),
        "dynamic_install_performed": False,
        "service_authorization": (
            "not_required_for_sealed_zero_spend_fixture; "
            "real provider work stops when process-scoped authorization is missing"
        ),
    }


def _validate_plugin(plugin_root: Path) -> None:
    validator = plugin_root / "scripts" / "validate-package.py"
    result = subprocess.run(
        [str(validator), str(plugin_root)],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise SmokeStop(
            "installed package validation failed: "
            + (result.stderr or result.stdout).strip()
        )
    skills = sorted(
        path.name
        for path in (plugin_root / "skills").iterdir()
        if path.is_dir()
    )
    if skills != [
        "minimax-h3-replica",
        "seedance-25-replica",
        "seedance-run",
        "video-shot-refinement",
        "video-subtitle-removal",
        "viral-replica",
    ]:
        raise SmokeStop(f"unexpected Customer Skill surface: {skills}")


def _specialist_smokes(
    plugin_root: Path,
    fixture_root: Path,
    workspace: Path,
    run_workspace: Path,
    behavior: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    source = fixture_root / "core" / "source_4s.mkv"
    master = fixture_root / "finalization" / "subtitle-clean.mp4"
    source_before = _sha256(source)
    master_before = _sha256(master)
    shot_public = (
        plugin_root / "skills" / "video-shot-refinement" / "SKILL.md"
    ).read_text(encoding="utf-8")
    subtitle_public = (
        plugin_root / "skills" / "video-subtitle-removal" / "SKILL.md"
    ).read_text(encoding="utf-8")
    import run_next_loop_round as runner

    cost_policy, _ = runner.load_cost_policy(plugin_root / "engine")
    approval_context = runner.approval_context_for(
        run_workspace,
        {"id": "job-001"},
        {},
        cost_policy,
        types.SimpleNamespace(
            planned_task_count=1,
            approval_source_message="",
            approval_recorded=False,
            approval_scope="",
            approval_task_count=0,
            generation_intent="quality_retake",
            approve_mediakit_subtitle_retry=False,
        ),
    )
    boundary_reason, _ = runner.cost_stop_reason(
        status="generation_approved",
        next_stage="quality_retake",
        rule={"cost_class": "expensive_generation"},
        job_state={},
        cost_policy=cost_policy,
        paid_markers=("generation",),
        allow_paid=False,
        approval_context=approval_context,
    )
    approval_reason, _ = runner.cost_stop_reason(
        status="generation_approved",
        next_stage="quality_retake",
        rule={"cost_class": "expensive_generation"},
        job_state={},
        cost_policy=cost_policy,
        paid_markers=("generation",),
        allow_paid=True,
        approval_context=approval_context,
    )

    clean_branch = next(
        row
        for row in behavior["branch_rows"]
        if row["case_id"] == "subtitle-clean-classification"
    )
    subtitle_root = (
        run_workspace
        / "branches"
        / "subtitle-clean"
        / "output"
        / "job-001"
        / "subtitle_removal"
    )
    detection_path = subtitle_root / "subtitle_detection.json"
    detection_qc_path = subtitle_root / "detection_qc.json"
    detection = json.loads(detection_path.read_text(encoding="utf-8"))
    detection_qc = json.loads(
        detection_qc_path.read_text(encoding="utf-8")
    )
    frames = detection.get("evidence_frames") or []
    frame_evidence_valid = bool(frames)
    for frame in frames:
        path = Path(str(frame.get("path") or "")).resolve()
        try:
            path.relative_to(run_workspace.resolve())
        except ValueError:
            frame_evidence_valid = False
            break
        if (
            not path.is_file()
            or frame.get("sha256") != _sha256(path)
        ):
            frame_evidence_valid = False
            break
    duration = float(detection.get("duration_seconds") or 0)
    timestamps = [
        float(frame.get("timestamp_seconds") or 0)
        for frame in frames
    ]
    full_timeline = (
        bool(timestamps)
        and timestamps[0] == 0
        and timestamps[-1] >= duration - 0.125
    )
    checker = detection.get("checker") or {}
    checks = {
        "video-shot-refinement": {
            "public_entry": "Video Shot Refinement" in shot_public,
            "bounded_input": "bounded" in shot_public.lower(),
            "production_boundary_executed": True,
            "approval_boundary": boundary_reason
            == "expensive generation requires --allow-paid",
            "approval_record_boundary": approval_reason
            == "expensive generation requires explicit approval record",
            "input_protected": source_before == _sha256(source),
            "paid_task_count": 0,
            "production_policy_function": (
                "run_next_loop_round.cost_stop_reason"
            ),
            "boundary_reason": boundary_reason,
            "approval_record_reason": approval_reason,
            "conclusion": "STOP before provider submit without repair approval",
        },
        "video-subtitle-removal": {
            "public_entry": "Video Subtitle Removal" in subtitle_public,
            "production_boundary_executed": True,
            "clean_branch": (
                clean_branch["result"] == "PASS"
                and clean_branch["actual"]["conclusion"] == "PASS"
                and clean_branch["actual"]["mediakit_task_count"] == 0
            ),
            "detection_qc_passed": detection_qc.get("overall") == "PASS",
            "classification_bound": (
                detection.get("classification") == "clean"
                and detection.get("finishing_master_sha256")
                == master_before
            ),
            "frame_evidence_valid": frame_evidence_valid,
            "full_timeline": full_timeline,
            "independent_checker": checker.get("reviewer")
            == "independent_product_fixture_checker",
            "input_protected": master_before == _sha256(master),
            "paid_task_count": 0,
            "classification": detection.get("classification"),
            "checker": checker.get("reviewer"),
            "evidence_frame_count": len(frames),
            "detection_report": str(detection_path),
            "detection_qc": str(detection_qc_path),
            "conclusion": "clean fixture stops with no MediaKit submit",
        },
    }
    output: dict[str, dict[str, Any]] = {}
    for name, result in checks.items():
        passed = all(
            value is True
            for key, value in result.items()
            if key
            in {
                "public_entry",
                "bounded_input",
                "clean_branch",
                "approval_boundary",
                "approval_record_boundary",
                "detection_qc_passed",
                "classification_bound",
                "frame_evidence_valid",
                "full_timeline",
                "independent_checker",
                "input_protected",
                "production_boundary_executed",
            }
        )
        if not passed:
            raise SmokeStop(f"{name} boundary smoke failed: {result}")
        output[name] = {"overall": "PASS", **result}
        _write_json(
            workspace / "specialists" / f"{name}.json",
            output[name],
        )
    return output


def _remove_parity_adapter(canonical_workspace: Path) -> None:
    for name in ADAPTER_ENTRIES:
        path = canonical_workspace / name
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_dir():
                    child.chmod(0o755)
                elif child.is_file():
                    child.chmod(0o644)
            path.chmod(0o755)
            shutil.rmtree(path)
    state_root = canonical_workspace / ".viral-replica" / "state"
    for name in STATE_ADAPTER_BRIDGES:
        bridge = state_root / name
        if bridge.is_symlink():
            bridge.unlink()
        elif (
            name == "output"
            and bridge.is_dir()
            and all(child.is_symlink() for child in bridge.iterdir())
        ):
            for child in bridge.iterdir():
                child.unlink()
            bridge.rmdir()
        elif bridge.exists():
            raise SmokeStop(
                f"refusing to remove non-adapter resume state: {bridge}"
            )


def _restore_canonical_resume_state(
    canonical_workspace: Path,
) -> dict[str, str]:
    job_id = "job-001"
    job_root = canonical_workspace / "jobs" / job_id
    intake = json.loads(
        (job_root / "input" / "intake.json").read_text(encoding="utf-8")
    )
    reference_fields = {
        "video_path": (
            str(intake["source_video"]["path"]),
            "videos",
        ),
        "product_assets": (
            str(intake["product_assets"]),
            "products",
        ),
        "audio_assets": (
            str(intake["audio_assets"]),
            "audio",
        ),
    }
    restored: dict[str, str] = {}
    for field, (raw_path, collection) in reference_fields.items():
        path = Path(raw_path).resolve()
        expected_root = (
            canonical_workspace / "references" / collection
        ).resolve()
        try:
            path.relative_to(expected_root)
        except ValueError as exc:
            raise SmokeStop(
                f"canonical {field} escaped imported references: {path}"
            ) from exc
        if not path.is_file():
            raise SmokeStop(
                f"canonical {field} is unavailable for resume: {path}"
            )
        restored[field] = str(path)

    jobs_path = canonical_workspace / ".viral-replica" / "state" / "jobs.csv"
    with jobs_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    matches = [row for row in rows if row.get("id") == job_id]
    if len(matches) != 1:
        raise SmokeStop(
            f"canonical resume expected one {job_id} state row"
        )
    active_row = matches[0]
    checkpoint_artifact = Path(active_row["last_artifact"]).resolve()
    try:
        checkpoint_artifact.relative_to((job_root / "work").resolve())
    except ValueError as exc:
        raise SmokeStop(
            "canonical resume checkpoint escaped the active Job"
        ) from exc
    if not checkpoint_artifact.is_file():
        raise SmokeStop(
            f"canonical resume checkpoint is unavailable: "
            f"{checkpoint_artifact}"
        )
    interrupted_after_status = str(active_row["status"])
    active_row.update(
        {
            "workflow_run_id": f"canonical-{job_id}",
            **restored,
            "person_assets": str(intake["person_assets"]),
            "output_dir": str(job_root / "work"),
        }
    )
    temporary = jobs_path.with_name(f".{jobs_path.name}.resume.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, jobs_path)
    return {
        **restored,
        "person_assets": str(intake["person_assets"]),
        "product_name": str(intake["product_name"]),
        "handoff_mode": str(intake["handoff_mode"]),
        "notes": str(intake["notes"]),
        "interrupted_after_status": interrupted_after_status,
        "checkpoint_artifact": str(checkpoint_artifact),
        "checkpoint_artifact_sha256": _sha256(checkpoint_artifact),
    }


def _resume_public_job(
    plugin_root: Path,
    canonical_workspace: Path,
    smoke_engine: Any,
) -> dict[str, Any]:
    job_work = canonical_workspace / "jobs" / "job-001" / "work"
    before = _tree_projection(job_work)
    resume_inputs = _restore_canonical_resume_state(canonical_workspace)
    _remove_parity_adapter(canonical_workspace)
    interruption_path = (
        canonical_workspace
        / ".viral-replica"
        / "state"
        / "smoke-interruption.json"
    )
    _write_json(
        interruption_path,
        {
            "schema_version": 1,
            "kind": "sealed_process_boundary",
            "job_id": "job-001",
            "status": resume_inputs["interrupted_after_status"],
            "checkpoint_artifact": resume_inputs["checkpoint_artifact"],
            "checkpoint_artifact_sha256": resume_inputs[
                "checkpoint_artifact_sha256"
            ],
        },
    )
    command = [
        sys.executable,
        str(plugin_root / "scripts" / "run-canonical-job.py"),
        "--workspace",
        str(canonical_workspace),
        "--video",
        resume_inputs["video_path"],
        "--product-name",
        resume_inputs["product_name"],
        "--product-assets",
        resume_inputs["product_assets"],
        "--person-assets",
        resume_inputs["person_assets"],
        "--audio-assets",
        resume_inputs["audio_assets"],
        "--handoff-mode",
        resume_inputs["handoff_mode"],
        "--notes",
        resume_inputs["notes"],
    ]
    sandbox_profile = smoke_engine.build_sandbox_profile(
        engine_root=plugin_root / "engine",
        fixture_root=plugin_root / "assets" / "fixtures" / "v1",
        workspace=canonical_workspace,
        target_root=plugin_root,
    )
    result = subprocess.run(
        [
            "/usr/bin/sandbox-exec",
            "-p",
            sandbox_profile,
            *command,
        ],
        cwd=canonical_workspace,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0 or "Resumed job-001" not in result.stdout:
        raise SmokeStop(
            "public Job resume failed: "
            + (result.stderr or result.stdout).strip()
        )
    if (
        "required assets missing" in result.stdout
        or "Outcome type: `COST_GATE`" not in result.stdout
        or "- Submitted task count: `0`" not in result.stdout
    ):
        raise SmokeStop(
            "public Job resume did not stop at the generation approval "
            "boundary: "
            + result.stdout.strip()
        )
    after = _tree_projection(job_work)
    changed_completed_artifacts = sorted(
        path
        for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    )
    if changed_completed_artifacts:
        raise SmokeStop(
            "resumed Job changed completed stage artifacts instead of "
            "continuing from the safe checkpoint: "
            + ", ".join(changed_completed_artifacts)
        )
    return {
        "result": "PASS",
        "interruption_simulated": interruption_path.is_file(),
        "interrupted_after_status": resume_inputs[
            "interrupted_after_status"
        ],
        "checkpoint_artifact": resume_inputs["checkpoint_artifact"],
        "checkpoint_artifact_sha256": resume_inputs[
            "checkpoint_artifact_sha256"
        ],
        "changed_completed_artifact_count": len(
            changed_completed_artifacts
        ),
        "replayed_stage_count": len(changed_completed_artifacts),
        "replayed_external_work_count": 0,
        "external_work_evidence": (
            "public resume returned COST_GATE with Submitted task count 0 "
            "inside a deny-network sandbox"
        ),
        "runner_output": result.stdout.strip(),
    }


def run_smoke(
    *,
    plugin_root: Path,
    workspace: Path,
    report_path: Path,
) -> dict[str, Any]:
    plugin_root = plugin_root.resolve()
    workspace = workspace.resolve()
    report_path = report_path.resolve()
    if workspace.exists() and any(workspace.iterdir()):
        raise SmokeStop(f"clean smoke Workspace is not empty: {workspace}")
    if report_path != workspace / report_path.name:
        raise SmokeStop("smoke report must be directly inside its Workspace")
    try:
        workspace.relative_to(plugin_root)
    except ValueError:
        pass
    else:
        raise SmokeStop("smoke Workspace overlaps the installed Plugin")

    host = _supported_host()
    _validate_plugin(plugin_root)
    workspace.mkdir(parents=True, exist_ok=True)
    temporary_root = workspace / ".tmp"
    temporary_root.mkdir()
    for name in ("TMPDIR", "TMP", "TEMP"):
        os.environ[name] = str(temporary_root)
    tempfile.tempdir = str(temporary_root)
    fixture_root = plugin_root / "assets" / "fixtures" / "v1"
    smoke_engine = _load_smoke_engine(plugin_root)
    run = smoke_engine.run_target(
        target_name="plugin",
        run_number=1,
        engine_root=plugin_root / "engine",
        fixture_root=fixture_root,
        out_dir=workspace,
        handoff_mode="web",
    )
    behavior = run["_behavior"]
    if behavior["final_status"] != "seedance_inputs_prepared":
        raise SmokeStop(
            "no-spend run did not reach Pre-Seedance Handoff: "
            + behavior["final_status"]
        )
    side_effects = behavior["side_effects"]
    expected_zero = (
        "real_task_count",
        "paid_task_count",
        "media_generation_task_count",
        "unmatched_request_count",
        "network_attempt_count",
        "recorder_fallback_count",
        "forbidden_write_count",
    )
    nonzero = {
        key: side_effects[key]
        for key in expected_zero
        if side_effects[key] != 0
    }
    if nonzero:
        raise SmokeStop(f"provider or boundary side effect recorded: {nonzero}")

    run_workspace = Path(run["report_path"]).parent
    canonical_workspace = run_workspace / "actual-intake"
    resume = _resume_public_job(
        plugin_root,
        canonical_workspace,
        smoke_engine,
    )
    specialist_smokes = _specialist_smokes(
        plugin_root,
        fixture_root,
        workspace,
        run_workspace,
        behavior,
    )
    job_work = canonical_workspace / "jobs" / "job-001" / "work"
    inspection_paths = {
        "handoff": str(
            run_workspace / "handoff" / "pre_seedance_handoff.json"
        ),
        "image": str(job_work / "final-images" / "part1_seedance_ref.png"),
        "prompt": str(job_work / "seedance" / "seedance_part1_prompt.txt"),
        "audio": str(
            job_work / "audio-boundary" / "part1_reference_audio.mp3"
        ),
        "manifest": str(
            job_work / "visual-assets" / "approved_visual_manifest.json"
        ),
        "qc": str(job_work / "checks" / "pre_seedance_pack_gate_review.md"),
        "smoke_report": str(report_path),
    }
    missing = [
        f"{name}: {path}"
        for name, path in inspection_paths.items()
        if name != "smoke_report" and not Path(path).is_file()
    ]
    if missing:
        raise SmokeStop("missing inspection artifact: " + ", ".join(missing))

    report = {
        "schema_version": 1,
        "overall": "PASS",
        "claim": "本机可用、行为等效的轻量插件 MVP",
        "customer_ready": False,
        "final_status": behavior["final_status"],
        "progress": PROGRESS,
        "host": host,
        "effect_contract": {
            "replication_mode": "source_locked",
            "change_policy": "necessary_only",
            "engine_contract": behavior["engine_contract"],
            "stage_order": behavior["stage_order"],
            "gate_conclusions": behavior["artifacts"]["gate_conclusions"],
        },
        "provider_recorder": {
            "real_task_count": side_effects["real_task_count"],
            "paid_task_count": side_effects["paid_task_count"],
            "media_generation_task_count": side_effects[
                "media_generation_task_count"
            ],
            "unmatched_request_count": side_effects[
                "unmatched_request_count"
            ],
            "unregistered_outbound_attempt_count": side_effects[
                "network_attempt_count"
            ],
            "recorder_fallback_count": side_effects[
                "recorder_fallback_count"
            ],
        },
        "resume": resume,
        "specialist_smokes": specialist_smokes,
        "inspection_paths": inspection_paths,
        "release_scope": {
            "legacy_baseline_changed": False,
            "previous_passing_package_changed": False,
            "g00_g09_claimed": False,
            "private_release_claimed": False,
        },
    }
    _write_json(report_path, report)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin-root", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--report", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = run_smoke(
            plugin_root=Path(args.plugin_root),
            workspace=Path(args.workspace),
            report_path=Path(args.report),
        )
    except Exception as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 2
    for label, state in zip(
        PROGRESS,
        ("PASS", "PASS", "PASS", "STOP before paid generation", "WAIT"),
    ):
        print(f"{label}: {state}")
    print(f"PASS {report['claim']}")
    for name, path in report["inspection_paths"].items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
