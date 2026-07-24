#!/usr/bin/env python3
import argparse
import csv
import datetime as dt
import hashlib
import json
import time
from pathlib import Path

from hash_gated_visual_qc import (
    active_visible_defects,
    current_fingerprint,
    display_path,
    load_state as load_visual_reuse_state,
    resolve_path,
    sha256_file,
)
from product_profile import load_product_profile, profile_requires_skincare_progression
from qc_input_binding import validate_input_binding
from storyboard_visual_acceptance import (
    build_acceptance,
    current_semantic_family_selection,
)
from subtitle_workflow_qc import removal_issues


PASSING_STATUSES = {"PASS", "REUSED_PASS"}
STATE_FILE = "qc_risk_ledger_state.json"
IMAGEGEN_CONTRACT_STAGES = {"image_sample", "image_sample_review", "image_batch_qc"}
CONTINUITY_STAGES = {"image_batch_qc", "seedance_prompt", "request_qc", "pre_seedance_pack"}
GEOMETRY_STAGES = {"image_batch_qc", "seedance_prompt", "request_qc", "pre_seedance_pack"}
PROMPT_STAGES = {"seedance_prompt", "request_qc", "pre_seedance_pack"}
REQUEST_STAGES = {"request_qc", "pre_seedance_pack"}
FINAL_QC_STAGE = "final_qc"
FINISHING_STAGE = "finishing"
SUBTITLE_REMOVAL_STAGE = "subtitle_removal"
SOURCE_BLUEPRINT_STAGE = "source_blueprint"
STORYBOARD_SEMANTIC_FAMILIES = (
    "geometry_appearance",
    "identity_product_material_integrity",
    "cross_part_continuity",
    "skincare_progression",
)


def stable_hash(value):
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def deterministic_status(evidence):
    if not evidence:
        return "STOP", "required deterministic evidence is missing"
    statuses = {str(item.get("status") or "STOP").upper() for item in evidence}
    if "FAIL" in statuses:
        return "FAIL", "deterministic evidence found a defect"
    if statuses == {"PASS"}:
        return "PASS", "all deterministic evidence passed"
    return "STOP", "deterministic evaluation is incomplete"


def semantic_status(evidence, fingerprint_hash):
    current = [
        item
        for item in evidence
        if item.get("fingerprint_hash") == fingerprint_hash
    ]
    statuses = {str(item.get("status") or "STOP").upper() for item in current}
    if "FAIL" in statuses:
        return "FAIL", "current semantic review found a defect", False
    if "PASS" in statuses:
        return "PASS", "current semantic review passed", False
    if current:
        return "STOP", "current semantic review could not decide", False
    return "STOP", "semantic review required", True


def evaluate_risk_families(job_id, stage, families, previous=None, timestamp=None):
    generated_at = timestamp or dt.datetime.now().isoformat(timespec="seconds")
    previous_families = (previous or {}).get("families") or {}
    results = {}
    review_families = []

    for family in families:
        name = family["name"]
        fingerprint_hash = family.get("fingerprint_hash") or stable_hash(family.get("fingerprint") or {})
        prior = previous_families.get(name) or {}
        can_reuse = (
            prior.get("status") in PASSING_STATUSES
            and prior.get("fingerprint_hash") == fingerprint_hash
            and family.get("reuse_evidence_valid") is True
            and not family.get("defects")
        )
        if can_reuse:
            status = "REUSED_PASS"
            reason = "fingerprint unchanged and prior PASS evidence is current"
            evidence = prior.get("evidence") or []
        else:
            evidence = family.get("evidence") or []
            if family.get("defects"):
                status = "FAIL"
                reason = "user-visible defect invalidated this risk scope"
            elif family.get("evaluation_blocker"):
                status = "STOP"
                reason = str(family["evaluation_blocker"])
            elif family.get("kind") == "deterministic":
                status, reason = deterministic_status(evidence)
            else:
                status, reason, review_required = semantic_status(evidence, fingerprint_hash)
                if review_required:
                    review_families.append({
                        "name": name,
                        "fingerprint_hash": fingerprint_hash,
                        "scope": family.get("scope") or {"job_id": job_id, "stage": stage},
                        "defect_scopes": family.get("defects") or [],
                    })

        results[name] = {
            "kind": family.get("kind", "semantic"),
            "scope": family.get("scope") or {"job_id": job_id, "stage": stage},
            "status": status,
            "fingerprint_hash": fingerprint_hash,
            "reason": reason,
            "evidence": evidence,
            "defect_scopes": family.get("defects") or [],
            "retry_scope": next(
                (
                    item.get("retry_scope")
                    for item in evidence
                    if item.get("retry_scope")
                    and str(item.get("status") or "").upper() in {"FAIL", "STOP"}
                ),
                None,
            ),
            "decision_trace": {
                "active_seconds": float(family.get("active_seconds") or 0.0),
                "wait_seconds": float(family.get("wait_seconds") or 0.0),
                "decision": status,
                "reason": reason,
            },
        }

    statuses = {family["status"] for family in results.values()}
    if statuses.issubset(PASSING_STATUSES):
        overall = "PASS"
    elif "FAIL" in statuses:
        overall = "FAIL"
    else:
        overall = "STOP"
    review_request = {
        "job_id": job_id,
        "stage": stage,
        "created_at": generated_at,
        "required": bool(review_families),
        "invocation_count": 1 if review_families else 0,
        "families": review_families,
    }
    review_request["request_id"] = stable_hash({
        "job_id": job_id,
        "stage": stage,
        "families": review_families,
    })
    previous_request = (previous or {}).get("semantic_review_request") or {}
    if previous_request.get("request_id") == review_request["request_id"]:
        review_request["created_at"] = (
            previous_request.get("created_at") or generated_at
        )
    return {
        "version": 1,
        "job_id": job_id,
        "stage": stage,
        "updated_at": generated_at,
        "overall": overall,
        "families": results,
        "semantic_review_request": review_request,
    }


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def qc_evidence(root, name, paths):
    seen = set()
    for path in paths:
        if path is None or path in seen:
            continue
        seen.add(path)
        report = load_json(path) if path.exists() else {}
        status = str(report.get("overall") or "").upper()
        if status in {"PASS", "FAIL", "STOP"}:
            return {
                "name": name,
                "status": status,
                "path": display_path(root, path),
                "sha256": sha256_file(path),
            }
    first = next(iter(paths), None)
    return {
        "name": name,
        "status": "STOP",
        "path": display_path(root, first),
        "reason": "missing required QC evidence",
    }


def file_fingerprint(root, paths):
    files = {}
    for path in sorted({path for path in paths if path}):
        key = display_path(root, path)
        if path.is_file():
            files[key] = {"kind": "file", "sha256": sha256_file(path)}
        elif path.is_dir():
            directory_files = {
                str(child.relative_to(path)): sha256_file(child)
                for child in sorted(path.rglob("*"))
                if child.is_file()
            }
            files[key] = {
                "kind": "directory",
                "files": directory_files,
            }
        else:
            files[key] = {"kind": "missing"}
    return files


def visual_family_payload(fingerprint):
    return {
        "version": fingerprint.get("version"),
        "job_id": fingerprint.get("job_id"),
        "active_final_image_hashes": fingerprint.get("active_final_image_hashes") or {},
        "approved_visual_manifest_mapping": fingerprint.get("approved_visual_manifest_mapping") or {},
    }


