#!/usr/bin/env python3
"""Initialize and render a director-plan-backed pre-Seedance pack."""

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from pre_seedance_part_compiler import MAX_WORKERS as PART_COMPILER_MAX_WORKERS
from pre_seedance_part_compiler import compile_and_merge
from presenter_gender import presenter_gender_text_issues, validate_presenter_gender_pair
from seedance_request_contract import TASK_CREATE_URL, build_taskcode_request
from speech_budget import assess_speech_groups, spoken_units


DEFAULT_PART_DURATION = 15.0
MIN_PART_DURATION = 4.0
MAX_PART_DURATION = 15.0
MAX_AUDIO_SECONDS = 14.90
HANDOFF_MODES = ("web", "api", "both")
INIT_HANDOFF_MODES = ("auto",) + HANDOFF_MODES
REUSABLE_ROLE_ORDER = (
    "product_front",
    "product_open",
    "product_open_mud",
    "identity_ref",
)
IGNORED_REUSABLE_ROLES = {"afterwash_face"}
ROLE_LABELS = {
    "storyboard": "分镜参考",
    "product_front": "产品正面",
    "product_open": "产品开盖参考",
    "product_open_mud": "产品开盖材质",
    "identity_ref": "主播身份",
}
SCRIPT_TEXT_SEPARATORS = re.compile(r"[\s，。！？；：、,.!?;:'\"“”‘’（）()《》【】\[\]{}<>—…·-]+")
IMAGE_REFERENCE_RE = re.compile(r"@图片(\d+)")
ALLOWED_LINE_EDIT_REASONS = {
    "product_name",
    "product_fact",
    "person_or_role",
    "price_or_offer",
    "duration_compression",
    "user_requested",
}
PRODUCT_FACT_CONFLICT_KINDS = {
    "wrong_product_form",
    "unsupported_effect",
    "wrong_ingredient",
    "contradicted_frequency",
    "unsupported_replacement_claim",
    "wrong_usage_action",
}
PRICE_OFFER_CONFLICT_KINDS = {
    "expired_campaign",
    "unsupported_offer",
}
FACT_TARGET_POLICIES = {
    "profile_supported",
    "neutralize_unsupported_claim",
}
ALLOWED_VISUAL_EDIT_REASONS = {
    "product_identity",
    "product_fact",
    "product_action_translation",
    "person_identity",
    "remove_source_overlay",
    "safety_or_policy",
    "user_requested",
}
LOCKED_VISUAL_DIMENSIONS = (
    "shot_order",
    "scene",
    "camera",
    "framing",
    "action_stage",
    "action_timing",
    "hard_cuts",
)
VISUAL_FIDELITY_FIELDS = (
    "scene",
    "camera",
    "framing",
    "action_stage",
    "action_timing",
    "transition",
    "hard_cuts",
)


def read_json(path):
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.rstrip() + "\n", encoding="utf-8")


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_path(root, value):
    path = Path(value).expanduser()
    return path if path.is_absolute() else root / path


def display_path(root, path):
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def normalized_spoken_text(value):
    return SCRIPT_TEXT_SEPARATORS.sub("", str(value or "")).casefold()


def validate_request_evidence(value, context, root, current_job_id):
    if not isinstance(value, dict):
        raise ValueError(f"{context} requires request_evidence bound to BRIEF or intake")
    source = str(value.get("source", "")).strip()
    path = str(value.get("path", "")).strip()
    sha256 = str(value.get("sha256", "")).strip()
    quote = str(value.get("quote", "")).strip()
    if source not in {"brief", "intake"} or not path or not quote or not re.fullmatch(
        r"[0-9a-f]{64}", sha256
    ):
        raise ValueError(f"{context} requires request_evidence bound to BRIEF or intake")
    if root is None:
        raise ValueError(f"{context} request_evidence cannot be verified without a root")
    if source == "brief" and Path(path).as_posix() != "BRIEF.md":
        raise ValueError(f"{context} brief request_evidence must bind BRIEF.md")
    if source == "intake":
        expected_intake_path = Path("output") / current_job_id / "intake.json"
        if Path(path).as_posix() != expected_intake_path.as_posix():
            raise ValueError(
                f"{context} intake request_evidence must bind the current job"
            )
    evidence_path = resolve_path(root, path)
    if not evidence_path.is_file():
        raise ValueError(f"{context} request_evidence file is missing: {path}")
    if file_sha256(evidence_path) != sha256:
        raise ValueError(f"{context} request_evidence hash does not match: {path}")
    if quote not in evidence_path.read_text(encoding="utf-8"):
        raise ValueError(f"{context} request_evidence quote is absent from: {path}")


def json_pointer_value(document, pointer):
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("fact_evidence support ref requires a JSON pointer")
    value = document
    for raw_token in pointer.removeprefix("/").split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            try:
                value = value[int(token)]
            except (ValueError, IndexError) as exc:
                raise ValueError(
                    "fact_evidence support ref JSON pointer is invalid"
                ) from exc
        elif isinstance(value, dict) and token in value:
            value = value[token]
        else:
            raise ValueError("fact_evidence support ref JSON pointer is invalid")
    return value


def validate_fact_evidence(
    value,
    source_text,
    target_text,
    reason,
    context,
    root,
    current_job_id,
):
    message = f"{reason} requires fact_evidence bound to the current product profile"
    if not isinstance(value, dict) or root is None:
        raise ValueError(message)
    expected_path = Path("output") / current_job_id / "product_profile.json"
    path = str(value.get("path", "")).strip()
    sha256 = str(value.get("sha256", "")).strip()
    conflict_kind = str(value.get("conflict_kind", "")).strip()
    target_policy = str(value.get("target_policy", "")).strip()
    allowed_conflicts = (
        PRODUCT_FACT_CONFLICT_KINDS
        if reason == "product_fact"
        else PRICE_OFFER_CONFLICT_KINDS
    )
    if (
        value.get("source") != "product_profile"
        or Path(path).as_posix() != expected_path.as_posix()
        or not re.fullmatch(r"[0-9a-f]{64}", sha256)
        or normalized_spoken_text(value.get("source_slot")) != source_text
        or normalized_spoken_text(value.get("target_slot")) != target_text
        or conflict_kind not in allowed_conflicts
        or target_policy not in FACT_TARGET_POLICIES
    ):
        raise ValueError(message)
    profile_path = resolve_path(root, path)
    if not profile_path.is_file() or file_sha256(profile_path) != sha256:
        raise ValueError(message)
    profile = read_json(profile_path)
    support_refs = value.get("support_refs")
    if not isinstance(support_refs, list) or not support_refs:
        raise ValueError(message)
    referenced_texts = []
    for support_ref in support_refs:
        if not isinstance(support_ref, dict):
            raise ValueError(message)
        pointer = str(support_ref.get("json_pointer", "")).strip()
        quote = str(support_ref.get("quote", "")).strip()
        if not pointer or not quote:
            raise ValueError(message)
        try:
            referenced = json_pointer_value(profile, pointer)
        except ValueError as exc:
            raise ValueError(message) from exc
        referenced_text = (
            json.dumps(referenced, ensure_ascii=False)
            if isinstance(referenced, (dict, list))
            else str(referenced)
        )
        if quote not in referenced_text:
            raise ValueError(message)
        referenced_texts.append(referenced_text)
    if conflict_kind == "contradicted_frequency":
        target_slot = normalized_spoken_text(value.get("target_slot"))
        if (
            target_policy != "profile_supported"
            or not target_slot
            or not any(
                target_slot in normalized_spoken_text(referenced_text)
                for referenced_text in referenced_texts
            )
        ):
            raise ValueError(message)


def validate_source_product_slot_evidence(
    value,
    source_line,
    source_text,
    root,
    source_rhythm_binding,
    allowed_source_beat_ids,
):
    message = "product_name edit requires current source-slot evidence"
    if (
        not isinstance(value, dict)
        or root is None
        or not isinstance(source_rhythm_binding, dict)
    ):
        raise ValueError(message)
    path = str(value.get("path", "")).strip()
    sha256 = str(value.get("sha256", "")).strip()
    beat_id = str(value.get("beat_id", "")).strip()
    text = str(value.get("text", "")).strip()
    if (
        value.get("source") != "source_rhythm"
        or not path
        or not beat_id
        or not re.fullmatch(r"[0-9a-f]{64}", sha256)
        or normalized_spoken_text(text) != source_text
        or path != str(source_rhythm_binding.get("path", ""))
        or sha256 != str(source_rhythm_binding.get("analysis_sha256", ""))
        or set(allowed_source_beat_ids) != {beat_id}
    ):
        raise ValueError(message)
    evidence_path = resolve_path(root, path)
    if not evidence_path.is_file() or file_sha256(evidence_path) != sha256:
        raise ValueError(message)
    source_rhythm = read_json(evidence_path)
    if int(source_rhythm.get("schema_version") or 0) < 3:
        raise ValueError(message)
    matches = [
        beat
        for beat in source_rhythm.get("beats") or []
        if str(beat.get("id", "")) == beat_id
    ]
    if len(matches) != 1:
        raise ValueError(message)
    beat = matches[0]
    declared_names = beat.get("spoken_product_names")
    if (
        not isinstance(declared_names, list)
        or source_text not in {
            normalized_spoken_text(name) for name in declared_names
        }
        or source_text not in normalized_spoken_text(beat.get("confirmed_source_line"))
        or source_text not in normalized_spoken_text(source_line)
    ):
        raise ValueError(message)
    review_path = evidence_path.parents[1] / "checks" / "source_rhythm_visual_review_qc.json"
    if not review_path.is_file():
        raise ValueError(message)
    review = read_json(review_path)
    review_checks = {
        str(item.get("beat_id", "")): item
        for item in review.get("checks") or []
        if isinstance(item, dict)
    }
    review_item = review_checks.get(beat_id)
    confirmed_names = (
        review_item.get("confirmed_spoken_product_names")
        if isinstance(review_item, dict)
        else None
    )
    if (
        review.get("overall") != "PASS"
        or review.get("source_rhythm_sha256") != sha256
        or not isinstance(review_item, dict)
        or review_item.get("spoken_product_names_are_product_entities") is not True
        or not isinstance(confirmed_names, list)
        or source_text
        not in {normalized_spoken_text(name) for name in confirmed_names}
    ):
        raise ValueError(message)


def occurrence_start(text, source, occurrence):
    starts = [match.start() for match in re.finditer(re.escape(source), text)]
    if occurrence < 1 or occurrence > len(starts):
        raise ValueError("occurrence is outside the current source line")
    return starts[occurrence - 1]


