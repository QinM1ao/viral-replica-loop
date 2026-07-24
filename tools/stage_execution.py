#!/usr/bin/env python3
"""Validate one-job, one-stage work packets for safe parallel execution."""

from __future__ import annotations

import _thread
import ctypes
import errno
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


DEFAULT_COORDINATOR_ONLY_PATHS = (
    "jobs.csv",
    "RUNNER_STATE.json",
    "STATE.md",
)
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
RESTORABLE_SUFFIXES = {
    ".csv",
    ".json",
    ".jsonl",
    ".log",
    ".md",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
MAX_RESTORABLE_BYTES = 1024 * 1024
MAX_TOTAL_RESTORABLE_BYTES = 32 * 1024 * 1024
IGNORED_RUNTIME_NAMES = {
    ".cache",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
}
IGNORED_RUNTIME_SUFFIXES = {".pyc", ".pyo"}
_CLONEFILE = None
_CLONEFILE_CHECKED = False
if not hasattr(subprocess, "_stage_execution_packet_policy"):
    subprocess._stage_execution_packet_policy = threading.local()
if not hasattr(subprocess, "_stage_execution_original_popen"):
    subprocess._stage_execution_original_popen = subprocess.Popen
_PACKET_POLICY = subprocess._stage_execution_packet_policy
_ORIGINAL_POPEN = subprocess._stage_execution_original_popen
if not hasattr(threading, "_stage_execution_original_thread_start"):
    threading._stage_execution_original_thread_start = threading.Thread.start
_ORIGINAL_THREAD_START = threading._stage_execution_original_thread_start
if not hasattr(_thread, "_stage_execution_original_start_new_thread"):
    _thread._stage_execution_original_start_new_thread = (
        _thread.start_new_thread
    )
_ORIGINAL_START_NEW_THREAD = (
    _thread._stage_execution_original_start_new_thread
)
if hasattr(_thread, "start_new"):
    if not hasattr(_thread, "_stage_execution_original_start_new"):
        _thread._stage_execution_original_start_new = _thread.start_new
    _ORIGINAL_START_NEW = _thread._stage_execution_original_start_new
else:
    _ORIGINAL_START_NEW = None
if hasattr(os, "fork"):
    if not hasattr(os, "_stage_execution_original_fork"):
        os._stage_execution_original_fork = os.fork
    _ORIGINAL_FORK = os._stage_execution_original_fork
else:
    _ORIGINAL_FORK = None
if hasattr(os, "forkpty"):
    if not hasattr(os, "_stage_execution_original_forkpty"):
        os._stage_execution_original_forkpty = os.forkpty
    _ORIGINAL_FORKPTY = os._stage_execution_original_forkpty
else:
    _ORIGINAL_FORKPTY = None


def _policy_path(value):
    if isinstance(value, int) or value is None:
        return None
    try:
        return Path(os.path.abspath(os.fsdecode(value)))
    except (TypeError, ValueError):
        return None


def _policy_path_allowed(policy, value):
    path = _policy_path(value)
    if path is None:
        return True
    resolved = path.resolve(strict=False)
    return any(
        path == allowed
        or is_within(path, allowed)
        or resolved == allowed
        or is_within(resolved, allowed)
        for allowed in policy["allowed_roots"]
    )


def _deny_packet_mutation(policy, event, value):
    path = _policy_path(value)
    detail = str(path) if path is not None else repr(value)
    message = f"packet filesystem policy blocked {event}: {detail}"
    policy["violations"].append(message)
    raise PermissionError(errno.EPERM, message, detail)


def _packet_audit_hook(event, args):
    policy = getattr(_PACKET_POLICY, "current", None)
    if policy is None:
        return
    if event == "open":
        path = args[0] if args else None
        mode = args[1] if len(args) > 1 else None
        flags = args[2] if len(args) > 2 else 0
        writes = (
            isinstance(mode, str)
            and any(value in mode for value in "wax+")
        ) or (
            isinstance(flags, int)
            and flags
            & (
                os.O_WRONLY
                | os.O_RDWR
                | os.O_CREAT
                | os.O_TRUNC
                | os.O_APPEND
            )
        )
        if writes and not _policy_path_allowed(policy, path):
            _deny_packet_mutation(policy, event, path)
        return
    if event in {"os.symlink", "os.link"}:
        _deny_packet_mutation(
            policy,
            event,
            args[1] if len(args) > 1 else None,
        )
    if event in {"os.rename", "os.replace"}:
        for value in args[:2]:
            if not _policy_path_allowed(policy, value):
                _deny_packet_mutation(policy, event, value)
        return
    if event in {
        "os.chdir",
        "os.chmod",
        "os.chown",
        "os.lchown",
        "os.mkdir",
        "os.remove",
        "os.rmdir",
        "os.truncate",
        "os.unlink",
        "os.utime",
    }:
        value = args[0] if args else None
        if not _policy_path_allowed(policy, value):
            _deny_packet_mutation(policy, event, value)
        return
    if event in {"os.system", "os.exec", "os.spawn"}:
        _deny_packet_mutation(policy, event, args[0] if args else None)
    if (
        event in {"os.posix_spawn", "os.posix_spawnp"}
        and not getattr(_PACKET_POLICY, "launching_sandbox", False)
    ):
        _deny_packet_mutation(policy, event, args[0] if args else None)


def _sandbox_profile(policy):
    predicates = " ".join(
        f"(subpath {json.dumps(str(path), ensure_ascii=False)})"
        for path in policy["sandbox_write_roots"]
    )
    return (
        "(version 1)"
        "(allow default)"
        "(deny file-write* "
        f"(require-not (require-any {predicates})))"
    )


def _sandboxed_popen(*popenargs, **kwargs):
    policy = getattr(_PACKET_POLICY, "current", None)
    if policy is None:
        return _ORIGINAL_POPEN(*popenargs, **kwargs)
    sandbox_exec = Path("/usr/bin/sandbox-exec")
    if not sandbox_exec.is_file():
        _deny_packet_mutation(
            policy,
            "subprocess without OS write sandbox",
            sandbox_exec,
        )
    if popenargs:
        command = popenargs[0]
        remaining = popenargs[1:]
    else:
        command = kwargs.pop("args")
        remaining = ()
    shell = bool(kwargs.pop("shell", False))
    executable = kwargs.pop("executable", None)
    if shell:
        if not isinstance(command, str):
            command = subprocess.list2cmdline(
                [os.fsdecode(value) for value in command]
            )
        command = ["/bin/sh", "-c", command]
    elif isinstance(command, (str, bytes, os.PathLike)):
        command = [os.fsdecode(command)]
    else:
        command = [os.fsdecode(value) for value in command]
    if executable is not None:
        command[0] = os.fsdecode(executable)
    wrapped = [
        str(sandbox_exec),
        "-p",
        _sandbox_profile(policy),
        *command,
    ]
    packet_temp_root = str(policy["sandbox_write_roots"][0])
    child_env = dict(kwargs.get("env") or os.environ)
    child_env.update(
        {
            "TMPDIR": packet_temp_root,
            "TMP": packet_temp_root,
            "TEMP": packet_temp_root,
        }
    )
    kwargs["env"] = child_env
    _PACKET_POLICY.launching_sandbox = True
    try:
        if popenargs:
            return _ORIGINAL_POPEN(
                wrapped,
                *remaining,
                shell=False,
                **kwargs,
            )
        return _ORIGINAL_POPEN(wrapped, shell=False, **kwargs)
    finally:
        _PACKET_POLICY.launching_sandbox = False


def _policy_thread_start(thread, *args, **kwargs):
    policy = getattr(_PACKET_POLICY, "current", None)
    if (
        policy is not None
        and not getattr(thread, "_stage_execution_policy_wrapped", False)
    ):
        original_run = thread.run
        child_policy = {
            "allowed_roots": policy["sandbox_write_roots"],
            "sandbox_write_roots": policy["sandbox_write_roots"],
            "violations": policy["violations"],
            "threads": policy["threads"],
        }

        def run_with_packet_policy():
            prior_policy = getattr(_PACKET_POLICY, "current", None)
            _PACKET_POLICY.current = child_policy
            try:
                return original_run()
            finally:
                _PACKET_POLICY.current = prior_policy

        thread.run = run_with_packet_policy
        thread._stage_execution_policy_wrapped = True
        policy["threads"].append(thread)
    return _ORIGINAL_THREAD_START(thread, *args, **kwargs)


def _policy_low_level_start(namespace, entrypoint, original, *args, **kwargs):
    policy = getattr(_PACKET_POLICY, "current", None)
    if policy is not None:
        _deny_packet_mutation(
            policy,
            f"{namespace}.{entrypoint}",
            None,
        )
    return original(*args, **kwargs)


def _policy_start_new_thread(*args, **kwargs):
    return _policy_low_level_start(
        "_thread",
        "start_new_thread",
        _ORIGINAL_START_NEW_THREAD,
        *args,
        **kwargs,
    )


def _policy_start_new(*args, **kwargs):
    return _policy_low_level_start(
        "_thread",
        "start_new",
        _ORIGINAL_START_NEW,
        *args,
        **kwargs,
    )


def _policy_fork(*args, **kwargs):
    return _policy_low_level_start(
        "os",
        "fork",
        _ORIGINAL_FORK,
        *args,
        **kwargs,
    )


def _policy_forkpty(*args, **kwargs):
    return _policy_low_level_start(
        "os",
        "forkpty",
        _ORIGINAL_FORKPTY,
        *args,
        **kwargs,
    )


def _wait_for_packet_threads(policy, timeout_seconds=5.0):
    deadline = time.monotonic() + timeout_seconds
    index = 0
    while index < len(policy["threads"]):
        thread = policy["threads"][index]
        index += 1
        remaining = max(0.0, deadline - time.monotonic())
        thread.join(timeout=remaining)
        if thread.is_alive():
            policy["violations"].append(
                "packet child thread outlived the execution boundary: "
                f"{thread.name}"
            )


sys.addaudithook(_packet_audit_hook)
subprocess.Popen = _sandboxed_popen
threading.Thread.start = _policy_thread_start
_thread.start_new_thread = _policy_start_new_thread
if _ORIGINAL_START_NEW is not None:
    _thread.start_new = _policy_start_new
if _ORIGINAL_FORK is not None:
    os.fork = _policy_fork
if _ORIGINAL_FORKPTY is not None:
    os.forkpty = _policy_forkpty


class PlanError(ValueError):
    pass


def stable_hash(value):
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def resolve_path(root, value):
    path = Path(value)
    return path.resolve() if path.is_absolute() else (Path(root) / path).resolve()


def is_within(path, parent):
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def validate_identifier(value, field):
    if not isinstance(value, str) or not IDENTIFIER_RE.fullmatch(value):
        raise PlanError(
            f"{field} must contain only letters, numbers, underscores, and hyphens"
        )


def coordinator_only_paths(root, plan):
    root = Path(root).resolve()
    paths = []
    for value in (
        list(DEFAULT_COORDINATOR_ONLY_PATHS)
        + list(plan.get("coordinator_only_paths") or [])
    ):
        path = resolve_path(root, value)
        if not is_within(path, root):
            raise PlanError(f"coordinator-only path must stay inside root: {value}")
        paths.append(path)
    return tuple(dict.fromkeys(paths))


def validate_plan(root, plan):
    root = Path(root).resolve()
    if plan.get("plan_sha256"):
        unsigned = dict(plan)
        expected = unsigned.pop("plan_sha256")
        if stable_hash(unsigned) != expected:
            raise PlanError("stage execution plan hash mismatch")
    if plan.get("schema_version") != 1:
        raise PlanError("stage execution plan schema_version must be 1")
    job_id = str(plan.get("job_id") or "").strip()
    stage = str(plan.get("stage") or "").strip()
    if not job_id or not stage:
        raise PlanError("stage execution plan requires job_id and stage")
    validate_identifier(job_id, "job_id")
    validate_identifier(stage, "stage")

    job_root = (root / "output" / job_id).resolve()
    coordinator_only = set(coordinator_only_paths(root, plan))
    packets = plan.get("packets")
    if not isinstance(packets, list) or not packets:
        raise PlanError("stage execution plan requires at least one packet")

    packet_ids = []
    packet_write_roots = {}
    completion_paths = {}
    for packet in packets:
        packet_id = str(packet.get("packet_id") or "").strip()
        if not packet_id:
            raise PlanError("every packet requires packet_id")
        validate_identifier(packet_id, "packet_id")
        if packet_id in packet_ids:
            raise PlanError(f"duplicate packet_id: {packet_id}")
        packet_ids.append(packet_id)

        executor_kind = packet.get("executor_kind") or "command"
        if executor_kind not in {"command", "agent"}:
            raise PlanError(
                f"packet {packet_id} executor_kind must be command or agent"
            )
        if executor_kind == "command":
            command = packet.get("command")
            if (
                not isinstance(command, list)
                or not command
                or any(
                    not isinstance(token, str) or not token
                    for token in command
                )
            ):
                raise PlanError(f"packet {packet_id} requires a command list")
        elif not str(packet.get("task") or "").strip():
            raise PlanError(f"agent packet {packet_id} requires task instructions")
        write_roots = packet.get("allowed_write_roots")
        if not isinstance(write_roots, list) or not write_roots:
            raise PlanError(f"packet {packet_id} requires allowed_write_roots")
        resolved_write_roots = []
        for value in write_roots:
            write_root = resolve_path(root, value)
            resolved_write_roots.append(write_root)
            if not is_within(write_root, job_root):
                raise PlanError(
                    f"packet {packet_id} write root must stay under output/{job_id}: "
                    f"{value}"
                )
            for protected in coordinator_only:
                if write_root == protected or is_within(protected, write_root):
                    raise PlanError(
                        f"packet {packet_id} write root contains coordinator-only path: "
                        f"{value}"
                    )

        completion_path = resolve_path(root, packet.get("completion_path") or "")
        if not is_within(completion_path, job_root):
            raise PlanError(
                f"packet {packet_id} completion_path must stay under output/{job_id}"
            )
        for protected in coordinator_only:
            if (
                completion_path == protected
                or is_within(completion_path, protected)
                or is_within(protected, completion_path)
            ):
                raise PlanError(
                    f"packet {packet_id} completion_path overlaps "
                    "a coordinator-only path"
                )
        packet_write_roots[packet_id] = resolved_write_roots
        completion_paths[packet_id] = completion_path

    if len(set(completion_paths.values())) != len(completion_paths):
        raise PlanError("stage execution completion paths must be unique")
    for left_index, left_id in enumerate(packet_ids):
        for right_id in packet_ids[left_index + 1:]:
            for left_root in packet_write_roots[left_id]:
                for right_root in packet_write_roots[right_id]:
                    if (
                        is_within(left_root, right_root)
                        or is_within(right_root, left_root)
                    ):
                        raise PlanError(
                            "stage execution packet write roots overlap: "
                            f"{left_id}, {right_id}"
                        )
            if any(
                is_within(completion_paths[left_id], write_root)
                for write_root in packet_write_roots[right_id]
            ) or any(
                is_within(completion_paths[right_id], write_root)
                for write_root in packet_write_roots[left_id]
            ):
                raise PlanError(
                    "stage execution completion path overlaps another packet"
                )

    known = set(packet_ids)
    for packet in packets:
        packet_id = packet["packet_id"]
        dependencies = packet.get("depends_on") or []
        if not isinstance(dependencies, list):
            raise PlanError(f"packet {packet_id} depends_on must be a list")
        missing = [value for value in dependencies if value not in known]
        if missing:
            raise PlanError(
                f"packet {packet_id} has unknown dependencies: {', '.join(missing)}"
            )
        if packet_id in dependencies:
            raise PlanError(f"packet {packet_id} cannot depend on itself")

    _assert_acyclic(packets)
    return plan


def seal_plan(root, plan):
    sealed = json.loads(json.dumps(plan, ensure_ascii=False))
    sealed.pop("plan_sha256", None)
    validate_plan(root, sealed)
    sealed["plan_sha256"] = stable_hash(sealed)
    return sealed


def _assert_acyclic(packets):
    dependencies = {
        packet["packet_id"]: set(packet.get("depends_on") or [])
        for packet in packets
    }
    resolved = set()
    while len(resolved) < len(dependencies):
        ready = {
            packet_id
            for packet_id, needs in dependencies.items()
            if packet_id not in resolved and needs <= resolved
        }
        if not ready:
            raise PlanError("stage execution packet dependencies contain a cycle")
        resolved.update(ready)


def ready_packet_ids(plan, completed):
    completed = set(completed or [])
    return [
        packet["packet_id"]
        for packet in plan["packets"]
        if packet["packet_id"] not in completed
        and set(packet.get("depends_on") or []) <= completed
    ]


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def display_path(root, path):
    root = Path(root).resolve()
    path = Path(path).resolve()
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def runtime_path(root, packet, value):
    """Map one canonical packet path into that packet's isolated staging root."""
    path = resolve_path(root, value)
    for binding in packet.get("_stage_path_map") or []:
        canonical = Path(binding["canonical"]).resolve()
        staged = Path(binding["staged"]).resolve()
        if path == staged or is_within(path, staged):
            return path
        if path == canonical:
            return staged
        if is_within(path, canonical):
            return staged / path.relative_to(canonical)
    return path


def canonical_path(root, packet, value):
    """Map one staged packet path back to its sealed canonical destination."""
    path = resolve_path(root, value)
    for binding in packet.get("_stage_path_map") or []:
        canonical = Path(binding["canonical"]).resolve()
        staged = Path(binding["staged"]).resolve()
        if path == canonical or is_within(path, canonical):
            return path
        if path == staged:
            return canonical
        if is_within(path, staged):
            return canonical / path.relative_to(staged)
    return path


def packet_by_id(plan, packet_id):
    for packet in plan["packets"]:
        if packet["packet_id"] == packet_id:
            return packet
    raise PlanError(f"unknown packet_id: {packet_id}")


def record_completion(root, plan, packet_id, status, outputs):
    root = Path(root).resolve()
    validate_plan(root, plan)
    if status not in {"PASS", "FAIL", "STOP"}:
        raise PlanError(f"invalid completion status: {status}")
    packet = packet_by_id(plan, packet_id)
    write_roots = [
        resolve_path(root, value)
        for value in packet["allowed_write_roots"]
    ]
    bound_outputs = []
    for value in outputs or []:
        output = resolve_path(root, value)
        if not output.is_file():
            raise PlanError(f"completion output is missing: {value}")
        if not any(is_within(output, write_root) for write_root in write_roots):
            raise PlanError(
                f"completion output is outside packet write roots: {value}"
            )
        bound_outputs.append(
            {
                "path": display_path(root, output),
                "sha256": sha256_file(output),
            }
        )
    completion = {
        "schema_version": 1,
        "job_id": plan["job_id"],
        "stage": plan["stage"],
        "packet_id": packet_id,
        "status": status,
        "outputs": bound_outputs,
    }
    completion_path = resolve_path(root, packet["completion_path"])
    completion_path.parent.mkdir(parents=True, exist_ok=True)
    completion_path.write_text(
        json.dumps(completion, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return completion


def _default_dispatcher(root, runner):
    def dispatch(packet):
        if (packet.get("executor_kind") or "command") != "command":
            raise PlanError(
                f"agent packet {packet['packet_id']} requires an injected dispatcher"
            )
        completed = runner(
            packet["command"],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
        return {
            "status": "PASS" if completed.returncode == 0 else "FAIL",
            "outputs": list(packet.get("expected_outputs") or []),
            "returncode": completed.returncode,
            "stdout": completed.stdout or "",
            "stderr": completed.stderr or "",
        }

    return dispatch


def _dispatch_packet(root, packet, dispatcher):
    try:
        packet_write_roots = (
            Path(packet["_packet_staging_root"]).resolve(),
            Path("/dev"),
        )
        policy = {
            "allowed_roots": packet_write_roots,
            "sandbox_write_roots": packet_write_roots,
            "violations": [],
            "threads": [],
        }
        prior_policy = getattr(_PACKET_POLICY, "current", None)
        _PACKET_POLICY.current = policy
        try:
            result = dispatcher(packet)
        finally:
            _PACKET_POLICY.current = prior_policy
            _wait_for_packet_threads(policy)
        if policy["violations"]:
            raise PlanError("; ".join(policy["violations"]))
        if not isinstance(result, dict):
            raise PlanError("dispatcher result must be an object")
        status = str(result.get("status") or "").upper()
        if status not in {"PASS", "FAIL", "STOP"}:
            raise PlanError(f"invalid completion status: {status}")
        outputs = []
        write_roots = [
            resolve_path(root, value)
            for value in packet["allowed_write_roots"]
        ]
        for value in result.get("outputs") or []:
            raw_output = Path(value)
            if not raw_output.is_absolute():
                raw_output = Path(root) / raw_output
            if raw_output.is_symlink():
                raise PlanError(
                    f"completion output cannot be a symlink: {value}"
                )
            output = raw_output.resolve()
            if not output.is_file():
                raise PlanError(f"completion output is missing: {value}")
            if not any(
                is_within(output, write_root)
                for write_root in write_roots
            ):
                raise PlanError(
                    "completion output is outside packet staging roots: "
                    f"{value}"
                )
            outputs.append(str(output))
        deleted_outputs = []
        for value in result.get("deleted_outputs") or []:
            deleted = Path(value)
            if not deleted.is_absolute():
                deleted = Path(root) / deleted
            if deleted.exists() or deleted.is_symlink():
                raise PlanError(
                    f"declared deleted output still exists: {value}"
                )
            deleted = deleted.absolute()
            if not any(
                deleted == write_root or is_within(deleted, write_root)
                for write_root in write_roots
            ):
                raise PlanError(
                    "deleted output is outside packet staging roots: "
                    f"{value}"
                )
            deleted_outputs.append(str(deleted))
        completion = {
            "schema_version": 1,
            "job_id": packet["_job_id"],
            "stage": packet["_stage"],
            "packet_id": packet["packet_id"],
            "status": status,
            "outputs": outputs,
            "_deleted_outputs": deleted_outputs,
        }
        for key in ("returncode", "stdout", "stderr", "error"):
            if key in result:
                completion[key] = result[key]
    except Exception as exc:
        completion = {
            "schema_version": 1,
            "job_id": packet["_job_id"],
            "stage": packet["_stage"],
            "packet_id": packet["packet_id"],
            "status": "FAIL",
            "outputs": [],
            "_deleted_outputs": [],
        }
        completion["error"] = str(exc)
    return completion


def _snapshot_coordinator_only(paths):
    snapshot = {}
    for path in paths:
        if path.is_dir():
            raise PlanError(
                f"coordinator-only path must be a file, not a directory: {path}"
            )
        if path.is_file():
            snapshot[path] = {
                "exists": True,
                "content": path.read_bytes(),
                "mode": stat.S_IMODE(path.stat().st_mode),
            }
        else:
            snapshot[path] = {"exists": False}
    return snapshot


def _changed_coordinator_only(snapshot):
    changed = []
    for path, before in snapshot.items():
        if before["exists"]:
            if (
                not path.is_file()
                or path.read_bytes() != before["content"]
                or stat.S_IMODE(path.stat().st_mode) != before["mode"]
            ):
                changed.append(path)
        elif path.exists():
            changed.append(path)
    return changed


def _restore_coordinator_only(snapshot):
    for path, before in snapshot.items():
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists() and not before["exists"]:
            path.unlink()
        if before["exists"]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(before["content"])
            path.chmod(before["mode"])


def _rewrite_completion(root, plan, completion):
    packet = packet_by_id(plan, completion["packet_id"])
    completion_path = resolve_path(root, packet["completion_path"])
    completion_path.write_text(
        json.dumps(completion, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _is_runtime_cache(path):
    return (
        any(part in IGNORED_RUNTIME_NAMES for part in path.parts)
        or path.suffix.lower() in IGNORED_RUNTIME_SUFFIXES
    )


def _path_is_allowed(path, allowed_paths):
    return any(is_within(path, allowed) for allowed in allowed_paths)


def _path_is_allowed_or_parent(path, allowed_paths):
    return any(
        is_within(path, allowed) or is_within(allowed, path)
        for allowed in allowed_paths
    )


def _entry_signature(path):
    metadata = path.lstat()
    return (
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
        metadata.st_ino,
    )


def _clone_or_copy_file(source, destination):
    """Create an independent CoW clone when supported, else a safe copy."""
    global _CLONEFILE, _CLONEFILE_CHECKED
    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        if not _CLONEFILE_CHECKED:
            libc = ctypes.CDLL(None, use_errno=True)
            _CLONEFILE = libc.clonefile
            _CLONEFILE.argtypes = [
                ctypes.c_char_p,
                ctypes.c_char_p,
                ctypes.c_int,
            ]
            _CLONEFILE.restype = ctypes.c_int
            _CLONEFILE_CHECKED = True
        if _CLONEFILE is None:
            raise AttributeError("clonefile is unavailable")
        if _CLONEFILE(
            os.fsencode(source),
            os.fsencode(destination),
            0,
        ) != 0:
            error_number = ctypes.get_errno()
            raise OSError(error_number, os.strerror(error_number))
        shutil.copystat(source, destination, follow_symlinks=False)
    except AttributeError:
        _CLONEFILE = None
        _CLONEFILE_CHECKED = True
        shutil.copy2(source, destination, follow_symlinks=False)
    except OSError:
        if destination.exists() or destination.is_symlink():
            _remove_path(destination)
        shutil.copy2(source, destination, follow_symlinks=False)
    return str(destination)


def _copy_path_for_staging(source, destination):
    source = Path(source)
    destination = Path(destination)
    if source.is_symlink():
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.symlink_to(os.readlink(source))
    elif source.is_dir():
        shutil.copytree(
            source,
            destination,
            symlinks=True,
            copy_function=_clone_or_copy_file,
        )
    elif source.is_file():
        _clone_or_copy_file(source, destination)
    elif source.exists():
        raise PlanError(f"unsupported packet write-root type: {source}")


def _stable_file_promotion_state(path):
    before = _entry_signature(path)
    digest = sha256_file(path)
    after = _entry_signature(path)
    if before != after:
        raise PlanError(
            f"staged file changed while sealing promotion state: {path}"
        )
    metadata = path.stat()
    return {
        "mode": stat.S_IMODE(metadata.st_mode),
        "size": metadata.st_size,
        "mtime_ns": metadata.st_mtime_ns,
        "sha256": digest,
    }


def _capture_promotion_state(path):
    path = Path(path)
    if path.is_symlink():
        raise PlanError(f"promotion source cannot be a symlink: {path}")
    if not path.exists():
        return {"kind": "missing"}
    if path.is_file():
        return {
            "kind": "file",
            "file": _stable_file_promotion_state(path),
        }
    if not path.is_dir():
        raise PlanError(f"unsupported promotion source type: {path}")

    before = _capture_staging_tree(path)
    directories = []
    files = []
    for current_raw, dirnames, filenames in os.walk(
        path,
        topdown=True,
        followlinks=False,
    ):
        current = Path(current_raw)
        relative_directory = current.relative_to(path).as_posix()
        metadata = current.stat()
        directories.append(
            {
                "path": relative_directory,
                "mode": stat.S_IMODE(metadata.st_mode),
                "mtime_ns": metadata.st_mtime_ns,
            }
        )
        for name in list(dirnames):
            candidate = current / name
            if candidate.is_symlink():
                raise PlanError(
                    f"promotion source cannot contain a symlink: {candidate}"
                )
        for name in filenames:
            candidate = current / name
            if candidate.is_symlink():
                raise PlanError(
                    f"promotion source cannot contain a symlink: {candidate}"
                )
            if not candidate.is_file():
                raise PlanError(
                    f"unsupported promotion source entry: {candidate}"
                )
            files.append(
                {
                    "path": candidate.relative_to(path).as_posix(),
                    **_stable_file_promotion_state(candidate),
                }
            )
    after = _capture_staging_tree(path)
    if before != after:
        raise PlanError(
            f"staged directory changed while sealing promotion state: {path}"
        )
    return {
        "kind": "directory",
        "directories": sorted(
            directories,
            key=lambda item: item["path"],
        ),
        "files": sorted(files, key=lambda item: item["path"]),
    }


def _copy_path_for_promotion(source, destination):
    source = Path(source)
    destination = Path(destination)
    if source.is_symlink():
        raise PlanError(f"promotion source cannot be a symlink: {source}")
    if source.is_dir():
        shutil.copytree(
            source,
            destination,
            symlinks=False,
            copy_function=_clone_or_copy_file,
        )
    elif source.is_file():
        _clone_or_copy_file(source, destination)
    elif source.exists():
        raise PlanError(f"unsupported promotion source type: {source}")


def _assert_independent_promotion_copy(source, copied):
    source = Path(source)
    copied = Path(copied)
    if source.samefile(copied):
        raise PlanError(
            f"promotion copy reused the staged inode: {source}"
        )
    if not source.is_dir():
        return
    for source_entry in source.rglob("*"):
        copied_entry = copied / source_entry.relative_to(source)
        if source_entry.samefile(copied_entry):
            raise PlanError(
                "promotion copy reused a staged tree inode: "
                f"{source_entry}"
            )


def _rewrite_runtime_token(root, packet, token):
    mapped = runtime_path(root, packet, token)
    canonical = resolve_path(root, token)
    return str(mapped) if mapped != canonical else token


def _unresolved_path(root, value):
    path = Path(value)
    if not path.is_absolute():
        path = Path(root) / path
    return Path(os.path.abspath(str(path)))


def _assert_write_root_has_no_symlink(root, value):
    workspace = _unresolved_path(root, ".")
    write_root = _unresolved_path(root, value)
    try:
        relative = write_root.relative_to(workspace)
    except ValueError:
        relative = None
    if relative is not None:
        current = workspace
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise PlanError(
                    f"packet write root contains a symlink: {current}"
                )
    elif write_root.is_symlink():
        raise PlanError(
            f"packet write root contains a symlink: {write_root}"
        )
    if not write_root.is_dir():
        return
    for current_raw, dirnames, filenames in os.walk(
        write_root,
        topdown=True,
        followlinks=False,
    ):
        current = Path(current_raw)
        for name in [*dirnames, *filenames]:
            path = current / name
            if path.is_symlink():
                raise PlanError(
                    f"packet write root contains a symlink: {path}"
                )


def _prepare_runtime_packets(root, plan, packet_ids):
    staging_roots = {}
    runtime_packets = {}
    try:
        for packet_id in packet_ids:
            sealed_packet = packet_by_id(plan, packet_id)
            packet_staging_root = Path(
                tempfile.mkdtemp(
                    prefix=f".stage-execution-{packet_id}-",
                    dir=Path(root).resolve().parent,
                )
            )
            staging_roots[packet_id] = packet_staging_root
            runtime_packet = json.loads(
                json.dumps(sealed_packet, ensure_ascii=False)
            )
            bindings = []
            for index, value in enumerate(
                sealed_packet["allowed_write_roots"]
            ):
                _assert_write_root_has_no_symlink(root, value)
                canonical = resolve_path(root, value)
                staged = (
                    packet_staging_root
                    / f"root-{index:03d}"
                    / canonical.name
                )
                if canonical.exists() or canonical.is_symlink():
                    _copy_path_for_staging(canonical, staged)
                bindings.append(
                    {
                        "canonical": str(canonical),
                        "staged": str(staged),
                    }
                )
            runtime_packet["_stage_path_map"] = bindings
            runtime_packet["_packet_staging_root"] = str(
                packet_staging_root
            )
            runtime_packet["_job_id"] = plan["job_id"]
            runtime_packet["_stage"] = plan["stage"]
            runtime_packet["allowed_write_roots"] = [
                binding["staged"]
                for binding in bindings
            ]
            if runtime_packet.get("command"):
                runtime_packet["command"] = [
                    _rewrite_runtime_token(root, runtime_packet, token)
                    for token in runtime_packet["command"]
                ]
            if runtime_packet.get("expected_outputs"):
                runtime_packet["expected_outputs"] = [
                    str(runtime_path(root, runtime_packet, value))
                    for value in runtime_packet["expected_outputs"]
                ]
            runtime_packets[packet_id] = runtime_packet
    except Exception:
        for staging_root in staging_roots.values():
            shutil.rmtree(staging_root, ignore_errors=True)
        raise
    return staging_roots, runtime_packets


def _capture_staging_tree(staging_root):
    staging_root = Path(staging_root)
    entries = {}
    directories = {}
    for current_raw, dirnames, filenames in os.walk(
        staging_root,
        topdown=True,
        followlinks=False,
    ):
        current = Path(current_raw)
        directories[current] = _entry_signature(current)
        for name in list(dirnames):
            path = current / name
            if not path.is_symlink():
                continue
            dirnames.remove(name)
            entries[path] = {
                "kind": "symlink",
                "signature": _entry_signature(path),
                "link_target": os.readlink(path),
            }
        for name in filenames:
            path = current / name
            if path.is_symlink():
                entries[path] = {
                    "kind": "symlink",
                    "signature": _entry_signature(path),
                    "link_target": os.readlink(path),
                }
            else:
                entries[path] = {
                    "kind": (
                        "file"
                        if path.is_file()
                        else "other"
                    ),
                    "signature": _entry_signature(path),
                }
    return {"entries": entries, "directories": directories}


def _audit_staging_outputs(staging_root, before, provisional):
    after = _capture_staging_tree(staging_root)
    declared = {
        Path(value).absolute()
        for value in [
            *(provisional.get("outputs") or []),
            *(provisional.get("_deleted_outputs") or []),
        ]
    }
    violations = []
    all_entries = set(before["entries"]) | set(after["entries"])
    for path in sorted(all_entries, key=lambda value: value.as_posix()):
        old = before["entries"].get(path)
        new = after["entries"].get(path)
        if old is not None and new is not None and not _entry_changed(
            path,
            old,
            new,
        ):
            continue
        if path.absolute() not in declared:
            reason = (
                "packet staging symlink is not a valid provisional output"
                if (new or old).get("kind") == "symlink"
                else (
                    "packet staging path changed without "
                    "a provisional output"
                )
            )
            violations.append(
                (
                    path,
                    reason,
                    True,
                )
            )
    all_directories = (
        set(before["directories"]) | set(after["directories"])
    )
    for path in sorted(
        all_directories,
        key=lambda value: value.as_posix(),
    ):
        if before["directories"].get(path) == after["directories"].get(path):
            continue
        if any(
            effect == path or is_within(effect, path)
            for effect in declared
        ):
            continue
        if not any(item[0] == path for item in violations):
            violations.append(
                (
                    path,
                    "packet staging directory changed without a provisional output",
                    True,
                )
            )
    return violations


def _capture_output_tree(root, allowed_paths, backup=True):
    output_root = Path(root).resolve()
    entries = {}
    directories = {}
    backup_bytes = 0
    backup_root = None
    if not output_root.exists():
        return {
            "output_root": output_root,
            "entries": entries,
            "directories": directories,
            "backup_root": backup_root,
        }
    if not output_root.is_dir():
        raise PlanError("stage execution root must be a directory")
    if backup:
        backup_root = Path(
            tempfile.mkdtemp(
                prefix=".stage-execution-audit-",
                dir=output_root.parent,
            )
        )

    try:
        for current_raw, dirnames, filenames in os.walk(
            output_root,
            topdown=True,
            followlinks=False,
        ):
            current = Path(current_raw)
            dirnames[:] = sorted(
                name
                for name in dirnames
                if name not in IGNORED_RUNTIME_NAMES
            )
            if not _is_runtime_cache(current):
                directories[current] = _entry_signature(current)
            for name in list(dirnames):
                path = current / name
                if not path.is_symlink():
                    continue
                dirnames.remove(name)
                if _is_runtime_cache(path):
                    continue
                entries[path] = {
                    "kind": "symlink",
                    "signature": _entry_signature(path),
                    "link_target": os.readlink(path),
                }
            for name in sorted(filenames):
                path = current / name
                if _is_runtime_cache(path):
                    continue
                metadata = path.lstat()
                if stat.S_ISLNK(metadata.st_mode):
                    entries[path] = {
                        "kind": "symlink",
                        "signature": _entry_signature(path),
                        "link_target": os.readlink(path),
                    }
                    continue
                entry = {
                    "kind": (
                        "file"
                        if stat.S_ISREG(metadata.st_mode)
                        else "other"
                    ),
                    "signature": _entry_signature(path),
                }
                if (
                    backup
                    and entry["kind"] == "file"
                    and not _path_is_allowed(path, allowed_paths)
                ):
                    entry["atime_ns"] = metadata.st_atime_ns
                    if (
                        metadata.st_size <= MAX_RESTORABLE_BYTES
                        and (
                            backup_bytes + metadata.st_size
                            <= MAX_TOTAL_RESTORABLE_BYTES
                        )
                        and path.suffix.lower() in RESTORABLE_SUFFIXES
                    ):
                        entry["backup"] = path.read_bytes()
                        backup_bytes += metadata.st_size
                    else:
                        backup_path = (
                            backup_root
                            / "files"
                            / path.relative_to(output_root)
                        )
                        _clone_or_copy_file(path, backup_path)
                        entry["disk_backup"] = str(backup_path)
                entries[path] = entry
    except Exception:
        if backup_root is not None:
            shutil.rmtree(backup_root, ignore_errors=True)
        raise
    return {
        "output_root": output_root,
        "entries": entries,
        "directories": directories,
        "backup_root": backup_root,
    }


def _entry_changed(path, before, after):
    if before["kind"] != after["kind"]:
        return True
    if before["signature"] != after["signature"]:
        return True
    if before["kind"] == "symlink":
        return before["link_target"] != after.get("link_target")
    return False


def _remove_path(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def _restore_output_entry(path, before):
    if before["kind"] == "file" and (
        before.get("backup") is not None
        or before.get("disk_backup") is not None
    ):
        if path.exists() or path.is_symlink():
            _remove_path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if before.get("backup") is not None:
            path.write_bytes(before["backup"])
        else:
            os.replace(before["disk_backup"], path)
        mode, _, mtime_ns, _, _ = before["signature"]
        path.chmod(stat.S_IMODE(mode))
        os.utime(
            path,
            ns=(before["atime_ns"], mtime_ns),
            follow_symlinks=False,
        )
        return True
    if before["kind"] == "symlink":
        if path.exists() or path.is_symlink():
            _remove_path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(before["link_target"])
        return True
    return False


def _audit_output_write_set(root, before, allowed_paths):
    after = _capture_output_tree(root, allowed_paths, backup=False)
    before_entries = before["entries"]
    after_entries = after["entries"]
    violations = []
    new_entry_paths = set(after_entries) - set(before_entries)

    for path in sorted(
        new_entry_paths,
        key=lambda value: value.as_posix(),
    ):
        if _path_is_allowed(path, allowed_paths):
            continue
        violations.append((path, "new out-of-bounds path", True))
        _remove_path(path)

    for path in sorted(
        set(before_entries),
        key=lambda value: value.as_posix(),
    ):
        if _path_is_allowed(path, allowed_paths):
            continue
        current = after_entries.get(path)
        if current is not None and not _entry_changed(
            path,
            before_entries[path],
            current,
        ):
            continue
        restored = _restore_output_entry(path, before_entries[path])
        reason = (
            "out-of-bounds path changed and was restored"
            if restored
            else "out-of-bounds path changed; restore unavailable"
        )
        violations.append((path, reason, restored))

    new_directories = sorted(
        set(after["directories"]) - set(before["directories"]),
        key=lambda value: len(value.parts),
        reverse=True,
    )
    for path in new_directories:
        if _path_is_allowed_or_parent(path, allowed_paths):
            continue
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
                violations.append(
                    (
                        path,
                        "new out-of-bounds directory is not empty; "
                        "restore unavailable",
                        False,
                    )
                )
                continue
        contained_new_entry = any(
            is_within(entry, path)
            for entry in new_entry_paths
        )
        if (
            not contained_new_entry
            and not any(item[0] == path for item in violations)
        ):
            violations.append(
                (path, "new out-of-bounds directory was removed", True)
            )

    for path in sorted(
        before["directories"],
        key=lambda value: len(value.parts),
        reverse=True,
    ):
        if _path_is_allowed_or_parent(path, allowed_paths):
            continue
        current_signature = after["directories"].get(path)
        if current_signature == before["directories"][path]:
            continue
        if path.exists() and not path.is_dir():
            violations.append(
                (
                    path,
                    "out-of-bounds directory changed; restore unavailable",
                    False,
                )
            )
            continue
        path.mkdir(parents=True, exist_ok=True)
        mode, _, mtime_ns, _, _ = before["directories"][path]
        path.chmod(stat.S_IMODE(mode))
        os.utime(path, ns=(path.stat().st_atime_ns, mtime_ns))
        has_reported_child = any(
            child != path and is_within(child, path)
            for child, _, _ in violations
        )
        if not has_reported_child:
            violations.append(
                (
                    path,
                    "out-of-bounds directory metadata changed and was restored",
                    True,
                )
            )
    return violations


def _cleanup_snapshot(snapshot):
    backup_root = snapshot.get("backup_root")
    if backup_root:
        shutil.rmtree(backup_root, ignore_errors=True)


def _promote_runtime_packets(
    runtime_packets,
    provisional,
    promotion_states,
):
    promoted = []
    temporary_roots = []
    try:
        for packet_id, packet in runtime_packets.items():
            if provisional[packet_id]["status"] != "PASS":
                continue
            for index, binding in enumerate(packet["_stage_path_map"]):
                canonical = Path(binding["canonical"])
                staged = Path(binding["staged"])
                expected_state = promotion_states[packet_id][index]
                backup = (
                    staged.parents[1]
                    / ".promotion-backup"
                    / f"root-{index:03d}"
                    / canonical.name
                )
                had_original = canonical.exists() or canonical.is_symlink()
                canonical.parent.mkdir(parents=True, exist_ok=True)
                record = {
                    "canonical": canonical,
                    "staged": staged,
                    "backup": backup,
                    "had_original": had_original,
                    "backup_moved": False,
                    "installed": False,
                }
                promoted.append(record)

                current_state = _capture_promotion_state(staged)
                if current_state != expected_state:
                    raise PlanError(
                        "staged content changed after promotion audit: "
                        f"{staged}"
                    )

                temporary_root = None
                payload = None
                if expected_state["kind"] != "missing":
                    temporary_root = Path(
                        tempfile.mkdtemp(
                            prefix=(
                                f".{canonical.name}."
                                "stage-promotion-"
                            ),
                            dir=canonical.parent,
                        )
                    )
                    temporary_roots.append(temporary_root)
                    payload = temporary_root / "payload"
                    _copy_path_for_promotion(staged, payload)
                    if _capture_promotion_state(staged) != expected_state:
                        raise PlanError(
                            "staged content changed during promotion copy: "
                            f"{staged}"
                        )
                    if _capture_promotion_state(payload) != expected_state:
                        raise PlanError(
                            "promotion copy does not match audited state: "
                            f"{staged}"
                        )
                    _assert_independent_promotion_copy(staged, payload)

                if had_original:
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(canonical, backup)
                    record["backup_moved"] = True
                if payload is not None:
                    os.replace(payload, canonical)
                    record["installed"] = True
                    if (
                        _capture_promotion_state(canonical)
                        != expected_state
                    ):
                        raise PlanError(
                            "installed promotion does not match audited state: "
                            f"{canonical}"
                        )
                if staged.exists() or staged.is_symlink():
                    _remove_path(staged)
    except Exception:
        for record in reversed(promoted):
            canonical = record["canonical"]
            if record["installed"] and (
                canonical.exists() or canonical.is_symlink()
            ):
                _remove_path(canonical)
            if record["backup_moved"] and (
                record["backup"].exists()
                or record["backup"].is_symlink()
            ):
                canonical.parent.mkdir(parents=True, exist_ok=True)
                os.replace(record["backup"], canonical)
        raise
    finally:
        for temporary_root in temporary_roots:
            shutil.rmtree(temporary_root, ignore_errors=True)


def _finalize_runtime_completion(root, plan, runtime_packet, provisional):
    outputs = [
        canonical_path(root, runtime_packet, value)
        for value in (
            provisional.get("outputs") or []
            if provisional["status"] == "PASS"
            else []
        )
    ]
    completion = record_completion(
        root,
        plan,
        provisional["packet_id"],
        provisional["status"],
        outputs,
    )
    for key in ("returncode", "stdout", "stderr", "error"):
        if key in provisional:
            completion[key] = provisional[key]
    _rewrite_completion(root, plan, completion)
    return completion


def _write_set_error(root, violations):
    details = "; ".join(
        f"{display_path(root, path)} ({reason})"
        for path, reason, _ in violations
    )
    return f"parallel wave violated declared write set: {details}"


def execute_plan(
    root,
    plan,
    dispatcher=None,
    coordinator_commit=None,
    max_workers=8,
    runner=subprocess.run,
):
    """Dispatch dependency-ready packets and fan them into one coordinator commit."""
    root = Path(root).resolve()
    if not isinstance(plan, dict) or not plan.get("plan_sha256"):
        raise PlanError("execute_plan requires a sealed plan with plan_sha256")
    validate_plan(root, plan)
    if not isinstance(max_workers, int) or max_workers < 1:
        raise PlanError("max_workers must be a positive integer")
    selected_dispatcher = dispatcher or _default_dispatcher(root, runner)
    protected_paths = coordinator_only_paths(root, plan)
    packets = {packet["packet_id"]: packet for packet in plan["packets"]}
    pending = set(packets)
    completions = {}

    while pending:
        ready = [
            packet_id
            for packet_id in packets
            if packet_id in pending
            and set(packets[packet_id].get("depends_on") or []) <= set(completions)
        ]
        if not ready:
            raise PlanError("stage execution made no dependency progress")
        runnable = []
        for packet_id in ready:
            packet = packets[packet_id]
            dependencies = packet.get("depends_on") or []
            if any(
                completions[dependency]["status"] != "PASS"
                for dependency in dependencies
            ):
                completion = record_completion(
                    root,
                    plan,
                    packet_id,
                    "STOP",
                    [],
                )
                completion["error"] = "blocked by failed dependency"
                completion_path = resolve_path(
                    root,
                    packet["completion_path"],
                )
                completion_path.write_text(
                    json.dumps(completion, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                completions[packet_id] = completion
                pending.remove(packet_id)
            else:
                runnable.append(packet_id)
        if not runnable:
            continue
        staging_roots, runtime_packets = _prepare_runtime_packets(
            root,
            plan,
            runnable,
        )
        staging_snapshots = {
            packet_id: _capture_staging_tree(
                staging_roots[packet_id]
            )
            for packet_id in runnable
        }
        protected_snapshot = _snapshot_coordinator_only(protected_paths)
        output_audit_allowed = tuple(protected_paths)
        output_snapshot = _capture_output_tree(
            root,
            output_audit_allowed,
            backup=True,
        )
        provisional = {}
        try:
            with ThreadPoolExecutor(
                max_workers=min(max_workers, len(runnable))
            ) as executor:
                futures = {
                    executor.submit(
                        _dispatch_packet,
                        root,
                        runtime_packets[packet_id],
                        selected_dispatcher,
                    ): packet_id
                    for packet_id in runnable
                }
                for future in as_completed(futures):
                    packet_id = futures[future]
                    provisional[packet_id] = future.result()
                    pending.remove(packet_id)
            changed_protected = _changed_coordinator_only(
                protected_snapshot
            )
            violations = []
            if changed_protected:
                _restore_coordinator_only(protected_snapshot)
                violations.extend(
                    (
                        path,
                        "coordinator-only path changed and was restored",
                        True,
                    )
                    for path in changed_protected
                )
            violations.extend(
                _audit_output_write_set(
                    root,
                    output_snapshot,
                    output_audit_allowed,
                )
            )
            promotion_states = {}
            for packet_id in runnable:
                packet_violations = _audit_staging_outputs(
                    staging_roots[packet_id],
                    staging_snapshots[packet_id],
                    provisional[packet_id],
                )
                violations.extend(packet_violations)
                if (
                    not packet_violations
                    and provisional[packet_id]["status"] == "PASS"
                ):
                    try:
                        promotion_states[packet_id] = [
                            _capture_promotion_state(
                                Path(binding["staged"])
                            )
                            for binding in runtime_packets[packet_id][
                                "_stage_path_map"
                            ]
                        ]
                    except Exception as exc:
                        violations.append(
                            (
                                staging_roots[packet_id],
                                (
                                    "could not seal audited promotion state: "
                                    f"{exc}"
                                ),
                                False,
                            )
                        )
            if violations:
                error = _write_set_error(root, violations)
                policy_errors = [
                    item["error"]
                    for item in provisional.values()
                    if "packet filesystem policy" in item.get("error", "")
                ]
                if policy_errors:
                    error = (
                        f"{error}; packet isolation blocked: "
                        + "; ".join(policy_errors)
                    )
                for packet_id in runnable:
                    item = provisional[packet_id]
                    item["status"] = "FAIL"
                    item["outputs"] = []
                    item["error"] = error
                    completions[packet_id] = _finalize_runtime_completion(
                        root,
                        plan,
                        runtime_packets[packet_id],
                        item,
                    )
            else:
                try:
                    _promote_runtime_packets(
                        runtime_packets,
                        provisional,
                        promotion_states,
                    )
                except Exception as exc:
                    for packet_id in runnable:
                        item = provisional[packet_id]
                        item["status"] = "FAIL"
                        item["outputs"] = []
                        item["error"] = (
                            "packet staging promotion failed: "
                            f"{exc}"
                        )
                        completions[packet_id] = (
                            _finalize_runtime_completion(
                                root,
                                plan,
                                runtime_packets[packet_id],
                                item,
                            )
                        )
                else:
                    for packet_id in runnable:
                        completions[packet_id] = (
                            _finalize_runtime_completion(
                                root,
                                plan,
                                runtime_packets[packet_id],
                                provisional[packet_id],
                            )
                        )
        finally:
            _cleanup_snapshot(output_snapshot)
            for staging_root in staging_roots.values():
                shutil.rmtree(staging_root, ignore_errors=True)

    ordered = [
        completions[packet["packet_id"]]
        for packet in plan["packets"]
    ]
    statuses = {item["status"] for item in ordered}
    overall = (
        "FAIL"
        if "FAIL" in statuses
        else "STOP"
        if "STOP" in statuses
        else "PASS"
    )
    report = {
        "schema_version": 1,
        "job_id": plan["job_id"],
        "stage": plan["stage"],
        "overall": overall,
        "completions": ordered,
    }
    if coordinator_commit is not None:
        coordinator_commit(report)
    return report
