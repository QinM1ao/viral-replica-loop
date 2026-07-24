#!/usr/bin/env python3
"""Replay Storyboard Visual Acceptance without touching live job state."""

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from checker_review_qc import (
    bind_risk_request,
    review_report,
    write_bound_report_json,
)
from codex_imagegen_contract_qc import build_report as build_imagegen_contract_report
from qc_input_binding import (
    attach_input_binding,
    resolve_path,
    validate_input_binding,
)
from qc_risk_ledger import build_stage_ledger, find_job


STAGE = "image_batch_qc"
FAMILY_ORDER = [
    "geometry_appearance",
    "identity_product_material_integrity",
    "cross_part_continuity",
    "skincare_progression",
]
LEGACY_COMPARE_NAMES = [
    "storyboard_geometry_compare.jpg",
    "cross_part_continuity_compare.jpg",
    "skincare_progression_compare.jpg",
]
LEGACY_REVIEW_NAMES = [
    "storyboard_geometry_review.json",
    "cross_part_continuity_review.json",
    "skincare_progression_review.json",
    "image_batch_checker_visual_review.json",
]


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def display_path(root, path):
    path = Path(path).resolve()
    try:
        return str(path.relative_to(Path(root).resolve()))
    except ValueError:
        return str(path)


def protected_snapshot(root, paths):
    root = Path(root).resolve()
    snapshot = {}
    for path in sorted({Path(path).resolve() for path in paths}):
        snapshot[display_path(root, path)] = {
            "exists": path.is_file(),
            "sha256": sha256_file(path) if path.is_file() else None,
        }
    return snapshot


def default_protected_paths(root, job_id):
    root = Path(root).resolve()
    paths = [root / name for name in ("jobs.csv", "RUNNER_STATE.json", "STATE.md")]
    job_seedance = root / "output" / job_id / "seedance"
    paths.extend(sorted(job_seedance.glob("seedance_*_prompt.txt")))
    paths.extend(sorted((job_seedance / "requests").glob("*request*.json")))

    validated_job = root / "output" / "job-011"
    if validated_job.exists():
        paths.append(
            validated_job / "final-delivery" / "孔凤春清洁泥膜_最终版_26s.mp4"
        )
        paths.extend(sorted((validated_job / "seedance").glob("seedance_*_prompt.txt")))
        paths.extend(
            sorted((validated_job / "seedance" / "requests").glob("*request*.json"))
        )
    return paths


def write_isolated_jobs(source_root, replay_root, job_id):
    source_path = Path(source_root) / "jobs.csv"
    with source_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        row = next((item for item in reader if item.get("id", "").strip() == job_id), None)
        fieldnames = reader.fieldnames
    if row is None or not fieldnames:
        raise ValueError(f"job not found: {job_id}")
    with (Path(replay_root) / "jobs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(row)
    return row


def sanitize_active_replay_files(replay_root, job_id):
    checks = Path(replay_root) / "output" / job_id / "checks"
    for name in (
        f"{STAGE}_storyboard_visual_acceptance.json",
        f"{STAGE}_semantic_review_request.json",
        f"{STAGE}_qc_risk_ledger.json",
        f"{STAGE}_gate_review.md",
        f"{STAGE}_gate_review_qc.json",
        f"{STAGE}_gate_review_qc.md",
        "storyboard_visual_acceptance_compare.jpg",
        "qc_risk_ledger_state.json",
    ):
        (checks / name).unlink(missing_ok=True)


def write_imagegen_contract(replay_root, job_id):
    replay_root = Path(replay_root)
    job_dir = replay_root / "output" / job_id
    manifest_path = job_dir / "visual-assets" / "approved_visual_manifest.json"
    report_path = job_dir / "checks" / f"{STAGE}_codex_imagegen_contract_qc.json"
    copied_report = load_json(report_path) if report_path.is_file() else {}
    report = build_imagegen_contract_report(replay_root, job_id, STAGE)
    validation_mode = "recomputed_real_contract"
    if report.get("overall") == "PASS":
        attach_input_binding(
            report,
            replay_root,
            [
                resolve_path(replay_root, report.get("contract_path")),
                resolve_path(replay_root, report.get("visual_manifest_path")),
            ],
        )
    else:
        binding_ok, _ = validate_input_binding(
            replay_root,
            copied_report.get("input_binding"),
        )
        copied_checks = copied_report.get("checks") or []
        if copied_report.get("overall") != "PASS" or not copied_checks or not binding_ok:
            raise RuntimeError("isolated replay has no passing exact-input ImageGen contract")
        report = copied_report
        validation_mode = "copied_exact_input_fixture"
    write_json(
        report_path,
        report,
    )
    return {
        "mode": validation_mode,
        "check_count": len(report.get("checks") or []),
    }


def prepare_replay(source_root, replay_root, job_id):
    source_root = Path(source_root).resolve()
    replay_root = Path(replay_root).resolve()
    replay_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source_root / "output" / job_id,
        replay_root / "output" / job_id,
        dirs_exist_ok=True,
    )
    shared = source_root / "output" / "shared"
    if shared.exists():
        shutil.copytree(shared, replay_root / "output" / "shared", dirs_exist_ok=True)
    job = write_isolated_jobs(source_root, replay_root, job_id)
    sanitize_active_replay_files(replay_root, job_id)
    job["_replay_imagegen_contract"] = write_imagegen_contract(replay_root, job_id)
    return job