def apply_line_edits(
    source_line,
    edits,
    job_product_name,
    context,
    replication_fidelity=None,
    root=None,
    current_job_id="",
    source_rhythm_binding=None,
    source_char_beat_ids=None,
):
    current = normalized_spoken_text(source_line)
    current_char_beat_ids = list(source_char_beat_ids or [None] * len(current))
    if len(current_char_beat_ids) != len(current):
        raise ValueError(f"{context} source beat character map is invalid")
    duration_mode = str((replication_fidelity or {}).get("duration_mode", "source_length"))
    strict_necessary_only = (
        (replication_fidelity or {}).get("change_policy") == "necessary_only"
    )
    for index, edit in enumerate(edits, start=1):
        edit_context = f"{context} line edit {index}"
        if not isinstance(edit, dict):
            raise ValueError(f"{edit_context} must be an object")
        kind = str(edit.get("kind", "")).strip()
        source_text = normalized_spoken_text(edit.get("from"))
        target_text = normalized_spoken_text(edit.get("to"))
        reason = str(edit.get("reason", "")).strip()
        reason_detail = str(edit.get("reason_detail", "")).strip()
        if kind not in {"replace", "delete"}:
            raise ValueError(f"{edit_context} kind must be replace or delete")
        if not source_text:
            raise ValueError(f"{edit_context} from must name one exact source slot")
        occurrence = edit.get("occurrence")
        occurrence_count = current.count(source_text)
        if occurrence is None and occurrence_count != 1:
            raise ValueError(
                f"{edit_context} repeated from requires a 1-based occurrence"
            )
        if occurrence is not None and (
            isinstance(occurrence, bool) or not isinstance(occurrence, int)
        ):
            raise ValueError(f"{edit_context} occurrence must be a positive integer")
        selected_occurrence = 1 if occurrence is None else occurrence
        try:
            start = occurrence_start(current, source_text, selected_occurrence)
        except ValueError as exc:
            raise ValueError(f"{edit_context} {exc}") from exc
        affected_source_beat_ids = {
            beat_id
            for beat_id in current_char_beat_ids[start : start + len(source_text)]
            if beat_id
        }
        if reason not in ALLOWED_LINE_EDIT_REASONS:
            raise ValueError(f"{edit_context} reason is not allowed")
        if not reason_detail:
            raise ValueError(f"{edit_context} reason_detail is required")
        if kind == "replace" and not target_text:
            raise ValueError(f"{edit_context} replacement text is required")
        if kind == "delete" and target_text:
            raise ValueError(f"{edit_context} delete must use an empty to value")
        if reason == "product_name" and target_text != normalized_spoken_text(job_product_name):
            raise ValueError(f"{edit_context} product_name replacement must equal the job product name")
        if kind == "delete" and reason not in {"duration_compression", "user_requested"}:
            raise ValueError(
                f"{edit_context} delete is allowed only for explicit compression or user request"
            )
        if reason == "duration_compression":
            if duration_mode != "user_compressed":
                raise ValueError(
                    f"{edit_context} duration_compression requires explicit user_compressed mode"
                )
            if kind != "delete":
                raise ValueError(f"{edit_context} duration_compression may only delete")
        if reason == "user_requested":
            if strict_necessary_only:
                validate_request_evidence(
                    edit.get("request_evidence"),
                    f"{edit_context} user_requested",
                    root,
                    current_job_id,
                )
            elif not str(edit.get("request_evidence", "")).strip():
                raise ValueError(f"{edit_context} user_requested requires request_evidence")
        if strict_necessary_only and reason == "person_or_role":
            validate_request_evidence(
                edit.get("request_evidence"),
                f"{edit_context} person_or_role",
                root,
                current_job_id,
            )
        if strict_necessary_only and reason == "product_name":
            try:
                validate_source_product_slot_evidence(
                    edit.get("source_slot_evidence"),
                    source_line,
                    source_text,
                    root,
                    source_rhythm_binding,
                    affected_source_beat_ids,
                )
            except ValueError as exc:
                raise ValueError(f"{edit_context} {exc}") from exc
        if (
            strict_necessary_only
            and
            source_text == current
            and reason not in {"product_name", "duration_compression", "user_requested"}
        ):
            raise ValueError(
                f"{edit_context} must edit a local slot, not replace the whole source line"
            )
        if strict_necessary_only and reason in {"product_fact", "price_or_offer"}:
            try:
                validate_fact_evidence(
                    edit.get("fact_evidence"),
                    source_text,
                    target_text,
                    reason,
                    edit_context,
                    root,
                    current_job_id,
                )
            except ValueError as exc:
                raise ValueError(f"{edit_context} {exc}") from exc
        replacement_beat_id = None
        if reason == "product_name" and isinstance(
            edit.get("source_slot_evidence"), dict
        ):
            replacement_beat_id = str(
                edit["source_slot_evidence"].get("beat_id", "")
            ).strip() or None
        current = (
            current[:start] + target_text + current[start + len(source_text) :]
        )
        current_char_beat_ids = (
            current_char_beat_ids[:start]
            + [replacement_beat_id] * len(target_text)
            + current_char_beat_ids[start + len(source_text) :]
        )
    return current


def validate_script_fidelity(plan, parts, root=None):
    job_product_name = plan.get("job", {}).get("product_name", "")
    current_job_id = str(plan.get("job", {}).get("id", "")).strip()
    source_rhythm_binding = plan.get("source_rhythm")
    source_rhythm_beats = {}
    if isinstance(source_rhythm_binding, dict) and root is not None:
        source_rhythm_path = resolve_path(root, source_rhythm_binding.get("path", ""))
        if source_rhythm_path.is_file():
            source_rhythm_beats = {
                str(beat.get("id", "")): beat
                for beat in (read_json(source_rhythm_path).get("beats") or [])
                if isinstance(beat, dict)
            }
    replication_fidelity = (
        (plan.get("replication_fidelity") or {})
        if int(plan.get("version") or 0) >= 6
        else {}
    )
    for part in parts:
        beats = {beat["id"]: beat for beat in part["beats"]}
        for group_index, group in enumerate(part["speech_groups"], start=1):
            context = f"{part['id']} speech group {group_index}"
            line_edits = group.get("line_edits")
            if not isinstance(line_edits, list):
                raise ValueError(f"{context} line_edits must be a list")
            source_line = "".join(
                str(beats[beat_id].get("source_line", ""))
                for beat_id in group["beat_ids"]
            )
            source_char_beat_ids = []
            for beat_id in group["beat_ids"]:
                target_beat = beats[beat_id]
                target_line = normalized_spoken_text(target_beat.get("source_line"))
                mapped_ids = [
                    str(value)
                    for value in target_beat.get("source_beat_ids") or []
                    if str(value)
                ]
                mapped_lines = [
                    normalized_spoken_text(
                        source_rhythm_beats.get(value, {}).get(
                            "confirmed_source_line"
                        )
                    )
                    for value in mapped_ids
                ]
                if mapped_ids and "".join(mapped_lines) == target_line:
                    for mapped_id, mapped_line in zip(mapped_ids, mapped_lines):
                        source_char_beat_ids.extend([mapped_id] * len(mapped_line))
                elif len(mapped_ids) == 1:
                    source_char_beat_ids.extend([mapped_ids[0]] * len(target_line))
                else:
                    source_char_beat_ids.extend([None] * len(target_line))
            expected_line = apply_line_edits(
                source_line,
                line_edits,
                job_product_name,
                context,
                replication_fidelity,
                root,
                current_job_id,
                source_rhythm_binding,
                source_char_beat_ids,
            )
            if expected_line != normalized_spoken_text(group.get("line")):
                raise ValueError(f"{context} has an undeclared script rewrite")


def validate_replication_fidelity(plan, parts, root=None):
    contract = plan.get("replication_fidelity")
    if not isinstance(contract, dict):
        raise ValueError("director plan v6 requires replication_fidelity")
    if contract.get("mode") != "source_locked":
        raise ValueError("replication_fidelity.mode must be source_locked")
    if contract.get("change_policy") != "necessary_only":
        raise ValueError("replication_fidelity.change_policy must be necessary_only")
    duration_mode = str(contract.get("duration_mode", "")).strip()
    if duration_mode not in {"source_length", "user_compressed"}:
        raise ValueError(
            "replication_fidelity.duration_mode must be source_length or user_compressed"
        )
    if duration_mode == "user_compressed":
        validate_request_evidence(
            contract.get("user_request_evidence"),
            "user_compressed mode",
            root,
            str(plan.get("job", {}).get("id", "")).strip(),
        )
    locked_dimensions = contract.get("locked_visual_dimensions")
    if locked_dimensions != list(LOCKED_VISUAL_DIMENSIONS):
        raise ValueError(
            "replication_fidelity must lock shot order, scene, camera, framing, "
            "action stage/timing, and hard cuts"
        )

    for part in parts:
        for beat_index, beat in enumerate(part.get("beats") or [], start=1):
            context = f"{part['id']} beat {beat_index}"
            source_action = str(beat.get("source_visual_action", "")).strip()
            target_action = str(beat.get("target_visual_action", "")).strip()
            visual_fidelity = beat.get("visual_fidelity")
            if not isinstance(visual_fidelity, dict):
                raise ValueError(f"{context} visual_fidelity is required")
            for field in VISUAL_FIDELITY_FIELDS:
                source_value = str(
                    visual_fidelity.get(f"source_{field}", "")
                ).strip()
                target_value = str(
                    visual_fidelity.get(f"target_{field}", "")
                ).strip()
                if not source_value or not target_value:
                    raise ValueError(
                        f"{context} visual_fidelity requires source_{field} and target_{field}"
                    )
                if normalized_spoken_text(source_value) != normalized_spoken_text(
                    target_value
                ):
                    raise ValueError(f"{context} must preserve source_{field}")
            edits = beat.get("visual_edits")
            if not isinstance(edits, list):
                raise ValueError(f"{context} visual_edits must be a list")
            if normalized_spoken_text(source_action) == normalized_spoken_text(target_action):
                if edits:
                    raise ValueError(f"{context} unchanged visual action must not declare edits")
                continue
            if len(edits) != 1 or not isinstance(edits[0], dict):
                raise ValueError(f"{context} has an undeclared visual rewrite")
            edit = edits[0]
            if normalized_spoken_text(edit.get("from")) != normalized_spoken_text(source_action):
                raise ValueError(f"{context} visual edit from must equal source_visual_action")
            if normalized_spoken_text(edit.get("to")) != normalized_spoken_text(target_action):
                raise ValueError(f"{context} visual edit to must equal target_visual_action")
            reason = str(edit.get("reason", "")).strip()
            if reason not in ALLOWED_VISUAL_EDIT_REASONS:
                raise ValueError(f"{context} visual edit reason is not allowed")
            if not str(edit.get("reason_detail", "")).strip():
                raise ValueError(f"{context} visual edit reason_detail is required")
            if reason == "user_requested":
                validate_request_evidence(
                    edit.get("request_evidence"),
                    f"{context} user_requested visual edit",
                    root,
                    str(plan.get("job", {}).get("id", "")).strip(),
                )
            if reason.startswith("product_") and not str(
                edit.get("profile_evidence", "")
            ).strip():
                raise ValueError(
                    f"{context} product visual edit requires product-profile evidence"
                )
            if edit.get("preserved_dimensions") != list(LOCKED_VISUAL_DIMENSIONS):
                raise ValueError(
                    f"{context} visual edit must preserve every locked visual dimension"
                )

        if duration_mode == "source_length":
            for function in part.get("source_functions") or []:
                if function.get("coverage") == "dropped":
                    raise ValueError(
                        f"{part['id']} source_length replication cannot drop source functions"
                    )


