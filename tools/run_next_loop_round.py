#!/usr/bin/env python3
import argparse
import csv
import datetime as dt
import fcntl
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from evidence_ledger import select_job_id
from finish_video import PlanError as FinishingPlanError
from finish_video import probe as probe_finished_media
from finish_video import validate_plan as validate_finishing_plan
from hash_gated_visual_qc import record_snapshot
from qc_risk_ledger import build_stage_ledger, ledger_failure_message
from qc_outcomes import (
    OUTCOME_COST_GATE,
    OUTCOME_EVIDENCE_STOP,
    OUTCOME_HARD_FAILURE,
    OUTCOME_HUMAN_REVIEW,
    OUTCOME_PROVIDER_FAILURE,
    OUTCOME_VISUAL_WARNING,
    blocker_category,
    normalize_outcome,
    outcome_for_result,
    validate_outcome,
)
from caption_finishing_qc import (
    caption_report_issues,
    caption_request_issues,
    captions_requested,
    report_path_for as caption_report_path_for,
    request_path_for as caption_request_path_for,
)
from subtitle_workflow_qc import removal_issues


DEFAULT_RETRY_LIMIT = 2
GATE_RESULTS = {"PASS", "FAIL", "STOP"}
GATE_OUTCOMES = {
    "PASS",
    "HARD_FAILURE",
    "VISUAL_WARNING",
    "EVIDENCE_STOP",
    "PROVIDER_FAILURE",
    "COST_GATE",
    "HUMAN_REVIEW",
}
APPROVAL_SCOPES = {"current_job", "batch", "all", "named_jobs", "targeted_retry"}
GENERATION_INTENTS = {
    "current_job",
    "batch",
    "failed_part_retry",
    "quality_retake",
    "final_video_retry",
}
CHECKER_AGENT_FILE = ".codex/agents/viral-replica-checker.toml"
CHECKER_WORKER_FILE = "workers/checker_worker.md"
CHECKER_REVIEW_SCRIPT = "tools/checker_review_qc.py"
VISUAL_QC_STAGES = {
    "image_sample",
    "image_sample_review",
    "image_batch_qc",
    "seedance_prompt",
    "request_qc",
    "pre_seedance_pack",
}
QC_RISK_LEDGER_STAGES = VISUAL_QC_STAGES | {"finishing", "subtitle_removal", "final_qc"}
PRE_SEEDANCE_HANDOFF = "Pre-Seedance Handoff"
FINAL_VIDEO_DELIVERY = "Final Video"
NO_USER_DELIVERY = "none (internal runner decision)"
VISUAL_QC_GATES = {
    "image_sample_review_gate.md",
    "image_batch_gate.md",
    "seedance_prompt_gate.md",
    "request_gate.md",
    "pre_seedance_pack_gate.md",
}
USER_VISIBLE_STAGES = (
    {
        "index": 1,
        "label": "看懂原片",
        "summary": "拆清楚原视频剧情、口播、镜头节奏和污染风险。",
        "canonical": {"asset_gate", "source_blueprint", "story_analysis", "storyboard"},
        "statuses": {"pending", "story_analyzed"},
        "next_stages": {"source_blueprint", "story_analysis", "storyboard"},
    },
    {
        "index": 2,
        "label": "改好分镜",
        "summary": "一次性改完所有 Part 分镜，替换人物和产品，并去掉旧字幕/旧画面污染。",
        "canonical": {"image_sample", "image_sample_review", "image_batch_qc", "afterwash_reference_review"},
        "statuses": {
            "storyboard_passed",
            "sample_image_waiting_review",
            "image_sample_approved",
            "afterwash_ref_waiting_review",
            "afterwash_ref_passed",
        },
        "next_stages": {
            "image_sample",
            "image_sample_review",
            "image_batch_qc",
            "sample_image_waiting_review",
            "afterwash_reference_review",
        },
    },
    {
        "index": 3,
        "label": "写视频脚本",
        "summary": "写口播、缝点、Seedance 提示词和请求素材，并完成音频边界检查。",
        "canonical": {"voiceover", "seam", "seedance_prompt", "audio_boundary_qc", "request_qc", "pre_seedance_pack"},
        "statuses": {
            "image_qc_passed",
            "part2_storyboard_loop_passed",
            "voiceover_done",
            "seam_done",
            "seedance_prompt_done",
            "audio_boundary_qc_done",
        },
        "next_stages": {"voiceover", "seam", "seedance_prompt", "audio_boundary_qc", "request_qc", "pre_seedance_pack"},
    },
    {
        "index": 4,
        "label": "生成视频",
        "summary": "确认付费范围，提交或等待 Seedance，并下载各 Part 视频。",
        "canonical": {"cost_gate", "generation_approval", "generation"},
        "statuses": {"seedance_inputs_prepared", "generation_approved"},
        "status_prefixes": {"seedance_inputs_prepared", "seedance_generating"},
        "next_stages": {"generation_approval", "generation"},
    },
    {
        "index": 5,
        "label": "质检交付",
        "summary": "按明确剪辑计划收尾成片，跑技术 QC，交付最终视频或明确失败原因。",
        "canonical": {"finishing", "subtitle_removal", "final_qc", "caption_finishing", "terminal"},
        "statuses": {"finishing", "subtitle_removal", "final_qc", "caption_finishing", "done", "blocked"},
        "status_prefixes": {"finishing", "subtitle_removal", "final_qc", "caption_finishing"},
        "next_stages": {"finishing", "subtitle_removal", "final_qc", "caption_finishing", "done", "blocked"},
    },
)
DEFAULT_USER_VISIBLE_STAGE = USER_VISIBLE_STAGES[0]


def now_iso():
    return dt.datetime.now().isoformat(timespec="seconds")


def parse_bool(value):
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def user_visible_stage(canonical_stage="", status="", next_stage=""):
    canonical_stage = str(canonical_stage or "").strip()
    status = str(status or "").strip()
    next_stage = str(next_stage or "").strip()

    if canonical_stage in {"confirmation_gate", "retry_limit_gate", "self_audit_review", "unknown"}:
        canonical_stage = ""

    for stage in USER_VISIBLE_STAGES:
        if (
            canonical_stage in stage["canonical"]
            or status in stage["statuses"]
            or any(status.startswith(prefix) for prefix in stage.get("status_prefixes", ()))
            or next_stage in stage["next_stages"]
        ):
            return stage
    return DEFAULT_USER_VISIBLE_STAGE


def user_visible_stage_text(stage):
    return f"{stage['index']}/5 {stage['label']}"


def normalize_stop_at(values):
    out = set()
    for value in values or []:
        for item in str(value).replace(",", " ").split():
            item = item.strip()
            if item:
                out.add(item)
    return out


def load_stage_rules(root):
    candidates = [
        root / "rules" / "STAGE_RULES.json",
        root / "stages" / "STAGE_RULES.json",
    ]
    path = next((candidate for candidate in candidates if candidate.exists()), candidates[0])
    with path.open(encoding="utf-8") as f:
        config = json.load(f)

    if not isinstance(config.get("rules"), list):
        raise ValueError(f"{path} must contain a `rules` list")

    return config, path


def default_cost_policy():
    return {
        "version": 1,
        "cost_classes": {
            "free_check": {"auto_allowed": True},
            "cheap_quality_work": {"auto_allowed": True, "counter": "gpt_image_runs"},
            "conditional_paid_repair": {
                "auto_allowed": True,
                "requires_detection_evidence": True,
                "max_tasks_per_job": 1,
                "requires_new_approval_for_retry": True,
            },
            "expensive_generation": {
                "auto_allowed": False,
                "counter": "seedance_runs",
                "requires_allow_paid": True,
                "requires_approval_record": True,
            },
        },
        "budgets": {
            "gpt_image_runs_per_job": {"soft": 8, "hard": 12},
            "seedance_runs_without_approval": {"hard": 0},
            "seedance_runs_per_approval": {"hard": 1},
            "seedance_targeted_retries_per_failed_output": {"hard": 1},
            "same_failure_type": {"hard": DEFAULT_RETRY_LIMIT},
        },
        "routes": {
            "cost_stop_worker": "workers/cost_approval_worker.md",
            "cost_stop_gate": "gates/cost_approval_gate.md",
        },
    }


def extract_first_json_block(text):
    marker = "```json"
    start = text.find(marker)
    if start == -1:
        return None
    start += len(marker)
    end = text.find("```", start)
    if end == -1:
        return None
    return text[start:end].strip()


def load_cost_policy(root):
    path = root / "COST_POLICY.md"
    if not path.exists():
        return default_cost_policy(), path

    block = extract_first_json_block(path.read_text(encoding="utf-8"))
    if not block:
        raise ValueError(f"{path} must contain a fenced json machine policy block")

    policy = json.loads(block)
    default = default_cost_policy()
    default.update(policy)
    default.setdefault("cost_classes", {}).update(policy.get("cost_classes", {}))
    default.setdefault("budgets", {}).update(policy.get("budgets", {}))
    default.setdefault("routes", {}).update(policy.get("routes", {}))
    return default, path


def terminal_statuses(stage_config):
    return set(stage_config.get("terminal_statuses", ["done", "blocked"]))


def default_runner_state():
    return {
        "version": 1,
        "retry_limit": DEFAULT_RETRY_LIMIT,
        "updated_at": None,
        "jobs": {},
    }


def default_job_state(last_artifact=""):
    return {
        "current_failure_type": None,
        "failure_count": 0,
        "retry_count": 0,
        "consecutive_no_progress": 0,
        "last_gate_result": None,
        "last_outcome_type": None,
        "last_blocker_category": None,
        "last_why_not_fail": None,
        "last_gate": None,
        "last_stage": None,
        "last_artifact": last_artifact,
        "last_effective_progress_at": None,
        "last_no_progress_at": None,
        "last_stop_at": None,
        "active_stage_attempt": None,
        "spent": {
            "gpt_image_runs": 0,
            "seedance_runs": 0,
            "mediakit_subtitle_removal_runs": 0,
            "seedance_targeted_retries": 0,
            "final_video_seedance_retries": 0,
        },
        "cost_approval": {
            "scope": None,
            "approved_task_count": 0,
            "submitted_task_count": 0,
            "generation_intent": None,
            "approval_source": None,
            "approved_at": None,
        },
        "gate_history": [],
    }


def load_runner_state(root):
    path = root / "RUNNER_STATE.json"
    if not path.exists():
        return default_runner_state(), path

    with path.open(encoding="utf-8") as f:
        state = json.load(f)

    if not isinstance(state.get("jobs"), dict):
        raise ValueError(f"{path} must contain a `jobs` object")

    state.setdefault("version", 1)
    state.setdefault("retry_limit", DEFAULT_RETRY_LIMIT)
    state.setdefault("updated_at", None)
    return state, path


def ensure_job_state(state, job):
    job_id = job.get("id", "")
    jobs = state.setdefault("jobs", {})
    if job_id not in jobs:
        jobs[job_id] = default_job_state(job.get("last_artifact", ""))
    else:
        base = default_job_state(job.get("last_artifact", ""))
        base.update(jobs[job_id])
        base.setdefault("spent", {}).setdefault("gpt_image_runs", 0)
        base.setdefault("spent", {}).setdefault("seedance_runs", 0)
        base.setdefault("spent", {}).setdefault("mediakit_subtitle_removal_runs", 0)
        base.setdefault("spent", {}).setdefault("seedance_targeted_retries", 0)
        base.setdefault("spent", {}).setdefault("final_video_seedance_retries", 0)
        approval = base.setdefault("cost_approval", {})
        approval.setdefault("scope", None)
        approval.setdefault("approved_task_count", 0)
        approval.setdefault("submitted_task_count", 0)
        approval.setdefault("generation_intent", None)
        approval.setdefault("approval_source", None)
        approval.setdefault("approved_at", None)
        base.setdefault("gate_history", [])
        jobs[job_id] = base
    return jobs[job_id]


def write_runner_state(path, state):
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def start_stage_attempt(job_state, job, decision, timestamp=None):
    if decision.get("decision") != "continue":
        return None
    stage = str(decision.get("canonical_stage") or "").strip()
    if not stage:
        return None
    current = job_state.get("active_stage_attempt") or {}
    if current.get("stage") == stage:
        return current
    timestamp = timestamp or now_iso()
    attempt = {
        "run_id": f"{job.get('id', '')}:{stage}:{timestamp}",
        "stage": stage,
        "started_at": timestamp,
    }
    job_state["active_stage_attempt"] = attempt
    return attempt


def finish_stage_attempt(job_state, stage, timestamp):
    attempt = job_state.get("active_stage_attempt") or {}
    if attempt.get("stage") != stage:
        return {}
    started_at = attempt.get("started_at")
    try:
        duration_seconds = max(
            0.0,
            (dt.datetime.fromisoformat(timestamp) - dt.datetime.fromisoformat(started_at)).total_seconds(),
        )
    except (TypeError, ValueError):
        duration_seconds = None
    job_state["active_stage_attempt"] = None
    return {
        "stage_run_id": attempt.get("run_id"),
        "started_at": started_at,
        "finished_at": timestamp,
        "duration_seconds": duration_seconds,
    }


