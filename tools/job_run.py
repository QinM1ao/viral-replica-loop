#!/usr/bin/env python3
"""Durable Stage Run / Job Run coordinator.

The coordinator owns continuation and retry policy. Stage workers stay injected
so the same policy can drive local commands or an agent-backed stage executor.
"""

from dataclasses import dataclass, replace
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from typing import Callable, Optional, Tuple

from lifecycle_registry import LifecycleRegistry


RUN_CHECKPOINT_SCHEMA_VERSION = 2
IMAGE_STAGES = {"image_sample", "image_batch", "image_batch_qc"}
SEMANTIC_OUTCOMES = {"SEMANTIC_QC", "VISUAL_WARNING"}
HARD_BLOCKERS = {
    "missing_required_input",
    "paid_approval_required",
    "state_conflict",
    "stale_or_wrong_job_binding",
    "unusable_artifact",
}
EXTERNAL_SUBMISSION_STAGES = {
    "source_blueprint",
    "image_sample",
    "image_batch",
    "generation",
    "subtitle_removal",
}
APPROVAL_REQUIRED_STAGES = {"generation"}


@dataclass(frozen=True)
class StageRequest:
    job_id: str
    stage: str
    attempt: int
    idempotency_key: str
    authorization: str
    scope: str = "stage"


@dataclass(frozen=True)
class StageArtifact:
    artifact: str
    next_stage: str
    usable: bool = True


@dataclass(frozen=True)
class CheckResult:
    passed: bool
    reason: str = ""
    blocker: str = ""
    retry_scopes: Tuple[str, ...] = ()

    @classmethod
    def pass_(cls) -> "CheckResult":
        return cls(passed=True)


@dataclass(frozen=True)
class StageResult:
    status: str
    artifact: str
    next_stage: str
    usable: bool = True
    outcome_type: str = "PASS"
    reason: str = ""
    blocker: str = ""
    retry_scopes: Tuple[str, ...] = ()

    @classmethod
    def pass_(cls, artifact: str, next_stage: str) -> "StageResult":
        return cls(
            status="PASS",
            artifact=artifact,
            next_stage=next_stage,
        )


@dataclass(frozen=True)
class JobRunReport:
    status: str
    job_id: str
    current_stage: str
    completed_stages: Tuple[str, ...]
    warnings: Tuple[str, ...]
    checkpoint_path: Path
    reason: str = ""


def run_stage(
    *,
    request: StageRequest,
    make: Callable[[StageRequest], StageArtifact],
    deterministic_check: Callable[[StageArtifact], CheckResult],
    build_risk_ledger: Callable[[StageArtifact], bool],
    semantic_check: Callable[[StageArtifact], CheckResult],
    writeback: Callable[[StageResult], None],
) -> StageResult:
    """Complete one stage, invoking semantic review only when requested."""
    artifact = make(request)
    hard_check = deterministic_check(artifact)
    if not hard_check.passed:
        result = StageResult(
            status="FAIL",
            artifact=artifact.artifact,
            next_stage=request.stage,
            usable=False,
            outcome_type="HARD_FAILURE",
            reason=hard_check.reason,
            blocker=hard_check.blocker or "unusable_artifact",
        )
    elif build_risk_ledger(artifact):
        semantic = semantic_check(artifact)
        result = StageResult(
            status="PASS" if semantic.passed else "FAIL",
            artifact=artifact.artifact,
            next_stage=artifact.next_stage,
            usable=artifact.usable,
            outcome_type="PASS" if semantic.passed else "SEMANTIC_QC",
            reason=semantic.reason,
            retry_scopes=semantic.retry_scopes,
        )
    else:
        result = StageResult.pass_(
            artifact=artifact.artifact,
            next_stage=artifact.next_stage,
        )
    writeback(result)
    return result


def _checkpoint_path(root: Path, job_id: str) -> Path:
    return root / "output" / job_id / "checks" / "job_run_checkpoint.json"