def part_number(value):
    match = re.search(r"(\d+)$", str(value))
    return int(match.group(1)) if match else sys.maxsize


def part_label(part_id):
    number = part_number(part_id)
    return f"Part{number}" if number != sys.maxsize else str(part_id)


def load_job(root, job_id):
    path = root / "jobs.csv"
    if not path.exists():
        raise FileNotFoundError(f"missing jobs.csv: {path}")
    with path.open(newline="", encoding="utf-8-sig") as file:
        for row in csv.DictReader(file):
            if row.get("id") == job_id:
                return row
    raise ValueError(f"job not found in jobs.csv: {job_id}")


def load_manifest(root, job_id, plan=None):
    relative = (
        plan.get("approved_visual_manifest")
        if plan
        else f"output/{job_id}/visual-assets/approved_visual_manifest.json"
    )
    path = resolve_path(root, relative)
    if not path.exists():
        raise FileNotFoundError(f"missing approved visual manifest: {path}")
    manifest = read_json(path)
    if manifest.get("job_id") not in (None, "", job_id):
        raise ValueError(f"manifest job_id does not match {job_id}")
    parts = manifest.get("part_storyboards")
    if not isinstance(parts, dict) or not parts:
        raise ValueError("approved visual manifest has no part_storyboards")
    return path, manifest


def load_model_route(root, plan=None):
    relative = plan.get("model_route_path", "rules/SEEDANCE_MODEL.json") if plan else "rules/SEEDANCE_MODEL.json"
    path = resolve_path(root, relative)
    if not path.exists():
        raise FileNotFoundError(f"missing Seedance model route: {path}")
    route = read_json(path)
    for field in ("model", "task_code", "endpoint"):
        if field not in route:
            raise ValueError(f"Seedance model route is missing {field}")
    return path, route


def manifest_presenter_gender(root, manifest):
    source = str(manifest.get("source_presenter_gender", "")).strip().lower()
    declared_target = str(manifest.get("target_presenter_gender", "")).strip().lower()
    identity_manifest_value = str(manifest.get("identity_group_manifest", "")).strip()
    identity_target = ""
    if identity_manifest_value:
        identity_manifest_path = resolve_path(root, identity_manifest_value)
        if not identity_manifest_path.is_file():
            raise FileNotFoundError(f"missing identity group manifest: {identity_manifest_path}")
        identity_target = str(
            read_json(identity_manifest_path).get("presenter_gender", "")
        ).strip().lower()
    target = identity_target or declared_target
    if declared_target and identity_target and declared_target != identity_target:
        raise ValueError(
            "target presenter gender does not match approved identity manifest: "
            f"visual={declared_target}, identity={identity_target}"
        )
    return {"source": source, "target": target}


def default_asset_role(role):
    if role == "storyboard":
        return {
            "role": "定义为“分镜板”，只控制镜头顺序、景别、动作节奏和场景关系",
            "exclusions": "不传递分镜网格、边框、文字、旧产品及旧人物身份",
        }
    if "identity" in role or role == "afterwash_face":
        if role == "identity_ref":
            alias = "主角"
        elif str(role).startswith("identity_role_"):
            alias = f"角色{str(role).removeprefix('identity_role_')}"
        elif role == "afterwash_face":
            alias = "洁面后人物"
        else:
            alias = "当前角色"
        return {
            "role": f"中的人物定义为“{alias}”，只锁定脸、发型、身体、服装和身份一致性",
            "exclusions": "不传递参考图背景、构图、无关人物或其他角色身份",
        }
    return {
        "role": "中的产品定义为“目标产品”，只锁定包装、标签、结构和材质",
        "exclusions": "不传递白底或棚拍背景，不控制镜头构图、场景、手部位置或动作节奏",
    }


def ordered_reusable_refs(manifest, part_id=None):
    refs = manifest.get("reusable_refs") or {}
    ordered = [(role, refs[role]) for role in REUSABLE_ROLE_ORDER if refs.get(role)]
    ordered.extend(
        (role, value)
        for role, value in refs.items()
        if value and role not in REUSABLE_ROLE_ORDER and role not in IGNORED_REUSABLE_ROLES
    )
    if part_id is not None:
        part_refs = (manifest.get("part_reusable_refs") or {}).get(part_id) or {}
        existing_roles = {role for role, _value in ordered}
        ordered.extend(
            (role, value)
            for role, value in part_refs.items()
            if value and role not in existing_roles and role not in IGNORED_REUSABLE_ROLES
        )
    return ordered


def indexed_asset_specs(specs):
    return [
        (index, role, path)
        for index, (role, path) in enumerate(specs, start=1)
    ]


def validate_part_image_reference_bounds(parts, specs_by_part):
    for part in parts:
        part_id = part["id"]
        image_count = len(specs_by_part[part_id])
        refs = sorted(
            {
                int(value)
                for value in IMAGE_REFERENCE_RE.findall(
                    json.dumps(part, ensure_ascii=False)
                )
            }
        )
        invalid = [index for index in refs if index < 1 or index > image_count]
        if invalid:
            reference = f"@图片{invalid[0]}"
            raise ValueError(
                f"{part_id} references {reference} but only {image_count} image assets exist"
            )


def beat_skeleton(duration=DEFAULT_PART_DURATION):
    scale = float(duration) / DEFAULT_PART_DURATION
    points = tuple(round(point * scale, 6) for point in (0.0, 2.5, 5.0, 7.5, 10.0, 12.5, 15.0))
    shots = (1, 1, 2, 2, 3, 3)
    return [
        {
            "id": f"beat{index + 1}",
            "panel_start": index * 2 + 1,
            "panel_end": index * 2 + 2,
            "shot": shots[index],
            "target_start": points[index],
            "target_end": points[index + 1],
            "source_start": None,
            "source_end": None,
            "source_beat_ids": [],
            "source_visual_action": "",
            "source_speaker_mode": "",
            "source_line": "",
            "target_visual_action": "",
            "visual_fidelity": {
                f"{side}_{field}": ""
                for field in VISUAL_FIDELITY_FIELDS
                for side in ("source", "target")
            },
            "visual_edits": [],
            "sound_effect": "",
            "reference_binding": "",
            "must_keep_reason": "",
        }
        for index in range(6)
    ]


def parse_target_duration(value):
    match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
    return float(match.group(0)) if match else None


def allocate_part_durations(target_duration, part_count):
    total = parse_target_duration(target_duration)
    if not total or part_count < 1:
        return [DEFAULT_PART_DURATION] * part_count
    rounded_total = int(round(total))
    base, remainder = divmod(rounded_total, part_count)
    durations = [base + (1 if index < remainder else 0) for index in range(part_count)]
    if any(duration < MIN_PART_DURATION or duration > MAX_PART_DURATION for duration in durations):
        return [DEFAULT_PART_DURATION] * part_count
    return durations


def build_plan(root, job_id, handoff_mode):
    job = load_job(root, job_id)
    manifest_path, manifest = load_manifest(root, job_id)
    route_path, route = load_model_route(root)
    presenter_gender = manifest_presenter_gender(root, manifest)
    presenter_label = (
        "男主播" if presenter_gender.get("target") == "male" else "女主播"
    )
    asset_roles = {"storyboard": default_asset_role("storyboard")}
    for part_id in manifest["part_storyboards"]:
        for role, _value in ordered_reusable_refs(manifest, part_id):
            asset_roles[role] = default_asset_role(role)

    audio_source = job.get("audio_assets", "")
    if audio_source == "extract_from_original":
        audio_source = job.get("video_path", "")

    sorted_storyboards = sorted(manifest["part_storyboards"].items(), key=lambda item: part_number(item[0]))
    durations = allocate_part_durations(job.get("target_duration"), len(sorted_storyboards))
    parts = []
    for (part_id, storyboard), duration in zip(sorted_storyboards, durations):
        parts.append(
            {
                "id": part_id,
                "duration_seconds": duration,
                "storyboard": storyboard.get("path", ""),
                "main_goal": "",
                "secondary_goal": "",
                "simplify": "",
                "scene_rule": "",
                "seam": {"start_state": "", "end_state": ""},
                "audio": {
                    "source": audio_source,
                    "source_start": None,
                    "source_end": None,
                },
                "beats": beat_skeleton(duration),
                "source_functions": [],
                "speech_groups": [],
                "execution_blocks": [],
            }
        )

    job_fields = (
        "id",
        "product_name",
        "video_path",
        "product_assets",
        "person_assets",
        "audio_assets",
        "target_duration",
        "notes",
        "output_dir",
    )
    source_rhythm_path = root / "output" / job_id / "剧情分析" / "source_rhythm.json"
    if not source_rhythm_path.is_file():
        raise FileNotFoundError(
            f"source_rhythm.json is required for the new replication flow: {source_rhythm_path}"
        )
    source_rhythm_payload = read_json(source_rhythm_path)
    if int(source_rhythm_payload.get("schema_version") or 0) < 3:
        raise ValueError("source_rhythm.json schema_version must be at least 3")
    source_rhythm = {
        "path": display_path(root, source_rhythm_path),
        "analysis_sha256": file_sha256(source_rhythm_path),
        "source_video_sha256": source_rhythm_payload.get("source_sha256", ""),
    }
    source_duration = source_rhythm_payload.get("duration")
    target_duration = parse_target_duration(job.get("target_duration"))
    compressed = (
        isinstance(source_duration, (int, float))
        and target_duration is not None
        and target_duration < float(source_duration) - 0.5
    )
    duration_request_evidence = None
    if compressed:
        intake_path = root / "output" / job_id / "intake.json"
        if not intake_path.is_file():
            raise ValueError(
                "explicit target-duration intake evidence is required before compression"
            )
        intake = read_json(intake_path)
        duration_request = intake.get("target_duration") or {}
        raw_evidence = duration_request.get("request_evidence")
        if (
            intake.get("job_id") != job_id
            or duration_request.get("value") != job.get("target_duration")
            or duration_request.get("explicitly_requested") is not True
            or not isinstance(raw_evidence, dict)
            or raw_evidence.get("source") != "intake"
            or not str(raw_evidence.get("quote", "")).strip()
        ):
            raise ValueError(
                "explicit target-duration intake evidence is required before compression"
            )
        duration_request_evidence = {
            "source": "intake",
            "path": display_path(root, intake_path),
            "sha256": file_sha256(intake_path),
            "quote": str(raw_evidence["quote"]),
        }

    plan = {
        "version": 6,
        "job": {field: job.get(field, "") for field in job_fields},
        "approved_visual_manifest": display_path(root, manifest_path),
        "model_route_path": display_path(root, route_path),
        "model_route": route,
        "handoff_mode": handoff_mode,
        "presenter_gender": presenter_gender,
        "script_fidelity": {"mode": "source_locked"},
        "replication_fidelity": {
            "mode": "source_locked",
            "change_policy": "necessary_only",
            "duration_mode": "user_compressed" if compressed else "source_length",
            "user_request_evidence": duration_request_evidence,
            "locked_visual_dimensions": list(LOCKED_VISUAL_DIMENSIONS),
        },
        "spoken_product_anchor": {"enabled": False},
        "audio_prompt_rule": (
            "@音频1只参考男主播音色和节奏；口播内容只按引号内台词。"
            if presenter_gender.get("target") == "male"
            else "@音频1只参考女主播音色和节奏；口播内容只按引号内台词。"
        ),
        "global_prompt_rules": (
            f"生成约{{duration_seconds}}秒、{route.get('ratio', '9:16')}竖屏、"
            f"{route.get('resolution', '720p')}真实手机短视频。"
            f"按@图片1的Shot顺序和硬切节奏执行；保持同一{presenter_label}和同一服装，"
            "场景严格按对应Shot执行，不继承人物参考图背景，"
            "每镜完成动作后切换，不生成冻结帧或慢动作。"
            "全片无字幕，不生成任何背景音乐，只保留口播、环境声和同步动作音效。"
        ),
        "asset_roles": asset_roles,
        "parts": parts,
    }
    plan["source_rhythm"] = source_rhythm
    return plan


