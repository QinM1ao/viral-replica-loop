#!/usr/bin/env python3
"""Reserve, run, and merge isolated Seedance generation Part work."""

import argparse
import csv
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

try:
    from . import stage_execution
except ImportError:
    import stage_execution


DEFAULT_STAGE = "generation"
FANOUT_POLICY = "durable_reservation_then_part_fanout_then_serial_merge"
RUNNER_COMMAND = ("python3", "tools/seedance_taskcode_runner.py")
GENERATION_INTENTS = {
    "current_job",
    "failed_part_retry",
    "quality_retake",
}


class FanoutError(ValueError):
    """Raised when paid generation fanout would violate its reservation."""


def _write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as target:
            target.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            target.flush()
            os.fsync(target.fileno())
        os.replace(str(temporary), str(path))
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _load_json(path):
    with Path(path).open(encoding="utf-8") as source:
        return json.load(source)


def _resolve_path(root, value):
    path = Path(str(value))
    if path.is_absolute():
        return path.resolve()
    return (Path(root) / path).resolve()


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _part_id(value):
    raw = str(value or "").strip().lower()
    match = re.fullmatch(r"(?:part[\s_-]*)?(\d+)", raw)
    if not match:
        raise FanoutError(f"invalid part id: {value!r}")
    return f"part{int(match.group(1))}"


def _part_sort_key(value):
    match = re.fullmatch(r"part(\d+)", _part_id(value))
    return int(match.group(1))


def _generation_intent(value, scope="", attempt=None):
    normalized = re.sub(
        r"[\s-]+",
        "_",
        str(value or "").strip().lower(),
    ).strip("_")
    aliases = {
        "current": "current_job",
        "retry": "failed_part_retry",
        "targeted_retry": "failed_part_retry",
        "quality_retry": "quality_retake",
        "quality_retake_retry": "quality_retake",
    }
    normalized = aliases.get(normalized, normalized)
    if not normalized:
        if scope == "current_job" or attempt == 1:
            return "current_job"
        if scope == "targeted_retry" or attempt == 2:
            return "failed_part_retry"
    if normalized not in GENERATION_INTENTS:
        raise FanoutError(f"invalid generation intent: {value!r}")
    return normalized


def _job_dir(root, job_id):
    root = Path(root).resolve()
    jobs_path = root / "jobs.csv"
    if jobs_path.is_file():
        with jobs_path.open(newline="", encoding="utf-8") as source:
            for row in csv.DictReader(source):
                if row.get("id") == job_id and row.get("output_dir"):
                    return _resolve_path(root, row["output_dir"])
    return root / "output" / job_id


def _fanout_dir(root, job_id):
    return _job_dir(root, job_id) / "generation" / "fanout"


def _attempt_dir(root, job_id, attempt):
    base = _fanout_dir(root, job_id)
    return base if attempt == 1 else base / "attempt_2"


def _strip_markdown(value):
    return str(value or "").strip().strip("`").strip()


def _markdown_field(text, *labels):
    for line in text.splitlines():
        candidate = re.sub(r"^\s*-\s*", "", line).strip()
        for label in labels:
            match = re.match(
                rf"^{re.escape(label)}\s*:\s*(.+?)\s*$",
                candidate,
                flags=re.IGNORECASE,
            )
            if match:
                return _strip_markdown(match.group(1))
    return ""


def _parts_from_value(value):
    return [
        f"part{int(number)}"
        for number in re.findall(
            r"\bpart[\s_-]*(\d+)\b",
            str(value or ""),
            flags=re.IGNORECASE,
        )
    ]


def _json_paths_from_text(value):
    quoted = re.findall(r"`([^`]+\.json)`", str(value or ""))
    if quoted:
        return quoted
    return re.findall(
        r"(?:[A-Za-z]:)?[^\s,`]+\.json",
        str(value or ""),
    )


def _parse_markdown_approval(text):
    result = _markdown_field(text, "Result")
    if not result:
        match = re.search(
            r"(?ims)^##\s*Result\s*$\s*(?:`([^`]+)`|([A-Za-z_]+))",
            text,
        )
        if match:
            result = _strip_markdown(match.group(1) or match.group(2))
    if not result:
        explicit_status = _markdown_field(
            text,
            "Approval status",
            "Status",
            "Approved action",
        )
        has_explicit_denial = re.search(
            r"\b(?:not\s+approved|not\s+allowed|unapproved|denied|rejected)\b"
            r"|未批准|不允许|禁止|拒绝",
            explicit_status,
            flags=re.IGNORECASE,
        )
        if not has_explicit_denial and re.search(
            r"\b(?:approved|allowed|pass)\b|批准|允许|同意",
            explicit_status,
            flags=re.IGNORECASE,
        ):
            result = "PASS"

    scope = _markdown_field(text, "Approval scope", "Scope")
    normalized_scope = re.sub(r"[\s-]+", "_", scope.lower()).strip("_")
    if normalized_scope in {
        "current_job",
        "current_job_only",
        "current_explicit_job",
    }:
        normalized_scope = "current_job"

    raw_count = _markdown_field(
        text,
        "Approved task count",
        "Number of Seedance tasks",
    )
    count_match = re.search(r"\d+", raw_count)
    approved_parts = _parts_from_value(
        _markdown_field(
            text,
            "Expected Parts",
            "Approved Part",
            "Approved failed Parts",
            "Target",
        )
    )

    request_paths = []
    request_file = _markdown_field(text, "Request file")
    if request_file:
        request_paths.extend(_json_paths_from_text(request_file))
    canonical_request_block = re.search(
        r"(?ims)^\s*(?:-\s*)?Request files\s*:\s*"
        r"(.*?)"
        r"(?=^\s*(?:-\s*)?(?:Number of Seedance tasks|"
        r"Approved task count|Expected Parts|Approval scope|"
        r"Approval source|Timestamp)\s*:|\Z)",
        text,
    )
    if canonical_request_block:
        request_paths.extend(
            _json_paths_from_text(canonical_request_block.group(1))
        )
    section = re.search(
        r"(?ims)^##\s*Approved Request Files\s*$"
        r"(.*?)(?=^##\s|\Z)",
        text,
    )
    if section:
        request_paths.extend(
            match.group(1)
            for match in re.finditer(r"`([^`]+\.json)`", section.group(1))
        )
    request_paths = list(dict.fromkeys(request_paths))

    return {
        "job_id": _markdown_field(text, "Job", "Current task"),
        "scope": normalized_scope,
        "generation_intent": _generation_intent(
            _markdown_field(text, "Generation intent"),
            scope=normalized_scope,
        ),
        "approved_task_count": (
            int(count_match.group(0)) if count_match else None
        ),
        "approved_parts": approved_parts,
        "request_paths": request_paths,
        "result": result.upper(),
    }


def _parse_json_approval(data):
    if not isinstance(data, dict):
        raise FanoutError("generation approval JSON must be an object")
    raw_parts = data.get("approved_parts") or data.get("parts") or []
    if isinstance(raw_parts, str):
        raw_parts = _parts_from_value(raw_parts)
    raw_paths = data.get("request_paths") or data.get("requests") or []
    if isinstance(raw_paths, str):
        raw_paths = [raw_paths]
    raw_count = data.get("approved_task_count")
    scope = str(data.get("scope") or "").strip().lower()
    return {
        "job_id": str(data.get("job_id") or data.get("job") or "").strip(),
        "scope": scope,
        "generation_intent": _generation_intent(
            data.get("generation_intent"),
            scope=scope,
        ),
        "approved_task_count": (
            raw_count if isinstance(raw_count, int) and not isinstance(raw_count, bool)
            else None
        ),
        "approved_parts": [_part_id(value) for value in raw_parts],
        "request_paths": [str(value) for value in raw_paths],
        "result": str(data.get("result") or "").strip().upper(),
    }