def evidence_still_current(root, evidence):
    if not evidence:
        return False
    for item in evidence:
        path = resolve_path(root, item.get("path", ""))
        if not path or not path.is_file():
            return False
        report = load_json(path)
        family_name = item.get("family_name")
        if family_name:
            family_results = (report.get("qc_risk_review") or {}).get("family_results") or {}
            family_status = family_results.get(family_name)
            if family_status is not None and str(family_status).upper() != "PASS":
                return False
            if family_status is None and str(report.get("overall") or "").upper() != "PASS":
                return False
        elif str(report.get("overall") or "").upper() != "PASS":
            return False
        if item.get("sha256") and sha256_file(path) != item["sha256"]:
            return False
        subject_manifest = item.get("subject_manifest")
        if isinstance(subject_manifest, dict):
            binding_ok, _ = validate_input_binding(root, report.get("input_binding"))
            if not binding_ok:
                return False
            subject_paths = [resolve_path(root, raw) for raw in subject_manifest]
            if file_fingerprint(root, subject_paths) != subject_manifest:
                return False
    return True


def evidence_covers(evidence, required):
    required_names = {item.get("name") for item in required}
    evidence_names = {item.get("name") for item in evidence}
    return required_names.issubset(evidence_names)


def semantic_family_evidence_current(root, evidence, family_name, fingerprint_hash):
    if not evidence:
        return False
    for item in evidence:
        binding = item.get("review_binding")
        if isinstance(binding, dict):
            path = resolve_path(root, item.get("path", ""))
            if not path or not path.is_file():
                return False
            if item.get("sha256") and sha256_file(path) != item["sha256"]:
                return False
            report = load_json(path)
            report_review = report.get("qc_risk_review") or {}
            if (
                not checker_report_structure_valid(report)
                or report_review.get("request_id") != binding.get("request_id")
                or report_review.get("family_fingerprints")
                != binding.get("family_fingerprints")
                or report_review.get("family_results") != binding.get("family_results")
                or not review_binding_current(root, binding, family_name, fingerprint_hash)
            ):
                return False
            continue
        path = resolve_path(root, item.get("path", ""))
        if not path or not path.is_file():
            return False
        if item.get("sha256") and sha256_file(path) != item["sha256"]:
            return False
        report = load_json(path)
        if not strict_checker_report(report, root):
            return False
        review = report.get("qc_risk_review") or {}
        if (review.get("family_fingerprints") or {}).get(family_name) != fingerprint_hash:
            return False
        if str((review.get("family_results") or {}).get(family_name) or "").upper() != "PASS":
            return False
    return True


def visual_context_current(root, context):
    if not isinstance(context, dict) or context.get("role") != "overview":
        return False
    compare = resolve_path(root, context.get("path"))
    if not compare or not compare.is_file() or sha256_file(compare) != context.get("sha256"):
        return False
    artifacts = context.get("source_artifacts")
    return bool(artifacts) and all(
        (path := resolve_path(root, item.get("path")))
        and path.is_file()
        and sha256_file(path) == item.get("sha256")
        for item in artifacts
        if isinstance(item, dict)
    ) and all(isinstance(item, dict) for item in artifacts)


def checker_report_structure_valid(report):
    review = report.get("qc_risk_review") or {}
    fingerprints = review.get("family_fingerprints") or {}
    results = review.get("family_results") or {}
    required_checks = {
        "storyboard_visual_request_integrity",
        "storyboard_visual_context_binding",
        "qc_risk_request_binding",
        "qc_risk_family_results",
        "qc_risk_top_level_result",
    }
    passing_checks = {
        item.get("name")
        for item in report.get("checks") or []
        if item.get("status") == "PASS"
    }
    return (
        bool(fingerprints)
        and set(results) == set(fingerprints)
        and all(str(status).upper() in {"PASS", "FAIL", "STOP"} for status in results.values())
        and bool(review.get("request_id"))
        and bool(review.get("request_sha256"))
        and review.get("invocation_count") == 1
        and required_checks.issubset(passing_checks)
    )


def strict_checker_report(report, root):
    return checker_report_structure_valid(report) and visual_context_current(
        root,
        (report.get("qc_risk_review") or {}).get("canonical_compare_context"),
    )


def generic_checker_report_current(root, report, stage, current_job_id):
    review = report.get("qc_risk_review") or {}
    fields = report.get("fields") or {}
    job_id = str(fields.get("Job") or "")
    if job_id != str(current_job_id or ""):
        return False
    expected_request = (
        root
        / "output"
        / job_id
        / "checks"
        / f"{stage}_semantic_review_request.json"
    ).resolve()
    request_path = resolve_path(root, review.get("request_path"))
    if not request_path or request_path.resolve() != expected_request or not request_path.is_file():
        return False
    if sha256_file(request_path) != review.get("request_sha256"):
        return False
    request = load_json(request_path)
    requested = {
        str(item.get("name") or ""): str(item.get("fingerprint_hash") or "")
        for item in request.get("families") or []
        if item.get("name") and item.get("fingerprint_hash")
    }
    passing_checks = {
        item.get("name")
        for item in report.get("checks") or []
        if item.get("status") == "PASS"
    }
    family_results = review.get("family_results") or {}
    severities = {"PASS": 0, "FAIL": 1, "STOP": 2}
    normalized_results = {
        str(name): str(status).upper() for name, status in family_results.items()
    }
    worst_result = (
        max(normalized_results.values(), key=lambda value: severities.get(value, 3))
        if normalized_results
        else "STOP"
    )
    return bool(requested) and all([
        request.get("required") is True,
        request.get("invocation_count") == 1,
        str(request.get("job_id") or "") == job_id,
        str(request.get("stage") or "") == str(fields.get("Stage") or "") == stage,
        request.get("request_id") == review.get("request_id"),
        requested == (review.get("family_fingerprints") or {}),
        set(normalized_results) == set(requested),
        all(value in severities for value in normalized_results.values()),
        str(report.get("overall") or "").upper() == worst_result,
        review.get("invocation_count") == 1,
        "qc_risk_request_binding" in passing_checks,
    ])


def review_binding_current(root, binding, family_name, fingerprint_hash):
    return (
        (binding.get("family_fingerprints") or {}).get(family_name) == fingerprint_hash
        and str((binding.get("family_results") or {}).get(family_name) or "").upper()
        == "PASS"
        and bool(binding.get("request_id"))
        and bool(binding.get("request_sha256"))
        and binding.get("invocation_count") == 1
        and binding.get("validated") is True
    )


def defects_for_family(defects, family_name):
    scoped = []
    for defect in defects:
        declared = defect.get("family", defect.get("risk_family"))
        if isinstance(declared, list):
            declared_families = {str(item) for item in declared}
        elif declared:
            declared_families = {str(declared)}
        else:
            declared_families = set(STORYBOARD_SEMANTIC_FAMILIES)
        if family_name in declared_families:
            scoped.append(defect)
    return scoped