def archive_paths(job_dir, paths, prefix):
    existing = [path for path in paths if path.exists()]
    if not existing:
        return None
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    archive = job_dir / "deprecated" / f"{prefix}_{stamp}"
    for path in existing:
        destination = archive / path.relative_to(job_dir)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(destination))
    return archive


def init_plan(root, job_id, handoff_mode, replace=False):
    job_dir = root / "output" / job_id
    plan_path = job_dir / "seedance" / "director_plan.json"
    if plan_path.exists() and not replace:
        raise ValueError(f"director plan already exists: {plan_path}; use --replace")
    if replace:
        archive_paths(job_dir, [plan_path], "director_plan")
    if handoff_mode == "auto":
        handoff_mode = str(load_job(root, job_id).get("handoff_mode") or "web").strip().lower()
        if handoff_mode not in HANDOFF_MODES:
            handoff_mode = "web"
    plan = build_plan(root, job_id, handoff_mode)
    write_json(plan_path, plan)
    return plan_path


def plan_parts(plan):
    parts = plan.get("parts")
    if not isinstance(parts, list) or not parts:
        raise ValueError("director plan must contain a non-empty parts list")
    return parts


def as_time(value, context):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be numeric")
    return float(value)


def part_duration_seconds(part):
    duration = as_time(
        part.get("duration_seconds", DEFAULT_PART_DURATION),
        f"{part.get('id', 'Part')} duration_seconds",
    )
    if duration < MIN_PART_DURATION or duration > MAX_PART_DURATION:
        raise ValueError(
            f"{part.get('id', 'Part')} duration_seconds must be between "
            f"{MIN_PART_DURATION:g} and {MAX_PART_DURATION:g} seconds"
        )
    return duration


def compact_number(value):
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:g}"


def speaker_mode_kind(value):
    text = str(value or "").strip().lower()
    if any(term in text for term in ("无台词", "不说话", "环境声", "silent", "no dialogue")):
        return "silent"
    if any(term in text for term in ("画外音", "旁白", "voiceover", "voice-over", "narration")):
        return "narration"
    if any(term in text for term in ("群体反应", "群体同期", "group")):
        return "group"
    if any(term in text for term in ("画面内", "同期", "口播", "on-camera", "in-frame", "sync")):
        return "sync"
    return "unknown"


def source_rate_for_part(part):
    spoken_beats = [
        beat
        for beat in part.get("beats", [])
        if speaker_mode_kind(beat.get("source_speaker_mode")) != "silent"
    ]
    if not spoken_beats:
        return None
    start = min(float(beat["source_start"]) for beat in spoken_beats)
    end = max(float(beat["source_end"]) for beat in spoken_beats)
    duration = end - start
    if duration <= 0:
        return None
    units = sum(spoken_units(beat.get("source_line", "")) for beat in spoken_beats)
    return units / duration


def source_total_spoken_units_for_part(part):
    return sum(
        spoken_units(beat.get("source_line", ""))
        for beat in part.get("beats", [])
        if speaker_mode_kind(beat.get("source_speaker_mode")) != "silent"
    )


def allowed_localized_expansion_units_for_part(part):
    return max(0, sum(
        spoken_units(edit.get("to", "")) - spoken_units(edit.get("from", ""))
        for group in part.get("speech_groups", [])
        for edit in group.get("line_edits", [])
        if isinstance(edit, dict)
    ))


def source_pause_seconds_for_part(part):
    return sum(
        max(0.0, float(beat.get("source_pause_after_seconds") or 0.0))
        for beat in part.get("beats", [])
        if speaker_mode_kind(beat.get("source_speaker_mode")) != "silent"
    )


def source_capacity_for_group(group, beat_by_id):
    beats = [beat_by_id[beat_id] for beat_id in group.get("beat_ids", [])]
    source_text = "".join(
        str(beat.get("source_line", ""))
        for beat in beats
    )
    source_units = sum(
        spoken_units(beat.get("source_line", ""))
        for beat in beats
    )
    source_duration = sum(
        max(
            0.0,
            float(beat.get("source_end") or 0.0)
            - float(beat.get("source_start") or 0.0)
            - max(
                0.0,
                float(beat.get("source_pause_after_seconds") or 0.0),
            ),
        )
        for beat in beats
    )
    localized_expansion = max(0, sum(
        spoken_units(edit.get("to", "")) - spoken_units(edit.get("from", ""))
        for edit in group.get("line_edits", [])
        if isinstance(edit, dict)
    ))
    return {
        "source_spoken_units": source_units,
        "source_duration_seconds": source_duration,
        "source_max_sync_units": max(
            (
                spoken_units(sentence)
                for sentence in re.split(r"[。！？!?；;]+", source_text)
                if sentence.strip()
            ),
            default=0,
        ),
        "allowed_localized_expansion_units": localized_expansion,
    }


def source_speech_group_count_for_part(part):
    count = 0
    previous_kind = None
    for beat in part.get("beats", []):
        kind = speaker_mode_kind(beat.get("source_speaker_mode"))
        if kind == "silent":
            previous_kind = None
            continue
        if kind != previous_kind:
            count += 1
        previous_kind = kind
    return count


def source_spoken_beat_count_for_part(part):
    return sum(
        1
        for beat in part.get("beats", [])
        if speaker_mode_kind(beat.get("source_speaker_mode")) != "silent"
    )