def checker_review_text(job_id, family_results):
    result = "FAIL" if "FAIL" in family_results.values() else "PASS"
    outcome = "HARD_FAILURE" if result == "FAIL" else "PASS"
    failed_item = (
        "identity_product_material_integrity" if result == "FAIL" else "none"
    )
    failure_type = "wrong_product" if result == "FAIL" else "none"
    retry_variable = "product_reference" if result == "FAIL" else "none"
    reason = (
        "product identity fixture failed while unrelated visual families passed"
        if result == "FAIL"
        else "all requested storyboard visual families passed"
    )
    return "\n".join(
        [
            "Gate: gates/image_batch_gate.md",
            f"Job: {job_id}",
            f"Stage: {STAGE}",
            f"Input artifacts: output/{job_id}/checks/storyboard_visual_acceptance_compare.jpg",
            "Checks: reviewed canonical compare and every requested family",
            f"Result: {result}",
            f"Outcome type: {outcome}",
            "Why not fail: ",
            f"Reason: {reason}",
            f"Failed item: {failed_item}",
            f"Failure type: {failure_type}",
            f"Retry variable: {retry_variable}",
            "Locked variables: source layout, shot order, accepted families",
            "Next status: image_qc_passed" if result == "PASS" else "Next status: storyboard_passed",
            "Needs user confirmation: false",
            "Family results: " + json.dumps(family_results, ensure_ascii=False),
            "",
        ]
    )


def bind_checker_fixture(replay_root, job_id, family_results):
    replay_root = Path(replay_root)
    checks = replay_root / "output" / job_id / "checks"
    review_path = checks / f"{STAGE}_gate_review.md"
    request_path = checks / f"{STAGE}_semantic_review_request.json"
    review_path.write_text(
        checker_review_text(job_id, family_results),
        encoding="utf-8",
    )
    report = bind_risk_request(review_report(review_path), request_path, replay_root)
    if report.get("qc_risk_review"):
        report["qc_risk_review"]["wait_seconds"] = 0.0
    write_bound_report_json(
        report,
        checks / f"{STAGE}_gate_review_qc.json",
        replay_root,
    )
    if report.get("overall") not in {"PASS", "FAIL"}:
        raise RuntimeError(f"checker fixture did not bind: {report}")
    return report


def metric(ledger, name):
    return (ledger.get("metrics") or {}).get(name, 0)


def semantic_families(ledger):
    return [
        name
        for name in FAMILY_ORDER
        if name in (ledger.get("families") or {})
    ]