def append_event_log(root, event):
    logs_dir = root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / "loop_events.jsonl"
    event = dict(event)
    event.setdefault("time", now_iso())
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def read_jobs(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_jobs_table(path):
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader), list(reader.fieldnames or [])


def write_jobs_table(path, jobs, fieldnames):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(jobs)


def select_job(jobs, terminal, job_id=""):
    if job_id:
        for row in jobs:
            if row.get("id", "").strip() == job_id:
                return row
        return None
    for row in jobs:
        if row.get("status", "").strip() not in terminal:
            return row
    return None


def resolve_path(root, raw):
    if not raw:
        return None
    path = Path(raw)
    if path.is_absolute():
        return path
    if raw.startswith(root.name + "/"):
        return root.parent / path
    return root / path


def path_status(root, raw):
    path = resolve_path(root, raw)
    if path is None:
        return "missing: empty"
    return "ok" if path.exists() else f"missing: {path}"


def required_asset_checks(root, job):
    checks = []
    missing = []
    for key in ("video_path", "product_assets", "person_assets"):
        raw = job.get(key, "").strip()
        if key == "person_assets" and raw == "storyboard_derived":
            status = "storyboard_derived"
        else:
            status = path_status(root, raw)
        ok = status in {"ok", "storyboard_derived"}
        checks.append((key, ok, status))
        if not ok:
            missing.append((key, status))

    audio = job.get("audio_assets", "").strip()
    if audio and audio != "extract_from_original":
        status = path_status(root, audio)
        ok = status == "ok"
        checks.append(("audio_assets", ok, status))
        if not ok:
            missing.append(("audio_assets", status))

    return checks, missing


def last_artifact_check(root, job):
    raw = job.get("last_artifact", "").strip()
    if not raw and job.get("status", "").strip() == "pending":
        return True, "not required for pending job"
    status = path_status(root, raw)
    return status == "ok", status


def add_gate_check(root, checks, gate):
    if not gate or gate == "none":
        return
    gate_status = path_status(root, gate)
    checks.append(("gate_contract", gate_status == "ok", gate_status))


def add_worker_check(root, checks, worker_file):
    if not worker_file or worker_file == "none":
        return
    worker_status = path_status(root, worker_file)
    checks.append(("worker_contract", worker_status == "ok", worker_status))


def add_script_check(root, checks, script_file):
    if not script_file or script_file == "none":
        return
    script_status = path_status(root, script_file)
    checks.append(("script_file", script_status == "ok", script_status))


def add_checker_checks(root, checks, checker_agent=CHECKER_AGENT_FILE):
    add_worker_check(root, checks, CHECKER_WORKER_FILE)
    add_script_check(root, checks, CHECKER_REVIEW_SCRIPT)
    add_script_check(root, checks, "tools/qc_risk_ledger.py")
    agent_status = path_status(root, checker_agent)
    checks.append(("checker_agent", agent_status == "ok", agent_status))


def add_cost_checks(root, checks, cost_policy):
    path = root / "COST_POLICY.md"
    checks.append(("COST_POLICY.md", path.exists(), str(path)))
    checks.append(("cost_policy_machine_block", bool(cost_policy), "loaded"))


def contains_any(value, markers):
    return any(marker in value for marker in markers)


def rule_matches(rule, status):
    match = rule.get("match", {})
    match_type = match.get("type", "exact")
    target = match.get("status", "")

    if match_type == "exact":
        return status == target
    if match_type == "prefix":
        return status.startswith(target)
    if match_type == "contains":
        return target in status

    raise ValueError(f"Unknown match type `{match_type}` in rule `{rule.get('id', '')}`")


def find_rule(stage_config, status):
    for rule in stage_config.get("rules", []):
        if rule_matches(rule, status):
            return rule
    return None


def stop_at_matches(rule, status, next_stage, stop_at):
    if not stop_at:
        return False
    values = {
        status,
        rule.get("id", "") if rule else "",
        rule.get("canonical_stage", "") if rule else "",
    }
    return bool(values.intersection(stop_at))


def same_or_value(value, fallback):
    return fallback if value == "same" else value


def retry_limit_reached(job_state, retry_limit):
    failure_type = job_state.get("current_failure_type")
    failure_count = int(job_state.get("failure_count", 0) or 0)
    no_progress = int(job_state.get("consecutive_no_progress", 0) or 0)

    if failure_type and failure_count >= retry_limit:
        return f"same failure repeated {failure_count} times: {failure_type}"
    if no_progress >= retry_limit:
        return f"no effective progress for {no_progress} consecutive rounds"
    return None


def spent_count(job_state, counter):
    spent = job_state.get("spent", {})
    return int(spent.get(counter, 0) or 0)


def infer_required_seedance_tasks(root, job):
    job_id = job.get("id", "")
    output_dir = root / "output" / job_id
    request_dir = output_dir / "seedance" / "requests"
    request_files = []
    if request_dir.exists():
        request_files = sorted(request_dir.glob("part*_request_prepared.json"))
    if request_files:
        return len(request_files), [str(path) for path in request_files]

    prompt_dir = output_dir / "seedance_web_final" / "prompts"
    prompt_files = []
    if prompt_dir.exists():
        prompt_files = sorted(prompt_dir.glob("Part*_Seedance提示词.txt"))
    if prompt_files:
        return len(prompt_files), [str(path) for path in prompt_files]

    return 1, []


def approval_recorded_from_context(approval_context):
    return bool(approval_context and approval_context.get("approval_recorded"))


def mediakit_retry_approved(approval_context, allow_paid):
    return bool(
        allow_paid
        and approval_context
        and approval_context.get("mediakit_subtitle_retry_approved")
        and approval_context.get("approval_recorded")
        and approval_context.get("approval_scope") == "targeted_retry"
    )


def approval_context_for(root, job, job_state, cost_policy, args):
    planned_count, request_files = infer_required_seedance_tasks(root, job)
    cli_planned = int(getattr(args, "planned_task_count", 0) or 0)
    if cli_planned > 0:
        planned_count = cli_planned

    source_message = str(getattr(args, "approval_source_message", "") or "").strip()
    approval_recorded = bool(getattr(args, "approval_recorded", False))
    approval_policy = cost_policy.get("approval", {})
    direct_phrases = approval_policy.get("direct_generation_phrases", [])
    direct_message = bool(
        source_message
        and any(phrase.lower() in source_message.lower() for phrase in direct_phrases)
    )
    if direct_message and approval_policy.get("direct_generation_request_is_approval", True):
        approval_recorded = True

    raw_scope = str(getattr(args, "approval_scope", "") or "").strip()
    if not raw_scope and approval_recorded:
        raw_scope = approval_policy.get("default_approval_scope", "current_explicit_job")
    scope_aliases = {
        "current_explicit_job": "current_job",
        "current-job": "current_job",
        "current": "current_job",
        "named": "named_jobs",
        "named-job": "named_jobs",
        "named-jobs": "named_jobs",
        "retry": "targeted_retry",
        "targeted-retry": "targeted_retry",
    }
    approval_scope = scope_aliases.get(raw_scope, raw_scope) if raw_scope else None

    generation_intent = str(getattr(args, "generation_intent", "") or "current_job").strip()
    approval_task_count = int(getattr(args, "approval_task_count", 0) or 0)
    if approval_task_count <= 0 and approval_recorded:
        if approval_scope == "current_job" and approval_policy.get("current_job_approval_covers_required_parts_once", True):
            approval_task_count = planned_count
        elif approval_scope in {"batch", "all", "named_jobs", "targeted_retry"}:
            approval_task_count = planned_count

    stored_approval = job_state.get("cost_approval", {}) or {}
    submitted_count = int(stored_approval.get("submitted_task_count", 0) or 0)
    stored_approved_count = int(stored_approval.get("approved_task_count", 0) or 0)
    if not approval_recorded and stored_approved_count > submitted_count:
        approval_recorded = True
        approval_scope = stored_approval.get("scope")
        approval_task_count = stored_approved_count
        generation_intent = stored_approval.get("generation_intent") or generation_intent
        source_message = stored_approval.get("approval_source") or source_message

    return {
        "approval_recorded": approval_recorded,
        "approval_scope": approval_scope,
        "approval_task_count": approval_task_count,
        "planned_task_count": planned_count,
        "submitted_task_count": submitted_count,
        "stored_approved_task_count": stored_approved_count,
        "generation_intent": generation_intent,
        "approval_source": source_message or ("direct_generation_request" if direct_message else None),
        "mediakit_subtitle_retry_approved": bool(
            getattr(args, "approve_mediakit_subtitle_retry", False)
        ),
        "request_files": request_files,
    }


def cost_state_for(job_state, cost_policy, cost_class, approval_context=None):
    budgets = cost_policy.get("budgets", {})
    gpt_budget = budgets.get("gpt_image_runs_per_job", {})
    seedance_budget = budgets.get("seedance_runs_per_approval", {})
    approval_context = approval_context or {}
    return {
        "cost_class": cost_class,
        "gpt_image_runs": spent_count(job_state, "gpt_image_runs"),
        "gpt_image_soft_limit": int(gpt_budget.get("soft", 12) or 12),
        "gpt_image_hard_limit": int(gpt_budget.get("hard", 20) or 20),
        "seedance_runs": spent_count(job_state, "seedance_runs"),
        "mediakit_subtitle_removal_runs": spent_count(
            job_state, "mediakit_subtitle_removal_runs"
        ),
        "seedance_targeted_retries": spent_count(job_state, "seedance_targeted_retries"),
        "final_video_seedance_retries": spent_count(job_state, "final_video_seedance_retries"),
        "seedance_per_approval_limit": int(seedance_budget.get("hard", 1) or 1),
        "approval_scope": approval_context.get("approval_scope"),
        "approved_task_count": int(approval_context.get("approval_task_count", 0) or 0),
        "planned_task_count": int(approval_context.get("planned_task_count", 0) or 0),
        "submitted_task_count": int(approval_context.get("submitted_task_count", 0) or 0),
        "generation_intent": approval_context.get("generation_intent"),
    }


def cost_policy_violation(approval_context, job_state, cost_policy):
    approval = cost_policy.get("approval", {})
    budgets = cost_policy.get("budgets", {})
    scope = approval_context.get("approval_scope")
    intent = approval_context.get("generation_intent") or "current_job"
    planned = int(approval_context.get("planned_task_count", 0) or 0)
    approved = int(approval_context.get("approval_task_count", 0) or 0)

    if intent not in GENERATION_INTENTS:
        return f"unknown generation intent `{intent}`"
    if scope and scope not in APPROVAL_SCOPES:
        return f"unknown approval scope `{scope}`"

    if not approval_recorded_from_context(approval_context):
        return "expensive generation requires explicit approval record"

    if intent == "batch" and scope not in {"batch", "all", "named_jobs"}:
        return "batch generation requires explicit batch/all/named-jobs approval"

    if scope == "current_job" and intent == "batch":
        return "current-job approval does not approve batch jobs"

    if intent in {"failed_part_retry", "quality_retake"} and approval.get(
        (
            "quality_retake_requires_new_approval"
            if intent == "quality_retake"
            else "failed_part_retry_requires_new_approval"
        ),
        True,
    ):
        if scope != "targeted_retry":
            if intent == "failed_part_retry":
                return "failed-Part retry requires new targeted approval"
            return "quality_retake requires new targeted approval"
        if intent == "quality_retake" and (planned != 1 or approved != 1):
            return "quality_retake approval must bind exactly one Part and one task"

    if intent == "final_video_retry":
        if scope != "targeted_retry":
            return "final-video regeneration retry requires new targeted approval"
        retry_limit = int(budgets.get("seedance_targeted_retries_per_failed_output", {}).get("hard", 1) or 1)
        used = spent_count(job_state, "final_video_seedance_retries")
        if used >= retry_limit:
            return f"second paid retry blocked: final-video Seedance retries {used} / {retry_limit}"

    if planned <= 0:
        return "planned Seedance task count is unclear"

    if approved < planned:
        return f"approved task count {approved} is below planned task count {planned}"

    if intent == "current_job":
        per_approval_limit = int(budgets.get("seedance_runs_per_approval", {}).get("hard", 1) or 1)
        if per_approval_limit > 0 and approved > planned * per_approval_limit:
            return f"approved task count {approved} exceeds current-job once-per-part limit {planned * per_approval_limit}"

    return None