def validate_plan(plan, root=None):
    target_presenter_gender = validate_presenter_gender_pair(plan.get("presenter_gender"))
    gender_issues = presenter_gender_text_issues(
        json.dumps(plan, ensure_ascii=False),
        target_presenter_gender,
    )
    if gender_issues:
        raise ValueError("director plan has " + "; ".join(gender_issues))
    parts = plan_parts(plan)
    plan_version = int(plan.get("version", 2))
    if plan_version >= 5:
        script_fidelity = plan.get("script_fidelity")
        if not isinstance(script_fidelity, dict) or script_fidelity.get("mode") != "source_locked":
            raise ValueError("director plan v5 requires script_fidelity.mode=source_locked")
    seen_ids = set()
    for part in parts:
        part_id = str(part.get("id", "")).strip()
        if not part_id or part_id in seen_ids:
            raise ValueError(f"invalid or duplicate Part id: {part_id!r}")
        seen_ids.add(part_id)
        part_duration = part_duration_seconds(part)
        for field in ("main_goal", "secondary_goal", "simplify"):
            if not str(part.get(field, "")).strip():
                raise ValueError(f"{part_id} {field} is required")
        beats = part.get("beats")
        if not isinstance(beats, list) or len(beats) < 3:
            raise ValueError(f"{part_id} must contain at least 3 beats")

        expected_start = 0.0
        expected_panel_start = 1
        shots = set()
        beat_by_id = {}
        for index, beat in enumerate(beats, start=1):
            context = f"{part_id} beat {index}"
            beat_id = str(beat.get("id", "")).strip()
            if not beat_id or beat_id in beat_by_id:
                raise ValueError(f"{context} id must be present and unique")
            beat_by_id[beat_id] = beat
            panel_start = beat.get("panel_start")
            panel_end = beat.get("panel_end")
            if (
                isinstance(panel_start, bool)
                or isinstance(panel_end, bool)
                or not isinstance(panel_start, int)
                or not isinstance(panel_end, int)
                or panel_start != expected_panel_start
                or panel_end < panel_start
            ):
                raise ValueError(f"{part_id} storyboard panels must be continuous from panel 1")
            expected_panel_start = panel_end + 1
            shot = beat.get("shot")
            if isinstance(shot, bool) or shot not in (1, 2, 3):
                raise ValueError(f"{context} shot must be 1, 2, or 3")
            shots.add(shot)
            start = as_time(beat.get("target_start"), f"{context} target_start")
            end = as_time(beat.get("target_end"), f"{context} target_end")
            if abs(start - expected_start) > 1e-6 or end <= start:
                raise ValueError(f"{part_id} target time must be continuous from 0 to 15 seconds")
            expected_start = end

            source_mode = str(beat.get("source_speaker_mode", "")).strip()
            source_kind = speaker_mode_kind(source_mode)
            if source_kind == "unknown":
                raise ValueError(f"{context} source speaker mode is required")
            for field in (
                "source_visual_action",
                "target_visual_action",
                "sound_effect",
                "reference_binding",
                "must_keep_reason",
            ):
                if not str(beat.get(field, "")).strip():
                    raise ValueError(f"{context} {field} is required")
            if beat.get("source_start") is None or beat.get("source_end") is None:
                raise ValueError(f"{context} source time is required")
            if source_kind != "silent" and not str(beat.get("source_line", "")).strip():
                raise ValueError(f"{context} source spoken line is required")

        if shots != {1, 2, 3}:
            raise ValueError(f"{part_id} must contain shots 1, 2, and 3")
        if abs(expected_start - part_duration) > 1e-6:
            raise ValueError(
                f"{part_id} target time must be continuous from 0 to "
                f"{compact_number(part_duration)} seconds"
            )

        execution_blocks = part.get("execution_blocks")
        if plan_version >= 3 and (not isinstance(execution_blocks, list) or not execution_blocks):
            raise ValueError(f"{part_id} execution_blocks must contain 3 to 8 blocks")
        block_by_beat = {}
        if isinstance(execution_blocks, list) and execution_blocks:
            if not 3 <= len(execution_blocks) <= 8:
                raise ValueError(f"{part_id} execution_blocks must contain 3 to 8 blocks")
            seen_block_ids = set()
            flattened = []
            for block_index, block in enumerate(execution_blocks, start=1):
                context = f"{part_id} execution block {block_index}"
                block_id = str(block.get("id", "")).strip()
                beat_ids = block.get("beat_ids")
                if not block_id or block_id in seen_block_ids:
                    raise ValueError(f"{context} id must be present and unique")
                seen_block_ids.add(block_id)
                if not isinstance(beat_ids, list) or not beat_ids:
                    raise ValueError(f"{context} beat_ids must be a non-empty list")
                if any(beat_id not in beat_by_id for beat_id in beat_ids):
                    raise ValueError(f"{context} references an unknown beat id")
                positions = [beats.index(beat_by_id[beat_id]) for beat_id in beat_ids]
                if positions != list(range(min(positions), max(positions) + 1)):
                    raise ValueError(f"{context} beat_ids must be consecutive and ordered")
                first_beat = beat_by_id[beat_ids[0]]
                last_beat = beat_by_id[beat_ids[-1]]
                panel_count = int(last_beat["panel_end"]) - int(first_beat["panel_start"]) + 1
                if panel_count > 5:
                    raise ValueError(f"{context} may cover at most 5 storyboard panels")
                for beat_id in beat_ids:
                    if beat_id in block_by_beat:
                        raise ValueError(f"{part_id} {beat_id} belongs to multiple execution blocks")
                    block_by_beat[beat_id] = block_id
                flattened.extend(beat_ids)
            if flattened != [beat["id"] for beat in beats]:
                raise ValueError(f"{part_id} execution_blocks must cover every beat exactly once in order")

        groups = part.get("speech_groups")
        if not isinstance(groups, list):
            raise ValueError(f"{part_id} speech_groups must be a list")
        assigned = {}
        budget_groups = []
        block_speaker_kinds = {}
        for group_index, group in enumerate(groups, start=1):
            context = f"{part_id} speech group {group_index}"
            group_id = str(group.get("id", "")).strip()
            beat_ids = group.get("beat_ids")
            if not group_id or not isinstance(beat_ids, list) or not beat_ids:
                raise ValueError(f"{context} requires id and beat_ids")
            if any(beat_id not in beat_by_id for beat_id in beat_ids):
                raise ValueError(f"{context} references an unknown beat id")
            positions = [beats.index(beat_by_id[beat_id]) for beat_id in beat_ids]
            if positions != list(range(min(positions), max(positions) + 1)):
                raise ValueError(f"{context} beat_ids must be consecutive and ordered")

            target_mode = str(group.get("speaker_mode", "")).strip()
            target_kind = speaker_mode_kind(target_mode)
            if target_kind in {"unknown", "silent"}:
                raise ValueError(f"{context} speaker mode must be spoken")
            for beat_id in beat_ids:
                if beat_id in assigned:
                    raise ValueError(f"{part_id} {beat_id} belongs to multiple speech groups")
                source_kind = speaker_mode_kind(beat_by_id[beat_id].get("source_speaker_mode"))
                if source_kind != target_kind:
                    raise ValueError(f"{context} must preserve source speaker mode for {beat_id}")
                assigned[beat_id] = group_id
            if block_by_beat:
                group_block_ids = {block_by_beat[beat_id] for beat_id in beat_ids}
                if len(group_block_ids) != 1:
                    raise ValueError(f"{context} must stay inside one execution block")
                block_id = next(iter(group_block_ids))
                block_speaker_kinds.setdefault(block_id, set()).add(target_kind)

            start = as_time(group.get("target_start"), f"{context} target_start")
            end = as_time(group.get("target_end"), f"{context} target_end")
            span_start = float(beat_by_id[beat_ids[0]]["target_start"])
            span_end = float(beat_by_id[beat_ids[-1]]["target_end"])
            if start < span_start - 1e-6 or end > span_end + 1e-6:
                raise ValueError(f"{context} target time must stay inside its bound visual beats")
            budget_groups.append(
                {
                    "id": group_id,
                    "target_start": start,
                    "target_end": end,
                    "speaker_kind": target_kind,
                    "line": group.get("line", ""),
                    **source_capacity_for_group(group, beat_by_id),
                }
            )

        crossing_blocks = [
            block_id
            for block_id, speaker_kinds in block_speaker_kinds.items()
            if len(speaker_kinds) > 1
        ]
        if crossing_blocks:
            raise ValueError(
                f"{part_id} execution block {crossing_blocks[0]} crosses speaker-mode boundaries"
            )

        spoken_beat_ids = {
            beat_id
            for beat_id, beat in beat_by_id.items()
            if speaker_mode_kind(beat.get("source_speaker_mode")) != "silent"
        }
        if set(assigned) != spoken_beat_ids:
            missing = sorted(spoken_beat_ids - set(assigned))
            extra = sorted(set(assigned) - spoken_beat_ids)
            raise ValueError(
                f"{part_id} speech groups must bind every spoken beat exactly once; "
                f"missing={missing}, extra={extra}"
            )
        budget = assess_speech_groups(
            budget_groups,
            part_duration,
            source_units_per_second=source_rate_for_part(part),
            source_speech_group_count=source_speech_group_count_for_part(part),
            source_spoken_beat_count=source_spoken_beat_count_for_part(part),
            source_total_spoken_units=source_total_spoken_units_for_part(part),
            allowed_localized_expansion_units=(
                allowed_localized_expansion_units_for_part(part)
            ),
            source_pause_seconds=source_pause_seconds_for_part(part),
        )
        if budget["overall"] != "PASS":
            raise ValueError(
                f"{part_id} speech budget failed: {', '.join(budget['failed_rules'])}; "
                + "; ".join(budget["details"])
            )

        source_functions = part.get("source_functions")
        if not isinstance(source_functions, list) or not source_functions:
            raise ValueError(f"{part_id} source_functions must be a non-empty list")
        valid_target_refs = set(beat_by_id) | {group["id"] for group in groups}
        seen_function_ids = set()
        for function_index, function in enumerate(source_functions, start=1):
            context = f"{part_id} source function {function_index}"
            function_id = str(function.get("id", "")).strip()
            label = str(function.get("label", "")).strip()
            priority = str(function.get("priority", "")).strip()
            coverage = str(function.get("coverage", "")).strip()
            target_refs = function.get("target_refs")
            if not function_id or function_id in seen_function_ids:
                raise ValueError(f"{context} id must be present and unique")
            seen_function_ids.add(function_id)
            if not label:
                raise ValueError(f"{context} label is required")
            if priority not in {"must_keep", "mergeable", "removable"}:
                raise ValueError(f"{context} priority must be must_keep, mergeable, or removable")
            if coverage not in {"speech", "visual", "both", "dropped"}:
                raise ValueError(f"{context} coverage must be speech, visual, both, or dropped")
            if not isinstance(target_refs, list):
                raise ValueError(f"{context} target_refs must be a list")
            if priority == "must_keep" and coverage == "dropped":
                raise ValueError(f"{part_id} must_keep source function {function_id} cannot be dropped")
            if priority == "mergeable" and coverage == "dropped":
                raise ValueError(f"{part_id} mergeable source function {function_id} needs target coverage")
            if coverage == "dropped" and target_refs:
                raise ValueError(f"{context} dropped coverage cannot have target_refs")
            if coverage != "dropped" and not target_refs:
                raise ValueError(f"{context} covered function requires target_refs")
            unknown_refs = sorted(set(target_refs) - valid_target_refs)
            if unknown_refs:
                raise ValueError(f"{context} has unknown target_refs: {unknown_refs}")

        audio = part.get("audio") or {}
        has_start = audio.get("source_start") is not None
        has_end = audio.get("source_end") is not None
        if has_start != has_end:
            raise ValueError(f"{part_id} audio requires both source_start and source_end")
        if has_start:
            start = as_time(audio["source_start"], f"{part_id} audio source_start")
            end = as_time(audio["source_end"], f"{part_id} audio source_end")
            if end <= start:
                raise ValueError(f"{part_id} audio source_end must be after source_start")
            if not str(audio.get("source", "")).strip():
                raise ValueError(f"{part_id} audio source is required")

    anchor = plan.get("spoken_product_anchor")
    if plan_version >= 3 and not isinstance(anchor, dict):
        raise ValueError("spoken_product_anchor is required")
    if isinstance(anchor, dict):
        enabled = anchor.get("enabled", True)
        if enabled is not True:
            if enabled is not False or set(anchor) != {"enabled"}:
                raise ValueError(
                    "disabled spoken_product_anchor must be exactly {'enabled': false}"
                )
            anchor = None
    if isinstance(anchor, dict):
        full_name = str(anchor.get("full_name", "")).strip()
        anchor_part_id = str(anchor.get("part_id", "")).strip()
        anchor_group_id = str(anchor.get("speech_group_id", "")).strip()
        if not all((full_name, anchor_part_id, anchor_group_id)):
            raise ValueError(
                "spoken_product_anchor requires full_name, part_id, and speech_group_id"
            )
        job_product_name = str(plan.get("job", {}).get("product_name", "")).strip()
        if full_name != job_product_name:
            raise ValueError("spoken_product_anchor full_name must equal the job product_name")
        all_groups = [
            (part["id"], group)
            for part in parts
            for group in part.get("speech_groups", [])
        ]
        anchor_matches = [
            (part_id, group)
            for part_id, group in all_groups
            if part_id == anchor_part_id and group.get("id") == anchor_group_id
        ]
        if len(anchor_matches) != 1:
            raise ValueError("spoken_product_anchor must reference exactly one speech group")
        anchor_group = anchor_matches[0][1]
        anchor_line = str(anchor_group.get("line", "")).strip()
        if full_name not in anchor_line:
            raise ValueError("spoken_product_anchor speech group must contain the full product name")
        anchor_part = next(part for part in parts if part["id"] == anchor_part_id)
        anchor_beats = {
            beat["id"]: beat for beat in anchor_part.get("beats", [])
        }
        if not any(
            "@图片2" in str(anchor_beats[beat_id].get("reference_binding", ""))
            for beat_id in anchor_group.get("beat_ids", [])
        ):
            raise ValueError("spoken_product_anchor must be bound to a product-reference beat")
    if plan_version >= 6:
        validate_replication_fidelity(plan, parts, root)
    if plan_version >= 5:
        validate_script_fidelity(plan, parts, root)
    return parts


