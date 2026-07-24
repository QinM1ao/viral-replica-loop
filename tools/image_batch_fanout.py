#!/usr/bin/env python3
import argparse
import csv
import json
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

try:
    from . import stage_execution
except ImportError:
    import stage_execution


FANOUT_POLICY = "part_contracts_then_serial_merge"
DEFAULT_STAGE = "image_batch_qc"
GENERATOR = (
    Path(__file__).resolve().parents[1]
    / ".agents"
    / "skills"
    / "video-replication"
    / "scripts"
    / "generate.py"
)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path):
    with Path(path).open(encoding="utf-8") as f:
        return json.load(f)


def display_path(root, path):
    path = Path(path)
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except (FileNotFoundError, ValueError):
        return str(path)


def resolve_path(root, raw):
    if raw is None:
        return None
    path = Path(str(raw))
    if path.is_absolute():
        return path
    return root / path


def part_id(value):
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if re.fullmatch(r"\d+", raw):
        return f"part{raw}"
    match = re.fullmatch(r"part\s*[-_ ]?\s*(\d+)", raw)
    if match:
        return f"part{match.group(1)}"
    return raw.replace(" ", "")


def part_sort_key(value):
    pid = part_id(value)
    match = re.fullmatch(r"part(\d+)", pid)
    if match:
        return (0, int(match.group(1)))
    return (1, pid)


def read_jobs(root):
    path = root / "jobs.csv"
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def find_job(root, job_id):
    for row in read_jobs(root):
        if row.get("id") == job_id:
            return row
    return None


def job_dir(root, job_id):
    row = find_job(root, job_id)
    if row and row.get("output_dir"):
        return resolve_path(root, row["output_dir"])
    return root / "output" / job_id


def storyboard_manifest_path(root, job_id):
    return job_dir(root, job_id) / "storyboard_source_refs" / "source_storyboard_manifest.json"


def required_storyboard_parts(root, job_id):
    manifest = storyboard_manifest_path(root, job_id)
    parts = []
    if manifest.exists():
        data = load_json(manifest)
        for item in data.get("parts", []):
            if not isinstance(item, dict):
                continue
            pid = part_id(item.get("part"))
            source = resolve_path(root, item.get("path"))
            if pid and source:
                parts.append({"part": pid, "source_storyboard": source})
    if parts:
        return sorted(parts, key=lambda item: part_sort_key(item["part"]))

    refs_dir = job_dir(root, job_id) / "storyboard_source_refs"
    for path in sorted(refs_dir.glob("source_storyboard_part*.jpg")):
        match = re.search(r"part[-_ ]?(\d+)", path.stem, flags=re.IGNORECASE)
        pid = f"part{match.group(1)}" if match else path.stem
        parts.append({"part": part_id(pid), "source_storyboard": path})
    return sorted(parts, key=lambda item: part_sort_key(item["part"]))


def prompt_candidates(root, job_id, pid):
    prompts = job_dir(root, job_id) / "image-batch" / "prompts"
    return [display_path(root, path) for path in sorted(prompts.glob(f"*{pid}*"))]


def fanout_dir(root, job_id):
    return job_dir(root, job_id) / "image-batch" / "fanout"


def contract_dir(root, job_id):
    return job_dir(root, job_id) / "image-batch" / "contracts"


def invocation_dir(root, job_id):
    return job_dir(root, job_id) / "image-batch" / "invocations"


def candidate_dir(root, job_id):
    return job_dir(root, job_id) / "image-batch" / "candidates"


def part_specs_path(root, job_id):
    return job_dir(root, job_id) / "image-batch" / "part_execution_specs.json"


def load_part_specs(root, job_id):
    path = part_specs_path(root, job_id)
    if not path.exists():
        raise ValueError(
            "image-batch part_execution_specs.json is required before plan; "
            "write every required Part prompt_path, ordered references, and depends_on"
        )
    data = load_json(path)
    if data.get("schema_version") != 1:
        raise ValueError("image-batch part_execution_specs schema_version must be 1")
    if data.get("job_id") != job_id:
        raise ValueError("image-batch part_execution_specs job_id mismatch")
    specs = {}
    for item in data.get("parts") or []:
        if not isinstance(item, dict):
            continue
        pid = part_id(item.get("part"))
        if not pid:
            continue
        if pid in specs:
            raise ValueError(f"duplicate image-batch Part spec: {pid}")
        specs[pid] = item
    return specs


