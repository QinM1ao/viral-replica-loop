#!/usr/bin/env python3
"""Freeze and verify the byte-level LegacyLayout migration baseline."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import io
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


SOURCE_POLICY = "migration/policies/legacy-source-closure-v1.json"
RETENTION_POLICY = "migration/policies/migration-retention-v1.json"
FIXTURE_POLICY = "migration/policies/product-fixture-v1.json"
PARITY_POLICY = "migration/policies/parity-policy-v1.json"
SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")
SANDBOX_PROFILE = (
    '(version 1)(allow default)'
    '(deny network-outbound (require-not (remote ip "localhost:*")))'
)
SOCKET_GUARD_SOURCE = """\
import ipaddress
import socket

_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex
_original_getaddrinfo = socket.getaddrinfo


def _loopback_host(host):
    if isinstance(host, bytes):
        host = host.decode("ascii", errors="ignore")
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _guard_address(address):
    if isinstance(address, tuple) and address and not _loopback_host(address[0]):
        raise PermissionError("legacy baseline no-spend guard denied external network")


def _guarded_connect(self, address):
    _guard_address(address)
    return _original_connect(self, address)


def _guarded_connect_ex(self, address):
    _guard_address(address)
    return _original_connect_ex(self, address)


def _guarded_getaddrinfo(host, *args, **kwargs):
    if not _loopback_host(host):
        raise PermissionError("legacy baseline no-spend guard denied external DNS")
    return _original_getaddrinfo(host, *args, **kwargs)