def cost_stop_reason(
    status,
    next_stage,
    rule,
    job_state,
    cost_policy,
    paid_markers,
    allow_paid,
    approval_context,
    recording_zero_spend_pass=False,
):
    cost_class = rule.get("cost_class", "free_check") if rule else "free_check"
    state = cost_state_for(job_state, cost_policy, cost_class, approval_context)

    if (
        cost_class == "cheap_quality_work"
        and state["gpt_image_runs"] >= state["gpt_image_hard_limit"]
        and not recording_zero_spend_pass
    ):
        return (
            f"Image generation hard budget reached: {state['gpt_image_runs']} / {state['gpt_image_hard_limit']}",
            state,
        )

    if cost_class == "conditional_paid_repair":
        class_policy = cost_policy.get("cost_classes", {}).get(cost_class, {})
        limit = int(class_policy.get("max_tasks_per_job", 1) or 1)
        used = state["mediakit_subtitle_removal_runs"]
        if used >= limit and not mediakit_retry_approved(approval_context, allow_paid):
            return (
                f"automatic MediaKit subtitle-removal limit reached: {used} / {limit}; "
                "a retry requires a new explicit user decision",
                state,
            )

    has_paid_marker = contains_any(status, paid_markers) or contains_any(next_stage, paid_markers)
    is_expensive = cost_class == "expensive_generation" or has_paid_marker
    if not is_expensive:
        return None, state

    class_policy = cost_policy.get("cost_classes", {}).get("expensive_generation", {})
    if class_policy.get("requires_allow_paid", True) and not allow_paid:
        return "expensive generation requires --allow-paid", state
    if class_policy.get("requires_approval_record", True):
        violation = cost_policy_violation(approval_context, job_state, cost_policy)
        if violation:
            return violation, state
    return None, state


def requires_visual_qc(decision):
    stage = decision.get("canonical_stage", "")
    gate_name = Path(decision.get("gate", "")).name
    return stage in VISUAL_QC_STAGES or gate_name in VISUAL_QC_GATES


def requires_qc_risk_ledger(decision):
    return decision.get("canonical_stage", "") in QC_RISK_LEDGER_STAGES


def load_qc_overall(path):
    if path is None or not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    overall = data.get("overall")
    return str(overall).strip().upper() if overall is not None else None


def load_qc_data(path):
    if path is None or not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def first_passing_qc(paths):
    seen = []
    for path in paths:
        if path is None:
            continue
        if path in seen:
            continue
        seen.append(path)
        if load_qc_overall(path) == "PASS":
            return path
    return None


def qc_status_summary(root, paths):
    parts = []
    for path in paths:
        if path is None:
            continue
        overall = load_qc_overall(path)
        status = overall or "missing"
        parts.append(f"{path.relative_to(root) if path.is_relative_to(root) else path}: {status}")
    return "; ".join(parts) or "no candidate paths"


def checker_qc_for_artifact(root, artifact):
    artifact_path = resolve_path(root, artifact) if artifact else None
    if artifact_path is None or artifact_path.suffix.lower() != ".md":
        return {}
    return load_qc_data(artifact_path.with_name(artifact_path.stem + "_qc.json"))


def candidate_source_rhythm_qc_paths(root, job):
    checks_dir = root / "output" / job.get("id", "") / "checks"
    return [checks_dir / "source_rhythm_qc.json"]


def candidate_source_rhythm_visual_review_qc_paths(root, job):
    checks_dir = root / "output" / job.get("id", "") / "checks"
    return [checks_dir / "source_rhythm_visual_review_qc.json"]


def source_video_understanding_issues(root, job):
    output_dir = root / "output" / job.get("id", "")
    analysis_path = output_dir / "剧情分析" / "video_understanding" / "analysis.json"
    manifest_path = output_dir / "剧情分析" / "video_understanding" / "request_manifest.json"
    config_path = root / "rules" / "VIDEO_UNDERSTANDING_MODEL.json"
    issues = []
    for label, path in [
        ("project model config", config_path),
        ("video understanding analysis", analysis_path),
        ("video understanding request manifest", manifest_path),
    ]:
        if not path.is_file():
            issues.append(f"missing {label}: {path}")
    if issues:
        return issues
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"invalid video understanding JSON: {exc}"]

    if analysis.get("status") != "PASS":
        issues.append("video understanding status is not PASS")
    for key in ("provider", "model"):
        if analysis.get(key) != config.get(key):
            issues.append(f"video understanding {key} does not match project config")
        if manifest.get(key) != config.get(key):
            issues.append(f"video understanding manifest {key} does not match project config")
    if manifest.get("http_status") != 200:
        issues.append("video understanding request did not return HTTP 200")
    expected_endpoint = config.get("base_url", "").rstrip("/") + "/" + config.get("endpoint", "").lstrip("/")
    if analysis.get("endpoint") != expected_endpoint:
        issues.append("video understanding analysis endpoint does not match project config")
    if manifest.get("endpoint") != expected_endpoint:
        issues.append("video understanding manifest endpoint does not match project config")
    if manifest.get("fps") != config.get("fps"):
        issues.append("video understanding fps does not match project config")
    if not isinstance(analysis.get("analysis"), dict):
        issues.append("video understanding result has no analysis object")
    else:
        model_analysis = analysis["analysis"]
        if not str(model_analysis.get("summary") or "").strip():
            issues.append("video understanding analysis is missing summary")
        if not isinstance(model_analysis.get("timeline"), list):
            issues.append("video understanding analysis is missing timeline array")

    source_path = Path(job.get("video_path", "")).expanduser()
    if not source_path.is_absolute():
        source_path = root / source_path
    if not source_path.is_file():
        issues.append(f"source video missing for understanding hash check: {source_path}")
    else:
        digest = hashlib.sha256()
        with source_path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        if analysis.get("source_sha256") != digest.hexdigest():
            issues.append("video understanding source hash does not match current source video")
    return issues


def source_storyboard_rhythm_issues(root, job):
    output_dir = root / "output" / job.get("id", "")
    rhythm_path = output_dir / "剧情分析" / "source_rhythm.json"
    manifest_path = (
        output_dir / "storyboard_source_refs" / "source_storyboard_manifest.json"
    )
    issues = []
    if not rhythm_path.is_file():
        issues.append(f"missing source rhythm: {rhythm_path}")
    if not manifest_path.is_file():
        issues.append(f"missing storyboard manifest: {manifest_path}")
    if issues:
        return issues
    try:
        rhythm = json.loads(rhythm_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"invalid rhythm/storyboard JSON: {exc}"]
    if manifest.get("selection_mode") != "source_rhythm":
        issues.append(
            f"selection_mode={manifest.get('selection_mode')!r}, expected 'source_rhythm'"
        )
    selected = []
    for part in manifest.get("parts") or []:
        selected.extend(part.get("selected_frames") or [])
    required_beats = [
        beat
        for beat in rhythm.get("beats") or []
        if beat.get("replication_priority") in {"must_keep", "mergeable"}
    ]
    for beat in required_beats:
        beat_id = str(beat.get("id") or "")
        matches = [
            frame
            for frame in selected
            if beat_id and beat_id in (frame.get("source_beat_ids") or [])
        ]
        if len(matches) != 1:
            issues.append(f"beat {beat_id or '<missing-id>'} selected {len(matches)} times")
            continue
        if beat.get("action_peak_times") and matches[0].get("selection_reason") != "action_peak":
            issues.append(f"beat {beat_id} did not select an action peak")
    return issues


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def selected_generation_outputs(root, job):
    generation_dir = (root / "output" / job.get("id", "") / "generation").resolve()
    manifest_path = generation_dir / "selected_outputs.json"
    issues = []
    if not manifest_path.is_file():
        return [], [f"missing selected generation outputs: {manifest_path}"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], [f"invalid selected generation outputs: {exc}"]
    if manifest.get("schema_version") != 1:
        issues.append("selected generation outputs schema_version must be 1")
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        return [], issues + ["selected generation outputs must contain at least one Part"]

    bindings = []
    part_ids = set()
    paths = set()
    for index, item in enumerate(outputs, start=1):
        prefix = f"selected generation output {index}"
        if not isinstance(item, dict):
            issues.append(f"{prefix} must be an object")
            continue
        part_id = str(item.get("part_id") or "").strip()
        if not part_id or part_id in part_ids:
            issues.append(f"{prefix} has missing or duplicate part_id")
        part_ids.add(part_id)
        path = resolve_path(root, item.get("path", ""))
        if path in paths:
            issues.append(f"{prefix} duplicates a selected path")
        paths.add(path)
        try:
            path.relative_to(generation_dir)
        except ValueError:
            issues.append(f"{prefix} is outside the current generation directory")
        if not path.is_file():
            issues.append(f"{prefix} file is missing: {path}")
        elif item.get("sha256") != file_sha256(path):
            issues.append(f"{prefix} hash does not match the current Part")
        try:
            duration = float(item.get("duration_seconds"))
        except (TypeError, ValueError):
            duration = 0.0
        if duration <= 0:
            issues.append(f"{prefix} duration_seconds must be positive")
        bindings.append({"part_id": part_id, "path": path, "sha256": item.get("sha256")})
    return bindings, issues


def active_product_reference_bindings(root, job):
    job_id = str(job.get("id") or "")
    manifest_path = (
        root
        / "output"
        / job_id
        / "visual-assets"
        / "approved_visual_manifest.json"
    )
    if not manifest_path.is_file():
        return [], []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], [f"invalid approved visual manifest for product still guard: {exc}"]
    reusable_refs = manifest.get("reusable_refs")
    if not isinstance(reusable_refs, dict):
        return [], []
    bindings = []
    issues = []
    seen = set()
    for role, value in reusable_refs.items():
        if not str(role).startswith("product_"):
            continue
        path = resolve_path(root, value)
        if path in seen:
            continue
        seen.add(path)
        if not path.is_file():
            issues.append(f"product still guard reference is missing: {path}")
            continue
        bindings.append(
            {
                "role": str(role),
                "path": path,
                "sha256": file_sha256(path),
            }
        )
    return bindings, issues