def _write_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _checkpoint_artifact_issue(
    root: Path,
    job_id: str,
    stage: str,
    binding: dict,
) -> str:
    value = str(binding.get("path") or "").strip()
    if not value:
        return f"completed stage `{stage}` has no canonical artifact binding"
    raw = Path(value)
    path = raw if raw.is_absolute() else root / raw
    path = path.resolve()
    job_root = (root / "output" / job_id).resolve()
    if job_root != path and job_root not in path.parents:
        return f"completed stage `{stage}` artifact belongs to another Job"
    if not path.is_file() or path.is_symlink():
        return f"completed stage `{stage}` artifact is missing"
    expected = str(binding.get("sha256") or "")
    if not expected or _sha256_file(path) != expected:
        return f"completed stage `{stage}` artifact binding is stale"
    return ""


def run_job(
    *,
    root: Path,
    job_id: str,
    initial_stage: str,
    execute_stage: Callable[[StageRequest], StageResult],
    writeback_stage: Optional[
        Callable[[StageRequest, StageResult], str]
    ] = None,
    validate_retry_scope: Optional[Callable[[str], bool]] = None,
    checkpoint_path: Optional[Path] = None,
    approved_paid_stages: Tuple[str, ...] = (),
    lifecycle_registry: Optional[LifecycleRegistry] = None,
) -> JobRunReport:
    """Run passing stages continuously until delivery."""
    root = Path(root).resolve()
    lifecycle_registry = lifecycle_registry or LifecycleRegistry.load(
        Path(__file__).resolve().parents[1]
    )
    writeback_stage = writeback_stage or (
        lambda _request, result: result.next_stage
    )
    validate_retry_scope = validate_retry_scope or (
        lambda scope: bool(scope and scope != "stage")
    )
    checkpoint_path = checkpoint_path or _checkpoint_path(root, job_id)
    if checkpoint_path.is_file():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint.get("job_id") != job_id:
            raise ValueError("job run checkpoint belongs to a different job")
        completed = list(checkpoint.get("completed_stages") or [])
        warnings = list(checkpoint.get("warnings") or [])
        stage = str(checkpoint.get("current_stage") or initial_stage)
        artifacts = dict(checkpoint.get("artifacts") or {})
        abandoned_attempts = list(
            checkpoint.get("abandoned_external_attempts") or []
        )
        single_attempt_consumed = set(
            checkpoint.get("single_attempt_consumed") or []
        )
        in_flight = checkpoint.get("in_flight") or {}
        if (
            in_flight.get("stage") == stage
            and in_flight.get("external_submission") is True
        ):
            return JobRunReport(
                status="STOPPED",
                job_id=job_id,
                current_stage=stage,
                completed_stages=tuple(completed),
                warnings=tuple(warnings),
                checkpoint_path=checkpoint_path,
                reason=(
                    "external submission state is ambiguous; reconcile the "
                    "existing request before resuming"
                ),
            )
        for completed_stage in completed:
            issue = _checkpoint_artifact_issue(
                root,
                job_id,
                completed_stage,
                artifacts.get(completed_stage) or {},
            )
            if issue:
                return JobRunReport(
                    status="STOPPED",
                    job_id=job_id,
                    current_stage=stage,
                    completed_stages=tuple(completed),
                    warnings=tuple(warnings),
                    checkpoint_path=checkpoint_path,
                    reason=issue,
                )
    else:
        completed = []
        warnings = []
        stage = initial_stage
        artifacts = {}
        abandoned_attempts = []
        single_attempt_consumed = set()

    while not lifecycle_registry.is_terminal(stage):
        if stage == "generation" and stage in single_attempt_consumed:
            return JobRunReport(
                status="STOPPED",
                job_id=job_id,
                current_stage=stage,
                completed_stages=tuple(completed),
                warnings=tuple(warnings),
                checkpoint_path=checkpoint_path,
                reason=(
                    "generation single attempt was already consumed; a new "
                    "explicit retake decision is required"
                ),
            )
        if stage == "generation_approval":
            return JobRunReport(
                status="STOPPED",
                job_id=job_id,
                current_stage=stage,
                completed_stages=tuple(completed),
                warnings=tuple(warnings),
                checkpoint_path=checkpoint_path,
                reason=(
                    "generation requires a recorded cost-gate approval before "
                    "Job Run can resume"
                ),
            )
        if (
            stage in APPROVAL_REQUIRED_STAGES
            and stage not in approved_paid_stages
        ):
            return JobRunReport(
                status="STOPPED",
                job_id=job_id,
                current_stage=stage,
                completed_stages=tuple(completed),
                warnings=tuple(warnings),
                checkpoint_path=checkpoint_path,
                reason=f"{stage} requires explicit paid approval",
            )
        stage_results = []
        final_request = None
        scopes = ("stage",)
        for attempt, scope in [(1, "stage")]:
            request = StageRequest(
                job_id=job_id,
                stage=stage,
                attempt=attempt,
                idempotency_key=f"{job_id}:{stage}:{attempt}:{scope}",
                authorization=(
                    "job_image_targeted_retry"
                    if stage in IMAGE_STAGES and attempt == 2
                    else "job_image_scope"
                    if stage in IMAGE_STAGES
                    else "explicit_paid_approval"
                    if stage in APPROVAL_REQUIRED_STAGES
                    else "free_stage"
                ),
                scope=scope,
            )
            _write_json_atomic(
                checkpoint_path,
                {
                    "schema_version": RUN_CHECKPOINT_SCHEMA_VERSION,
                    "job_id": job_id,
                    "current_stage": stage,
                    "completed_stages": completed,
                    "warnings": warnings,
                    "artifacts": artifacts,
                    "abandoned_external_attempts": abandoned_attempts,
                    "single_attempt_consumed": sorted(
                        single_attempt_consumed
                    ),
                    "in_flight": {
                        "stage": stage,
                        "attempt": attempt,
                        "idempotency_key": request.idempotency_key,
                        "external_submission": (
                            stage in EXTERNAL_SUBMISSION_STAGES
                        ),
                    },
                },
            )
            result = execute_stage(request)
            if stage == "generation":
                single_attempt_consumed.add(stage)
            final_request = request
            resolved_blocker = (
                result.blocker
                if result.blocker in HARD_BLOCKERS
                else "unusable_artifact"
                if not result.usable
                else ""
            )
            if resolved_blocker:
                if (
                    resolved_blocker == "state_conflict"
                    and stage in EXTERNAL_SUBMISSION_STAGES
                ):
                    if stage == "generation":
                        ambiguous_checkpoint = json.loads(
                            checkpoint_path.read_text(encoding="utf-8")
                        )
                        ambiguous_checkpoint["single_attempt_consumed"] = (
                            sorted(single_attempt_consumed)
                        )
                        _write_json_atomic(
                            checkpoint_path,
                            ambiguous_checkpoint,
                        )
                    return JobRunReport(
                        status="STOPPED",
                        job_id=job_id,
                        current_stage=stage,
                        completed_stages=tuple(completed),
                        warnings=tuple(warnings),
                        checkpoint_path=checkpoint_path,
                        reason=result.reason or resolved_blocker,
                    )
                _write_json_atomic(
                    checkpoint_path,
                    {
                        "schema_version": RUN_CHECKPOINT_SCHEMA_VERSION,
                        "job_id": job_id,
                        "current_stage": stage,
                        "completed_stages": completed,
                        "warnings": warnings,
                        "artifacts": artifacts,
                        "abandoned_external_attempts": abandoned_attempts,
                        "single_attempt_consumed": sorted(
                            single_attempt_consumed
                        ),
                        "last_result": {
                            "status": result.status,
                            "artifact": result.artifact,
                            "outcome_type": result.outcome_type,
                            "blocker": resolved_blocker,
                            "reason": result.reason,
                        },
                    },
                )
                return JobRunReport(
                    status="STOPPED",
                    job_id=job_id,
                    current_stage=stage,
                    completed_stages=tuple(completed),
                    warnings=tuple(warnings),
                    checkpoint_path=checkpoint_path,
                    reason=result.reason or resolved_blocker,
                )
            stage_results.append((scope, result))

        first_result = stage_results[0][1]
        if (
            stage in IMAGE_STAGES
            and first_result.outcome_type in SEMANTIC_OUTCOMES
        ):
            scopes = tuple(
                dict.fromkeys(first_result.retry_scopes)
            )
            if not scopes or not all(
                validate_retry_scope(scope) for scope in scopes
            ):
                warnings.append(
                    f"{stage}: targeted retry was skipped because failed "
                    "Part scopes were not bound; kept the original usable "
                    "candidate"
                )
                scopes = ()
            for scope in scopes:
                request = StageRequest(
                    job_id=job_id,
                    stage=stage,
                    attempt=2,
                    idempotency_key=f"{job_id}:{stage}:2:{scope}",
                    authorization="job_image_targeted_retry",
                    scope=scope,
                )
                _write_json_atomic(
                    checkpoint_path,
                    {
                        "schema_version": RUN_CHECKPOINT_SCHEMA_VERSION,
                        "job_id": job_id,
                        "current_stage": stage,
                        "completed_stages": completed,
                        "warnings": warnings,
                        "artifacts": artifacts,
                        "abandoned_external_attempts": abandoned_attempts,
                        "single_attempt_consumed": sorted(
                            single_attempt_consumed
                        ),
                        "in_flight": {
                            "stage": stage,
                            "attempt": 2,
                            "scope": scope,
                            "idempotency_key": request.idempotency_key,
                            "external_submission": True,
                        },
                    },
                )
                retry_result = execute_stage(request)
                final_request = request
                retry_blocker = (
                    retry_result.blocker
                    if retry_result.blocker in HARD_BLOCKERS
                    else "unusable_artifact"
                    if not retry_result.usable
                    else ""
                )
                if retry_blocker:
                    if retry_blocker == "state_conflict":
                        return JobRunReport(
                            status="STOPPED",
                            job_id=job_id,
                            current_stage=stage,
                            completed_stages=tuple(completed),
                            warnings=tuple(warnings),
                            checkpoint_path=checkpoint_path,
                            reason=retry_result.reason or retry_blocker,
                        )
                    warning = (
                        f"{stage}/{scope}: targeted retry was unusable; "
                        "kept the original usable candidate"
                    )
                    warnings.append(warning)
                    abandoned_attempts.append(
                        {
                            "stage": stage,
                            "scope": scope,
                            "idempotency_key": request.idempotency_key,
                            "blocker": retry_blocker,
                            "reason": retry_result.reason,
                        }
                    )
                    continue
                stage_results.append((scope, retry_result))

        result = stage_results[-1][1]
        failed_results = [
            (scope, value)
            for scope, value in stage_results[1:] or stage_results
            if value.status != "PASS"
        ]
        if failed_results:
            reasons = [
                f"{scope}: {value.reason or value.outcome_type}"
                for scope, value in failed_results
            ]
            result = replace(
                result,
                status="FAIL",
                outcome_type="SEMANTIC_QC",
                reason="; ".join(reasons),
            )
        for result_scope, stage_result in stage_results[1:] or stage_results:
            if stage_result.status != "PASS":
                warnings.append(
                    f"{stage}/{result_scope}: "
                    f"{stage_result.reason or stage_result.outcome_type}"
                )
        try:
            result = replace(
                result,
                next_stage=writeback_stage(final_request, result),
            )
        except (OSError, RuntimeError, ValueError) as exc:
            return JobRunReport(
                status="STOPPED",
                job_id=job_id,
                current_stage=stage,
                completed_stages=tuple(completed),
                warnings=tuple(warnings),
                checkpoint_path=checkpoint_path,
                reason=f"state writeback conflict: {exc}",
            )
        completed.append(stage)
        artifact_path = Path(result.artifact)
        if not artifact_path.is_absolute():
            artifact_path = root / artifact_path
        artifacts[stage] = {
            "path": result.artifact,
            "sha256": (
                _sha256_file(artifact_path)
                if artifact_path.is_file() and not artifact_path.is_symlink()
                else ""
            ),
        }
        stage = result.next_stage
        _write_json_atomic(
            checkpoint_path,
            {
                "schema_version": RUN_CHECKPOINT_SCHEMA_VERSION,
                "job_id": job_id,
                "current_stage": stage,
                "completed_stages": completed,
                "warnings": warnings,
                "artifacts": artifacts,
                "abandoned_external_attempts": abandoned_attempts,
                "single_attempt_consumed": sorted(
                    single_attempt_consumed
                ),
            },
        )

    delivered = stage == "done"
    return JobRunReport(
        status="DELIVERED" if delivered else "STOPPED",
        job_id=job_id,
        current_stage=stage,
        completed_stages=tuple(completed),
        warnings=tuple(warnings),
        checkpoint_path=checkpoint_path,
        reason="" if delivered else f"Job is terminal: {stage}",
    )


