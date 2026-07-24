#!/usr/bin/env python3
"""Run deterministic, parallel QC for a rendered Pre-Seedance package."""

import argparse
import json
import re
import shutil
import shlex
import subprocess
import time
from pathlib import Path

import qc_evidence_fanout

HANDOFF_MODES = {"web", "api", "both"}
AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".flac"}
PART_RE = re.compile(r"part[_ -]?(\d+)", re.IGNORECASE)


def read_handoff_mode(root, job_id):
    path = root / "output" / job_id / "seedance" / "handoff_mode.json"
    try:
        mode = str(json.loads(path.read_text(encoding="utf-8")).get("mode", "")).lower()
    except (OSError, json.JSONDecodeError, AttributeError):
        return "both"
    return mode if mode in HANDOFF_MODES else "both"


def part_sort_key(path):
    match = PART_RE.search(str(path))
    return (int(match.group(1)) if match else float("inf"), path.as_posix().lower())


def relative_paths(root, paths):
    return [path.relative_to(root).as_posix() for path in sorted(paths, key=part_sort_key)]


def discover_prompt_files(root, job_dir):
    canonical = list((job_dir / "seedance").glob("seedance_part*_prompt.txt"))
    if canonical:
        return relative_paths(root, canonical)

    web_prompts = [
        path
        for path in (job_dir / "seedance_web_final" / "prompts").glob("*.txt")
        if PART_RE.search(path.name)
    ]
    if web_prompts:
        return relative_paths(root, web_prompts)

    upload_prompts = [
        path
        for path in (job_dir / "seedance_web_final").glob("Part*_上传素材/00_*.txt")
        if PART_RE.search(str(path))
    ]
    return relative_paths(root, upload_prompts)


def discover_request_files(root, job_dir):
    request_re = re.compile(r"^part\d+_request_prepared\.json$", re.IGNORECASE)
    paths = [
        path
        for path in (job_dir / "seedance" / "requests").glob("*.json")
        if request_re.match(path.name)
    ]
    return relative_paths(root, paths)


def discover_audio_files(root, job_dir, mode):
    web_paths = []
    if mode in {"web", "both"}:
        web_paths = [
            path
            for path in (job_dir / "seedance_web_final").glob("Part*_上传素材/*")
            if path.is_file()
            and path.suffix.lower() in AUDIO_SUFFIXES
            and PART_RE.search(str(path))
        ]
    if web_paths:
        return relative_paths(root, web_paths)

    canonical = [
        path
        for path in (job_dir / "audio-boundary").glob("*")
        if path.is_file()
        and path.suffix.lower() in AUDIO_SUFFIXES
        and PART_RE.search(path.name)
    ]
    return relative_paths(root, canonical)


def task(name, command, out_json, out_md):
    return {
        "name": name,
        "command": command,
        "out_json": out_json,
        "out_md": out_md,
    }


