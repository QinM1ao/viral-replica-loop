#!/usr/bin/env python3
"""Fail-closed execution context for one Canonical Plugin Job."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
PACKAGE_NAME = "shotloom"
REQUIRED_WORKFLOW_RESOURCES = (
    ".codex-plugin/plugin.json",
    "engine/COST_POLICY.md",
    "engine/LOOP.md",
    "engine/QC_RULES.md",
    "engine/gates/source_blueprint_gate.md",
    "engine/rules/STAGE_RULES.json",
    "engine/tools/prepare_source_blueprint.py",
    "engine/tools/run_next_loop_round.py",
    "engine/workers/source_blueprint_worker.md",
    "profiles/builtin/generic_product.json",
    "scripts/run-canonical-job.py",
)
WORKFLOW_RESOURCE_ROOTS = (
    "skills",
    "engine/.agents/skills",
    "engine/.codex/agents",
    "engine/client-profiles",
    "engine/gates",
    "engine/rules",
    "engine/scripts",
    "engine/tools",
    "engine/workers",
    "profiles/builtin",
)


class ExecutionContextError(ValueError):
    pass


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def paths_overlap(first: Path, second: Path) -> bool:
    first = first.resolve()
    second = second.resolve()
    return _is_within(first, second) or _is_within(second, first)


def _absolute_root(payload: dict[str, Any], field: str) -> Path:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ExecutionContextError(
            f"{field} must be a non-empty absolute path"
        )
    path = Path(value)
    if not path.is_absolute():
        raise ExecutionContextError(
            f"{field} must be a non-empty absolute path"
        )
    return path.resolve()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_plugin_root(plugin_root: Path) -> dict[str, Any]:
    plugin_root = Path(plugin_root).resolve()
    if not plugin_root.is_dir():
        raise ExecutionContextError(f"Plugin Root is unavailable: {plugin_root}")
    manifest_path = plugin_root / ".codex-plugin" / "plugin.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise ExecutionContextError(
            f"missing or invalid plugin resource: {manifest_path}"
        ) from exc
    if manifest.get("name") != PACKAGE_NAME or manifest.get("skills") != "./skills/":
        raise ExecutionContextError(
            "plugin manifest does not identify the canonical shotloom package"
        )
    for relative in REQUIRED_WORKFLOW_RESOURCES:
        path = plugin_root / relative
        if not path.is_file() or path.is_symlink():
            raise ExecutionContextError(
                f"missing plugin resource: {path}; root fallback is forbidden"
            )
    return manifest


def _workflow_resource_paths(plugin_root: Path) -> tuple[str, ...]:
    resources = set(REQUIRED_WORKFLOW_RESOURCES)
    for relative_root in WORKFLOW_RESOURCE_ROOTS:
        root = plugin_root / relative_root
        if not root.is_dir() or root.is_symlink():
            raise ExecutionContextError(
                f"missing plugin resource: {root}; root fallback is forbidden"
            )
        for path in root.rglob("*"):
            if path.is_symlink():
                raise ExecutionContextError(
                    f"plugin workflow resource cannot be a symlink: {path}"
                )
            if path.is_file():
                resources.add(path.relative_to(plugin_root).as_posix())
    return tuple(sorted(resources))


def build_workflow_contract(plugin_root: Path) -> dict[str, Any]:
    plugin_root = Path(plugin_root).resolve()
    manifest = validate_plugin_root(plugin_root)
    resources = []
    digest = hashlib.sha256()
    for relative in _workflow_resource_paths(plugin_root):
        path = plugin_root / relative
        file_digest = _file_sha256(path)
        resources.append({"path": relative, "sha256": file_digest})
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(file_digest))
    return {
        "schema_version": SCHEMA_VERSION,
        "plugin_version": manifest["version"],
        "sha256": digest.hexdigest(),
        "resources": resources,
    }


@dataclass(frozen=True)
class CanonicalExecutionContext:
    plugin_root: Path
    workspace_root: Path
    state_root: Path
    job_root: Path
    job_id: str
    workflow_contract: dict[str, Any]

    @property
    def contract_root(self) -> Path:
        return self.plugin_root / "engine"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "layout": "canonical",
            "plugin_root": str(self.plugin_root),
            "contract_root": str(self.contract_root),
            "workspace_root": str(self.workspace_root),
            "state_root": str(self.state_root),
            "job_root": str(self.job_root),
            "job_id": self.job_id,
            "workflow_contract": self.workflow_contract,
        }

    def validate(self) -> None:
        plugin_root = self.plugin_root.resolve()
        workspace_root = self.workspace_root.resolve()
        state_root = self.state_root.resolve()
        job_root = self.job_root.resolve()
        if paths_overlap(plugin_root, workspace_root):
            raise ExecutionContextError(
                "Plugin Root and Workspace Root overlap; canonical execution stopped"
            )
        if not workspace_root.is_dir():
            raise ExecutionContextError(
                f"Workspace Root is unavailable: {workspace_root}"
            )
        if not _is_within(state_root, workspace_root):
            raise ExecutionContextError("state_root escapes the selected Workspace")
        if not _is_within(job_root, workspace_root):
            raise ExecutionContextError("job_root escapes the selected Workspace")
        if job_root != workspace_root / "jobs" / self.job_id:
            raise ExecutionContextError("job_root does not match the current Job")
        current_contract = build_workflow_contract(plugin_root)
        if current_contract != self.workflow_contract:
            raise ExecutionContextError(
                "workflow contract changed after the launcher bound this Job"
            )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CanonicalExecutionContext":
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise ExecutionContextError("unsupported execution context schema")
        if payload.get("layout") != "canonical":
            raise ExecutionContextError("execution context is not canonical")
        job_id = str(payload.get("job_id") or "").strip()
        if not job_id:
            raise ExecutionContextError("execution context has no current Job")
        context = cls(
            plugin_root=_absolute_root(payload, "plugin_root"),
            workspace_root=_absolute_root(payload, "workspace_root"),
            state_root=_absolute_root(payload, "state_root"),
            job_root=_absolute_root(payload, "job_root"),
            job_id=job_id,
            workflow_contract=dict(payload.get("workflow_contract") or {}),
        )
        expected_contract_root = context.contract_root.resolve()
        supplied_contract_root = _absolute_root(payload, "contract_root")
        if supplied_contract_root != expected_contract_root:
            raise ExecutionContextError(
                "contract_root does not belong to the bound Plugin Root"
            )
        context.validate()
        return context

    @classmethod
    def load(cls, path: Path) -> "CanonicalExecutionContext":
        path = Path(path)
        if not path.is_absolute():
            raise ExecutionContextError(
                "execution context path must be absolute"
            )
        if path.is_symlink():
            raise ExecutionContextError(
                f"execution context cannot be a symbolic link: {path}"
            )
        path = path.resolve()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise ExecutionContextError(
                f"execution context is unavailable: {path}"
            ) from exc
        context = cls.from_dict(payload)
        if path.parent != context.state_root:
            raise ExecutionContextError(
                "execution context must live in the selected Workspace state root"
            )
        return context