def _require_bool(payload: dict, key: str, default: Optional[bool] = None) -> bool:
    if key not in payload and default is not None:
        return default
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"stage executor field `{key}` must be boolean")
    return value


def _invoke_executor(
    arguments,
    root: Path,
    request: StageRequest,
    operation: str,
    **values,
) -> dict:
    payload = {
        "operation": operation,
        "root": str(root),
        "job_id": request.job_id,
        "stage": request.stage,
        "attempt": request.attempt,
        "scope": request.scope,
        "idempotency_key": request.idempotency_key,
        "authorization": request.authorization,
        **values,
    }
    completed = subprocess.run(
        arguments,
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            completed.stderr.strip()
            or f"{operation} executor exited {completed.returncode}"
        )
    result = json.loads(completed.stdout)
    if not isinstance(result, dict):
        raise ValueError(f"{operation} executor result must be an object")
    return result


def _validated_artifact(root: Path, job_id: str, value: str) -> str:
    root = root.resolve()
    raw = Path(str(value or ""))
    if not str(value or "").strip():
        raise ValueError("stage executor returned no artifact")
    artifact = raw if raw.is_absolute() else root / raw
    artifact = artifact.resolve()
    job_root = (root / "output" / job_id).resolve()
    if job_root != artifact and job_root not in artifact.parents:
        raise ValueError("stage artifact is outside the current Job")
    if not artifact.is_file() or artifact.is_symlink():
        raise ValueError("stage artifact is missing or unreadable")
    return str(artifact.relative_to(root))


