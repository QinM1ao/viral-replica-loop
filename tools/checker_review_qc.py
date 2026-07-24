#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
import time
from pathlib import Path

from qc_outcomes import blocker_category, outcome_for_result, validate_outcome


RESULTS = {"PASS", "FAIL", "STOP"}
RESULT_SEVERITY = {"PASS": 0, "FAIL": 1, "STOP": 2}
REQUIRED_FIELDS = [
    "Gate",
    "Job",
    "Stage",
    "Input artifacts",
    "Checks",
    "Result",
    "Reason",
    "Failed item",
    "Failure type",
    "Retry variable",
    "Locked variables",
    "Next status",
    "Needs user confirmation",
]
OPTIONAL_FIELDS = [
    "Outcome type",
    "Why not fail",
    "Family results",
    "Line edit results",
]

VISUAL_GATE_NAMES = {
    "image_sample_review_gate.md",
    "image_batch_gate.md",
    "seedance_prompt_gate.md",
    "request_gate.md",
}

SOURCE_CONTAMINATION_PATTERNS = [
    r"motion[- ]only",
    r"source rhythm",
    r"rhythm image",
    r"rhythm board",
    r"contact sheet",
    r"sample direction",
    r"constrain(?:ed|s)? .*role table",
    r"role table.*source",
    r"constrain(?:ed|s)? .*source",
    r"ignore .*source",
    r"old product",
    r"old person",
    r"old mud",
    r"source product",
    r"source person",
    r"源片",
    r"源视频",
    r"节奏图",
    r"节奏参考",
    r"旧产品",
    r"旧人物",
    r"旧男主",
    r"源男主",
    r"旧灰泥",
    r"灰泥",
    r"忽略.*旧",
    r"素材角色表.*旧",
    r"素材角色表.*源",
    r"素材角色表.*节奏",
    r"只传.*动作",
    r"只传.*节奏",
    r"禁止传递",
]


def field_re(name):
    return re.compile(rf"^{re.escape(name)}[ \t]*:[ \t]*(.*)$", re.MULTILINE)


def extract_field(text, name):
    match = field_re(name).search(text)
    if not match:
        return None
    return match.group(1).strip()


def normalize_result(value):
    if not value:
        return None
    for result in RESULTS:
        if re.search(rf"\b{result}\b", value.upper()):
            return result
    return None


def is_emptyish(value):
    if value is None:
        return True
    return value.strip().lower() in {"", "none", "n/a", "na", "无", "不适用", "-"}


def is_visual_gate(fields, gate_path):
    gate_name = gate_path.name if gate_path is not None else ""
    gate_field = (fields.get("Gate") or "").strip()
    stage_field = (fields.get("Stage") or "").strip().lower()
    return (
        gate_name in VISUAL_GATE_NAMES
        or any(name in gate_field for name in VISUAL_GATE_NAMES)
        or stage_field in {"image_sample_review", "image_batch_qc", "seedance_prompt", "request_qc"}
    )


def source_contamination_hits(fields):
    haystack = "\n".join(value or "" for value in fields.values())
    hits = []
    for pattern in SOURCE_CONTAMINATION_PATTERNS:
        if re.search(pattern, haystack, flags=re.IGNORECASE):
            hits.append(pattern)
    return hits


def stable_hash(value):
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def resolve_artifact(root, raw):
    if not raw:
        return None
    path = Path(str(raw))
    return path if path.is_absolute() else Path(root).resolve() / path


