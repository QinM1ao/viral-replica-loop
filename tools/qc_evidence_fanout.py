#!/usr/bin/env python3
"""Run isolated deterministic QC evidence tasks concurrently."""

import argparse
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

try:
    from . import stage_execution
except ImportError:
    import stage_execution


POLICY = "deterministic_evidence_only"
MAX_WORKERS = 8
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
VALID_STATUSES = {"PASS", "FAIL", "STOP"}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_command(command):
    if (
        not isinstance(command, list)
        or not command
        or any(not isinstance(token, str) or not token for token in command)
    ):
        raise ValueError("command must be a nonempty list of nonempty strings")


def validate_identifier(value, field):
    if not isinstance(value, str) or not IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"{field} must contain only letters, numbers, underscores, and hyphens")


def validate_report_path(root, evidence_dir, report_path):
    if not isinstance(report_path, str) or not report_path:
        raise ValueError(f"report_path must be inside {evidence_dir.as_posix()}")
    raw = Path(report_path)
    if raw.is_absolute():
        raise ValueError(f"report_path must be inside {evidence_dir.as_posix()}")
    target = (root / raw).resolve()
    allowed = (root / evidence_dir).resolve()
    try:
        target.relative_to(allowed)
    except ValueError:
        raise ValueError(
            f"report_path must be inside {evidence_dir.as_posix()}"
        ) from None
    return target.relative_to(root).as_posix()


def execution_packet(task):
    return {
        "packet_id": task["name"],
        "command": task["command"],
        "depends_on": [],
        "allowed_write_roots": [
            task["report_path"],
            *task["additional_output_paths"],
            task["stdout_log"],
            task["stderr_log"],
            task["result_path"],
        ],
        "completion_path": task["completion_path"],
    }


def validate_evidence_plan(root, plan):
    if not isinstance(plan, dict):
        raise ValueError("plan must be an object")
    expected_hash = plan.get("plan_sha256")
    if not expected_hash:
        raise ValueError("QC evidence plan requires plan_sha256")
    unsigned = dict(plan)
    unsigned.pop("plan_sha256")
    if stage_execution.stable_hash(unsigned) != expected_hash:
        raise ValueError("QC evidence plan hash mismatch")

    execution = plan.get("stage_execution")
    if not execution:
        raise ValueError("QC evidence plan requires sealed stage_execution")
    stage_execution.validate_plan(root, execution)
    if (
        execution.get("job_id") != plan.get("job_id")
        or execution.get("stage") != plan.get("stage")
    ):
        raise ValueError("QC evidence plan identity does not match stage_execution")
    expected_packets = [execution_packet(task) for task in plan.get("tasks") or []]
    if execution.get("packets") != expected_packets:
        raise ValueError(
            "QC evidence tasks do not match sealed stage_execution packets"
        )
    return plan


