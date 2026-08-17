#!/usr/bin/env python3
"""Prove no-spend Pre-Seedance parity between two independent run targets."""

from __future__ import annotations

import argparse
import ast
import base64
import copy
import csv
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import types
from pathlib import Path
from typing import Any


SOURCE_ROOT = Path(__file__).resolve().parents[1]
FIXED_JOB_ID = "job-001"
FIXED_TIME = "2099-01-01T00:00:00"
MACOS_F_GETPATH = 50
PINNED_EXECUTABLE_PATH = ":".join(
    dict.fromkeys(
        (
            str(Path(sys.executable).resolve().parent),
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/usr/bin",
            "/bin",
            "/usr/sbin",
            "/sbin",
        )
    )
)
REQUIRED_ROWS = [
    "intake_normalization",
    "effective_profile",
    "source_rhythm",
    "part_coverage",
    "director_plan",
    "source_script_fidelity",
    "line_edits",
    "visual_edits",
    "audio_boundary",
    "reference_roles_and_order",
    "prompt",
    "provider_request",
    "approval",
    "cost",
    "retry_authority",
    "qc_risk_families",
    "gate_conclusions",
    "pre_seedance_handoff",
]
ROW_STAGES = {
    "intake_normalization": "intake",
    "effective_profile": "intake",
    "source_rhythm": "source_blueprint",
    "part_coverage": "source_blueprint",
    "director_plan": "pre_seedance_pack",
    "source_script_fidelity": "pre_seedance_pack",
    "line_edits": "pre_seedance_pack",
    "visual_edits": "pre_seedance_pack",
    "audio_boundary": "pre_seedance_pack",
    "reference_roles_and_order": "pre_seedance_pack",
    "prompt": "pre_seedance_pack",
    "provider_request": "pre_seedance_pack",
    "approval": "pre_seedance_pack",
    "cost": "pre_seedance_pack",
    "retry_authority": "pre_seedance_pack",
    "qc_risk_families": "pre_seedance_pack",
    "gate_conclusions": "pre_seedance_pack",
    "pre_seedance_handoff": "pre_seedance_pack",
}
REQUIRED_BRANCHES = [
    "missing-required-input",
    "generic-profile-routing",
    "clay-mask-profile-routing",
    "toner-profile-routing",
    "storyboard-derived-identity",
    "generation-approval-boundary",
    "failed-part-retry-boundary",
    "request-rejection",
    "local-finishing",
    "subtitle-clean-classification",
    "subtitle-burned-in-classification",
    "final-technical-qc",
]
NORMALIZATION_ALLOWLIST = [
    "plugin_root",
    "workspace_root",
    "job_root",
    "declared_temporary_root",
    "created_at",
    "updated_at",
    "generated_at",
]
STAGE_WORKER_RESOURCES = {
    "source_blueprint": "workers/source_blueprint_worker.md",
    "image_batch_qc": "workers/image_batch_worker.md",
    "pre_seedance_pack": "workers/pre_seedance_pack_worker.md",
}
QC_EXECUTABLE_CONTRACT_PATHS = (
    "tools/audio_duration_qc.py",
    "tools/caption_finishing_qc.py",
    "tools/checker_review_qc.py",
    "tools/cross_part_continuity_qc.py",
    "tools/final_video_qc.py",
    "tools/image_hard_gate_qc.py",
    "tools/pre_seedance_pack_qc.py",
    "tools/qc_risk_ledger.py",
    "tools/seedance_prompt_contract_qc.py",
    "tools/skincare_progression_qc.py",
    "tools/source_rhythm_qc.py",
    "tools/source_rhythm_visual_review_qc.py",
    "tools/storyboard_geometry_qc.py",
    "tools/storyboard_loop_qc.py",
    "tools/subtitle_workflow_qc.py",
    "tools/visual_asset_manifest_qc.py",
)
QC_FULL_SEMANTIC_EQUIVALENCE = {
    "tools/request_body_qc.py": {
        "70e19aa95e7a27994548514e3fa52f159310ce4ae7fea53cb94ef26cfd1f42cd",
        "2003a328d587d36381d5106b3572a9a846a895a6a7049b84c14029ac64fe6bba",
    },
    "tools/codex_imagegen_contract_qc.py": {
        "d402b2683e4582542f35dfe963d27c0d754ab1704da4cf1f968b19d43f64d354",
        "3210e564761ddf42ef434fda116741c1de7ae39eae4f1692a42a50518f906412",
    },
    "tools/storyboard_visual_acceptance.py": {
        "f8bea8bd57af4bce0efca4bb496a3cb1044fbbf8bb34f573338643bc44b035de",
        "a34c8abe939559c9e190c569b787641fc4915c5c8d17a9041e0a6bbe44b13dce",
    },
}
_ACTIVE_SUBPROCESS_NETWORK_GUARD: dict[str, Any] | None = None
_PROCESS_AUDIT_GUARD_INSTALLED = False


class ParityStop(RuntimeError):
    def __init__(
        self,
        code: str,
        detail: str,
        **context: Any,
    ):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.context = context


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise ParityStop("missing_or_invalid_artifact", str(path)) from exc
    if not isinstance(value, dict):
        raise ParityStop("missing_or_invalid_artifact", str(path))
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.rstrip("\n") + "\n", encoding="utf-8")


def write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def path_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def checked_fixture_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path_within(path, root) or not path.is_file():
        raise ParityStop(
            "fixture_branch_failed",
            f"fixture input is missing or escapes the suite: {relative}",
        )
    return path