def downstream_storyboard_visual_families(root, job, previous):
    job_id = job.get("id", "")
    previous_families = previous.get("families") or {}
    selected, selection_blocker = current_semantic_family_selection(root, job)
    if not selected:
        selected = [
            {
                "name": name,
                "fingerprint_hash": previous_families[name].get("fingerprint_hash", ""),
            }
            for name in STORYBOARD_SEMANTIC_FAMILIES
            if name in previous_families
        ]
        if not selected:
            return []

    visible_defects = active_visible_defects(root, job_id)
    families = []
    for selected_family in selected:
        name = selected_family["name"]
        fingerprint_hash = str(selected_family.get("fingerprint_hash") or "")
        prior = previous_families.get(name) or {}
        evidence = prior.get("evidence") or []
        reusable = (
            prior.get("status") in PASSING_STATUSES
            and prior.get("fingerprint_hash") == fingerprint_hash
            and bool(fingerprint_hash)
            and semantic_family_evidence_current(
                root,
                evidence,
                name,
                fingerprint_hash,
            )
        )
        families.append({
            "name": name,
            "kind": "semantic",
            "fingerprint_hash": fingerprint_hash,
            "reuse_evidence_valid": reusable,
            "evidence": [],
            "defects": defects_for_family(visible_defects, name),
            "evaluation_blocker": (
                selection_blocker
                or "unified storyboard visual PASS is stale; rerun image_batch_qc"
                if not reusable
                else ""
            ),
            "scope": {"job_id": job_id, "asset_group": "approved_storyboards"},
        })
    return families


def report_declared_input_paths(root, report):
    raw_paths = []

    def visit(value, key=""):
        if isinstance(value, dict):
            for child_key, child in value.items():
                visit(child, str(child_key))
        elif isinstance(value, list):
            for child in value:
                visit(child, key)
        elif isinstance(value, str) and (
            key == "path"
            or key.endswith("_path")
            or key in {"shot_line_map", "manifest_path"}
        ):
            raw_paths.append(value)

    visit(report)
    return [resolve_path(root, raw) for raw in raw_paths if resolve_path(root, raw)]


def program_evidence_for_current_inputs(root, evidence, subject_paths):
    if evidence.get("status") != "PASS":
        return evidence
    report_path = resolve_path(root, evidence.get("path", ""))
    if not report_path or not report_path.is_file():
        return evidence
    report = load_json(report_path)
    binding_ok, binding_reason = validate_input_binding(root, report.get("input_binding"))
    if not binding_ok:
        evidence = dict(evidence)
        evidence["status"] = "STOP"
        evidence["reason"] = binding_reason
        return evidence
    declared_paths = report_declared_input_paths(root, report)
    subjects = sorted({path for path in [*subject_paths, *declared_paths] if path})
    evidence = dict(evidence)
    subject_manifest = file_fingerprint(root, subjects)
    evidence["subject_manifest"] = subject_manifest
    evidence["subject_fingerprint"] = stable_hash(subject_manifest)
    missing_declared = [
        display_path(root, path)
        for path in declared_paths
        if not path.exists()
    ]
    if missing_declared:
        evidence["status"] = "STOP"
        evidence["reason"] = f"program QC input manifest has missing paths: {missing_declared}"
        return evidence
    return evidence


def visual_subject_paths(root, job_id):
    manifest = root / "output" / job_id / "visual-assets" / "approved_visual_manifest.json"
    paths = [manifest]
    data = load_json(manifest) if manifest.is_file() else {}
    for entry in (data.get("part_storyboards") or {}).values():
        if not isinstance(entry, dict):
            continue
        path = resolve_path(root, entry.get("path", ""), base=manifest.parent)
        if path:
            paths.append(path)
    return paths


def prompt_subject_paths(root, job_id):
    output = root / "output" / job_id
    prompt_directories = [
        output / "seedance" / "prompts",
        output / "seedance_web_final" / "prompts",
    ]
    paths = [
        output / "seedance" / "director_plan.json",
        output / "voiceover" / "shot_line_map.md",
        output / "剧情分析" / "source_rhythm.json",
        *prompt_directories,
    ]
    for directory in [output / "seedance", *prompt_directories]:
        if directory.exists():
            paths.extend(path for path in directory.rglob("*prompt*.txt") if path.is_file())
            paths.extend(path for path in directory.rglob("*Seedance提示词*.txt") if path.is_file())
    return paths


def request_subject_paths(root, job_id):
    output = root / "output" / job_id
    request_dir = output / "seedance" / "requests"
    paths = prompt_subject_paths(root, job_id) + [root / "rules" / "SEEDANCE_MODEL.json"]
    if request_dir.exists():
        paths.extend(request_dir.glob("*request_prepared.json"))
    return paths


def audio_subject_paths(root, job_id):
    output = root / "output" / job_id
    suffixes = {".mp3", ".wav", ".m4a", ".aac", ".flac"}
    return [
        path
        for directory in (output / "audio-boundary", output / "seedance_web_final", output / "seedance" / "requests")
        if directory.exists()
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in suffixes
    ]


def legacy_visual_previous(root, job_id):
    snapshot = load_visual_reuse_state(root, job_id)
    if not snapshot:
        return {}
    reports = [
        {"name": name, **report}
        for name, report in (snapshot.get("reused_reports") or {}).items()
    ]
    payload = visual_family_payload(snapshot.get("fingerprint") or {})
    family = {
        "status": "PASS",
        "fingerprint_hash": stable_hash(payload),
        "evidence": reports,
    }
    return {"families": {"visual_integrity": family, "visual_contracts": dict(family)}}


def ledger_state_path(root, job_id):
    return root / "output" / job_id / "checks" / STATE_FILE


def load_previous_ledger(root, job_id):
    path = ledger_state_path(root, job_id)
    if path.exists():
        return load_json(path)
    return legacy_visual_previous(root, job_id)


def generation_pack_paths(root, job_id):
    output = root / "output" / job_id
    paths = [
        output / "seedance" / "director_plan.json",
        output / "seedance" / "handoff_mode.json",
        root / "rules" / "SEEDANCE_MODEL.json",
    ]
    for directory in (
        output / "seedance_web_final" / "prompts",
        output / "seedance" / "prompts",
        output / "voiceover",
        output / "seam",
    ):
        if directory.exists():
            paths.extend(path for path in directory.rglob("*") if path.is_file())
    for path in (output / "seedance_web_final").glob("reference_audio*"):
        if path.is_file():
            paths.append(path)
    request_dir = output / "seedance" / "requests"
    if request_dir.exists():
        paths.extend(sorted(request_dir.glob("*request_prepared.json")))
        paths.extend(sorted(path for path in request_dir.glob("reference_audio*") if path.is_file()))
    seedance_dir = output / "seedance"
    if seedance_dir.exists():
        paths.extend(sorted(path for path in seedance_dir.glob("*素材角色表*") if path.is_file()))
        paths.extend(sorted(path for path in seedance_dir.glob("*prompt*.txt") if path.is_file()))
    return paths


def source_fidelity_paths(root, job_id):
    output = root / "output" / job_id
    return [
        output / "剧情分析" / "source_rhythm.json",
        output / "剧情分析" / "raw_asr.json",
        output / "voiceover" / "source_script_fidelity.md",
        output / "voiceover" / "source_replication_fidelity.md",
    ]


def line_edit_audit(root, job_id):
    plan = load_json(root / "output" / job_id / "seedance" / "director_plan.json")
    audit = []
    for part in plan.get("parts") or []:
        part_id = str(part.get("id") or "")
        beats = {
            str(beat.get("id") or ""): beat
            for beat in part.get("beats") or []
            if isinstance(beat, dict)
        }
        for group in part.get("speech_groups") or []:
            if not isinstance(group, dict):
                continue
            group_id = str(group.get("id") or "")
            source_line = "".join(
                str((beats.get(str(beat_id)) or {}).get("source_line") or "")
                for beat_id in group.get("beat_ids") or []
            )
            for index, edit in enumerate(group.get("line_edits") or [], start=1):
                if not isinstance(edit, dict):
                    continue
                evidence = {
                    key: edit[key]
                    for key in (
                        "request_evidence",
                        "source_slot_evidence",
                        "fact_evidence",
                    )
                    if key in edit
                }
                audit.append({
                    "id": f"{part_id}:{group_id}:{index}",
                    "part_id": part_id,
                    "speech_group_id": group_id,
                    "edit_index": index,
                    "source_line": source_line,
                    "target_line": str(group.get("line") or ""),
                    "kind": str(edit.get("kind") or ""),
                    "from": str(edit.get("from") or ""),
                    "to": str(edit.get("to") or ""),
                    "reason": str(edit.get("reason") or ""),
                    "reason_detail": str(edit.get("reason_detail") or ""),
                    "evidence": evidence,
                })
    return audit