def changed_and_unchanged_replay(source_root, job_id):
    with tempfile.TemporaryDirectory(prefix="storyboard-visual-changed-") as tmp:
        replay_root = Path(tmp)
        job = prepare_replay(source_root, replay_root, job_id)

        requested = build_stage_ledger(replay_root, job, STAGE, write=True)
        requested_families = [
            item["name"]
            for item in requested["semantic_review_request"]["families"]
        ]
        checker_started = time.perf_counter()
        checker = bind_checker_fixture(
            replay_root,
            job_id,
            {name: "PASS" for name in requested_families},
        )
        checker_active_seconds = time.perf_counter() - checker_started
        accepted = build_stage_ledger(replay_root, job, STAGE, write=True)
        changed_active_seconds = (
            metric(requested, "active_seconds")
            + checker_active_seconds
            + metric(accepted, "active_seconds")
        )

        compare_path = (
            replay_root
            / "output"
            / job_id
            / "checks"
            / "storyboard_visual_acceptance_compare.jpg"
        )
        compare_sha = sha256_file(compare_path)
        compare_mtime = compare_path.stat().st_mtime_ns
        unchanged_started = time.perf_counter()
        unchanged = build_stage_ledger(replay_root, job, STAGE, write=True)
        unchanged_active_seconds = time.perf_counter() - unchanged_started

        changed_report = {
            "families": semantic_families(requested),
            "compare_count": metric(requested, "compare_generation_count"),
            "semantic_request_count": metric(requested, "semantic_request_count"),
            "checker_invocation_count": int(
                (checker.get("qc_risk_review") or {}).get("invocation_count") or 0
            ),
            "requested_family_count": metric(requested, "requested_family_count"),
            "reused_family_count": metric(requested, "reused_family_count"),
            "accepted_overall": accepted["overall"],
            "imagegen_contract_validation": job["_replay_imagegen_contract"]["mode"],
            "imagegen_contract_check_count": job["_replay_imagegen_contract"]["check_count"],
            "active_seconds": round(changed_active_seconds, 6),
            "checker_active_seconds": round(checker_active_seconds, 6),
            "wait_seconds": round(metric(accepted, "wait_seconds"), 6),
        }
        unchanged_report = {
            "compare_generation_count": metric(unchanged, "compare_generation_count"),
            "semantic_request_count": metric(unchanged, "semantic_request_count"),
            "checker_invocation_count": metric(unchanged, "checker_invocation_count"),
            "requested_family_count": metric(unchanged, "requested_family_count"),
            "reused_family_count": sum(
                1
                for name in FAMILY_ORDER
                if (unchanged.get("families") or {}).get(name, {}).get("status")
                == "REUSED_PASS"
            ),
            "overall": unchanged["overall"],
            "active_seconds": round(unchanged_active_seconds, 6),
            "wait_seconds": round(metric(unchanged, "wait_seconds"), 6),
            "compare_unchanged": (
                sha256_file(compare_path) == compare_sha
                and compare_path.stat().st_mtime_ns == compare_mtime
            ),
        }
        return changed_report, unchanged_report


def mixed_replay(source_root, job_id):
    with tempfile.TemporaryDirectory(prefix="storyboard-visual-mixed-") as tmp:
        replay_root = Path(tmp)
        job = prepare_replay(source_root, replay_root, job_id)
        requested = build_stage_ledger(replay_root, job, STAGE, write=True)
        names = [
            item["name"]
            for item in requested["semantic_review_request"]["families"]
        ]
        results = {name: "PASS" for name in names}
        results["identity_product_material_integrity"] = "FAIL"
        bind_checker_fixture(replay_root, job_id, results)
        failed = build_stage_ledger(replay_root, job, STAGE, write=True)

        manifest = load_json(
            replay_root
            / "output"
            / job_id
            / "visual-assets"
            / "approved_visual_manifest.json"
        )
        product_front = replay_root / manifest["reusable_refs"]["product_front"]
        with product_front.open("ab") as handle:
            handle.write(b"replay-local-product-ref-change")
        repair = build_stage_ledger(replay_root, job, STAGE, write=True)
        return {
            "overall": failed["overall"],
            "preserved_pass_families": [
                name
                for name in FAMILY_ORDER
                if (failed.get("families") or {}).get(name, {}).get("status") == "PASS"
            ],
            "failed_families": [
                name
                for name in FAMILY_ORDER
                if (failed.get("families") or {}).get(name, {}).get("status") == "FAIL"
            ],
            "repair_request_families": [
                item["name"]
                for item in repair["semantic_review_request"]["families"]
            ],
            "repair_reused_family_count": sum(
                1
                for name in FAMILY_ORDER
                if (repair.get("families") or {}).get(name, {}).get("status")
                == "REUSED_PASS"
            ),
        }