def product_still_guard_evidence_issues(
    root,
    job,
    plan_path,
    validated_plan,
    finish_report,
    output_path,
):
    expected, issues = active_product_reference_bindings(root, job)
    if not expected:
        return issues
    expected_by_path = {
        item["path"].resolve(): item["sha256"]
        for item in expected
    }
    config = validated_plan.get("product_still_guard")
    if not isinstance(config, dict):
        issues.append(
            "product still guard is required when approved product references exist"
        )
    else:
        configured_paths = {
            Path(path).resolve()
            for path in config.get("references") or []
        }
        if configured_paths != set(expected_by_path):
            issues.append(
                "product still guard references do not match the approved product references"
            )

    binding = finish_report.get("product_still_guard")
    if not isinstance(binding, dict):
        issues.append("finishing report is missing product still guard evidence")
        return issues
    guard_path = output_path.parent / "product_still_guard.json"
    if Path(str(binding.get("report") or "")).resolve() != guard_path.resolve():
        issues.append("product still guard report path does not match the active final output")
        return issues
    if not guard_path.is_file():
        issues.append(f"product still guard report is missing: {guard_path}")
        return issues
    if binding.get("report_sha256") != file_sha256(guard_path):
        issues.append("product still guard report hash is stale")
    try:
        guard = json.loads(guard_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        issues.append(f"invalid product still guard report: {exc}")
        return issues
    if guard.get("overall") != "PASS":
        issues.append("product still guard report overall is not PASS")
    if guard.get("status") not in {"clean", "repaired"}:
        issues.append("product still guard status must be clean or repaired")
    if guard.get("paid_tasks_submitted") != 0:
        issues.append("product still guard must remain local and free")
    if guard.get("audio_preserved") is not True:
        issues.append("product still guard did not preserve the original audio")
    if guard.get("audio_packet_sha256_before") != guard.get(
        "audio_packet_sha256_after"
    ):
        issues.append("product still guard audio packet hashes do not match")
    if Path(str(guard.get("output_video") or "")).resolve() != output_path.resolve():
        issues.append("product still guard points to a different final video")
    elif guard.get("output_sha256") != file_sha256(output_path):
        issues.append("product still guard output hash does not match the final video")
    reported_refs = {}
    for item in guard.get("references") or []:
        if isinstance(item, dict):
            reported_refs[Path(str(item.get("path") or "")).resolve()] = item.get(
                "sha256"
            )
    if reported_refs != expected_by_path:
        issues.append(
            "product still guard report is not bound to the approved product references"
        )
    verification = guard.get("verification") or {}
    if verification.get("suspicious_intervals"):
        issues.append("product still guard verification still contains a bad interval")
    if guard.get("status") == "repaired" and not guard.get("repairs"):
        issues.append("product still guard says repaired but records no edit")
    if binding.get("status") != guard.get("status"):
        issues.append("finishing report product still guard status is stale")
    if binding.get("audio_preserved") is not True:
        issues.append("finishing report does not confirm product still guard audio preservation")
    return issues


def finishing_evidence_issues(root, job):
    output_dir = root / "output" / job.get("id", "")
    plan_path = (output_dir / "finishing" / "edit_plan.json").resolve()
    report_path = output_dir / "final" / "finish_report.json"
    output_path = (output_dir / "final" / "final_video.mp4").resolve()
    issues = []
    if not plan_path.is_file():
        issues.append(f"missing finishing plan: {plan_path}")
    if not report_path.is_file():
        issues.append(f"missing finishing report: {report_path}")
    if not output_path.is_file():
        issues.append(f"missing final video: {output_path}")
    if issues:
        return issues
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"invalid finishing plan/report: {exc}"]
    try:
        validated_plan = validate_finishing_plan(plan_path)
        output_media = probe_finished_media(output_path)
    except FinishingPlanError as exc:
        return [f"invalid finishing plan/media: {exc}"]
    tolerance = max(0.15, 2 / max(output_media.get("fps") or 1, 1))
    if abs(output_media["duration"] - validated_plan["expected_duration"]) > tolerance:
        issues.append("finishing output duration does not match the validated edit plan")
    try:
        reported_expected = float(report.get("expected_duration"))
        reported_actual = float(report.get("actual_duration"))
    except (TypeError, ValueError):
        reported_expected = reported_actual = -1.0
    if abs(reported_expected - validated_plan["expected_duration"]) > 0.01:
        issues.append("finishing report expected_duration does not match the edit plan")
    if abs(reported_actual - output_media["duration"]) > tolerance:
        issues.append("finishing report actual_duration does not match the final video")
    if not shutil.which("ffmpeg"):
        issues.append("ffmpeg is missing for finishing decode verification")
    else:
        decoded = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(output_path), "-f", "null", "-"],
            text=True,
            capture_output=True,
        )
        if decoded.returncode != 0:
            issues.append(f"finishing output decode failed: {decoded.stderr.strip()}")
    if report.get("overall") != "PASS":
        issues.append("finishing report overall is not PASS")
    if report.get("executor") != "local_ffmpeg":
        issues.append("finishing executor is not local_ffmpeg")
    if report.get("paid_tasks_submitted") != 0:
        issues.append("finishing report records paid task submission")
    if report.get("caption_free") is not True:
        issues.append("finishing report must confirm a caption-free master")
    if "subtitles" in plan:
        issues.append("finishing plan must remain caption-free")
    if Path(str(report.get("plan") or "")).resolve() != plan_path:
        issues.append("finishing report points to a different edit plan")
    elif report.get("plan_sha256") != file_sha256(plan_path):
        issues.append("finishing plan hash does not match the current edit plan")
    if Path(str(report.get("output") or "")).resolve() != output_path:
        issues.append("finishing report points to a different final video")
    elif report.get("output_sha256") != file_sha256(output_path):
        issues.append("finishing output hash does not match the current final video")
    report_inputs = report.get("inputs") or {}
    if not isinstance(report_inputs, dict):
        issues.append("finishing report inputs must be an ID-keyed object")
        report_inputs = {}
    for input_id, input_report in report_inputs.items():
        if not isinstance(input_report, dict):
            issues.append(f"finishing input {input_id} evidence must be an object")
            continue
        input_path = Path(str(input_report.get("path") or "")).resolve()
        if not input_path.is_file():
            issues.append(f"finishing input {input_id} is missing: {input_path}")
        elif input_report.get("sha256") != file_sha256(input_path):
            issues.append(f"finishing input {input_id} hash does not match the current Part")
    if not report_inputs:
        issues.append("finishing report has no input evidence")
    if report.get("timeline") != validated_plan["timeline"]:
        issues.append("finishing report timeline does not match the validated edit plan")
    selected, selected_issues = selected_generation_outputs(root, job)
    issues.extend(selected_issues)
    if not selected_issues:
        selected_bindings = {
            item["part_id"]: (item["path"], item["sha256"])
            for item in selected
        }
        plan_bindings = {
            input_id: (Path(input_report["path"]).resolve(), input_report["sha256"])
            for input_id, input_report in validated_plan["input_reports"].items()
        }
        report_bindings = {
            input_id: (
                Path(str(input_report.get("path") or "")).resolve(),
                input_report.get("sha256"),
            )
            for input_id, input_report in report_inputs.items()
            if isinstance(input_report, dict)
        }
        if not (
            plan_bindings == report_bindings == selected_bindings
        ):
            issues.append(
                "finishing plan inputs, report inputs, and "
                "generation/selected_outputs.json must match exactly"
            )
    issues.extend(
        product_still_guard_evidence_issues(
            root,
            job,
            plan_path,
            validated_plan,
            report,
            output_path,
        )
    )
    return issues


def final_qc_active_output_issues(root, job, artifact=""):
    output_dir = root / "output" / job.get("id", "")
    removal_path = output_dir / "subtitle_removal" / "subtitle_removal_report.json"
    configured = False
    stage_rules_path = root / "rules" / "STAGE_RULES.json"
    if stage_rules_path.is_file():
        try:
            stage_rules = json.loads(stage_rules_path.read_text(encoding="utf-8"))
            configured = any(
                item.get("canonical_stage") == "subtitle_removal"
                for item in stage_rules.get("rules") or []
            )
        except (OSError, json.JSONDecodeError):
            configured = True
    if not configured and not removal_path.is_file():
        return []
    issues = removal_issues(removal_path)
    if issues:
        return [f"subtitle removal evidence: {issue}" for issue in issues]
    removal = json.loads(removal_path.read_text(encoding="utf-8"))
    active_path = Path(str(removal.get("output_video") or "")).resolve()
    active_hash = str(removal.get("output_sha256") or "")

    artifact_path = resolve_path(root, artifact) if artifact else None
    candidates = []
    if artifact_path and artifact_path.suffix.lower() == ".md":
        candidates.append(artifact_path.with_suffix(".json"))
    candidates.extend([
        output_dir / "final_qc" / "final_qc.json",
        output_dir / "final" / "final_qc.json",
    ])
    final_qc_path = next((path for path in candidates if path.is_file()), candidates[0])
    if not final_qc_path.is_file():
        return [f"missing final QC report: {final_qc_path}"]
    try:
        final_qc = json.loads(final_qc_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"invalid final QC report: {exc}"]
    videos = final_qc.get("videos") or []
    if len(videos) != 1:
        return ["final QC must contain exactly one active final video"]
    checked = videos[0]
    checked_path = resolve_path(root, checked.get("path", ""))
    if checked_path != active_path:
        issues.append(
            "final QC video is not the active subtitle-removal output: "
            f"expected {active_path}, got {checked_path}"
        )
    if checked.get("sha256") != active_hash:
        issues.append("final QC hash does not match the active subtitle-removal output")
    return issues


def existing_mediakit_attempt_reason(root, job, retry_approved=False):
    output_dir = root / "output" / job.get("id", "")
    attempt_path = output_dir / "subtitle_removal" / "paid_attempt.json"
    if not attempt_path.is_file():
        return None
    report_path = output_dir / "subtitle_removal" / "subtitle_removal_report.json"
    if not removal_issues(report_path):
        return (
            "a MediaKit subtitle-removal attempt is already recorded and its result "
            "must proceed only through checker/gate recording; another submission is blocked"
        )
    if retry_approved:
        return None
    return (
        "a MediaKit subtitle-removal attempt is already recorded but has no passing "
        "bound result; automatic retry is blocked"
    )


def apply_optional_caption_transition(root, job, decision):
    """Redirect final_qc only when a valid explicit caption request exists."""
    if decision.get("canonical_stage") != "final_qc":
        return decision
    if not captions_requested(root, job):
        return decision
    redirected = dict(decision)
    redirected["next_expected"] = "caption_finishing"
    redirected["action"] = (
        "Run final technical QC, then add source-faithful captions as the last "
        "post-production step because the user explicitly requested captions."
    )
    return redirected


def preflight_pass_recording(root, job, decision, args):
    if args.record_gate_result.upper() != "PASS":
        return

    if decision.get("canonical_stage", "") == "finishing":
        issues = finishing_evidence_issues(root, job)
        if issues:
            raise ValueError("refusing to record PASS: finishing evidence is stale or invalid. " + "; ".join(issues))

    source_stage = decision.get("canonical_stage", "")
    is_supplemental_approval = (
        bool(getattr(args, "approval_recorded", False))
        and bool(getattr(args, "approval_scope", ""))
        and int(getattr(args, "spent_seedance_runs", 0) or 0) == 0
    )
    if source_stage == "generation" and not is_supplemental_approval:
        _, issues = selected_generation_outputs(root, job)
        if issues:
            raise ValueError(
                "refusing to record PASS: selected generation outputs are stale or invalid. "
                + "; ".join(issues)
            )

    if source_stage == "subtitle_removal":
        report_path = (
            root
            / "output"
            / job.get("id", "")
            / "subtitle_removal"
            / "subtitle_removal_report.json"
        )
        issues = removal_issues(report_path)
        if issues:
            raise ValueError(
                "refusing to record PASS: subtitle removal evidence is stale or invalid. "
                + "; ".join(issues)
            )

    if source_stage == "final_qc":
        request_path = caption_request_path_for(root, job)
        request_issues = caption_request_issues(root, job, required=request_path.is_file())
        if request_issues:
            raise ValueError(
                "refusing to record PASS: final caption request is invalid. "
                + "; ".join(request_issues)
            )
        issues = final_qc_active_output_issues(
            root,
            job,
            getattr(args, "artifact", ""),
        )
        if issues:
            raise ValueError(
                "refusing to record PASS: final QC is not bound to the active subtitle-removal output. "
                + "; ".join(issues)
            )

    if source_stage == "caption_finishing":
        issues = caption_report_issues(root, job)
        if issues:
            raise ValueError(
                "refusing to record PASS: final caption evidence is stale or invalid. "
                + "; ".join(issues)
            )

    if source_stage == "story_analysis":
        understanding_issues = source_video_understanding_issues(root, job)
        if understanding_issues:
            raise ValueError(
                "refusing to record PASS: Seed 2.0 Mini video understanding evidence is missing or invalid. "
                + "; ".join(understanding_issues)
            )

    if source_stage == "source_blueprint":
        rhythm_paths = candidate_source_rhythm_qc_paths(root, job)
        if first_passing_qc(rhythm_paths) is None:
            raise ValueError(
                "refusing to record PASS: missing passing source rhythm QC. "
                "Run tools/source_rhythm_qc.py after authoring source_rhythm.json. "
                f"Candidates: {qc_status_summary(root, rhythm_paths)}"
            )
        visual_review_paths = candidate_source_rhythm_visual_review_qc_paths(root, job)
        if first_passing_qc(visual_review_paths) is None:
            raise ValueError(
                "refusing to record PASS: missing passing source rhythm visual review QC. "
                "The independent checker must review every required beat against its cited frames with "
                "tools/source_rhythm_visual_review_qc.py. "
                f"Candidates: {qc_status_summary(root, visual_review_paths)}"
            )
        understanding_issues = source_video_understanding_issues(root, job)
        if understanding_issues:
            raise ValueError(
                "refusing to record PASS: Seed 2.0 Mini video understanding evidence is missing or invalid. "
                + "; ".join(understanding_issues)
            )
        storyboard_issues = source_storyboard_rhythm_issues(root, job)
        if storyboard_issues:
            raise ValueError(
                "refusing to record PASS: storyboard is not locked to source rhythm. "
                + "; ".join(storyboard_issues)
            )

    if not requires_qc_risk_ledger(decision):
        return

    artifact = getattr(args, "artifact", "").strip() or job.get("last_artifact", "")
    ledger = build_stage_ledger(
        root,
        job,
        decision.get("canonical_stage", ""),
        artifact=artifact,
        write=not getattr(args, "dry_run", False),
    )
    if ledger.get("overall") != "PASS":
        raise ValueError(
            "refusing to record PASS: QC Risk Ledger did not pass. "
            + ledger_failure_message(ledger)
            + f" Ledger: {ledger.get('ledger_path', '')}"
        )