def checker_paths(root, job_id, stage, artifact=""):
    paths = []
    artifact_path = resolve_path(root, artifact) if artifact else None
    if artifact_path and artifact_path.suffix.lower() == ".md":
        paths.append(artifact_path.with_name(artifact_path.stem + "_qc.json"))
    paths.append(root / "output" / job_id / "checks" / f"{stage}_gate_review_qc.json")
    return paths


def checker_evidence(root, job_id, stage, family_name, fingerprint_hash, artifact=""):
    evidence = qc_evidence(root, "batched_checker_review", checker_paths(root, job_id, stage, artifact))
    path = resolve_path(root, evidence.get("path", ""))
    if not path or not path.is_file():
        return []
    report = load_json(path)
    unified_storyboard_family = (
        stage == "image_batch_qc"
        and family_name in STORYBOARD_SEMANTIC_FAMILIES
    )
    if (
        stage in {FINISHING_STAGE, SUBTITLE_REMOVAL_STAGE}
        and not generic_checker_report_current(root, report, stage, job_id)
    ):
        return []
    if unified_storyboard_family and not strict_checker_report(report, root):
        return []
    review = report.get("qc_risk_review") or {}
    if unified_storyboard_family:
        archive_path = resolve_path(root, review.get("immutable_report_path"))
        if not archive_path or not archive_path.is_file():
            return []
        archive_report = load_json(archive_path)
        archive_review = archive_report.get("qc_risk_review") or {}
        if (
            not checker_report_structure_valid(archive_report)
            or archive_review.get("request_id") != review.get("request_id")
            or archive_review.get("family_fingerprints")
            != review.get("family_fingerprints")
            or archive_review.get("family_results") != review.get("family_results")
        ):
            return []
        evidence["path"] = display_path(root, archive_path)
        evidence["sha256"] = sha256_file(archive_path)
        report = archive_report
        review = archive_review
    fingerprints = review.get("family_fingerprints") or {}
    bound = fingerprints.get(family_name)
    if bound == fingerprint_hash:
        family_results = review.get("family_results") or {}
        if family_name in family_results:
            evidence["status"] = str(family_results[family_name]).upper()
        elif len(fingerprints) > 1 and evidence.get("status") != "PASS":
            evidence["status"] = "STOP"
            evidence["reason"] = "batched checker did not report a result for this family"
        evidence["fingerprint_hash"] = fingerprint_hash
        evidence["family_name"] = family_name
        evidence["binding"] = "explicit"
        evidence["wait_seconds"] = float(review.get("wait_seconds") or 0.0)
        if unified_storyboard_family:
            evidence["review_binding"] = {
                "family_fingerprints": dict(review.get("family_fingerprints") or {}),
                "family_results": dict(review.get("family_results") or {}),
                "request_id": review.get("request_id"),
                "request_sha256": review.get("request_sha256"),
                "active_input_fingerprint": review.get("active_input_fingerprint"),
                "canonical_compare_context": review.get("canonical_compare_context"),
                "invocation_count": review.get("invocation_count"),
                "validated": True,
            }
        fields = report.get("fields") or {}
        if evidence["status"] in {"FAIL", "STOP"}:
            evidence["retry_scope"] = {
                "failed_item": fields.get("Failed item"),
                "failure_type": fields.get("Failure type"),
                "retry_variable": fields.get("Retry variable"),
                "reason": fields.get("Reason"),
            }
        return [evidence]
    return []


def stage_names(stage):
    names = [stage]
    if stage in {"image_sample", "image_sample_review"}:
        names.extend(["image_sample", "image_sample_review"])
    elif stage == "image_batch_qc":
        names.append("image_batch")
    return list(dict.fromkeys(name for name in names if name))


def named_check_pass(path, name):
    report = load_json(path)
    return any(
        item.get("name") == name and str(item.get("status") or "").upper() == "PASS"
        for item in report.get("checks") or []
    )


def handoff_mode(root, job):
    path = root / "output" / job.get("id", "") / "seedance" / "handoff_mode.json"
    mode = str(load_json(path).get("mode") or job.get("handoff_mode") or "").lower()
    if mode in {"web", "api", "both"}:
        return mode
    direct_generation_states = {"generation_approved", "seedance_generating", "final_qc"}
    if job.get("status") in direct_generation_states or job.get("next_stage") in direct_generation_states:
        return "api"
    return "web"


def final_dir_has_audio(root, job_id):
    directory = root / "output" / job_id / "seedance_web_final"
    suffixes = {".mp3", ".wav", ".m4a", ".aac", ".flac"}
    return directory.exists() and any(
        path.is_file() and path.suffix.lower() in suffixes for path in directory.rglob("*")
    )


def report_candidates(checks, names, suffix, fallbacks=()):
    paths = [checks / f"{name}_{suffix}.json" for name in names]
    paths.extend(checks / fallback for fallback in fallbacks)
    return paths


def visual_contract_evidence(root, job, stage):
    job_id = job.get("id", "")
    output = root / "output" / job_id
    checks = output / "checks"
    names = stage_names(stage)
    evidence = []
    if stage in IMAGEGEN_CONTRACT_STAGES:
        evidence.append(program_evidence_for_current_inputs(root, qc_evidence(
            root,
            "codex_imagegen_contract",
            report_candidates(
                checks,
                names,
                "codex_imagegen_contract_qc",
                ("codex_imagegen_contract_qc.json",),
            ) + [
                output / "image-batch" / "codex_imagegen_contract_qc.json",
                output / "改图小样" / "codex_imagegen_contract_qc.json",
            ],
        ), visual_subject_paths(root, job_id)))
    if stage in CONTINUITY_STAGES:
        evidence.append(program_evidence_for_current_inputs(root, qc_evidence(
            root,
            "cross_part_continuity",
            report_candidates(
                checks,
                names,
                "cross_part_continuity_qc",
                ("cross_part_continuity_qc.json",),
            ),
        ), visual_subject_paths(root, job_id)))
    if stage in GEOMETRY_STAGES:
        evidence.append(program_evidence_for_current_inputs(root, qc_evidence(
            root,
            "storyboard_geometry",
            report_candidates(
                checks,
                names,
                "storyboard_geometry_qc",
                ("storyboard_geometry_qc.json",),
            ),
        ), visual_subject_paths(root, job_id)))
    profile, _, _ = load_product_profile(root, job)
    if stage in CONTINUITY_STAGES and profile_requires_skincare_progression(profile):
        evidence.append(program_evidence_for_current_inputs(root, qc_evidence(
            root,
            "skincare_progression",
            report_candidates(
                checks,
                names,
                "skincare_progression_qc",
                ("skincare_progression_qc.json",),
            ),
        ), visual_subject_paths(root, job_id)))
    return evidence