def _active_image_retry_scopes(root: Path, job_id: str) -> Tuple[str, ...]:
    fanout = (
        root
        / "output"
        / job_id
        / "image-batch"
        / "fanout"
        / "fanout_plan.json"
    )
    if fanout.is_file():
        payload = json.loads(fanout.read_text(encoding="utf-8"))
        if str(payload.get("job_id") or job_id) != job_id:
            raise ValueError("image fanout plan belongs to another Job")
        parts = payload.get("required_parts") or []
        if isinstance(parts, list) and all(
            isinstance(part, str) and part.strip() for part in parts
        ):
            return tuple(dict.fromkeys(parts))
    contracts = (
        root / "output" / job_id / "image-batch" / "contracts"
    )
    parts = [
        path.name[: -len("_contract.json")]
        for path in sorted(contracts.glob("part*_contract.json"))
    ]
    return tuple(parts)


def _command_executor(
    root: Path,
    command: str,
) -> Callable[[StageRequest], StageResult]:
    root = root.resolve()
    arguments = shlex.split(command)
    if not arguments:
        raise ValueError("executor command cannot be empty")

    def execute(request: StageRequest) -> StageResult:
        try:
            def make(_request):
                payload = _invoke_executor(
                    arguments,
                    root,
                    request,
                    "maker",
                )
                artifact = _validated_artifact(
                    root,
                    request.job_id,
                    str(payload.get("artifact") or ""),
                )
                return StageArtifact(
                    artifact=artifact,
                    next_stage=str(payload.get("next_stage") or request.stage),
                    usable=_require_bool(payload, "usable", True),
                )

            def deterministic_check(artifact):
                payload = _invoke_executor(
                    arguments,
                    root,
                    request,
                    "deterministic_qc",
                    artifact=artifact.artifact,
                )
                return CheckResult(
                    passed=_require_bool(payload, "passed"),
                    reason=str(payload.get("reason") or ""),
                    blocker=str(payload.get("blocker") or ""),
                )

            def build_risk_ledger(artifact):
                payload = _invoke_executor(
                    arguments,
                    root,
                    request,
                    "risk_ledger",
                    artifact=artifact.artifact,
                )
                return _require_bool(payload, "semantic_review_required")

            def semantic_check(artifact):
                payload = _invoke_executor(
                    arguments,
                    root,
                    request,
                    "semantic_qc",
                    artifact=artifact.artifact,
                )
                scopes = payload.get("retry_scopes") or []
                if not isinstance(scopes, list) or not all(
                    isinstance(scope, str) and scope.strip()
                    for scope in scopes
                ):
                    raise ValueError(
                        "semantic_qc retry_scopes must be a string list"
                    )
                return CheckResult(
                    passed=_require_bool(payload, "passed"),
                    reason=str(payload.get("reason") or ""),
                    retry_scopes=tuple(scopes),
                )

            result = run_stage(
                request=request,
                make=make,
                deterministic_check=deterministic_check,
                build_risk_ledger=build_risk_ledger,
                semantic_check=semantic_check,
                writeback=lambda _result: None,
            )
            return result
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            return StageResult(
                status="STOP",
                artifact="",
                next_stage=request.stage,
                usable=False,
                outcome_type="HARD_FAILURE",
                blocker="state_conflict",
                reason=str(exc),
            )

    return execute