def cut_audio_segment(source, output, source_start, source_end, runner=None):
    start = float(source_start)
    duration = min(float(source_end) - start, MAX_AUDIO_SECONDS)
    if duration <= 0:
        raise ValueError("audio source_end must be after source_start")
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(source),
        "-t",
        f"{duration:.3f}",
        "-vn",
        "-codec:a",
        "libmp3lame",
        str(output),
    ]
    (runner or subprocess.run)(command, check=True, capture_output=True, text=True)
    return output


def format_time(value):
    number = float(value)
    return f"{number:.1f}"


def time_range(beat, prefix="target"):
    return f"{format_time(beat[f'{prefix}_start'])}-{format_time(beat[f'{prefix}_end'])}秒"


def markdown_cell(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def speaker_text(mode, line, delivery_note=None):
    mode = str(mode).strip()
    line = str(line or "").strip()
    note = str(delivery_note or "").strip()
    if note:
        mode = f"{mode}（{note}）"
    return f"{mode}：“{line}”" if line else mode


def model_speaker_text(mode, line, delivery_note=None):
    """Render compact, model-facing dialogue while keeping rich modes in plan/QC artifacts."""
    raw_mode = str(mode or "").strip()
    line = str(line or "").strip()
    note = str(delivery_note or "").strip()
    kind = speaker_mode_kind(raw_mode)
    if kind == "narration":
        label = "旁白"
    elif kind == "sync":
        label = raw_mode
    elif kind == "group":
        label = "众人说"
    elif kind == "silent":
        return "无台词"
    else:
        label = raw_mode or "人物说"
    if note:
        label = f"{label}（{note}）"
    return f"{label}{{{line}}}" if line else label


def model_sound_effect_text(value):
    effect = str(value or "").strip().rstrip("。；")
    empty_labels = {"无", "无音效", "无额外音效"}
    effects = [
        item.strip()
        for item in re.split(r"[；;]", effect)
        if item.strip() and item.strip() not in empty_labels
    ]
    if not effects:
        return ""
    return "；".join(f"<{item}>" for item in effects)


def group_by_beat(part):
    result = {}
    for group in part.get("speech_groups", []):
        for beat_id in group.get("beat_ids", []):
            result[beat_id] = group
    return result


def speech_time_range(group):
    return f"{format_time(group['target_start'])}-{format_time(group['target_end'])}秒"


def panel_range(start_or_beat, end=None):
    if isinstance(start_or_beat, dict):
        start = int(start_or_beat["panel_start"])
        end = int(start_or_beat["panel_end"])
    else:
        start = int(start_or_beat)
        end = int(end)
    return f"分镜{start}" if start == end else f"分镜{start}-{end}"


def speech_panel_range(part, group):
    beats = {beat["id"]: beat for beat in part["beats"]}
    first = beats[group["beat_ids"][0]]
    last = beats[group["beat_ids"][-1]]
    return panel_range(first["panel_start"], last["panel_end"])


def model_shot_range(start, end):
    start = int(start)
    end = int(end)
    return f"Shot {start:02d}" if start == end else f"Shot {start:02d}–{end:02d}"


def model_time_range(first_beat, last_beat):
    return f"{format_time(first_beat['target_start'])}–{format_time(last_beat['target_end'])}秒"


def join_prompt_items(values):
    items = [
        str(value).strip().rstrip("。；")
        for value in values
        if str(value or "").strip()
    ]
    return "；".join(items) + "。"


def prompt_blocks(part):
    beats = part["beats"]
    beat_by_id = {beat["id"]: beat for beat in beats}
    execution_blocks = part.get("execution_blocks") or []
    if execution_blocks:
        groups = part.get("speech_groups", [])
        return [
            (
                [beat_by_id[beat_id] for beat_id in block["beat_ids"]],
                [
                    group
                    for group in groups
                    if set(group.get("beat_ids", [])).issubset(set(block["beat_ids"]))
                ],
            )
            for block in execution_blocks
        ]
    groups = group_by_beat(part)
    consumed = set()
    blocks = []
    for beat in beats:
        if beat["id"] in consumed:
            continue
        group = groups.get(beat["id"])
        if group:
            block_beats = [beat_by_id[beat_id] for beat_id in group["beat_ids"]]
            consumed.update(group["beat_ids"])
        else:
            block_beats = [beat]
            consumed.add(beat["id"])
        blocks.append((block_beats, [group] if group else []))
    return blocks


def render_voiceover(job_id, parts):
    lines = ["# Voiceover Script", "", f"Job: {job_id}", "Stage: pre_seedance_pack"]
    for part in parts:
        lines.extend(["", f"## {part_label(part['id'])} Script", ""])
        for group in part["speech_groups"]:
            lines.append(f"{speech_time_range(group)} {speaker_text(group['speaker_mode'], group['line'])}")
        lines.append("其余时间无台词，只留环境声和操作声。")
    return "\n".join(lines)


def render_source_script_fidelity(job_id, plan, parts):
    mode = str((plan.get("script_fidelity") or {}).get("mode", "legacy"))
    lines = [
        "# Source Script Fidelity",
        "",
        f"Job: {job_id}",
        "Stage: pre_seedance_pack",
        f"Mode: `{mode}`",
        "",
        "| Part | Speech group | Source line | Declared line edits | Target line |",
        "|---|---|---|---|---|",
    ]
    for part in parts:
        beats = {beat["id"]: beat for beat in part["beats"]}
        for group in part["speech_groups"]:
            source_line = "".join(
                str(beats[beat_id].get("source_line", ""))
                for beat_id in group["beat_ids"]
            )
            edit_summary = "; ".join(
                f"{edit.get('kind')}:{edit.get('reason')}:{edit.get('from')}→{edit.get('to', '')}"
                for edit in group.get("line_edits", [])
            ) or "exact"
            cells = [
                part_label(part["id"]),
                group["id"],
                source_line,
                edit_summary,
                group["line"],
            ]
            lines.append("| " + " | ".join(markdown_cell(cell) for cell in cells) + " |")
    return "\n".join(lines)


def render_source_replication_fidelity(job_id, plan, parts):
    contract = plan.get("replication_fidelity") or {}
    lines = [
        "# Source Replication Fidelity",
        "",
        f"Job: {job_id}",
        "Stage: pre_seedance_pack",
        f"Mode: `{contract.get('mode', 'legacy')}`",
        f"Change policy: `{contract.get('change_policy', 'legacy')}`",
        f"Duration mode: `{contract.get('duration_mode', 'legacy')}`",
        "",
        "| Part | Beat | Source action | Declared visual edit | Target action | Locked dimensions |",
        "|---|---|---|---|---|---|",
    ]
    for part in parts:
        for beat in part.get("beats") or []:
            edit_summary = "; ".join(
                f"{edit.get('reason')}:{edit.get('from')}→{edit.get('to')}"
                for edit in beat.get("visual_edits") or []
            ) or "exact"
            cells = [
                part_label(part["id"]),
                beat["id"],
                beat.get("source_visual_action", ""),
                edit_summary,
                beat.get("target_visual_action", ""),
                ", ".join(contract.get("locked_visual_dimensions") or []),
            ]
            lines.append("| " + " | ".join(markdown_cell(cell) for cell in cells) + " |")
    return "\n".join(lines)


def render_shot_line_map(job_id, parts):
    lines = ["# Shot-Line Map", "", f"Job: {job_id}", "Stage: pre_seedance_pack"]
    header = (
        "| Target time | Storyboard panels | Source time | Source visual action | Source speaker mode / line | "
        "Target visual action | Sound effect | Speech group | Speech time | Target speaker mode / line | "
        "Reference binding | Must-keep reason |"
    )
    separator = "|---|---|---|---|---|---|---|---|---|---|---|---|"
    for part in parts:
        beat_groups = group_by_beat(part)
        lines.extend(["", f"## {part_label(part['id'])}", "", header, separator])
        for beat in part["beats"]:
            source_time = ""
            if beat.get("source_start") is not None and beat.get("source_end") is not None:
                source_time = time_range(beat, "source")
            group = beat_groups.get(beat["id"])
            first_group_beat = bool(group and group["beat_ids"][0] == beat["id"])
            target_speech = "无台词，只留环境声"
            if group:
                target_speech = (
                    speaker_text(
                        group["speaker_mode"],
                        group["line"],
                        group.get("delivery_note"),
                    )
                    if first_group_beat
                    else f"{group['speaker_mode']}（{group['id']}承接，无新增台词）"
                )
            cells = [
                time_range(beat),
                panel_range(beat),
                source_time,
                beat.get("source_visual_action", ""),
                speaker_text(beat["source_speaker_mode"], beat.get("source_line")),
                beat.get("target_visual_action", ""),
                beat.get("sound_effect", ""),
                group.get("id", "") if group else "",
                speech_time_range(group) if first_group_beat else "",
                target_speech,
                beat.get("reference_binding", ""),
                beat.get("must_keep_reason", ""),
            ]
            lines.append("| " + " | ".join(markdown_cell(cell) for cell in cells) + " |")
    return "\n".join(lines)


def render_replication_function_coverage(job_id, parts):
    lines = [
        "# Replication Function Coverage",
        "",
        f"Job: {job_id}",
        "Stage: pre_seedance_pack",
        "",
        "容量 PASS 只说明说得下；本表由独立 checker 核对原片功能是否真的保住。",
    ]
    for part in parts:
        lines.extend(
            [
                "",
                f"## {part_label(part['id'])}",
                "",
                "| Function | Priority | Coverage | Target evidence |",
                "|---|---|---|---|",
            ]
        )
        for function in part["source_functions"]:
            cells = [
                function["label"],
                function["priority"],
                function["coverage"],
                ", ".join(function["target_refs"]),
            ]
            lines.append("| " + " | ".join(markdown_cell(cell) for cell in cells) + " |")
    return "\n".join(lines)


def render_seam_design(job_id, parts):
    lines = ["# Seam Design", "", f"Job: {job_id}", "Stage: pre_seedance_pack"]
    if len(parts) == 1:
        lines.extend(["", "No inter-Part boundary."])
    for previous, following in zip(parts, parts[1:]):
        lines.extend(
            [
                "",
                f"## {part_label(previous['id'])} -> {part_label(following['id'])}",
                "",
                f"- Previous end state: {previous.get('seam', {}).get('end_state', '')}",
                f"- Next start state: {following.get('seam', {}).get('start_state', '')}",
                "- Boundary mode: Independent hard cut; each Part is a self-contained Seedance task.",
                "- The next Part does not inherit the previous Part's final-frame pose, scene, framing, or unfinished motion.",
                "- Identity and product consistency come from each Part's own approved references and prompt.",
                "- Do not freeze the final or opening frame.",
            ]
        )
    return "\n".join(lines)


def asset_specs(root, manifest, part_id):
    storyboard = manifest["part_storyboards"].get(part_id)
    if not isinstance(storyboard, dict) or not storyboard.get("path"):
        raise ValueError(f"manifest is missing storyboard path for {part_id}")
    specs = [("storyboard", resolve_path(root, storyboard["path"]))]
    for role, value in ordered_reusable_refs(manifest, part_id):
        if value:
            specs.append((role, resolve_path(root, value)))
    for role, path in specs:
        if not path.is_file():
            raise FileNotFoundError(f"missing approved {role} asset: {path}")
    return specs


def role_label(role):
    if str(role).startswith("identity_"):
        return f"人物身份_{role.removeprefix('identity_')}"
    return ROLE_LABELS.get(role, re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff-]", "_", role))


def asset_placeholder(part_id, index, role):
    clean_role = re.sub(r"[^0-9A-Za-z]+", "_", role).strip("_").upper() or "IMAGE"
    return f"asset://UPLOAD_{part_id.upper()}_{index:02d}_{clean_role}"


def render_material_roles(job_id, parts, specs_by_part, route, plan):
    roles = plan.get("asset_roles") or {}
    lines = [
        "# Seedance 素材角色表",
        "",
        f"Job: {job_id}",
        "Stage: pre_seedance_pack",
        f"Model route: {route.get('model_name', '')} / `{route['model']}`",
        f"Mode: {plan['handoff_mode']}",
    ]
    for part in parts:
        lines.extend(
            [
                "",
                f"## {part_label(part['id'])}",
                "",
                "| Upload label | Manifest role | Source | Role | Exclusions |",
                "|---|---|---|---|---|",
            ]
        )
        for index, role, path_value in indexed_asset_specs(specs_by_part[part["id"]]):
            detail = roles.get(role) or default_asset_role(role)
            cells = [
                f"@图片{index}",
                role,
                f"`{path_value}`",
                detail.get("role", ""),
                detail.get("exclusions", ""),
            ]
            lines.append("| " + " | ".join(markdown_cell(cell) for cell in cells) + " |")
    return "\n".join(lines)


def render_prompt(plan, part, specs_by_part, route):
    roles = plan.get("asset_roles") or {}
    lines = ["参考图角色："]
    for index, role, _value in indexed_asset_specs(specs_by_part[part["id"]]):
        detail = roles.get(role) or default_asset_role(role)
        description = "；".join(
            item
            for item in (
                str(detail.get("role", "")).strip(),
                str(detail.get("exclusions", "")).strip(),
            )
            if item
        )
        lines.append(f"@图片{index}{description}。")
    audio_rule = str(plan.get("audio_prompt_rule", "")).strip()
    part_audio = part.get("audio") or {}
    if audio_rule and part_audio.get("source_start") is not None:
        lines.append(audio_rule)
    global_rules = str(plan.get("global_prompt_rules", ""))
    global_rules = global_rules.replace(
        "{duration_seconds}", compact_number(part_duration_seconds(part))
    )
    scene_rule = str(part.get("scene_rule", "")).strip().rstrip("。；")
    if scene_rule:
        global_rules = f"{global_rules.rstrip('。；')}；{scene_rule}。"
    lines.extend(
        [
            "",
            global_rules,
        ]
    )
    for beats, groups in prompt_blocks(part):
        first = beats[0]
        last = beats[-1]
        visual = join_prompt_items(beat.get("target_visual_action") for beat in beats)
        sound_effect = join_prompt_items(beat.get("sound_effect") for beat in beats)
        model_sound_effect = model_sound_effect_text(sound_effect)
        voice = (
            "；".join(
                model_speaker_text(
                    group["speaker_mode"],
                    group["line"],
                    group.get("delivery_note"),
                ).rstrip("。")
                for group in groups
            )
            if groups
            else "无台词"
        )
        block_lines = [
            "",
            f"{model_time_range(first, last)}｜{model_shot_range(first['panel_start'], last['panel_end'])}",
            f"画面：{visual}",
            f"声音：{voice.rstrip('。')}。",
        ]
        if model_sound_effect:
            block_lines.append(f"音效：{model_sound_effect}")
        lines.extend(block_lines)
    return "\n".join(lines)


def managed_outputs(job_dir, parts):
    paths = [
        job_dir / "voiceover" / "voiceover.md",
        job_dir / "voiceover" / "source_script_fidelity.md",
        job_dir / "voiceover" / "source_replication_fidelity.md",
        job_dir / "voiceover" / "shot_line_map.md",
        job_dir / "voiceover" / "replication_function_coverage.md",
        job_dir / "seam" / "seam_design.md",
        job_dir / "seedance" / "seedance_素材角色表.md",
        job_dir / "seedance" / "part_compilation_manifest.json",
        job_dir / "seedance" / "handoff_mode.json",
        job_dir / "seedance" / "requests",
        job_dir / "seedance_web_final",
        job_dir / "audio-boundary",
    ]
    paths.extend(job_dir / "seedance" / f"seedance_{part['id']}_prompt.txt" for part in parts)
    return paths


def prepare_audio(root, job_dir, parts):
    outputs = {}
    for part in parts:
        audio = part.get("audio") or {}
        if audio.get("source_start") is None:
            continue
        source = resolve_path(root, audio["source"])
        if not source.is_file():
            raise FileNotFoundError(f"missing audio source for {part['id']}: {source}")
        output = job_dir / "audio-boundary" / f"{part['id']}_reference_audio.mp3"
        cut_audio_segment(source, output, audio["source_start"], audio["source_end"])
        if not output.is_file():
            raise RuntimeError(f"ffmpeg did not create audio output: {output}")
        outputs[part["id"]] = output
    return outputs


def render_audio_boundary(job_id, parts, audio_outputs):
    lines = ["# Audio Boundary QC", "", f"Job: {job_id}", "Stage: pre_seedance_pack"]
    if not audio_outputs:
        lines.extend(["", "No reference audio requested for this job."])
        return "\n".join(lines)
    lines.extend(["", "## Source Cuts", ""])
    for part in parts:
        if part["id"] not in audio_outputs:
            continue
        audio = part["audio"]
        duration = min(float(audio["source_end"]) - float(audio["source_start"]), MAX_AUDIO_SECONDS)
        lines.append(
            f"- {part_label(part['id'])}: {float(audio['source_start']):.2f}s to "
            f"{float(audio['source_start']) + duration:.2f}s -> `{audio_outputs[part['id']]}` ({duration:.2f}s)."
        )
    lines.extend(
        [
            "",
            "Every cut is capped at 14.90s. Run tools/audio_duration_qc.py before gate PASS.",
            "Reference audio controls voice texture, cadence, pauses, and ambience only; target lines come from director_plan.json.",
        ]
    )
    return "\n".join(lines)


def copy_web_handoff(root, job_dir, job_id, parts, specs_by_part, prompts, audio_outputs, route):
    final_dir = job_dir / "seedance_web_final"
    uploads_by_part = {}
    for part in parts:
        uploads_by_part[part["id"]] = write_web_part(
            final_dir,
            part,
            specs_by_part[part["id"]],
            prompts[part["id"]],
            audio_outputs.get(part["id"]),
        )
    write_web_upload_order(final_dir, job_id, parts, uploads_by_part, route)
    return final_dir


def write_web_part(final_dir, part, specs, prompt, audio_output):
    prompt_dir = final_dir / "prompts"
    label = part_label(part["id"])
    part_dir = final_dir / f"{label}_上传素材"
    canonical_prompt = prompt_dir / f"{label}_Seedance_prompt.txt"
    local_prompt = part_dir / f"00_{label}_Seedance_prompt.txt"
    write_text(canonical_prompt, prompt)
    write_text(local_prompt, prompt)
    uploads = []
    for index, role, source in indexed_asset_specs(specs):
        upload_index = index if index <= 5 else index + 1
        destination = part_dir / f"{upload_index:02d}_{label}_{role_label(role)}{source.suffix.lower()}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        uploads.append(destination.relative_to(final_dir).as_posix())
    if audio_output is not None:
        destination = part_dir / f"06_{label}_声音参考.mp3"
        shutil.copy2(audio_output, destination)
        uploads.append(destination.relative_to(final_dir).as_posix())
    return uploads


def write_web_upload_order(final_dir, job_id, parts, uploads_by_part, route):
    upload_order = [
        "# Web-Side Seedance Upload Order",
        "",
        f"Job: {job_id}",
        "Stop point: before Seedance generation",
    ]
    for part in parts:
        label = part_label(part["id"])
        upload_order.extend(
            [
                "",
                f"## {label}",
                "",
                f"Prompt: `prompts/{label}_Seedance_prompt.txt`",
                "",
                "Upload assets in this order:",
                "",
            ]
        )
        upload_order.extend(
            f"{index}. `{path}`"
            for index, path in enumerate(uploads_by_part[part["id"]], start=1)
        )

    upload_order.extend(
        [
            "",
            "## Route",
            "",
            f"- Model: {route.get('model_name', '')}",
            f"- Model EP: `{route['model']}`",
            f"- Ratio: `{route.get('ratio', '9:16')}`",
            "- Duration: `"
            + ", ".join(
                f"{part_label(part['id'])}={compact_number(part_duration_seconds(part))}s"
                for part in parts
            )
            + "`",
            f"- Resolution: `{route.get('resolution', '720p')}`",
            "- Prepared only. Do not submit generation without approval.",
        ]
    )
    write_text(final_dir / "UPLOAD_ORDER.md", "\n".join(upload_order))


def write_api_requests(root, job_dir, job_id, parts, specs_by_part, prompts, audio_outputs, route):
    request_paths = []
    for part in parts:
        request = build_api_request(
            root,
            job_dir,
            part,
            specs_by_part[part["id"]],
            prompts[part["id"]],
            part["id"] in audio_outputs,
            route,
        )
        path = job_dir / "seedance" / "requests" / f"{part['id']}_request_prepared.json"
        write_json(path, request)
        request_paths.append(path)
    return request_paths


def build_api_request(root, job_dir, part, specs, prompt, has_audio, route):
    content = [{"type": "text", "text": prompt}]
    for index, role, _source in indexed_asset_specs(specs):
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": asset_placeholder(part["id"], index, role)},
                "role": "reference_image",
            }
        )
    if has_audio:
        content.append(
            {
                "type": "audio_url",
                "audio_url": {"url": asset_placeholder(part["id"], 1, "reference_audio")},
                "role": "reference_audio",
            }
        )
    param = {
        route.get("request_field", "model"): route["model"],
        "content": content,
        "generate_audio": bool(route.get("generate_audio", True)),
        "ratio": route.get("ratio", "9:16"),
        "duration": int(math.ceil(part_duration_seconds(part))),
        "resolution": route.get("resolution", "720p"),
        "watermark": False,
    }
    return build_taskcode_request(
        param,
        task_code=route["task_code"],
        url=TASK_CREATE_URL,
        metadata={
            "endpoint": route["endpoint"],
            "prepared_only": True,
            "do_not_submit": True,
            "asset_binding_note": (
                "Activate approved manifest assets and replace asset:// "
                "placeholders before submission."
            ),
            "prompt_file": display_path(
                root,
                job_dir / "seedance" / f"seedance_{part['id']}_prompt.txt",
            ),
        },
    )