def extend_repeated(command, flag, values):
    for value in values or []:
        command.extend([flag, str(value)])


def build_generate_command(
    root,
    job_id,
    stage,
    pid,
    spec,
    candidate,
    contract,
    invocation,
):
    if not spec:
        raise ValueError(f"missing execution spec for {pid}")
    prompt = resolve_path(root, spec.get("prompt_path"))
    references = spec.get("references") or []
    if not prompt or not prompt.is_file():
        raise ValueError(f"{pid} prompt_path is missing or unreadable")
    if not references:
        raise ValueError(f"{pid} references must be a nonempty ordered list")
    command = [
        sys.executable,
        str(GENERATOR),
        "--prompt-file",
        str(prompt),
        "--file",
        str(candidate),
        "--job-id",
        job_id,
        "--stage",
        stage,
        "--part",
        pid,
        "--contract",
        str(contract),
        "--invocation-manifest",
        str(invocation),
        "--quality",
        str(spec.get("quality") or "medium"),
        "--size",
        str(spec.get("size") or "1024x1536"),
        "--no-retry",
    ]
    for reference in references:
        if not isinstance(reference, dict):
            raise ValueError(f"{pid} reference entries must be objects")
        role = str(reference.get("role") or "").strip()
        path = resolve_path(root, reference.get("path"))
        if not role or not path or not path.is_file():
            raise ValueError(
                f"{pid} reference requires a role and an existing local path"
            )
        command.extend(["--image", str(path), "--reference-role", role])
    extend_repeated(command, "--source-risk", spec.get("source_risks"))
    extend_repeated(
        command,
        "--required-translation",
        spec.get("required_translations"),
    )
    extend_repeated(command, "--review-flag", spec.get("review_flags"))
    if spec.get("target_application_method"):
        command.extend(
            [
                "--target-application-method",
                str(spec["target_application_method"]),
            ]
        )
    return command


def default_merged_contract(root, job_id):
    return job_dir(root, job_id) / "image-batch" / "codex_imagegen_contract.json"


def execution_packet(root, job_id, stage, part):
    pid = part["part"]
    completions = (
        job_dir(root, job_id)
        / "work-packets"
        / stage
        / "completions"
    )
    return {
        "packet_id": pid,
        "command": part["command"],
        "depends_on": part["depends_on"],
        "allowed_write_roots": [
            part["candidate_path"],
            part["contract_path"],
            part["invocation_manifest"],
            display_path(
                root,
                fanout_dir(root, job_id) / "logs" / f"{pid}.stdout.txt",
            ),
            display_path(
                root,
                fanout_dir(root, job_id) / "logs" / f"{pid}.stderr.txt",
            ),
        ],
        "completion_path": display_path(root, completions / f"{pid}.json"),
    }


def validate_fanout_plan(root, plan):
    if not isinstance(plan, dict):
        raise ValueError("fanout plan must be an object")
    expected_hash = plan.get("plan_sha256")
    if not expected_hash:
        raise ValueError("fanout plan requires plan_sha256")
    unsigned = dict(plan)
    unsigned.pop("plan_sha256")
    if stage_execution.stable_hash(unsigned) != expected_hash:
        raise ValueError("fanout plan hash mismatch")

    execution = plan.get("stage_execution")
    if not execution:
        raise ValueError("fanout plan requires sealed stage_execution")
    stage_execution.validate_plan(root, execution)
    if (
        execution.get("job_id") != plan.get("job_id")
        or execution.get("stage") != plan.get("stage")
    ):
        raise ValueError("fanout plan identity does not match stage_execution")

    parts = plan.get("parts")
    if not isinstance(parts, list) or not parts:
        raise ValueError("fanout plan requires executable Parts")
    expected_packets = [
        execution_packet(
            root,
            plan["job_id"],
            plan["stage"],
            part,
        )
        for part in parts
    ]
    if execution.get("packets") != expected_packets:
        raise ValueError(
            "fanout Parts do not match sealed stage_execution packets"
        )
    if plan.get("required_parts") != [part.get("part") for part in parts]:
        raise ValueError("fanout required_parts do not match executable Parts")
    return plan