def build_plan(root, job_id):
    root = Path(root).resolve()
    job_dir = root / "output" / job_id
    mode = read_handoff_mode(root, job_id)
    prompts = discover_prompt_files(root, job_dir)
    requests = discover_request_files(root, job_dir)
    audio = discover_audio_files(root, job_dir, mode)
    checks = f"output/{job_id}/checks"
    request_dir = f"output/{job_id}/seedance/requests"

    visual_command = [
        "python3",
        "tools/visual_asset_manifest_qc.py",
        "--root",
        ".",
        "--job-id",
        job_id,
        "--stage",
        "pre_seedance_pack",
        "--out-json",
        f"{checks}/pre_seedance_pack_visual_asset_manifest_qc.json",
        "--out-md",
        f"{checks}/pre_seedance_pack_visual_asset_manifest_qc.md",
    ]
    if mode in {"web", "both"}:
        visual_command.append("--check-final-dir")

    tasks = [
        task(
            "part_compilation_qc",
            [
                "python3",
                "tools/pre_seedance_part_compiler.py",
                "--job-dir",
                f"output/{job_id}",
                "--out-json",
                f"{checks}/pre_seedance_pack_part_compilation_qc.json",
                "--out-md",
                f"{checks}/pre_seedance_pack_part_compilation_qc.md",
            ],
            f"{checks}/pre_seedance_pack_part_compilation_qc.json",
            f"{checks}/pre_seedance_pack_part_compilation_qc.md",
        ),
        task(
            "visual_asset_manifest_qc",
            visual_command,
            f"{checks}/pre_seedance_pack_visual_asset_manifest_qc.json",
            f"{checks}/pre_seedance_pack_visual_asset_manifest_qc.md",
        ),
        task(
            "seedance_prompt_contract_qc",
            [
                "python3",
                "tools/seedance_prompt_contract_qc.py",
                "--root",
                ".",
                "--job-id",
                job_id,
                "--stage",
                "pre_seedance_pack",
                "--prompt-files",
                *prompts,
                "--out-json",
                f"{checks}/pre_seedance_pack_seedance_prompt_contract_qc.json",
                "--out-md",
                f"{checks}/pre_seedance_pack_seedance_prompt_contract_qc.md",
            ],
            f"{checks}/pre_seedance_pack_seedance_prompt_contract_qc.json",
            f"{checks}/pre_seedance_pack_seedance_prompt_contract_qc.md",
        ),
    ]

    source_rhythm = job_dir / "剧情分析" / "source_rhythm.json"
    director_plan = job_dir / "seedance" / "director_plan.json"
    tasks.append(
        task(
            "source_rhythm_qc",
            [
                "python3",
                "tools/source_rhythm_qc.py",
                "--source-rhythm",
                source_rhythm.relative_to(root).as_posix(),
                "--director-plan",
                director_plan.relative_to(root).as_posix(),
                "--json-out",
                f"{checks}/pre_seedance_pack_source_rhythm_qc.json",
                "--md-out",
                f"{checks}/pre_seedance_pack_source_rhythm_qc.md",
            ],
            f"{checks}/pre_seedance_pack_source_rhythm_qc.json",
            f"{checks}/pre_seedance_pack_source_rhythm_qc.md",
        )
    )

    if audio:
        tasks.append(
            task(
                "audio_duration_qc",
                [
                    "python3",
                    "tools/audio_duration_qc.py",
                    "--audio",
                    *audio,
                    "--max-seconds",
                    "15.0",
                    "--out-json",
                    f"{request_dir}/final_upload_audio_duration_qc.json",
                    "--out-md",
                    f"{request_dir}/final_upload_audio_duration_qc.md",
                ],
                f"{request_dir}/final_upload_audio_duration_qc.json",
                f"{request_dir}/final_upload_audio_duration_qc.md",
            )
        )

    if mode in {"api", "both"}:
        tasks.append(
            task(
                "request_body_qc",
                [
                    "python3",
                    "tools/request_body_qc.py",
                    "--requests",
                    *requests,
                    "--prompt-files",
                    *prompts,
                    "--model-route-config",
                    "rules/SEEDANCE_MODEL.json",
                    "--allow-asset-refs",
                    "--out-json",
                    f"{request_dir}/request_qc.json",
                    "--out-md",
                    f"{request_dir}/request_qc.md",
                ],
                f"{request_dir}/request_qc.json",
                f"{request_dir}/request_qc.md",
            )
        )

    return {
        "version": 1,
        "job_id": job_id,
        "handoff_mode": mode,
        "inputs": {
            "prompt_files": prompts,
            "request_files": requests,
            "audio_files": audio,
        },
        "tasks": tasks,
    }