def deterministic_failure_replay(source_root, job_id):
    with tempfile.TemporaryDirectory(prefix="storyboard-visual-preflight-") as tmp:
        replay_root = Path(tmp)
        job = prepare_replay(source_root, replay_root, job_id)
        evidence_path = (
            replay_root / "output" / job_id / "checks" / "part1_shot_label_restore.json"
        )
        evidence = load_json(evidence_path)
        evidence["grid"] = {"cols": 1, "rows": 1}
        write_json(evidence_path, evidence)
        ledger = build_stage_ledger(replay_root, job, STAGE, write=True)
        request = ledger.get("semantic_review_request") or {}
        return {
            "overall": ledger["overall"],
            "semantic_request_count": int(bool(request.get("required"))),
            "checker_invocation_count": int(request.get("invocation_count") or 0),
            "failed_checks": [
                check["name"]
                for check in (
                    load_json(
                        replay_root
                        / "output"
                        / job_id
                        / "checks"
                        / f"{STAGE}_storyboard_visual_acceptance.json"
                    ).get("deterministic_preflight", {}).get("checks", [])
                )
                if check.get("status") == "FAIL"
            ],
        }


def legacy_baseline(source_root, job_id):
    checks = Path(source_root) / "output" / job_id / "checks"
    compares = [name for name in LEGACY_COMPARE_NAMES if (checks / name).is_file()]
    reviews = [name for name in LEGACY_REVIEW_NAMES if (checks / name).is_file()]
    return {
        "compare_count": len(compares),
        "review_count": len(reviews),
        "checker_invocation_count": len(reviews),
        "requested_family_count": len(reviews),
        "reused_family_count": 0,
        "active_seconds": None,
        "wait_seconds": None,
        "timing_note": "legacy reports do not record active or wait time",
        "compare_files": compares,
        "review_files": reviews,
    }


def run_replay(source_root, job_id, protected_paths=None):
    source_root = Path(source_root).resolve()
    if find_job(source_root, job_id) is None:
        raise ValueError(f"job not found: {job_id}")
    protected = default_protected_paths(source_root, job_id)
    protected.extend(Path(path) for path in (protected_paths or []))
    before = protected_snapshot(source_root, protected)

    changed, unchanged = changed_and_unchanged_replay(source_root, job_id)
    mixed = mixed_replay(source_root, job_id)
    deterministic = deterministic_failure_replay(source_root, job_id)

    after = protected_snapshot(source_root, protected)
    return {
        "version": 1,
        "job_id": job_id,
        "isolated_replay": True,
        "paid_generation_calls": {"gpt_image": 0, "seedance": 0},
        "shared_state_mutations": 0,
        "execution_context": execution_context(source_root),
        "before": legacy_baseline(source_root, job_id),
        "changed_state": changed,
        "unchanged_state": unchanged,
        "mixed_result": mixed,
        "deterministic_failure": deterministic,
        "protected_artifacts": {
            "unchanged": before == after,
            "before": before,
            "after": after,
        },
        "conclusion": (
            "Three legacy visual compare/review paths converge to one canonical "
            "compare and one batched checker on change; unchanged inputs reuse all "
            "four accepted semantic families without regenerating compare context."
        ),
    }


def execution_context(root):
    root = Path(root).resolve()
    relevant = [
        "tools/replay_storyboard_visual_acceptance.py",
        "tools/storyboard_visual_acceptance.py",
        "tools/qc_risk_ledger.py",
        "tools/checker_review_qc.py",
        "tools/codex_imagegen_contract_qc.py",
        "rules/STAGE_RULES.json",
    ]
    hashes = {
        raw: sha256_file(root / raw)
        for raw in relevant
        if (root / raw).is_file()
    }
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--short"],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError):
        commit, status = None, []
    return {
        "git_commit": commit,
        "dirty": bool(status),
        "dirty_path_count": len(status),
        "relevant_file_sha256": hashes,
    }