def preflight_cost_policy_recording(root, job, decision, args, cost_policy, job_state):
    gate_name = Path(decision.get("gate", "")).name
    is_cost_gate = gate_name == "cost_approval_gate.md" or decision.get("canonical_stage") == "generation_approval"
    retry_context = {
        "approval_recorded": bool(args.approval_recorded),
        "approval_scope": args.approval_scope,
        "mediakit_subtitle_retry_approved": bool(
            getattr(args, "approve_mediakit_subtitle_retry", False)
        ),
    }
    retry_approved = mediakit_retry_approved(retry_context, args.allow_paid)
    if getattr(args, "approve_mediakit_subtitle_retry", False) and not retry_approved:
        raise ValueError(
            "MediaKit subtitle retry requires --allow-paid, --approval-recorded, "
            "and --approval-scope targeted_retry"
        )
    if retry_approved and decision.get("canonical_stage") != "subtitle_removal":
        raise ValueError("MediaKit subtitle retry approval is only valid at subtitle_removal")
    is_supplemental_approval = bool(
        args.approval_recorded
        and args.approval_scope
        and not getattr(args, "approve_mediakit_subtitle_retry", False)
    )
    if args.record_gate_result.upper() == "PASS" and (is_cost_gate or is_supplemental_approval):
        approval_context = approval_context_for(root, job, job_state, cost_policy, args)
        if not args.allow_paid:
            raise ValueError("refusing to record cost approval PASS: --allow-paid is required")
        violation = cost_policy_violation(approval_context, job_state, cost_policy)
        if violation:
            raise ValueError(f"refusing to record cost approval PASS: {violation}")

    mediakit_runs = int(
        getattr(args, "spent_mediakit_subtitle_removal_runs", 0) or 0
    )
    if mediakit_runs > 0:
        if decision.get("canonical_stage") != "subtitle_removal":
            raise ValueError(
                "refusing to record MediaKit subtitle-removal spend outside subtitle_removal"
            )
        if mediakit_runs != 1:
            raise ValueError(
                "refusing to record MediaKit subtitle-removal spend: exactly one task is allowed"
            )
        used = spent_count(job_state, "mediakit_subtitle_removal_runs")
        if used >= 1 and not retry_approved:
            raise ValueError(
                "refusing to record a second automatic MediaKit subtitle-removal task"
            )

    if args.spent_seedance_runs <= 0:
        return

    if not args.allow_paid:
        raise ValueError("refusing to record Seedance spend: --allow-paid is required")

    approval = job_state.get("cost_approval", {}) or {}
    approved = int(approval.get("approved_task_count", 0) or 0)
    submitted = int(approval.get("submitted_task_count", 0) or 0)
    if approved <= 0:
        raise ValueError("refusing to record Seedance spend: no active cost approval exists")
    if submitted + args.spent_seedance_runs > approved:
        raise ValueError(
            "refusing to record Seedance spend: submitted task count would exceed approval "
            f"({submitted} + {args.spent_seedance_runs} > {approved})"
        )

    intent = args.generation_intent or approval.get("generation_intent") or "current_job"
    if intent == "final_video_retry":
        budgets = cost_policy.get("budgets", {})
        retry_limit = int(budgets.get("seedance_targeted_retries_per_failed_output", {}).get("hard", 1) or 1)
        used = spent_count(job_state, "final_video_seedance_retries")
        if used >= retry_limit:
            raise ValueError(
                f"refusing to record Seedance spend: second paid retry blocked "
                f"({used} / {retry_limit} final-video retries already used)"
            )


def record_gate_result(state, job, decision, args, root, cost_policy):
    gate_result = args.record_gate_result.upper()
    if gate_result not in GATE_RESULTS:
        raise ValueError(f"gate result must be one of {sorted(GATE_RESULTS)}")

    timestamp = now_iso()
    job_state = ensure_job_state(state, job)
    spent = job_state.setdefault("spent", {})
    spent["gpt_image_runs"] = int(spent.get("gpt_image_runs", 0) or 0) + args.spent_gpt_image_runs
    spent["seedance_runs"] = int(spent.get("seedance_runs", 0) or 0) + args.spent_seedance_runs
    spent["mediakit_subtitle_removal_runs"] = int(
        spent.get("mediakit_subtitle_removal_runs", 0) or 0
    ) + int(getattr(args, "spent_mediakit_subtitle_removal_runs", 0) or 0)
    spent["seedance_targeted_retries"] = int(spent.get("seedance_targeted_retries", 0) or 0)
    spent["final_video_seedance_retries"] = int(spent.get("final_video_seedance_retries", 0) or 0)
    if args.spent_seedance_runs > 0 and args.generation_intent in {
        "failed_part_retry",
        "quality_retake",
        "final_video_retry",
    }:
        spent["seedance_targeted_retries"] += 1
    if args.spent_seedance_runs > 0 and args.generation_intent == "final_video_retry":
        spent["final_video_seedance_retries"] += 1

    retry_variable = args.retry_variable.strip() or None
    artifact = args.artifact.strip() or job.get("last_artifact", "")
    artifact_qc = checker_qc_for_artifact(root, artifact)
    artifact_fields = (
        artifact_qc.get("fields")
        if isinstance(artifact_qc.get("fields"), dict)
        else {}
    )
    inherited_failure_type = artifact_fields.get("Failure type")
    failure_type = (
        args.failure_type.strip()
        or str(inherited_failure_type or "").strip()
        or None
    )
    inherited_outcome = artifact_qc.get("outcome_type")
    inherited_why_not_fail = artifact_qc.get("why_not_fail")
    why_not_fail = args.why_not_fail.strip() or inherited_why_not_fail or None
    outcome_context = "\n".join(
        value
        for value in [
            gate_result,
            args.outcome_type or inherited_outcome,
            failure_type,
            retry_variable,
            why_not_fail,
            artifact,
            args.note.strip(),
        ]
        if value
    )
    outcome_type = outcome_for_result(gate_result, args.outcome_type or inherited_outcome, outcome_context)
    outcome_type, outcome_checks = validate_outcome(
        gate_result,
        outcome_type,
        why_not_fail=why_not_fail,
        text=outcome_context,
        finding_code=failure_type,
    )
    failed_outcome_checks = [name for name, status, _ in outcome_checks if status != "PASS"]
    if failed_outcome_checks:
        details = "; ".join(f"{name}: {detail}" for name, status, detail in outcome_checks if status != "PASS")
        raise ValueError(f"invalid QC outcome: {details}")
    category = blocker_category(outcome_type)

    if gate_result == "PASS":
        job_state["current_failure_type"] = None
        job_state["failure_count"] = 0
        job_state["consecutive_no_progress"] = 0
        job_state["last_effective_progress_at"] = timestamp
    elif gate_result == "FAIL":
        if failure_type is None:
            failure_type = "unspecified_failure"
        if job_state.get("current_failure_type") == failure_type:
            job_state["failure_count"] = int(job_state.get("failure_count", 0) or 0) + 1
        else:
            job_state["current_failure_type"] = failure_type
            job_state["failure_count"] = 1
        job_state["retry_count"] = int(job_state.get("retry_count", 0) or 0) + 1
        job_state["consecutive_no_progress"] = int(job_state.get("consecutive_no_progress", 0) or 0) + 1
        job_state["last_no_progress_at"] = timestamp
    else:
        job_state["last_stop_at"] = timestamp

    job_state["last_gate_result"] = gate_result
    job_state["last_outcome_type"] = outcome_type
    job_state["last_blocker_category"] = category
    job_state["last_why_not_fail"] = why_not_fail
    job_state["last_gate"] = decision.get("gate", "none")
    job_state["last_stage"] = decision.get("canonical_stage", "")
    job_state["last_artifact"] = artifact

    gate_name = Path(decision.get("gate", "")).name
    approval_context = approval_context_for(root, job, job_state, cost_policy, args)
    is_approval_record = (
        gate_name == "cost_approval_gate.md"
        or decision.get("canonical_stage") == "generation_approval"
        or bool(
            getattr(args, "approval_recorded", False)
            and getattr(args, "approval_scope", None)
            and not getattr(args, "approve_mediakit_subtitle_retry", False)
        )
    )
    if gate_result == "PASS" and is_approval_record:
        job_state["cost_approval"] = {
            "scope": approval_context.get("approval_scope"),
            "approved_task_count": int(approval_context.get("approval_task_count", 0) or 0),
            "submitted_task_count": 0,
            "generation_intent": approval_context.get("generation_intent"),
            "approval_source": approval_context.get("approval_source"),
            "approved_at": timestamp,
        }
    elif args.spent_seedance_runs > 0:
        approval = job_state.setdefault("cost_approval", {})
        approval["submitted_task_count"] = int(approval.get("submitted_task_count", 0) or 0) + args.spent_seedance_runs

    timing = finish_stage_attempt(job_state, decision.get("canonical_stage", ""), timestamp)
    event = {
        "time": timestamp,
        "job": job.get("id", ""),
        "workflow_run_id": job.get("workflow_run_id", ""),
        "status": job.get("status", ""),
        "stage": decision.get("canonical_stage", ""),
        "gate": decision.get("gate", "none"),
        "result": gate_result,
        "outcome_type": outcome_type,
        "blocker_category": category,
        "why_not_fail": why_not_fail,
        "failure_type": failure_type,
        "retry_variable": retry_variable,
        "artifact": artifact,
        "note": args.note.strip() or None,
        "approval_scope": approval_context.get("approval_scope"),
        "approved_task_count": approval_context.get("approval_task_count"),
        "submitted_task_count": job_state.get("cost_approval", {}).get("submitted_task_count", 0),
        "seedance_runs": spent.get("seedance_runs", 0),
        "mediakit_subtitle_removal_runs": spent.get(
            "mediakit_subtitle_removal_runs", 0
        ),
        **timing,
    }
    history = job_state.setdefault("gate_history", [])
    history.append(event)
    del history[:-50]

    state["updated_at"] = timestamp
    return job_state, event


def transition_for_gate_result(job, decision, gate_event, stage_config):
    result = gate_event["result"]
    current_status = job.get("status", "")
    current_next_stage = job.get("next_stage", "")
    artifact = gate_event.get("artifact") or job.get("last_artifact", "")

    if result == "PASS":
        new_status = same_or_value(decision.get("next_expected", current_status), current_status)
        next_rule = find_rule(stage_config, new_status)
        new_next_stage = next_rule.get("next_expected", new_status) if next_rule else new_status
        is_visual_warning = gate_event.get("outcome_type") == OUTCOME_VISUAL_WARNING
        is_delivery_status = new_status == "done" or new_status.startswith("seedance_inputs_prepared")
        needs_confirmation = (
            "true"
            if next_rule and next_rule.get("decision") == "stop" and not is_visual_warning and not is_delivery_status
            else "false"
        )
        action = "advance"
        reason = "gate passed"
    elif result == "FAIL":
        new_status = current_status
        new_next_stage = current_next_stage
        needs_confirmation = job.get("needs_user_confirmation", "false")
        action = "stay"
        category = gate_event.get("blocker_category") or "visual_failure"
        reason = f"gate failed ({category}): {gate_event.get('failure_type') or 'unspecified_failure'}"
    else:
        new_status = current_status
        new_next_stage = current_next_stage
        needs_confirmation = "true"
        action = "stop"
        category = gate_event.get("blocker_category") or "human_review"
        reason = f"gate stopped ({category})"

    return {
        "job": job.get("id", ""),
        "action": action,
        "reason": reason,
        "from_status": current_status,
        "to_status": new_status,
        "from_next_stage": current_next_stage,
        "to_next_stage": new_next_stage,
        "last_artifact": artifact,
        "needs_user_confirmation": needs_confirmation,
    }


def user_facing_delivery(job, result):
    status = job.get("status", "").strip()
    canonical_stage = result.get("canonical_stage", "")
    rule_id = result.get("rule_id", "")
    blocker = result.get("blocker_category")

    if status == "done" or (canonical_stage == "terminal" and result.get("next_expected") == "done"):
        return FINAL_VIDEO_DELIVERY
    if (
        status.startswith("seedance_inputs_prepared")
        or canonical_stage == "generation_approval"
        or rule_id == "seedance_inputs_prepared"
    ) and blocker in {"cost_gate", "human_review"}:
        return PRE_SEEDANCE_HANDOFF
    return NO_USER_DELIVERY


def rel_or_abs(root, path):
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def append_existing_path(items, label, root, path):
    if path and path.exists():
        value = rel_or_abs(root, path)
        if not any(existing["path"] == value for existing in items):
            items.append({"label": label, "path": value})


def latest_qc_blockers(output_dir):
    checks_dir = output_dir / "checks"
    if not checks_dir.exists():
        return []
    blockers = []
    for path in sorted(checks_dir.glob("*.json")):
        data = load_qc_data(path)
        overall = str(data.get("overall") or data.get("status") or data.get("result") or "").upper()
        if overall in {"FAIL", "STOP"}:
            blockers.append(path)
    return blockers[-5:]