def generation_pack_evidence(root, job, stage):
    job_id = job.get("id", "")
    output = root / "output" / job_id
    checks = output / "checks"
    names = stage_names(stage)
    visual = program_evidence_for_current_inputs(root, qc_evidence(
        root,
        "visual_asset_manifest",
        report_candidates(
            checks,
            names,
            "visual_asset_manifest_qc",
            ("visual_asset_manifest_qc.json",),
        ) + [output / "visual-assets" / "visual_asset_manifest_qc.json"],
    ), visual_subject_paths(root, job_id))
    evidence = [visual]
    visual_path = resolve_path(root, visual.get("path", ""))
    if stage in IMAGEGEN_CONTRACT_STAGES and (
        not visual_path or not named_check_pass(visual_path, "shot_label_metadata_policy")
    ):
        evidence.append({
            "name": "shot_label_metadata_policy",
            "status": "STOP",
            "path": visual.get("path", ""),
            "reason": "visual manifest schema v2 Shot-label metadata policy is missing",
        })
    if stage not in PROMPT_STAGES:
        return evidence

    evidence.append(program_evidence_for_current_inputs(root, qc_evidence(
        root,
        "seedance_prompt_contract",
        [checks / f"{stage}_seedance_prompt_contract_qc.json"],
    ), prompt_subject_paths(root, job_id)))
    mode = handoff_mode(root, job)
    if mode in {"web", "both"} and (
        not visual_path or not named_check_pass(visual_path, "final_upload_dir_exists")
    ):
        evidence.append({
            "name": "final_upload_dir",
            "status": "STOP",
            "path": visual.get("path", ""),
            "reason": "web handoff mode requires final-directory QC",
        })
    if stage in REQUEST_STAGES and mode in {"api", "both"}:
        request_dir = output / "seedance" / "requests"
        candidates = [request_dir / "request_qc.json"]
        if request_dir.exists():
            candidates.extend(sorted(request_dir.rglob("*request*qc*.json")))
        evidence.append(program_evidence_for_current_inputs(
            root,
            qc_evidence(root, "request_body", candidates),
            request_subject_paths(root, job_id),
        ))
    if stage in REQUEST_STAGES and final_dir_has_audio(root, job_id):
        request_dir = output / "seedance" / "requests"
        candidates = []
        if request_dir.exists():
            candidates.extend(sorted(request_dir.rglob("*audio*duration*qc*.json")))
            candidates.extend(sorted(request_dir.rglob("*duration*audio*qc*.json")))
        candidates.extend(sorted(output.rglob("*audio*duration*qc*.json")))
        candidates.extend(sorted(output.rglob("*duration*audio*qc*.json")))
        evidence.append(program_evidence_for_current_inputs(
            root,
            qc_evidence(root, "audio_duration", candidates),
            audio_subject_paths(root, job_id),
        ))
    return evidence


def ledger_failure_message(ledger):
    review = ledger.get("semantic_review_request") or {}
    failures = []
    if review.get("required"):
        names = ", ".join(item.get("name", "") for item in review.get("families") or [])
        failures.append(
            "semantic review required for changed QC risk families: "
            f"{names}. Run one batched checker review from the semantic review request."
        )
    messages = {
        "seedance_prompt_contract": "missing passing Seedance prompt contract QC",
        "final_upload_dir": "web handoff mode requires final-directory QC",
        "request_body": "missing passing request body QC",
        "audio_duration": "final web upload audio exists but no passing audio duration QC was found",
        "visual_asset_manifest": "missing passing visual asset manifest QC",
        "codex_imagegen_contract": "missing passing GPT Image contract QC",
        "cross_part_continuity": "missing passing cross-Part continuity QC",
        "storyboard_geometry": "missing passing storyboard geometry / API-effect QC",
        "skincare_progression": "missing passing skincare progression QC",
        "shot_label_metadata_policy": "visual manifest schema v2 Shot-label metadata policy is missing",
    }
    for family in (ledger.get("families") or {}).values():
        family_messages_before = len(failures)
        for evidence in family.get("evidence") or []:
            if evidence.get("status") not in PASSING_STATUSES:
                failures.append(messages.get(evidence.get("name"), evidence.get("reason") or evidence.get("name", "QC failed")))
        if family.get("status") not in PASSING_STATUSES and len(failures) == family_messages_before:
            failures.append(family.get("reason") or f"{family.get('kind', 'QC')} family did not pass")
    return "; ".join(dict.fromkeys(failures)) or "QC Risk Ledger did not pass"


def final_qc_report_path(root, job_id, artifact=""):
    artifact_path = resolve_path(root, artifact) if artifact else None
    if artifact_path and artifact_path.suffix.lower() == ".md":
        candidate = artifact_path.with_suffix(".json")
        if candidate.is_file():
            return candidate
    return root / "output" / job_id / "final" / "final_qc.json"


def final_artifact_family(root, job_id, artifact=""):
    report_path = final_qc_report_path(root, job_id, artifact)
    report = load_json(report_path) if report_path.is_file() else {}
    current_videos = {}
    problems = []
    for item in report.get("videos") or []:
        path = resolve_path(root, item.get("path", ""))
        display = display_path(root, path)
        if not path or not path.is_file():
            current_videos[display] = None
            problems.append(("STOP", f"final video is missing: {display}"))
            continue
        digest = sha256_file(path)
        current_videos[display] = digest
        expected = str(item.get("sha256") or "")
        if not expected:
            problems.append(("STOP", f"final QC has no video hash binding: {display}"))
        elif expected != digest:
            problems.append(("FAIL", f"final video hash does not match final QC: {display}"))

    report_status = str(report.get("overall") or "STOP").upper()
    if not report_path.is_file():
        status, reason = "STOP", f"missing final QC report: {display_path(root, report_path)}"
    elif report_status in {"FAIL", "STOP"}:
        status, reason = report_status, "final technical QC did not pass"
    elif not report.get("videos"):
        status, reason = "STOP", "final QC report contains no generated video"
    elif problems:
        status = "FAIL" if any(item[0] == "FAIL" for item in problems) else "STOP"
        reason = "; ".join(item[1] for item in problems)
    else:
        status, reason = "PASS", "final QC is bound to the exact current video hash"

    evidence = {
        "name": "final_video_artifact",
        "status": status,
        "path": display_path(root, report_path),
        "reason": reason,
    }
    if report_path.is_file():
        evidence["sha256"] = sha256_file(report_path)
    return {
        "name": "final_artifact_integrity",
        "kind": "deterministic",
        "scope": {"job_id": job_id, "artifact": "final_video"},
        "fingerprint": {
            "report": evidence.get("sha256"),
            "videos": current_videos,
        },
        "reuse_evidence_valid": evidence_still_current(
            root,
            [evidence] if evidence.get("sha256") else [],
        ),
        "evidence": [evidence],
    }


