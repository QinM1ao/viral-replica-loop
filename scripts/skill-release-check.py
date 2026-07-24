#!/usr/bin/env python3
"""Structural release check for local governed skill packages."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REQUIRED_MANIFEST_KEYS = {
    "name",
    "version",
    "owner",
    "updated_at",
    "review_cadence",
    "status",
    "maturity_tier",
    "lifecycle_stage",
    "input_files",
    "output_contract",
    "rollback_boundary",
    "trust_report",
    "output_quality_scorecard",
}

ALLOWED_STATUS = {"experimental", "active", "deprecated"}
ALLOWED_TIERS = {"scaffold", "production", "library", "governed"}
ALLOWED_REVIEW_CADENCE = {
    "monthly",
    "quarterly",
    "semiannual",
    "annual",
    "per-release",
}
REQUIRED_TRIGGER_KINDS = {"positive", "negative", "near_neighbor"}
MIN_TRIGGER_CASES = 5
MIN_OUTPUT_CASES = 3


class CheckResult:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def load_json(path: Path, result: CheckResult) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        result.error(f"Missing JSON file: {path}")
    except json.JSONDecodeError as exc:
        result.error(f"Invalid JSON in {path}: {exc}")
    return None


def require_relative_file(skill_dir: Path, rel: str, result: CheckResult) -> None:
    target = skill_dir / rel
    if not target.exists():
        result.error(f"{skill_dir}: missing referenced file {rel}")


def validate_manifest(skill_dir: Path, result: CheckResult) -> dict | None:
    manifest_path = skill_dir / "manifest.json"
    data = load_json(manifest_path, result)
    if not isinstance(data, dict):
        return None

    missing = sorted(REQUIRED_MANIFEST_KEYS - data.keys())
    for key in missing:
        result.error(f"{manifest_path}: missing manifest key {key}")

    if data.get("status") not in ALLOWED_STATUS:
        result.error(f"{manifest_path}: invalid status {data.get('status')!r}")
    if data.get("maturity_tier") not in ALLOWED_TIERS:
        result.error(f"{manifest_path}: invalid maturity_tier {data.get('maturity_tier')!r}")
    if data.get("lifecycle_stage") not in ALLOWED_TIERS:
        result.error(f"{manifest_path}: invalid lifecycle_stage {data.get('lifecycle_stage')!r}")
    if data.get("review_cadence") not in ALLOWED_REVIEW_CADENCE:
        result.error(f"{manifest_path}: invalid review_cadence {data.get('review_cadence')!r}")

    for item in data.get("input_files", []):
        if not isinstance(item, dict):
            result.error(f"{manifest_path}: input_files entries must be objects")
            continue
        if item.get("evidence") != "file-backed fixture":
            result.warn(f"{manifest_path}: input file {item.get('path')} is not labeled file-backed fixture")

    if not data.get("output_contract"):
        result.error(f"{manifest_path}: output_contract must not be empty")
    if not data.get("rollback_boundary"):
        result.error(f"{manifest_path}: rollback_boundary must not be empty")

    for rel_key in ["trust_report", "output_quality_scorecard"]:
        value = data.get(rel_key)
        if isinstance(value, str):
            require_relative_file(skill_dir, value, result)
        else:
            result.error(f"{manifest_path}: {rel_key} must be a relative path")

    evals = data.get("evals", {})
    if not isinstance(evals, dict):
        result.error(f"{manifest_path}: evals must be an object")
    else:
        for key in ["trigger_cases", "output_cases"]:
            value = evals.get(key)
            if isinstance(value, str):
                require_relative_file(skill_dir, value, result)
            else:
                result.error(f"{manifest_path}: evals.{key} must be a relative path")

    if data.get("missing_evidence"):
        result.warn(f"{manifest_path}: release has missing evidence: {', '.join(data['missing_evidence'])}")
    if data.get("release_state") != "release_ready":
        result.warn(f"{manifest_path}: release_state is {data.get('release_state')!r}")

    return data


def validate_interface(skill_dir: Path, result: CheckResult) -> None:
    interface = skill_dir / "agents" / "interface.yaml"
    if not interface.exists():
        result.error(f"{skill_dir}: missing agents/interface.yaml")
        return
    text = interface.read_text(encoding="utf-8")
    for needle in ["interface:", "display_name:", "short_description:", "default_prompt:"]:
        if needle not in text:
            result.error(f"{interface}: missing {needle}")


def validate_trigger_cases(skill_dir: Path, result: CheckResult) -> None:
    path = skill_dir / "evals" / "trigger_cases.json"
    data = load_json(path, result)
    if not isinstance(data, dict):
        return
    cases = data.get("cases")
    if not isinstance(cases, list):
        result.error(f"{path}: cases must be a list")
        return
    if len(cases) < MIN_TRIGGER_CASES:
        result.error(f"{path}: expected at least {MIN_TRIGGER_CASES} trigger cases")

    kinds: set[str] = set()
    seen_ids: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            result.error(f"{path}: each trigger case must be an object")
            continue
        case_id = case.get("id")
        if not case_id:
            result.error(f"{path}: trigger case missing id")
        elif case_id in seen_ids:
            result.error(f"{path}: duplicate trigger case id {case_id}")
        else:
            seen_ids.add(case_id)
        kinds.add(str(case.get("kind")))
        for key in ["prompt", "expected_skill", "why"]:
            if not case.get(key):
                result.error(f"{path}: case {case_id} missing {key}")

    missing_kinds = REQUIRED_TRIGGER_KINDS - kinds
    for kind in sorted(missing_kinds):
        result.error(f"{path}: missing trigger case kind {kind}")


def validate_output_cases(skill_dir: Path, result: CheckResult) -> None:
    path = skill_dir / "evals" / "output_cases.json"
    data = load_json(path, result)
    if not isinstance(data, dict):
        return
    cases = data.get("cases")
    if not isinstance(cases, list):
        result.error(f"{path}: cases must be a list")
        return
    if len(cases) < MIN_OUTPUT_CASES:
        result.error(f"{path}: expected at least {MIN_OUTPUT_CASES} output cases")

    seen_ids: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            result.error(f"{path}: each output case must be an object")
            continue
        case_id = case.get("id")
        if not case_id:
            result.error(f"{path}: output case missing id")
        elif case_id in seen_ids:
            result.error(f"{path}: duplicate output case id {case_id}")
        else:
            seen_ids.add(case_id)
        for key in ["task", "input_files", "baseline_failures", "with_skill_assertions", "evidence_status"]:
            if not case.get(key):
                result.error(f"{path}: case {case_id} missing {key}")
        for rel in case.get("input_files", []):
            repo_root = skill_dir.parents[2]
            if not (repo_root / rel).exists():
                result.warn(f"{path}: case {case_id} references missing input file {rel}")
        if case.get("missing_evidence"):
            result.warn(f"{path}: case {case_id} has missing evidence")


def validate_skill(skill_dir: Path, result: CheckResult) -> None:
    if not (skill_dir / "SKILL.md").exists():
        result.error(f"{skill_dir}: missing SKILL.md")
    validate_manifest(skill_dir, result)
    validate_interface(skill_dir, result)
    validate_trigger_cases(skill_dir, result)
    validate_output_cases(skill_dir, result)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as release-blocking")
    parser.add_argument(
        "--skill",
        action="append",
        default=None,
        help="Skill directory name under .agents/skills",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    result = CheckResult()
    skill_names = args.skill or ["viral-replica", "viral-replica-improver", "video-replication"]
    for name in skill_names:
        validate_skill(root / ".agents" / "skills" / name, result)

    for warning in result.warnings:
        print(f"WARN: {warning}")
    for error in result.errors:
        print(f"ERROR: {error}", file=sys.stderr)

    if result.errors or (args.strict and result.warnings):
        print(
            f"Skill release check failed: {len(result.errors)} error(s), {len(result.warnings)} warning(s)",
            file=sys.stderr,
        )
        return 1

    print(f"Skill release structural check passed with {len(result.warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