def inspection_paths(root, job, result):
    job_id = job.get("id", "")
    output_dir = resolve_path(root, job.get("output_dir", "")) or (root / "output" / job_id)
    items = []

    append_existing_path(items, "Output directory", root, output_dir)
    append_existing_path(items, "Finishing edit plan", root, output_dir / "finishing" / "edit_plan.json")
    subtitle_report = output_dir / "subtitle_removal" / "subtitle_removal_report.json"
    active_final = output_dir / "final" / "final_video.mp4"
    if subtitle_report.is_file():
        try:
            subtitle_payload = json.loads(subtitle_report.read_text(encoding="utf-8"))
            candidate = resolve_path(root, subtitle_payload.get("output_video", ""))
            if candidate and candidate.is_file():
                active_final = candidate
        except (OSError, json.JSONDecodeError):
            pass
    pre_caption_final = active_final
    caption_report = caption_report_path_for(root, job)
    if caption_report.is_file() and not caption_report_issues(root, job):
        caption_payload = json.loads(caption_report.read_text(encoding="utf-8"))
        candidate = resolve_path(root, caption_payload.get("output_video", ""))
        if candidate and candidate.is_file():
            active_final = candidate
    append_existing_path(items, "Final video", root, active_final)
    if active_final != pre_caption_final:
        append_existing_path(items, "Pre-caption final video", root, pre_caption_final)
    if pre_caption_final != output_dir / "final" / "final_video.mp4":
        append_existing_path(items, "Pre-removal final video", root, output_dir / "final" / "final_video.mp4")
    append_existing_path(items, "Finishing report", root, output_dir / "final" / "finish_report.md")
    append_existing_path(items, "Subtitle detection", root, output_dir / "subtitle_removal" / "subtitle_detection.json")
    append_existing_path(items, "Subtitle removal report", root, subtitle_report)
    append_existing_path(items, "Final caption request", root, caption_request_path_for(root, job))
    append_existing_path(items, "Final caption report", root, caption_report)
    append_existing_path(items, "Pre-Seedance handoff directory", root, output_dir / "seedance_web_final")
    append_existing_path(items, "Approved visual manifest", root, output_dir / "visual-assets" / "approved_visual_manifest.json")

    final_images = output_dir / "final-images"
    if final_images.exists():
        for path in sorted(final_images.glob("*"))[:6]:
            if path.is_file():
                append_existing_path(items, "Key image", root, path)

    prompt_dir = output_dir / "seedance_web_final" / "prompts"
    if prompt_dir.exists():
        for path in sorted(prompt_dir.glob("*.txt"))[:6]:
            append_existing_path(items, "Seedance prompt", root, path)

    handoff_dir = output_dir / "seedance_web_final"
    if handoff_dir.exists():
        for suffix, label in [("*.mp3", "Reference audio"), ("*.wav", "Reference audio"), ("*.json", "Handoff manifest"), ("*.md", "Handoff note")]:
            for path in sorted(handoff_dir.rglob(suffix))[:4]:
                append_existing_path(items, label, root, path)

    for pattern in ["*.mp4", "*.mov"]:
        for path in sorted(output_dir.rglob(pattern))[:6]:
            append_existing_path(items, "Final/generated video", root, path)

    last_artifact = resolve_path(root, job.get("last_artifact", ""))
    append_existing_path(items, "Last artifact", root, last_artifact)

    checks_dir = output_dir / "checks"
    stage = result.get("canonical_stage", "")
    if checks_dir.exists() and stage:
        for path in sorted(checks_dir.glob(f"{stage}*"))[:6]:
            if path.is_file():
                append_existing_path(items, "Stage QC/report", root, path)
    if result.get("blocker_category") in {"visual_failure", "evidence_failure", "provider_failure"}:
        for path in latest_qc_blockers(output_dir):
            append_existing_path(items, "Blocking QC report", root, path)

    return items[:24]


def apply_transition_to_jobs(jobs, transition):
    updated = False
    for row in jobs:
        if row.get("id") == transition["job"]:
            row["status"] = transition["to_status"]
            row["next_stage"] = transition["to_next_stage"]
            row["last_artifact"] = transition["last_artifact"]
            row["needs_user_confirmation"] = transition["needs_user_confirmation"]
            updated = True
            break
    if not updated:
        raise ValueError(f"job `{transition['job']}` not found in jobs.csv")


def transition_markdown(transition, applied):
    from_stage = user_visible_stage("", transition.get("from_status"), transition.get("from_next_stage"))
    to_stage = user_visible_stage("", transition.get("to_status"), transition.get("to_next_stage"))
    lines = [
        "# 状态更新",
        "",
        f"- 用户可见阶段: **{user_visible_stage_text(from_stage)} -> {user_visible_stage_text(to_stage)}**",
        f"- 本次动作: `{transition['action']}`",
        f"- 是否已写入 jobs.csv: `{str(applied).lower()}`",
        f"- 原因: {transition['reason']}",
        "",
        "## 内部字段（排查用）",
        "",
        f"- Job: `{transition['job']}`",
        f"- Action: `{transition['action']}`",
        f"- Reason: {transition['reason']}",
        f"- Applied: `{str(applied).lower()}`",
        "",
        "## Status",
        "",
        f"- From: `{transition['from_status']}`",
        f"- To: `{transition['to_status']}`",
        "",
        "## Next Stage",
        "",
        f"- From: `{transition['from_next_stage']}`",
        f"- To: `{transition['to_next_stage']}`",
        "",
        "## Artifact",
        "",
        f"- Last artifact: `{transition['last_artifact']}`",
        f"- Needs user confirmation: `{transition['needs_user_confirmation']}`",
        "",
    ]
    return "\n".join(lines)


def cost_stop_result(root, checks, reason, state_job, retry_limit, cost_state):
    gate = "gates/cost_approval_gate.md"
    worker_file = "workers/cost_approval_worker.md"
    add_gate_check(root, checks, gate)
    add_worker_check(root, checks, worker_file)
    return {
        "decision": "stop",
        "reason": reason,
        "blocker_category": "cost_gate",
        "outcome_type": OUTCOME_COST_GATE,
        "canonical_stage": "cost_gate",
        "action": "Stop and prepare a cost approval summary before spending more.",
        "worker": "human approval",
        "worker_file": worker_file,
        "next_expected": "same",
        "rule_id": "cost_policy_stop",
        "gate": gate,
        "retry_state": state_job,
        "retry_limit": retry_limit,
        "cost_state": cost_state,
        "checks": checks,
    }


def explicit_stop_result(root, checks, reason, status, rule, state_job, retry_limit, cost_state):
    gate = "gates/manual_confirmation_gate.md"
    worker_file = "workers/manual_review_worker.md"
    add_gate_check(root, checks, gate)
    add_worker_check(root, checks, worker_file)
    return {
        "decision": "stop",
        "reason": reason,
        "blocker_category": "human_review",
        "outcome_type": OUTCOME_HUMAN_REVIEW,
        "canonical_stage": rule.get("canonical_stage", status) if rule else status,
        "action": "Stop here because this stage/status matched the explicit stop-at list.",
        "worker": "human",
        "worker_file": worker_file,
        "script_file": "none",
        "next_expected": status,
        "rule_id": "explicit_stop_at",
        "gate": gate,
        "retry_state": state_job,
        "retry_limit": retry_limit,
        "cost_state": cost_state,
        "checks": checks,
    }


def asset_stop_result(root, checks, missing, state_job, retry_limit, cost_policy):
    gate = "gates/manual_confirmation_gate.md"
    worker_file = "workers/manual_review_worker.md"
    add_gate_check(root, checks, gate)
    add_worker_check(root, checks, worker_file)
    detail = "; ".join(f"{key}: {status}" for key, status in missing)
    return {
        "decision": "stop",
        "reason": f"required assets missing: {detail}",
        "blocker_category": "evidence_failure",
        "outcome_type": OUTCOME_EVIDENCE_STOP,
        "canonical_stage": "asset_gate",
        "action": "Stop and ask the user to provide the missing source, product, person, or audio assets.",
        "worker": "human",
        "worker_file": worker_file,
        "script_file": "none",
        "next_expected": "same",
        "rule_id": "missing_required_assets",
        "gate": gate,
        "retry_state": state_job,
        "retry_limit": retry_limit,
        "cost_state": cost_state_for(state_job, cost_policy, "free_check"),
        "checks": checks,
    }