def build_plan(root, job_id, stage, tasks):
    root = Path(root).resolve()
    validate_identifier(job_id, "job_id")
    validate_identifier(stage, "stage")
    evidence_dir = Path("output") / job_id / "checks" / "evidence" / stage
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("tasks must be a nonempty list")
    normalized = []
    names = set()
    report_paths = set()
    commands = set()
    artifact_paths = {(evidence_dir / "evidence_bundle.json").as_posix()}
    for item in tasks:
        if not isinstance(item, dict):
            raise ValueError("each task must be an object")
        task = dict(item)
        name = task.get("name")
        validate_identifier(name, "task name")
        kind = str(task.get("kind") or "").strip().lower()
        if kind == "semantic":
            raise ValueError("semantic families are not allowed in deterministic evidence fanout")
        if kind != "deterministic":
            raise ValueError("task kind must be deterministic")
        validate_command(task.get("command"))
        report_path = validate_report_path(
            root,
            evidence_dir,
            task.get("report_path"),
        )
        additional_output_paths = [
            validate_report_path(root, evidence_dir, value)
            for value in task.get("additional_output_paths") or []
        ]
        if len(set(additional_output_paths)) != len(additional_output_paths):
            raise ValueError(f"duplicate additional output path for task: {name}")
        command_key = tuple(task["command"])
        if name in names:
            raise ValueError(f"duplicate task name: {name}")
        if report_path in report_paths:
            raise ValueError(f"duplicate report_path: {report_path}")
        if command_key in commands:
            raise ValueError(f"duplicate command: {task['command']}")
        names.add(name)
        report_paths.add(report_path)
        commands.add(command_key)
        task["kind"] = kind
        task["report_path"] = report_path
        task["additional_output_paths"] = additional_output_paths
        task["stdout_log"] = (evidence_dir / f"{name}.stdout.log").as_posix()
        task["stderr_log"] = (evidence_dir / f"{name}.stderr.log").as_posix()
        task["result_path"] = (evidence_dir / f"{name}.result.json").as_posix()
        task["completion_path"] = (
            evidence_dir / f"{name}.completion.json"
        ).as_posix()
        task_paths = {
            report_path,
            *additional_output_paths,
            task["stdout_log"],
            task["stderr_log"],
            task["result_path"],
            task["completion_path"],
        }
        if (
            len(task_paths) != 5 + len(additional_output_paths)
            or task_paths.intersection(artifact_paths)
        ):
            raise ValueError(f"report_path must be independent: {report_path}")
        artifact_paths.update(task_paths)
        normalized.append(task)
    plan = {
        "version": 1,
        "job_id": job_id,
        "stage": stage,
        "policy": POLICY,
        "evidence_dir": evidence_dir.as_posix(),
        "bundle_path": (evidence_dir / "evidence_bundle.json").as_posix(),
        "tasks": normalized,
    }
    execution = {
        "schema_version": 1,
        "job_id": job_id,
        "stage": stage,
        "coordinator_only_paths": [
            plan["bundle_path"],
            (
                Path("output")
                / job_id
                / "checks"
                / f"{stage}_qc_risk_ledger.json"
            ).as_posix(),
            (Path("output") / job_id / "checks" / "qc_risk_ledger_state.json").as_posix(),
            (
                Path("output")
                / job_id
                / "checks"
                / f"{stage}_semantic_review_request.json"
            ).as_posix(),
        ],
        "packets": [execution_packet(item) for item in normalized],
    }
    plan["stage_execution"] = stage_execution.seal_plan(root, execution)
    plan["plan_sha256"] = stage_execution.stable_hash(plan)
    validate_evidence_plan(root, plan)
    return plan


def report_status(path):
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return "STOP", f"report unavailable: {exc}"
    if not isinstance(report, dict):
        return "STOP", "report must be a JSON object"
    status = str(report.get("overall") or report.get("status") or "").upper()
    if status not in VALID_STATUSES:
        return "STOP", "report must declare overall/status as PASS, FAIL, or STOP"
    return status, "status loaded from deterministic report"