def _approval_record(root, job_id, approval_record_path=None):
    job_dir = _job_dir(root, job_id).resolve()
    path = (
        _resolve_path(root, approval_record_path)
        if approval_record_path
        else job_dir / "seedance" / "generation_approval.md"
    )
    try:
        path.relative_to(job_dir)
    except ValueError:
        raise FanoutError(
            f"generation approval record must be job-local: {path}"
        )
    if not path.is_file():
        raise FanoutError(f"generation approval record not found: {path}")
    if path.suffix.lower() == ".json":
        claims = _parse_json_approval(_load_json(path))
    else:
        claims = _parse_markdown_approval(path.read_text(encoding="utf-8"))
    claims["approved_parts"] = [
        _part_id(value) for value in claims.get("approved_parts") or []
    ]
    claims["request_paths"] = [
        str(_resolve_path(root, value))
        for value in claims.get("request_paths") or []
    ]
    return path, _sha256(path), claims


def _validate_approval_claims(
    claims,
    job_id,
    attempt,
    approval_task_count,
    parts,
    generation_intent,
):
    if claims.get("result") != "PASS":
        raise FanoutError("generation approval Result must be PASS")
    if claims.get("job_id") != job_id:
        raise FanoutError("generation approval Job does not match plan")
    expected_scope = "current_job" if attempt == 1 else "targeted_retry"
    if claims.get("scope") != expected_scope:
        raise FanoutError(
            f"generation approval scope must be {expected_scope}"
        )
    if claims.get("generation_intent") != generation_intent:
        raise FanoutError(
            "generation approval intent does not match plan"
        )
    if claims.get("approved_task_count") != approval_task_count:
        raise FanoutError(
            "generation approval task count does not match plan"
        )
    expected_parts = [item["part_id"] for item in parts]
    if claims.get("approved_parts") != expected_parts:
        raise FanoutError(
            "generation approval approved Parts do not match plan"
        )
    expected_requests = [item["request_path"] for item in parts]
    if claims.get("request_paths") != expected_requests:
        raise FanoutError(
            "generation approval request paths do not match plan"
        )


def _validate_attempt(value):
    if not isinstance(value, int) or isinstance(value, bool) or value not in {1, 2}:
        raise FanoutError("generation attempt must be 1 or 2")
    return value


def _validate_targeted_retry(
    root,
    job_id,
    approval_path,
    approval_hash,
    part,
):
    previous_path = _fanout_dir(root, job_id) / "reservation.json"
    if not previous_path.is_file():
        raise FanoutError(
            "targeted retry requires previous attempt 1 spent FAIL evidence"
        )
    previous = _load_json(previous_path)
    if previous.get("job_id") != job_id or previous.get("attempt") != 1:
        raise FanoutError(
            "targeted retry previous attempt reservation is invalid"
        )
    previous_part = next(
        (
            item
            for item in previous.get("parts") or []
            if _part_id(item.get("part_id")) == part["part_id"]
        ),
        None,
    )
    if (
        previous_part is None
        or previous_part.get("spent") is not True
        or previous_part.get("status") != "FAIL"
    ):
        raise FanoutError(
            f"targeted retry requires previous attempt 1 {part['part_id']} "
            "to be spent and FAIL"
        )
    if (
        previous.get("approval_record_path") == str(approval_path)
        or previous.get("approval_record_sha256") == approval_hash
    ):
        raise FanoutError(
            "targeted retry requires a new approval record path and hash"
        )
    if (
        previous_part.get("request_sha256") == part["request_sha256"]
        or previous_part.get("request_path") == part["request_path"]
    ):
        raise FanoutError(
            "targeted retry requires a new request path and hash"
        )


def _selected_outputs_path(root, job_id):
    return _job_dir(root, job_id) / "generation" / "selected_outputs.json"


def _final_master_path(root, job_id):
    return _job_dir(root, job_id) / "final" / "final_video.mp4"


def _quality_retake_state_path(root, job_id):
    return (
        _job_dir(root, job_id)
        / "generation"
        / "quality_retake_state.json"
    )


def _validated_final_master(root, job_id, expected_hash=None):
    path = _final_master_path(root, job_id).resolve()
    if not path.is_file():
        raise FanoutError(
            "quality_retake requires current final/final_video.mp4"
        )
    current_hash = _sha256(path)
    if expected_hash and current_hash != expected_hash:
        raise FanoutError(
            "quality_retake baseline final master hash changed"
        )
    return path, current_hash


def _validated_selected_outputs(root, job_id, expected_hash=None):
    path = _selected_outputs_path(root, job_id).resolve()
    if not path.is_file():
        raise FanoutError(
            "quality_retake requires current generation/selected_outputs.json"
        )
    current_hash = _sha256(path)
    if expected_hash and current_hash != expected_hash:
        raise FanoutError(
            "quality_retake baseline selected_outputs hash changed"
        )
    manifest = _load_json(path)
    if manifest.get("schema_version") != 1:
        raise FanoutError(
            "quality_retake selected_outputs schema_version must be 1"
        )
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise FanoutError(
            "quality_retake selected_outputs has no outputs"
        )
    seen = set()
    for item in outputs:
        part_id = _part_id(item.get("part_id"))
        if part_id in seen:
            raise FanoutError(
                f"quality_retake selected_outputs duplicates {part_id}"
            )
        output_path = _resolve_path(root, item.get("path"))
        if not output_path.is_file():
            raise FanoutError(
                f"quality_retake baseline {part_id} output is missing"
            )
        if _sha256(output_path) != item.get("sha256"):
            raise FanoutError(
                f"quality_retake baseline {part_id} output hash changed"
            )
        try:
            duration = float(item.get("duration_seconds"))
        except (TypeError, ValueError):
            duration = 0.0
        if duration <= 0:
            raise FanoutError(
                f"quality_retake baseline {part_id} duration is not positive"
            )
        seen.add(part_id)
    return path, current_hash, manifest


def _validate_quality_retake(root, job_id, part, expected_hash=None):
    path, current_hash, manifest = _validated_selected_outputs(
        root,
        job_id,
        expected_hash=expected_hash,
    )
    target = part["part_id"]
    if target not in {
        _part_id(item.get("part_id"))
        for item in manifest["outputs"]
    }:
        raise FanoutError(
            f"quality_retake target {target} is not in selected_outputs"
        )
    return path, current_hash, manifest


def _write_quality_retake_state(
    root,
    plan,
    status,
    next_stage,
    initialize_only=False,
):
    path = _quality_retake_state_path(
        root,
        plan["job_id"],
    ).resolve()
    if path.is_file():
        existing = _load_json(path)
        if existing.get("plan_sha256") != plan["plan_sha256"]:
            raise FanoutError(
                "quality_retake state is bound to a different plan"
            )
        if initialize_only:
            return existing
    selected_path = Path(
        plan["baseline_selected_outputs_path"]
    ).resolve()
    final_path = Path(plan["baseline_final_path"]).resolve()
    state = {
        "schema_version": 1,
        "job_id": plan["job_id"],
        "generation_intent": "quality_retake",
        "plan_sha256": plan["plan_sha256"],
        "target_part": plan["parts"][0]["part_id"],
        "status": status,
        "next_stage": next_stage,
        "baseline_selected_outputs_path": str(selected_path),
        "baseline_selected_outputs_sha256": plan[
            "baseline_selected_outputs_sha256"
        ],
        "current_selected_outputs_sha256": (
            _sha256(selected_path)
            if selected_path.is_file()
            else None
        ),
        "baseline_final_path": str(final_path),
        "baseline_final_sha256": plan["baseline_final_sha256"],
        "current_final_sha256": (
            _sha256(final_path)
            if final_path.is_file()
            else None
        ),
        "global_state_files_touched": [],
    }
    _write_json(path, state)
    return state