def decide(
    root,
    job,
    stage_config,
    runner_state,
    cost_policy,
    allow_paid=False,
    approval_context=None,
    self_audit=False,
    stop_at=None,
    recording_zero_spend_pass=False,
):
    status = job.get("status", "").strip()
    next_stage = job.get("next_stage", "").strip()
    needs_confirmation = parse_bool(job.get("needs_user_confirmation", ""))
    terminal = terminal_statuses(stage_config)
    paid_markers = tuple(stage_config.get("paid_stage_markers", []))
    retry_limit = int(runner_state.get("retry_limit", DEFAULT_RETRY_LIMIT) or DEFAULT_RETRY_LIMIT)
    state_job = ensure_job_state(runner_state, job)
    approval_context = approval_context or {}
    checks = []

    for required in ("STATE.md", "QC_RULES.md", "jobs.csv", "LOOP.md", "RUNNER_STATE.json", "rules/STAGE_RULES.json"):
        path = root / required
        checks.append((required, path.exists(), str(path)))
    add_cost_checks(root, checks, cost_policy)

    asset_checks, missing_assets = required_asset_checks(root, job)
    checks.extend(asset_checks)
    if missing_assets:
        return asset_stop_result(root, checks, missing_assets, state_job, retry_limit, cost_policy)

    last_artifact_ok, last_artifact_status = last_artifact_check(root, job)
    checks.append(("last_artifact", last_artifact_ok, last_artifact_status))

    rule = find_rule(stage_config, status)
    stop_at = stop_at or set()

    if status in terminal:
        gate = rule.get("gate", "none") if rule else "none"
        worker_file = rule.get("worker_file", "none") if rule else "none"
        script_file = rule.get("script_file", "none") if rule else "none"
        cost_class = rule.get("cost_class", "free_check") if rule else "free_check"
        cost_state = cost_state_for(state_job, cost_policy, cost_class)
        add_gate_check(root, checks, gate)
        add_worker_check(root, checks, worker_file)
        add_script_check(root, checks, script_file)
        return {
            "decision": "stop",
            "reason": rule.get("reason", f"selected job is terminal: {status}") if rule else f"selected job is terminal: {status}",
            "blocker_category": blocker_category(state_job.get("last_outcome_type")),
            "outcome_type": state_job.get("last_outcome_type"),
            "canonical_stage": rule.get("canonical_stage", "terminal") if rule else "terminal",
            "action": rule.get("action", "No action.") if rule else "No action.",
            "worker": rule.get("worker", "none") if rule else "none",
            "worker_file": worker_file,
            "script_file": script_file,
            "next_expected": rule.get("next_expected", status) if rule else status,
            "rule_id": rule.get("id", "terminal") if rule else "terminal",
            "gate": gate,
            "retry_state": state_job,
            "retry_limit": retry_limit,
            "cost_state": cost_state,
            "checks": checks,
        }

    if stop_at_matches(rule, status, next_stage, stop_at):
        cost_class = rule.get("cost_class", "free_check") if rule else "free_check"
        cost_state = cost_state_for(state_job, cost_policy, cost_class)
        return explicit_stop_result(
            root,
            checks,
            f"explicit stop-at matched achieved status or current stage `{status}`",
            status,
            rule,
            state_job,
            retry_limit,
            cost_state,
        )

    is_cost_approval_stage = bool(rule and rule.get("canonical_stage") == "generation_approval")
    if is_cost_approval_stage:
        cost_reason, _ = cost_stop_reason(
            status,
            next_stage,
            rule,
            state_job,
            cost_policy,
            paid_markers,
            allow_paid,
            approval_context,
            recording_zero_spend_pass,
        )
        if cost_reason:
            current_cost_state = cost_state_for(state_job, cost_policy, rule.get("cost_class", "expensive_generation"), approval_context)
            return cost_stop_result(root, checks, cost_reason, state_job, retry_limit, current_cost_state)

        gate = rule.get("gate", "gates/cost_approval_gate.md")
        worker_file = rule.get("worker_file", "workers/cost_approval_worker.md")
        script_file = rule.get("script_file", "none")
        cost_class = rule.get("cost_class", "expensive_generation")
        cost_state = cost_state_for(state_job, cost_policy, cost_class, approval_context)
        add_gate_check(root, checks, gate)
        add_worker_check(root, checks, worker_file)
        add_script_check(root, checks, script_file)
        return {
            "decision": "continue",
            "reason": "generation approval is recorded for the approved scope; run the cost approval gate",
            "canonical_stage": rule.get("canonical_stage", "generation_approval"),
            "action": "Write the cost approval note, verify approval scope and task count, then record the cost gate result.",
            "worker": rule.get("worker", "human approval"),
            "worker_file": worker_file,
            "script_file": script_file,
            "next_expected": same_or_value(rule.get("next_expected", status), status),
            "rule_id": rule.get("id", "seedance_inputs_prepared"),
            "gate": gate,
            "retry_state": state_job,
            "retry_limit": retry_limit,
            "cost_state": cost_state,
            "checks": checks,
        }

    approved_mediakit_retry = bool(
        rule
        and rule.get("canonical_stage") == "subtitle_removal"
        and mediakit_retry_approved(approval_context, allow_paid)
    )
    if approved_mediakit_retry:
        needs_confirmation = False

    if needs_confirmation:
        self_audit_rule = rule.get("self_audit", {}) if rule else {}
        if not (self_audit and self_audit_rule.get("allowed")):
            if rule and rule.get("decision") == "stop":
                gate = rule.get("gate", "gates/manual_confirmation_gate.md")
                worker_file = rule.get("worker_file", "workers/manual_review_worker.md")
                script_file = rule.get("script_file", "none")
                cost_class = rule.get("cost_class", "free_check")
                canonical_stage = rule.get("canonical_stage", "confirmation_gate")
                action = rule.get("action", "Ask user to review/approve the current artifact.")
                worker = rule.get("worker", "human")
                next_expected = same_or_value(rule.get("next_expected", status), status)
                rule_id = rule.get("id", "needs_user_confirmation")
                reason = rule.get("reason", "job needs user confirmation")
            else:
                gate = "gates/manual_confirmation_gate.md"
                worker_file = "workers/manual_review_worker.md"
                script_file = "none"
                cost_class = "free_check"
                canonical_stage = "confirmation_gate"
                action = "Ask user to review/approve the current artifact."
                worker = "human"
                next_expected = status
                rule_id = "needs_user_confirmation"
                reason = "job needs user confirmation"
            add_gate_check(root, checks, gate)
            add_worker_check(root, checks, worker_file)
            add_script_check(root, checks, script_file)
            cost_state = cost_state_for(state_job, cost_policy, cost_class)
            return {
                "decision": "stop",
                "reason": reason,
                "blocker_category": "cost_gate" if canonical_stage == "generation_approval" else "human_review",
                "outcome_type": OUTCOME_COST_GATE if canonical_stage == "generation_approval" else OUTCOME_HUMAN_REVIEW,
                "canonical_stage": canonical_stage,
                "action": action,
                "worker": worker,
                "worker_file": worker_file,
                "script_file": script_file,
                "next_expected": next_expected,
                "rule_id": rule_id,
                "gate": gate,
                "retry_state": state_job,
                "retry_limit": retry_limit,
                "cost_state": cost_state,
                "checks": checks,
            }

    retry_stop_reason = retry_limit_reached(state_job, retry_limit)
    if retry_stop_reason:
        gate = "RUNNER_STATE.json"
        worker_file = "workers/manual_review_worker.md"
        script_file = "none"
        add_worker_check(root, checks, worker_file)
        cost_state = cost_state_for(state_job, cost_policy, "free_check")
        return {
            "decision": "stop",
            "reason": retry_stop_reason,
            "blocker_category": blocker_category(state_job.get("last_outcome_type") or OUTCOME_HARD_FAILURE),
            "outcome_type": state_job.get("last_outcome_type") or OUTCOME_HARD_FAILURE,
            "canonical_stage": "retry_limit_gate",
            "action": "Stop this loop. Step back to the previous stage or ask the user which variable to change next.",
            "worker": "human / runner_state_review",
            "worker_file": worker_file,
            "script_file": script_file,
            "next_expected": status,
            "rule_id": "retry_limit_reached",
            "gate": gate,
            "retry_state": state_job,
            "retry_limit": retry_limit,
            "cost_state": cost_state,
            "checks": checks,
        }

    cost_reason, current_cost_state = cost_stop_reason(
        status,
        next_stage,
        rule,
        state_job,
        cost_policy,
        paid_markers,
        allow_paid,
        approval_context,
        recording_zero_spend_pass,
    )
    if cost_reason:
        return cost_stop_result(root, checks, cost_reason, state_job, retry_limit, current_cost_state)

    if rule is None:
        cost_state = cost_state_for(state_job, cost_policy, "free_check")
        return {
            "decision": "plan_only",
            "reason": "no runner rule for this status yet",
            "blocker_category": "evidence_failure",
            "outcome_type": OUTCOME_EVIDENCE_STOP,
            "canonical_stage": "unknown",
            "action": f"Add a rule to rules/STAGE_RULES.json for status `{status}`. Current next_stage is `{next_stage}`.",
            "worker": "runner_spec_update",
            "worker_file": "none",
            "script_file": "none",
            "next_expected": next_stage or status,
            "rule_id": "missing_rule",
            "gate": "none",
            "retry_state": state_job,
            "retry_limit": retry_limit,
            "cost_state": cost_state,
            "checks": checks,
        }

    if rule.get("decision", "continue") == "stop" and self_audit:
        self_audit_rule = rule.get("self_audit", {})
        if self_audit_rule.get("allowed"):
            gate = rule.get("gate", "none")
            worker_file = self_audit_rule.get("worker_file", CHECKER_WORKER_FILE)
            script_file = self_audit_rule.get("script_file", CHECKER_REVIEW_SCRIPT)
            cost_class = rule.get("cost_class", "free_check")
            cost_state = cost_state_for(state_job, cost_policy, cost_class)
            add_gate_check(root, checks, gate)
            add_worker_check(root, checks, worker_file)
            add_script_check(root, checks, script_file)
            add_checker_checks(root, checks, self_audit_rule.get("checker_agent", CHECKER_AGENT_FILE))
            return {
                "decision": "continue",
                "reason": f"self-audit enabled for stop rule `{rule.get('id', '')}`",
                "blocker_category": "none",
                "outcome_type": "PASS",
                "canonical_stage": rule.get("canonical_stage", "self_audit_review"),
                "action": self_audit_rule.get("action", "Run the independent checker review, validate it, then record its gate result."),
                "worker": self_audit_rule.get("worker", "$viral-replica checker"),
                "worker_file": worker_file,
                "script_file": script_file,
                "checker_agent": self_audit_rule.get("checker_agent", CHECKER_AGENT_FILE),
                "next_expected": same_or_value(rule.get("next_expected", status), status),
                "rule_id": rule.get("id", ""),
                "gate": gate,
                "retry_state": state_job,
                "retry_limit": retry_limit,
                "cost_state": cost_state,
                "checks": checks,
                "self_audit": True,
            }

    decision = rule.get("decision", "continue")
    next_expected = same_or_value(rule.get("next_expected", next_stage or status), status)
    gate = rule.get("gate", "none")
    worker_file = rule.get("worker_file", "none")
    script_file = rule.get("script_file", "none")
    cost_class = rule.get("cost_class", "free_check")
    cost_state = cost_state_for(state_job, cost_policy, cost_class, approval_context)
    add_gate_check(root, checks, gate)
    add_worker_check(root, checks, worker_file)
    add_script_check(root, checks, script_file)

    return {
        "decision": decision,
        "reason": rule.get("reason", f"matched stage rule `{rule.get('id', '')}`"),
        "blocker_category": "none",
        "outcome_type": "PASS",
        "canonical_stage": rule.get("canonical_stage", "unknown"),
        "action": rule.get("action", "No action."),
        "worker": rule.get("worker", "none"),
        "worker_file": worker_file,
        "script_file": script_file,
        "next_expected": next_expected,
        "rule_id": rule.get("id", ""),
        "gate": gate,
        "retry_state": state_job,
        "retry_limit": retry_limit,
        "cost_state": cost_state,
        "checks": checks,
    }


def decision_markdown(root, job, result):
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    retry_state = result.get("retry_state") or {}
    cost_state = result.get("cost_state") or {}
    delivery = user_facing_delivery(job, result)
    paths = inspection_paths(root, job, result)
    stage = user_visible_stage(result.get("canonical_stage"), job.get("status"), job.get("next_stage"))
    next_expected = str(result.get("next_expected") or "").strip()
    next_stage = stage if next_expected in {"", "same"} else user_visible_stage("", next_expected, "")
    lines = [
        "# 当前进度",
        "",
        f"- 当前阶段: **{user_visible_stage_text(stage)}**",
        f"- 这一步要做: {stage['summary']}",
        f"- 本轮决策: **{result['decision']}**",
        f"- 下一步预期: **{user_visible_stage_text(next_stage)}**",
        f"- 关键原因: {result['reason']}",
        f"- 需要执行: {result['action']}",
        "",
        "## 内部字段（排查用）",
        "",
        f"- Generated: {now}",
        f"- Selected job: `{job.get('id', '')}`",
        f"- Status: `{job.get('status', '')}`",
        f"- Next stage field: `{job.get('next_stage', '')}`",
        f"- Decision: **{result['decision']}**",
        f"- Reason: {result['reason']}",
        f"- Outcome type: `{result.get('outcome_type')}`",
        f"- Blocker category: `{result.get('blocker_category', 'none')}`",
        f"- User-facing delivery: `{delivery}`",
        f"- Matched rule: `{result.get('rule_id', '')}`",
        f"- Canonical stage: `{result['canonical_stage']}`",
        f"- Worker: `{result['worker']}`",
        f"- Worker file: `{result.get('worker_file', 'none')}`",
        f"- Script file: `{result.get('script_file', 'none')}`",
        f"- Gate: `{result.get('gate', 'none')}`",
        f"- Expected next status: `{result['next_expected']}`",
    ]
    if result.get("checker_agent"):
        lines.append(f"- Checker agent: `{result['checker_agent']}`")
    if result.get("self_audit"):
        lines.append("- Self-audit: `true`")
    lines.extend([
        "",
        "## Runner State",
        "",
        f"- Last gate result: `{retry_state.get('last_gate_result')}`",
        f"- Last outcome type: `{retry_state.get('last_outcome_type')}`",
        f"- Last blocker category: `{retry_state.get('last_blocker_category')}`",
        f"- Current failure type: `{retry_state.get('current_failure_type')}`",
        f"- Failure count: `{retry_state.get('failure_count', 0)} / {result.get('retry_limit', DEFAULT_RETRY_LIMIT)}`",
        f"- Retry count: `{retry_state.get('retry_count', 0)}`",
        f"- Consecutive no-progress rounds: `{retry_state.get('consecutive_no_progress', 0)}`",
        "",
        "## Cost State",
        "",
        f"- Cost class: `{cost_state.get('cost_class', 'unknown')}`",
        f"- Image generation runs: `{cost_state.get('gpt_image_runs', 0)} / {cost_state.get('gpt_image_hard_limit', 0)}`",
        f"- Image generation soft limit: `{cost_state.get('gpt_image_soft_limit', 0)}`",
        f"- Seedance runs: `{cost_state.get('seedance_runs', 0)}`",
        f"- MediaKit subtitle-removal runs: `{cost_state.get('mediakit_subtitle_removal_runs', 0)}`",
        f"- Approval scope: `{cost_state.get('approval_scope')}`",
        f"- Approved task count: `{cost_state.get('approved_task_count', 0)}`",
        f"- Planned task count: `{cost_state.get('planned_task_count', 0)}`",
        f"- Submitted task count: `{cost_state.get('submitted_task_count', 0)}`",
        f"- Generation intent: `{cost_state.get('generation_intent')}`",
        "",
        "## Action",
        "",
        result["action"],
        "",
        "## Checks",
        "",
    ])
    for name, ok, detail in result["checks"]:
        mark = "PASS" if ok else "FAIL"
        lines.append(f"- {mark}: `{name}` - {detail}")
    lines.extend([
        "",
        "## Inspection Paths",
        "",
    ])
    if paths:
        for item in paths:
            lines.append(f"- {item['label']}: `{item['path']}`")
    else:
        lines.append("- No concrete artifact paths found yet.")
    lines.extend([
        "",
        "## Suggested Next Prompt",
        "",
        "```text",
        f"Run one loop round for {job.get('id', '')}.",
        f"Current status: {job.get('status', '')}.",
        "Mandatory skill: first read and follow .agents/skills/video-replication/SKILL.md.",
        "Use .agents/skills/viral-replica/SKILL.md only as the loop adapter.",
        f"Do only this action: {result['action']}",
        f"Use worker contract: {result.get('worker_file', 'none')}.",
        f"Use script if applicable: {result.get('script_file', 'none')}.",
        f"Use gate contract: {result.get('gate', 'none')}.",
        "Dispatch only sealed tools/stage_execution.py work packets; every maker or sub-agent writes its declared job-local completion artifact.",
    ])
    if result.get("checker_agent"):
        lines.extend([
            f"Use checker agent: {result['checker_agent']}.",
            "Save checker review to output/<job-id>/checks/<stage>_gate_review.md.",
            "Validate checker review with tools/checker_review_qc.py before recording the gate result.",
        ])
    lines.extend([
        "Do not write STATE.md, jobs.csv, or RUNNER_STATE.json directly.",
        "The coordinator records the gate through ./run-loop.sh --record-gate-result and applies the transition.",
        "Stop before paid/batch generation. Final technical QC PASS delivers the final video; subjective review is post-delivery.",
        "```",
        "",
    ])
    return "\n".join(lines)