def install_write_guard(
    workspace: Path,
    boundary_events: dict[str, int],
) -> None:
    workspace = workspace.resolve()
    write_events = {
        "os.remove",
        "os.rename",
        "os.replace",
        "os.rmdir",
        "os.mkdir",
        "os.chmod",
        "os.chown",
        "os.truncate",
        "os.utime",
    }

    def directory_fd_path(dir_fd: int) -> Path | None:
        try:
            value = fcntl.fcntl(
                dir_fd,
                MACOS_F_GETPATH,
                b"\0" * 1024,
            )
        except OSError:
            return None
        raw_path = value.split(b"\0", 1)[0]
        return Path(os.fsdecode(raw_path)) if raw_path else None

    def resolved_write_path(
        raw_path: object,
        dir_fd: object | None,
    ) -> Path | None:
        if not isinstance(raw_path, (str, bytes, os.PathLike)):
            return None
        candidate = Path(os.fsdecode(raw_path))
        if candidate.is_absolute():
            return candidate
        base = Path.cwd()
        if isinstance(dir_fd, int) and dir_fd >= 0:
            base = directory_fd_path(dir_fd)
            if base is None:
                return None
        return base / candidate

    original_os_open = os.open

    def guarded_os_open(
        path: object,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if flags & (
            os.O_WRONLY
            | os.O_RDWR
            | os.O_CREAT
            | os.O_TRUNC
            | os.O_APPEND
        ):
            candidate = resolved_write_path(path, dir_fd)
            if candidate is None or not path_within(candidate, workspace):
                boundary_events["forbidden_write_count"] += 1
                raise PermissionError(
                    "parity target denied os.open write outside Workspace"
                )
        if dir_fd is None:
            return original_os_open(path, flags, mode)
        return original_os_open(path, flags, mode, dir_fd=dir_fd)

    os.open = guarded_os_open  # type: ignore[assignment]

    def guard(event: str, args: tuple[Any, ...]) -> None:
        candidates: list[tuple[object, object | None]] = []
        if event == "open" and args:
            raw_path = args[0]
            mode = args[1] if len(args) > 1 else "r"
            flags = args[2] if len(args) > 2 else 0
            write_mode = isinstance(mode, str) and any(
                token in mode for token in ("w", "a", "x", "+")
            )
            write_flags = isinstance(flags, int) and bool(
                flags
                & (
                    os.O_WRONLY
                    | os.O_RDWR
                    | os.O_CREAT
                    | os.O_TRUNC
                    | os.O_APPEND
                )
            )
            if (
                (write_mode or write_flags)
                and mode is not None
                and isinstance(raw_path, (str, bytes, os.PathLike))
            ):
                candidates.append((raw_path, None))
        elif event in {"os.rename", "os.replace"} and len(args) >= 2:
            candidates.extend(
                (
                    (args[0], args[2] if len(args) > 2 else None),
                    (args[1], args[3] if len(args) > 3 else None),
                )
            )
        elif event in write_events and args:
            dir_fd_indexes = {
                "os.remove": 1,
                "os.rmdir": 1,
                "os.mkdir": 2,
                "os.chmod": 2,
                "os.chown": 3,
                "os.utime": 3,
            }
            dir_fd_index = dir_fd_indexes.get(event)
            dir_fd = (
                args[dir_fd_index]
                if dir_fd_index is not None and len(args) > dir_fd_index
                else None
            )
            candidates.append((args[0], dir_fd))
        for raw_path, dir_fd in candidates:
            candidate = resolved_write_path(raw_path, dir_fd)
            if candidate is None or not path_within(candidate, workspace):
                boundary_events["forbidden_write_count"] += 1
                raise PermissionError(
                    f"parity target denied write outside Workspace: {candidate}"
                )

    sys.addaudithook(guard)


def install_network_guard(boundary_events: dict[str, int]) -> None:
    def denied(*_args: Any, **_kwargs: Any) -> Any:
        boundary_events["network_attempt_count"] += 1
        raise PermissionError("parity target denied outbound network access")

    socket.socket.connect = denied  # type: ignore[assignment]
    socket.socket.connect_ex = denied  # type: ignore[assignment]
    socket.getaddrinfo = denied  # type: ignore[assignment]


def _append_boundary_event(state: dict[str, Any], event: str) -> None:
    payload = (json.dumps({"event": event}) + "\n").encode("utf-8")
    descriptor = os.open(
        state["ledger"],
        os.O_WRONLY | os.O_CREAT | os.O_APPEND,
        0o600,
    )
    try:
        os.write(descriptor, payload)
    finally:
        os.close(descriptor)


def _install_process_audit_guard() -> None:
    global _PROCESS_AUDIT_GUARD_INSTALLED
    if _PROCESS_AUDIT_GUARD_INSTALLED:
        return

    def audit(event: str, _args: tuple[Any, ...]) -> None:
        state = _ACTIVE_SUBPROCESS_NETWORK_GUARD
        if (
            state is None
            or state.get("launching_monitored_process")
            or event
            not in {
                "os.exec",
                "os.posix_spawn",
                "os.spawn",
                "os.system",
            }
        ):
            return
        _append_boundary_event(state, f"unmonitored_process:{event}")
        raise PermissionError(
            "parity target denied an unmonitored process launch"
        )

    sys.addaudithook(audit)
    _PROCESS_AUDIT_GUARD_INSTALLED = True


def _guarded_process_argv(
    popenargs: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> list[str] | None:
    command = popenargs[0] if popenargs else kwargs.get("args")
    if isinstance(command, (str, bytes, os.PathLike)):
        return [os.fsdecode(command)]
    try:
        return [os.fsdecode(value) for value in command]
    except (TypeError, ValueError):
        return None


def _install_subprocess_launch_guard(state: dict[str, Any]) -> None:
    prior_popen = state["prior_popen"]
    network_scheme = re.compile(
        r"(?i)(?:https?|ftp|sftp|rtmp|rtsp|tcp|udp)://?"
    )

    def denied(event: str) -> None:
        _append_boundary_event(state, event)
        raise PermissionError(
            "parity target denied an unmonitored or network-capable "
            "process launch"
        )

    def guarded_popen(*popenargs: Any, **kwargs: Any) -> Any:
        if kwargs.get("shell"):
            denied("unmonitored_process:shell")
        argv = _guarded_process_argv(popenargs, kwargs)
        if not argv:
            denied("unmonitored_process:invalid_command")
        executable = os.fsdecode(
            kwargs.get("executable") or argv[0]
        )
        name = Path(executable).name.lower()
        if name.startswith("python"):
            if any(
                argument in {"-S", "-I", "-E"}
                for argument in argv[1:]
            ):
                denied("python_guard_bypass_flag")
            child_environment = dict(
                kwargs.get("env") or os.environ
            )
            child_environment["PYTHONPATH"] = str(state["guard_root"])
            child_environment[
                "VIRAL_REPLICA_PARITY_NETWORK_LEDGER"
            ] = str(state["ledger"])
            child_environment["PYTHONNOUSERSITE"] = "1"
            kwargs["env"] = child_environment
        elif name in {"ffmpeg", "ffprobe"}:
            if any(network_scheme.search(value) for value in argv[1:]):
                denied(f"native_network_argument:{name}")
        elif name == "git":
            if not any(value in {"status", "ls-files"} for value in argv):
                denied("unmonitored_process:git")
        else:
            denied(f"unmonitored_process:{name}")
        state["launching_monitored_process"] = True
        try:
            return prior_popen(*popenargs, **kwargs)
        finally:
            state["launching_monitored_process"] = False

    state["guarded_popen"] = guarded_popen
    subprocess.Popen = guarded_popen


def activate_subprocess_network_guard(
    workspace: Path,
    boundary_events: dict[str, int],
) -> dict[str, Any]:
    """Install a fail-closed network guard in every Python child process."""
    global _ACTIVE_SUBPROCESS_NETWORK_GUARD
    guard_root = workspace.resolve() / ".parity-python-guard"
    guard_root.mkdir(parents=True, exist_ok=True)
    ledger = guard_root / "network-attempts.jsonl"
    ledger.write_text("", encoding="utf-8")
    sitecustomize = guard_root / "sitecustomize.py"
    write_text(
        sitecustomize,
        "\n".join(
            [
                "import json",
                "import os",
                "import re",
                "import socket",
                "import subprocess",
                "import sys",
                "from pathlib import Path",
                "def _parity_denied(name):",
                "    ledger = os.environ.get("
                "'VIRAL_REPLICA_PARITY_NETWORK_LEDGER', '')",
                "    if ledger:",
                "        fd = os.open("
                "ledger, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)",
                "        try:",
                "            os.write(fd, (json.dumps({'event': name}) + "
                "'\\n').encode('utf-8'))",
                "        finally:",
                "            os.close(fd)",
                "    raise PermissionError("
                "'parity target denied outbound network access')",
                "def _parity_connect(*args, **kwargs):",
                "    return _parity_denied('socket.connect')",
                "def _parity_connect_ex(*args, **kwargs):",
                "    return _parity_denied('socket.connect_ex')",
                "def _parity_getaddrinfo(*args, **kwargs):",
                "    return _parity_denied('socket.getaddrinfo')",
                "socket.socket.connect = _parity_connect",
                "socket.socket.connect_ex = _parity_connect_ex",
                "socket.getaddrinfo = _parity_getaddrinfo",
                "_parity_original_popen = subprocess.Popen",
                "_parity_launching = False",
                "_parity_network_scheme = re.compile("
                "r'(?i)(?:https?|ftp|sftp|rtmp|rtsp|tcp|udp)://?')",
                "def _parity_popen(*args, **kwargs):",
                "    global _parity_launching",
                "    if kwargs.get('shell'):",
                "        return _parity_denied('unmonitored_process:shell')",
                "    command = args[0] if args else kwargs.get('args')",
                "    if isinstance(command, (str, bytes, os.PathLike)):",
                "        argv = [os.fsdecode(command)]",
                "    else:",
                "        try:",
                "            argv = [os.fsdecode(value) for value in command]",
                "        except (TypeError, ValueError):",
                "            return _parity_denied("
                "'unmonitored_process:invalid_command')",
                "    executable = os.fsdecode("
                "kwargs.get('executable') or argv[0])",
                "    name = Path(executable).name.lower()",
                "    if name.startswith('python'):",
                "        if any(value in {'-S', '-I', '-E'} "
                "for value in argv[1:]):",
                "            return _parity_denied("
                "'python_guard_bypass_flag')",
                "        child_env = dict(kwargs.get('env') or os.environ)",
                "        child_env['PYTHONPATH'] = str(Path(__file__).parent)",
                "        child_env["
                "'VIRAL_REPLICA_PARITY_NETWORK_LEDGER'] = "
                "os.environ.get("
                "'VIRAL_REPLICA_PARITY_NETWORK_LEDGER', '')",
                "        child_env['PYTHONNOUSERSITE'] = '1'",
                "        kwargs['env'] = child_env",
                "    elif name in {'ffmpeg', 'ffprobe'}:",
                "        if any(_parity_network_scheme.search(value) "
                "for value in argv[1:]):",
                "            return _parity_denied("
                "f'native_network_argument:{name}')",
                "    elif name == 'git':",
                "        if not any(value in {'status', 'ls-files'} "
                "for value in argv):",
                "            return _parity_denied("
                "'unmonitored_process:git')",
                "    else:",
                "        return _parity_denied("
                "f'unmonitored_process:{name}')",
                "    _parity_launching = True",
                "    try:",
                "        return _parity_original_popen(*args, **kwargs)",
                "    finally:",
                "        _parity_launching = False",
                "subprocess.Popen = _parity_popen",
                "def _parity_process_audit(event, args):",
                "    if (not _parity_launching and event in "
                "{'os.exec', 'os.posix_spawn', 'os.spawn', 'os.system'}):",
                "        _parity_denied(f'unmonitored_process:{event}')",
                "sys.addaudithook(_parity_process_audit)",
            ]
        ),
    )
    state = {
        "guard_root": guard_root,
        "ledger": ledger,
        "seen": 0,
        "boundary_events": boundary_events,
        "prior_popen": subprocess.Popen,
        "launching_monitored_process": False,
        "prior_environment": {
            key: os.environ.get(key)
            for key in (
                "PYTHONPATH",
                "VIRAL_REPLICA_PARITY_NETWORK_LEDGER",
            )
        },
    }
    os.environ["PYTHONPATH"] = str(guard_root)
    os.environ["VIRAL_REPLICA_PARITY_NETWORK_LEDGER"] = str(ledger)
    _ACTIVE_SUBPROCESS_NETWORK_GUARD = state
    _install_process_audit_guard()
    _install_subprocess_launch_guard(state)
    return state


def assert_no_subprocess_network_attempts() -> None:
    state = _ACTIVE_SUBPROCESS_NETWORK_GUARD
    if state is None:
        return
    try:
        count = sum(
            1
            for line in state["ledger"].read_text(
                encoding="utf-8",
            ).splitlines()
            if line.strip()
        )
    except OSError as exc:
        raise ParityStop(
            "network_guard_failed",
            "subprocess network event ledger is unreadable",
        ) from exc
    delta = count - int(state["seen"])
    if delta > 0:
        state["boundary_events"]["network_attempt_count"] += delta
        state["seen"] = count
        raise ParityStop(
            "network_forbidden",
            f"{delta} subprocess outbound network or guard-bypass "
            "attempt(s)",
            stage="provider_boundary",
            artifact_family="network_attempts",
            expected=0,
            actual=count,
        )


def deactivate_subprocess_network_guard() -> None:
    global _ACTIVE_SUBPROCESS_NETWORK_GUARD
    state = _ACTIVE_SUBPROCESS_NETWORK_GUARD
    if state is None:
        return
    subprocess.Popen = state["prior_popen"]
    for key, prior in state["prior_environment"].items():
        if prior is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = prior
    _ACTIVE_SUBPROCESS_NETWORK_GUARD = None


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ParityStop("missing_engine_resource", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_source_rhythm_qc(engine_root: Path) -> Any:
    tools = engine_root / "tools"
    path = tools / "source_rhythm_qc.py"
    if not path.is_file():
        raise ParityStop("missing_engine_resource", str(path))
    sys.path.insert(0, str(tools))
    return load_module(
        path,
        "parity_source_rhythm_qc",
    )


def cost_policy(engine_root: Path) -> dict[str, Any]:
    text = (engine_root / "COST_POLICY.md").read_text(encoding="utf-8")
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if match is None:
        raise ParityStop("missing_engine_resource", "COST_POLICY.md JSON contract")
    value = json.loads(match.group(1))
    if not isinstance(value, dict):
        raise ParityStop("missing_engine_resource", "COST_POLICY.md JSON contract")
    return value


def rule_for_status(stage_rules: dict[str, Any], status: str) -> dict[str, Any]:
    for rule in stage_rules.get("rules", []):
        match = rule.get("match") or {}
        if match.get("type") == "exact" and match.get("status") == status:
            return copy.deepcopy(rule)
        if (
            match.get("type") == "prefix"
            and isinstance(match.get("status"), str)
            and status.startswith(match["status"])
        ):
            return copy.deepcopy(rule)
    raise ParityStop("missing_engine_resource", f"stage rule for {status}")


def fixture_file_projection(fixture_root: Path) -> dict[str, dict[str, Any]]:
    return {
        path.relative_to(fixture_root).as_posix(): {
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for path in sorted(fixture_root.rglob("*"))
        if path.is_file()
    }


def python_semantic_sha256(path: Path) -> str:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        raise ParityStop("missing_engine_resource", str(path)) from exc
    semantics = ast.dump(
        tree,
        annotate_fields=True,
        include_attributes=False,
    )
    return sha256_bytes((semantics + "\n").encode("utf-8"))


def qc_behavior_probe_projection(engine_root: Path) -> dict[str, Any]:
    script = r'''
import json
import sys
import tempfile
import types
from pathlib import Path

from PIL import Image

tools = Path(sys.argv[1]).resolve() / "tools"
sys.path.insert(0, str(tools))
import codex_imagegen_contract_qc as image_contract
import request_body_qc as request_qc
import seedance_request_contract
import storyboard_visual_acceptance as storyboard_acceptance


def status_map(checks):
    return {
        str(item.get("name")): str(item.get("status"))
        for item in checks
        if isinstance(item, dict)
    }


def request_status(data):
    args = types.SimpleNamespace(
        allowed_task_codes=["123"],
        expected_endpoint="higress-api.wujieai.com",
        expected_model_ep="ep-test",
        require_public_urls=True,
        forbid_asset_refs=True,
        prompt_files=[],
    )
    report = request_qc.check_request(Path("request.json"), data, args)
    checks = status_map(report["checks"])
    return {
        name: checks.get(name)
        for name in (
            "task_code_consistency",
            "task_code",
            "endpoint",
            "model_ep",
            "public_urls",
            "no_asset_refs",
            "prompt_text_present",
        )
    }


param = {
    "duration": 4,
    "content": [
        {
            "type": "text",
            "text": "@图片1 synthetic production prompt with enough text",
        },
        {
            "type": "image_url",
            "role": "reference_image",
            "image_url": {"url": "https://example.invalid/reference.png"},
        },
    ],
}
base_request = {
    "method": "POST",
    "url": seedance_request_contract.TASK_CREATE_URL,
    "prepared_only": True,
    "do_not_submit": True,
    "model": "ep-test",
    "body": {
        "taskCode": 123,
        "acquireResourceTimeoutSeconds": 60,
        "param": json.dumps(param),
    },
}
local_request = json.loads(json.dumps(base_request))
local_request["local_image"] = "/Users/example/local.png"
relative_request = json.loads(json.dumps(base_request))
relative_request["local_image"] = "relative-board.png"
task_mismatch = json.loads(json.dumps(base_request))
task_mismatch["taskCode"] = 999
model_mismatch = json.loads(json.dumps(base_request))
model_mismatch["model"] = "ep-weakened"
endpoint_mismatch = json.loads(json.dumps(base_request))
endpoint_mismatch["url"] = "https://example.invalid/task-create"
request_projection = {
    "valid": request_status(base_request),
    "local_absolute": request_status(local_request),
    "local_relative": request_status(relative_request),
    "taskcode_mismatch": request_status(task_mismatch),
    "model_mismatch": request_status(model_mismatch),
    "endpoint_mismatch": request_status(endpoint_mismatch),
}

reference_checks = []
image_contract.check_reference_order(
    reference_checks,
    {"reference_order": [
        "source_storyboard",
        "product_front",
        "product_open_mud",
        "identity_ref",
    ]},
    {},
    "valid",
    {},
)
image_contract.check_reference_order(
    reference_checks,
    {"reference_order": [
        "product_front",
        "source_storyboard",
        "product_open_mud",
        "identity_ref",
    ]},
    {},
    "reordered",
    {},
)
generation_checks = []
image_contract.check_generation_settings(
    generation_checks,
    {
        "codex_generation_settings": {
            "quality": "medium",
            "resolution": "1k",
            "ratio": "4:3",
        }
    },
    {},
    "valid",
)
image_contract.check_generation_settings(
    generation_checks,
    {
        "codex_generation_settings": {
            "quality": "low",
            "resolution": "512",
        }
    },
    {},
    "weakened",
)
profile = {
    "prompt_required_groups": [
        {"name": "target", "patterns": ["fixture-target"]}
    ],
    "source_storyboard_controls": sorted(
        image_contract.REQUIRED_SOURCE_CONTROLS
    ),
    "source_storyboard_must_not_control": sorted(
        image_contract.REQUIRED_SOURCE_EXCLUSIONS
    ),
}
prompt_checks = []
image_contract.check_prompt(
    prompt_checks,
    "fixture-target clean prompt",
    "valid",
    profile,
)
image_contract.check_prompt(
    prompt_checks,
    "missing required target",
    "missing",
    profile,
)
image_contract.check_prompt(
    prompt_checks,
    "fixture-target with brush head",
    "forbidden",
    profile,
)
source_checks = []
image_contract.check_source_contract(
    source_checks,
    {
        "source_storyboard_controls": sorted(
            image_contract.REQUIRED_SOURCE_CONTROLS
        ),
        "source_storyboard_must_not_control": sorted(
            image_contract.REQUIRED_SOURCE_EXCLUSIONS
        ),
    },
    profile,
)
image_contract_projection = {
    "accepted_routes": sorted(image_contract.ACCEPTED_IMAGE_ROUTES),
    "required_review_flags": sorted(
        image_contract.REQUIRED_REVIEW_FLAGS
    ),
    "reference_order": status_map(reference_checks),
    "generation_settings": status_map(generation_checks),
    "prompt": status_map(prompt_checks),
    "source_contract": status_map(source_checks),
}


def aspect_status(root, width):
    job_dir = root / "output" / "job-001"
    candidate = job_dir / "final-images" / f"candidate-{width}.png"
    source = job_dir / "storyboard_source_refs" / "source.png"
    evidence = job_dir / "checks" / f"labels-{width}.json"
    hard_gate = job_dir / "checks" / f"hard-gate-{width}.json"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    source.parent.mkdir(parents=True, exist_ok=True)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1000, 1000), "white").save(source)
    Image.new("RGB", (width, 1000), "white").save(candidate)
    evidence.write_text(
        json.dumps({
            "grid": {"cols": 3, "rows": 4},
            "canvas": [width, 1000],
            "output_sha256": storyboard_acceptance.sha256_file(candidate),
            "labels": [f"Shot {index:02d}" for index in range(1, 13)],
            "status": "PASS",
            "postprocess_type": "shot_label_metadata_only",
            "outside_label_changed_pixels": 0,
            "panel_pixels_modified": False,
            "panel_content_sha256_before": "a" * 64,
            "panel_content_sha256_after": "a" * 64,
        }),
        encoding="utf-8",
    )
    hard_gate.write_text(
        json.dumps({
            "overall": "PASS",
            "candidate": str(candidate),
            "candidate_sha256": storyboard_acceptance.sha256_file(candidate),
        }),
        encoding="utf-8",
    )
    checks = []
    storyboard_acceptance.validate_part_context(
        root,
        "job-001",
        {
            "part_storyboards": {
                "part1": {
                    "path": str(candidate),
                    "source_reference": str(source),
                    "candidate_sha256": storyboard_acceptance.sha256_file(
                        candidate
                    ),
                    "shot_label_metadata": {
                        "evidence": str(evidence),
                    },
                    "hard_gate": str(hard_gate),
                }
            }
        },
        checks,
        [],
    )
    statuses = status_map(checks)
    return {
        "orientation": statuses.get("part1_orientation_matches_source"),
        "canvas_aspect": statuses.get(
            "part1_canvas_aspect_matches_source"
        ),
    }


with tempfile.TemporaryDirectory() as tmp:
    storyboard_projection = {
        "two_percent_drift": aspect_status(Path(tmp), 1020),
        "four_percent_drift": aspect_status(Path(tmp), 1040),
        "portrait_grid": storyboard_acceptance.expected_grid("portrait"),
        "landscape_grid": storyboard_acceptance.expected_grid("landscape"),
    }

print(json.dumps({
    "request_body_qc": request_projection,
    "codex_imagegen_contract_qc": image_contract_projection,
    "storyboard_visual_acceptance": storyboard_projection,
}, sort_keys=True))
'''
    result = subprocess.run(
        [sys.executable, "-c", script, str(engine_root)],
        text=True,
        capture_output=True,
        check=False,
        env=safe_target_environment(),
    )
    assert_no_subprocess_network_attempts()
    if result.returncode != 0:
        raise ParityStop(
            "missing_engine_resource",
            "QC behavior probe failed: "
            f"{result.stdout}{result.stderr}",
        )
    try:
        projection = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ParityStop(
            "missing_engine_resource",
            f"QC behavior probe emitted invalid JSON: {result.stdout}",
        ) from exc
    if not isinstance(projection, dict):
        raise ParityStop(
            "missing_engine_resource",
            "QC behavior probe did not emit an object",
        )
    return projection


def engine_contract_projection(
    engine_root: Path,
    *,
    include_behavior_probes: bool = True,
) -> dict[str, Any]:
    json_paths = [
        "rules/STAGE_RULES.json",
        "rules/SEEDANCE_MODEL.json",
        "rules/VIDEO_UNDERSTANDING_MODEL.json",
    ]
    projection = {}
    for relative in json_paths:
        path = engine_root / relative
        if not path.is_file():
            raise ParityStop("missing_engine_resource", relative)
        projection[relative] = read_json(path)
    projection["cost_policy"] = cost_policy(engine_root)
    projection["qc_full_semantic_closure"] = {}
    for relative, accepted_hashes in QC_FULL_SEMANTIC_EQUIVALENCE.items():
        path = engine_root / relative
        if not path.is_file():
            raise ParityStop("missing_engine_resource", relative)
        semantic_sha256 = python_semantic_sha256(path)
        projection["qc_full_semantic_closure"][relative] = (
            {
                "contract": "reviewed_full_ast_equivalence_v1",
                "recognized": True,
            }
            if semantic_sha256 in accepted_hashes
            else {
                "contract": "unreviewed_semantics",
                "recognized": False,
                "semantic_sha256": semantic_sha256,
            }
        )
    projection["qc_executable_semantics"] = {}
    for relative in QC_EXECUTABLE_CONTRACT_PATHS:
        path = engine_root / relative
        if not path.is_file():
            raise ParityStop("missing_engine_resource", relative)
        projection["qc_executable_semantics"][relative] = (
            python_semantic_sha256(path)
        )
    if include_behavior_probes:
        projection["qc_behavior_probes"] = qc_behavior_probe_projection(
            engine_root,
        )
    return projection


def read_job_row(path: Path, job_id: str) -> dict[str, str]:
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    except OSError as exc:
        raise ParityStop("actual_intake_failed", str(path)) from exc
    matches = [row for row in rows if row.get("id") == job_id]
    if len(matches) != 1:
        raise ParityStop(
            "actual_intake_failed",
            f"{path}: expected one {job_id} row, found {len(matches)}",
        )
    return matches[0]


def normalize_parity_job_row(path: Path) -> None:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    matches = [row for row in rows if row.get("id") == FIXED_JOB_ID]
    if len(matches) != 1:
        raise ParityStop(
            "actual_intake_failed",
            f"{path}: cannot normalize the active parity row",
        )
    row = matches[0]
    updates = {
        "workflow_run_id": "parity-job-001",
        "video_path": "assets/source_video.mkv",
        "product_assets": "assets/product_reference.svg",
        "audio_assets": "assets/source_audio.wav",
        "output_dir": f"output/{FIXED_JOB_ID}",
    }
    row.update({key: value for key, value in updates.items() if key in fieldnames})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run_checked(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        env=safe_target_environment(),
    )
    assert_no_subprocess_network_attempts()
    if result.returncode != 0:
        raise ParityStop(
            "actual_tool_failed",
            f"{' '.join(command)}: {result.stdout}{result.stderr}",
        )
    return result


def write_outer_sandbox_adapter(
    root: Path,
    *,
    audited_workspace_root: Path,
) -> Path:
    if os.environ.get("VIRAL_REPLICA_PARITY_OUTER_SANDBOX") != "1":
        raise ParityStop(
            "sandbox_unavailable",
            "production-tool adapter requires the sealed outer sandbox",
        )
    path = root / "run_outer_sandbox_tool.py"
    write_text(
        path,
        "\n".join(
            [
                "import importlib",
                "import sys",
                "from pathlib import Path",
                "sys.path.insert(0, str(Path(__file__).parent / 'tools'))",
                "import stage_execution",
                "if hasattr(stage_execution, '_external_sandbox_execution_active'):",
                "    stage_execution._external_sandbox_execution_active = lambda: True",
                "    stage_execution._external_sandbox_workspace_root = (",
                "        lambda: Path("
                + repr(str(audited_workspace_root.resolve()))
                + ")",
                "    )",
                "else:",
                "    stage_execution._sandbox_execution_available = lambda: False",
                "module_name = sys.argv[1]",
                "sys.argv = [module_name, *sys.argv[2:]]",
                "module = importlib.import_module(module_name)",
                "raise SystemExit(module.main())",
            ]
        ),
    )
    return path


def normalize_fixture_reference(
    value: str,
    *,
    fixture_root: Path,
    workspace: Path,
) -> str:
    path = Path(value)
    if not path.is_absolute():
        return {
            "assets/source_video.mkv": "fixture://core/source_4s.mkv",
            "assets/product_reference.svg":
                "fixture://core/product_reference.svg",
            "assets/source_audio.wav":
                "fixture://core/source_audio_4s.wav",
        }.get(value, value)
    resolved = path.resolve()
    known = {
        sha256_file(fixture_root / "core" / "source_4s.mkv"):
            "fixture://core/source_4s.mkv",
        sha256_file(fixture_root / "core" / "product_reference.svg"):
            "fixture://core/product_reference.svg",
        sha256_file(fixture_root / "core" / "source_audio_4s.wav"):
            "fixture://core/source_audio_4s.wav",
    }
    if resolved.is_file():
        reference = known.get(sha256_file(resolved))
        if reference:
            return reference
    if path_within(resolved, workspace):
        return f"workspace://{resolved.relative_to(workspace).as_posix()}"
    raise ParityStop(
        "actual_intake_failed",
        f"unrecognized absolute intake path: {resolved}",
    )


def normalize_declared_roots(
    value: Any,
    *,
    fixture_root: Path,
    workspace: Path,
    job_root: Path | None = None,
) -> Any:
    if isinstance(value, dict):
        return {
            key: normalize_declared_roots(
                item,
                fixture_root=fixture_root,
                workspace=workspace,
                job_root=job_root,
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            normalize_declared_roots(
                item,
                fixture_root=fixture_root,
                workspace=workspace,
                job_root=job_root,
            )
            for item in value
        ]
    if not isinstance(value, str) or not value.startswith("/"):
        return value
    resolved = Path(value).resolve(strict=False)
    fixture_root_resolved = fixture_root.resolve()
    workspace_resolved = workspace.resolve()
    if path_within(resolved, fixture_root_resolved):
        return (
            "fixture://"
            f"{resolved.relative_to(fixture_root_resolved).as_posix()}"
        )
    if job_root is not None and path_within(resolved, job_root):
        job_root_resolved = job_root.resolve()
        return (
            "job_root://"
            f"{resolved.relative_to(job_root_resolved).as_posix()}"
        )
    if path_within(resolved, workspace_resolved):
        relative = resolved.relative_to(workspace_resolved).as_posix()
        parts = relative.split("/")
        for index, part in enumerate(parts):
            if part.startswith("video-understanding-"):
                suffix = "/".join(parts[index + 1 :])
                return (
                    "declared_temporary_root://video-understanding"
                    + (f"/{suffix}" if suffix else "")
                )
        return f"workspace://{relative}"
    return value


def normalize_declared_timestamps(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                f"<{key}>"
                if key in {"created_at", "updated_at", "generated_at"}
                else normalize_declared_timestamps(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [normalize_declared_timestamps(item) for item in value]
    return value


def normalize_job_root_aliases(
    value: Any,
    *,
    workspace: Path,
    job_root: Path,
    _field: str | None = None,
) -> Any:
    if isinstance(value, dict):
        return {
            key: normalize_job_root_aliases(
                item,
                workspace=workspace,
                job_root=job_root,
                _field=str(key),
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            normalize_job_root_aliases(
                item,
                workspace=workspace,
                job_root=job_root,
                _field=_field,
            )
            for item in value
        ]
    if not isinstance(value, str):
        return value
    job_id = job_root.parent.name if job_root.name == "work" else job_root.name
    normalized = re.sub(
        (
            rf"(?<![\w/:-])"
            rf"{re.escape(str(job_root.resolve()))}/"
        ),
        "job_root://",
        value,
    )
    normalized = re.sub(
        (
            rf"(?<![\w/:-])"
            rf"{re.escape(str(workspace.resolve()))}/"
        ),
        "workspace://",
        normalized,
    )
    normalized = re.sub(
        (
            rf"(?<![\w/:-])workspace://"
            rf"[^\s\"']*?/output/{re.escape(job_id)}/"
        ),
        "job_root://",
        normalized,
    )
    relative_prefix = f"output/{job_id}/"
    if normalized.startswith(relative_prefix) and not re.search(
        r"\s",
        normalized,
    ):
        return "job_root://" + normalized.removeprefix(relative_prefix)
    if _field == "detail":
        normalized = re.sub(
            rf"(?<![\w:/]){re.escape(relative_prefix)}",
            "job_root://",
            normalized,
        )
    return normalized


def canonical_artifact_bytes(
    path: Path,
    *,
    fixture_root: Path,
    workspace: Path,
    job_root: Path,
) -> bytes:
    if path.suffix.lower() == ".json":
        value = normalize_declared_roots(
            read_json(path),
            fixture_root=fixture_root,
            workspace=workspace,
            job_root=job_root,
        )
        value = normalize_job_root_aliases(
            value,
            workspace=workspace,
            job_root=job_root,
        )
        return canonical_bytes(normalize_declared_timestamps(value))
    if path.suffix.lower() not in {".md", ".txt", ".csv"}:
        return path.read_bytes()
    text = path.read_text(encoding="utf-8")
    text = re.sub(
        rf"(?<![\w/:-]){re.escape(str(job_root.resolve()))}/",
        "job_root://",
        text,
    )
    text = re.sub(
        rf"(?<![\w/:-]){re.escape(str(fixture_root.resolve()))}/",
        "fixture://",
        text,
    )
    text = re.sub(
        rf"(?<![\w/:-]){re.escape(str(workspace.resolve()))}/",
        "workspace://",
        text,
    )
    text = normalize_job_root_aliases(
        text,
        workspace=workspace,
        job_root=job_root,
    )
    return text.encode("utf-8")


def runner_decision_projection(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    fields = {}
    for field in (
        "Decision",
        "Matched rule",
        "Canonical stage",
        "Worker",
        "Gate",
        "Expected next status",
    ):
        match = re.search(
            rf"^- {re.escape(field)}: (?:\*\*)?`?([^`*\n]+)",
            text,
            flags=re.MULTILINE,
        )
        if match is None:
            raise ParityStop(
                "actual_intake_failed",
                f"{path}: missing runner field {field}",
            )
        fields[field.lower().replace(" ", "_")] = match.group(1).strip()
    return fields


def run_actual_intake(
    *,
    target_kind: str,
    engine_root: Path,
    fixture_root: Path,
    workspace: Path,
    handoff_mode: str = "both",
) -> tuple[dict[str, Any], dict[str, Any], list[Path], dict[str, Any]]:
    intake_root = workspace / "actual-intake"
    intake_root.mkdir()
    notes = "source_locked + necessary_only; stop before Seedance generation"
    common_args = [
        "--video",
        str(fixture_root / "core" / "source_4s.mkv"),
        "--product-name",
        "Synthetic Fixture Product",
        "--product-assets",
        str(fixture_root / "core" / "product_reference.svg"),
        "--person-assets",
        "storyboard_derived",
        "--audio-assets",
        str(fixture_root / "core" / "source_audio_4s.wav"),
        "--handoff-mode",
        handoff_mode,
        "--notes",
        notes,
    ]
    if target_kind == "legacy":
        for directory in ("rules", "gates", "workers"):
            shutil.copytree(
                engine_root / directory,
                intake_root / directory,
            )
        for filename in ("COST_POLICY.md", "LOOP.md", "QC_RULES.md"):
            shutil.copy2(engine_root / filename, intake_root / filename)
        run_checked(
            [
                sys.executable,
                str(engine_root / "scripts" / "new-task.py"),
                "--root",
                str(intake_root),
                *common_args,
            ],
            cwd=intake_root,
        )
        run_checked(
            [
                sys.executable,
                str(engine_root / "tools" / "run_next_loop_round.py"),
                "--root",
                str(intake_root),
                "--job-id",
                FIXED_JOB_ID,
            ],
            cwd=intake_root,
        )
        intake_path = intake_root / "output" / FIXED_JOB_ID / "intake.json"
        profile_path = (
            intake_root / "output" / FIXED_JOB_ID / "product_profile.json"
        )
        row = read_job_row(intake_root / "jobs.csv", FIXED_JOB_ID)
        decision_path = intake_root / "RUNNER_LAST_DECISION.md"
        execution = {
            "target_kind": target_kind,
            "layout_root": intake_root,
            "state_root": intake_root,
            "job_root": intake_root / "output" / FIXED_JOB_ID,
            "job_work": intake_root / "output" / FIXED_JOB_ID,
            "jobs_path": intake_root / "jobs.csv",
            "execution_context": None,
        }
    elif target_kind == "plugin":
        plugin_root = engine_root.parent
        run_checked(
            [
                sys.executable,
                str(plugin_root / "scripts" / "run-canonical-job.py"),
                "--workspace",
                str(intake_root),
                *common_args,
            ],
            cwd=intake_root,
        )
        intake_path = (
            intake_root / "jobs" / FIXED_JOB_ID / "input" / "intake.json"
        )
        profile_path = (
            intake_root
            / "jobs"
            / FIXED_JOB_ID
            / "input"
            / "product_profile.json"
        )
        row = read_job_row(
            intake_root / ".viral-replica" / "state" / "jobs.csv",
            FIXED_JOB_ID,
        )
        decision_path = (
            intake_root
            / ".viral-replica"
            / "state"
            / "RUNNER_LAST_DECISION.md"
        )
        execution = {
            "target_kind": target_kind,
            "layout_root": intake_root,
            "state_root": intake_root / ".viral-replica" / "state",
            "job_root": intake_root / "jobs" / FIXED_JOB_ID,
            "job_work": intake_root / "jobs" / FIXED_JOB_ID / "work",
            "jobs_path": (
                intake_root / ".viral-replica" / "state" / "jobs.csv"
            ),
            "execution_context": (
                intake_root
                / ".viral-replica"
                / "state"
                / f"execution-context-{FIXED_JOB_ID}.json"
            ),
        }
    else:
        raise ParityStop("actual_intake_failed", f"unknown target: {target_kind}")

    actual_intake = read_json(intake_path)
    profile = read_json(profile_path)
    fixture_effective_profile = read_json(
        fixture_root / "shared" / "effective_profile.json"
    )
    profile_overlay = fixture_effective_profile.get("product_profile_overlay")
    if not isinstance(profile_overlay, dict) or not profile_overlay:
        raise ParityStop(
            "actual_intake_failed",
            "fixture Effective Profile has no product_profile_overlay",
        )
    if profile.get("loaded_rules") != ["generic:generic_product"]:
        raise ParityStop(
            "actual_intake_failed",
            "main fixture no longer routes through the generic product profile",
        )
    profile.update(copy.deepcopy(profile_overlay))
    profile["effective_profile_id"] = fixture_effective_profile[
        "effective_profile_id"
    ]
    profile["effective_profile_components"] = copy.deepcopy(
        fixture_effective_profile["components"]
    )
    write_json(profile_path, profile)
    if not decision_path.is_file():
        raise ParityStop("actual_intake_failed", str(decision_path))
    source = actual_intake.get("source_video") or {}
    if source.get("sha256") != sha256_file(
        fixture_root / "core" / "source_4s.mkv"
    ):
        raise ParityStop("actual_intake_failed", "source hash changed")
    target_duration = actual_intake.get("target_duration") or {}
    projection = {
        "schema_version": 1,
        "job_id": FIXED_JOB_ID,
        "simple_intake": {
            "source_video": normalize_fixture_reference(
                str(source.get("path") or row["video_path"]),
                fixture_root=fixture_root,
                workspace=intake_root,
            ),
            "product_name": row["product_name"],
            "product_assets": normalize_fixture_reference(
                row["product_assets"],
                fixture_root=fixture_root,
                workspace=intake_root,
            ),
            "person_assets": row["person_assets"],
            "audio_assets": normalize_fixture_reference(
                row["audio_assets"],
                fixture_root=fixture_root,
                workspace=intake_root,
            ),
            "target_duration": None,
            "notes": row["notes"],
        },
        "target_duration": {
            "value": target_duration["value"],
            "explicitly_requested": target_duration["explicitly_requested"],
            "evidence": {
                "source": "measured_source_media",
                "duration_seconds": 4.0,
            },
        },
        "handoff_mode": row["handoff_mode"],
        "status": row["status"],
        "next_stage": row["next_stage"],
        "production_evidence": {
            "entrypoint_executed": True,
            "profile_semantic_sha256": sha256_bytes(canonical_bytes(profile)),
            "fixture_effective_profile_sha256": sha256_file(
                fixture_root / "shared" / "effective_profile.json"
            ),
            "first_runner_decision": runner_decision_projection(decision_path),
        },
    }
    return (
        projection,
        profile,
        [intake_path, profile_path, decision_path],
        execution,
    )


def prepare_actual_pre_seedance_pack(
    *,
    engine_root: Path,
    fixture_root: Path,
    workspace: Path,
    execution: dict[str, Any],
    profile: dict[str, Any],
    rhythm: dict[str, Any],
    script: dict[str, Any],
    sealed_verdicts: dict[str, Any],
    advance_stage: Any,
) -> tuple[dict[str, Any], list[Path], dict[str, Any]]:
    if execution["target_kind"] == "legacy":
        root = Path(execution["layout_root"])
    else:
        root = Path(execution["layout_root"])
        output_root = root / "output"
        output_root.mkdir()
        canonical_work = Path(execution["job_work"])
        physical_work = output_root / FIXED_JOB_ID
        physical_work.symlink_to(
            canonical_work,
            target_is_directory=True,
        )
        shutil.copy2(Path(execution["jobs_path"]), root / "jobs.csv")
        state_output = Path(execution["state_root"]) / "output"
        state_output.mkdir(exist_ok=True)
        state_job = state_output / FIXED_JOB_ID
        if not state_job.exists():
            state_job.symlink_to(
                canonical_work,
                target_is_directory=True,
            )
        for name in ("tools", "rules", "gates", "workers"):
            bridge = Path(execution["state_root"]) / name
            if not bridge.exists():
                bridge.symlink_to(
                    engine_root / name,
                    target_is_directory=True,
                )
        for name in ("assets", "references"):
            bridge = Path(execution["state_root"]) / name
            if not bridge.exists():
                bridge.symlink_to(
                    root / name,
                    target_is_directory=True,
                )
    job_dir = root / "output" / FIXED_JOB_ID
    write_json(job_dir / "product_profile.json", profile)
    shutil.copytree(engine_root / "tools", root / "tools")
    if not (root / "rules").exists():
        shutil.copytree(engine_root / "rules", root / "rules")
    production_adapter = write_outer_sandbox_adapter(
        root,
        audited_workspace_root=workspace,
    )
    stage_execution = {
        **execution,
        "adapter_root": root,
        "production_root": root,
        "job_dir": job_dir,
        "production_adapter": production_adapter,
    }
    qc_root = (
        Path(execution["state_root"])
        if execution["target_kind"] == "plugin"
        else root
    )
    for source, relative in (
        (fixture_root / "core" / "source_4s.mkv", "assets/source_video.mkv"),
        (
            fixture_root / "core" / "source_audio_4s.wav",
            "assets/source_audio.wav",
        ),
        (
            fixture_root / "core" / "product_reference.svg",
            "assets/product_reference.svg",
        ),
        (fixture_root / "core" / "storyboard.svg", "assets/storyboard.svg"),
    ):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    normalize_parity_job_row(Path(execution["jobs_path"]))
    source_evidence = prepare_source_blueprint_gate_evidence(
        fixture_root=fixture_root,
        workspace=workspace,
        rhythm=rhythm,
        pack_execution=stage_execution,
        sealed_verdicts=sealed_verdicts,
    )
    advance_stage(
        "source_blueprint",
        source_evidence,
        stage_execution,
    )

    fixture_recorder = load_module(
        SOURCE_ROOT / "tools" / "provider_fixture_recorder.py",
        "parity_image_provider_fixture_recorder",
    )
    image_request = read_json(
        fixture_root / "provider" / "image_request.json"
    )
    image_recorder = fixture_recorder.ZeroSubmissionRecorder(
        fixture_root / "provider" / "image_recording.json",
        now="2026-07-30T12:00:00Z",
    )
    image_response = image_recorder.replay(image_request)
    image_recorder_metrics = image_recorder.metrics()
    image_receipt = image_response.get("receipt")
    if image_receipt != {
        "mode": "sealed_offline_replay",
        "real_submit": False,
        "task_created": False,
        "paid_task_count": 0,
        "media_generation_task_count": 0,
        "external_effects": [],
    }:
        raise ParityStop(
            "provider_side_effect",
            json.dumps(image_receipt, ensure_ascii=False),
        )
    image_result = image_response.get("result") or {}
    sealed_candidate = fixture_root / str(image_result.get("path") or "")
    if (
        not sealed_candidate.is_file()
        or image_result.get("sha256") != sha256_file(sealed_candidate)
    ):
        raise ParityStop(
            "image_recorder_failed",
            "sealed image response does not bind its saved candidate",
        )
    source_board = (
        job_dir / "storyboard_source_refs" / "source_storyboard_part1.png"
    )
    candidate = job_dir / "final-images" / "part1_seedance_ref.png"
    for destination, source in (
        (source_board, fixture_root / "image" / "source_storyboard.png"),
        (candidate, sealed_candidate),
    ):
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        destination.chmod(0o644)
    product_front = job_dir / "reusable" / "product" / "front.png"
    product_open = job_dir / "reusable" / "product" / "open.png"
    identity_ref = job_dir / "reusable" / "identity" / "ref.png"
    for destination, source in (
        (product_front, fixture_root / "image" / "product_front.png"),
        (product_open, fixture_root / "image" / "product_open.png"),
        (identity_ref, fixture_root / "image" / "identity_ref.png"),
    ):
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        destination.chmod(0o644)
    write_json(
        product_front.parent / "manifest.json",
        {
            "asset_group_type": "product_group",
            "product_id": "fixture-product",
            "product_name": "Synthetic Fixture Product",
            "source_assets": read_job_row(
                Path(execution["jobs_path"]),
                FIXED_JOB_ID,
            )["product_assets"],
            "front_ref": "front.png",
            "open_mud_ref": "open.png",
        },
    )
    role_map = job_dir / "visual-assets" / "storyboard_derived_role_map.json"
    write_json(
        role_map,
        {
            "job_id": FIXED_JOB_ID,
            "roles": [
                {
                    "id": "host",
                    "identity_required": True,
                    "gender": "female",
                    "parts": ["part1"],
                }
            ],
        },
    )
    role_manifest = (
        job_dir / "reusable" / "identity" / "host_manifest.json"
    )
    write_json(
        role_manifest,
        {
            "asset_group_type": "identity_group",
            "identity_id": "host",
            "role_id": "host",
            "origin": "storyboard_derived",
            "source_job_id": FIXED_JOB_ID,
            "source_part": "part1",
            "source_storyboard": candidate.relative_to(root).as_posix(),
            "presenter_gender": "female",
            "identity_ref": "ref.png",
        },
    )
    shot_label_evidence = (
        job_dir / "checks" / "part1_shot_label_restore.json"
    )
    write_json(
        shot_label_evidence,
        {
            "status": "PASS",
            "postprocess_type": "shot_label_metadata_only",
            "output_sha256": sha256_file(candidate),
            "canvas": [400, 600],
            "grid": {"cols": 4, "rows": 3},
            "labels": [f"Shot {index:02d}" for index in range(1, 13)],
            "outside_label_changed_pixels": 0,
            "panel_pixels_modified": False,
            "panel_content_sha256_before": "a" * 64,
            "panel_content_sha256_after": "a" * 64,
        },
    )
    hard_gate = job_dir / "checks" / "part1_image_hard_gate_qc.json"
    write_json(
        hard_gate,
        {
            "overall": "PASS",
            "candidate": candidate.relative_to(root).as_posix(),
            "candidate_sha256": sha256_file(candidate),
        },
    )
    write_json(
        job_dir / "visual-assets" / "approved_visual_manifest.json",
        {
            "schema_version": 2,
            "job_id": FIXED_JOB_ID,
            "product_group_id": "fixture-product",
            "product_group_manifest": (
                f"output/{FIXED_JOB_ID}/reusable/product/manifest.json"
            ),
            "person_asset_mode": "storyboard_derived",
            "role_map": role_map.relative_to(root).as_posix(),
            "identity_role_manifests": {
                "host": role_manifest.relative_to(root).as_posix()
            },
            "part_identity_roles": {"part1": ["host"]},
            "part_reusable_refs": {
                "part1": {
                    "identity_host": identity_ref.relative_to(root).as_posix()
                }
            },
            "source_presenter_gender": "female",
            "target_presenter_gender": "female",
            "reusable_refs": {
                "product_front": (
                    f"output/{FIXED_JOB_ID}/reusable/product/front.png"
                ),
                "product_open": (
                    f"output/{FIXED_JOB_ID}/reusable/product/open.png"
                ),
                "identity_ref": (
                    f"output/{FIXED_JOB_ID}/reusable/identity/ref.png"
                ),
            },
            "part_storyboards": {
                "part1": {
                    "path": candidate.relative_to(root).as_posix(),
                    "asset_type": "AI改好分镜图",
                    "image_route": image_result["image_route"],
                    "contains_source_video_pixels": False,
                    "source_reference": source_board.relative_to(root).as_posix(),
                    "candidate_sha256": sha256_file(candidate),
                    "hard_gate": hard_gate.relative_to(root).as_posix(),
                    "shot_label_metadata": {
                        "type": "shot_label_metadata_only",
                        "evidence": (
                            shot_label_evidence.relative_to(root).as_posix()
                        ),
                        "panel_pixels_modified": False,
                    },
                }
            },
        },
    )
    image_contract = job_dir / "image-batch" / "codex_imagegen_contract.json"
    image_prompt = job_dir / "image-batch" / "prompts" / "part1.txt"
    image_contract.parent.mkdir(parents=True, exist_ok=True)
    image_prompt.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        fixture_root / "image" / "sealed_image_contract.json",
        image_contract,
    )
    shutil.copy2(
        fixture_root / "image" / "image_prompt.txt",
        image_prompt,
    )
    run_checked(
        [
            sys.executable,
            str(production_adapter),
            "codex_imagegen_contract_qc",
            "--root",
            str(qc_root),
            "--job-id",
            FIXED_JOB_ID,
            "--stage",
            "image_batch_qc",
            "--out-json",
            str(job_dir / "checks" / "codex_imagegen_contract_qc.json"),
            "--out-md",
            str(job_dir / "checks" / "codex_imagegen_contract_qc.md"),
        ],
        cwd=qc_root,
    )
    run_checked(
        [
            sys.executable,
            str(production_adapter),
            "visual_asset_manifest_qc",
            "--root",
            str(qc_root),
            "--job-id",
            FIXED_JOB_ID,
            "--stage",
            "image_batch_qc",
            "--out-json",
            str(job_dir / "checks" / "visual_asset_manifest_qc.json"),
            "--out-md",
            str(job_dir / "checks" / "visual_asset_manifest_qc.md"),
        ],
        cwd=qc_root,
    )
    run_checked(
        [
            sys.executable,
            str(production_adapter),
            "storyboard_visual_acceptance",
            "--root",
            str(qc_root),
            "--job-id",
            FIXED_JOB_ID,
            "--stage",
            "image_batch_qc",
            "--mode",
            "active",
        ],
        cwd=qc_root,
    )
    image_evidence = [
        candidate,
        job_dir / "visual-assets" / "approved_visual_manifest.json",
        image_contract,
        image_prompt,
        job_dir / "checks" / "codex_imagegen_contract_qc.json",
        job_dir / "checks" / "visual_asset_manifest_qc.json",
        job_dir
        / "checks"
        / "image_batch_qc_storyboard_visual_acceptance.json",
        job_dir
        / "checks"
        / "image_batch_qc_storyboard_visual_acceptance_request.json",
        hard_gate,
    ]
    advance_stage(
        "image_batch_qc",
        image_evidence,
        stage_execution,
    )
    write_json(job_dir / "剧情分析" / "source_rhythm.json", rhythm)
    write_json(
        job_dir / "剧情分析" / "expression_prompt_profile.json",
        {
            "schema_version": 1,
            "source_sha256": rhythm["source_sha256"],
            "mode": "single_person_budgeted",
            "people_mode": "single_primary",
            "blink_policy": "budgeted",
            "budget": {
                "max_chars_per_shot": 36,
                "max_clauses_per_shot": 3,
                "max_blink_phrases_per_cue": 1,
            },
            "natural_blink_fallback": {
                "eligible": True,
                "face_detection_coverage": 1.0,
                "reliable_blink_event_count": 0,
            },
            "semantic_timeline": [],
        },
    )
    write_json(
        job_dir / "intake.json",
        {
            "schema_version": 1,
            "job_id": FIXED_JOB_ID,
            "target_duration": {
                "value": "4s",
                "explicitly_requested": False,
                "request_evidence": None,
            },
            "user_request": {
                "notes": (
                    "source_locked + necessary_only; "
                    "stop before Seedance generation"
                )
            },
        },
    )
    write_json(job_dir / "product_profile.json", profile)
    run_checked(
        [
            sys.executable,
            str(production_adapter),
            "pre_seedance_pack",
            "init",
            "--root",
            str(root),
            "--job-id",
            FIXED_JOB_ID,
            "--handoff-mode",
            "both",
        ],
        cwd=root,
    )
    plan_path = job_dir / "seedance" / "director_plan.json"
    plan = read_json(plan_path)
    if len(plan.get("parts") or []) != 1:
        raise ParityStop(
            "actual_pre_seedance_failed",
            "4-second fixture must compile to exactly one Part",
        )
    part = plan["parts"][0]
    if len(part.get("beats") or []) != len(rhythm["beats"]):
        raise ParityStop(
            "actual_pre_seedance_failed",
            "fixture rhythm must bind the production six-beat skeleton",
        )
    part.update(
        {
            "main_goal": "Preserve the source-locked product proof",
            "secondary_goal": "Keep the fixture product identity stable",
            "simplify": "No extra people, actions, overlays, or music",
            "scene_rule": "Keep the source tabletop scene",
        }
    )
    part["seam"] = {
        "start_state": "closed product at source start",
        "end_state": "single wipe proof complete",
    }
    part["audio"] = {
        "source": "assets/source_audio.wav",
        "source_start": 0.0,
        "source_end": 4.0,
    }
    for target_beat, source_beat in zip(part["beats"], rhythm["beats"]):
        duration = (
            float(source_beat["source_end"])
            - float(source_beat["source_start"])
        )
        peak_fractions = ",".join(
            f"{(float(peak) - float(source_beat['source_start'])) / duration:.3f}"
            for peak in source_beat["action_peak_times"]
        )
        transition = (
            f"entry={source_beat['entry_transition']};"
            f"exit={source_beat['exit_transition']}"
        )
        target_beat.update(
            {
                "target_start": source_beat["source_start"],
                "target_end": source_beat["source_end"],
                "source_start": source_beat["source_start"],
                "source_end": source_beat["source_end"],
                "source_beat_ids": [source_beat["id"]],
                "source_visual_action": source_beat["visual_action"],
                "source_speaker_mode": source_beat["speaker_mode"],
                "source_line": source_beat["confirmed_source_line"],
                "source_pause_after_seconds": source_beat[
                    "pause_after_seconds"
                ],
                "target_visual_action": (
                    f"{source_beat['visual_action']} with the teal "
                    "Synthetic Fixture Product replacing the coral "
                    "source fixture product"
                ),
                "visual_fidelity": {
                    "source_scene": source_beat["scene"],
                    "target_scene": source_beat["scene"],
                    "source_camera": source_beat["camera"],
                    "target_camera": source_beat["camera"],
                    "source_framing": source_beat["framing"],
                    "target_framing": source_beat["framing"],
                    "source_action_stage": source_beat[
                        "visual_action_type"
                    ],
                    "target_action_stage": source_beat[
                        "visual_action_type"
                    ],
                    "source_action_timing": (
                        f"peak_fractions={peak_fractions}"
                    ),
                    "target_action_timing": (
                        f"peak_fractions={peak_fractions}"
                    ),
                    "source_transition": (
                        f"{source_beat['entry_transition']} -> "
                        f"{source_beat['exit_transition']}"
                    ),
                    "target_transition": (
                        f"{source_beat['entry_transition']} -> "
                        f"{source_beat['exit_transition']}"
                    ),
                    "source_hard_cuts": transition,
                    "target_hard_cuts": transition,
                },
                "visual_edits": [
                    {
                        "from": source_beat["visual_action"],
                        "to": (
                            f"{source_beat['visual_action']} with the teal "
                            "Synthetic Fixture Product replacing the coral "
                            "source fixture product"
                        ),
                        "reason": "product_identity",
                        "reason_detail": (
                            "preserve the source action while binding the "
                            "approved fixture product"
                        ),
                        "profile_evidence": (
                            f"output/{FIXED_JOB_ID}/product_profile.json"
                        ),
                        "preserved_dimensions": [
                            "shot_order",
                            "scene",
                            "camera",
                            "framing",
                            "action_stage",
                            "action_timing",
                            "hard_cuts",
                        ],
                    }
                ],
                "sound_effect": "source-synchronized object sound",
                "reference_binding": "@图片1/@图片2/@图片3/@图片4",
                "must_keep_reason": "source_rhythm must_keep beat",
            }
        )
    part["speech_groups"] = []
    for index, beat_ids in enumerate(
        (("beat1", "beat2"), ("beat3", "beat4"), ("beat5", "beat6")),
        start=1,
    ):
        selected = [
            beat for beat in part["beats"] if beat["id"] in beat_ids
        ]
        part["speech_groups"].append(
            {
                "id": f"speech{index}",
                "target_start": selected[0]["target_start"],
                "target_end": selected[-1]["target_end"],
                "speaker_mode": script["speaker_mode"],
                "line": "".join(beat["source_line"] for beat in selected),
                "beat_ids": list(beat_ids),
                "line_edits": [],
            }
        )
    part["execution_blocks"] = [
        {"id": f"block{index}", "beat_ids": list(beat_ids)}
        for index, beat_ids in enumerate(
            (("beat1", "beat2"), ("beat3", "beat4"), ("beat5", "beat6")),
            start=1,
        )
    ]
    part["source_functions"] = [
        {
            "id": f"function{index}",
            "label": source_beat["visual_action"],
            "priority": "must_keep",
            "coverage": "both",
            "target_refs": [
                f"beat{index}",
                f"speech{((index - 1) // 2) + 1}",
            ],
        }
        for index, source_beat in enumerate(rhythm["beats"], start=1)
    ]
    plan["job"].update(
        {
            "video_path": "assets/source_video.mkv",
            "product_assets": "assets/product_reference.svg",
            "audio_assets": "assets/source_audio.wav",
            "output_dir": f"output/{FIXED_JOB_ID}",
        }
    )
    write_json(plan_path, plan)
    run_checked(
        [
            sys.executable,
            str(production_adapter),
            "pre_seedance_pack",
            "render",
            "--root",
            str(root),
            "--job-id",
            FIXED_JOB_ID,
        ],
        cwd=root,
    )
    run_checked(
        [
            sys.executable,
            str(production_adapter),
            "pre_seedance_pack_qc",
            "--root",
            str(qc_root),
            "--job-id",
            FIXED_JOB_ID,
        ],
        cwd=qc_root,
    )
    role_table_path = job_dir / "seedance" / "seedance_素材角色表.md"
    write_text(
        role_table_path,
        role_table_path.read_text(encoding="utf-8").replace(
            f"{job_dir}/",
            "job_root://",
        ),
    )

    request_path = (
        job_dir / "seedance" / "requests" / "part1_request_prepared.json"
    )
    prompt_path = job_dir / "seedance" / "seedance_part1_prompt.txt"
    audio_qc_path = (
        job_dir
        / "seedance"
        / "requests"
        / "final_upload_audio_duration_qc.json"
    )
    request_qc_path = (
        job_dir / "seedance" / "requests" / "request_qc.json"
    )
    handoff_path = job_dir / "seedance" / "handoff_mode.json"
    qc_bundle_path = (
        job_dir / "checks" / "pre_seedance_pack_qc_bundle.json"
    )
    qc_bundle = read_json(qc_bundle_path)
    if qc_bundle.get("overall") != "PASS":
        raise ParityStop(
            "actual_pre_seedance_failed",
            json.dumps(qc_bundle, ensure_ascii=False),
        )
    prompt = prompt_path.read_text(encoding="utf-8").rstrip("\n")
    rendered_plan = read_json(plan_path)
    rendered_plan_projection = copy.deepcopy(rendered_plan)
    for field in ("video_path", "product_assets", "audio_assets"):
        value = rendered_plan_projection.get("job", {}).get(field)
        if isinstance(value, str):
            rendered_plan_projection["job"][field] = (
                normalize_fixture_reference(
                    value,
                    fixture_root=fixture_root,
                    workspace=Path(execution["layout_root"]),
                )
            )
    rendered_plan_projection["job"]["output_dir"] = "job_root://"
    line_edits = [
        edit
        for item in rendered_plan["parts"]
        for group in item["speech_groups"]
        for edit in group.get("line_edits", [])
    ]
    visual_edits = [
        edit
        for item in rendered_plan["parts"]
        for beat in item["beats"]
        for edit in beat.get("visual_edits", [])
    ]
    web_root = job_dir / "seedance_web_final"
    web_contents = [
        {
            "path": path.relative_to(job_dir).as_posix(),
            "sha256": sha256_file(path),
        }
        for path in sorted(web_root.rglob("*"))
        if path.is_file()
    ]
    artifacts = {
        "director_plan": rendered_plan_projection,
        "source_script_fidelity": (
            job_dir / "voiceover" / "source_script_fidelity.md"
        ).read_text(encoding="utf-8").rstrip("\n"),
        "line_edits": line_edits,
        "visual_edits": visual_edits,
        "audio_boundary": read_json(audio_qc_path),
        "reference_roles_and_order": (
            job_dir / "seedance" / "seedance_素材角色表.md"
        )
        .read_text(encoding="utf-8")
        .replace(
            "job_root://",
            "workspace://actual-pre-seedance/output/job-001/",
        )
        .replace(str(root), "workspace://actual-pre-seedance")
        .rstrip("\n"),
        "prompt": prompt,
        "provider_request": {
            "request": read_json(request_path),
            "request_body_qc": read_json(request_qc_path),
        },
        "pre_seedance_handoff": {
            "handoff": read_json(handoff_path),
            "web_contents": web_contents,
        },
    }
    evidence = [
        plan_path,
        job_dir / "voiceover" / "source_script_fidelity.md",
        job_dir / "audio-boundary" / "part1_reference_audio.mp3",
        prompt_path,
        request_path,
        request_qc_path,
        audio_qc_path,
        handoff_path,
    ]
    return (
        artifacts,
        evidence,
        {
            **stage_execution,
            "image_request": image_request,
            "image_response": image_response,
            "image_recorder_metrics": image_recorder_metrics,
        },
    )


def prepare_source_blueprint_gate_evidence(
    *,
    fixture_root: Path,
    workspace: Path,
    rhythm: dict[str, Any],
    pack_execution: dict[str, Any],
    sealed_verdicts: dict[str, Any],
) -> list[Path]:
    root = Path(pack_execution["adapter_root"])
    job_dir = Path(pack_execution["job_dir"])
    adapter = Path(pack_execution["production_adapter"])
    checks = job_dir / "checks"
    checks.mkdir(parents=True, exist_ok=True)

    understanding_source = (
        workspace / "actual-source-understanding" / "video_understanding"
    )
    understanding_target = (
        job_dir / "剧情分析" / "video_understanding"
    )
    if understanding_target.exists():
        shutil.rmtree(understanding_target)
    shutil.copytree(understanding_source, understanding_target)
    for understanding_json in understanding_target.rglob("*.json"):
        write_json(
            understanding_json,
            normalize_declared_roots(
                read_json(understanding_json),
                fixture_root=fixture_root,
                workspace=workspace,
                job_root=job_dir,
            ),
        )

    rhythm_path = job_dir / "剧情分析" / "source_rhythm.json"
    write_json(rhythm_path, rhythm)
    run_checked(
        [
            sys.executable,
            str(adapter),
            "source_rhythm_qc",
            "--source-rhythm",
            str(rhythm_path),
            "--json-out",
            str(checks / "source_rhythm_qc.json"),
            "--md-out",
            str(checks / "source_rhythm_qc.md"),
        ],
        cwd=root,
    )

    sealed_review = (
        sealed_verdicts["stages"]["source_blueprint"][
            "source_rhythm_visual_review"
        ]
    )
    beat_reasons = sealed_review.get("beats") or {}
    if sorted(beat_reasons) != sorted(
        beat["id"] for beat in rhythm["beats"]
    ):
        raise ParityStop(
            "sealed_checker_mismatch",
            "source rhythm beat verdict coverage changed",
        )
    for beat in rhythm["beats"]:
        sealed_beat = beat_reasons[beat["id"]]
        frame_paths = [
            checked_fixture_path(fixture_root, relative)
            for relative in beat["evidence_frame_refs"]
        ]
        if sealed_beat.get("evidence_sha256") != [
            sha256_file(path) for path in frame_paths
        ]:
            raise ParityStop(
                "sealed_checker_mismatch",
                f"{beat['id']} source frame evidence changed",
            )
    visual_review_path = checks / "source_rhythm_visual_review.json"
    write_json(
        visual_review_path,
        {
            "reviewer": sealed_verdicts["reviewer"],
            "fixture_id": sealed_verdicts["fixture_id"],
            "beats": [
                {
                    "beat_id": beat["id"],
                    "reviewed_frame_refs": beat["evidence_frame_refs"],
                    "description_matches_evidence": True,
                    "action_type_matches_evidence": True,
                    "notes": beat_reasons[beat["id"]]["reason"],
                }
                for beat in rhythm["beats"]
            ],
        },
    )
    run_checked(
        [
            sys.executable,
            str(adapter),
            "source_rhythm_visual_review_qc",
            "--root",
            str(fixture_root),
            "--source-rhythm",
            str(rhythm_path),
            "--review",
            str(visual_review_path),
            "--out-json",
            str(checks / "source_rhythm_visual_review_qc.json"),
            "--out-md",
            str(checks / "source_rhythm_visual_review_qc.md"),
        ],
        cwd=root,
    )
    storyboard_dir = job_dir / "storyboard_source_refs"
    run_checked(
        [
            sys.executable,
            str(adapter),
            "build_part_storyboards",
            "--input",
            str(fixture_root / "core" / "source_4s.mkv"),
            "--output",
            str(storyboard_dir),
            "--total-frames",
            "6",
            "--groups",
            "1",
            "--source-rhythm",
            str(rhythm_path),
        ],
        cwd=root,
    )
    storyboard_manifest_path = (
        storyboard_dir / "source_storyboard_manifest.json"
    )
    write_json(
        storyboard_manifest_path,
        normalize_declared_roots(
            read_json(storyboard_manifest_path),
            fixture_root=fixture_root,
            workspace=workspace,
            job_root=job_dir,
        ),
    )
    report_path = checks / "source_blueprint_report.json"
    write_json(
        report_path,
        {
            "overall": "PASS",
            "fixture_mode": "sealed_zero_submit",
            "production_tools": [
                "video_understanding.understand_video",
                "source_rhythm_qc.py",
                "source_rhythm_visual_review_qc.py",
                "build_part_storyboards.py",
            ],
            "semantic_verdict_fixture": sealed_verdicts["fixture_id"],
        },
    )
    return [
        rhythm_path,
        checks / "source_rhythm_qc.json",
        visual_review_path,
        checks / "source_rhythm_visual_review_qc.json",
        storyboard_dir / "source_storyboard_manifest.json",
        report_path,
    ]


def run_actual_video_understanding(
    *,
    engine_root: Path,
    fixture_root: Path,
    workspace: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    sealed_httpx = types.ModuleType("httpx")

    class TransportError(Exception):
        pass

    class Response:
        def __init__(self, status_code: int, *, json: Any):
            self.status_code = status_code
            self._json = copy.deepcopy(json)
            self.text = json_module.dumps(
                json,
                ensure_ascii=False,
            )

        def json(self) -> Any:
            return copy.deepcopy(self._json)

    class MockTransport:
        def __init__(self, handler: Any):
            self.handler = handler

    class Client:
        def __init__(
            self,
            *,
            transport: Any = None,
            timeout: float | None = None,
        ):
            del timeout
            self.transport = transport

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *_args: Any) -> None:
            self.close()

        def close(self) -> None:
            return None

        def post(
            self,
            url: str,
            *,
            headers: dict[str, str],
            json: Any,
        ) -> Any:
            if self.transport is None:
                raise TransportError(
                    "sealed parity client has no network transport",
                )
            request = types.SimpleNamespace(
                method="POST",
                url=url,
                headers=dict(headers),
                content=json_module.dumps(
                    json,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8"),
            )
            return self.transport.handler(request)

    json_module = json
    sealed_httpx.TransportError = TransportError
    sealed_httpx.Response = Response
    sealed_httpx.MockTransport = MockTransport
    sealed_httpx.Client = Client
    prior_httpx = sys.modules.get("httpx")
    sys.modules["httpx"] = sealed_httpx
    try:
        module = load_module(
            engine_root / "tools" / "video_understanding.py",
            "parity_video_understanding",
        )
    finally:
        if prior_httpx is None:
            sys.modules.pop("httpx", None)
        else:
            sys.modules["httpx"] = prior_httpx
    contract = read_json(
        fixture_root / "provider" / "wujie_request_contract.json"
    )
    frozen_response = read_json(
        fixture_root / "provider" / "wujie_response.json"
    )
    matched = {"count": 0}

    def handler(request: Any) -> Any:
        try:
            payload = json.loads(request.content.decode("utf-8"))
            content = payload["messages"][0]["content"]
            video_item, prompt_item = content
            data_url = video_item["video_url"]["url"]
            encoded = data_url.split(";base64,", 1)[1]
            submitted = base64.b64decode(encoded, validate=True)
            actual = {
                "method": request.method,
                "endpoint": str(request.url),
                "authorization": request.headers.get("Authorization"),
                "payload_keys": sorted(payload),
                "model": payload.get("model"),
                "response_format": payload.get("response_format"),
                "stream": payload.get("stream"),
                "content_types": [item.get("type") for item in content],
                "sampling_fps": video_item["video_url"]["fps"],
                "submitted_video_sha256": sha256_bytes(submitted),
                "submitted_video_size_bytes": len(submitted),
                "prompt_sha256": sha256_bytes(
                    prompt_item["text"].encode("utf-8")
                ),
            }
        except Exception as exc:
            raise ParityStop(
                "unmatched_request",
                f"invalid Wujie fixture request: {exc}",
            ) from exc
        expected = {
            "method": "POST",
            "endpoint": contract["endpoint"],
            "authorization": "Bearer fixture-offline-key",
            "payload_keys": [
                "messages",
                "model",
                "response_format",
                "stream",
            ],
            "model": contract["model"],
            "response_format": {"type": "json_object"},
            "stream": False,
            "content_types": ["video_url", "text"],
            "sampling_fps": contract["sampling_fps"],
            "submitted_video_sha256": contract[
                "submitted_video_sha256"
            ],
            "submitted_video_size_bytes": contract[
                "submitted_video_size_bytes"
            ],
            "prompt_sha256": contract["prompt_sha256"],
        }
        if actual != expected or matched["count"] != 0:
            raise ParityStop(
                "unmatched_request",
                json.dumps(
                    {"expected": expected, "actual": actual},
                    ensure_ascii=False,
                ),
            )
        matched["count"] += 1
        return module.httpx.Response(
            contract["http_status"],
            json=frozen_response,
        )

    out_dir = (
        workspace / "actual-source-understanding" / "video_understanding"
    )
    prior_key = os.environ.get("HIGRESS_API_KEY")
    prior_time_module = module.time
    perf_counter_values = iter((100.0, 100.01, 100.011, 100.05))
    os.environ["HIGRESS_API_KEY"] = "fixture-offline-key"
    module.time = types.SimpleNamespace(
        perf_counter=lambda: next(perf_counter_values)
    )
    try:
        with module.httpx.Client(
            transport=module.httpx.MockTransport(handler)
        ) as client:
            result = module.understand_video(
                fixture_root / "core" / "source_4s.mkv",
                out_dir,
                config_path=(
                    engine_root
                    / "rules"
                    / "VIDEO_UNDERSTANDING_MODEL.json"
                ),
                env_file=workspace / "missing-provider-env",
                client=client,
                mode="full",
            )
    finally:
        module.time = prior_time_module
        if prior_key is None:
            os.environ.pop("HIGRESS_API_KEY", None)
        else:
            os.environ["HIGRESS_API_KEY"] = prior_key
    if matched["count"] != 1:
        raise ParityStop(
            "unmatched_request",
            f"expected one matched Wujie request, got {matched['count']}",
        )
    submitted = result.get("submitted_video") or {}
    projection = {
        "provider": result.get("provider"),
        "model": result.get("model"),
        "endpoint": result.get("endpoint"),
        "http_status": contract["http_status"],
        "analysis_mode": result.get("analysis_mode"),
        "sampling_fps": result.get("sampling_fps"),
        "source_sha256": result.get("source_sha256"),
        "submitted_video": {
            "used_proxy": submitted.get("used_proxy"),
            "sha256": submitted.get("sha256"),
            "size_bytes": submitted.get("size_bytes"),
        },
        "prompt_sha256": contract["prompt_sha256"],
        "matched_offline_request_count": matched["count"],
        "real_submit": False,
        "network_access": False,
    }
    expected_projection = {
        "provider": contract["provider"],
        "model": contract["model"],
        "endpoint": contract["endpoint"],
        "http_status": contract["http_status"],
        "analysis_mode": contract["analysis_mode"],
        "sampling_fps": contract["sampling_fps"],
        "source_sha256": contract["source_sha256"],
        "submitted_video": {
            "used_proxy": True,
            "sha256": contract["submitted_video_sha256"],
            "size_bytes": contract["submitted_video_size_bytes"],
        },
        "prompt_sha256": contract["prompt_sha256"],
        "matched_offline_request_count": 1,
        "real_submit": False,
        "network_access": False,
    }
    if projection != expected_projection:
        raise ParityStop(
            "provider_response_mismatch",
            json.dumps(
                {
                    "expected": expected_projection,
                    "actual": projection,
                },
                ensure_ascii=False,
            ),
        )
    return result["analysis"], projection


def source_rhythm(
    provider_result: dict[str, Any],
    script: dict[str, Any],
    understanding_route: dict[str, Any],
    source_sha256: str,
) -> dict[str, Any]:
    ordered = provider_result.get("ordered_beats")
    if ordered != ["open", "texture-proof", "single-wipe"]:
        raise ParityStop("provider_response_mismatch", "ordered source beats changed")
    timings = [
        (0.0, 0.5),
        (0.5, 1.0),
        (1.0, 1.75),
        (1.75, 2.5),
        (2.5, 3.25),
        (3.25, 4.0),
    ]
    line_spans = [(0, 4), (4, 8), (9, 17), (17, 26), (27, 31), (31, 41)]
    actions = [
        "open-entry",
        "open-proof",
        "texture-entry",
        "texture-proof",
        "single-wipe-entry",
        "single-wipe-proof",
    ]
    line = script["lines"][0]["text"]
    evidence_indices = [
        (1, 2, 3),
        (3, 4, 5),
        (6, 8, 9),
        (9, 11, 13),
        (13, 15, 17),
        (17, 18, 20),
    ]
    beats = []
    for index, (name, timing, line_span) in enumerate(
        zip(actions, timings, line_spans),
        start=1,
    ):
        beats.append(
            {
                "id": f"B{index:02d}",
                "source_start": timing[0],
                "source_end": timing[1],
                "asr_span": {
                    "start": line_span[0],
                    "end": line_span[1],
                },
                "confirmed_source_line": line[line_span[0]:line_span[1]],
                "scene": "tabletop",
                "camera": "locked",
                "framing": "macro" if index == 2 else "close-up",
                "visual_action_type": "object_manipulation",
                "visual_action": name,
                "emphasis_tokens": (
                    script["lines"][0]["emphasis"] if index == 2 else []
                ),
                "pause_after_seconds": 0.0,
                "action_peak_times": [
                    min(3.5, round(sum(timing) / 2, 3))
                ],
                "emotion_function": "source-locked product proof",
                "rhythm_class": "rapid_hook" if index == 1 else "normal",
                "evidence_frame_refs": [
                    f"core/source_frames/frame_{frame:03d}.png"
                    for frame in evidence_indices[index - 1]
                ],
                "entry_transition": (
                    "source_start"
                    if index == 1
                    else "hard_cut"
                    if index in {3, 5}
                    else "continuous"
                ),
                "exit_transition": (
                    "source_end"
                    if index == len(actions)
                    else "hard_cut"
                    if index in {2, 4}
                    else "continuous"
                ),
                "speaker_mode": script["speaker_mode"],
                "replication_priority": "must_keep",
            }
        )
    return {
        "schema_version": 3,
        "source_sha256": source_sha256,
        "duration": 4.0,
        "actual_cut_points": [{"time": 1.0}, {"time": 2.5}],
        "source_evidence": {
            "asr_text": line,
            "asr_span_basis": "raw_text",
            "subtitle_observations": [],
        },
        "replication_mode": provider_result["replication_mode"],
        "edit_scope": "necessary_only",
        "understanding_route": {
            "provider": understanding_route["provider"],
            "endpoint": understanding_route["endpoint"],
            "model": understanding_route["model"],
        },
        "beats": beats,
    }


def checker_review_text(
    *,
    stage: str,
    gate: str,
    next_status: str,
    family_results: dict[str, str],
    reasons: list[str],
    fixture_id: str,
) -> str:
    overall = (
        "PASS"
        if family_results
        and all(result == "PASS" for result in family_results.values())
        else "FAIL"
    )
    return "\n".join(
        [
            f"Gate: {gate}",
            f"Job: {FIXED_JOB_ID}",
            f"Stage: {stage}",
            f"Input artifacts: sealed fixture {fixture_id}",
            "Checks: sealed verdict fingerprint and current risk request binding",
            f"Result: {overall}",
            f"Family results: {json.dumps(family_results, sort_keys=True)}",
            f"Outcome type: {overall}",
            "Why not fail: the independent fixture verdict exactly matches every requested fingerprint",
            f"Reason: {'; '.join(reasons)}",
            f"Failed item: {'none' if overall == 'PASS' else 'sealed checker family'}",
            f"Failure type: {'none' if overall == 'PASS' else 'semantic_mismatch'}",
            "Retry variable: none",
            "Locked variables: fixture bytes, ordered references, approval, and QC thresholds",
            f"Next status: {next_status}",
            "Needs user confirmation: false",
        ]
    )


def runner_command(
    engine_root: Path,
    execution: dict[str, Any],
) -> list[str]:
    command = [
        sys.executable,
        str(engine_root / "tools" / "run_next_loop_round.py"),
    ]
    context = execution.get("execution_context")
    production_root = execution.get("production_root")
    if context:
        command.extend(["--execution-context", str(context)])
    elif production_root:
        command.extend(
            [
                "--root",
                str(production_root),
                "--job-id",
                FIXED_JOB_ID,
            ]
        )
    else:
        command.extend(
            ["--root", str(execution["state_root"]), "--job-id", FIXED_JOB_ID]
        )
    return command


def bind_production_checker_and_advance(
    *,
    engine_root: Path,
    fixture_root: Path,
    workspace: Path,
    execution: dict[str, Any],
    stage: str,
    stage_rule: dict[str, Any],
    sealed_verdicts: dict[str, Any],
    execution_order: list[str],
) -> dict[str, Any]:
    state_root = Path(execution["state_root"])
    gate_root = state_root
    job_dir = Path(execution["job_work"])
    checks = job_dir / "checks"
    review_path = checks / f"{stage}_gate_review.md"
    request_path = checks / f"{stage}_semantic_review_request.json"
    ledger_path = checks / f"{stage}_qc_risk_ledger.json"

    run_checked(runner_command(engine_root, execution), cwd=state_root)
    first_ledger = subprocess.run(
        [
            sys.executable,
            str(engine_root / "tools" / "qc_risk_ledger.py"),
            "--root",
            str(gate_root),
            "--job-id",
            FIXED_JOB_ID,
            "--stage",
            stage,
        ],
        cwd=gate_root,
        text=True,
        capture_output=True,
    )
    if first_ledger.returncode not in {0, 1, 2} or not request_path.is_file():
        raise ParityStop(
            "production_gate_failed",
            f"{stage} did not emit one semantic checker request: "
            f"{first_ledger.stderr or first_ledger.stdout}",
        )
    request = read_json(request_path)
    if (
        request.get("required") is not True
        or request.get("invocation_count") != 1
    ):
        raise ParityStop(
            "production_gate_failed",
            f"{stage} semantic checker was not requested exactly once",
        )
    execution_order.append("qc_risk_ledger")
    actual_families = {
        item["name"]: item["fingerprint_hash"]
        for item in request.get("families") or []
    }
    expected_families = (
        sealed_verdicts["stages"][stage].get("production_families") or {}
    )
    if set(actual_families) != set(expected_families):
        raise ParityStop(
            "sealed_checker_mismatch",
            f"{stage} production families changed",
            stage=stage,
            artifact_family="production_checker_families",
            expected=sorted(expected_families),
            actual=sorted(actual_families),
        )
    results = {}
    reasons = []
    for name, actual_fingerprint in actual_families.items():
        sealed = expected_families[name]
        if sealed.get("fingerprint_sha256") != actual_fingerprint:
            raise ParityStop(
                "sealed_checker_mismatch",
                (
                    f"{stage}/{name} production fingerprint changed: "
                    f"expected={sealed.get('fingerprint_sha256')} "
                    f"actual={actual_fingerprint}"
                ),
                stage=stage,
                artifact_family=name,
                expected=sealed.get("fingerprint_sha256"),
                actual=actual_fingerprint,
            )
        results[name] = str(sealed.get("result") or "")
        reasons.append(str(sealed.get("reason") or ""))
    write_text(
        review_path,
        checker_review_text(
            stage=stage,
            gate=stage_rule["gate"],
            next_status=stage_rule["next_expected"],
            family_results=results,
            reasons=reasons,
            fixture_id=str(sealed_verdicts["fixture_id"]),
        ),
    )
    checker_json = checks / f"{stage}_gate_review_qc.json"
    run_checked(
        [
            sys.executable,
            str(engine_root / "tools" / "checker_review_qc.py"),
            "--root",
            str(gate_root),
            "--review",
            str(review_path),
            "--gate",
            str(engine_root / stage_rule["gate"]),
            "--risk-request",
            str(request_path),
            "--out-json",
            str(checker_json),
            "--out-md",
            str(checks / f"{stage}_gate_review_qc.md"),
        ],
        cwd=gate_root,
    )
    execution_order.append("checker")
    run_checked(
        [
            sys.executable,
            str(engine_root / "tools" / "qc_risk_ledger.py"),
            "--root",
            str(gate_root),
            "--job-id",
            FIXED_JOB_ID,
            "--stage",
            stage,
            "--artifact",
            str(review_path),
        ],
        cwd=gate_root,
    )
    ledger = read_json(ledger_path)
    if ledger.get("overall") != "PASS":
        raise ParityStop(
            "production_gate_failed",
            f"{stage} risk ledger did not pass after sealed checker binding",
        )
    execution_order.append("gate")
    transition = run_checked(
        [
            *runner_command(engine_root, execution),
            "--record-gate-result",
            "PASS",
            "--outcome-type",
            "PASS",
            "--artifact",
            str(review_path),
            "--spent-gpt-image-runs",
            "0",
            "--apply-transition",
        ],
        cwd=state_root,
    )
    row = read_job_row(Path(execution["jobs_path"]), FIXED_JOB_ID)
    if row["status"] != stage_rule["next_expected"]:
        raise ParityStop(
            "production_gate_failed",
            f"{stage} transitioned to {row['status']!r}",
        )
    bound_checker = read_json(checker_json)
    checker_binding = bound_checker.get("qc_risk_review") or {}
    risk_ledger = {}
    for name, family in ledger["families"].items():
        fingerprint_hash = family["fingerprint_hash"]
        if family["kind"] == "deterministic":
            evidence_projection = []
            for evidence in family.get("evidence") or []:
                evidence_path = Path(str(evidence.get("path") or ""))
                if not evidence_path.is_absolute():
                    evidence_path = gate_root / evidence_path
                if (
                    not path_within(evidence_path, workspace)
                    or not evidence_path.is_file()
                ):
                    raise ParityStop(
                        "production_gate_failed",
                        f"{stage}/{name} deterministic evidence is unavailable",
                    )
                evidence_projection.append(
                    {
                        "name": evidence.get("name"),
                        "status": evidence.get("status"),
                        "sha256": sha256_bytes(
                            canonical_artifact_bytes(
                                evidence_path,
                                fixture_root=fixture_root,
                                workspace=workspace,
                                job_root=job_dir,
                            )
                        ),
                    }
                )
            fingerprint_hash = sha256_bytes(
                canonical_bytes(
                    {
                        "kind": family["kind"],
                        "scope": family.get("scope"),
                        "status": family["status"],
                        "reason": family.get("reason"),
                        "evidence": evidence_projection,
                        "defect_scopes": family.get("defect_scopes"),
                        "retry_scope": family.get("retry_scope"),
                    }
                )
            )
        risk_ledger[name] = {
            "kind": family["kind"],
            "status": family["status"],
            "fingerprint_hash": fingerprint_hash,
        }
    return {
        "risk_ledger": risk_ledger,
        "request_id": request["request_id"],
        "checker_invocation_count": request["invocation_count"],
        "checker_qc_sha256": sha256_bytes(
            canonical_bytes(
                {
                    "overall": bound_checker.get("overall"),
                    "request_id": checker_binding.get("request_id"),
                    "invocation_count": checker_binding.get(
                        "invocation_count"
                    ),
                    "family_fingerprints": checker_binding.get(
                        "family_fingerprints"
                    ),
                    "family_results": checker_binding.get(
                        "family_results"
                    ),
                }
            )
        ),
        "checker_family_results": checker_binding.get("family_results"),
        "transition_status": row["status"],
        "transition_output": transition.stdout,
    }


def run_production_stage_audit(
    *,
    engine_root: Path,
    workspace: Path,
    fixture_root: Path,
    execution: dict[str, Any],
    stage: str,
    stage_rule: dict[str, Any],
    maker_artifact_paths: list[Path],
    sealed_verdicts: dict[str, Any],
) -> dict[str, Any]:
    worker_resource = STAGE_WORKER_RESOURCES[stage]
    worker_path = engine_root / worker_resource
    gate_path = engine_root / stage_rule["gate"]
    if not worker_path.is_file() or not gate_path.is_file():
        raise ParityStop(
            "missing_engine_resource",
            f"{stage}: worker={worker_path}, gate={gate_path}",
        )
    maker_artifacts = []
    for path in maker_artifact_paths:
        if not path_within(path, workspace) or not path.is_file():
            raise ParityStop("maker_artifact_missing", f"{stage}: {path}")
        artifact_bytes = canonical_artifact_bytes(
            path,
            fixture_root=fixture_root,
            workspace=workspace,
            job_root=Path(execution["job_work"]),
        )
        maker_artifacts.append(
            {
                "path": f"workspace://{path.relative_to(workspace).as_posix()}",
                "sha256": sha256_bytes(artifact_bytes),
                "bytes": len(artifact_bytes),
            }
        )
    if not maker_artifacts:
        raise ParityStop("maker_artifact_missing", stage)

    execution_order = ["maker"]
    production = bind_production_checker_and_advance(
        engine_root=engine_root,
        fixture_root=fixture_root,
        workspace=workspace,
        execution=execution,
        stage=stage,
        stage_rule=stage_rule,
        sealed_verdicts=sealed_verdicts,
        execution_order=execution_order,
    )
    audit = {
        "stage": stage,
        "rule_id": stage_rule["id"],
        "status_before": {
            "source_blueprint": "pending",
            "image_batch_qc": "storyboard_passed",
            "pre_seedance_pack": "image_qc_passed",
        }[stage],
        "status_after": production["transition_status"],
        "worker": stage_rule["worker"],
        "worker_resource": worker_resource,
        "worker_sha256": sha256_file(worker_path),
        "maker_artifacts": maker_artifacts,
        "gate": stage_rule["gate"],
        "gate_sha256": sha256_file(gate_path),
        "execution_order": execution_order,
        "checker_request_id": production["request_id"],
        "checker_invocation_count": production["checker_invocation_count"],
        "checker_family_results": production["checker_family_results"],
        "checker_qc_sha256": production["checker_qc_sha256"],
        "qc_risk_families": production["risk_ledger"],
        "gate_conclusion": "PASS",
    }
    stage_root = workspace / "qc" / stage
    write_json(stage_root / "stage_audit.json", audit)
    return audit


MULTI_PERSON_HOST_BOX = (8, 45, 43, 145)
MULTI_PERSON_SUPPORT_BOX = (62, 45, 97, 145)


def render_multi_person_storyboard_fixture(
    path: Path,
    *,
    part_id: str,
    source_variant: bool,
) -> None:
    from PIL import Image, ImageDraw

    image = Image.new(
        "RGB",
        (400, 600),
        "#e7f0ee" if source_variant else "#edf6f4",
    )
    draw = ImageDraw.Draw(image)
    for index in range(12):
        column = index % 4
        row = index // 4
        left = column * 100
        top = row * 200
        draw.rectangle(
            (left, top, left + 99, top + 199),
            outline="#26343b",
            width=2,
        )
        draw.rectangle(
            (left + 1, top + 1, left + 98, top + 29),
            fill="#f5f8f7",
        )
        draw.text(
            (left + 5, top + 8),
            f"Shot {index + 1:02d}",
            fill="#1f2b31",
        )
        host_left = left + 8
        host_top = top + 45
        draw.rectangle(
            (host_left + 4, host_top, host_left + 31, host_top + 18),
            fill="#2f3742",
        )
        draw.rectangle(
            (
                host_left + 8,
                host_top + 18,
                host_left + 27,
                host_top + 45,
            ),
            fill="#f1b49f",
        )
        draw.rectangle(
            (
                host_left,
                host_top + 45,
                host_left + 35,
                host_top + 100,
            ),
            fill="#517b6f",
        )
        if part_id == "part1" and index < 4:
            support_left = left + 62
            support_top = top + 45
            draw.rectangle(
                (
                    support_left + 2,
                    support_top,
                    support_left + 33,
                    support_top + 16,
                ),
                fill="#6a3f2a",
            )
            draw.rectangle(
                (
                    support_left + 7,
                    support_top + 16,
                    support_left + 28,
                    support_top + 45,
                ),
                fill="#c98e70",
            )
            draw.rectangle(
                (
                    support_left,
                    support_top + 45,
                    support_left + 35,
                    support_top + 100,
                ),
                fill="#365a80",
            )
        else:
            product_left = left + (58 if part_id == "part1" else 52)
            product_top = top + 76 + (index % 3) * 3
            draw.rectangle(
                (
                    product_left,
                    product_top,
                    product_left + 32,
                    product_top + 52,
                ),
                fill="#3d8a72",
                outline="#255b4c",
            )
            draw.rectangle(
                (
                    product_left + 6,
                    product_top + 9,
                    product_left + 26,
                    product_top + 30,
                ),
                fill="#f7fbfa",
            )
        if part_id == "part2":
            draw.line(
                (
                    left + 43,
                    top + 151,
                    left + 82,
                    top + 151 - (index % 4) * 4,
                ),
                fill="#b16249",
                width=4,
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG")


def derive_storyboard_identity_reference(
    storyboard: Path,
    crop_box: tuple[int, int, int, int],
    output: Path,
) -> None:
    from PIL import Image

    with Image.open(storyboard) as opened:
        crop = opened.convert("RGB").crop(crop_box)
        resampling = getattr(Image, "Resampling", Image).NEAREST
        derived = crop.resize((200, 240), resample=resampling)
    output.parent.mkdir(parents=True, exist_ok=True)
    derived.save(output, format="PNG")


def storyboard_identity_pixel_projection(
    *,
    part1: Path,
    part2: Path,
    host_ref: Path,
    support_ref: Path,
) -> dict[str, Any]:
    from PIL import Image

    with Image.open(part1) as board:
        board_rgb = board.convert("RGB")
        resampling = getattr(Image, "Resampling", Image).NEAREST
        host_expected = board_rgb.crop(
            MULTI_PERSON_HOST_BOX
        ).resize((200, 240), resample=resampling)
        support_expected = board_rgb.crop(
            MULTI_PERSON_SUPPORT_BOX
        ).resize((200, 240), resample=resampling)
    with Image.open(host_ref) as opened:
        host_actual = opened.convert("RGB")
    with Image.open(support_ref) as opened:
        support_actual = opened.convert("RGB")
    projection = {
        "part1_sha256": sha256_file(part1),
        "part2_sha256": sha256_file(part2),
        "host_ref_sha256": sha256_file(host_ref),
        "support_ref_sha256": sha256_file(support_ref),
        "part_content_distinct": sha256_file(part1) != sha256_file(part2),
        "role_identity_content_distinct": (
            host_actual.tobytes() != support_actual.tobytes()
        ),
        "host_ref_derived_from_passed_part1": (
            host_actual.tobytes() == host_expected.tobytes()
        ),
        "support_ref_derived_from_passed_part1": (
            support_actual.tobytes() == support_expected.tobytes()
        ),
        "part1_role_region_content_distinct": (
            host_expected.tobytes() != support_expected.tobytes()
        ),
    }
    if not all(
        projection[name]
        for name in (
            "part_content_distinct",
            "role_identity_content_distinct",
            "host_ref_derived_from_passed_part1",
            "support_ref_derived_from_passed_part1",
            "part1_role_region_content_distinct",
        )
    ):
        raise ParityStop(
            "fixture_branch_failed",
            "multi-person storyboard pixel bindings are invalid",
            stage="branch_matrix",
            artifact_family="storyboard-derived-identity",
            expected={
                "part_content_distinct": True,
                "role_identity_content_distinct": True,
                "host_ref_derived_from_passed_part1": True,
                "support_ref_derived_from_passed_part1": True,
                "part1_role_region_content_distinct": True,
            },
            actual=projection,
        )
    return projection


def run_storyboard_derived_branch_probe(
    *,
    engine_root: Path,
    workspace: Path,
    visual_manifest_qc_path: Path,
) -> dict[str, Any]:
    source_job_dir = visual_manifest_qc_path.parents[1]
    if not source_job_dir.is_dir():
        raise ParityStop(
            "fixture_branch_failed",
            f"missing source job for identity branch: {source_job_dir}",
        )
    branch_root = (
        workspace / "branches" / "storyboard-derived-multi-person"
    )
    branch_job_dir = branch_root / "output" / FIXED_JOB_ID
    branch_job_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_job_dir, branch_job_dir)

    visual_path = (
        branch_job_dir
        / "visual-assets"
        / "approved_visual_manifest.json"
    )
    visual = read_json(visual_path)
    product_manifest_path = checked_fixture_path(
        branch_root,
        str(visual.get("product_group_manifest") or ""),
    )
    product_manifest = read_json(product_manifest_path)
    with (branch_root / "jobs.csv").open(
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:
        fieldnames = [
            "id",
            "product_name",
            "product_assets",
            "person_assets",
            "notes",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(
            {
                "id": FIXED_JOB_ID,
                "product_name": product_manifest["product_name"],
                "product_assets": product_manifest["source_assets"],
                "person_assets": "storyboard_derived",
                "notes": "sealed multi-person branch probe",
            }
        )

    storyboards = visual.get("part_storyboards") or {}
    part1 = copy.deepcopy(storyboards.get("part1") or {})
    if not part1:
        raise ParityStop(
            "fixture_branch_failed",
            "identity branch source has no part1 storyboard",
        )
    part1_candidate = checked_fixture_path(
        branch_root,
        str(part1.get("path") or ""),
    )
    part1_source = checked_fixture_path(
        branch_root,
        str(part1.get("source_reference") or ""),
    )
    part2_candidate = (
        branch_job_dir / "final-images" / "part2_seedance_ref.png"
    )
    part2_source = (
        branch_job_dir
        / "storyboard_source_refs"
        / "source_storyboard_part2.png"
    )
    render_multi_person_storyboard_fixture(
        part1_candidate,
        part_id="part1",
        source_variant=False,
    )
    render_multi_person_storyboard_fixture(
        part1_source,
        part_id="part1",
        source_variant=True,
    )
    render_multi_person_storyboard_fixture(
        part2_candidate,
        part_id="part2",
        source_variant=False,
    )
    render_multi_person_storyboard_fixture(
        part2_source,
        part_id="part2",
        source_variant=True,
    )
    part1_label_evidence = checked_fixture_path(
        branch_root,
        str(
            (part1.get("shot_label_metadata") or {}).get("evidence")
            or ""
        ),
    )
    part1_label = read_json(part1_label_evidence)
    part1_label["output_sha256"] = sha256_file(part1_candidate)
    part1_label["canvas"] = [400, 600]
    write_json(part1_label_evidence, part1_label)
    part1_hard_gate = checked_fixture_path(
        branch_root,
        str(part1.get("hard_gate") or ""),
    )
    write_json(
        part1_hard_gate,
        {
            "overall": "PASS",
            "candidate": part1_candidate.relative_to(
                branch_root
            ).as_posix(),
            "candidate_sha256": sha256_file(part1_candidate),
        },
    )
    part1["candidate_sha256"] = sha256_file(part1_candidate)
    part2_label_evidence = (
        branch_job_dir / "checks" / "part2_shot_label_restore.json"
    )
    part2_label = copy.deepcopy(part1_label)
    part2_label["output_sha256"] = sha256_file(part2_candidate)
    write_json(part2_label_evidence, part2_label)
    part2_hard_gate = (
        branch_job_dir / "checks" / "part2_image_hard_gate_qc.json"
    )
    write_json(
        part2_hard_gate,
        {
            "overall": "PASS",
            "candidate": part2_candidate.relative_to(
                branch_root
            ).as_posix(),
            "candidate_sha256": sha256_file(part2_candidate),
        },
    )
    part2 = copy.deepcopy(part1)
    part2.update(
        {
            "path": part2_candidate.relative_to(
                branch_root
            ).as_posix(),
            "source_reference": part2_source.relative_to(
                branch_root
            ).as_posix(),
            "candidate_sha256": sha256_file(part2_candidate),
            "hard_gate": part2_hard_gate.relative_to(
                branch_root
            ).as_posix(),
            "shot_label_metadata": {
                "type": "shot_label_metadata_only",
                "evidence": part2_label_evidence.relative_to(
                    branch_root
                ).as_posix(),
                "panel_pixels_modified": False,
            },
        }
    )
    storyboards["part1"] = part1
    storyboards["part2"] = part2
    visual["part_storyboards"] = storyboards

    identity_dir = branch_job_dir / "reusable" / "identity"
    host_ref = identity_dir / "ref.png"
    support_ref = identity_dir / "support.png"
    derive_storyboard_identity_reference(
        part1_candidate,
        MULTI_PERSON_HOST_BOX,
        host_ref,
    )
    derive_storyboard_identity_reference(
        part1_candidate,
        MULTI_PERSON_SUPPORT_BOX,
        support_ref,
    )
    pixel_projection = storyboard_identity_pixel_projection(
        part1=part1_candidate,
        part2=part2_candidate,
        host_ref=host_ref,
        support_ref=support_ref,
    )
    host_manifest_path = identity_dir / "host_manifest.json"
    host_manifest = read_json(host_manifest_path)
    host_manifest.update(
        {
            "origin": "storyboard_derived",
            "source_job_id": FIXED_JOB_ID,
            "source_part": "part1",
            "source_storyboard": part1_candidate.relative_to(
                branch_root
            ).as_posix(),
            "presenter_gender": "female",
            "identity_ref": "ref.png",
        }
    )
    write_json(host_manifest_path, host_manifest)
    support_manifest_path = identity_dir / "support_manifest.json"
    write_json(
        support_manifest_path,
        {
            "asset_group_type": "identity_group",
            "identity_id": "support",
            "role_id": "support",
            "origin": "storyboard_derived",
            "source_job_id": FIXED_JOB_ID,
            "source_part": "part1",
            "source_storyboard": part1_candidate.relative_to(
                branch_root
            ).as_posix(),
            "presenter_gender": "male",
            "identity_ref": "support.png",
        },
    )
    role_map_path = (
        branch_job_dir
        / "visual-assets"
        / "storyboard_derived_role_map.json"
    )
    write_json(
        role_map_path,
        {
            "job_id": FIXED_JOB_ID,
            "roles": [
                {
                    "id": "host",
                    "identity_required": True,
                    "gender": "female",
                    "parts": ["part1", "part2"],
                },
                {
                    "id": "support",
                    "identity_required": True,
                    "gender": "male",
                    "parts": ["part1"],
                },
            ],
        },
    )
    visual.update(
        {
            "person_asset_mode": "storyboard_derived",
            "role_map": role_map_path.relative_to(
                branch_root
            ).as_posix(),
            "identity_role_manifests": {
                "host": host_manifest_path.relative_to(
                    branch_root
                ).as_posix(),
                "support": support_manifest_path.relative_to(
                    branch_root
                ).as_posix(),
            },
            "part_identity_roles": {
                "part1": ["host", "support"],
                "part2": ["host"],
            },
            "part_reusable_refs": {
                "part1": {
                    "identity_host": host_ref.relative_to(
                        branch_root
                    ).as_posix(),
                    "identity_support": support_ref.relative_to(
                        branch_root
                    ).as_posix(),
                },
                "part2": {
                    "identity_host": host_ref.relative_to(
                        branch_root
                    ).as_posix(),
                },
            },
        }
    )
    write_json(visual_path, visual)

    report_path = (
        branch_job_dir
        / "checks"
        / "multi_person_visual_asset_manifest_qc.json"
    )
    run_checked(
        [
            sys.executable,
            str(engine_root / "tools" / "visual_asset_manifest_qc.py"),
            "--root",
            str(branch_root),
            "--job-id",
            FIXED_JOB_ID,
            "--stage",
            "image_batch_qc",
            "--out-json",
            str(report_path),
            "--out-md",
            str(report_path.with_suffix(".md")),
        ],
        cwd=branch_root,
    )
    report = read_json(report_path)
    checks = {
        str(item.get("name") or ""): str(item.get("status") or "")
        for item in report.get("checks") or []
        if isinstance(item, dict)
    }
    required_checks = {
        "person_asset_mode",
        "storyboard_derived_role_map",
        "storyboard_derived_roles_present",
        "storyboard_derived_host_provenance",
        "storyboard_derived_host_gender",
        "storyboard_derived_host_part_binding",
        "storyboard_derived_host_part1_ref",
        "storyboard_derived_host_part2_ref",
        "storyboard_derived_support_provenance",
        "storyboard_derived_support_gender",
        "storyboard_derived_support_part_binding",
        "storyboard_derived_support_part1_ref",
    }
    derived_refs = (
        (report.get("inputs") or {}).get("derived_identity_refs") or {}
    )
    host_part1 = (derived_refs.get("part1") or {}).get(
        "identity_host"
    )
    host_part2 = (derived_refs.get("part2") or {}).get(
        "identity_host"
    )
    support_part1 = (derived_refs.get("part1") or {}).get(
        "identity_support"
    )
    support_part2 = (derived_refs.get("part2") or {}).get(
        "identity_support"
    )
    cross_part_host_reuse = bool(
        host_part1 and host_part1 == host_part2
    )
    support_part_scope = bool(support_part1 and not support_part2)
    host_source = checked_fixture_path(
        branch_root,
        str(host_manifest.get("source_storyboard") or ""),
    )
    host_provenance = (
        host_manifest.get("origin") == "storyboard_derived"
        and host_manifest.get("source_job_id") == FIXED_JOB_ID
        and host_manifest.get("source_part") == "part1"
        and host_source.resolve() == part1_candidate.resolve()
    )
    contract_passed = (
        report.get("overall") == "PASS"
        and required_checks <= set(checks)
        and all(checks[name] == "PASS" for name in required_checks)
        and set(
            Path(value).name
            for value in (
                report.get("storyboard_derived_identity_manifests")
                or []
            )
        )
        == {"host_manifest.json", "support_manifest.json"}
        and cross_part_host_reuse
        and support_part_scope
        and host_provenance
    )
    if not contract_passed:
        raise ParityStop(
            "fixture_branch_failed",
            "production multi-person identity contract did not pass",
            stage="branch_matrix",
            artifact_family="storyboard-derived-identity",
            expected={
                "overall": "PASS",
                "roles": ["host", "support"],
                "cross_part_host_reuse": True,
                "support_part_scope": ["part1"],
            },
            actual={
                "overall": report.get("overall"),
                "failed_checks": {
                    name: checks.get(name)
                    for name in sorted(required_checks)
                    if checks.get(name) != "PASS"
                },
                "cross_part_host_reuse": cross_part_host_reuse,
                "support_part_scope": support_part_scope,
                "host_provenance": host_provenance,
            },
        )
    return {
        "protagonist_identity_source": (
            "passed_current_job_storyboard"
        ),
        "production_evidence": {
            "tool": "visual_asset_manifest_qc.py",
            "overall": report["overall"],
            "people_mode": "multi-person",
            "roles": ["host", "support"],
            "part_identity_roles": visual["part_identity_roles"],
            "cross_part_host_reuse": cross_part_host_reuse,
            "support_part_scope": ["part1"],
            "pixel_bindings": pixel_projection,
            "required_checks": {
                name: checks[name]
                for name in sorted(required_checks)
            },
            "report": report_path.relative_to(workspace).as_posix(),
        },
    }


def evaluate_branch_cases(
    *,
    engine_root: Path,
    fixture_root: Path,
    workspace: Path,
    stage_rules: dict[str, Any],
    policy: dict[str, Any],
    recorder: Any,
    request: dict[str, Any],
    fixture_suite: Any,
    sealed_verdicts: dict[str, Any],
    visual_manifest_qc_path: Path,
) -> list[dict[str, Any]]:
    branch_table = read_json(fixture_root / "branches" / "branch_table.json")
    mutations = read_json(
        fixture_root / "failures" / "single_variable_mutations.json"
    )["mutations"]
    cases = branch_table.get("cases")
    if not isinstance(cases, list):
        raise ParityStop("fixture_branch_failed", "branch cases missing")
    case_inputs = {
        str(case.get("case_id") or ""): case.get("input")
        for case in cases
    }
    if set(case_inputs) != set(REQUIRED_BRANCHES):
        raise ParityStop("fixture_branch_failed", "branch input coverage changed")
    media_expectations_path = checked_fixture_path(
        fixture_root,
        str(
            case_inputs["final-technical-qc"].get(
                "media_expectations"
            )
            or ""
        ),
    )
    finalization = read_json(media_expectations_path)

    job_intake = load_module(
        engine_root / "tools" / "job_intake.py",
        "parity_job_intake",
    )
    product_profile = load_module(
        engine_root / "tools" / "product_profile.py",
        "parity_product_profile",
    )
    finish_video = load_module(
        engine_root / "tools" / "finish_video.py",
        "parity_finish_video",
    )
    runner = load_module(
        engine_root / "tools" / "run_next_loop_round.py",
        "parity_run_next_loop_round",
    )

    def actual_route_rules(product_name: str) -> list[str]:
        profile = product_profile.build_product_profile(
            engine_root,
            {"id": FIXED_JOB_ID, "product_name": product_name},
        )
        projection = []
        for rule in profile.get("loaded_rules") or []:
            if rule == "generic:generic_product":
                projection.append("generic")
            elif str(rule).startswith("category:"):
                projection.append(rule)
        return projection

    missing_case = case_inputs["missing-required-input"]
    if missing_case != {"source_video": "missing"}:
        raise ParityStop(
            "fixture_branch_failed",
            "missing-input branch declaration changed",
        )
    missing_input = workspace / "branches" / "missing-source.mp4"
    try:
        job_intake.discover_videos("", [str(missing_input)])
    except ValueError:
        missing_actual = {
            "conclusion": "STOP",
            "machine_code": "missing_input",
            "paid_task_count": 0,
        }
    else:
        missing_actual = {
            "conclusion": "PASS",
            "machine_code": "none",
            "paid_task_count": 0,
        }

    finalization_root = workspace / "branches" / "finalization"
    finalization_root.mkdir(parents=True)
    finishing_case = case_inputs["local-finishing"]
    ordered_inputs = finishing_case.get("ordered_inputs") or []
    if ordered_inputs != finalization["finishing"]["ordered_inputs"]:
        raise ParityStop(
            "fixture_branch_failed",
            "local-finishing ordered inputs changed",
        )
    part_paths = []
    for relative in ordered_inputs:
        fixture_part = checked_fixture_path(fixture_root, relative)
        part_paths.append(fixture_part)
    finishing_root = finalization_root / "output" / FIXED_JOB_ID
    plan_path = finishing_root / "finishing" / "edit_plan.json"
    final_dir = finishing_root / "final"
    run_checked(
        [
            sys.executable,
            str(engine_root / "tools" / "finish_video.py"),
            "init",
            *[
                value
                for path in part_paths
                for value in ("--input", str(path))
            ],
            "--plan",
            str(plan_path),
            "--audio-fade-out-seconds",
            "0.1",
        ],
        cwd=finalization_root,
    )
    run_checked(
        [
            sys.executable,
            str(engine_root / "tools" / "finish_video.py"),
            "render",
            "--plan",
            str(plan_path),
            "--out-dir",
            str(final_dir),
        ],
        cwd=finalization_root,
    )
    finish_report = read_json(final_dir / "finish_report.json")
    finished_video = Path(finish_report["output"]).resolve()
    finished_frame_probe = run_checked(
        [
            "ffprobe",
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_read_frames",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(finished_video),
        ],
        cwd=finalization_root,
    )
    finished_frame_count = int(finished_frame_probe.stdout.strip())
    finished_output = finished_video.relative_to(
        finalization_root.resolve()
    ).as_posix()
    final_qc_input = checked_fixture_path(
        fixture_root,
        str(finalization["final_technical_qc"]["input"]),
    )
    final_qc_probe = finish_video.probe(final_qc_input)
    final_qc_dir = finishing_root / "checks" / "final-qc"
    run_checked(
        [
            sys.executable,
            str(engine_root / "tools" / "final_video_qc.py"),
            "--videos",
            str(final_qc_input),
            "--target-duration",
            str(
                finalization["final_technical_qc"][
                    "expected_duration_seconds"
                ]
            ),
            "--duration-tolerance",
            "0.2",
            "--out-dir",
            str(final_qc_dir),
        ],
        cwd=finalization_root,
    )
    final_qc = read_json(final_qc_dir / "final_qc.json")

    def subtitle_detection(case_id: str) -> bool:
        case_input = case_inputs[case_id]
        declared_input = str(case_input.get("input") or "")
        sealed_matches = [
            value
            for value in sealed_verdicts.get(
                "subtitle_classification",
                {},
            ).values()
            if value.get("input") == declared_input
        ]
        if len(sealed_matches) != 1:
            raise ParityStop(
                "sealed_checker_mismatch",
                f"subtitle verdict is missing for {declared_input!r}",
            )
        sealed = sealed_matches[0]
        classification = str(sealed.get("result") or "")
        if classification not in {"clean", "burned_in"}:
            raise ParityStop(
                "sealed_checker_mismatch",
                f"invalid subtitle verdict for {declared_input!r}",
            )
        sealed_input = checked_fixture_path(
            fixture_root,
            declared_input,
        )
        if sealed.get("input_sha256") != sha256_file(sealed_input):
            raise ParityStop(
                "sealed_checker_mismatch",
                f"subtitle input hash changed for {declared_input!r}",
            )
        branch_root = (
            workspace / "branches" / f"subtitle-{classification}"
        )
        job_output = branch_root / "output" / FIXED_JOB_ID
        branch_final = job_output / "final" / "final_video.mp4"
        branch_final.parent.mkdir(parents=True)
        shutil.copy2(sealed_input, branch_final)
        branch_probe = finish_video.probe(branch_final)
        evidence_root = (
            job_output / "subtitle_removal" / "subtitle_detection_evidence"
        )
        evidence_root.mkdir(parents=True)
        duration = float(branch_probe["duration"])
        frame_count = max(1, int(duration * 8))
        timestamps = [
            round(min(index / 8, max(0.0, duration - 0.001)), 3)
            for index in range(frame_count)
        ]
        frames = []
        for index, timestamp in enumerate(timestamps):
            frame = evidence_root / f"master_{index:04d}.png"
            run_checked(
                [
                    "ffmpeg",
                    "-loglevel",
                    "error",
                    "-y",
                    "-ss",
                    f"{timestamp:.3f}",
                    "-i",
                    str(branch_final),
                    "-frames:v",
                    "1",
                    str(frame),
                ],
                cwd=branch_root,
            )
            frames.append(
                {
                    "path": str(frame.resolve()),
                    "sha256": sha256_file(frame),
                    "timestamp_seconds": timestamp,
                }
            )
        report_path = (
            job_output / "subtitle_removal" / "subtitle_detection.json"
        )
        write_json(
            report_path,
            {
                "schema_version": 2,
                "overall": "PASS",
                "finishing_master": str(branch_final.resolve()),
                "finishing_master_sha256": sha256_file(branch_final),
                "duration_seconds": duration,
                "classification": classification,
                "checker": {
                    "reviewer": sealed_verdicts["reviewer"],
                    "fixture_id": sealed_verdicts["fixture_id"],
                    "input_fixture": str(sealed.get("input")),
                    "input_sha256": sha256_file(sealed_input),
                    "reason": sealed.get("reason"),
                },
                "subtitle_intervals": (
                    [{"start": 0.1, "end": min(0.4, duration)}]
                    if classification == "burned_in"
                    else []
                ),
                "evidence_frames": frames,
            },
        )
        result = subprocess.run(
            [
                sys.executable,
                str(engine_root / "tools" / "subtitle_workflow_qc.py"),
                "detection",
                "--report",
                str(report_path),
                "--json-out",
                str(report_path.with_name("detection_qc.json")),
            ],
            cwd=branch_root,
            text=True,
            capture_output=True,
            env=safe_target_environment(),
        )
        return result.returncode == 0

    clean_detection_passed = subtitle_detection(
        "subtitle-clean-classification"
    )
    burned_detection_passed = subtitle_detection(
        "subtitle-burned-in-classification"
    )

    route_product_names = {
        "generic": "Synthetic Fixture Product",
        "category:clay_mask": "清洁泥膜",
        "category:toner": "爽肤水",
    }

    def routed_rules(case_id: str) -> dict[str, Any]:
        route = str(case_inputs[case_id].get("profile_route") or "")
        product_name = route_product_names.get(route)
        if product_name is None:
            raise ParityStop(
                "fixture_branch_failed",
                f"unsupported declared profile route: {route}",
            )
        return {"loaded_rules": actual_route_rules(product_name)}

    identity_input = case_inputs["storyboard-derived-identity"]
    person_assets = job_intake.normalized_person_assets(
        ""
        if identity_input.get("person_assets") == "omitted"
        else str(identity_input.get("person_assets") or "")
    )
    identity_probe = run_storyboard_derived_branch_probe(
        engine_root=engine_root,
        workspace=workspace,
        visual_manifest_qc_path=visual_manifest_qc_path,
    )
    if (
        person_assets != "storyboard_derived"
        or identity_input.get("people_mode") != "multi-person"
    ):
        raise ParityStop(
            "fixture_branch_failed",
            "production storyboard-derived identity provenance did not pass",
            stage="branch_matrix",
            artifact_family="storyboard-derived-identity",
            expected="passed production identity provenance",
            actual={
                "person_assets": person_assets,
                "people_mode": identity_input.get("people_mode"),
                "visual_manifest_qc": identity_probe[
                    "production_evidence"
                ]["overall"],
            },
        )
    protagonist_source = identity_probe[
        "protagonist_identity_source"
    ]

    approval_input = case_inputs["generation-approval-boundary"]
    approval_rule = rule_for_status(
        stage_rules,
        str(approval_input.get("status") or ""),
    )
    generation_approved = bool(
        approval_input.get("generation_approval")
    )

    retry_input = case_inputs["failed-part-retry-boundary"]
    targeted_approval = bool(retry_input.get("new_targeted_approval"))
    retry_args = types.SimpleNamespace(
        planned_task_count=1,
        approval_source_message="fixture targeted retry approval"
        if targeted_approval
        else "",
        approval_recorded=targeted_approval,
        approval_scope="targeted_retry" if targeted_approval else "",
        approval_task_count=1 if targeted_approval else 0,
        generation_intent=str(
            retry_input.get("generation_intent") or ""
        ),
        approve_mediakit_subtitle_retry=False,
    )
    retry_context = runner.approval_context_for(
        workspace,
        {"id": FIXED_JOB_ID},
        {},
        policy,
        retry_args,
    )
    retry_violation = runner.cost_policy_violation(
        retry_context,
        {},
        policy,
    )

    actuals: dict[str, Any] = {
        "missing-required-input": missing_actual,
        "generic-profile-routing": routed_rules("generic-profile-routing"),
        "clay-mask-profile-routing": routed_rules(
            "clay-mask-profile-routing"
        ),
        "toner-profile-routing": routed_rules("toner-profile-routing"),
        "storyboard-derived-identity": {
            "person_assets": person_assets,
            "protagonist_identity_source": protagonist_source,
        },
        "generation-approval-boundary": {
            "conclusion": approval_rule["decision"].upper(),
            "next_stage": approval_rule["canonical_stage"],
            "provider_submission_allowed": (
                approval_rule["decision"] != "stop"
                and generation_approved
            ),
            "paid_task_count": 0,
        },
        "failed-part-retry-boundary": {
            "conclusion": "STOP" if retry_violation else "PASS",
            "retry_authority": (
                0 if retry_violation else retry_context["planned_task_count"]
            ),
            "paid_task_count": 0,
        },
        "local-finishing": {
            "conclusion": finish_report["overall"],
            "output": finished_output,
            "caption_policy": (
                "caption-free"
                if finish_report.get("caption_free") is True
                else "captions-present"
            ),
            "expected_frames": finished_frame_count,
        },
        "subtitle-clean-classification": {
            "conclusion": "PASS" if clean_detection_passed else "FAIL",
            "mediakit_task_count": 0,
        },
        "subtitle-burned-in-classification": {
            "conclusion": "STOP" if burned_detection_passed else "FAIL",
            "next_stage": "subtitle_removal_dispatch_barrier",
            "automatic_attempt_authority": policy["cost_classes"][
                "conditional_paid_repair"
            ]["max_tasks_per_job"],
            "automatic_retry_authority": int(
                case_inputs["subtitle-burned-in-classification"].get(
                    "automatic_attempts_spent", 0
                )
            ),
        },
        "final-technical-qc": {
            "conclusion": final_qc["overall"],
            "required_streams": finalization["final_technical_qc"][
                "required_streams"
            ],
            "duration_seconds": (
                finalization["final_technical_qc"][
                    "expected_duration_seconds"
                ]
                if abs(
                    float(final_qc_probe["duration"])
                    - float(
                        finalization["final_technical_qc"][
                            "expected_duration_seconds"
                        ]
                    )
                )
                <= 0.05
                else round(float(final_qc_probe["duration"]), 3)
            ),
        },
    }
    mutation_id = str(
        case_inputs["request-rejection"].get("mutation_id") or ""
    )
    mutation = next(
        (
            item
            for item in mutations
            if item["mutation_id"] == mutation_id
        ),
        None,
    )
    if mutation is None:
        raise ParityStop(
            "fixture_branch_failed",
            f"unknown declared request mutation: {mutation_id}",
        )
    try:
        recorder.replay(fixture_suite.apply_mutation(request, mutation))
    except Exception as exc:
        code = getattr(exc, "code", None)
        actuals["request-rejection"] = {
            "conclusion": "STOP",
            "machine_code": code,
            "real_task_count": 0,
        }
    else:
        actuals["request-rejection"] = {
            "conclusion": "PASS",
            "machine_code": "none",
            "real_task_count": 1,
        }

    if policy["approval"]["failed_part_retry_requires_new_approval"] is not True:
        raise ParityStop("fixture_branch_failed", "retry approval policy weakened")

    rows = []
    for case in cases:
        case_id = case.get("case_id")
        actual = actuals.get(case_id)
        expected = case.get("expected")
        row = {
            "case_id": case_id,
            "expected": expected,
            "actual": actual,
            "result": "PASS" if actual == expected else "FAIL",
        }
        if case_id == "storyboard-derived-identity":
            row["production_evidence"] = identity_probe[
                "production_evidence"
            ]
        rows.append(row)
    if [row["case_id"] for row in rows] != REQUIRED_BRANCHES:
        raise ParityStop("fixture_branch_failed", "required branch order changed")
    if any(row["result"] != "PASS" for row in rows):
        first = next(row for row in rows if row["result"] != "PASS")
        raise ParityStop(
            "fixture_branch_failed",
            json.dumps(first),
            stage="branch_matrix",
            artifact_family=first["case_id"],
            path=first["case_id"],
            expected=first["expected"],
            actual=first["actual"],
        )
    return rows


def target_behavior(
    engine_root: Path,
    fixture_root: Path,
    workspace: Path,
    target_kind: str,
    handoff_mode: str = "both",
) -> dict[str, Any]:
    engine_root = engine_root.resolve()
    fixture_root = fixture_root.resolve()
    workspace = workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    boundary_events = {
        "network_attempt_count": 0,
        "forbidden_write_count": 0,
    }
    activate_subprocess_network_guard(workspace, boundary_events)
    install_network_guard(boundary_events)
    install_write_guard(workspace, boundary_events)
    source_rhythm_qc = load_source_rhythm_qc(engine_root)
    # Fixture validation and zero-submit replay are harness infrastructure,
    # not behavior supplied by either target.  The sealed Legacy Baseline
    # intentionally predates these helpers.
    fixture_suite = load_module(
        SOURCE_ROOT / "tools" / "product_fixture_suite.py",
        "parity_product_fixture_suite",
    )
    recorder_module = load_module(
        SOURCE_ROOT / "tools" / "provider_fixture_recorder.py",
        "parity_provider_fixture_recorder",
    )
    fixture_validation = fixture_suite.validate_fixture_suite(fixture_root)

    stage_rules = read_json(engine_root / "rules" / "STAGE_RULES.json")
    understanding_route = read_json(
        engine_root / "rules" / "VIDEO_UNDERSTANDING_MODEL.json"
    )
    policy = cost_policy(engine_root)
    input_binding = read_json(fixture_root / "core" / "input_binding.json")
    script = read_json(fixture_root / "core" / "source_script.json")
    approval = read_json(fixture_root / "shared" / "approval.json")
    sealed_verdicts = read_json(
        fixture_root / "checker" / "sealed_stage_verdicts.json"
    )
    provider_request = read_json(fixture_root / "provider" / "request.json")
    recorder = recorder_module.ZeroSubmissionRecorder(
        fixture_root / "provider" / "recording.json",
        now="2026-07-30T12:00:00Z",
    )
    provider_response = recorder.replay(provider_request)
    recorder_metrics = recorder.metrics()
    receipt = provider_response["receipt"]
    if receipt != {
        "mode": "sealed_offline_replay",
        "real_submit": False,
        "task_created": False,
        "paid_task_count": 0,
        "media_generation_task_count": 0,
        "external_effects": [],
    }:
        raise ParityStop("provider_side_effect", json.dumps(receipt))

    understanding_analysis, understanding_evidence = (
        run_actual_video_understanding(
            engine_root=engine_root,
            fixture_root=fixture_root,
            workspace=workspace,
        )
    )
    if understanding_analysis.get("story_structure") != [
        "open",
        "texture-proof",
        "single-wipe",
    ]:
        raise ParityStop(
            "provider_response_mismatch",
            "production video understanding story order changed",
        )
    intake, profile, _intake_evidence_paths, intake_execution = run_actual_intake(
        target_kind=target_kind,
        engine_root=engine_root,
        fixture_root=fixture_root,
        workspace=workspace,
        handoff_mode=handoff_mode,
    )
    rhythm = source_rhythm(
        provider_response["result"],
        script,
        understanding_route,
        sha256_file(fixture_root / "core" / "source_4s.mkv"),
    )
    rhythm["understanding_evidence"] = understanding_evidence
    rhythm_qc_report = source_rhythm_qc.check_source_rhythm(rhythm)
    if rhythm_qc_report.get("overall") != "PASS":
        raise ParityStop(
            "source_rhythm_qc_failed",
            json.dumps(rhythm_qc_report, ensure_ascii=False),
            stage="source_blueprint",
            artifact_family="source_rhythm",
            expected="PASS",
            actual=rhythm_qc_report,
        )
    coverage = {
        "selection_mode": "source_rhythm",
        "parts": [
            {
                "part_id": "part1",
                "source_beat_ids": [beat["id"] for beat in rhythm["beats"]],
                "coverage": "exactly_once",
            }
        ],
    }
    artifact_paths: dict[str, Path] = {}
    for family, value in {
        "intake_normalization": intake,
        "source_rhythm": rhythm,
        "part_coverage": coverage,
    }.items():
        path = workspace / "artifacts" / f"{family}.json"
        write_json(path, value)
        artifact_paths[family] = path
    stage_rules_by_name = {
        "source_blueprint": rule_for_status(stage_rules, "pending"),
        "image_batch_qc": rule_for_status(stage_rules, "storyboard_passed"),
        "pre_seedance_pack": rule_for_status(
            stage_rules,
            "image_qc_passed",
        ),
    }
    stage_audit: list[dict[str, Any]] = []

    def advance_stage(
        stage: str,
        maker_evidence: list[Path],
        stage_execution: dict[str, Any],
    ) -> None:
        source_contract_paths = (
            [
                artifact_paths["intake_normalization"],
                artifact_paths["source_rhythm"],
                artifact_paths["part_coverage"],
            ]
            if stage == "source_blueprint"
            else []
        )
        stage_audit.append(
            run_production_stage_audit(
                engine_root=engine_root,
                workspace=workspace,
                fixture_root=fixture_root,
                execution=stage_execution,
                stage=stage,
                stage_rule=stage_rules_by_name[stage],
                maker_artifact_paths=[
                    *source_contract_paths,
                    *maker_evidence,
                ],
                sealed_verdicts=sealed_verdicts,
            )
        )

    actual_pack, actual_pack_evidence, pack_execution = (
        prepare_actual_pre_seedance_pack(
            engine_root=engine_root,
            fixture_root=fixture_root,
            workspace=workspace,
            execution=intake_execution,
            profile=profile,
            rhythm=rhythm,
            script=script,
            sealed_verdicts=sealed_verdicts,
            advance_stage=advance_stage,
        )
    )
    director_plan = actual_pack["director_plan"]
    actual_coverage = [
        source_beat_id
        for part in director_plan["parts"]
        for beat in part["beats"]
        for source_beat_id in beat["source_beat_ids"]
    ]
    if actual_coverage != coverage["parts"][0]["source_beat_ids"]:
        raise ParityStop(
            "part_coverage_failed",
            "production Director Plan changed source beat coverage",
        )
    source_script_fidelity = actual_pack["source_script_fidelity"]
    audio_boundary = actual_pack["audio_boundary"]
    reference_roles = actual_pack["reference_roles_and_order"]
    prompt = actual_pack["prompt"]
    prepared_request = actual_pack["provider_request"]
    generation_rule = rule_for_status(stage_rules, "seedance_inputs_prepared")
    approval_projection = {
        **approval,
        "current_status": "seedance_inputs_prepared",
        "decision": generation_rule["decision"],
        "next_stage": generation_rule["next_expected"],
    }
    cost_projection = {
        "current_stage_cost_class": generation_rule["cost_class"],
        "auto_allowed": policy["cost_classes"]["expensive_generation"][
            "auto_allowed"
        ],
        "spent": {
            "gpt_image_runs": 0,
            "seedance_runs": 0,
            "mediakit_subtitle_removal_runs": 0,
        },
        "paid_task_count": 0,
    }
    retry_projection = {
        "current_retry_authority": approval["retry_authority"],
        "failed_part_retry_requires_new_approval": policy["approval"][
            "failed_part_retry_requires_new_approval"
        ],
        "automatic_seedance_retry_count": 0,
    }

    artifacts: dict[str, Any] = {
        "intake_normalization": intake,
        "effective_profile": profile,
        "source_rhythm": rhythm,
        "part_coverage": coverage,
        "director_plan": director_plan,
        "source_script_fidelity": source_script_fidelity,
        "line_edits": actual_pack["line_edits"],
        "visual_edits": actual_pack["visual_edits"],
        "audio_boundary": audio_boundary,
        "reference_roles_and_order": reference_roles,
        "prompt": prompt,
        "provider_request": prepared_request,
        "approval": approval_projection,
        "cost": cost_projection,
        "retry_authority": retry_projection,
    }
    for family, value in artifacts.items():
        suffix = ".txt" if isinstance(value, str) else ".json"
        path = workspace / "artifacts" / f"{family}{suffix}"
        if isinstance(value, str):
            write_text(path, value)
        else:
            write_json(path, value)
        artifact_paths[family] = path

    stage_audit.append(
        run_production_stage_audit(
            engine_root=engine_root,
            workspace=workspace,
            fixture_root=fixture_root,
            execution=pack_execution,
            stage="pre_seedance_pack",
            stage_rule=stage_rules_by_name["pre_seedance_pack"],
            maker_artifact_paths=[
                artifact_paths["director_plan"],
                artifact_paths["source_script_fidelity"],
                artifact_paths["audio_boundary"],
                artifact_paths["reference_roles_and_order"],
                artifact_paths["prompt"],
                artifact_paths["provider_request"],
                *actual_pack_evidence,
            ],
            sealed_verdicts=sealed_verdicts,
        )
    )
    artifacts["qc_risk_families"] = {
        audit["stage"]: audit["qc_risk_families"] for audit in stage_audit
    }
    artifacts["gate_conclusions"] = {
        audit["stage"]: {
            "gate": audit["gate"],
            "conclusion": audit["gate_conclusion"],
            "next_status": audit["status_after"],
        }
        for audit in stage_audit
    }
    final_row = read_job_row(Path(pack_execution["jobs_path"]), FIXED_JOB_ID)
    final_status = final_row["status"]
    if final_status != "seedance_inputs_prepared":
        raise ParityStop(
            "stage_transition_failed",
            f"expected seedance_inputs_prepared, got {final_status}",
        )
    approval_projection["current_status"] = final_status
    write_json(artifact_paths["approval"], approval_projection)
    for family in ("qc_risk_families", "gate_conclusions"):
        path = workspace / "artifacts" / f"{family}.json"
        write_json(path, artifacts[family])
        artifact_paths[family] = path

    handoff = actual_pack["pre_seedance_handoff"]
    handoff["status"] = final_status
    handoff["generation_barrier"] = {
        "decision": "stop",
        "reason": generation_rule["reason"],
        "real_task_count": 0,
        "paid_task_count": 0,
    }
    artifacts["pre_seedance_handoff"] = handoff
    handoff_path = workspace / "handoff" / "pre_seedance_handoff.json"
    write_json(handoff_path, handoff)

    branch_rows = evaluate_branch_cases(
        engine_root=engine_root,
        fixture_root=fixture_root,
        workspace=workspace,
        stage_rules=stage_rules,
        policy=policy,
        recorder=recorder,
        request=provider_request,
        fixture_suite=fixture_suite,
        sealed_verdicts=sealed_verdicts,
        visual_manifest_qc_path=(
            Path(pack_execution["job_work"])
            / "checks"
            / "visual_asset_manifest_qc.json"
        ),
    )
    assert_no_subprocess_network_attempts()
    behavior = {
        "schema_version": 1,
        "fixture_suite_id": fixture_validation["suite_id"],
        "job_id": FIXED_JOB_ID,
        "environment": {
            "locale": "C",
            "timezone": "UTC",
            "python_hash_seed": "0",
            "clock": FIXED_TIME,
            "runtime": sealed_runtime_projection(),
        },
        "execution_boundary": {
            "kind": "macos_sandbox_exec",
            "default_policy": "deny",
            "network": "deny_all",
            "network_attempt_observability": (
                "socket_guard_plus_monitored_process_closure"
            ),
            "python_guard_bypass_flags": ["-E", "-I", "-S"],
            "native_process_allowlist": [
                "ffmpeg_local_inputs_only",
                "ffprobe_local_inputs_only",
                "git_status_or_ls_files_only",
            ],
            "file_reads": "declared_roots_only",
            "file_writes": "workspace_only",
            "nested_stage_execution": (
                "production_serial_execution_under_outer_sandbox"
            ),
            "canonical_job_lineage": (
                "plugin_state_job_symlinked_to_compatibility_root"
            ),
            "adapter_location": "external_harness_workspace",
            "adapter_packaged": False,
        },
        "production_tools_executed": [
            "simple_intake_entrypoint",
            "run_next_loop_round.py",
            "video_understanding.understand_video",
            "source_rhythm_qc.py",
            "source_rhythm_visual_review_qc.py",
            "build_part_storyboards.py",
            "codex_imagegen_contract_qc.py",
            "visual_asset_manifest_qc.py",
            "pre_seedance_pack.py:init",
            "pre_seedance_pack.py:render",
            "pre_seedance_pack_qc.py",
            "qc_risk_ledger.py",
            "checker_review_qc.py",
            "finish_video.py:init",
            "finish_video.py:render",
            "subtitle_workflow_qc.py:detection",
            "final_video_qc.py",
        ],
        "engine_contract": engine_contract_projection(engine_root),
        "fixture_projection": fixture_file_projection(fixture_root),
        "stage_order": [audit["stage"] for audit in stage_audit],
        "stage_audit": stage_audit,
        "artifacts": artifacts,
        "branch_rows": branch_rows,
        "final_status": final_status,
        "side_effects": {
            "network_attempt_count": boundary_events["network_attempt_count"],
            "unmatched_request_count": (
                recorder_metrics["unmatched_request_count"]
                + pack_execution["image_recorder_metrics"][
                    "unmatched_request_count"
                ]
            ),
            "real_task_count": 0,
            "paid_task_count": (
                receipt["paid_task_count"]
                + pack_execution["image_response"]["receipt"][
                    "paid_task_count"
                ]
            ),
            "media_generation_task_count": (
                receipt["media_generation_task_count"]
                + pack_execution["image_response"]["receipt"][
                    "media_generation_task_count"
                ]
            ),
            "recorder_fallback_count": (
                recorder_metrics["fallback_count"]
                + pack_execution["image_recorder_metrics"][
                    "fallback_count"
                ]
            ),
            "forbidden_write_count": boundary_events[
                "forbidden_write_count"
            ],
        },
    }
    return behavior


def target_command(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    report_path = Path(args.report).resolve()
    if not path_within(report_path, workspace):
        print("STOP target report must be inside its Workspace", file=sys.stderr)
        return 2
    try:
        behavior = target_behavior(
            Path(args.engine_root),
            Path(args.fixture_root),
            workspace,
            args.target_kind,
            handoff_mode=args.handoff_mode,
        )
        report = {
            "overall": "PASS",
            "target_kind": args.target_kind,
            "behavior_sha256": sha256_bytes(canonical_bytes(behavior)),
            "behavior": behavior,
        }
        write_json(report_path, report)
    except Exception as exc:
        report = {
            "overall": "STOP",
            "failure": {
                "code": getattr(exc, "code", "target_execution_failed"),
                "detail": str(exc),
                **getattr(exc, "context", {}),
            },
        }
        try:
            write_json(report_path, report)
        except Exception:
            pass
        print(f"STOP {report['failure']['code']}: {exc}", file=sys.stderr)
        return 2
    print(report_path)
    return 0


def tree_snapshot(root: Path) -> dict[str, Any]:
    root = root.resolve()
    entries = []
    for path in [root, *sorted(root.rglob("*"))]:
        relative = "." if path == root else path.relative_to(root).as_posix()
        info = path.lstat()
        mode = info.st_mode
        if stat.S_ISREG(mode):
            kind = "file"
        elif stat.S_ISDIR(mode):
            kind = "directory"
        elif stat.S_ISLNK(mode):
            kind = "symlink"
        else:
            kind = "other"
        entry = {
            "path": relative,
            "kind": kind,
            "mode": stat.S_IMODE(mode),
            "uid": info.st_uid,
            "gid": info.st_gid,
            "nlink": info.st_nlink,
            "size": info.st_size,
            "device": info.st_dev,
            "inode": info.st_ino,
            "mtime_ns": info.st_mtime_ns,
            "ctime_ns": info.st_ctime_ns,
            "birthtime_ns": int(
                getattr(info, "st_birthtime", 0) * 1_000_000_000
            ),
            "flags": int(getattr(info, "st_flags", 0)),
        }
        if kind == "file":
            entry["sha256"] = sha256_file(path)
        elif kind == "symlink":
            entry["target"] = os.readlink(path)
        entries.append(entry)
    return {
        "entry_count": len(entries),
        "sha256": sha256_bytes(canonical_bytes(entries)),
    }


def sandbox_literal(path: Path) -> str:
    return json.dumps(str(path.resolve()), ensure_ascii=False)


def executable_dependency_files(executable: Path) -> set[Path]:
    pending = [executable.resolve()]
    dependencies: set[Path] = set()
    while pending:
        current = pending.pop()
        if current in dependencies or not current.is_file():
            continue
        dependencies.add(current)
        result = subprocess.run(
            ["/usr/bin/otool", "-L", str(current)],
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            continue
        for line in result.stdout.splitlines()[1:]:
            candidate = line.strip().split(" (", 1)[0]
            if not candidate.startswith("/"):
                continue
            raw_path = Path(candidate).absolute()
            dependencies.add(raw_path)
            path = raw_path.resolve()
            if path not in dependencies:
                pending.append(path)
    return dependencies


def homebrew_package_root(path: Path) -> Path | None:
    path = path.absolute()
    for prefix, depth in (
        (Path("/opt/homebrew/opt"), 1),
        (Path("/opt/homebrew/Cellar"), 2),
    ):
        try:
            relative = path.relative_to(prefix)
        except ValueError:
            continue
        if len(relative.parts) >= depth:
            return prefix.joinpath(*relative.parts[:depth])
    return None


def runtime_read_filters() -> tuple[set[Path], set[Path]]:
    roots = {
        Path("/System"),
        Path("/usr"),
        Path("/bin"),
        Path("/sbin"),
        Path("/dev"),
        Path("/private/etc"),
        Path("/private/var/db/timezone"),
        Path(sys.base_prefix),
        Path(sys.prefix),
        Path("/Library/Developer/CommandLineTools"),
    }
    files: set[Path] = set()
    for name in ("ffmpeg", "ffprobe"):
        executable = shutil.which(name, path=PINNED_EXECUTABLE_PATH)
        if executable:
            executable_path = Path(executable)
            files.add(executable_path)
            dependencies = executable_dependency_files(executable_path)
            files.update(dependencies)
            roots.update(path.parent for path in dependencies)
            roots.update(
                package_root
                for path in dependencies
                if (package_root := homebrew_package_root(path)) is not None
            )
    return roots, files


def build_sandbox_profile(
    *,
    engine_root: Path,
    fixture_root: Path,
    workspace: Path | None,
    target_root: Path,
    extra_read_files: tuple[Path, ...] = (),
) -> str:
    runtime_roots, runtime_files = runtime_read_filters()
    read_roots = {
        engine_root.resolve(),
        fixture_root.resolve(),
        target_root.resolve(),
        *runtime_roots,
    }
    if workspace is not None:
        read_roots.add(workspace.resolve())
    read_files = {
        Path(__file__).resolve(),
        SOURCE_ROOT / "tools",
        SOURCE_ROOT / "tools" / "product_fixture_suite.py",
        SOURCE_ROOT / "tools" / "provider_fixture_recorder.py",
        *runtime_files,
        *(path.resolve() for path in extra_read_files),
    }
    root_filter_paths = {
        candidate
        for path in read_roots
        if path.exists()
        for candidate in (path.absolute(), path.resolve())
    }
    filters = [
        f"(subpath {json.dumps(str(path), ensure_ascii=False)})"
        for path in sorted(root_filter_paths, key=str)
    ]
    filters.extend(
        f"(literal {json.dumps(str(path.absolute()), ensure_ascii=False)})"
        for path in sorted(read_files, key=str)
        if path.exists()
    )
    metadata_paths: set[Path] = set()
    for path in [
        *read_roots,
        *read_files,
    ]:
        for candidate in {path.absolute(), path.resolve()}:
            current = candidate
            while True:
                metadata_paths.add(current)
                if current.parent == current:
                    break
                current = current.parent
    metadata_filters = [
        f"(literal {sandbox_literal(path)})"
        for path in sorted(metadata_paths, key=str)
        if path.exists()
    ]
    lines = [
        "(version 1)",
        "(deny default)",
        '(import "system.sb")',
        "(deny network*)",
        "(allow process*)",
        "(allow sysctl-read)",
        f"(allow file-read-metadata {' '.join(metadata_filters)})",
        f"(allow file-read* {' '.join(filters)})",
    ]
    if workspace is not None:
        lines.append(
            f"(allow file-write* (subpath {sandbox_literal(workspace)}))"
        )
    return "\n".join(lines)


def safe_target_environment() -> dict[str, str]:
    forbidden_markers = (
        "API_KEY",
        "PASSWORD",
        "SECRET",
        "TOKEN",
        "CREDENTIAL",
        "AUTHORIZATION",
    )
    environment = {
        key: value
        for key, value in os.environ.items()
        if not any(marker in key.upper() for marker in forbidden_markers)
        and key
        not in {
            "PYTHONHOME",
            "PYTHONPATH",
            "PYTHONUSERBASE",
            "VIRAL_REPLICA_ALLOW_PROVIDER_SUBMIT",
            "VIRAL_REPLICA_GENERATION_APPROVED",
        }
    }
    environment.update(
        {
            "LANG": "C",
            "LC_ALL": "C",
            "TZ": "UTC",
            "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PATH": PINNED_EXECUTABLE_PATH,
        }
    )
    guard = _ACTIVE_SUBPROCESS_NETWORK_GUARD
    if guard is not None:
        environment["PYTHONPATH"] = str(guard["guard_root"])
        environment["VIRAL_REPLICA_PARITY_NETWORK_LEDGER"] = str(
            guard["ledger"],
        )
    return environment


def sealed_runtime_projection() -> dict[str, Any]:
    try:
        import site
        import PIL
    except ImportError as exc:
        raise ParityStop(
            "runtime_unsealed",
            "the declared parity runtime is missing Pillow",
        ) from exc
    module_path = Path(PIL.__file__).resolve()
    runtime_prefix = Path(sys.prefix).resolve()
    if site.ENABLE_USER_SITE is not False or not path_within(
        module_path,
        runtime_prefix,
    ):
        raise ParityStop(
            "runtime_unsealed",
            "parity dependencies must come from the isolated runtime, "
            "never user site-packages",
            stage="environment",
            artifact_family="managed_runtime",
            expected={
                "user_site_enabled": False,
                "dependency_root": "runtime_prefix",
            },
            actual={
                "user_site_enabled": site.ENABLE_USER_SITE,
                "pillow_path": str(module_path),
            },
        )
    python_executable = Path(sys.executable).resolve()
    media_tools = {}
    for name in ("ffmpeg", "ffprobe"):
        executable_raw = shutil.which(name, path=PINNED_EXECUTABLE_PATH)
        if executable_raw is None:
            raise ParityStop(
                "runtime_unsealed",
                f"the declared parity runtime is missing {name}",
            )
        media_executable = Path(executable_raw).resolve()
        version = subprocess.run(
            [str(media_executable), "-version"],
            text=True,
            capture_output=True,
            check=False,
            env=safe_target_environment(),
        )
        assert_no_subprocess_network_attempts()
        if version.returncode != 0 or not version.stdout.strip():
            raise ParityStop(
                "runtime_unsealed",
                f"{name} version probe failed",
            )
        media_tools[name] = {
            "sha256": sha256_file(media_executable),
            "version": version.stdout.splitlines()[0],
        }
    return {
        "python_implementation": sys.implementation.name,
        "python_version": ".".join(
            str(value) for value in sys.version_info[:3]
        ),
        "python_executable_sha256": sha256_file(python_executable),
        "user_site_enabled": False,
        "pillow_version": str(PIL.__version__),
        "pillow_init_sha256": sha256_file(module_path),
        "media_tools": media_tools,
    }


def run_target(
    *,
    target_name: str,
    run_number: int,
    engine_root: Path,
    fixture_root: Path,
    out_dir: Path,
    handoff_mode: str = "both",
) -> dict[str, Any]:
    workspace = out_dir / "workspaces" / target_name / f"run-{run_number}"
    workspace.mkdir(parents=True)
    temporary_root = workspace / "tmp"
    temporary_root.mkdir()
    report_path = workspace / "target_report.json"
    sandbox_exec = Path("/usr/bin/sandbox-exec")
    if not sandbox_exec.is_file():
        raise ParityStop(
            "sandbox_unavailable",
            "supported parity runs require macOS sandbox-exec",
        )
    target_root = (
        engine_root.parent if target_name == "plugin" else engine_root
    )
    sandbox_profile = build_sandbox_profile(
        engine_root=engine_root,
        fixture_root=fixture_root,
        workspace=workspace,
        target_root=target_root,
    )
    result = subprocess.run(
        [
            str(sandbox_exec),
            "-p",
            sandbox_profile,
            sys.executable,
            "-s",
            str(Path(__file__).resolve()),
            "target",
            "--engine-root",
            str(engine_root),
            "--target-kind",
            target_name,
            "--fixture-root",
            str(fixture_root),
            "--workspace",
            str(workspace),
            "--report",
            str(report_path),
            "--handoff-mode",
            handoff_mode,
        ],
        cwd=workspace,
        text=True,
        capture_output=True,
        env={
            **safe_target_environment(),
            "VIRAL_REPLICA_PARITY_OUTER_SANDBOX": "1",
            "TMPDIR": str(temporary_root),
            "TMP": str(temporary_root),
            "TEMP": str(temporary_root),
        },
    )
    if not report_path.is_file():
        raise ParityStop(
            "target_sandbox_failed",
            f"{target_name} run {run_number}: {result.stderr or result.stdout}",
        )
    report = read_json(report_path)
    if result.returncode != 0 or report.get("overall") != "PASS":
        failure = report.get("failure") or {}
        raise ParityStop(
            failure.get("code") or "target_execution_failed",
            f"{target_name} run {run_number}: "
            f"{failure.get('detail') or result.stderr}",
            **{
                key: value
                for key, value in failure.items()
                if key not in {"code", "detail"}
            },
        )
    behavior = report["behavior"]
    return {
        "run_number": run_number,
        "behavior_sha256": report["behavior_sha256"],
        "stage_order": behavior["stage_order"],
        "stage_audit": behavior["stage_audit"],
        "side_effects": behavior["side_effects"],
        "report_path": str(report_path),
        "_behavior": behavior,
    }


def first_difference(expected: Any, actual: Any, path: str = "") -> dict[str, Any]:
    if type(expected) is not type(actual):
        return {"path": path or "$", "expected": expected, "actual": actual}
    if isinstance(expected, dict):
        if list(expected) != list(actual):
            return {
                "path": path or "$",
                "expected": list(expected),
                "actual": list(actual),
            }
        for key in expected:
            difference = first_difference(
                expected[key],
                actual[key],
                f"{path}.{key}" if path else key,
            )
            if difference:
                return difference
        return {}
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return {
                "path": path or "$",
                "expected": expected,
                "actual": actual,
            }
        for index, (left, right) in enumerate(zip(expected, actual)):
            difference = first_difference(
                left,
                right,
                f"{path}[{index}]",
            )
            if difference:
                return difference
        return {}
    if expected != actual:
        return {"path": path or "$", "expected": expected, "actual": actual}
    return {}


def instability_failure(
    target: str,
    expected_behavior: dict[str, Any],
    actual_behavior: dict[str, Any],
) -> dict[str, Any]:
    difference = first_difference(expected_behavior, actual_behavior)
    return {
        "code": "baseline_unstable",
        "target": target,
        "stage": "target_stability",
        "artifact_family": "complete_behavior",
        "path": difference.get("path", "$"),
        "expected": difference.get("expected"),
        "actual": difference.get("actual"),
    }


def branch_mismatch_failure(
    expected_row: dict[str, Any],
    actual_row: dict[str, Any],
    *,
    case_id: str | None = None,
) -> dict[str, Any]:
    difference = first_difference(expected_row, actual_row)
    return {
        "code": "deterministic_parity_mismatch",
        "stage": "branch_matrix",
        "artifact_family": str(
            case_id
            or expected_row.get("case_id")
            or actual_row.get("case_id")
            or "unknown_branch"
        ),
        "path": difference.get("path", "$"),
        "expected": difference.get("expected"),
        "actual": difference.get("actual"),
    }


def public_run(run: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in run.items() if key != "_behavior"}


def write_report_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Pre-Seedance Behavioral Parity",
        "",
        f"- Overall: **{report['overall']}**",
        f"- Final status: `{report.get('final_status')}`",
        f"- Real tasks: `{report.get('side_effects', {}).get('real_task_count', 0)}`",
        f"- Paid tasks: `{report.get('side_effects', {}).get('paid_task_count', 0)}`",
    ]
    if report.get("failure"):
        failure = report["failure"]
        lines.extend(
            [
                "",
                "## First difference",
                "",
                f"- Code: `{failure.get('code')}`",
                f"- Stage: `{failure.get('stage')}`",
                f"- Artifact family: `{failure.get('artifact_family')}`",
                f"- Path: `{failure.get('path')}`",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "## Required rows",
                "",
                *[
                    f"- {row['result']}: `{row['row_id']}`"
                    for row in report["required_rows"]
                ],
            ]
        )
    write_text(path, "\n".join(lines))


def verify_legacy_baseline(
    legacy_root: Path,
    baseline: Path,
    expected_snapshot: dict[str, Any],
) -> dict[str, Any]:
    if not path_within(baseline, legacy_root):
        raise ParityStop(
            "baseline_invalid",
            "legacy baseline must be inside the Legacy Baseline root",
        )
    tool = legacy_root / "tools" / "legacy_baseline.py"
    baseline_contract = read_json(baseline)
    verifier_python_raw = (
        (baseline_contract.get("runtime_contract") or {})
        .get("python", {})
        .get("executable")
    )
    verifier_python = (
        Path(str(verifier_python_raw)).resolve()
        if verifier_python_raw
        else None
    )
    if verifier_python is None or not verifier_python.is_file():
        raise ParityStop(
            "baseline_invalid",
            "Legacy Baseline does not declare an available verifier Python",
        )
    verifier_objects = [
        item
        for item in (
            baseline_contract.get("source_closure", {}).get("objects", [])
        )
        if item.get("path") == "tools/legacy_baseline.py"
    ]
    if len(verifier_objects) != 1:
        raise ParityStop(
            "baseline_invalid",
            "Legacy Baseline does not bind exactly one verifier object",
        )
    verifier_object = verifier_objects[0]
    verifier_mode = oct(stat.S_IMODE(tool.stat().st_mode))
    if (
        verifier_object.get("kind") != "file"
        or verifier_object.get("sha256") != sha256_file(tool)
        or verifier_object.get("size_bytes") != tool.stat().st_size
        or verifier_object.get("mode") != verifier_mode
    ):
        raise ParityStop(
            "baseline_integrity_failed",
            "Legacy verifier differs from its sealed source closure",
        )
    sandbox_exec = Path("/usr/bin/sandbox-exec")
    if not sandbox_exec.is_file():
        raise ParityStop(
            "sandbox_unavailable",
            "Legacy Baseline verification requires macOS sandbox-exec",
        )
    profile = build_sandbox_profile(
        engine_root=legacy_root,
        fixture_root=legacy_root,
        workspace=None,
        target_root=legacy_root,
        extra_read_files=(baseline, tool),
    )
    try:
        result = subprocess.run(
            [
                str(sandbox_exec),
                "-p",
                profile,
                str(verifier_python),
                str(tool),
                "verify",
                "--root",
                str(legacy_root),
                "--baseline",
                baseline.relative_to(legacy_root).as_posix(),
            ],
            cwd=legacy_root,
            text=True,
            capture_output=True,
            env=safe_target_environment(),
        )
    finally:
        current_snapshot = tree_snapshot(legacy_root)
        if current_snapshot != expected_snapshot:
            raise ParityStop(
                "legacy_write_forbidden",
                "Legacy Baseline changed while its verifier was running",
            )
    if result.returncode != 0 or result.stdout.strip() != "PASS":
        raise ParityStop(
            "baseline_integrity_failed",
            result.stdout + result.stderr,
        )
    return {
        "path": baseline.relative_to(legacy_root).as_posix(),
        "sha256": sha256_file(baseline),
        "verification_tool_sha256": sha256_file(tool),
        "verification_python": str(verifier_python),
        "verification_python_sha256": sha256_file(verifier_python),
        "tree_snapshot_sha256": expected_snapshot["sha256"],
        "result": "PASS",
    }


def harness_command(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "parity_report.json"
    markdown_path = out_dir / "parity_report.md"
    legacy_root = Path(args.legacy_root).resolve()
    plugin_root = Path(args.plugin_root).resolve()
    fixture_root = Path(args.fixture_root).resolve()
    baseline = Path(args.legacy_baseline).resolve()
    report: dict[str, Any] = {
        "schema_version": 1,
        "overall": "STOP",
        "required_rows": [],
        "branch_rows": [],
        "targets": {},
        "normalization": {
            "allowlist": NORMALIZATION_ALLOWLIST,
            "applied": ["workspace_root"],
        },
        "side_effects": {
            "network_attempt_count": 0,
            "unmatched_request_count": 0,
            "real_task_count": 0,
            "paid_task_count": 0,
            "media_generation_task_count": 0,
            "recorder_fallback_count": 0,
            "forbidden_write_count": 0,
        },
        "final_status": None,
        "execution_proof": {
            "legacy_intake_entrypoint": "scripts/new-task.py",
            "plugin_intake_entrypoint": "scripts/run-canonical-job.py",
            "pre_seedance_entrypoint": "engine/tools/pre_seedance_pack.py",
            "qc_entrypoint": "engine/tools/pre_seedance_pack_qc.py",
            "adapter": "top-level harness only; excluded from Plugin Package",
        },
    }
    try:
        plugin_engine = plugin_root / "engine"
        plugin_fixture = plugin_root / "assets" / "fixtures" / "v1"
        if not (plugin_root / ".codex-plugin" / "plugin.json").is_file():
            raise ParityStop("plugin_invalid", "Canonical Plugin manifest is missing")
        if (plugin_engine / "tools" / "pre_seedance_parity.py").exists():
            raise ParityStop(
                "legacy_adapter_forbidden",
                "the top-level harness entered the Plugin Package",
            )
        if fixture_file_projection(fixture_root) != fixture_file_projection(
            plugin_fixture
        ):
            raise ParityStop(
                "fixture_binding_mismatch",
                "Legacy and Plugin targets do not use byte-identical fixtures",
            )
        policy = read_json(SOURCE_ROOT / "migration" / "policies" / "parity-policy-v1.json")
        if policy.get("normalization_allowlist") != NORMALIZATION_ALLOWLIST:
            raise ParityStop(
                "normalization_policy_invalid",
                "only root prefixes and declared timestamps may be normalized",
            )

        legacy_before = tree_snapshot(legacy_root)
        plugin_before = tree_snapshot(plugin_root)
        report["legacy_baseline"] = verify_legacy_baseline(
            legacy_root,
            baseline,
            legacy_before,
        )
        legacy_engine_contract = engine_contract_projection(
            legacy_root,
            include_behavior_probes=False,
        )
        plugin_engine_contract = engine_contract_projection(
            plugin_engine,
            include_behavior_probes=False,
        )
        if legacy_engine_contract != plugin_engine_contract:
            difference = first_difference(
                legacy_engine_contract,
                plugin_engine_contract,
            )
            difference_path = difference.get("path", "")
            if difference_path.startswith("rules/SEEDANCE_MODEL.json"):
                report["failure"] = {
                    "code": "deterministic_parity_mismatch",
                    "stage": "pre_seedance_pack",
                    "artifact_family": "director_plan",
                    "path": (
                        "model_route."
                        + difference_path.removeprefix(
                            "rules/SEEDANCE_MODEL.json."
                        )
                    ),
                    "expected": {
                        "model_route": legacy_engine_contract[
                            "rules/SEEDANCE_MODEL.json"
                        ]
                    },
                    "actual": {
                        "model_route": plugin_engine_contract[
                            "rules/SEEDANCE_MODEL.json"
                        ]
                    },
                    "expected_value": difference.get("expected"),
                    "actual_value": difference.get("actual"),
                }
            elif difference_path.startswith(
                "qc_executable_semantics.",
            ) or difference_path.startswith(
                "qc_full_semantic_closure.",
            ) or difference_path.startswith("qc_behavior_probes."):
                report["failure"] = {
                    "code": "deterministic_parity_mismatch",
                    "stage": "behavior_contract",
                    "artifact_family": "qc_executable_semantics",
                    **difference,
                }
            else:
                report["failure"] = {
                    "code": "deterministic_parity_mismatch",
                    "stage": "behavior_contract",
                    "artifact_family": "engine_semantics",
                    **difference,
                }
            report["overall"] = "FAIL"
            write_json(report_path, report)
            write_report_markdown(markdown_path, report)
            print(
                "FAIL deterministic_parity_mismatch: "
                f"{report['failure']['stage']}/"
                f"{report['failure']['artifact_family']}"
            )
            return 3
        target_specs = {
            "legacy": (legacy_root, fixture_root),
            "plugin": (plugin_engine, plugin_fixture),
        }
        target_runs: dict[str, list[dict[str, Any]]] = {}
        for target_name, (engine_root, target_fixture) in target_specs.items():
            target_runs[target_name] = [
                run_target(
                    target_name=target_name,
                    run_number=run_number,
                    engine_root=engine_root,
                    fixture_root=target_fixture,
                    out_dir=out_dir,
                )
                for run_number in (1, 2)
            ]
            first_run, second_run = target_runs[target_name]
            if first_run["_behavior"] != second_run["_behavior"]:
                report["failure"] = instability_failure(
                    target_name,
                    first_run["_behavior"],
                    second_run["_behavior"],
                )
                raise ParityStop(
                    "baseline_unstable",
                    f"{target_name}: {report['failure']['path']}",
                )

        verify_legacy_baseline(legacy_root, baseline, legacy_before)
        if tree_snapshot(legacy_root) != legacy_before:
            raise ParityStop("legacy_write_forbidden", "Legacy Baseline changed")
        if tree_snapshot(plugin_root) != plugin_before:
            raise ParityStop("plugin_write_forbidden", "Plugin Package changed")

        legacy_behavior = target_runs["legacy"][0]["_behavior"]
        plugin_behavior = target_runs["plugin"][0]["_behavior"]
        for row_id in REQUIRED_ROWS:
            expected = legacy_behavior["artifacts"][row_id]
            actual = plugin_behavior["artifacts"][row_id]
            result = "PASS" if expected == actual else "FAIL"
            row = {
                "row_id": row_id,
                "stage": ROW_STAGES[row_id],
                "required": True,
                "result": result,
            }
            report["required_rows"].append(row)
            if result != "PASS":
                difference = first_difference(expected, actual)
                report["failure"] = {
                    "code": "deterministic_parity_mismatch",
                    "stage": ROW_STAGES[row_id],
                    "artifact_family": row_id,
                    "expected": expected,
                    "actual": actual,
                    "path": difference.get("path"),
                    "expected_value": difference.get("expected"),
                    "actual_value": difference.get("actual"),
                }
                break
        if report.get("failure"):
            report["overall"] = "FAIL"
        else:
            legacy_branches = legacy_behavior["branch_rows"]
            plugin_branches = plugin_behavior["branch_rows"]
            legacy_branch_ids = [
                row.get("case_id") for row in legacy_branches
            ]
            plugin_branch_ids = [
                row.get("case_id") for row in plugin_branches
            ]
            if (
                legacy_branch_ids != REQUIRED_BRANCHES
                or plugin_branch_ids != REQUIRED_BRANCHES
            ):
                report["failure"] = {
                    "code": "deterministic_parity_mismatch",
                    "stage": "branch_matrix",
                    "artifact_family": "branch_order",
                    "path": "case_ids",
                    "expected": legacy_branch_ids,
                    "actual": plugin_branch_ids,
                }
            for expected, actual in zip(
                legacy_branches,
                plugin_branches,
            ):
                row = {
                    "case_id": expected["case_id"],
                    "required": True,
                    "expected": expected,
                    "actual": actual,
                    "result": (
                        "PASS"
                        if expected["result"] == actual["result"] == "PASS"
                        and expected["actual"] == actual["actual"]
                        else "FAIL"
                    ),
                }
                report["branch_rows"].append(row)
            if (
                report.get("failure") is None
                and any(
                    row["result"] != "PASS"
                    for row in report["branch_rows"]
                )
            ):
                first = next(
                    row
                    for row in report["branch_rows"]
                    if row["result"] != "PASS"
                )
                report["failure"] = branch_mismatch_failure(
                    first["expected"],
                    first["actual"],
                    case_id=first["case_id"],
                )
            if report.get("failure") is not None:
                report["overall"] = "FAIL"
            elif legacy_behavior != plugin_behavior:
                difference = first_difference(legacy_behavior, plugin_behavior)
                report["overall"] = "FAIL"
                behavior_path = str(difference.get("path") or "")
                report["failure"] = {
                    "code": "deterministic_parity_mismatch",
                    "stage": "behavior_contract",
                    "artifact_family": (
                        "qc_executable_semantics"
                        if behavior_path.startswith(
                            "engine_contract.qc_behavior_probes."
                        )
                        else "complete_behavior"
                    ),
                    **difference,
                }
            else:
                report["overall"] = "PASS"
                report["final_status"] = legacy_behavior["final_status"]

        report["targets"] = {
            target: {"runs": [public_run(run) for run in runs]}
            for target, runs in target_runs.items()
        }
        effects = [
            run["side_effects"]
            for runs in target_runs.values()
            for run in runs
        ]
        report["side_effects"] = {
            key: sum(int(effect[key]) for effect in effects)
            for key in report["side_effects"]
        }
        if any(report["side_effects"].values()):
            report["overall"] = "FAIL"
            report["failure"] = {
                "code": "forbidden_side_effect",
                "stage": "provider_boundary",
                "artifact_family": "side_effects",
                "expected": {key: 0 for key in report["side_effects"]},
                "actual": report["side_effects"],
            }
        write_json(report_path, report)
        write_report_markdown(markdown_path, report)
        if report["overall"] != "PASS":
            print(
                "FAIL "
                f"{report['failure']['code']}: "
                f"{report['failure'].get('stage')}/"
                f"{report['failure'].get('artifact_family')}"
            )
            return 3
        print(f"PASS {report_path}")
        return 0
    except ParityStop as exc:
        if "failure" not in report:
            report["failure"] = {
                "code": exc.code,
                "detail": exc.detail,
                **exc.context,
            }
        if report.get("overall") != "FAIL":
            report["overall"] = "STOP"
        write_json(report_path, report)
        write_report_markdown(markdown_path, report)
        print(f"STOP {exc.code}: {exc.detail}", file=sys.stderr)
        return 2


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--legacy-root", required=True)
    run.add_argument("--plugin-root", required=True)
    run.add_argument("--fixture-root", required=True)
    run.add_argument("--legacy-baseline", required=True)
    run.add_argument("--out-dir", required=True)
    target = commands.add_parser("target", help=argparse.SUPPRESS)
    target.add_argument("--engine-root", required=True)
    target.add_argument(
        "--target-kind",
        required=True,
        choices=("legacy", "plugin"),
    )
    target.add_argument("--fixture-root", required=True)
    target.add_argument("--workspace", required=True)
    target.add_argument("--report", required=True)
    target.add_argument(
        "--handoff-mode",
        choices=("web", "api", "both"),
        default="both",
    )
    return root


def main() -> int:
    args = parser().parse_args()
    if args.command == "target":
        return target_command(args)
    return harness_command(args)


if __name__ == "__main__":
    raise SystemExit(main())