def compile_part_packet(
    root,
    job_dir,
    plan,
    part,
    specs,
    route,
    mode,
    packet_dir,
    audio_runner=None,
):
    prompt = render_prompt(plan, part, {part["id"]: specs}, route)
    prompt_path = packet_dir / "seedance" / f"seedance_{part['id']}_prompt.txt"
    write_text(prompt_path, prompt)
    audio_output = None
    audio = part.get("audio") or {}
    if audio.get("source_start") is not None:
        source = resolve_path(root, audio["source"])
        audio_output = (
            packet_dir / "audio-boundary" / f"{part['id']}_reference_audio.mp3"
        )
        cut_audio_segment(
            source,
            audio_output,
            audio["source_start"],
            audio["source_end"],
            runner=audio_runner,
        )
        if not audio_output.is_file():
            raise RuntimeError(f"ffmpeg did not create audio output: {audio_output}")

    metadata = {
        "prompt_path": prompt_path.relative_to(packet_dir).as_posix(),
        "audio_path": (
            audio_output.relative_to(packet_dir).as_posix()
            if audio_output is not None
            else None
        ),
        "web_uploads": [],
        "request_path": None,
    }
    if mode in ("web", "both"):
        metadata["web_uploads"] = write_web_part(
            packet_dir / "seedance_web_final",
            part,
            specs,
            prompt,
            audio_output,
        )
    if mode in ("api", "both"):
        request_path = (
            packet_dir
            / "seedance"
            / "requests"
            / f"{part['id']}_request_prepared.json"
        )
        write_json(
            request_path,
            build_api_request(
                root,
                job_dir,
                part,
                specs,
                prompt,
                audio_output is not None,
                route,
            ),
        )
        metadata["request_path"] = request_path.relative_to(packet_dir).as_posix()
    return metadata