def current_file_hash(root, raw):
    path = resolve_artifact(root, raw)
    if not path or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review_report(review_path, gate_path=None):
    checks = []
    if not review_path.exists():
        return {
            "overall": "STOP",
            "review_result": None,
            "checks": [{
                "name": "review_file_exists",
                "status": "STOP",
                "detail": f"missing: {review_path}",
            }],
            "fields": {},
        }

    text = review_path.read_text(encoding="utf-8")
    fields = {name: extract_field(text, name) for name in REQUIRED_FIELDS + OPTIONAL_FIELDS}
    missing = [name for name, value in fields.items() if value is None]
    missing = [name for name in missing if name in REQUIRED_FIELDS]
    checks.append({
        "name": "required_fields",
        "status": "PASS" if not missing else "FAIL",
        "detail": f"missing={missing}",
    })

    result = normalize_result(fields.get("Result"))
    checks.append({
        "name": "result_value",
        "status": "PASS" if result in RESULTS else "FAIL",
        "detail": f"result={fields.get('Result')!r}",
    })

    outcome_text = "\n".join(value or "" for value in fields.values())
    outcome = outcome_for_result(result, fields.get("Outcome type"), outcome_text)
    outcome, outcome_checks = validate_outcome(
        result,
        outcome,
        why_not_fail=fields.get("Why not fail"),
        text=outcome_text,
        finding_code=fields.get("Failure type"),
    )
    for name, status, detail in outcome_checks:
        checks.append({
            "name": name,
            "status": status,
            "detail": detail,
        })

    if gate_path is not None:
        checks.append({
            "name": "gate_file_exists",
            "status": "PASS" if gate_path.exists() else "STOP",
            "detail": str(gate_path),
        })

    if result == "FAIL":
        checks.append({
            "name": "fail_has_failure_type",
            "status": "PASS" if not is_emptyish(fields.get("Failure type")) else "FAIL",
            "detail": fields.get("Failure type") or "",
        })
        checks.append({
            "name": "fail_has_retry_variable",
            "status": "PASS" if not is_emptyish(fields.get("Retry variable")) else "FAIL",
            "detail": fields.get("Retry variable") or "",
        })

    if result == "STOP":
        needs_confirmation = (fields.get("Needs user confirmation") or "").strip().lower()
        checks.append({
            "name": "stop_needs_confirmation",
            "status": "PASS" if needs_confirmation in {"yes", "true", "y", "是"} else "FAIL",
            "detail": fields.get("Needs user confirmation") or "",
        })

    if result == "PASS":
        checks.append({
            "name": "pass_has_reason",
            "status": "PASS" if not is_emptyish(fields.get("Reason")) else "FAIL",
            "detail": fields.get("Reason") or "",
        })
        if is_visual_gate(fields, gate_path):
            hits = source_contamination_hits(fields)
            checks.append({
                "name": "visual_pass_no_source_contamination_workaround",
                "status": "PASS" if not hits else "FAIL",
                "detail": f"red_flags={hits}",
            })

    order = {"PASS": 0, "FAIL": 1, "STOP": 2}
    structure_status = max((c["status"] for c in checks), key=lambda s: order[s])
    overall = result if structure_status == "PASS" else "STOP"
    return {
        "overall": overall,
        "review_result": result,
        "outcome_type": outcome,
        "blocker_category": blocker_category(outcome),
        "why_not_fail": fields.get("Why not fail"),
        "structure_status": structure_status,
        "checks": checks,
        "fields": fields,
    }