def build_plan(root, job_id, stage=DEFAULT_STAGE):
    specs = load_part_specs(root, job_id)
    required = required_storyboard_parts(root, job_id)
    if not required:
        raise ValueError("image-batch plan has no required source storyboard Parts")
    required_ids = [item["part"] for item in required]
    missing = [pid for pid in required_ids if pid not in specs]
    if missing:
        raise ValueError(
            "image-batch part_execution_specs is missing required Part specs: "
            + ", ".join(missing)
        )
    extras = sorted(set(specs) - set(required_ids), key=part_sort_key)
    if extras:
        raise ValueError(
            "image-batch part_execution_specs has unexpected Parts: "
            + ", ".join(extras)
        )
    parts = []
    for item in required:
        pid = item["part"]
        contract = contract_dir(root, job_id) / f"{pid}_contract.json"
        invocation = invocation_dir(root, job_id) / f"{pid}_matpool_invocation.json"
        candidate = candidate_dir(root, job_id) / f"{pid}_matpool.png"
        spec = specs.get(pid)
        command = build_generate_command(
            root,
            job_id,
            stage,
            pid,
            spec,
            candidate,
            contract,
            invocation,
        )
        parts.append(
            {
                "part": pid,
                "source_storyboard": display_path(root, item["source_storyboard"]),
                "prompt_candidates": prompt_candidates(root, job_id, pid),
                "candidate_path": display_path(root, candidate),
                "contract_path": display_path(root, contract),
                "invocation_manifest": display_path(root, invocation),
                "required_generate_flags": [
                    "--job-id",
                    job_id,
                    "--stage",
                    stage,
                    "--part",
                    pid,
                    "--contract",
                    display_path(root, contract),
                    "--invocation-manifest",
                    display_path(root, invocation),
                ],
                "depends_on": [
                    part_id(value)
                    for value in (spec.get("depends_on") or [])
                ],
                "command": command,
            }
        )
    merge_command = (
        f"python3 tools/image_batch_fanout.py --root . --job-id {job_id} "
        f"merge --stage {stage}"
    )
    plan = {
        "schema_version": 1,
        "job_id": job_id,
        "stage": stage,
        "fanout_policy": FANOUT_POLICY,
        "shared_state_policy": "only merge and loop gate/state writes are serialized",
        "required_parts": [item["part"] for item in parts],
        "parts": parts,
        "merge_command": merge_command,
        "plan_path": display_path(
            root,
            fanout_dir(root, job_id) / "fanout_plan.json",
        ),
        "plan_markdown": display_path(
            root,
            fanout_dir(root, job_id) / "fanout_plan.md",
        ),
    }
    execution = {
        "schema_version": 1,
        "job_id": job_id,
        "stage": stage,
        "coordinator_only_paths": [
            display_path(root, default_merged_contract(root, job_id)),
            display_path(
                root,
                job_dir(root, job_id)
                / "visual-assets"
                / "approved_visual_manifest.json",
            ),
        ],
        "packets": [
            execution_packet(root, job_id, stage, part)
            for part in parts
        ],
    }
    plan["stage_execution"] = stage_execution.seal_plan(root, execution)
    plan["plan_sha256"] = stage_execution.stable_hash(plan)
    validate_fanout_plan(root, plan)
    return plan