def build_subtitle_removal_ledger(root, job_id, stage, artifact, previous, write):
    output = root / "output" / job_id
    checks = output / "checks"
    report_path = output / "subtitle_removal" / "subtitle_removal_report.json"
    issues = removal_issues(report_path)
    report = load_json(report_path) if report_path.is_file() else {}
    deterministic = {
        "name": "subtitle_removal_contract",
        "status": "PASS" if not issues else "STOP",
        "path": display_path(root, report_path),
        "reason": "; ".join(issues),
    }
    if report_path.is_file():
        deterministic["sha256"] = sha256_file(report_path)
    families = [{
        "name": "subtitle_removal_contract",
        "kind": "deterministic",
        "fingerprint": {
            "report": deterministic.get("sha256"),
            "source": report.get("source_sha256"),
            "output": report.get("output_sha256"),
            "detection": report.get("detection_sha256"),
        },
        "reuse_evidence_valid": False,
        "evidence": [deterministic],
    }]
    detection_path = resolve_path(
        root,
        report.get("detection_report"),
        base=report_path.parent,
    )
    detection = load_json(detection_path) if detection_path and detection_path.is_file() else {}
    if not issues:
        presence_fingerprint = {
            "detection": report.get("detection_sha256"),
            "master": detection.get("finishing_master_sha256"),
            "classification": detection.get("classification"),
            "evidence_frames": [
                {
                    "sha256": frame.get("sha256"),
                    "timestamp_seconds": frame.get("timestamp_seconds"),
                }
                for frame in detection.get("evidence_frames") or []
                if isinstance(frame, dict)
            ],
            "subtitle_intervals": detection.get("subtitle_intervals") or [],
        }
        presence_hash = stable_hash(presence_fingerprint)
        families.append({
            "name": "subtitle_presence_classification",
            "kind": "semantic",
            "fingerprint": presence_fingerprint,
            "fingerprint_hash": presence_hash,
            "reuse_evidence_valid": False,
            "evidence": checker_evidence(
                root,
                job_id,
                stage,
                "subtitle_presence_classification",
                presence_hash,
                artifact,
            ),
            "scope": {
                "job_id": job_id,
                "finishing_master": detection.get("finishing_master"),
                "classification": detection.get("classification"),
                "evidence_frames": detection.get("evidence_frames") or [],
                "subtitle_intervals": detection.get("subtitle_intervals") or [],
                "checks": [
                    "distinguish burned-in captions from valid scene text",
                    "confirm no caption interval was missed across the full timeline",
                ],
            },
        })
    if report.get("action") == "mediakit_pro" and not issues:
        visual_qc_path = resolve_path(
            root,
            report.get("visual_qc_report"),
            base=report_path.parent,
        )
        fingerprint = {
            "source": report.get("source_sha256"),
            "output": report.get("output_sha256"),
            "detection": report.get("detection_sha256"),
            "visual_qc": (
                sha256_file(visual_qc_path)
                if visual_qc_path and visual_qc_path.is_file()
                else None
            ),
        }
        fingerprint_hash = stable_hash(fingerprint)
        families.append({
            "name": "subtitle_repair_quality",
            "kind": "semantic",
            "fingerprint": fingerprint,
            "fingerprint_hash": fingerprint_hash,
            "reuse_evidence_valid": False,
            "evidence": checker_evidence(
                root,
                job_id,
                stage,
                "subtitle_repair_quality",
                fingerprint_hash,
                artifact,
            ),
            "scope": {
                "job_id": job_id,
                "source_video": report.get("source_video"),
                "output_video": report.get("output_video"),
                "subtitle_intervals": (
                    load_json(
                        resolve_path(
                            root,
                            report.get("detection_report"),
                            base=report_path.parent,
                        )
                    )
                    if resolve_path(
                        root,
                        report.get("detection_report"),
                        base=report_path.parent,
                    )
                    else {}
                ).get("subtitle_intervals", []),
            },
        })
    ledger = evaluate_risk_families(
        job_id,
        stage,
        families,
        previous=previous,
    )
    ledger["ledger_path"] = display_path(
        root,
        checks / f"{stage}_qc_risk_ledger.json",
    )
    if write:
        write_json(checks / f"{stage}_qc_risk_ledger.json", ledger)
        request_path = checks / f"{stage}_semantic_review_request.json"
        if ledger["semantic_review_request"].get("required"):
            write_json(request_path, ledger["semantic_review_request"])
        write_json(ledger_state_path(root, job_id), ledger)
    return ledger


def build_finishing_ledger(root, job_id, stage, artifact, previous, write):
    output = root / "output" / job_id
    checks = output / "checks"
    paths = {
        "plan": output / "finishing" / "edit_plan.json",
        "report": output / "final" / "finish_report.json",
        "product_still_guard": output / "final" / "product_still_guard.json",
        "video": output / "final" / "final_video.mp4",
        "director_plan": output / "seedance" / "director_plan.json",
        "source_rhythm": output / "剧情分析" / "source_rhythm.json",
    }
    fingerprint = {
        name: sha256_file(path) if path.is_file() else None
        for name, path in paths.items()
    }
    fingerprint_hash = stable_hash(fingerprint)
    family = {
        "name": "finishing_story_integrity",
        "kind": "semantic",
        "fingerprint": fingerprint,
        "fingerprint_hash": fingerprint_hash,
        "reuse_evidence_valid": False,
        "evidence": checker_evidence(
            root,
            job_id,
            stage,
            "finishing_story_integrity",
            fingerprint_hash,
            artifact,
        ),
        "scope": {
            "job_id": job_id,
            "edit_plan": display_path(root, paths["plan"]),
            "finished_video": display_path(root, paths["video"]),
            "director_plan": display_path(root, paths["director_plan"]),
            "source_rhythm": display_path(root, paths["source_rhythm"]),
            "checks": [
                "required beats retained",
                "spoken lines remain coherent",
                "shot order and hard cuts preserve the approved story",
                "any product-reference still repair changes only the bad visual interval",
            ],
        },
    }
    ledger = evaluate_risk_families(
        job_id,
        stage,
        [family],
        previous=previous,
    )
    ledger["ledger_path"] = display_path(
        root,
        checks / f"{stage}_qc_risk_ledger.json",
    )
    if write:
        write_json(checks / f"{stage}_qc_risk_ledger.json", ledger)
        request_path = checks / f"{stage}_semantic_review_request.json"
        if ledger["semantic_review_request"].get("required"):
            write_json(request_path, ledger["semantic_review_request"])
        write_json(ledger_state_path(root, job_id), ledger)
    return ledger


def storyboard_acceptance_paths(root, job_id, stage):
    checks = root / "output" / job_id / "checks"
    return {
        "report": checks / f"{stage}_storyboard_visual_acceptance.json",
        "request": checks / f"{stage}_semantic_review_request.json",
        "compare": checks / "storyboard_visual_acceptance_compare.jpg",
    }


def image_batch_visual_contract_evidence(root, job, stage, acceptance, report_path):
    preflight = acceptance.get("deterministic_preflight") or {}
    evidence = [{
        "name": "storyboard_visual_acceptance_preflight",
        "status": str(preflight.get("overall") or "STOP").upper(),
        "path": display_path(root, report_path),
        "sha256": sha256_file(report_path) if report_path.is_file() else None,
    }]
    evidence.extend(
        item
        for item in visual_contract_evidence(root, job, stage)
        if item.get("name") == "codex_imagegen_contract"
    )
    return evidence


def active_storyboard_review_request(base_request, requested_families):
    requested_names = {item.get("name") for item in requested_families}
    request = dict(base_request)
    request["families"] = [
        family
        for family in base_request.get("families") or []
        if family.get("name") in requested_names
    ]
    request["required"] = bool(request["families"])
    request["invocation_count"] = 1 if request["families"] else 0
    request.pop("request_id", None)
    request["request_id"] = stable_hash(request)
    return request