def _report_payload(report: JobRunReport) -> dict:
    return {
        "status": report.status,
        "job_id": report.job_id,
        "current_stage": report.current_stage,
        "completed_stages": list(report.completed_stages),
        "warnings": list(report.warnings),
        "checkpoint_path": str(report.checkpoint_path),
        "reason": report.reason,
    }


def _job_row(root: Path, job_id: str) -> dict:
    jobs_path = root / "jobs.csv"
    if not jobs_path.is_file():
        raise ValueError("jobs.csv is unavailable")
    with jobs_path.open(encoding="utf-8", newline="") as handle:
        matches = [
            row
            for row in csv.DictReader(handle)
            if str(row.get("id") or "").strip() == job_id
        ]
    if len(matches) != 1:
        raise ValueError(
            f"cannot reconstruct one unambiguous jobs.csv row for {job_id}"
        )
    return matches[0]


def _canonical_stage_for_job(root: Path, job_id: str) -> str:
    row = _job_row(root, job_id)
    status = str(row.get("status") or "").strip()
    registry = LifecycleRegistry.load(root)
    if registry.is_terminal(status):
        return status
    stage = registry.execution_stage(status)
    if stage is None:
        raise ValueError(f"no stage rule matches status `{status}`")
    return stage


def _runner_writeback(
    root: Path,
    request: StageRequest,
    result: StageResult,
) -> str:
    gate_result = "PASS" if result.usable else "FAIL"
    outcome_type = (
        "PASS"
        if result.status == "PASS"
        else "VISUAL_WARNING"
        if result.usable
        else "HARD_FAILURE"
    )
    command = [
        sys.executable,
        str(Path(__file__).with_name("run_next_loop_round.py")),
        "--root",
        str(root),
        "--job-id",
        request.job_id,
        "--self-audit",
        "--record-gate-result",
        gate_result,
        "--outcome-type",
        outcome_type,
        "--apply-transition",
        "--artifact",
        result.artifact,
    ]
    if outcome_type == "VISUAL_WARNING":
        command.extend(
            [
                "--why-not-fail",
                result.reason or "artifact remains usable for the next stage",
                "--advisory-usable-artifact",
            ]
        )
    if gate_result == "FAIL":
        command.extend(
            [
                "--failure-type",
                result.blocker or "unusable_artifact",
            ]
        )
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            completed.stderr.strip()
            or completed.stdout.strip()
            or "runner writeback failed"
        )
    return _canonical_stage_for_job(root, request.job_id)