def write_markdown(path, bundle):
    lines = [
        "# Pre-Seedance Pack QC Bundle",
        "",
        f"- Overall: **{bundle['overall']}**",
        f"- Job: `{bundle['job_id']}`",
        f"- Handoff mode: `{bundle['handoff_mode']}`",
        "",
        "## Tasks",
        "",
        "| Task | Overall | Return code | Duration (s) |",
        "|---|---|---:|---:|",
    ]
    for item in bundle["tasks"]:
        lines.append(
            f"| `{item['name']}` | **{item['overall']}** | {item['returncode']} | "
            f"{item['duration_seconds']:.6f} |"
        )
    lines.extend(["", "## Commands", ""])
    for item in bundle["tasks"]:
        lines.extend(
            [
                f"### `{item['name']}`",
                "",
                "```text",
                shlex.join(item["command"]),
                "```",
                "",
            ]
        )
    lines.extend(
        [
            "## Discovered Inputs",
            "",
            "```json",
            json.dumps(bundle["inputs"], ensure_ascii=False, indent=2),
            "```",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def semantic_families_from_existing_contract(root, job_id):
    from qc_risk_ledger import build_stage_ledger, find_job

    job = (
        find_job(root, job_id)
        if (root / "jobs.csv").is_file()
        else None
    )
    if job is None:
        job = {"id": job_id, "status": "image_qc_passed"}
    baseline = build_stage_ledger(
        root,
        job,
        "pre_seedance_pack",
        write=False,
    )
    requested = {
        item["name"]
        for item in (
            baseline.get("semantic_review_request") or {}
        ).get("families") or []
    }
    families = []
    for name, result in (baseline.get("families") or {}).items():
        if result.get("kind") != "semantic":
            continue
        family = {
            "name": name,
            "kind": "semantic",
            "fingerprint_hash": result.get("fingerprint_hash"),
            "reuse_evidence_valid": result.get("status") == "REUSED_PASS",
            "evidence": result.get("evidence") or [],
            "defects": result.get("defect_scopes") or [],
            "scope": result.get("scope"),
            "active_seconds": (
                result.get("decision_trace") or {}
            ).get("active_seconds", 0.0),
            "wait_seconds": (
                result.get("decision_trace") or {}
            ).get("wait_seconds", 0.0),
        }
        if result.get("status") == "STOP" and name not in requested:
            family["evaluation_blocker"] = result.get("reason")
        families.append(family)
    return families


def run_bundle(root, job_id, runner=subprocess.run, clock=time.perf_counter):
    root = Path(root).resolve()
    plan = build_plan(root, job_id)
    tasks = plan["tasks"]
    evidence_base = (
        Path("output")
        / job_id
        / "checks"
        / "evidence"
        / "pre_seedance_pack"
    )
    fanout_tasks = []
    for item in tasks:
        evidence_json = (
            evidence_base / item["name"] / f"{item['name']}.json"
        ).as_posix()
        evidence_md = (
            evidence_base / item["name"] / f"{item['name']}.md"
        ).as_posix()
        command = [
            evidence_json
            if value == item["out_json"]
            else evidence_md
            if value == item["out_md"]
            else value
            for value in item["command"]
        ]
        fanout_tasks.append(
            {
                "name": item["name"],
                "kind": "deterministic",
                "command": command,
                "report_path": evidence_json,
                "additional_output_paths": [evidence_md],
            }
        )
    evidence_plan = qc_evidence_fanout.build_plan(
        root,
        job_id,
        "pre_seedance_pack",
        fanout_tasks,
    )
    evidence_bundle = qc_evidence_fanout.run_bundle(
        root,
        evidence_plan,
        max_workers=len(tasks),
        runner=runner,
        clock=clock,
    )
    evidence_by_name = {
        family["name"]: family["evidence"][0]
        for family in evidence_bundle["families"]
    }
    results = []
    for item in tasks:
        evidence = evidence_by_name[item["name"]]
        source_json = root / evidence["path"]
        source_md = root / evidence["additional_outputs"][0]["path"]
        for source, relative_destination in (
            (source_json, item["out_json"]),
            (source_md, item["out_md"]),
        ):
            if source.is_file():
                destination = root / relative_destination
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
        results.append(
            {
                "name": item["name"],
                "overall": (
                    "PASS" if evidence["status"] == "PASS" else "FAIL"
                ),
                "command": evidence["command"],
                "returncode": evidence["returncode"],
                "duration_seconds": evidence["duration_seconds"],
                "report_overall": evidence["status"],
                "out_json": item["out_json"],
                "out_md": item["out_md"],
                **(
                    {"error": evidence["reason"]}
                    if evidence["status"] != "PASS"
                    else {}
                ),
            }
        )
    bundle = {
        "version": 1,
        "job_id": job_id,
        "handoff_mode": plan["handoff_mode"],
        "overall": "PASS" if all(item["overall"] == "PASS" for item in results) else "FAIL",
        "inputs": plan["inputs"],
        "evidence_bundle": evidence_plan["bundle_path"],
        "tasks": results,
    }
    checks_dir = root / "output" / job_id / "checks"
    checks_dir.mkdir(parents=True, exist_ok=True)
    json_path = checks_dir / "pre_seedance_pack_qc_bundle.json"
    md_path = checks_dir / "pre_seedance_pack_qc_bundle.md"
    json_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(md_path, bundle)
    ledger = qc_evidence_fanout.coordinate_ledger(
        root,
        evidence_bundle,
        semantic_families=semantic_families_from_existing_contract(
            root,
            job_id,
        ),
        write=True,
    )
    bundle["qc_risk_ledger"] = ledger["ledger_path"]
    bundle["qc_risk_ledger_overall"] = ledger["overall"]
    json_path.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_markdown(md_path, bundle)
    return bundle


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--dry-plan", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    root = args.root.expanduser().resolve()
    if args.dry_plan:
        print(json.dumps(build_plan(root, args.job_id), ensure_ascii=False, indent=2))
        return 0

    bundle = run_bundle(root, args.job_id)
    print(json.dumps({"overall": bundle["overall"], "job_id": args.job_id}, ensure_ascii=False))
    return 0 if bundle["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