def bind_risk_request(report, request_path, root=None):
    root = Path(root or ".").resolve()
    try:
        request_bytes = request_path.read_bytes()
        request = json.loads(request_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        report["checks"].append({
            "name": "qc_risk_request_binding",
            "status": "STOP",
            "detail": f"invalid risk request: {exc}",
        })
        report["overall"] = "STOP"
        report["structure_status"] = "STOP"
        return report

    family_fingerprints = {
        str(item.get("name") or ""): str(item.get("fingerprint_hash") or "")
        for item in request.get("families") or []
        if str(item.get("name") or "") and str(item.get("fingerprint_hash") or "")
    }
    requested_line_edits = {
        str(edit.get("id") or ""): edit
        for family in request.get("families") or []
        if str(family.get("name") or "") == "source_to_generation_fidelity"
        for edit in (family.get("scope") or {}).get("line_edit_audit") or []
        if isinstance(edit, dict) and str(edit.get("id") or "")
    }
    fields = report.get("fields") or {}
    unified_visual_request = request.get("request_type") == "storyboard_visual_acceptance"
    request_id_valid = True
    context_valid = True
    if unified_visual_request:
        unsigned_request = {key: value for key, value in request.items() if key != "request_id"}
        request_id_valid = request.get("request_id") == stable_hash(unsigned_request)
        context = request.get("canonical_compare_context")
        context_valid = isinstance(context, dict)
        if context_valid:
            context_valid = (
                context.get("role") == "overview"
                and current_file_hash(root, context.get("path")) == context.get("sha256")
                and isinstance(context.get("source_artifacts"), list)
                and bool(context.get("source_artifacts"))
                and all(
                    isinstance(item, dict)
                    and current_file_hash(root, item.get("path")) == item.get("sha256")
                    for item in context.get("source_artifacts")
                )
            )
        report["checks"].append({
            "name": "storyboard_visual_request_integrity",
            "status": "PASS" if request_id_valid else "STOP",
            "detail": f"request_id={request.get('request_id')!r}",
        })
        report["checks"].append({
            "name": "storyboard_visual_context_binding",
            "status": "PASS" if context_valid else "STOP",
            "detail": f"compare={(context or {}).get('path') if isinstance(context, dict) else None!r}",
        })

    valid = (
        request.get("required") is True
        and request.get("invocation_count") == 1
        and bool(family_fingerprints)
        and str(request.get("job_id") or "") == str(fields.get("Job") or "")
        and str(request.get("stage") or "") == str(fields.get("Stage") or "")
        and request_id_valid
        and context_valid
    )
    report["checks"].append({
        "name": "qc_risk_request_binding",
        "status": "PASS" if valid else "STOP",
        "detail": f"job={request.get('job_id')!r}, stage={request.get('stage')!r}, families={sorted(family_fingerprints)}",
    })
    if not valid:
        report["overall"] = "STOP"
        report["structure_status"] = "STOP"
        return report

    family_results = {}
    review_result = str(report.get("overall") or "STOP").upper()
    raw_family_results = fields.get("Family results")
    if raw_family_results:
        try:
            parsed = json.loads(raw_family_results)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            family_results = {
                str(name): str(status).upper()
                for name, status in parsed.items()
            }
    family_results_valid = (
        set(family_results) == set(family_fingerprints)
        and all(status in RESULTS for status in family_results.values())
    )
    top_level_valid = True
    if unified_visual_request:
        if family_results:
            worst_family_result = max(family_results.values(), key=lambda item: RESULT_SEVERITY.get(item, 3))
            top_level_valid = worst_family_result == review_result
        else:
            top_level_valid = False
        report["checks"].append({
            "name": "qc_risk_family_results",
            "status": "PASS" if family_results_valid else "STOP",
            "detail": f"requested={sorted(family_fingerprints)}, returned={sorted(family_results)}",
        })
        report["checks"].append({
            "name": "qc_risk_top_level_result",
            "status": "PASS" if top_level_valid else "STOP",
            "detail": f"top={review_result}, families={family_results}",
        })
        if not family_results_valid or not top_level_valid:
            report["overall"] = "STOP"
            report["structure_status"] = "STOP"
            return report
    elif review_result == "PASS":
        family_results = {name: "PASS" for name in family_fingerprints}
    elif len(family_fingerprints) == 1 and not family_results:
        family_results = {next(iter(family_fingerprints)): review_result}
    elif set(family_results) != set(family_fingerprints):
        report["checks"].append({
            "name": "qc_risk_family_results",
            "status": "STOP",
            "detail": "mixed batched checker results must name every requested family",
        })
        report["overall"] = "STOP"
        report["structure_status"] = "STOP"
        return report

    line_edit_results = {}
    if requested_line_edits:
        raw_line_edit_results = fields.get("Line edit results")
        if raw_line_edit_results:
            try:
                parsed = json.loads(raw_line_edit_results)
            except json.JSONDecodeError:
                parsed = {}
            if isinstance(parsed, dict):
                line_edit_results = parsed
        exact_coverage = set(line_edit_results) == set(requested_line_edits)
        structured_results = exact_coverage and all(
            isinstance(value, dict)
            and str(value.get("result") or "").upper() in RESULTS
            and isinstance(value.get("necessary"), bool)
            and isinstance(value.get("minimal"), bool)
            and value.get("evidence_checked") is True
            and bool(str(value.get("note") or "").strip())
            for value in line_edit_results.values()
        )
        source_result = family_results.get("source_to_generation_fidelity")
        returned_statuses = {
            str(value.get("result") or "").upper()
            for value in line_edit_results.values()
            if isinstance(value, dict)
        }
        result_consistent = (
            source_result == "PASS"
            and returned_statuses == {"PASS"}
            and all(
                value.get("necessary") is True and value.get("minimal") is True
                for value in line_edit_results.values()
                if isinstance(value, dict)
            )
        ) or (
            source_result in {"FAIL", "STOP"}
            and source_result in returned_statuses
        )
        line_edit_results_valid = structured_results and result_consistent
        report["checks"].append({
            "name": "line_edit_results",
            "status": "PASS" if line_edit_results_valid else "STOP",
            "detail": (
                f"requested={sorted(requested_line_edits)}, "
                f"returned={sorted(line_edit_results)}, "
                f"source_result={source_result}"
            ),
        })
        if not line_edit_results_valid:
            report["overall"] = "STOP"
            report["structure_status"] = "STOP"
            return report

    report["qc_risk_review"] = {
        "request_path": str(request_path),
        "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
        "family_fingerprints": family_fingerprints,
        "family_results": family_results,
        "request_id": request.get("request_id"),
        "active_input_fingerprint": request.get("active_input_fingerprint"),
        "canonical_compare_context": request.get("canonical_compare_context"),
        "line_edit_results": line_edit_results,
        "invocation_count": 1,
        "wait_seconds": max(0.0, time.time() - request_path.stat().st_mtime),
    }
    return report


def write_md(path, report):
    lines = [
        "# Checker Review QC",
        "",
        f"- Overall: **{report['overall']}**",
        f"- Review result: `{report.get('review_result')}`",
        f"- Outcome type: `{report.get('outcome_type')}`",
        f"- Blocker category: `{report.get('blocker_category')}`",
        f"- Structure status: `{report.get('structure_status')}`",
        "",
        "## Checks",
        "",
    ]
    for check in report["checks"]:
        lines.append(f"- {check['status']}: `{check['name']}` - {check['detail']}")
    lines.extend(["", "## Fields", "", "```json", json.dumps(report["fields"], ensure_ascii=False, indent=2), "```", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def write_bound_report_json(report, out_json, root=None):
    root = Path(root or ".").resolve()
    out_json = Path(out_json)
    review = report.get("qc_risk_review") or {}
    request_id = str(review.get("request_id") or "").strip()
    archive_path = None
    if request_id:
        archive_path = (
            out_json.parent
            / "checker-review-bindings"
            / f"{request_id}.json"
        )
        try:
            review["immutable_report_path"] = str(archive_path.resolve().relative_to(root))
        except ValueError:
            review["immutable_report_path"] = str(archive_path.resolve())
        report["qc_risk_review"] = review
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(payload, encoding="utf-8")
    if archive_path is not None:
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        archive_path.write_text(payload, encoding="utf-8")
    return archive_path


def main():
    parser = argparse.ArgumentParser(description="Validate a viral-replica checker review artifact.")
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--gate", type=Path)
    parser.add_argument("--risk-request", type=Path)
    parser.add_argument("--root", default=".")
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    args = parser.parse_args()

    report = review_report(args.review, args.gate)
    if args.risk_request:
        report = bind_risk_request(report, args.risk_request, args.root)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    write_bound_report_json(report, args.out_json, args.root)
    write_md(args.out_md, report)
    print(report["overall"])


if __name__ == "__main__":
    main()