def write_plan_markdown(path, plan):
    lines = [
        "# Image Batch Fanout Plan",
        "",
        f"- Job: `{plan['job_id']}`",
        f"- Stage: `{plan['stage']}`",
        f"- Fanout policy: `{plan['fanout_policy']}`",
        "- Shared-state policy: Part generation writes isolated evidence; merge/QC/state writes are serialized.",
        "",
        "## Parts",
        "",
    ]
    for part in plan["parts"]:
        lines.extend(
            [
                f"### {part['part']}",
                "",
                f"- Source storyboard: `{part['source_storyboard']}`",
                f"- Candidate path: `{part['candidate_path']}`",
                f"- Part contract: `{part['contract_path']}`",
                f"- Invocation manifest: `{part['invocation_manifest']}`",
                f"- Required generate flags: `{' '.join(part['required_generate_flags'])}`",
            ]
        )
        if part["prompt_candidates"]:
            lines.append("- Prompt candidates:")
            lines.extend(f"  - `{prompt}`" for prompt in part["prompt_candidates"])
        else:
            lines.append("- Prompt candidates: none found yet")
        lines.append("")
    lines.extend(["## Merge", "", f"`{plan['merge_command']}`", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_plan(root, plan):
    out_dir = fanout_dir(root, plan["job_id"])
    json_path = out_dir / "fanout_plan.json"
    md_path = out_dir / "fanout_plan.md"
    validate_fanout_plan(root, plan)
    write_json(json_path, plan)
    write_plan_markdown(md_path, plan)
    return plan


def default_contract_paths(root, job_id):
    return sorted(contract_dir(root, job_id).glob("*_contract.json"))


def extract_parts(contract):
    parts = contract.get("parts")
    if isinstance(parts, list):
        return [item for item in parts if isinstance(item, dict)]
    return []


def merge_contracts(root, job_id, stage=DEFAULT_STAGE, contract_paths=None, out_contract=None):
    required = [item["part"] for item in required_storyboard_parts(root, job_id)]
    selected_paths = [resolve_path(root, path) for path in (contract_paths or [])]
    if not selected_paths:
        selected_paths = default_contract_paths(root, job_id)
    selected_paths = [path for path in selected_paths if path and path.exists()]

    report = {
        "schema_version": 1,
        "job_id": job_id,
        "stage": stage,
        "fanout_policy": FANOUT_POLICY,
        "required_parts": required,
        "part_contracts": [display_path(root, path) for path in selected_paths],
        "missing_part_contracts": [],
        "duplicate_parts": [],
        "contract_stage_mismatches": [],
        "contract_job_mismatches": [],
        "overall": "PASS",
    }
    contracts = []
    part_entries = {}
    part_sources = {}
    for path in selected_paths:
        contract = load_json(path)
        contracts.append((path, contract))
        if contract.get("job_id") not in {job_id, None, ""}:
            report["contract_job_mismatches"].append(display_path(root, path))
        if str(contract.get("stage") or stage).strip() != stage:
            report["contract_stage_mismatches"].append(display_path(root, path))
        for part in extract_parts(contract):
            pid = part_id(part.get("part") or part.get("id"))
            if not pid:
                continue
            if pid in part_entries:
                report["duplicate_parts"].append(pid)
                continue
            entry = dict(part)
            entry["part"] = pid
            entry.setdefault("part_contract", display_path(root, path))
            part_entries[pid] = entry
            part_sources[pid] = display_path(root, path)

    missing = [pid for pid in required if pid not in part_entries]
    report["missing_part_contracts"] = missing
    if missing or report["duplicate_parts"] or report["contract_stage_mismatches"] or report["contract_job_mismatches"]:
        report["overall"] = "FAIL"
        return report, None

    if not contracts:
        report["overall"] = "STOP"
        return report, None

    base = json.loads(json.dumps(contracts[0][1], ensure_ascii=False))
    base["job_id"] = job_id
    base["stage"] = stage
    base.setdefault("image_route", "matpool_gpt_image_2_edit")
    base.setdefault("preserve_api_route", True)
    base.setdefault("matpool_uses_real_image_inputs", True)
    base["fanout_policy"] = FANOUT_POLICY
    base["fanout_merge"] = {
        "merged_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "required_parts": required,
        "part_contracts": part_sources,
        "merge_report": display_path(root, fanout_dir(root, job_id) / "fanout_merge_report.json"),
    }
    base["parts"] = [part_entries[pid] for pid in sorted(part_entries, key=part_sort_key)]

    target = resolve_path(root, out_contract) if out_contract else default_merged_contract(root, job_id)
    report["merged_contract"] = display_path(root, target)
    return report, (target, base)


def write_merge_report(root, job_id, report):
    out_dir = fanout_dir(root, job_id)
    json_path = out_dir / "fanout_merge_report.json"
    md_path = out_dir / "fanout_merge_report.md"
    write_json(json_path, report)
    lines = [
        "# Image Batch Fanout Merge Report",
        "",
        f"- Overall: **{report['overall']}**",
        f"- Job: `{report['job_id']}`",
        f"- Stage: `{report['stage']}`",
        f"- Policy: `{report['fanout_policy']}`",
        f"- Merged contract: `{report.get('merged_contract', '')}`",
        "",
        "## Parts",
        "",
    ]
    for part in report.get("required_parts", []):
        lines.append(f"- `{part}`")
    lines.extend(
        [
            "",
            "## Checks",
            "",
            f"- missing_part_contracts: `{report.get('missing_part_contracts', [])}`",
            f"- duplicate_parts: `{report.get('duplicate_parts', [])}`",
            f"- contract_job_mismatches: `{report.get('contract_job_mismatches', [])}`",
            f"- contract_stage_mismatches: `{report.get('contract_stage_mismatches', [])}`",
            "",
        ]
    )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def command_list(value):
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str) and value.strip():
        return shlex.split(value)
    return []


def validate_image_command(part):
    command = command_list(part.get("command"))
    if len(command) < 2 or Path(command[1]).resolve() != GENERATOR.resolve():
        raise ValueError(
            f"{part.get('part')} command must call the project Matpool generator"
        )
    for flag in (
        "--prompt-file",
        "--file",
        "--job-id",
        "--stage",
        "--part",
        "--contract",
        "--invocation-manifest",
        "--no-retry",
    ):
        if flag not in command:
            raise ValueError(f"{part.get('part')} command is missing {flag}")
    return command


def run_part_command(
    root,
    job_id,
    part,
    stdout_path,
    stderr_path,
    runner=subprocess.run,
):
    pid = part["part"]
    command = command_list(part.get("command"))
    if not command:
        return {
            "part": pid,
            "status": "STOP",
            "returncode": 2,
            "error": "missing command in fanout plan",
        }
    try:
        command = validate_image_command(part)
    except ValueError as exc:
        return {
            "part": pid,
            "status": "STOP",
            "returncode": 2,
            "error": str(exc),
        }
    stdout_path = Path(stdout_path)
    stderr_path = Path(stderr_path)
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    proc = runner(command, cwd=root, text=True, capture_output=True, check=False)
    stdout_path.write_text(proc.stdout, encoding="utf-8")
    stderr_path.write_text(proc.stderr, encoding="utf-8")
    return {
        "part": pid,
        "status": "PASS" if proc.returncode == 0 else "FAIL",
        "returncode": proc.returncode,
        "duration_seconds": round(time.time() - started, 3),
        "stdout": display_path(root, stdout_path),
        "stderr": display_path(root, stderr_path),
    }


def completion_outputs(root, part):
    return [
        resolve_path(root, part["candidate_path"]),
        resolve_path(root, part["contract_path"]),
        resolve_path(root, part["invocation_manifest"]),
    ]


def rewrite_packet_staging_references(packet):
    """Remove packet-local staging paths from promoted text evidence."""
    replacements = [
        (str(Path(item["staged"]).resolve()), str(Path(item["canonical"]).resolve()))
        for item in packet.get("_stage_path_map") or []
    ]
    if not replacements:
        return
    for staged, _canonical in replacements:
        path = Path(staged)
        candidates = (
            [path]
            if path.is_file()
            else [
                child
                for child in path.rglob("*")
                if child.is_file()
            ]
            if path.is_dir()
            else []
        )
        for candidate in candidates:
            if candidate.suffix.lower() not in {".json", ".md", ".txt", ".csv"}:
                continue
            try:
                content = candidate.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            rewritten = content
            for old, new in replacements:
                rewritten = rewritten.replace(old, new)
            if rewritten != content:
                candidate.write_text(rewritten, encoding="utf-8")


def run_fanout(root, job_id, plan_path, max_workers, runner=subprocess.run):
    path = resolve_path(root, plan_path) if plan_path else fanout_dir(root, job_id) / "fanout_plan.json"
    if not path or not path.exists():
        raise SystemExit(f"fanout plan not found: {path}")
    plan = load_json(path)
    if plan.get("job_id") != job_id:
        raise ValueError(
            "CLI job_id does not match fanout plan job_id: "
            f"{job_id} != {plan.get('job_id')}"
        )
    validate_fanout_plan(root, plan)
    parts = plan.get("parts", [])
    execution = plan.get("stage_execution")
    by_id = {part["part"]: part for part in parts}
    results_by_id = {}
    committed = {}

    def dispatch(packet):
        packet_id = packet["packet_id"]
        canonical_part = by_id[packet_id]
        runtime_part = dict(canonical_part)
        runtime_part["command"] = list(packet["command"])
        for key in (
            "candidate_path",
            "contract_path",
            "invocation_manifest",
        ):
            runtime_part[key] = str(
                stage_execution.runtime_path(
                    root,
                    packet,
                    canonical_part[key],
                )
            )
        runtime_stdout = stage_execution.runtime_path(
            root,
            packet,
            fanout_dir(root, job_id)
            / "logs"
            / f"{packet_id}.stdout.txt",
        )
        runtime_stderr = stage_execution.runtime_path(
            root,
            packet,
            fanout_dir(root, job_id)
            / "logs"
            / f"{packet_id}.stderr.txt",
        )
        result = run_part_command(
            root,
            job_id,
            runtime_part,
            runtime_stdout,
            runtime_stderr,
            runner,
        )
        if result["status"] == "PASS":
            rewrite_packet_staging_references(packet)
        for key in ("stdout", "stderr"):
            if result.get(key):
                result[key] = display_path(
                    root,
                    stage_execution.canonical_path(
                        root,
                        packet,
                        result[key],
                    ),
                )
        required_outputs = completion_outputs(root, runtime_part)
        if (
            result["status"] == "PASS"
            and any(not path.is_file() for path in required_outputs)
        ):
            result["status"] = "FAIL"
            result["returncode"] = 1
            result["error"] = "generator did not produce every required output"
        results_by_id[packet_id] = result
        actual_outputs = [
            path
            for path in [
                *required_outputs,
                runtime_stdout,
                runtime_stderr,
            ]
            if path.is_file() and not path.is_symlink()
        ]
        return {
            "status": result["status"],
            "outputs": actual_outputs,
            "returncode": result["returncode"],
            "error": result.get("error", ""),
        }

    def commit(stage_report):
        for completion in stage_report["completions"]:
            packet_id = completion["packet_id"]
            if packet_id not in results_by_id:
                results_by_id[packet_id] = {
                    "part": packet_id,
                    "status": completion["status"],
                    "returncode": 2,
                    "error": completion.get(
                        "error",
                        "blocked by failed dependency",
                    ),
                }
        results = [results_by_id[part["part"]] for part in parts]
        report = {
            "schema_version": 1,
            "job_id": job_id,
            "stage": plan.get("stage", DEFAULT_STAGE),
            "fanout_policy": FANOUT_POLICY,
            "results": results,
            "overall": stage_report["overall"],
        }
        write_json(
            fanout_dir(root, job_id) / "fanout_run_report.json",
            report,
        )
        committed["report"] = report

    stage_execution.execute_plan(
        root,
        execution,
        dispatcher=dispatch,
        coordinator_commit=commit,
        max_workers=max_workers,
    )
    return committed["report"]


def main():
    parser = argparse.ArgumentParser(description="Plan, run, and merge safe image-batch Part fanout.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--job-id", required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--stage", default=DEFAULT_STAGE)
    plan_parser.add_argument("--json", action="store_true")

    merge_parser = subparsers.add_parser("merge")
    merge_parser.add_argument("--stage", default=DEFAULT_STAGE)
    merge_parser.add_argument("--contract", action="append", default=[])
    merge_parser.add_argument("--out-contract", default="")
    merge_parser.add_argument("--json", action="store_true")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--plan", default="")
    run_parser.add_argument("--max-workers", type=int, default=3)
    run_parser.add_argument("--merge", action="store_true", help="Merge contracts after all Part commands pass.")
    run_parser.add_argument("--json", action="store_true")

    args = parser.parse_args()
    root = Path(args.root).resolve()

    if args.command == "plan":
        try:
            plan = write_plan(root, build_plan(root, args.job_id, args.stage))
        except ValueError as exc:
            parser.error(str(exc))
        if args.json:
            print(json.dumps(plan, ensure_ascii=False, indent=2))
        else:
            print(f"Wrote: {plan['plan_path']}")
            print(f"Wrote: {plan['plan_markdown']}")
        return

    if args.command == "merge":
        report, merged = merge_contracts(root, args.job_id, args.stage, args.contract, args.out_contract)
        if merged:
            target, contract = merged
            write_json(target, contract)
        write_merge_report(root, args.job_id, report)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(report["overall"])
        if report["overall"] != "PASS":
            print(
                "image_batch_fanout merge failed: "
                f"missing_part_contracts={report.get('missing_part_contracts')} "
                f"duplicate_parts={report.get('duplicate_parts')} "
                f"contract_job_mismatches={report.get('contract_job_mismatches')} "
                f"contract_stage_mismatches={report.get('contract_stage_mismatches')}",
                file=sys.stderr,
            )
            sys.exit(1)
        return

    if args.command == "run":
        report = run_fanout(root, args.job_id, args.plan, args.max_workers)
        if report["overall"] == "PASS" and args.merge:
            merge_report, merged = merge_contracts(root, args.job_id, report["stage"])
            if merged:
                target, contract = merged
                write_json(target, contract)
            write_merge_report(root, args.job_id, merge_report)
            report["merge"] = merge_report
            report["overall"] = "PASS" if merge_report["overall"] == "PASS" else "FAIL"
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(report["overall"])
        if report["overall"] != "PASS":
            sys.exit(1)


if __name__ == "__main__":
    main()