def run_task(root, item, runner, clock):
    paths = {
        key: root / item[key]
        for key in ("report_path", "stdout_log", "stderr_log", "result_path")
    }
    additional_paths = [
        root / value
        for value in item.get("additional_output_paths") or []
    ]
    for path in [*paths.values(), *additional_paths]:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        path.parent.mkdir(parents=True, exist_ok=True)

    started = clock()
    runner_error = ""
    try:
        completed = runner(
            item["command"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        returncode = int(completed.returncode)
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
    except Exception as exc:
        returncode = -1
        stdout = ""
        stderr = ""
        runner_error = f"runner error: {exc}"
    duration = round(max(0.0, clock() - started), 6)

    paths["stdout_log"].write_text(str(stdout), encoding="utf-8")
    paths["stderr_log"].write_text(str(stderr), encoding="utf-8")
    status, reason = report_status(paths["report_path"])
    if runner_error:
        status = "STOP"
        reason = runner_error
    elif status == "PASS" and returncode != 0:
        status = "FAIL"
        reason = "command exited nonzero despite a PASS report"
    elif status == "PASS" and any(
        not path.is_file()
        for path in additional_paths
    ):
        status = "FAIL"
        reason = "required additional deterministic output is missing"

    result = {
        "name": item["name"],
        "kind": "deterministic",
        "status": status,
        "path": item["report_path"],
        "sha256": (
            sha256_file(paths["report_path"])
            if paths["report_path"].is_file()
            else None
        ),
        "command": list(item["command"]),
        "returncode": returncode,
        "duration_seconds": duration,
        "stdout_log": item["stdout_log"],
        "stderr_log": item["stderr_log"],
        "result_path": item["result_path"],
        "additional_outputs": [
            {
                "path": item["additional_output_paths"][index],
                "sha256": sha256_file(path) if path.is_file() else None,
            }
            for index, path in enumerate(additional_paths)
        ],
        "reason": reason,
    }
    write_json(paths["result_path"], result)
    return result


def run_bundle(
    root,
    plan,
    max_workers=4,
    runner=subprocess.run,
    clock=time.monotonic,
):
    root = Path(root).resolve()
    validated = validate_evidence_plan(root, plan)
    if not isinstance(max_workers, int) or max_workers < 1:
        raise ValueError("max_workers must be a positive integer")
    worker_count = min(max_workers, MAX_WORKERS, len(validated["tasks"]))

    results_by_name = {}
    committed = {}

    def dispatch(packet):
        item = next(
            task
            for task in validated["tasks"]
            if task["name"] == packet["packet_id"]
        )
        runtime_item = dict(item)
        runtime_item["command"] = list(packet["command"])
        for key in (
            "report_path",
            "stdout_log",
            "stderr_log",
            "result_path",
        ):
            runtime_item[key] = str(
                stage_execution.runtime_path(
                    root,
                    packet,
                    item[key],
                )
            )
        runtime_item["additional_output_paths"] = [
            str(stage_execution.runtime_path(root, packet, value))
            for value in item.get("additional_output_paths") or []
        ]
        runtime_result = run_task(
            root,
            runtime_item,
            runner,
            clock,
        )
        result = dict(runtime_result)
        result["path"] = item["report_path"]
        result["command"] = list(item["command"])
        result["stdout_log"] = item["stdout_log"]
        result["stderr_log"] = item["stderr_log"]
        result["result_path"] = item["result_path"]
        result["additional_outputs"] = [
            {
                **binding,
                "path": item["additional_output_paths"][index],
            }
            for index, binding in enumerate(
                runtime_result["additional_outputs"]
            )
        ]
        write_json(Path(runtime_item["result_path"]), result)
        results_by_name[item["name"]] = result
        output_paths = [
            runtime_item["stdout_log"],
            runtime_item["stderr_log"],
            runtime_item["result_path"],
            *(
                [runtime_item["report_path"]]
                if Path(runtime_item["report_path"]).is_file()
                else []
            ),
            *[
                path
                for path in runtime_item["additional_output_paths"]
                if Path(path).is_file()
            ],
        ]
        deleted_outputs = [
            runtime_value
            for canonical_value, runtime_value in [
                (item["report_path"], runtime_item["report_path"]),
                *zip(
                    item["additional_output_paths"],
                    runtime_item["additional_output_paths"],
                ),
            ]
            if (
                (root / canonical_value).is_file()
                and not Path(runtime_value).exists()
                and not Path(runtime_value).is_symlink()
            )
        ]
        return {
            "status": result["status"],
            "outputs": output_paths,
            "deleted_outputs": deleted_outputs,
            "returncode": result["returncode"],
            "error": result.get("reason", ""),
        }

    def commit(stage_report):
        for completion in stage_report["completions"]:
            name = completion["packet_id"]
            result = results_by_name.get(name)
            if result is None:
                item = next(
                    task
                    for task in validated["tasks"]
                    if task["name"] == name
                )
                result = {
                    "name": name,
                    "kind": "deterministic",
                    "status": completion["status"],
                    "path": item["report_path"],
                    "sha256": None,
                    "command": list(item["command"]),
                    "returncode": completion.get("returncode", 2),
                    "duration_seconds": 0.0,
                    "stdout_log": item["stdout_log"],
                    "stderr_log": item["stderr_log"],
                    "result_path": item["result_path"],
                    "additional_outputs": [],
                    "reason": completion.get(
                        "error",
                        "stage execution did not produce a domain result",
                    ),
                }
                results_by_name[name] = result
            if completion["status"] != result["status"]:
                result["status"] = completion["status"]
                result["returncode"] = completion.get("returncode", 2)
                result["reason"] = completion.get(
                    "error",
                    "stage execution overrode the deterministic result",
                )

        ordered_results = [
            results_by_name[item["name"]]
            for item in validated["tasks"]
        ]
        families = []
        for item, result in zip(validated["tasks"], ordered_results):
            family = {
                "name": item["name"],
                "kind": "deterministic",
                "evidence": [result],
                "active_seconds": result["duration_seconds"],
                "wait_seconds": 0.0,
            }
            for key in ("fingerprint", "fingerprint_hash", "scope"):
                if key in item:
                    family[key] = item[key]
            families.append(family)

        bundle = {
            "version": 1,
            "job_id": validated["job_id"],
            "stage": validated["stage"],
            "policy": POLICY,
            "overall": stage_report["overall"],
            "max_workers": worker_count,
            "families": families,
            "bundle_path": validated["bundle_path"],
        }
        write_json(root / validated["bundle_path"], bundle)
        committed["bundle"] = bundle

    stage_execution.execute_plan(
        root,
        validated["stage_execution"],
        dispatcher=dispatch,
        coordinator_commit=commit,
        max_workers=worker_count,
    )
    return committed["bundle"]


def coordinate_ledger(
    root,
    bundle,
    semantic_families=None,
    previous=None,
    write=False,
):
    """Evaluate all families once after deterministic fan-out completes."""
    root = Path(root).resolve()
    if not isinstance(bundle, dict):
        raise ValueError("evidence bundle must be an object")
    if bundle.get("version") != 1 or bundle.get("policy") != POLICY:
        raise ValueError("evidence bundle is invalid")
    job_id = bundle.get("job_id")
    stage = bundle.get("stage")
    validate_identifier(job_id, "job_id")
    validate_identifier(stage, "stage")

    deterministic_families = bundle.get("families")
    if not isinstance(deterministic_families, list) or not deterministic_families:
        raise ValueError("evidence bundle must contain deterministic families")
    combined = []
    names = set()
    for family in deterministic_families:
        if not isinstance(family, dict) or family.get("kind") != "deterministic":
            raise ValueError("evidence bundle may contain only deterministic families")
        name = family.get("name")
        validate_identifier(name, "family name")
        if name in names:
            raise ValueError(f"duplicate ledger family: {name}")
        names.add(name)
        combined.append(dict(family))
    for family in semantic_families or []:
        if not isinstance(family, dict) or family.get("kind") != "semantic":
            raise ValueError("coordinator semantic families must use kind=semantic")
        name = family.get("name")
        validate_identifier(name, "family name")
        if name in names:
            raise ValueError(f"duplicate ledger family: {name}")
        names.add(name)
        combined.append(dict(family))

    from qc_risk_ledger import (
        evaluate_risk_families,
        ledger_state_path,
        load_previous_ledger,
    )

    prior = previous
    if prior is None:
        prior = load_previous_ledger(root, job_id)
    ledger = evaluate_risk_families(
        job_id,
        stage,
        combined,
        previous=prior,
    )
    checks = root / "output" / job_id / "checks"
    ledger_path = checks / f"{stage}_qc_risk_ledger.json"
    request_path = checks / f"{stage}_semantic_review_request.json"
    ledger["ledger_path"] = ledger_path.relative_to(root).as_posix()
    if write:
        write_json(ledger_path, ledger)
        write_json(ledger_state_path(root, job_id), ledger)
        if ledger["semantic_review_request"]["required"]:
            write_json(request_path, ledger["semantic_review_request"])
        else:
            request_path.unlink(missing_ok=True)
    return ledger


def load_spec(root, raw_path):
    path = Path(raw_path)
    if not path.is_absolute():
        path = root / path
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not load fanout spec: {exc}") from None
    if not isinstance(value, dict):
        raise ValueError("fanout spec must be a JSON object")
    return value


def main():
    parser = argparse.ArgumentParser(
        description="Run isolated deterministic QC evidence tasks in parallel."
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--spec", required=True)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--dry-plan", action="store_true")
    parser.add_argument(
        "--coordinate-ledger",
        action="store_true",
        help="After fan-out, evaluate all families once and write canonical ledger state.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    try:
        spec = load_spec(root, args.spec)
        plan = build_plan(
            root,
            spec.get("job_id"),
            spec.get("stage"),
            spec.get("tasks"),
        )
        if args.dry_plan:
            print(json.dumps(plan, ensure_ascii=False, indent=2))
            return
        bundle = run_bundle(
            root,
            plan,
            max_workers=args.max_workers,
        )
        if args.coordinate_ledger:
            ledger = coordinate_ledger(
                root,
                bundle,
                semantic_families=spec.get("semantic_families") or [],
                write=True,
            )
    except ValueError as exc:
        parser.error(str(exc))
        return

    result = (
        {"evidence_bundle": bundle, "qc_risk_ledger": ledger}
        if args.coordinate_ledger
        else bundle
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    overall = ledger["overall"] if args.coordinate_ledger else bundle["overall"]
    if overall != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