def gate_record_markdown(root, job, decision, event, job_state, retry_limit):
    transition_preview = {
        "canonical_stage": "terminal" if event["result"] == "PASS" and decision.get("next_expected") == "done" else decision.get("canonical_stage", ""),
        "next_expected": decision.get("next_expected"),
        "rule_id": decision.get("rule_id"),
        "blocker_category": event.get("blocker_category"),
    }
    delivery = user_facing_delivery(
        {**job, "status": "done"} if event["result"] == "PASS" and decision.get("next_expected") == "done" else job,
        transition_preview,
    )
    paths = inspection_paths(root, job, decision)
    stage = user_visible_stage(event.get("stage"), job.get("status"), job.get("next_stage"))
    next_expected = str(decision.get("next_expected") or "").strip()
    next_stage = stage if next_expected in {"", "same"} else user_visible_stage(transition_preview.get("canonical_stage"), next_expected, "")
    lines = [
        "# 阶段记录",
        "",
        f"- 当前阶段: **{user_visible_stage_text(stage)}**",
        f"- 本次结果: **{event['result']}**",
        f"- 下一步预期: **{user_visible_stage_text(next_stage)}**",
        f"- 产物: `{event.get('artifact')}`",
        f"- 对外交付: `{delivery}`",
        "",
        "## 内部字段（排查用）",
        "",
        f"- Job: `{job.get('id', '')}`",
        f"- Status: `{job.get('status', '')}`",
        f"- Stage: `{event['stage']}`",
        f"- Gate: `{event['gate']}`",
        f"- Result: **{event['result']}**",
        f"- Outcome type: `{event.get('outcome_type')}`",
        f"- Blocker category: `{event.get('blocker_category')}`",
        f"- Why not fail: `{event.get('why_not_fail')}`",
        f"- Failure type: `{event.get('failure_type')}`",
        f"- Retry variable: `{event.get('retry_variable')}`",
        f"- Artifact: `{event.get('artifact')}`",
        f"- Failure count: `{job_state.get('failure_count', 0)} / {retry_limit}`",
        f"- Retry count: `{job_state.get('retry_count', 0)}`",
        f"- Consecutive no-progress rounds: `{job_state.get('consecutive_no_progress', 0)}`",
        f"- Approval scope: `{event.get('approval_scope')}`",
        f"- Approved task count: `{event.get('approved_task_count')}`",
        f"- Submitted task count: `{event.get('submitted_task_count')}`",
        f"- Seedance runs: `{event.get('seedance_runs')}`",
        f"- User-facing delivery: `{delivery}`",
        "",
        "## Next Runner Decision",
        "",
        f"- Current decision before recording: **{decision['decision']}**",
        f"- Expected next status: `{decision['next_expected']}`",
        "",
    ]
    if event["result"] == "FAIL" and int(job_state.get("failure_count", 0) or 0) >= retry_limit:
        lines.extend([
            "## Stop Trigger",
            "",
            "Same failure reached the retry limit. The next normal runner decision will stop and ask to step back or change strategy.",
            "",
        ])
    lines.extend([
        "## Inspection Paths",
        "",
    ])
    if paths:
        for item in paths:
            lines.append(f"- {item['label']}: `{item['path']}`")
    else:
        lines.append("- No concrete artifact paths found yet.")
    return "\n".join(lines)


def decision_event(job, result):
    stage = user_visible_stage(result.get("canonical_stage"), job.get("status"), job.get("next_stage"))
    return {
        "type": "decision",
        "job": job.get("id", ""),
        "workflow_run_id": job.get("workflow_run_id", ""),
        "status": job.get("status", ""),
        "next_stage": job.get("next_stage", ""),
        "decision": result.get("decision"),
        "reason": result.get("reason"),
        "outcome_type": result.get("outcome_type"),
        "blocker_category": result.get("blocker_category"),
        "stage": result.get("canonical_stage"),
        "user_stage_index": stage["index"],
        "user_stage": stage["label"],
        "rule": result.get("rule_id"),
        "worker": result.get("worker_file"),
        "gate": result.get("gate"),
        "expected_next_status": result.get("next_expected"),
        "user_facing_delivery": user_facing_delivery(job, result),
        "self_audit": bool(result.get("self_audit")),
        "checker_agent": result.get("checker_agent"),
    }


def main():
    parser = argparse.ArgumentParser(description="Minimal video replication loop runner.")
    parser.add_argument("--root", default="viral-replica-loop", help="Loop root directory.")
    parser.add_argument("--job-id", default="", help="Select a specific job id. Useful for auto-runs that must stay pinned to one job.")
    parser.add_argument("--allow-paid", action="store_true", help="Allow paid/batch generation stages.")
    parser.add_argument("--approval-recorded", action="store_true", help="Mark that explicit user approval for the current paid action has been recorded.")
    parser.add_argument("--approval-source-message", default="", help="Current user message or approval source text. Direct Seedance requests count as current-job approval.")
    parser.add_argument("--approval-scope", choices=sorted(APPROVAL_SCOPES), default="", help="Approval scope for paid generation.")
    parser.add_argument("--approval-task-count", type=int, default=0, help="Number of Seedance tasks approved by the current approval.")
    parser.add_argument("--planned-task-count", type=int, default=0, help="Number of Seedance tasks the runner plans to submit.")
    parser.add_argument("--generation-intent", choices=sorted(GENERATION_INTENTS), default="current_job", help="Generation type being approved or submitted.")
    parser.add_argument(
        "--approve-mediakit-subtitle-retry",
        action="store_true",
        help=(
            "Use the current explicit targeted-retry approval for one additional "
            "MediaKit subtitle-removal attempt. Requires --allow-paid, "
            "--approval-recorded, and --approval-scope targeted_retry."
        ),
    )
    parser.add_argument("--self-audit", action="store_true", help="Allow configured review stops to be handled by the independent checker instead of the user.")
    parser.add_argument("--stop-at", action="append", default=[], help="Stop when the achieved status, current rule id, or current canonical stage matches this value. Can be repeated or comma-separated.")
    parser.add_argument("--dry-run", action="store_true", help="Print decision without writing RUNNER_LAST_DECISION.md.")
    parser.add_argument("--record-gate-result", choices=sorted(GATE_RESULTS), help="Record a gate result in RUNNER_STATE.json.")
    parser.add_argument("--outcome-type", choices=sorted(GATE_OUTCOMES), default="", help="QC outcome taxonomy for this gate result.")
    parser.add_argument("--why-not-fail", default="", help="Required when --outcome-type VISUAL_WARNING explains why the warning is not a hard failure.")
    parser.add_argument("--apply-transition", action="store_true", help="Apply PASS/FAIL/STOP transition to jobs.csv after recording a gate result.")
    parser.add_argument("--failure-type", default="", help="Failure type for FAIL results, e.g. thin_mud or rhythm_drift.")
    parser.add_argument("--retry-variable", default="", help="The single variable changed on the next retry.")
    parser.add_argument("--artifact", default="", help="Artifact path produced or reviewed by this gate.")
    parser.add_argument("--note", default="", help="Short note to store with the gate result.")
    parser.add_argument("--spent-gpt-image-runs", type=int, default=0, help="Image generation runs spent in this gate round.")
    parser.add_argument("--spent-seedance-runs", type=int, default=0, help="Seedance runs spent in this gate round.")
    parser.add_argument(
        "--spent-mediakit-subtitle-removal-runs",
        type=int,
        default=0,
        help="MediaKit Pro subtitle-removal tasks spent in this gate round (maximum one).",
    )
    args = parser.parse_args()

    if args.apply_transition and not args.record_gate_result:
        parser.error("--apply-transition requires --record-gate-result")

    root = Path(args.root).resolve()
    lock_path = root / ".run-loop.lock"
    with lock_path.open("w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)

        jobs_path = root / "jobs.csv"
        stage_config, _ = load_stage_rules(root)
        runner_state, runner_state_path = load_runner_state(root)
        cost_policy, _ = load_cost_policy(root)
        jobs, job_fieldnames = read_jobs_table(jobs_path)
        requested_job_id = args.job_id.strip()
        selected_job_id = requested_job_id or (select_job_id(root, self_audit=args.self_audit, allow_paid=args.allow_paid) or "")
        job = select_job(jobs, terminal_statuses(stage_config), selected_job_id)
        stop_at = normalize_stop_at(args.stop_at)

        if job is None:
            reason = f"job `{requested_job_id}` not found" if requested_job_id else "no runnable jobs found"
            stage = DEFAULT_USER_VISIBLE_STAGE
            text = "\n".join([
                "# 当前进度",
                "",
                f"- 当前阶段: **{user_visible_stage_text(stage)}**",
                "- 本轮决策: **stop**",
                f"- 关键原因: {reason}",
                "",
                "## 内部字段（排查用）",
                "",
                "- Decision: **stop**",
                f"- Reason: {reason}",
                "",
            ])
            result = None
        else:
            current_approval_context = approval_context_for(
                root,
                job,
                ensure_job_state(runner_state, job),
                cost_policy,
                args,
            )
            result = decide(
                root,
                job,
                stage_config,
                runner_state,
                cost_policy,
                allow_paid=args.allow_paid,
                approval_context=current_approval_context,
                self_audit=args.self_audit,
                stop_at=stop_at,
                recording_zero_spend_pass=bool(
                    args.record_gate_result == "PASS"
                    and int(args.spent_gpt_image_runs or 0) == 0
                ),
            )
            result = apply_optional_caption_transition(root, job, result)
            if (
                not args.record_gate_result
                and result.get("canonical_stage") == "subtitle_removal"
            ):
                attempt_reason = existing_mediakit_attempt_reason(
                    root,
                    job,
                    retry_approved=mediakit_retry_approved(
                        current_approval_context,
                        args.allow_paid,
                    ),
                )
                if attempt_reason:
                    retry_limit = int(
                        runner_state.get("retry_limit", DEFAULT_RETRY_LIMIT)
                        or DEFAULT_RETRY_LIMIT
                    )
                    job_state = ensure_job_state(runner_state, job)
                    cost_state = cost_state_for(
                        job_state,
                        cost_policy,
                        "conditional_paid_repair",
                    )
                    result = cost_stop_result(
                        root,
                        result.get("checks", []),
                        attempt_reason,
                        job_state,
                        retry_limit,
                        cost_state,
                    )
            if args.record_gate_result:
                preflight_pass_recording(root, job, result, args)
                job_state = ensure_job_state(runner_state, job)
                preflight_cost_policy_recording(root, job, result, args, cost_policy, job_state)
                job_state, event = record_gate_result(runner_state, job, result, args, root, cost_policy)
                if (
                    event["result"] == "PASS"
                    and event["stage"] == "image_batch_qc"
                    and not args.dry_run
                ):
                    reuse_snapshot = record_snapshot(root, job.get("id", ""), event["stage"])
                    job_state["visual_qc_reuse"] = {
                        "state_path": reuse_snapshot.get("state_path"),
                        "fingerprint_hash": reuse_snapshot.get("fingerprint", {}).get("fingerprint_hash"),
                        "updated_at": reuse_snapshot.get("updated_at"),
                    }
                    event["visual_qc_reuse_state"] = reuse_snapshot.get("state_path")
                retry_limit = int(runner_state.get("retry_limit", DEFAULT_RETRY_LIMIT) or DEFAULT_RETRY_LIMIT)
                transition = transition_for_gate_result(job, result, event, stage_config)
                text = gate_record_markdown(root, job, result, event, job_state, retry_limit)
                transition_text = transition_markdown(transition, args.apply_transition)
                text = text + "\n\n" + transition_text
                if not args.dry_run:
                    write_runner_state(runner_state_path, runner_state)
                    transition_path = root / "RUNNER_LAST_TRANSITION.md"
                    transition_path.write_text(transition_text, encoding="utf-8")
                    append_event_log(root, {"type": "gate_result", **event, "transition": transition})
                    if args.apply_transition:
                        apply_transition_to_jobs(jobs, transition)
                        write_jobs_table(jobs_path, jobs, job_fieldnames)
            else:
                text = decision_markdown(root, job, result)

        print(text)
        if not args.dry_run and not args.record_gate_result:
            out = root / "RUNNER_LAST_DECISION.md"
            out.write_text(text, encoding="utf-8")
            if job is None:
                append_event_log(root, {"type": "decision", "decision": "stop", "reason": reason})
            else:
                job_state = ensure_job_state(runner_state, job)
                if start_stage_attempt(job_state, job, result):
                    runner_state["updated_at"] = now_iso()
                    write_runner_state(runner_state_path, runner_state)
                append_event_log(root, decision_event(job, result))
            print(f"\nWrote: {out}")
        elif not args.dry_run and args.record_gate_result:
            print(f"\nWrote: {runner_state_path}")
            print(f"Wrote: {root / 'RUNNER_LAST_TRANSITION.md'}")
            if args.apply_transition:
                print(f"Updated: {jobs_path}")


if __name__ == "__main__":
    main()