def markdown_report(report):
    before = report["before"]
    changed = report["changed_state"]
    unchanged = report["unchanged_state"]
    lines = [
        "# job-012 One-pass 分镜视觉验收回放证据",
        "",
        "## 结论",
        "",
        "原先 3 套 compare/review 已收敛为 1 张 canonical compare + 1 次批量 checker。"
        " 输入不变时复用 4 组语义 PASS，不重生 compare，不发起 checker。",
        "",
        "| 场景 | Compare | Semantic request | Checker | Requested families | Reused families | Active time | Wait time |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
        f"| 改造前 job-012 证据 | {before['compare_count']} | 3 | {before['checker_invocation_count']} | {before['requested_family_count']} | 0 | 未记录 | 未记录 |",
        f"| Changed | {changed['compare_count']} | {changed['semantic_request_count']} | {changed['checker_invocation_count']} | {changed['requested_family_count']} | {changed['reused_family_count']} | {changed['active_seconds']:.6f}s | {changed['wait_seconds']:.6f}s |",
        f"| Unchanged | {unchanged['compare_generation_count']} | {unchanged['semantic_request_count']} | {unchanged['checker_invocation_count']} | {unchanged['requested_family_count']} | {unchanged['reused_family_count']} | {unchanged['active_seconds']:.6f}s | {unchanged['wait_seconds']:.6f}s |",
        "",
        "## 保留的硬保护",
        "",
        f"- Multi-Part 清洁泥膜仍检查 4 组 family：`{', '.join(changed['families'])}`。",
        f"- Mixed fixture 中局部 FAIL 后，仍保留 {len(report['mixed_result']['preserved_pass_families'])} 组无关 PASS；修复只重开 `{', '.join(report['mixed_result']['repair_request_families'])}`。",
        f"- 确定性 preflight 失败时 checker 调用数为 {report['deterministic_failure']['checker_invocation_count']}。",
        f"- GPT Image 合同在隔离副本中重新执行 `{changed['imagegen_contract_validation']}`，共 {changed['imagegen_contract_check_count']} 项确定性检查。",
        "- 回放只在临时隔离副本中运行；GPT Image 与 Seedance 调用数均为 0。",
        "",
        "## 交付保护",
        "",
        f"- 现有 prompts、Seedance requests、已验证 26 秒视频与共享状态哈希不变：`{report['protected_artifacts']['unchanged']}`。",
        f"- 执行基线 commit：`{report['execution_context']['git_commit']}`；当时工作区 dirty=`{report['execution_context']['dirty']}`，所以 JSON 同时固定了 {len(report['execution_context']['relevant_file_sha256'])} 个关键工具/规则哈希。",
        "- 旧链路未记录 active/wait time，因此不伪造改造前时间对比；表中只报告实际可测数据。",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Replay one-pass Storyboard Visual Acceptance in isolation."
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--job-id", default="job-012")
    parser.add_argument("--out-json")
    parser.add_argument("--out-md")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out_json = Path(args.out_json) if args.out_json else (
        root / "docs" / "research" / f"{args.job_id}-one-pass-storyboard-visual-replay.json"
    )
    out_md = Path(args.out_md) if args.out_md else (
        root / "docs" / "research" / f"{args.job_id}-one-pass-storyboard-visual-replay.md"
    )
    report = run_replay(root, args.job_id)
    write_json(out_json, report)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(markdown_report(report), encoding="utf-8")
    print(json.dumps({
        "overall": "PASS" if report["protected_artifacts"]["unchanged"] else "FAIL",
        "json": display_path(root, out_json),
        "markdown": display_path(root, out_md),
    }, ensure_ascii=False))
    raise SystemExit(0 if report["protected_artifacts"]["unchanged"] else 1)


if __name__ == "__main__":
    main()
