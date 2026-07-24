#!/usr/bin/env python3
"""Run post-QC source-rhythm composition tasks without rewriting source truth."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import re
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path

try:
    from . import stage_execution
except ImportError:
    import stage_execution


POLICY = "locked_source_rhythm_post_qc_fanout"
ALLOWED_FAMILIES = frozenset(
    {
        "story_view",
        "timeline_view",
        "shot_view",
        "role_product_seam_audit",
        "part_storyboard_rebuild",
    }
)
RESOURCE_LIMIT_CAPS = {
    "cpu": 8,
    "qwen_mlx": 1,
    "higress": 4,
    "ffmpeg": 4,
}
DEFAULT_RESOURCE_LIMITS = {
    "cpu": 8,
    "qwen_mlx": 1,
    "higress": 2,
    "ffmpeg": 2,
}
COORDINATOR_ONLY_PATHS = (
    "jobs.csv",
    "RUNNER_STATE.json",
    "STATE.md",
)


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_path(root, value):
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (Path(root) / path).resolve()


def display_path(root, path):
    root = Path(root).resolve()
    path = Path(path).resolve()
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def load_json(path):
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def stable_hash(payload):
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def is_within(path, parent):
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
    except ValueError:
        return False
    return True


def _validate_source_lock(
    root,
    source_rhythm_path,
    source_rhythm_sha256,
    source_rhythm_qc_path,
    expected_qc_binding=None,
):
    rhythm_path = resolve_path(root, source_rhythm_path)
    if not rhythm_path.is_file():
        raise ValueError(f"source rhythm is missing: {source_rhythm_path}")
    actual_sha256 = sha256_file(rhythm_path)
    if actual_sha256 != source_rhythm_sha256:
        raise ValueError(
            "source rhythm hash mismatch: "
            f"expected {source_rhythm_sha256}, actual {actual_sha256}"
        )

    qc_path = resolve_path(root, source_rhythm_qc_path)
    if not qc_path.is_file():
        raise ValueError(f"source rhythm QC is missing: {source_rhythm_qc_path}")
    qc = load_json(qc_path)
    if qc.get("overall") != "PASS":
        raise ValueError("external source rhythm QC must PASS")
    qc_rhythm = resolve_path(root, qc.get("source_rhythm") or "")
    if qc_rhythm != rhythm_path:
        raise ValueError("external source rhythm QC path mismatch")
    if qc.get("source_rhythm_sha256") != actual_sha256:
        raise ValueError("external source rhythm QC source hash mismatch")
    if qc_path.stat().st_mtime_ns < rhythm_path.stat().st_mtime_ns:
        raise ValueError(
            "external source rhythm QC is stale: "
            "source_rhythm.json changed after the PASS report"
        )
    qc_binding = {
        "source_rhythm_sha256": actual_sha256,
        "report_sha256": sha256_file(qc_path),
    }
    if expected_qc_binding:
        if (
            expected_qc_binding.get("source_rhythm_sha256")
            != qc_binding["source_rhythm_sha256"]
        ):
            raise ValueError("external source rhythm QC source hash mismatch")
        if expected_qc_binding.get("report_sha256") != qc_binding["report_sha256"]:
            raise ValueError("external source rhythm QC report hash mismatch")
    return rhythm_path, qc_path, qc_binding


def _resource_limits(configured):
    limits = dict(DEFAULT_RESOURCE_LIMITS)
    for name, value in (configured or {}).items():
        if name not in RESOURCE_LIMIT_CAPS:
            raise ValueError(f"unknown resource class limit: {name}")
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"{name} resource limit must be a positive integer")
        limits[name] = min(value, RESOURCE_LIMIT_CAPS[name])
    limits["qwen_mlx"] = 1
    return limits


def _assert_acyclic(tasks):
    dependencies = {
        task["task_id"]: set(task["depends_on"])
        for task in tasks
    }
    resolved = set()
    while len(resolved) < len(dependencies):
        ready = {
            task_id
            for task_id, needs in dependencies.items()
            if task_id not in resolved and needs <= resolved
        }
        if not ready:
            raise ValueError("source composition task dependencies contain a cycle")
        resolved.update(ready)


def _validate_tasks(root, bundle_root, tasks):
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("source composition plan requires at least one task")
    planned = []
    task_ids = set()
    output_roots = []
    for raw in tasks:
        if not isinstance(raw, dict):
            raise ValueError("source composition tasks must be objects")
        task_id = str(raw.get("task_id") or "").strip()
        if not task_id or not re.fullmatch(r"[A-Za-z0-9._-]+", task_id):
            raise ValueError("every source composition task requires a safe task_id")
        if task_id in task_ids:
            raise ValueError(f"duplicate source composition task_id: {task_id}")
        task_ids.add(task_id)

        family = str(raw.get("family") or "").strip()
        if family not in ALLOWED_FAMILIES:
            raise ValueError(f"{task_id} is not an allowed post-rhythm task family")
        executor_kind = str(raw.get("executor_kind") or "command").strip()
        if executor_kind not in {"command", "agent"}:
            raise ValueError(f"{task_id} executor_kind must be command or agent")
        command = raw.get("command")
        task_instructions = str(raw.get("task") or "").strip()
        if executor_kind == "command":
            if (
                not isinstance(command, list)
                or not command
                or any(
                    not isinstance(value, str) or not value.strip()
                    for value in command
                )
            ):
                raise ValueError(f"{task_id} command must be a nonempty string list")
        elif not task_instructions:
            raise ValueError(f"{task_id} agent task requires instructions")
        dependencies = raw.get("depends_on") or []
        if not isinstance(dependencies, list) or any(
            not isinstance(value, str) or not value.strip()
            for value in dependencies
        ):
            raise ValueError(f"{task_id} depends_on must be a string list")
        resource_class = str(raw.get("resource_class") or "cpu").strip()
        if resource_class not in RESOURCE_LIMIT_CAPS:
            raise ValueError(f"{task_id} has unknown resource class")

        task_output = resolve_path(
            root,
            raw.get("output_root") or bundle_root / "tasks" / task_id,
        )
        if not is_within(task_output, bundle_root) or task_output == bundle_root:
            raise ValueError(
                f"{task_id} output_root must be inside the composition output root"
            )
        for prior in output_roots:
            if is_within(task_output, prior) or is_within(prior, task_output):
                raise ValueError("source composition task output roots must be isolated")
        output_roots.append(task_output)
        planned_task = {
            "task_id": task_id,
            "family": family,
            "executor_kind": executor_kind,
            "depends_on": list(dependencies),
            "resource_class": resource_class,
            "output_root": display_path(root, task_output),
        }
        if executor_kind == "command":
            planned_task["command"] = list(command)
        else:
            planned_task["task"] = task_instructions
        planned.append(planned_task)

    known = {task["task_id"] for task in planned}
    for task in planned:
        missing = [value for value in task["depends_on"] if value not in known]
        if missing:
            raise ValueError(
                f"{task['task_id']} has unknown dependencies: {', '.join(missing)}"
            )
        if task["task_id"] in task["depends_on"]:
            raise ValueError(f"{task['task_id']} cannot depend on itself")
    _assert_acyclic(planned)
    return planned


def build_plan(
    root,
    job_id,
    source_rhythm_path,
    source_rhythm_sha256,
    source_rhythm_qc_path,
    cache_key,
    tasks,
    output_root=None,
    resource_limits=None,
):
    root = Path(root).resolve()
    if not re.fullmatch(r"[A-Za-z0-9._-]+", str(cache_key or "")):
        raise ValueError("cache_key must be a safe nonempty name")
    rhythm_path, qc_path, qc_binding = _validate_source_lock(
        root,
        source_rhythm_path,
        source_rhythm_sha256,
        source_rhythm_qc_path,
    )
    bundle_root = resolve_path(
        root,
        output_root
        or f"output/{job_id}/source-composition/{cache_key}",
    )
    job_output = (root / "output" / job_id).resolve()
    if not is_within(bundle_root, job_output):
        raise ValueError("composition output root must stay inside the job output")
    planned_tasks = _validate_tasks(root, bundle_root, tasks)
    limits = _resource_limits(resource_limits)
    plan = {
        "schema_version": 1,
        "job_id": job_id,
        "stage": "source_blueprint",
        "phase": "post_rhythm_composition",
        "policy": POLICY,
        "cache_key": cache_key,
        "source_rhythm": {
            "path": display_path(root, rhythm_path),
            "sha256": source_rhythm_sha256,
        },
        "source_rhythm_qc": {
            "path": display_path(root, qc_path),
            "overall": "PASS",
            **qc_binding,
        },
        "output_root": display_path(root, bundle_root),
        "bundle_path": display_path(
            root,
            bundle_root / "source_composition_bundle.json",
        ),
        "resource_limits": limits,
        "coordinator_only_paths": list(COORDINATOR_ONLY_PATHS)
        + [display_path(root, rhythm_path)],
        "tasks": planned_tasks,
    }
    execution = {
        "schema_version": 1,
        "job_id": job_id,
        "stage": "source_blueprint",
        "coordinator_only_paths": [
            display_path(root, rhythm_path),
            display_path(root, qc_path),
            plan["bundle_path"],
        ],
        "packets": [
            {
                "packet_id": task["task_id"],
                "executor_kind": task["executor_kind"],
                "depends_on": task["depends_on"],
                "allowed_write_roots": [task["output_root"]],
                "completion_path": display_path(
                    root,
                    resolve_path(root, task["output_root"])
                    / ".stage_completion.json",
                ),
                **(
                    {"command": task["command"]}
                    if task["executor_kind"] == "command"
                    else {"task": task["task"]}
                ),
            }
            for task in planned_tasks
        ],
    }
    plan["stage_execution"] = stage_execution.seal_plan(root, execution)
    plan["plan_sha256"] = stable_hash(plan)
    return plan


def _validate_bound_plan(root, plan):
    if plan.get("schema_version") != 1 or plan.get("policy") != POLICY:
        raise ValueError("invalid source composition plan")
    expected_plan_sha = plan.get("plan_sha256")
    unsigned = dict(plan)
    unsigned.pop("plan_sha256", None)
    if not expected_plan_sha or stable_hash(unsigned) != expected_plan_sha:
        raise ValueError("source composition plan hash mismatch")
    _validate_source_lock(
        root,
        plan["source_rhythm"]["path"],
        plan["source_rhythm"]["sha256"],
        plan["source_rhythm_qc"]["path"],
        plan["source_rhythm_qc"],
    )
    bundle_root = resolve_path(root, plan["output_root"])
    _validate_tasks(root, bundle_root, plan["tasks"])
    _resource_limits(plan.get("resource_limits"))
    stage_execution.validate_plan(root, plan.get("stage_execution") or {})
    return plan


@contextmanager
def _exclusive_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _expanded_command(root, plan, task):
    replacements = {
        "{output_root}": str(resolve_path(root, task["output_root"])),
        "{source_rhythm}": str(
            resolve_path(root, plan["source_rhythm"]["path"])
        ),
        "{source_rhythm_sha256}": plan["source_rhythm"]["sha256"],
    }
    return [
        replacements.get(value, value)
        for value in task["command"]
    ]


def _output_bindings(root, output_root):
    output_root = resolve_path(root, output_root)
    if not output_root.is_dir():
        return []
    outputs = []
    for path in sorted(output_root.rglob("*")):
        if path.is_file():
            outputs.append(
                {
                    "path": display_path(root, path),
                    "sha256": sha256_file(path),
                }
            )
    return outputs


def _rewrite_task_staging_references(staged_root, canonical_root):
    """Keep promoted text manifests from retaining packet-local staging paths."""
    staged_root = Path(staged_root).resolve()
    canonical_root = Path(canonical_root).resolve()
    old = str(staged_root)
    new = str(canonical_root)
    if old == new or not staged_root.is_dir():
        return
    for path in staged_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {
            ".json",
            ".md",
            ".txt",
            ".csv",
        }:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if old in content:
            path.write_text(content.replace(old, new), encoding="utf-8")


def _run_task(root, plan, task, runner):
    output_root = resolve_path(root, task["output_root"])
    output_root.mkdir(parents=True, exist_ok=True)
    command = _expanded_command(root, plan, task)
    try:
        completed = runner(
            command,
            cwd=Path(root),
            text=True,
            capture_output=True,
            check=False,
        )
        returncode = int(completed.returncode)
        error = ""
    except PermissionError:
        raise
    except Exception as exc:  # pragma: no cover - exercised through public result
        returncode = 1
        error = f"runner raised: {exc}"
    outputs = _output_bindings(root, task["output_root"])
    status = "PASS" if returncode == 0 and outputs else "FAIL"
    if returncode == 0 and not outputs:
        error = "task produced no output files"
    result = {
        "task_id": task["task_id"],
        "family": task["family"],
        "resource_class": task["resource_class"],
        "status": status,
        "returncode": returncode,
        "output_root": task["output_root"],
        "outputs": outputs,
    }
    if error:
        result["error"] = error
    return result


def _run_agent_task(root, plan, task, dispatcher):
    if dispatcher is None:
        return {
            "task_id": task["task_id"],
            "family": task["family"],
            "resource_class": task["resource_class"],
            "status": "FAIL",
            "returncode": 2,
            "output_root": task["output_root"],
            "outputs": [],
            "error": "agent task requires an injected agent_dispatcher",
        }
    output_root = resolve_path(root, task["output_root"])
    output_root.mkdir(parents=True, exist_ok=True)
    try:
        response = dispatcher(task, plan)
        if not isinstance(response, dict):
            raise ValueError("agent dispatcher result must be an object")
        status = str(response.get("status") or "").upper()
        if status not in {"PASS", "FAIL", "STOP"}:
            raise ValueError("agent dispatcher status must be PASS, FAIL, or STOP")
        bindings = []
        for raw_path in response.get("outputs") or []:
            path = resolve_path(root, raw_path)
            if not is_within(path, output_root) or not path.is_file():
                raise ValueError(
                    f"agent output is missing or outside task output_root: {raw_path}"
                )
            bindings.append(
                {
                    "path": display_path(root, path),
                    "sha256": sha256_file(path),
                }
            )
        if status == "PASS" and not bindings:
            raise ValueError("PASS agent task produced no output files")
        return {
            "task_id": task["task_id"],
            "family": task["family"],
            "resource_class": task["resource_class"],
            "status": status,
            "returncode": 0 if status == "PASS" else 1,
            "output_root": task["output_root"],
            "outputs": bindings,
            **(
                {"error": str(response["error"])}
                if response.get("error")
                else {}
            ),
        }
    except PermissionError:
        raise
    except Exception as exc:
        return {
            "task_id": task["task_id"],
            "family": task["family"],
            "resource_class": task["resource_class"],
            "status": "FAIL",
            "returncode": 1,
            "output_root": task["output_root"],
            "outputs": [],
            "error": str(exc),
        }


def _bundle_is_reusable(root, plan, bundle):
    if (
        bundle.get("schema_version") != 1
        or bundle.get("overall") != "PASS"
        or bundle.get("plan_sha256") != plan["plan_sha256"]
        or bundle.get("source_rhythm") != plan["source_rhythm"]
        or bundle.get("cache_key") != plan["cache_key"]
    ):
        return False
    expected_ids = sorted(task["task_id"] for task in plan["tasks"])
    if [task.get("task_id") for task in bundle.get("tasks", [])] != expected_ids:
        return False
    for task in bundle["tasks"]:
        if task.get("status") != "PASS" or not task.get("outputs"):
            return False
        for output in task["outputs"]:
            path = resolve_path(root, output.get("path") or "")
            if not path.is_file() or sha256_file(path) != output.get("sha256"):
                return False
    return True


def _build_bundle(plan, results):
    ordered = sorted(results, key=lambda item: item["task_id"])
    statuses = {item["status"] for item in ordered}
    if "FAIL" in statuses:
        overall = "FAIL"
    elif "STOP" in statuses:
        overall = "STOP"
    else:
        overall = "PASS"
    return {
        "schema_version": 1,
        "policy": POLICY,
        "job_id": plan["job_id"],
        "cache_key": plan["cache_key"],
        "plan_sha256": plan["plan_sha256"],
        "source_rhythm": plan["source_rhythm"],
        "overall": overall,
        "canonical_merge": "NOT_PERFORMED",
        "checker_review": "NOT_PERFORMED",
        "next_action": "coordinator_merge_then_single_checker_review",
        "tasks": ordered,
    }


def run_plan(
    root,
    plan,
    max_workers=8,
    runner=subprocess.run,
    agent_dispatcher=None,
):
    root = Path(root).resolve()
    if not isinstance(plan, dict):
        plan = load_json(resolve_path(root, plan))
    _validate_bound_plan(root, plan)
    bundle_path = resolve_path(root, plan["bundle_path"])
    singleflight_key = stable_hash(
        {
            "source_rhythm_sha256": plan["source_rhythm"]["sha256"],
            "cache_key": plan["cache_key"],
        }
    )
    lock_path = (
        resolve_path(root, plan["output_root"])
        / ".locks"
        / f"{singleflight_key}.lock"
    )
    with _exclusive_lock(lock_path):
        if bundle_path.is_file():
            existing = load_json(bundle_path)
            if _bundle_is_reusable(root, plan, existing):
                return existing

        task_by_id = {task["task_id"]: task for task in plan["tasks"]}
        results = {}
        results_lock = threading.Lock()
        worker_limit = max(
            1,
            min(
                int(max_workers),
                RESOURCE_LIMIT_CAPS["cpu"],
                len(task_by_id),
            ),
        )
        resource_slots = {
            resource_class: threading.BoundedSemaphore(limit)
            for resource_class, limit in plan["resource_limits"].items()
        }

        def dispatch(packet):
            task_id = packet["packet_id"]
            task = task_by_id[task_id]
            runtime_task = dict(task)
            runtime_task["output_root"] = str(
                stage_execution.runtime_path(
                    root,
                    packet,
                    task["output_root"],
                )
            )
            if runtime_task["executor_kind"] == "command":
                runtime_task["command"] = list(packet["command"])
            with resource_slots[runtime_task["resource_class"]]:
                runtime_result = (
                    _run_agent_task(
                        root,
                        plan,
                        runtime_task,
                        agent_dispatcher,
                    )
                    if task["executor_kind"] == "agent"
                    else _run_task(
                        root,
                        plan,
                        runtime_task,
                        runner,
                    )
                )
            if runtime_result["status"] == "PASS":
                _rewrite_task_staging_references(
                    runtime_task["output_root"],
                    resolve_path(root, task["output_root"]),
                )
                runtime_result["outputs"] = _output_bindings(
                    root,
                    runtime_task["output_root"],
                )
            result = dict(runtime_result)
            result["output_root"] = task["output_root"]
            result["outputs"] = [
                {
                    **binding,
                    "path": display_path(
                        root,
                        stage_execution.canonical_path(
                            root,
                            packet,
                            binding["path"],
                        ),
                    ),
                }
                for binding in runtime_result["outputs"]
            ]
            with results_lock:
                results[task_id] = result
            return {
                "status": result["status"],
                "outputs": [
                    item["path"]
                    for item in runtime_result["outputs"]
                ],
                "returncode": result["returncode"],
                "error": result.get("error", ""),
            }

        committed = {}

        def commit(stage_report):
            for completion in stage_report["completions"]:
                task_id = completion["packet_id"]
                task = task_by_id[task_id]
                if task_id not in results:
                    results[task_id] = {
                        "task_id": task_id,
                        "family": task["family"],
                        "resource_class": task["resource_class"],
                        "status": completion["status"],
                        "returncode": completion.get("returncode", 2),
                        "output_root": task["output_root"],
                        "outputs": [],
                        "error": completion.get(
                            "error",
                            "blocked by failed dependency",
                        ),
                    }
                    continue
                result = results[task_id]
                if completion["status"] != result["status"]:
                    result["status"] = completion["status"]
                    result["returncode"] = completion.get("returncode", 2)
                    result["outputs"] = []
                    result["error"] = completion.get(
                        "error",
                        "stage execution overrode the task result",
                    )
            bundle = _build_bundle(plan, list(results.values()))
            write_json(bundle_path, bundle)
            committed["bundle"] = bundle

        stage_execution.execute_plan(
            root,
            plan["stage_execution"],
            dispatcher=dispatch,
            coordinator_commit=commit,
            max_workers=worker_limit,
        )
        return committed["bundle"]


def main():
    parser = argparse.ArgumentParser(
        description="Plan or run locked post-rhythm source composition."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--root", default=".")
    plan_parser.add_argument("--spec", required=True)
    plan_parser.add_argument("--out", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--root", default=".")
    run_parser.add_argument("--plan", required=True)
    run_parser.add_argument("--max-workers", type=int, default=8)

    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve()
    if args.command == "plan":
        spec = load_json(resolve_path(root, args.spec))
        plan = build_plan(root=root, **spec)
        output_path = resolve_path(root, args.out)
        write_json(output_path, plan)
        print(f"SOURCE_COMPOSITION_PLAN={output_path}")
        return

    bundle = run_plan(root, args.plan, max_workers=args.max_workers)
    print(f"SOURCE_COMPOSITION={bundle['overall']}")
    print(f"SOURCE_COMPOSITION_BUNDLE={resolve_path(root, load_json(resolve_path(root, args.plan))['bundle_path'])}")
    raise SystemExit(0 if bundle["overall"] == "PASS" else 1)


if __name__ == "__main__":
    main()