def render_plan(root, job_id, handoff_mode=None, replace=False):
    job_dir = root / "output" / job_id
    plan_path = job_dir / "seedance" / "director_plan.json"
    if not plan_path.exists():
        raise FileNotFoundError(f"missing director plan: {plan_path}; run init first")
    plan = read_json(plan_path)
    if plan.get("job", {}).get("id") not in (None, "", job_id):
        raise ValueError(f"director plan job id does not match {job_id}")
    if handoff_mode is not None:
        plan = dict(plan)
        plan["handoff_mode"] = handoff_mode
    mode = plan.get("handoff_mode")
    if mode not in HANDOFF_MODES:
        raise ValueError(f"handoff_mode must be one of: {', '.join(HANDOFF_MODES)}")

    if int(plan.get("version") or 0) >= 6:
        binding = plan.get("source_rhythm")
        if not isinstance(binding, dict):
            raise ValueError("director plan v6 requires a current source_rhythm binding")
        source_rhythm_path = resolve_path(root, binding.get("path", ""))
        if not source_rhythm_path.is_file():
            raise FileNotFoundError(
                f"source_rhythm.json is required for render: {source_rhythm_path}"
            )
        if file_sha256(source_rhythm_path) != str(binding.get("analysis_sha256", "")):
            raise ValueError("director plan source_rhythm binding is stale")
        source_rhythm_payload = read_json(source_rhythm_path)
        if int(source_rhythm_payload.get("schema_version") or 0) < 3:
            raise ValueError("source_rhythm.json schema_version must be at least 3")

    parts = validate_plan(plan, root)
    manifest_path, manifest = load_manifest(root, job_id, plan)
    manifest_gender = manifest_presenter_gender(root, manifest)
    if plan.get("presenter_gender") != manifest_gender:
        raise ValueError(
            "director plan presenter_gender does not match approved visual manifest: "
            f"plan={plan.get('presenter_gender')}, manifest={manifest_gender}"
        )
    route_path, route = load_model_route(root, plan)
    manifest_part_ids = set(manifest["part_storyboards"])
    plan_part_ids = {part["id"] for part in parts}
    if manifest_part_ids != plan_part_ids:
        raise ValueError("director plan Parts must exactly match approved visual manifest Parts")
    specs_by_part = {part["id"]: asset_specs(root, manifest, part["id"]) for part in parts}
    validate_part_image_reference_bounds(parts, specs_by_part)
    for part in parts:
        audio = part.get("audio") or {}
        if audio.get("source_start") is not None:
            source = resolve_path(root, audio["source"])
            if not source.is_file():
                raise FileNotFoundError(f"missing audio source for {part['id']}: {source}")

    existing = [path for path in managed_outputs(job_dir, parts) if path.exists()]
    if existing and not replace:
        joined = ", ".join(str(path) for path in existing)
        raise ValueError(f"rendered output already exists: {joined}; use --replace")
    if replace:
        archive_paths(job_dir, managed_outputs(job_dir, parts), "pre_seedance_pack")

    write_text(job_dir / "voiceover" / "voiceover.md", render_voiceover(job_id, parts))
    write_text(
        job_dir / "voiceover" / "source_script_fidelity.md",
        render_source_script_fidelity(job_id, plan, parts),
    )
    write_text(
        job_dir / "voiceover" / "source_replication_fidelity.md",
        render_source_replication_fidelity(job_id, plan, parts),
    )
    write_text(job_dir / "voiceover" / "shot_line_map.md", render_shot_line_map(job_id, parts))
    write_text(
        job_dir / "voiceover" / "replication_function_coverage.md",
        render_replication_function_coverage(job_id, parts),
    )
    write_text(job_dir / "seam" / "seam_design.md", render_seam_design(job_id, parts))
    write_text(
        job_dir / "seedance" / "seedance_素材角色表.md",
        render_material_roles(job_id, parts, specs_by_part, route, plan),
    )
    frozen_inputs = [plan_path, manifest_path, route_path]
    if int(plan.get("version") or 0) >= 6:
        frozen_inputs.append(source_rhythm_path)
    for specs in specs_by_part.values():
        frozen_inputs.extend(source for _role, source in specs)
    for part in parts:
        audio = part.get("audio") or {}
        if audio.get("source_start") is not None:
            frozen_inputs.append(resolve_path(root, audio["source"]))
    frozen_inputs = list(dict.fromkeys(path.resolve() for path in frozen_inputs))
    parts_by_id = {part["id"]: part for part in parts}
    compiled_parts = compile_and_merge(
        job_dir,
        [part["id"] for part in parts],
        lambda part_id, packet_dir: compile_part_packet(
            root,
            job_dir,
            plan,
            parts_by_id[part_id],
            specs_by_part[part_id],
            route,
            mode,
            packet_dir,
        ),
        max_workers=PART_COMPILER_MAX_WORKERS,
        frozen_inputs=frozen_inputs,
    )
    compiler_manifest = {
        "version": 1,
        "job_id": job_id,
        "director_plan": display_path(root, plan_path),
        "director_plan_sha256": file_sha256(plan_path),
        "frozen_inputs": [
            {
                "path": display_path(root, path),
                "sha256": file_sha256(path),
            }
            for path in frozen_inputs
        ],
        "parts": [
            {
                "part_id": compiled.part_id,
                "metadata": compiled.metadata,
                "files": [
                    {
                        "path": compiled_file.relative_path,
                        "sha256": compiled_file.sha256,
                    }
                    for compiled_file in compiled.files
                ],
            }
            for compiled in compiled_parts
        ],
    }
    write_json(
        job_dir / "seedance" / "part_compilation_manifest.json",
        compiler_manifest,
    )
    audio_outputs = {
        compiled.part_id: job_dir / compiled.metadata["audio_path"]
        for compiled in compiled_parts
        if compiled.metadata.get("audio_path")
    }
    write_text(
        job_dir / "audio-boundary" / "audio_boundary_qc.md",
        render_audio_boundary(job_id, parts, audio_outputs),
    )
    web_dir = None
    request_paths = [
        job_dir / compiled.metadata["request_path"]
        for compiled in compiled_parts
        if compiled.metadata.get("request_path")
    ]
    if mode in ("web", "both"):
        web_dir = job_dir / "seedance_web_final"
        write_web_upload_order(
            web_dir,
            job_id,
            parts,
            {
                compiled.part_id: compiled.metadata["web_uploads"]
                for compiled in compiled_parts
            },
            route,
        )

    handoff = {
        "version": 1,
        "job_id": job_id,
        "mode": mode,
        "handoff_mode": mode,
        "prepared_only": True,
        "do_not_submit": True,
        "director_plan": display_path(root, plan_path),
        "source_script_fidelity": display_path(
            root, job_dir / "voiceover" / "source_script_fidelity.md"
        ),
        "source_replication_fidelity": display_path(
            root, job_dir / "voiceover" / "source_replication_fidelity.md"
        ),
        "replication_function_coverage": display_path(
            root, job_dir / "voiceover" / "replication_function_coverage.md"
        ),
        "web_handoff": display_path(root, web_dir) if web_dir else None,
        "api_requests": [display_path(root, path) for path in request_paths],
        "audio_parts": sorted(audio_outputs, key=part_number),
        "model_route": route,
    }
    handoff_path = job_dir / "seedance" / "handoff_mode.json"
    write_json(handoff_path, handoff)
    return handoff_path


def add_common_arguments(parser):
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--replace", action="store_true")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    init_parser = subparsers.add_parser("init", help="create a director_plan.json skeleton")
    add_common_arguments(init_parser)
    init_parser.add_argument("--handoff-mode", choices=INIT_HANDOFF_MODES, default="auto")
    render_parser = subparsers.add_parser("render", help="validate and mechanically render the plan")
    add_common_arguments(render_parser)
    render_parser.add_argument("--handoff-mode", choices=HANDOFF_MODES)
    return parser, parser.parse_args(argv)


def main(argv=None):
    parser, args = parse_args(argv)
    root = args.root.expanduser().resolve()
    try:
        if args.command == "init":
            output = init_plan(root, args.job_id, args.handoff_mode, args.replace)
        else:
            output = render_plan(root, args.job_id, args.handoff_mode, args.replace)
    except (FileNotFoundError, ValueError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        parser.error(str(exc))
    print(display_path(root, output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