def _recorded_paid_stages(root: Path, job_id: str) -> Tuple[str, ...]:
    state_path = root / "RUNNER_STATE.json"
    if not state_path.is_file():
        return ()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    job_state = (state.get("jobs") or {}).get(job_id) or {}
    approval = job_state.get("cost_approval") or {}
    approved = int(approval.get("approved_task_count") or 0)
    submitted = int(approval.get("submitted_task_count") or 0)
    history = job_state.get("gate_history") or []
    cost_gate_passed = any(
        str(event.get("stage") or "") == "generation_approval"
        and str(event.get("result") or "") == "PASS"
        for event in history
    )
    if approved > submitted and cost_gate_passed:
        return ("generation",)
    return ()


def _initial_stage_from_existing_state(root: Path, job_id: str) -> str:
    registry = LifecycleRegistry.load(root)
    checkpoint = _checkpoint_path(root, job_id)
    if checkpoint.is_file():
        payload = json.loads(checkpoint.read_text(encoding="utf-8"))
        if payload.get("job_id") != job_id:
            raise ValueError("job run checkpoint belongs to a different job")
        stage = str(payload.get("current_stage") or "").strip()
        if stage:
            if (root / "jobs.csv").is_file():
                declared = _canonical_stage_for_job(root, job_id)
                if declared != stage:
                    raise ValueError(
                        "checkpoint and jobs.csv disagree on current stage"
                    )
            return stage

    stage = _canonical_stage_for_job(root, job_id)
    if not registry.is_terminal(stage) and stage != "source_blueprint":
        row = _job_row(root, job_id)
        artifact = str(row.get("last_artifact") or "").strip()
        if not artifact:
            raise ValueError(
                "legacy Job has no canonical last_artifact to reconstruct from"
            )
        raw = Path(artifact)
        path = raw if raw.is_absolute() else root / raw
        path = path.resolve()
        job_root = (root / "output" / job_id).resolve()
        if (
            (job_root != path and job_root not in path.parents)
            or not path.is_file()
            or path.is_symlink()
        ):
            raise ValueError(
                "legacy Job canonical artifact is missing or belongs to "
                "another Job"
            )
    return stage


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one formal job continuously with durable checkpoints."
    )
    parser.add_argument("--root", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--initial-stage", default="")
    parser.add_argument("--executor-command", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    try:
        if not (root / "jobs.csv").is_file():
            raise ValueError("Job Run requires a formal jobs.csv Job")
        declared_stage = (
            _initial_stage_from_existing_state(root, args.job_id)
            if (root / "jobs.csv").is_file()
            or _checkpoint_path(root, args.job_id).is_file()
            else ""
        )
        requested_stage = args.initial_stage.strip()
        registry = LifecycleRegistry.load(root)
        if registry.is_terminal(declared_stage):
            initial_stage = declared_stage
        elif (
            requested_stage
            and declared_stage
            and requested_stage != declared_stage
        ):
            raise ValueError(
                "requested initial stage conflicts with current Job state"
            )
        else:
            initial_stage = requested_stage or declared_stage
        if not initial_stage:
            raise ValueError("initial stage is unavailable")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = JobRunReport(
            status="STOPPED",
            job_id=args.job_id,
            current_stage="state_conflict",
            completed_stages=(),
            warnings=(),
            checkpoint_path=_checkpoint_path(root, args.job_id),
            reason=str(exc),
        )
        print(
            json.dumps(
                _report_payload(report),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    writeback = lambda request, result: _runner_writeback(
        root,
        request,
        result,
    )
    report = run_job(
        root=root,
        job_id=args.job_id,
        initial_stage=initial_stage,
        execute_stage=_command_executor(
            root,
            args.executor_command,
        ),
        writeback_stage=writeback,
        validate_retry_scope=lambda scope: scope
        in set(_active_image_retry_scopes(root, args.job_id)),
        approved_paid_stages=_recorded_paid_stages(root, args.job_id),
        lifecycle_registry=registry,
    )
    print(json.dumps(_report_payload(report), ensure_ascii=False, indent=2))
    return 0 if report.status == "DELIVERED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