def build_image_batch_visual_ledger(root, job, stage, artifact, previous, write):
    started = time.perf_counter()
    job_id = job.get("id", "")
    output = root / "output" / job_id
    paths = storyboard_acceptance_paths(root, job_id, stage)
    prior_acceptance = load_json(paths["report"]) if paths["report"].is_file() else {}
    saved_request = (
        (prior_acceptance.get("semantic_review") or {}).get("request_payload")
        or {}
    )
    state_request = previous.get("semantic_review_request") or {}
    prior_request = (
        state_request
        if state_request.get("request_type") == "storyboard_visual_acceptance"
        else saved_request
    )
    acceptance = build_acceptance(
        root,
        job,
        stage,
        output / "visual-assets" / "approved_visual_manifest.json",
        output / "product_profile.json",
        paths["report"],
        paths["request"],
        paths["compare"],
        mode="active",
        write_request=False,
        prior_request=prior_request,
        write_artifacts=write,
    )
    base_request = (acceptance.get("semantic_review") or {}).get("request_payload") or {}
    contracts = image_batch_visual_contract_evidence(root, job, stage, acceptance, paths["report"])
    deterministic_fingerprint = {
        "acceptance": (acceptance.get("input_binding") or {}).get("fingerprint"),
        "evidence": {
            item.get("name", ""): item.get("subject_fingerprint") or item.get("sha256")
            for item in contracts
        },
    }
    families = [{
        "name": "visual_contracts",
        "kind": "deterministic",
        "fingerprint": deterministic_fingerprint,
        "reuse_evidence_valid": False,
        "evidence": contracts,
    }]
    visible_defects = active_visible_defects(root, job_id)
    for family in acceptance.get("semantic_family_selection") or []:
        family_name = family.get("name", "")
        family_hash = family.get("fingerprint_hash", "")
        prior_family = (previous.get("families") or {}).get(family_name) or {}
        reuse_valid = semantic_family_evidence_current(
            root,
            prior_family.get("evidence") or [],
            family_name,
            family_hash,
        )
        family_evidence = checker_evidence(
            root,
            job_id,
            stage,
            family_name,
            family_hash,
            artifact,
        )
        family_defects = defects_for_family(visible_defects, family_name)
        will_reuse = (
            prior_family.get("status") in PASSING_STATUSES
            and prior_family.get("fingerprint_hash") == family_hash
            and reuse_valid
            and not family_defects
        )
        families.append({
            "name": family_name,
            "kind": "semantic",
            "fingerprint_hash": family_hash,
            "reuse_evidence_valid": reuse_valid,
            "defects": family_defects,
            "evidence": family_evidence,
            "scope": {"job_id": job_id, "asset_group": "approved_storyboards"},
            "wait_seconds": (
                0.0
                if will_reuse
                else max(
                    (float(item.get("wait_seconds") or 0.0) for item in family_evidence),
                    default=0.0,
                )
            ),
        })
    ledger = evaluate_risk_families(job_id, stage, families, previous=previous)
    generated_request = ledger.get("semantic_review_request") or {}
    if base_request:
        ledger["semantic_review_request"] = active_storyboard_review_request(
            base_request,
            generated_request.get("families") or [],
        )
    request = ledger.get("semantic_review_request") or {}
    ledger["metrics"] = {
        "compare_generation_count": int(
            (acceptance.get("metrics") or {}).get("compare_generation_count") or 0
        ),
        "semantic_request_count": 1 if request.get("required") else 0,
        "checker_invocation_count": int(request.get("invocation_count") or 0),
        "requested_family_count": len(request.get("families") or []),
        "reused_family_count": sum(
            1
            for family in (ledger.get("families") or {}).values()
            if family.get("status") == "REUSED_PASS"
        ),
        "active_seconds": max(0.0, time.perf_counter() - started),
        "wait_seconds": max(
            (
                float((family.get("decision_trace") or {}).get("wait_seconds") or 0.0)
                for family in (ledger.get("families") or {}).values()
            ),
            default=0.0,
        ),
    }
    ledger["visual_acceptance"] = {
        "report_path": display_path(root, paths["report"]),
        "compare_path": (acceptance.get("canonical_compare_context") or {}).get("path"),
    }
    ledger["ledger_path"] = display_path(
        root,
        output / "checks" / f"{stage}_qc_risk_ledger.json",
    )
    if write and ledger["semantic_review_request"].get("required"):
        write_json(paths["request"], ledger["semantic_review_request"])
    elif write:
        paths["request"].unlink(missing_ok=True)
    if write:
        write_json(output / "checks" / f"{stage}_qc_risk_ledger.json", ledger)
        write_json(ledger_state_path(root, job_id), ledger)
    return ledger