socket.socket.connect = _guarded_connect
socket.socket.connect_ex = _guarded_connect_ex
socket.getaddrinfo = _guarded_getaddrinfo
"""
SENSITIVE_ENV_MARKERS = (
    "API_KEY",
    "PASSWORD",
    "SECRET",
    "TOKEN",
    "CREDENTIAL",
    "AUTHORIZATION",
)
FORBIDDEN_TEST_ENV_NAMES = {
    "VREP_ACCEPTANCE_JOB_ID",
    "VIRAL_REPLICA_ALLOW_PROVIDER_SUBMIT",
    "VIRAL_REPLICA_GENERATION_APPROVED",
}


class BaselineError(RuntimeError):
    pass


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


def identity(prefix: str, value: Any) -> str:
    return f"{prefix}-{sha256_bytes(canonical_bytes(value))}"


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BaselineError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BaselineError(f"JSON root must be an object: {path}")
    return value


def atomic_write_json(path: Path, payload: dict[str, Any], *, immutable: bool) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if path.exists():
        current = path.read_text(encoding="utf-8")
        if current == encoded:
            return
        if immutable:
            raise BaselineError(f"refusing to replace immutable baseline: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def root_relative_path(root: Path, value: str, *, label: str) -> tuple[Path, str]:
    candidate = Path(value)
    if candidate.is_absolute():
        raise BaselineError(f"{label} must be root-relative: {value}")
    normalized = PurePosixPath(value)
    if not value or ".." in normalized.parts:
        raise BaselineError(f"{label} escapes the root: {value}")
    absolute = root / Path(*normalized.parts)
    return absolute, normalized.as_posix()


def policy_reference(root: Path, relative_path: str) -> dict[str, str]:
    path, normalized = root_relative_path(root, relative_path, label="policy path")
    if not path.is_file():
        raise BaselineError(f"missing policy: {normalized}")
    digest = sha256_bytes(path.read_bytes())
    payload = load_json(path)
    policy_id = payload.get("policy_id")
    if not isinstance(policy_id, str) or not policy_id:
        raise BaselineError(f"policy_id is required: {normalized}")
    return {
        "path": normalized,
        "sha256": digest,
        "policy_id": policy_id,
    }


def git_tracked_paths(root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return set()
    return {
        item.decode("utf-8", errors="surrogateescape")
        for item in result.stdout.split(b"\0")
        if item
    }


def matches(relative_path: str, patterns: Iterable[str]) -> bool:
    path = PurePosixPath(relative_path)
    return any(path.match(pattern) for pattern in patterns)


def selector_paths(root: Path, selector: dict[str, Any]) -> list[tuple[Path, str]]:
    if "path" in selector:
        path_value = selector["path"]
        if not isinstance(path_value, str):
            raise BaselineError("selector path must be a string")
        path, normalized = root_relative_path(root, path_value, label="selector path")
        if not path.exists() and not path.is_symlink():
            if selector.get("required", True):
                raise BaselineError(f"missing required baseline object: {normalized}")
            return []
        return [(path, normalized)]

    root_value = selector.get("root")
    if not isinstance(root_value, str):
        raise BaselineError("selector must declare path or root")
    selector_root, normalized_root = root_relative_path(
        root,
        root_value,
        label="selector root",
    )
    if not selector_root.is_dir():
        if selector.get("required", True):
            raise BaselineError(f"missing required selector root: {normalized_root}")
        return []

    includes = selector.get("include", ["**"])
    excludes = selector.get("exclude", [])
    if not isinstance(includes, list) or not all(
        isinstance(pattern, str) for pattern in includes
    ):
        raise BaselineError(f"selector include must be a string list: {normalized_root}")
    if not isinstance(excludes, list) or not all(
        isinstance(pattern, str) for pattern in excludes
    ):
        raise BaselineError(f"selector exclude must be a string list: {normalized_root}")

    selected: list[tuple[Path, str]] = []
    for directory, child_directories, filenames in os.walk(
        selector_root,
        topdown=True,
        followlinks=False,
    ):
        directory_path = Path(directory)
        symlink_directories = []
        retained_directories = []
        for name in sorted(child_directories):
            child = directory_path / name
            if child.is_symlink():
                symlink_directories.append(name)
            else:
                retained_directories.append(name)
        child_directories[:] = retained_directories

        for name in sorted(filenames + symlink_directories):
            path = directory_path / name
            relative_to_selector = path.relative_to(selector_root).as_posix()
            if not matches(relative_to_selector, includes):
                continue
            if matches(relative_to_selector, excludes):
                continue
            selected.append((path, path.relative_to(root).as_posix()))
    return selected


def path_within(path: Path, boundary: Path) -> bool:
    try:
        path.relative_to(boundary)
    except ValueError:
        return False
    return True


def hash_regular_file(path: Path, relative_path: str) -> tuple[str, int, int]:
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, os.O_RDONLY | no_follow)
    except OSError as exc:
        raise BaselineError(f"cannot open baseline object {relative_path}: {exc}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise BaselineError(f"unsupported baseline object type: {relative_path}")
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    stable_fields_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_mode,
    )
    stable_fields_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_mode,
    )
    if stable_fields_before != stable_fields_after:
        raise BaselineError(f"source changed while hashing: {relative_path}")
    return digest.hexdigest(), before.st_size, before.st_mode


def snapshot_object(
    root: Path,
    path: Path,
    relative_path: str,
    selector: dict[str, Any],
    tracked_paths: set[str],
) -> dict[str, Any]:
    try:
        before = path.lstat()
    except OSError as exc:
        raise BaselineError(f"cannot inspect baseline object {relative_path}: {exc}") from exc

    common = {
        "path": relative_path,
        "role": selector["role"],
        "reason": selector["reason"],
        "git_state": "tracked" if relative_path in tracked_paths else "not_in_git",
    }
    if "retention" in selector:
        common["retention"] = selector["retention"]

    if stat.S_ISLNK(before.st_mode):
        target = os.readlink(path)
        after = path.lstat()
        if (
            before.st_dev,
            before.st_ino,
            before.st_mtime_ns,
            before.st_mode,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_mtime_ns,
            after.st_mode,
        ) or target != os.readlink(path):
            raise BaselineError(f"source changed while reading link: {relative_path}")
        resolved_target = (path.parent / target).resolve(strict=False)
        if Path(target).is_absolute() or not path_within(
            resolved_target,
            root.resolve(),
        ):
            raise BaselineError(f"boundary-escaping symlink: {relative_path}")
        return {
            **common,
            "kind": "symlink",
            "link_target": target,
            "sha256": sha256_bytes(target.encode("utf-8")),
            "size_bytes": len(target.encode("utf-8")),
            "mode": oct(stat.S_IMODE(before.st_mode)),
        }

    digest, size_bytes, mode = hash_regular_file(path, relative_path)
    return {
        **common,
        "kind": "file",
        "sha256": digest,
        "size_bytes": size_bytes,
        "mode": oct(stat.S_IMODE(mode)),
    }


def object_identity_view(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if key != "git_state"}


def snapshot(
    root: Path,
    selectors: list[dict[str, Any]],
    *,
    id_prefix: str,
) -> dict[str, Any]:
    tracked_paths = git_tracked_paths(root)
    selected: dict[str, tuple[Path, dict[str, Any]]] = {}
    for selector in selectors:
        if not isinstance(selector, dict):
            raise BaselineError("selectors must contain objects")
        for required_field in ("role", "reason"):
            if not isinstance(selector.get(required_field), str):
                raise BaselineError(f"selector requires {required_field}")
        for path, relative_path in selector_paths(root, selector):
            if relative_path in selected:
                raise BaselineError(
                    f"baseline object has multiple classifications: {relative_path}"
                )
            selected[relative_path] = (path, selector)

    objects = [
        snapshot_object(root, path, relative_path, selector, tracked_paths)
        for relative_path, (path, selector) in sorted(selected.items())
    ]
    identity_objects = [object_identity_view(item) for item in objects]
    return {
        "id": identity(id_prefix, identity_objects),
        "objects": objects,
    }


def source_and_protected_snapshots(
    root: Path,
    policy_path: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    path, _ = root_relative_path(root, policy_path, label="source policy")
    policy = load_json(path)
    source_selectors = policy.get("source_selectors")
    protected_selectors = policy.get("protected_selectors")
    if not isinstance(source_selectors, list) or not source_selectors:
        raise BaselineError("source policy requires source_selectors")
    if not isinstance(protected_selectors, list) or not protected_selectors:
        raise BaselineError("source policy requires protected_selectors")
    return (
        policy,
        snapshot(root, source_selectors, id_prefix="source-closure"),
        snapshot(root, protected_selectors, id_prefix="legacy-protected"),
    )


def command_contract(command: str) -> dict[str, Any]:
    executable = shutil.which(command)
    if executable is None:
        return {"available": False, "command": command}
    resolved = Path(executable).resolve()
    version = subprocess.run(
        [executable, "-version"],
        text=True,
        capture_output=True,
        check=False,
    )
    first_line = (version.stdout or version.stderr).splitlines()
    return {
        "available": version.returncode == 0,
        "command": command,
        "path": str(resolved),
        "sha256": sha256_bytes(resolved.read_bytes()),
        "version_line": first_line[0] if first_line else "",
    }


def runtime_contract(root: Path) -> dict[str, Any]:
    requirements = root / "requirements.txt"
    payload: dict[str, Any] = {
        "host": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "python": {
            "executable": str(Path(sys.executable).resolve()),
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
        },
        "ffmpeg": command_contract("ffmpeg"),
        "ffprobe": command_contract("ffprobe"),
        "requirements": {
            "path": "requirements.txt",
            "present": requirements.is_file(),
            "sha256": (
                sha256_bytes(requirements.read_bytes())
                if requirements.is_file()
                else None
            ),
        },
    }
    payload["runtime_contract_id"] = identity("runtime", payload)
    return payload


def workflow_contract(source_snapshot: dict[str, Any]) -> dict[str, Any]:
    workflow_roles = {
        "skill",
        "workflow_rule",
        "worker",
        "gate",
        "profile",
        "engine_entrypoint",
    }
    objects = [
        object_identity_view(item)
        for item in source_snapshot["objects"]
        if item["role"] in workflow_roles
    ]
    return {
        "workflow_contract_id": identity("workflow", objects),
        "roles": sorted(workflow_roles),
        "object_count": len(objects),
    }


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def flatten_tests(suite: unittest.TestSuite) -> list[unittest.TestCase]:
    flattened: list[unittest.TestCase] = []
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            flattened.extend(flatten_tests(test))
        else:
            flattened.append(test)
    return flattened


@contextlib.contextmanager
def working_directory(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class RecordingResult(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.cases: dict[str, dict[str, Any]] = {}

    def _record(self, test: unittest.TestCase, status_value: str, **extra: Any) -> None:
        self.cases[test.id()] = {
            "test_id": test.id(),
            "status": status_value,
            **extra,
        }

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test, "PASS")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        detail = self._exc_info_to_string(err, test)
        self._record(
            test,
            "FAIL",
            detail_sha256=sha256_bytes(detail.encode("utf-8")),
        )

    def addError(self, test, err):
        super().addError(test, err)
        detail = self._exc_info_to_string(err, test)
        self._record(
            test,
            "ERROR",
            detail_sha256=sha256_bytes(detail.encode("utf-8")),
        )

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._record(test, "SKIP", reason=reason)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._record(test, "EXPECTED_FAILURE")

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._record(test, "UNEXPECTED_SUCCESS")


def load_test_suite(root: Path, discovery: dict[str, Any]) -> unittest.TestSuite:
    required = ("start_directory", "pattern")
    if any(not isinstance(discovery.get(key), str) for key in required):
        raise BaselineError("test_discovery requires string paths and pattern")
    top_level = discovery.get("top_level_directory")
    if top_level is not None and not isinstance(top_level, str):
        raise BaselineError("test_discovery top_level_directory must be null or a string")
    loader = unittest.TestLoader()
    root_string = str(root)
    if root_string not in sys.path:
        sys.path.insert(0, root_string)
    with working_directory(root):
        return loader.discover(
            start_dir=discovery["start_directory"],
            pattern=discovery["pattern"],
            top_level_dir=top_level,
        )


def load_named_tests(
    root: Path,
    discovery: dict[str, Any],
    test_ids: list[str],
) -> unittest.TestSuite:
    start_directory = discovery.get("start_directory")
    if not isinstance(start_directory, str):
        raise BaselineError("test_discovery requires start_directory")
    tests_path, _ = root_relative_path(
        root,
        start_directory,
        label="test discovery start directory",
    )
    for import_root in (str(root), str(tests_path)):
        if import_root not in sys.path:
            sys.path.insert(0, import_root)
    loader = unittest.TestLoader()
    with working_directory(root):
        return loader.loadTestsFromNames(test_ids)


def stable_test_projection(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_closure_id": payload["source_closure_after"]["id"],
        "protected_legacy_snapshot_id": payload["protected_after"]["id"],
        "runtime_contract_id": payload["runtime_after"]["runtime_contract_id"],
        "test_manifest": payload["test_manifest"],
        "summary": payload["summary"],
        "cases": payload["cases"],
        "no_spend_guard": payload["no_spend_guard"],
    }


def snapshot_evidence(snapshot_value: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": snapshot_value["id"],
        "object_count": len(snapshot_value["objects"]),
        "size_bytes": sum(item["size_bytes"] for item in snapshot_value["objects"]),
    }


def run_tests_in_sandbox_child(
    root: Path,
    source_policy_path: str,
    payload_out: Path,
    partition: str,
    guard_kind: str,
) -> int:
    policy, source_before, protected_before = source_and_protected_snapshots(
        root,
        source_policy_path,
    )
    runtime_before = runtime_contract(root)
    discovery = policy.get("test_discovery")
    if not isinstance(discovery, dict):
        raise BaselineError("source policy requires test_discovery")
    nested_test_ids_value = discovery.get("nested_sandbox_test_ids", [])
    if not isinstance(nested_test_ids_value, list) or not all(
        isinstance(test_id, str) for test_id in nested_test_ids_value
    ):
        raise BaselineError("nested_sandbox_test_ids must be a string list")
    nested_test_ids = set(nested_test_ids_value)
    if partition == "external-deny":
        suite = load_test_suite(root, discovery)
        all_tests = flatten_tests(suite)
        all_test_ids = {test.id() for test in all_tests}
        missing_nested_ids = nested_test_ids - all_test_ids
        if missing_nested_ids:
            raise BaselineError(
                "nested sandbox test ID is not in the discovered manifest: "
                + ", ".join(sorted(missing_nested_ids))
            )
        selected_tests = [
            test for test in all_tests if test.id() not in nested_test_ids
        ]
    elif partition == "nested-sandbox":
        suite = load_named_tests(
            root,
            discovery,
            sorted(nested_test_ids),
        )
        selected_tests = flatten_tests(suite)
        loaded_ids = {test.id() for test in selected_tests}
        if loaded_ids != nested_test_ids:
            raise BaselineError(
                "nested sandbox test IDs did not load exactly: "
                + ", ".join(sorted(loaded_ids ^ nested_test_ids))
            )
    else:
        raise BaselineError(f"unknown test partition: {partition}")
    suite = unittest.TestSuite(selected_tests)
    test_ids = sorted(test.id() for test in selected_tests)
    result = RecordingResult()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
        io.StringIO()
    ):
        suite.run(result)
    _, source_after, protected_after = source_and_protected_snapshots(
        root,
        source_policy_path,
    )
    runtime_after = runtime_contract(root)

    cases = [result.cases[test_id] for test_id in sorted(result.cases)]
    counts: dict[str, int] = {}
    for case in cases:
        counts[case["status"]] = counts.get(case["status"], 0) + 1
    test_manifest = {
        "test_ids": test_ids,
        "test_manifest_id": identity("tests", test_ids),
    }
    payload: dict[str, Any] = {
        "schema_version": 1,
        "kind": "legacy_layout_no_spend_test_partition",
        "executed_at": utc_now(),
        "partition": partition,
        "source_closure_before": snapshot_evidence(source_before),
        "source_closure_after": snapshot_evidence(source_after),
        "protected_before": snapshot_evidence(protected_before),
        "protected_after": snapshot_evidence(protected_after),
        "runtime_before": {
            "runtime_contract_id": runtime_before["runtime_contract_id"]
        },
        "runtime_after": {
            "runtime_contract_id": runtime_after["runtime_contract_id"]
        },
        "test_manifest": test_manifest,
        "summary": {
            "tests_run": result.testsRun,
            "successful": result.wasSuccessful(),
            "counts": counts,
        },
        "cases": cases,
        "no_spend_guard": {
            "kind": guard_kind,
            "network": "deny_external_allow_loopback",
            "guard_sha256": sha256_bytes(SOCKET_GUARD_SOURCE.encode("utf-8")),
            "provider_credentials": "removed",
            "python_subprocesses_guarded": True,
        },
    }
    payload["stable_result_id"] = identity(
        "test-result",
        stable_test_projection(payload),
    )
    atomic_write_json(payload_out, payload, immutable=False)
    stable = (
        source_before["id"] == source_after["id"]
        and protected_before["id"] == protected_after["id"]
        and runtime_before["runtime_contract_id"]
        == runtime_after["runtime_contract_id"]
    )
    return 0 if result.wasSuccessful() and stable else 1


def sanitized_test_environment() -> tuple[dict[str, str], list[str]]:
    environment: dict[str, str] = {}
    removed = []
    for key, value in os.environ.items():
        if key in FORBIDDEN_TEST_ENV_NAMES or any(
            marker in key.upper() for marker in SENSITIVE_ENV_MARKERS
        ):
            removed.append(key)
            continue
        environment[key] = value
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["VIRAL_REPLICA_NO_SPEND"] = "1"
    return environment, sorted(removed)


def run_test_partition(
    *,
    root: Path,
    source_policy: str,
    partition: str,
    output_path: Path,
    environment: dict[str, str],
    os_network_sandbox: bool,
) -> subprocess.CompletedProcess:
    guard_kind = (
        "macos_external_network_sandbox_and_python_socket_guard"
        if os_network_sandbox
        else "python_socket_guard_for_nested_sandbox_tests"
    )
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "_run-tests",
        "--root",
        str(root),
        "--source-policy",
        source_policy,
        "--payload-out",
        str(output_path),
        "--partition",
        partition,
        "--guard-kind",
        guard_kind,
    ]
    if os_network_sandbox:
        command = [
            str(SANDBOX_EXEC),
            "-p",
            SANDBOX_PROFILE,
            *command,
        ]
    child_environment = dict(environment)
    child_environment["VIRAL_REPLICA_BASELINE_TEST_PARTITION"] = partition
    return subprocess.run(
        command,
        cwd=root,
        env=child_environment,
        text=True,
        capture_output=True,
        check=False,
    )


def combine_test_partitions(
    partitions: list[dict[str, Any]],
    *,
    nested_test_ids: list[str],
) -> dict[str, Any]:
    expected_partitions = {"external-deny", "nested-sandbox"}
    actual_partitions = {payload.get("partition") for payload in partitions}
    if actual_partitions != expected_partitions:
        raise BaselineError("test run is missing a required no-spend partition")

    source_ids = {
        payload[key]["id"]
        for payload in partitions
        for key in ("source_closure_before", "source_closure_after")
    }
    protected_ids = {
        payload[key]["id"]
        for payload in partitions
        for key in ("protected_before", "protected_after")
    }
    runtime_ids = {
        payload[key]["runtime_contract_id"]
        for payload in partitions
        for key in ("runtime_before", "runtime_after")
    }
    if len(source_ids) != 1:
        raise BaselineError("source closure changed between test partitions")
    if len(protected_ids) != 1:
        raise BaselineError("protected legacy bytes changed between test partitions")
    if len(runtime_ids) != 1:
        raise BaselineError("runtime contract changed between test partitions")

    test_ids_by_partition = [
        set(payload["test_manifest"]["test_ids"]) for payload in partitions
    ]
    if test_ids_by_partition[0] & test_ids_by_partition[1]:
        raise BaselineError("test partitions overlap")
    combined_test_ids = sorted(test_ids_by_partition[0] | test_ids_by_partition[1])
    if set(nested_test_ids) != next(
        set(payload["test_manifest"]["test_ids"])
        for payload in partitions
        if payload["partition"] == "nested-sandbox"
    ):
        raise BaselineError("nested sandbox partition does not match its allowlist")

    cases = sorted(
        [
            case
            for payload in partitions
            for case in payload["cases"]
        ],
        key=lambda case: case["test_id"],
    )
    counts: dict[str, int] = {}
    for case in cases:
        counts[case["status"]] = counts.get(case["status"], 0) + 1
    successful = all(
        payload["summary"]["successful"] for payload in partitions
    )
    external = next(
        payload for payload in partitions if payload["partition"] == "external-deny"
    )
    nested = next(
        payload for payload in partitions if payload["partition"] == "nested-sandbox"
    )
    combined: dict[str, Any] = {
        "schema_version": 1,
        "kind": "legacy_layout_no_spend_test_run",
        "executed_at": utc_now(),
        "source_closure_before": external["source_closure_before"],
        "source_closure_after": nested["source_closure_after"],
        "protected_before": external["protected_before"],
        "protected_after": nested["protected_after"],
        "runtime_before": external["runtime_before"],
        "runtime_after": nested["runtime_after"],
        "test_manifest": {
            "test_ids": combined_test_ids,
            "test_manifest_id": identity("tests", combined_test_ids),
        },
        "summary": {
            "tests_run": sum(
                payload["summary"]["tests_run"] for payload in partitions
            ),
            "successful": successful,
            "counts": counts,
        },
        "cases": cases,
        "no_spend_guard": {
            "kind": "partitioned_fail_closed_external_network",
            "network": "deny_external_allow_loopback",
            "provider_credentials": "removed",
            "python_subprocesses_guarded": True,
            "external_partition": {
                "test_count": len(external["test_manifest"]["test_ids"]),
                "guard": external["no_spend_guard"]["kind"],
                "sandbox_profile_sha256": sha256_bytes(
                    SANDBOX_PROFILE.encode("utf-8")
                ),
            },
            "nested_sandbox_partition": {
                "test_ids": sorted(nested_test_ids),
                "guard": nested["no_spend_guard"]["kind"],
                "source_bytes_bound_by_source_closure": True,
            },
            "socket_guard_sha256": sha256_bytes(
                SOCKET_GUARD_SOURCE.encode("utf-8")
            ),
        },
        "partition_evidence": [
            {
                "partition": payload["partition"],
                "executed_at": payload["executed_at"],
                "test_manifest_id": payload["test_manifest"]["test_manifest_id"],
                "stable_result_id": payload["stable_result_id"],
            }
            for payload in sorted(
                partitions,
                key=lambda item: item["partition"],
            )
        ],
    }
    combined["stable_result_id"] = identity(
        "test-result",
        stable_test_projection(combined),
    )
    return combined


def command_run_tests(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if platform.system() != "Darwin" or not SANDBOX_EXEC.is_file():
        raise BaselineError("no-spend network guard requires macOS sandbox-exec")
    output_path, _ = root_relative_path(root, args.out, label="test run output")
    environment, removed = sanitized_test_environment()
    with tempfile.TemporaryDirectory(prefix="legacy-baseline-test-") as directory:
        guard_path = Path(directory) / "sitecustomize.py"
        guard_path.write_text(SOCKET_GUARD_SOURCE, encoding="utf-8")
        environment["PYTHONPATH"] = directory
        guard_preflight = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import socket\n"
                    "try:\n"
                    "    socket.create_connection(('203.0.113.1', 9), timeout=0.01)\n"
                    "except PermissionError:\n"
                    "    pass\n"
                    "else:\n"
                    "    raise SystemExit('external socket was not denied')\n"
                    "try:\n"
                    "    socket.getaddrinfo('example.invalid', 443)\n"
                    "except PermissionError:\n"
                    "    pass\n"
                    "else:\n"
                    "    raise SystemExit('external DNS was not denied')\n"
                ),
            ],
            cwd=root,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        if guard_preflight.returncode != 0:
            detail = (guard_preflight.stderr or guard_preflight.stdout).strip()
            raise BaselineError(f"no-spend socket guard preflight failed: {detail}")
        sandbox_preflight = subprocess.run(
            [
                str(SANDBOX_EXEC),
                "-p",
                SANDBOX_PROFILE,
                sys.executable,
                "-S",
                "-c",
                (
                    "import socket\n"
                    "try:\n"
                    "    socket.create_connection(('203.0.113.1', 9), timeout=0.01)\n"
                    "except PermissionError:\n"
                    "    pass\n"
                    "else:\n"
                    "    raise SystemExit('OS sandbox did not deny external socket')\n"
                ),
            ],
            cwd=root,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        if sandbox_preflight.returncode != 0:
            detail = (sandbox_preflight.stderr or sandbox_preflight.stdout).strip()
            raise BaselineError(f"macOS network sandbox preflight failed: {detail}")

        policy_path, _ = root_relative_path(
            root,
            args.source_policy,
            label="source policy",
        )
        discovery = load_json(policy_path).get("test_discovery", {})
        nested_test_ids = discovery.get("nested_sandbox_test_ids", [])
        partition_results = []
        partition_payloads = []
        for partition, os_network_sandbox in (
            ("external-deny", True),
            ("nested-sandbox", False),
        ):
            child_output = Path(directory) / f"{partition}.json"
            result = run_test_partition(
                root=root,
                source_policy=args.source_policy,
                partition=partition,
                output_path=child_output,
                environment=environment,
                os_network_sandbox=os_network_sandbox,
            )
            partition_results.append(result)
            if not child_output.is_file():
                detail = (result.stderr or result.stdout).strip()
                raise BaselineError(
                    f"{partition} test partition produced no result: {detail}"
                )
            partition_payloads.append(load_json(child_output))
        payload = combine_test_partitions(
            partition_payloads,
            nested_test_ids=nested_test_ids,
        )
    payload["sanitized_environment_names"] = removed
    atomic_write_json(output_path, payload, immutable=False)
    if any(result.returncode != 0 for result in partition_results) or not payload.get(
        "summary",
        {},
    ).get("successful"):
        raise BaselineError(
            "legacy no-spend test run failed or changed protected baseline bytes"
        )
    print(payload["stable_result_id"])
    return 0


def validate_test_runs(
    root: Path,
    run_paths: list[str],
    source_snapshot: dict[str, Any],
    protected_snapshot: dict[str, Any],
    current_runtime: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(run_paths) != 2:
        raise BaselineError("exactly two no-spend test runs are required")
    loaded = []
    for relative_path in run_paths:
        path, normalized = root_relative_path(root, relative_path, label="test run")
        payload = load_json(path)
        payload["_evidence"] = {
            "path": normalized,
            "sha256": sha256_bytes(path.read_bytes()),
        }
        loaded.append(payload)

    if loaded[0].get("stable_result_id") != loaded[1].get("stable_result_id"):
        raise BaselineError("test runs are not reproducible")
    for payload in loaded:
        if payload.get("kind") != "legacy_layout_no_spend_test_run":
            raise BaselineError("invalid test run kind")
        if payload.get("stable_result_id") != identity(
            "test-result",
            stable_test_projection(payload),
        ):
            raise BaselineError("test run stable_result_id is invalid")
        if not payload.get("summary", {}).get("successful"):
            raise BaselineError("test run did not pass")
        guard = payload.get("no_spend_guard", {})
        if (
            guard.get("kind") != "partitioned_fail_closed_external_network"
            or guard.get("network") != "deny_external_allow_loopback"
            or guard.get("provider_credentials") != "removed"
            or guard.get("python_subprocesses_guarded") is not True
        ):
            raise BaselineError("test run lacks the required no-spend guard")
        for key in ("source_closure_before", "source_closure_after"):
            if payload.get(key, {}).get("id") != source_snapshot["id"]:
                raise BaselineError("test run source closure does not match current bytes")
        for key in ("protected_before", "protected_after"):
            if payload.get(key, {}).get("id") != protected_snapshot["id"]:
                raise BaselineError("test run changed protected legacy bytes")
        for key in ("runtime_before", "runtime_after"):
            if (
                payload.get(key, {}).get("runtime_contract_id")
                != current_runtime["runtime_contract_id"]
            ):
                raise BaselineError("test run runtime contract does not match")

    first = loaded[0]
    test_manifest = first["test_manifest"]
    if loaded[1].get("test_manifest") != test_manifest:
        raise BaselineError("test runs discovered different test IDs")
    evidence = [
        {
            **payload["_evidence"],
            "executed_at": payload["executed_at"],
            "stable_result_id": payload["stable_result_id"],
        }
        for payload in loaded
    ]
    return evidence, test_manifest


def command_freeze(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    policy, source_snapshot, protected_snapshot = source_and_protected_snapshots(
        root,
        args.source_policy,
    )
    current_runtime = runtime_contract(root)
    test_runs, test_manifest = validate_test_runs(
        root,
        args.test_run,
        source_snapshot,
        protected_snapshot,
        current_runtime,
    )
    policy_refs = {
        "source_closure": policy_reference(root, args.source_policy),
        "migration_retention": policy_reference(root, args.retention_policy),
        "product_fixture": policy_reference(root, args.fixture_policy),
        "parity": policy_reference(root, args.parity_policy),
    }
    workflow = workflow_contract(source_snapshot)
    identity_basis = {
        "source_closure_id": source_snapshot["id"],
        "protected_legacy_snapshot_id": protected_snapshot["id"],
        "runtime_contract_id": current_runtime["runtime_contract_id"],
        "workflow_contract_id": workflow["workflow_contract_id"],
        "test_manifest_id": test_manifest["test_manifest_id"],
        "test_result_id": test_runs[0]["stable_result_id"],
        "policy_sha256": {
            name: reference["sha256"] for name, reference in policy_refs.items()
        },
    }
    identity_digest = sha256_bytes(canonical_bytes(identity_basis))
    git_head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )
    payload = {
        "schema_version": 1,
        "kind": "legacy_layout_baseline",
        "baseline_id": f"legacy-{dt.datetime.now().strftime('%Y%m%d')}-{identity_digest}",
        "identity_sha256": identity_digest,
        "git_head": (
            git_head.stdout.strip() if git_head.returncode == 0 else "not-a-git-checkout"
        ),
        "git_head_is_informational_only": True,
        "policies": policy_refs,
        "source_closure": source_snapshot,
        "protected_legacy_snapshot": protected_snapshot,
        "runtime_contract": current_runtime,
        "workflow_contract": workflow,
        "test_manifest": test_manifest,
        "test_runs": test_runs,
        "test_reproducibility": {
            "result": "PASS",
            "stable_result_id": test_runs[0]["stable_result_id"],
            "consecutive_run_count": 2,
            "provider_submissions_allowed": False,
        },
        "identity_basis": identity_basis,
        "policy_contract": {
            "source_policy_id": policy["policy_id"],
            "unclassified_source_object": "STOP",
            "git_head_export_allowed": False,
            "whole_tree_copy_allowed": False,
        },
    }
    output_path, _ = root_relative_path(root, args.out, label="baseline output")
    atomic_write_json(output_path, payload, immutable=True)
    print(payload["baseline_id"])
    return 0


def compare_snapshots(
    expected: dict[str, Any],
    actual: dict[str, Any],
    *,
    label: str,
) -> list[str]:
    expected_by_path = {item["path"]: item for item in expected["objects"]}
    actual_by_path = {item["path"]: item for item in actual["objects"]}
    errors = []
    for path in sorted(expected_by_path.keys() - actual_by_path.keys()):
        errors.append(f"missing {label} object: {path}")
    for path in sorted(actual_by_path.keys() - expected_by_path.keys()):
        errors.append(f"added {label} object: {path}")
    for path in sorted(expected_by_path.keys() & actual_by_path.keys()):
        if object_identity_view(expected_by_path[path]) != object_identity_view(
            actual_by_path[path]
        ):
            errors.append(f"changed {label} object: {path}")
    return errors


def command_verify(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    baseline_path, _ = root_relative_path(root, args.baseline, label="baseline")
    baseline = load_json(baseline_path)
    errors = []
    if baseline.get("kind") != "legacy_layout_baseline":
        errors.append("invalid baseline kind")
    if baseline.get("schema_version") != 1:
        errors.append("unsupported baseline schema")

    policies = baseline.get("policies", {})
    for name, reference in sorted(policies.items()):
        path, _ = root_relative_path(root, reference["path"], label=f"{name} policy")
        if not path.is_file():
            errors.append(f"missing policy: {reference['path']}")
        elif sha256_bytes(path.read_bytes()) != reference["sha256"]:
            errors.append(f"changed policy: {reference['path']}")

    source_reference = policies.get("source_closure", {})
    source_policy_path = source_reference.get("path")
    if isinstance(source_policy_path, str) and not errors:
        _, source_snapshot, protected_snapshot = source_and_protected_snapshots(
            root,
            source_policy_path,
        )
        errors.extend(
            compare_snapshots(
                baseline["source_closure"],
                source_snapshot,
                label="source",
            )
        )
        errors.extend(
            compare_snapshots(
                baseline["protected_legacy_snapshot"],
                protected_snapshot,
                label="protected legacy",
            )
        )
        current_runtime = runtime_contract(root)
        if (
            current_runtime["runtime_contract_id"]
            != baseline.get("runtime_contract", {}).get("runtime_contract_id")
        ):
            errors.append("changed runtime contract")

    for evidence in baseline.get("test_runs", []):
        path, _ = root_relative_path(root, evidence["path"], label="test evidence")
        if not path.is_file():
            errors.append(f"missing test evidence: {evidence['path']}")
        elif sha256_bytes(path.read_bytes()) != evidence["sha256"]:
            errors.append(f"changed test evidence: {evidence['path']}")

    identity_basis = baseline.get("identity_basis")
    if not isinstance(identity_basis, dict):
        errors.append("missing baseline identity basis")
    else:
        expected_digest = sha256_bytes(canonical_bytes(identity_basis))
        if expected_digest != baseline.get("identity_sha256"):
            errors.append("invalid baseline identity")
        baseline_id = baseline.get("baseline_id", "")
        if not baseline_id.endswith(expected_digest):
            errors.append("baseline ID does not bind identity")

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("PASS")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_tests = subparsers.add_parser(
        "run-tests",
        help="run the frozen LegacyLayout suite under a no-network guard",
    )
    run_tests.add_argument("--root", required=True)
    run_tests.add_argument("--source-policy", default=SOURCE_POLICY)
    run_tests.add_argument("--out", required=True)
    run_tests.set_defaults(handler=command_run_tests)

    child = subparsers.add_parser("_run-tests")
    child.add_argument("--root", required=True)
    child.add_argument("--source-policy", required=True)
    child.add_argument("--payload-out", required=True)
    child.add_argument(
        "--partition",
        choices=("external-deny", "nested-sandbox"),
        required=True,
    )
    child.add_argument("--guard-kind", required=True)

    freeze = subparsers.add_parser("freeze")
    freeze.add_argument("--root", required=True)
    freeze.add_argument("--source-policy", default=SOURCE_POLICY)
    freeze.add_argument("--retention-policy", default=RETENTION_POLICY)
    freeze.add_argument("--fixture-policy", default=FIXTURE_POLICY)
    freeze.add_argument("--parity-policy", default=PARITY_POLICY)
    freeze.add_argument("--test-run", action="append", default=[])
    freeze.add_argument("--out", required=True)
    freeze.set_defaults(handler=command_freeze)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--root", required=True)
    verify.add_argument("--baseline", required=True)
    verify.set_defaults(handler=command_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "_run-tests":
            return run_tests_in_sandbox_child(
                Path(args.root).resolve(),
                args.source_policy,
                Path(args.payload_out),
                args.partition,
                args.guard_kind,
            )
        return args.handler(args)
    except BaselineError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