def _canonical_reservation_path(root, plan, reservation_path=None):
    filename = (
        "reservation.json"
        if plan["attempt"] == 1
        else "reservation_attempt_2.json"
    )
    canonical = (_fanout_dir(root, plan["job_id"]) / filename).resolve()
    if reservation_path:
        requested = _resolve_path(root, reservation_path)
        if requested != canonical:
            raise FanoutError(
                "generation reservation path must be the canonical "
                f"job/stage path: {canonical}"
            )
    return canonical


@contextmanager
def _reservation_lock(path):
    lock_path = Path(path).with_name(Path(path).name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _display_path(root, path):
    path = Path(path).resolve()
    try:
        return str(path.relative_to(Path(root).resolve()))
    except ValueError:
        return str(path)


def _normalize_prepared_requests(prepared_requests):
    if isinstance(prepared_requests, dict):
        prepared_requests = [
            {"part_id": part, "request_path": path}
            for part, path in prepared_requests.items()
        ]

    normalized = []
    for item in prepared_requests or []:
        if isinstance(item, str):
            if "=" not in item:
                raise FanoutError(
                    "prepared request strings must use PART=PATH"
                )
            part, request_path = item.split("=", 1)
        elif isinstance(item, (tuple, list)) and len(item) == 2:
            part, request_path = item
        elif isinstance(item, dict):
            part = item.get("part_id") or item.get("part")
            request_path = item.get("request_path") or item.get("request")
        else:
            raise FanoutError(f"invalid prepared request entry: {item!r}")
        normalized.append((_part_id(part), request_path))
    return normalized


def build_plan(
    root,
    job_id,
    prepared_requests,
    approval_task_count,
    stage=DEFAULT_STAGE,
    approval_record_path=None,
    attempt=1,
    generation_intent=None,
):
    """Build an immutable-input plan from explicit Part/request pairs."""
    root = Path(root).resolve()
    job_id = str(job_id or "").strip()
    stage = str(stage or "").strip()
    if not job_id:
        raise FanoutError("job_id is required")
    if not stage:
        raise FanoutError("stage is required")
    attempt = _validate_attempt(attempt)
    if not isinstance(approval_task_count, int) or approval_task_count < 1:
        raise FanoutError("approval task count must be a positive integer")
    approval_path, approval_hash, approval_claims = _approval_record(
        root,
        job_id,
        approval_record_path,
    )
    generation_intent = _generation_intent(
        generation_intent or approval_claims.get("generation_intent"),
        scope=approval_claims.get("scope"),
        attempt=attempt,
    )

    entries = _normalize_prepared_requests(prepared_requests)
    if not entries:
        raise FanoutError("at least one prepared request is required")
    if approval_task_count != len(entries):
        raise FanoutError(
            "approval task count must equal Part count"
        )
    if attempt == 2 and len(entries) != 1:
        raise FanoutError(
            "targeted retry attempt 2 must contain exactly one Part"
        )

    seen_parts = set()
    seen_requests = set()
    parts = []
    planned_part_dirs = {
        part: (
            _attempt_dir(root, job_id, attempt)
            / "parts"
            / part
        ).resolve()
        for part, unused_request_path in entries
    }
    for part, raw_request_path in entries:
        if part in seen_parts:
            raise FanoutError(f"duplicate part in generation plan: {part}")
        request_path = _resolve_path(root, raw_request_path)
        if not request_path.is_file():
            raise FanoutError(f"prepared request not found: {request_path}")
        if request_path in seen_requests:
            raise FanoutError(
                f"prepared request reused by multiple parts: {request_path}"
            )

        if any(
            request_path == write_root
            or stage_execution.is_within(request_path, write_root)
            for write_root in planned_part_dirs.values()
        ):
            raise FanoutError(
                f"{part} prepared request cannot be inside any generation "
                "write root"
            )
        part_dir = planned_part_dirs[part]
        out_dir = part_dir / "provider"
        output_path = part_dir / f"{part}.mp4"
        summary_path = out_dir / "summary.json"
        completion_path = part_dir / "completion.json"
        stage_completion_path = part_dir / "stage_execution_completion.json"
        base_command = [
            *RUNNER_COMMAND,
            "--request",
            str(request_path),
            "--out-dir",
            str(out_dir),
            "--output",
            str(output_path),
        ]
        command = [*base_command, "--require-existing-preflight"]
        preflight_command = [*base_command, "--preflight-only"]
        parts.append(
            {
                "part_id": part,
                "request_path": str(request_path),
                "request_sha256": _sha256(request_path),
                "attempt": attempt,
                "out_dir": str(out_dir),
                "output_path": str(output_path),
                "summary_path": str(summary_path),
                "completion_path": str(completion_path),
                "stage_completion_path": str(stage_completion_path),
                "command": command,
                "preflight_command": preflight_command,
            }
        )
        seen_parts.add(part)
        seen_requests.add(request_path)

    parts.sort(key=lambda item: _part_sort_key(item["part_id"]))
    _validate_approval_claims(
        approval_claims,
        job_id,
        attempt,
        approval_task_count,
        parts,
        generation_intent,
    )
    if attempt == 1 and generation_intent != "current_job":
        raise FanoutError(
            "generation attempt 1 intent must be current_job"
        )
    if attempt == 2 and generation_intent not in {
        "failed_part_retry",
        "quality_retake",
    }:
        raise FanoutError(
            "generation attempt 2 intent must be failed_part_retry "
            "or quality_retake"
        )
    baseline_selected_outputs_path = ""
    baseline_selected_outputs_sha256 = ""
    baseline_final_path = ""
    baseline_final_sha256 = ""
    if attempt == 2 and generation_intent == "failed_part_retry":
        _validate_targeted_retry(
            root,
            job_id,
            approval_path,
            approval_hash,
            parts[0],
        )
    elif attempt == 2:
        (
            selected_path,
            selected_hash,
            unused_manifest,
        ) = _validate_quality_retake(
            root,
            job_id,
            parts[0],
        )
        baseline_selected_outputs_path = str(selected_path)
        baseline_selected_outputs_sha256 = selected_hash
        final_path, final_hash = _validated_final_master(
            root,
            job_id,
        )
        baseline_final_path = str(final_path)
        baseline_final_sha256 = final_hash
    plan = {
        "schema_version": 1,
        "job_id": job_id,
        "stage": stage,
        "attempt": attempt,
        "generation_intent": generation_intent,
        "fanout_policy": FANOUT_POLICY,
        "approval_task_count": approval_task_count,
        "approval_record_path": str(approval_path),
        "approval_record_sha256": approval_hash,
        "approval_claims": approval_claims,
        "parts": parts,
    }
    if generation_intent == "quality_retake":
        plan["baseline_selected_outputs_path"] = (
            baseline_selected_outputs_path
        )
        plan["baseline_selected_outputs_sha256"] = (
            baseline_selected_outputs_sha256
        )
        plan["baseline_final_path"] = baseline_final_path
        plan["baseline_final_sha256"] = baseline_final_sha256
    execution = {
        "schema_version": 1,
        "job_id": job_id,
        "stage": stage,
        "coordinator_only_paths": [
            _display_path(
                root,
                _job_dir(root, job_id)
                / "generation"
                / "selected_outputs.json",
            ),
            _display_path(
                root,
                _job_dir(root, job_id)
                / "generation"
                / "generation_log.md",
            ),
        ],
        "packets": [
            {
                "packet_id": item["part_id"],
                "command": item["command"],
                "depends_on": [],
                "allowed_write_roots": [
                    _display_path(
                        root,
                        Path(item["completion_path"]).parent,
                    )
                ],
                "completion_path": _display_path(
                    root,
                    item["stage_completion_path"],
                ),
            }
            for item in parts
        ],
    }
    if generation_intent == "quality_retake":
        execution["coordinator_only_paths"].append(
            _display_path(
                root,
                _quality_retake_state_path(root, job_id),
            )
        )
    plan["stage_execution"] = stage_execution.seal_plan(root, execution)
    plan["plan_sha256"] = stage_execution.stable_hash(plan)
    return plan


def _validate_plan(root, plan):
    plan_hash = str(plan.get("plan_sha256") or "").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", plan_hash):
        raise FanoutError("generation plan requires plan_sha256")
    unsigned = dict(plan)
    unsigned.pop("plan_sha256", None)
    if stage_execution.stable_hash(unsigned) != plan_hash:
        raise FanoutError("generation plan hash mismatch")
    if plan.get("schema_version") != 1:
        raise FanoutError("generation plan schema_version must be 1")
    job_id = str(plan.get("job_id") or "").strip()
    stage = str(plan.get("stage") or "").strip()
    if not job_id or not stage:
        raise FanoutError("generation plan must bind job and stage")
    attempt = _validate_attempt(plan.get("attempt"))
    generation_intent = _generation_intent(
        plan.get("generation_intent"),
        attempt=attempt,
    )
    approval_count = plan.get("approval_task_count")
    if not isinstance(approval_count, int) or approval_count < 1:
        raise FanoutError("generation plan approval task count is invalid")
    approval_path, approval_hash, approval_claims = _approval_record(
        root,
        job_id,
        plan.get("approval_record_path"),
    )
    if approval_hash != plan.get("approval_record_sha256"):
        raise FanoutError(
            "generation approval record hash changed after planning"
        )
    if str(approval_path) != plan.get("approval_record_path"):
        raise FanoutError(
            "generation approval record path does not match plan"
        )
    if approval_claims != plan.get("approval_claims"):
        raise FanoutError(
            "generation approval parsed claims changed after planning"
        )
    execution = plan.get("stage_execution") or {}
    try:
        stage_execution.validate_plan(
            root,
            execution,
        )
    except stage_execution.PlanError as exc:
        raise FanoutError(str(exc)) from exc
    if execution.get("job_id") != job_id or execution.get("stage") != stage:
        raise FanoutError(
            "stage execution plan does not match generation job/stage"
        )

    parts = plan.get("parts")
    if not isinstance(parts, list) or not parts:
        raise FanoutError("generation plan has no parts")
    if len(parts) != approval_count:
        raise FanoutError(
            "generation approval task count must equal Part count"
        )
    if attempt == 2 and len(parts) != 1:
        raise FanoutError(
            "targeted retry attempt 2 must contain exactly one Part"
        )

    generation_dir = (_job_dir(root, job_id) / "generation").resolve()
    seen_parts = set()
    seen_isolated_paths = {
        "out-dir": set(),
        "output": set(),
        "completion": set(),
        "stage-completion": set(),
        "summary": set(),
    }
    for item in parts:
        part = _part_id(item.get("part_id"))
        if part in seen_parts:
            raise FanoutError(f"duplicate part in generation plan: {part}")
        if item.get("attempt") != attempt:
            raise FanoutError(
                f"{part} attempt does not match generation plan"
            )

        command = item.get("command")
        if not isinstance(command, list) or tuple(command[:2]) != RUNNER_COMMAND:
            raise FanoutError(
                f"{part} command must call only tools/seedance_taskcode_runner.py"
            )
        if "generation_fanout.py" in " ".join(str(value) for value in command):
            raise FanoutError(f"{part} command cannot recursively call fanout")
        preflight_command = item.get("preflight_command")
        if (
            not isinstance(preflight_command, list)
            or tuple(preflight_command[:2]) != RUNNER_COMMAND
            or preflight_command[-1:] != ["--preflight-only"]
            or command[-1:] != ["--require-existing-preflight"]
            or preflight_command[:-1] != command[:-1]
        ):
            raise FanoutError(
                f"{part} preflight and paid commands are not correctly sealed"
            )

        request_path = _resolve_path(root, item.get("request_path"))
        if not request_path.is_file():
            raise FanoutError(f"{part} prepared request not found: {request_path}")
        if _sha256(request_path) != item.get("request_sha256"):
            raise FanoutError(f"{part} prepared request hash changed after planning")

        output_path = _resolve_path(root, item.get("output_path"))
        out_dir = _resolve_path(root, item.get("out_dir"))
        completion_path = _resolve_path(root, item.get("completion_path"))
        stage_completion_path = _resolve_path(
            root,
            item.get("stage_completion_path"),
        )
        summary_path = _resolve_path(root, item.get("summary_path"))
        for path, label in (
            (output_path, "output"),
            (out_dir, "out-dir"),
            (completion_path, "completion"),
            (stage_completion_path, "stage-completion"),
            (summary_path, "summary"),
        ):
            try:
                path.relative_to(generation_dir)
            except ValueError:
                raise FanoutError(
                    f"{part} {label} path is outside the job generation directory"
                )
        for path, label in (
            (out_dir, "out-dir"),
            (output_path, "output"),
            (completion_path, "completion"),
            (stage_completion_path, "stage-completion"),
            (summary_path, "summary"),
        ):
            if path in seen_isolated_paths[label]:
                raise FanoutError(
                    f"duplicate {label} path in generation plan: {path}"
                )
            seen_isolated_paths[label].add(path)
        seen_parts.add(part)

    _validate_approval_claims(
        approval_claims,
        job_id,
        attempt,
        approval_count,
        parts,
        generation_intent,
    )
    if attempt == 1 and generation_intent != "current_job":
        raise FanoutError(
            "generation attempt 1 intent must be current_job"
        )
    if attempt == 2 and generation_intent not in {
        "failed_part_retry",
        "quality_retake",
    }:
        raise FanoutError(
            "generation attempt 2 intent must be failed_part_retry "
            "or quality_retake"
        )
    if attempt == 2 and generation_intent == "failed_part_retry":
        _validate_targeted_retry(
            root,
            job_id,
            approval_path,
            approval_hash,
            parts[0],
        )
    elif attempt == 2:
        baseline_path = str(
            plan.get("baseline_selected_outputs_path") or ""
        )
        expected_path = str(_selected_outputs_path(root, job_id).resolve())
        if baseline_path != expected_path:
            raise FanoutError(
                "quality_retake baseline selected_outputs path does not "
                "match the canonical job path"
            )
        _validate_quality_retake(
            root,
            job_id,
            parts[0],
            expected_hash=plan.get(
                "baseline_selected_outputs_sha256"
            ),
        )
        baseline_final_path = str(
            plan.get("baseline_final_path") or ""
        )
        expected_final_path = str(
            _final_master_path(root, job_id).resolve()
        )
        if baseline_final_path != expected_final_path:
            raise FanoutError(
                "quality_retake baseline final path does not match the "
                "canonical job path"
            )
        _validated_final_master(
            root,
            job_id,
            expected_hash=plan.get("baseline_final_sha256"),
        )

    packets = {
        packet.get("packet_id"): packet
        for packet in execution.get("packets") or []
    }
    if set(packets) != {item["part_id"] for item in parts}:
        raise FanoutError(
            "stage execution packet set does not match generation Parts"
        )
    expected_part_dirs = {
        part_item["part_id"]: (
            _attempt_dir(root, job_id, attempt)
            / "parts"
            / part_item["part_id"]
        ).resolve()
        for part_item in parts
    }
    for item in parts:
        packet = packets[item["part_id"]]
        expected_part_dir = expected_part_dirs[item["part_id"]]
        expected_write_root = _resolve_path(
            root,
            Path(item["completion_path"]).parent,
        )
        request_path = _resolve_path(root, item["request_path"])
        if any(
            request_path == write_root
            or stage_execution.is_within(request_path, write_root)
            for write_root in expected_part_dirs.values()
        ):
            raise FanoutError(
                f"{item['part_id']} prepared request cannot be inside any "
                "generation write root"
            )
        packet_write_roots = {
            _resolve_path(root, value)
            for value in packet.get("allowed_write_roots") or []
        }
        if (
            packet.get("command") != item["command"]
            or packet.get("depends_on") != []
            or expected_write_root != expected_part_dir
            or _resolve_path(root, item["out_dir"])
            != expected_part_dir / "provider"
            or _resolve_path(root, item["output_path"])
            != expected_part_dir / f"{item['part_id']}.mp4"
            or _resolve_path(root, item["summary_path"])
            != expected_part_dir / "provider" / "summary.json"
            or _resolve_path(root, item["completion_path"])
            != expected_part_dir / "completion.json"
            or _resolve_path(root, item["stage_completion_path"])
            != expected_part_dir / "stage_execution_completion.json"
            or _resolve_path(root, packet.get("completion_path"))
            != _resolve_path(root, item["stage_completion_path"])
            or packet_write_roots != {expected_write_root}
        ):
            raise FanoutError(
                f"{item['part_id']} stage execution packet does not match Part"
            )
    return plan


def _reservation_from_plan(plan):
    return {
        "schema_version": 1,
        "job_id": plan["job_id"],
        "stage": plan["stage"],
        "attempt": plan["attempt"],
        "generation_intent": plan["generation_intent"],
        "plan_sha256": plan["plan_sha256"],
        "approval_task_count": plan["approval_task_count"],
        "approval_record_path": plan["approval_record_path"],
        "approval_record_sha256": plan["approval_record_sha256"],
        "approval_claims": plan["approval_claims"],
        "reserved_task_count": len(plan["parts"]),
        "parts": [
            {
                "part_id": item["part_id"],
                "request_path": item["request_path"],
                "request_sha256": item["request_sha256"],
                "attempt": plan["attempt"],
                "spent": False,
                "status": "RESERVED",
            }
            for item in plan["parts"]
        ],
    }


def _reservation_hashes(reservation):
    return {
        _part_id(item.get("part_id")): item.get("request_sha256")
        for item in reservation.get("parts") or []
    }


def _validate_reservation(existing, proposed):
    if existing.get("schema_version") != 1:
        raise FanoutError("reservation schema_version must be 1")
    if existing.get("job_id") != proposed["job_id"]:
        raise FanoutError("reservation is bound to a different job")
    if existing.get("stage") != proposed["stage"]:
        raise FanoutError("reservation is bound to a different stage")
    if existing.get("attempt") != proposed["attempt"]:
        raise FanoutError("reservation is bound to a different attempt")
    if (
        existing.get("generation_intent")
        != proposed["generation_intent"]
    ):
        raise FanoutError(
            "reservation is bound to a different generation intent"
        )
    if existing.get("plan_sha256") != proposed["plan_sha256"]:
        raise FanoutError(
            "reservation is bound to a different generation plan; "
            "automatic retry is unsupported (STOP)"
        )
    if existing.get("approval_task_count") != proposed["approval_task_count"]:
        raise FanoutError("reservation approval task count differs")
    if (
        existing.get("approval_record_path")
        != proposed["approval_record_path"]
        or existing.get("approval_record_sha256")
        != proposed["approval_record_sha256"]
        or existing.get("approval_claims")
        != proposed["approval_claims"]
    ):
        raise FanoutError(
            "reservation is bound to a different approval record; "
            "automatic retry is unsupported (STOP)"
        )

    existing_hashes = _reservation_hashes(existing)
    proposed_hashes = _reservation_hashes(proposed)
    existing_parts = existing.get("parts") or []
    if existing.get("reserved_task_count") != len(existing_parts):
        raise FanoutError("reservation task count is inconsistent")
    if len(existing_parts) > existing.get("approval_task_count", 0):
        raise FanoutError("reservation exceeds approval task count")
    if any(
        item.get("attempt") != proposed["attempt"]
        for item in existing_parts
    ):
        raise FanoutError("reservation Part attempt does not match")
    if set(existing_hashes) != set(proposed_hashes):
        raise FanoutError("reservation is bound to a different Part set")
    proposed_paths = {
        item["part_id"]: item["request_path"] for item in proposed["parts"]
    }
    existing_paths = {
        _part_id(item.get("part_id")): item.get("request_path")
        for item in existing_parts
    }
    for part, request_hash in proposed_hashes.items():
        if existing_hashes.get(part) != request_hash:
            raise FanoutError(
                f"{part} reservation has a different request hash"
            )
        if existing_paths.get(part) != proposed_paths.get(part):
            raise FanoutError(
                f"{part} reservation is bound to a different request path"
            )
    return existing


def reserve_plan(root, plan, reservation_path=None):
    """Persist the paid-task reservation before any Part runner is started."""
    root = Path(root).resolve()
    _validate_plan(root, plan)
    _require_bound_preflight(root, plan)
    path = _canonical_reservation_path(root, plan, reservation_path)
    proposed = _reservation_from_plan(plan)
    with _reservation_lock(path):
        if not path.exists():
            _write_json(path, proposed)
            reservation = proposed
        else:
            reservation = _validate_reservation(
                _load_json(path),
                proposed,
            )
    if plan["generation_intent"] == "quality_retake":
        _write_quality_retake_state(
            root,
            plan,
            status="reserved_baseline_active",
            next_stage="generation",
            initialize_only=True,
        )
    return reservation


def _load_bound_reservation(root, plan, reservation_path):
    path = _canonical_reservation_path(root, plan, reservation_path)
    if not path.is_file():
        raise FanoutError(f"generation reservation not found: {path}")
    existing = _validate_reservation(
        _load_json(path),
        _reservation_from_plan(plan),
    )
    return path, existing


def _summary_result(root, part):
    summary_path = _resolve_path(root, part["summary_path"])
    output_path = _resolve_path(root, part["output_path"])
    if not summary_path.is_file():
        raise FanoutError(f"{part['part_id']} summary is missing")
    summary = _load_json(summary_path)
    overall = str(summary.get("overall") or "").strip().upper()
    status = str(summary.get("status") or "").strip().lower()
    if overall and overall != "PASS":
        raise FanoutError(f"{part['part_id']} summary is not PASS")
    if status and status not in {"pass", "success", "succeeded"}:
        raise FanoutError(f"{part['part_id']} summary is not PASS")
    if not overall and not status:
        raise FanoutError(f"{part['part_id']} summary is not PASS")

    summary_video = summary.get("video") or summary.get("output")
    if not summary_video:
        raise FanoutError(f"{part['part_id']} summary has no video")
    if _resolve_path(root, summary_video) != output_path:
        raise FanoutError(
            f"{part['part_id']} summary video does not match reserved output"
        )
    if not output_path.is_file():
        raise FanoutError(f"{part['part_id']} output video is missing")

    raw_duration = summary.get("duration_seconds_actual")
    if raw_duration is None:
        raw_duration = summary.get("duration_seconds")
    try:
        duration = float(raw_duration)
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        raise FanoutError(f"{part['part_id']} summary duration is not positive")
    return summary, output_path, duration


def _default_runner(command, cwd):
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def _validate_preflight_evidence(root, part):
    request_hash = part["request_sha256"]
    for filename, label in (
        ("request_contract.json", "request contract"),
        ("reference_audio_preflight.json", "reference audio preflight"),
    ):
        path = _resolve_path(root, Path(part["out_dir"]) / filename)
        if not path.is_file():
            raise FanoutError(
                f"{part['part_id']} {label} evidence is missing"
            )
        report = _load_json(path)
        if str(report.get("overall") or "").upper() != "PASS":
            raise FanoutError(f"{part['part_id']} {label} is not PASS")
        if report.get("request_sha256") != request_hash:
            raise FanoutError(
                f"{part['part_id']} {label} request hash does not match"
            )


def _run_one_preflight(root, part, runner):
    command = list(part["preflight_command"])
    try:
        result = runner(command, root)
        returncode = int(getattr(result, "returncode", result))
        stderr = str(getattr(result, "stderr", "") or "")
    except Exception as exc:
        returncode = 1
        stderr = f"runner raised: {exc}"
    if returncode != 0:
        return {
            "part_id": part["part_id"],
            "request_sha256": part["request_sha256"],
            "status": "FAIL",
            "returncode": returncode,
            "error": stderr.strip() or f"preflight exited {returncode}",
        }
    try:
        _validate_preflight_evidence(root, part)
    except FanoutError as exc:
        return {
            "part_id": part["part_id"],
            "request_sha256": part["request_sha256"],
            "status": "FAIL",
            "returncode": 0,
            "error": str(exc),
        }
    return {
        "part_id": part["part_id"],
        "request_sha256": part["request_sha256"],
        "status": "PASS",
        "returncode": 0,
    }


def _preflight_execution_plan(root, plan):
    attempt_dir = _attempt_dir(
        root,
        plan["job_id"],
        plan["attempt"],
    )
    execution = {
        "schema_version": 1,
        "job_id": plan["job_id"],
        "stage": f"{plan['stage']}_preflight",
        "coordinator_only_paths": [
            _display_path(root, attempt_dir / "preflight_report.json"),
        ],
        "packets": [
            {
                "packet_id": part["part_id"],
                "command": part["preflight_command"],
                "depends_on": [],
                "allowed_write_roots": [
                    _display_path(
                        root,
                        Path(part["completion_path"]).parent,
                    )
                ],
                "completion_path": _display_path(
                    root,
                    Path(part["completion_path"]).parent
                    / "preflight_stage_execution_completion.json",
                ),
            }
            for part in plan["parts"]
        ],
    }
    return stage_execution.seal_plan(root, execution)


def preflight_plan(root, plan, runner=None, max_workers=3):
    """Validate every request/audio input before a paid reservation exists."""
    root = Path(root).resolve()
    _validate_plan(root, plan)
    if not isinstance(max_workers, int) or max_workers < 1:
        raise FanoutError("max_workers must be a positive integer")
    selected_runner = runner or _default_runner
    worker_count = min(max_workers, len(plan["parts"]))
    parts_by_id = {
        item["part_id"]: item for item in plan["parts"]
    }

    def dispatch(packet):
        part = dict(parts_by_id[packet["packet_id"]])
        part["preflight_command"] = list(packet["command"])
        for key in ("out_dir", "output_path", "summary_path"):
            part[key] = str(
                stage_execution.runtime_path(
                    root,
                    packet,
                    part[key],
                )
            )
        result = _run_one_preflight(
            root,
            part,
            selected_runner,
        )
        runtime_root = Path(packet["allowed_write_roots"][0])
        result["outputs"] = [
            str(path)
            for path in sorted(runtime_root.rglob("*"))
            if path.is_file() and not path.is_symlink()
        ]
        return result

    execution_plan = _preflight_execution_plan(root, plan)
    try:
        execution_report = stage_execution.execute_plan(
            root,
            execution_plan,
            dispatcher=dispatch,
            max_workers=worker_count,
        )
    except stage_execution.PlanError as exc:
        raise FanoutError(
            f"generation preflight stage execution failed: {exc}"
        ) from exc
    results = []
    for completion in execution_report["completions"]:
        part = parts_by_id[completion["packet_id"]]
        result = {
            "part_id": part["part_id"],
            "request_sha256": part["request_sha256"],
            "status": completion["status"],
            "returncode": completion.get("returncode", 1),
        }
        if completion.get("error"):
            result["error"] = completion["error"]
        results.append(result)
    results.sort(key=lambda item: _part_sort_key(item["part_id"]))
    report = {
        "schema_version": 1,
        "job_id": plan["job_id"],
        "stage": plan["stage"],
        "attempt": plan["attempt"],
        "plan_sha256": plan["plan_sha256"],
        "approval_claims": plan["approval_claims"],
        "results": results,
        "overall": (
            "PASS"
            if all(item["status"] == "PASS" for item in results)
            else "FAIL"
        ),
    }
    _write_json(
        _attempt_dir(root, plan["job_id"], plan["attempt"])
        / "preflight_report.json",
        report,
    )
    return report


def _require_bound_preflight(root, plan):
    path = (
        _attempt_dir(root, plan["job_id"], plan["attempt"])
        / "preflight_report.json"
    )
    if not path.is_file():
        raise FanoutError(
            "generation preflight report is missing; preflight must pass "
            "before reservation and submission"
        )
    report = _load_json(path)
    if (
        report.get("schema_version") != 1
        or report.get("job_id") != plan["job_id"]
        or report.get("stage") != plan["stage"]
        or report.get("attempt") != plan["attempt"]
        or report.get("plan_sha256") != plan["plan_sha256"]
        or report.get("approval_claims") != plan["approval_claims"]
        or report.get("overall") != "PASS"
    ):
        raise FanoutError(
            "generation preflight report is not PASS for the current plan"
        )
    results = {
        _part_id(item.get("part_id")): item
        for item in report.get("results") or []
    }
    if set(results) != {item["part_id"] for item in plan["parts"]}:
        raise FanoutError("generation preflight Part set does not match plan")
    for part in plan["parts"]:
        result = results[part["part_id"]]
        if (
            result.get("status") != "PASS"
            or result.get("request_sha256") != part["request_sha256"]
        ):
            raise FanoutError(
                f"{part['part_id']} generation preflight is stale or not PASS"
            )
        _validate_preflight_evidence(root, part)
    return report


def _run_one_part(root, plan, part, runner):
    part_id = part["part_id"]
    command = list(part["command"])
    part_dir = _resolve_path(root, part["completion_path"]).parent
    part_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = runner(command, root)
        returncode = int(getattr(result, "returncode", result))
        stdout = str(getattr(result, "stdout", "") or "")
        stderr = str(getattr(result, "stderr", "") or "")
    except Exception as exc:
        returncode = 1
        stdout = ""
        stderr = f"runner raised: {exc}"

    stdout_path = part_dir / "stdout.txt"
    stderr_path = part_dir / "stderr.txt"
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    completion = {
        "schema_version": 1,
        "job_id": plan["job_id"],
        "stage": plan["stage"],
        "attempt": plan["attempt"],
        "part_id": part_id,
        "request_path": part["request_path"],
        "request_sha256": part["request_sha256"],
        "approval_claims": plan["approval_claims"],
        "status": "FAIL",
        "returncode": returncode,
        "summary_path": part["summary_path"],
        "output_path": part["output_path"],
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
    }
    if returncode == 0:
        try:
            unused_summary, output_path, duration = _summary_result(root, part)
            completion["status"] = "PASS"
            completion["output_sha256"] = _sha256(output_path)
            completion["duration_seconds"] = duration
        except FanoutError as exc:
            completion["error"] = str(exc)
    else:
        completion["error"] = stderr.strip() or f"runner exited {returncode}"
    _write_json(part["completion_path"], completion)
    return completion


def run_reserved_parts(
    root,
    plan,
    reservation_path=None,
    runner=None,
    max_workers=3,
):
    """Spend each reserved attempt once, then run the isolated Part commands."""
    root = Path(root).resolve()
    _validate_plan(root, plan)
    if not isinstance(max_workers, int) or max_workers < 1:
        raise FanoutError("max_workers must be a positive integer")
    _require_bound_preflight(root, plan)
    worker_count = min(max_workers, len(plan["parts"]))
    selected_runner = runner or _default_runner

    path = _canonical_reservation_path(root, plan, reservation_path)
    with _reservation_lock(path):
        path, reservation = _load_bound_reservation(root, plan, path)
        reservation_parts = {
            _part_id(item.get("part_id")): item
            for item in reservation["parts"]
        }
        for plan_part in plan["parts"]:
            reserved = reservation_parts[plan_part["part_id"]]
            if reserved.get("spent") or reserved.get("status") != "RESERVED":
                raise FanoutError(
                    f"{plan_part['part_id']} reservation is already spent "
                    f"(status={reserved.get('status')})"
                )

        # Persist spent under an OS lock before launching. A crash can never
        # silently resubmit paid work from another process.
        for item in reservation["parts"]:
            item["spent"] = True
            item["status"] = "RUNNING"
        _write_json(path, reservation)

    parts_by_id = {
        item["part_id"]: item for item in plan["parts"]
    }

    def dispatch(packet):
        part = parts_by_id[packet["packet_id"]]
        runtime_part = dict(part)
        runtime_part["command"] = list(packet["command"])
        for key in (
            "out_dir",
            "output_path",
            "summary_path",
            "completion_path",
        ):
            runtime_part[key] = str(
                stage_execution.runtime_path(
                    root,
                    packet,
                    part[key],
                )
            )
        completion = _run_one_part(
            root,
            plan,
            runtime_part,
            selected_runner,
        )
        if _resolve_path(root, runtime_part["summary_path"]).is_file():
            summary = _load_json(runtime_part["summary_path"])
            for key in ("video", "output"):
                if summary.get(key):
                    summary[key] = str(
                        stage_execution.canonical_path(
                            root,
                            packet,
                            summary[key],
                        )
                    )
            _write_json(runtime_part["summary_path"], summary)
        for key in (
            "summary_path",
            "output_path",
            "stdout_path",
            "stderr_path",
        ):
            if completion.get(key):
                completion[key] = str(
                    stage_execution.canonical_path(
                        root,
                        packet,
                        completion[key],
                    )
                )
        _write_json(runtime_part["completion_path"], completion)
        runtime_part_root = Path(packet["allowed_write_roots"][0])
        outputs = [
            str(path)
            for path in sorted(runtime_part_root.rglob("*"))
            if path.is_file() and not path.is_symlink()
        ]
        result = {
            "status": completion["status"],
            "outputs": outputs,
            "returncode": completion["returncode"],
        }
        if completion.get("error"):
            result["error"] = completion["error"]
        return result

    try:
        execution_report = stage_execution.execute_plan(
            root,
            plan["stage_execution"],
            dispatcher=dispatch,
            max_workers=worker_count,
        )
    except stage_execution.PlanError as exc:
        raise FanoutError(f"generation stage execution failed: {exc}") from exc

    stage_completions = {
        item["packet_id"]: item
        for item in execution_report["completions"]
    }
    completions = []
    for part in plan["parts"]:
        completion_path = _resolve_path(root, part["completion_path"])
        if completion_path.is_file():
            completion = _load_json(completion_path)
        else:
            completion = {
                "schema_version": 1,
                "job_id": plan["job_id"],
                "stage": plan["stage"],
                "attempt": plan["attempt"],
                "part_id": part["part_id"],
                "request_path": part["request_path"],
                "request_sha256": part["request_sha256"],
                "approval_claims": plan["approval_claims"],
                "status": "FAIL",
                "returncode": 1,
            }
        stage_completion = stage_completions[part["part_id"]]
        if stage_completion["status"] != "PASS":
            completion["status"] = "FAIL"
            completion["error"] = stage_completion.get(
                "error",
                "sealed stage execution failed",
            )
            _write_json(completion_path, completion)
        completions.append(completion)
    completions.sort(key=lambda item: _part_sort_key(item["part_id"]))

    completion_by_part = {
        item["part_id"]: item for item in completions
    }
    with _reservation_lock(path):
        current = _validate_reservation(
            _load_json(path),
            _reservation_from_plan(plan),
        )
        for item in current["parts"]:
            item["status"] = completion_by_part[item["part_id"]]["status"]
        _write_json(path, current)

    report = {
        "schema_version": 1,
        "job_id": plan["job_id"],
        "stage": plan["stage"],
        "attempt": plan["attempt"],
        "approval_claims": plan["approval_claims"],
        "fanout_policy": FANOUT_POLICY,
        "reservation_path": str(path),
        "results": completions,
        "overall": (
            "PASS"
            if completions
            and all(item["status"] == "PASS" for item in completions)
            else "FAIL"
        ),
    }
    _write_json(
        _attempt_dir(root, plan["job_id"], plan["attempt"])
        / "run_report.json",
        report,
    )
    if plan["generation_intent"] == "quality_retake":
        if report["overall"] == "PASS":
            status = "generation_passed_baseline_active"
            next_stage = "merge"
        else:
            status = "generation_failed_baseline_active"
            next_stage = "STOP"
        _write_quality_retake_state(
            root,
            plan,
            status=status,
            next_stage=next_stage,
        )
    return report


def _part_from_reservation(root, job_id, attempt, item):
    part_id = _part_id(item.get("part_id"))
    part_dir = _attempt_dir(root, job_id, attempt) / "parts" / part_id
    return {
        "part_id": part_id,
        "request_path": item.get("request_path"),
        "request_sha256": item.get("request_sha256"),
        "attempt": attempt,
        "output_path": str(part_dir / f"{part_id}.mp4"),
        "summary_path": str(part_dir / "provider" / "summary.json"),
        "completion_path": str(part_dir / "completion.json"),
    }


def _validated_output(root, job_id, stage, approval_claims, part):
    completion_path = _resolve_path(root, part["completion_path"])
    if not completion_path.is_file():
        raise FanoutError(
            f"{part['part_id']} PASS completion is missing"
        )
    completion = _load_json(completion_path)
    expected = {
        "job_id": job_id,
        "stage": stage,
        "attempt": part["attempt"],
        "part_id": part["part_id"],
        "request_sha256": part["request_sha256"],
        "approval_claims": approval_claims,
    }
    for key, value in expected.items():
        if completion.get(key) != value:
            raise FanoutError(
                f"{part['part_id']} completion {key} does not match plan"
            )
    if completion.get("status") != "PASS":
        raise FanoutError(
            f"{part['part_id']} completion is not PASS"
        )

    unused_summary, output_path, duration = _summary_result(root, part)
    output_hash = _sha256(output_path)
    if completion.get("output_sha256") != output_hash:
        raise FanoutError(
            f"{part['part_id']} output hash changed after completion"
        )
    try:
        completed_duration = float(completion.get("duration_seconds"))
    except (TypeError, ValueError):
        completed_duration = 0.0
    if abs(completed_duration - duration) > 1e-6:
        raise FanoutError(
            f"{part['part_id']} output duration changed after completion"
        )
    return {
        "part_id": part["part_id"],
        "attempt": part["attempt"],
        "path": str(output_path.resolve()),
        "sha256": output_hash,
        "duration_seconds": duration,
    }


def merge_completions(root, plan, selected_outputs_path=None):
    """Validate current PASS Parts and return a coordinator-owned manifest."""
    root = Path(root).resolve()
    _validate_plan(root, plan)
    selected_parts = []
    outputs = None
    if plan["attempt"] == 1:
        selected_parts = [
            (part, plan["approval_claims"])
            for part in plan["parts"]
        ]
    elif plan["generation_intent"] == "quality_retake":
        if not selected_outputs_path:
            raise FanoutError(
                "quality_retake merge requires the explicit canonical "
                "selected_outputs.json write target"
            )
        unused_retry_path, retry_reservation = _load_bound_reservation(
            root,
            plan,
            None,
        )
        retry_part = plan["parts"][0]
        retry_state = retry_reservation["parts"][0]
        if (
            retry_state.get("part_id") != retry_part["part_id"]
            or retry_state.get("spent") is not True
            or retry_state.get("status") != "PASS"
        ):
            raise FanoutError(
                "quality_retake reservation is not spent PASS"
            )
        (
            baseline_path,
            unused_baseline_hash,
            baseline,
        ) = _validate_quality_retake(
            root,
            plan["job_id"],
            retry_part,
            expected_hash=plan[
                "baseline_selected_outputs_sha256"
            ],
        )
        if selected_outputs_path and (
            _resolve_path(root, selected_outputs_path)
            != baseline_path
        ):
            raise FanoutError(
                "quality_retake may replace only the bound canonical "
                "selected_outputs.json"
            )
        replacement = _validated_output(
            root,
            plan["job_id"],
            plan["stage"],
            plan["approval_claims"],
            retry_part,
        )
        outputs = []
        for item in baseline["outputs"]:
            if _part_id(item.get("part_id")) == retry_part["part_id"]:
                outputs.append(replacement)
            else:
                outputs.append(dict(item))
    else:
        unused_retry_path, retry_reservation = _load_bound_reservation(
            root,
            plan,
            None,
        )
        retry_part = plan["parts"][0]
        retry_state = retry_reservation["parts"][0]
        if (
            retry_state.get("part_id") != retry_part["part_id"]
            or retry_state.get("spent") is not True
            or retry_state.get("status") != "PASS"
        ):
            raise FanoutError(
                "targeted retry reservation is not spent PASS"
            )
        first_path = _fanout_dir(root, plan["job_id"]) / "reservation.json"
        if not first_path.is_file():
            raise FanoutError("attempt 1 reservation is missing")
        first = _load_json(first_path)
        if (
            first.get("schema_version") != 1
            or first.get("job_id") != plan["job_id"]
            or first.get("stage") != plan["stage"]
            or first.get("attempt") != 1
        ):
            raise FanoutError("attempt 1 reservation is invalid")
        target = retry_part["part_id"]
        for item in first.get("parts") or []:
            part_id = _part_id(item.get("part_id"))
            if part_id == target:
                selected_parts.append(
                    (retry_part, plan["approval_claims"])
                )
                continue
            if (
                item.get("spent") is not True
                or item.get("status") != "PASS"
            ):
                raise FanoutError(
                    f"{part_id} attempt 1 is not spent PASS"
                )
            selected_parts.append(
                (
                    _part_from_reservation(
                        root,
                        plan["job_id"],
                        1,
                        item,
                    ),
                    first.get("approval_claims"),
                )
            )
        if not any(
            part["part_id"] == target for part, unused_claims in selected_parts
        ):
            raise FanoutError(
                "targeted retry Part is missing from attempt 1 reservation"
            )

    if outputs is None:
        outputs = [
            _validated_output(
                root,
                plan["job_id"],
                plan["stage"],
                approval_claims,
                part,
            )
            for part, approval_claims in selected_parts
        ]
    outputs.sort(key=lambda item: _part_sort_key(item["part_id"]))

    selected = {
        "schema_version": 1,
        "attempt": plan["attempt"],
        "approval_claims": plan["approval_claims"],
        "outputs": outputs,
    }
    if selected_outputs_path:
        _write_json(_resolve_path(root, selected_outputs_path), selected)
    if plan["generation_intent"] == "quality_retake":
        _write_quality_retake_state(
            root,
            plan,
            status="selected_part_replaced",
            next_stage="finishing",
        )
    return selected


def write_plan(root, plan, path=None):
    _validate_plan(Path(root).resolve(), plan)
    filename = (
        "fanout_plan.json"
        if plan["attempt"] == 1
        else "fanout_plan_attempt_2.json"
    )
    target = (
        _resolve_path(root, path)
        if path
        else _fanout_dir(root, plan["job_id"]) / filename
    )
    _write_json(target, plan)
    return target


def _load_plan(root, job_id, path, attempt=1):
    filename = (
        "fanout_plan.json"
        if attempt == 1
        else "fanout_plan_attempt_2.json"
    )
    target = (
        _resolve_path(root, path)
        if path
        else _fanout_dir(root, job_id) / filename
    )
    if not target.is_file():
        raise FanoutError(f"generation plan not found: {target}")
    return target, _load_json(target)


def main():
    parser = argparse.ArgumentParser(
        description="Plan, reserve, run, and merge safe generation Part fanout."
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--job-id", required=True)
    subparsers = parser.add_subparsers(dest="action", required=True)

    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--stage", default=DEFAULT_STAGE)
    plan_parser.add_argument("--attempt", type=int, choices=(1, 2), default=1)
    plan_parser.add_argument(
        "--generation-intent",
        choices=tuple(sorted(GENERATION_INTENTS)),
        default="",
        help=(
            "current_job for attempt 1; failed_part_retry or "
            "quality_retake for one approved attempt-2 Part."
        ),
    )
    plan_parser.add_argument(
        "--request",
        action="append",
        default=[],
        metavar="PART=PATH",
        help="Explicit prepared request binding; repeat once per Part.",
    )
    plan_parser.add_argument("--approval-task-count", required=True, type=int)
    plan_parser.add_argument(
        "--approval-record",
        default="",
        help=(
            "Job-local explicit generation approval record; defaults to "
            "output/<job>/seedance/generation_approval.md."
        ),
    )
    plan_parser.add_argument("--out-plan", default="")
    plan_parser.add_argument("--json", action="store_true")

    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("--stage", default=DEFAULT_STAGE)
    preflight_parser.add_argument("--attempt", type=int, choices=(1, 2), default=1)
    preflight_parser.add_argument("--plan", default="")
    preflight_parser.add_argument("--max-workers", type=int, default=3)
    preflight_parser.add_argument("--json", action="store_true")

    reserve_parser = subparsers.add_parser("reserve")
    reserve_parser.add_argument("--stage", default=DEFAULT_STAGE)
    reserve_parser.add_argument("--attempt", type=int, choices=(1, 2), default=1)
    reserve_parser.add_argument("--plan", default="")
    reserve_parser.add_argument("--reservation", default="")
    reserve_parser.add_argument("--json", action="store_true")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--stage", default=DEFAULT_STAGE)
    run_parser.add_argument("--attempt", type=int, choices=(1, 2), default=1)
    run_parser.add_argument("--plan", default="")
    run_parser.add_argument("--reservation", default="")
    run_parser.add_argument("--max-workers", type=int, default=3)
    run_parser.add_argument("--json", action="store_true")

    merge_parser = subparsers.add_parser("merge")
    merge_parser.add_argument("--stage", default=DEFAULT_STAGE)
    merge_parser.add_argument("--attempt", type=int, choices=(1, 2), default=1)
    merge_parser.add_argument("--plan", default="")
    merge_parser.add_argument(
        "--out-selected-outputs",
        default="",
        help="Coordinator-only explicit write target; omitted by default.",
    )
    merge_parser.add_argument("--json", action="store_true")

    args = parser.parse_args()
    root = Path(args.root).resolve()
    try:
        if args.action == "plan":
            plan = build_plan(
                root,
                args.job_id,
                args.request,
                approval_task_count=args.approval_task_count,
                stage=args.stage,
                approval_record_path=args.approval_record or None,
                attempt=args.attempt,
                generation_intent=args.generation_intent or None,
            )
            target = write_plan(root, plan, args.out_plan)
            result = dict(plan)
            result["plan_path"] = str(target)
        else:
            unused_path, plan = _load_plan(
                root,
                args.job_id,
                args.plan,
                attempt=args.attempt,
            )
            if plan.get("job_id") != args.job_id:
                raise FanoutError("generation plan is bound to a different job")
            if plan.get("stage") != args.stage:
                raise FanoutError("generation plan is bound to a different stage")
            if plan.get("attempt") != args.attempt:
                raise FanoutError(
                    "generation plan is bound to a different attempt"
                )
            if args.action == "preflight":
                result = preflight_plan(
                    root,
                    plan,
                    max_workers=args.max_workers,
                )
            elif args.action == "reserve":
                result = reserve_plan(
                    root,
                    plan,
                    reservation_path=args.reservation or None,
                )
            elif args.action == "run":
                result = run_reserved_parts(
                    root,
                    plan,
                    reservation_path=args.reservation or None,
                    max_workers=args.max_workers,
                )
            else:
                result = merge_completions(
                    root,
                    plan,
                    selected_outputs_path=args.out_selected_outputs or None,
                )
        if getattr(args, "json", False):
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(result.get("overall", "PASS"))
        if result.get("overall") == "FAIL":
            return 1
        return 0
    except (FanoutError, OSError, json.JSONDecodeError) as exc:
        print(f"generation_fanout: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