def build_stage_ledger(root, job, stage, artifact="", write=True):
    started = time.perf_counter()
    root = Path(root).resolve()
    job_id = job.get("id", "")
    checks = root / "output" / job_id / "checks"
    previous = load_previous_ledger(root, job_id)
    if stage == SOURCE_BLUEPRINT_STAGE:
        output = root / "output" / job_id
        source_paths = [
            output / "剧情分析" / "source_rhythm.json",
            output / "剧情分析" / "video_understanding" / "analysis.json",
            output / "剧情分析" / "video_understanding" / "request_manifest.json",
            output / "剧情分析" / "video_understanding" / "raw_response.json",
            output
            / "剧情分析"
            / "video_understanding"
            / "hook_review"
            / "analysis.json",
            output
            / "剧情分析"
            / "video_understanding"
            / "hook_review"
            / "request_manifest.json",
            output
            / "剧情分析"
            / "video_understanding"
            / "hook_review"
            / "raw_response.json",
            output
            / "剧情分析"
            / "video_understanding"
            / "hook_review"
            / "aligned_timeline.json",
            output / "剧情分析" / "剧情分析.md",
            output / "剧情分析" / "画面时间线.md",
            output / "剧情分析" / "字幕层整理.md",
            output / "剧情分析" / "shot_table.md",
            output / "分镜" / "分镜表与缝点审查.md",
            output / "分镜" / "分镜污染审查.md",
            output / "storyboard_source_refs" / "source_storyboard_manifest.json",
        ]
        source_paths.extend(
            sorted(
                path
                for path in (output / "storyboard_source_refs").glob(
                    "source_storyboard_part*.jpg"
                )
                if path.is_file()
            )
        )
        source_fingerprint = file_fingerprint(root, source_paths)
        source_hash = stable_hash(source_fingerprint)
        previous_source = (previous.get("families") or {}).get(
            "source_fidelity"
        ) or {}
        semantic_evidence = checker_evidence(
            root,
            job_id,
            stage,
            "source_fidelity",
            source_hash,
            artifact,
        )
        deterministic_evidence = [
            qc_evidence(
                root,
                "source_blueprint_report",
                [checks / "source_blueprint_report.json"],
            ),
            qc_evidence(
                root,
                "source_rhythm",
                [checks / "source_rhythm_qc.json"],
            ),
            qc_evidence(
                root,
                "source_rhythm_visual_review",
                [checks / "source_rhythm_visual_review_qc.json"],
            ),
        ]
        ledger = evaluate_risk_families(
            job_id,
            stage,
            [
                {
                    "name": "source_fact_contracts",
                    "kind": "deterministic",
                    "fingerprint": {
                        "source_fingerprint": source_fingerprint,
                        "required_evidence": [
                            item["name"] for item in deterministic_evidence
                        ],
                    },
                    "reuse_evidence_valid": False,
                    "evidence": deterministic_evidence,
                },
                {
                    "name": "source_fidelity",
                    "kind": "semantic",
                    "fingerprint_hash": source_hash,
                    "reuse_evidence_valid": (
                        evidence_still_current(
                            root,
                            previous_source.get("evidence") or [],
                        )
                    ),
                    "evidence": semantic_evidence,
                    "scope": {
                        "job_id": job_id,
                        "source_artifacts": "locked_source_blueprint",
                    },
                },
            ],
            previous=previous,
        )
        ledger["ledger_path"] = display_path(
            root,
            checks / f"{stage}_qc_risk_ledger.json",
        )
        request_path = checks / f"{stage}_semantic_review_request.json"
        if write:
            write_json(checks / f"{stage}_qc_risk_ledger.json", ledger)
            write_json(ledger_state_path(root, job_id), ledger)
            if ledger["semantic_review_request"]["required"]:
                write_json(request_path, ledger["semantic_review_request"])
            else:
                request_path.unlink(missing_ok=True)
        return ledger
    if stage == "image_batch_qc":
        return build_image_batch_visual_ledger(
            root,
            job,
            stage,
            artifact,
            previous,
            write,
        )
    if stage == SUBTITLE_REMOVAL_STAGE:
        return build_subtitle_removal_ledger(
            root,
            job_id,
            stage,
            artifact,
            previous,
            write,
        )
    if stage == FINISHING_STAGE:
        return build_finishing_ledger(
            root,
            job_id,
            stage,
            artifact,
            previous,
            write,
        )
    if stage == FINAL_QC_STAGE:
        ledger = evaluate_risk_families(
            job_id,
            stage,
            [final_artifact_family(root, job_id, artifact)],
            previous=previous,
        )
        ledger["ledger_path"] = display_path(root, checks / f"{stage}_qc_risk_ledger.json")
        if write:
            write_json(checks / f"{stage}_qc_risk_ledger.json", ledger)
            write_json(ledger_state_path(root, job_id), ledger)
        return ledger

    visual_blocker = ""
    try:
        visual_fingerprint = current_fingerprint(root, job_id)
    except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
        visual_blocker = str(exc)
        visual_fingerprint = {"version": 1, "job_id": job_id}
    visual_active_seconds = time.perf_counter() - started
    visual_payload = visual_family_payload(visual_fingerprint)
    visual_hash = stable_hash(visual_payload)
    previous_visual = (previous.get("families") or {}).get("visual_integrity") or {}
    previous_contracts = (previous.get("families") or {}).get("visual_contracts") or {}
    previous_pack = (previous.get("families") or {}).get("generation_pack_consistency") or {}

    pack_started = time.perf_counter()
    pack_files = file_fingerprint(root, generation_pack_paths(root, job_id))
    pack_active_seconds = time.perf_counter() - pack_started
    source_started = time.perf_counter()
    source_files = file_fingerprint(
        root,
        source_fidelity_paths(root, job_id) + prompt_subject_paths(root, job_id),
    )
    source_active_seconds = time.perf_counter() - source_started
    source_hash = stable_hash(source_files)
    previous_source = (previous.get("families") or {}).get("source_to_generation_fidelity") or {}

    storyboard_visual_families = downstream_storyboard_visual_families(
        root,
        job,
        previous,
    )
    visual_evidence = []
    if not storyboard_visual_families:
        visual_evidence = checker_evidence(
            root,
            job_id,
            stage,
            "visual_integrity",
            visual_hash,
            artifact,
        )
    source_evidence = checker_evidence(
        root,
        job_id,
        stage,
        "source_to_generation_fidelity",
        source_hash,
        artifact,
    )

    contract_started = time.perf_counter()
    contracts = (
        []
        if storyboard_visual_families
        else visual_contract_evidence(root, job, stage)
    )
    contract_active_seconds = time.perf_counter() - contract_started
    evidence_started = time.perf_counter()
    pack_evidence = generation_pack_evidence(root, job, stage)
    pack_active_seconds += time.perf_counter() - evidence_started
    previous_contract_evidence = previous_contracts.get("evidence") or []
    pack_payload = {
        "files": pack_files,
        "required_evidence": sorted(item.get("name", "") for item in pack_evidence),
    }
    previous_pack_evidence = previous_pack.get("evidence") or []
    families = []
    if storyboard_visual_families:
        families.extend(storyboard_visual_families)
    else:
        families.append({
            "name": "visual_integrity",
            "kind": "semantic",
            "fingerprint": visual_payload,
            "reuse_evidence_valid": evidence_still_current(root, previous_visual.get("evidence") or []),
            "evidence": visual_evidence,
            "defects": active_visible_defects(root, job_id),
            "evaluation_blocker": visual_blocker,
            "scope": {"job_id": job_id, "asset_group": "approved_storyboards"},
            "active_seconds": visual_active_seconds,
            "wait_seconds": sum(item.get("wait_seconds", 0.0) for item in visual_evidence),
        })
    if not storyboard_visual_families:
        families.append({
            "name": "visual_contracts",
            "kind": "deterministic",
            "fingerprint": visual_payload,
            "reuse_evidence_valid": (
                evidence_still_current(root, previous_contract_evidence)
                and evidence_covers(previous_contract_evidence, contracts)
            ),
            "evidence": contracts,
            "active_seconds": contract_active_seconds,
        })
    families.append({
            "name": "generation_pack_consistency",
            "kind": "deterministic",
            "fingerprint": pack_payload,
            "reuse_evidence_valid": (
                evidence_still_current(root, previous_pack_evidence)
                and evidence_covers(previous_pack_evidence, pack_evidence)
            ),
            "evidence": pack_evidence,
            "active_seconds": pack_active_seconds,
        })
    if stage in PROMPT_STAGES:
        families.append({
            "name": "source_to_generation_fidelity",
            "kind": "semantic",
            "fingerprint": source_files,
            "reuse_evidence_valid": evidence_still_current(root, previous_source.get("evidence") or []),
            "evidence": source_evidence,
            "scope": {
                "job_id": job_id,
                "line_edit_audit": line_edit_audit(root, job_id),
            },
            "active_seconds": source_active_seconds,
            "wait_seconds": sum(item.get("wait_seconds", 0.0) for item in source_evidence),
        })
    ledger = evaluate_risk_families(job_id, stage, families, previous=previous)
    ledger["ledger_path"] = display_path(root, checks / f"{stage}_qc_risk_ledger.json")
    if write:
        write_json(checks / f"{stage}_qc_risk_ledger.json", ledger)
        if ledger["semantic_review_request"]["required"]:
            write_json(
                checks / f"{stage}_semantic_review_request.json",
                ledger["semantic_review_request"],
            )
        write_json(ledger_state_path(root, job_id), ledger)
    return ledger


def find_job(root, job_id):
    with (root / "jobs.csv").open(newline="", encoding="utf-8") as handle:
        for job in csv.DictReader(handle):
            if job.get("id", "").strip() == job_id:
                return job
    return None


def main():
    parser = argparse.ArgumentParser(description="Build the stage-level QC Risk Ledger.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--artifact", default="")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    job = find_job(root, args.job_id)
    if job is None:
        parser.error(f"job not found: {args.job_id}")
    ledger = build_stage_ledger(
        root,
        job,
        args.stage,
        artifact=args.artifact,
        write=not args.no_write,
    )
    if args.json:
        print(json.dumps(ledger, ensure_ascii=False, indent=2))
    else:
        print(ledger["overall"])
        print(ledger["ledger_path"])
        request = ledger.get("semantic_review_request") or {}
        if request.get("required"):
            print(display_path(root, root / "output" / args.job_id / "checks" / f"{args.stage}_semantic_review_request.json"))


if __name__ == "__main__":
    main()
