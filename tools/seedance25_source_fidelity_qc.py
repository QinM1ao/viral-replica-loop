#!/usr/bin/env python3
"""Validate Seedance 2.5 source fidelity, semantic dialogue blocks, and optional depth."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


ALLOWED_AUDIO_MODES = {"generated_voiceover", "original_master_postmix"}
ALLOWED_SEMANTIC_UNITS = {"complete_sentence", "complete_clause", "standalone_utterance"}
ALLOWED_LINE_AUTHORIZATIONS = {"explicit_user_request", "product_fact_conflict"}
ALLOWED_VISUAL_EDIT_KINDS = {
    "entity_substitution",
    "appearance_substitution",
    "visible_text_removal",
    "user_requested_action_change",
}
ALLOWED_VISUAL_AUTHORIZATIONS = {"explicit_user_request", "source_cleanup"}
STAGE_RE = re.compile(r"^(阶段[一二三四五六七八九十百]+)：(.*)$", re.MULTILINE)
QUOTE_RE = re.compile(r"\{([^{}]*)\}")
INTERNAL_LABEL_RE = re.compile(r"source_rhythm|sr\d+|shot", re.IGNORECASE)
INCOMPLETE_END_RE = re.compile(r"(?:把[他她它这那]?|从(?:这|那|这个|那个)?|像从(?:这|那|这个|那个)?|哪款产品)$")
SPRAY_TRIGGER_RE = re.compile(r"按压喷头|喷头.{0,24}喷出|朝.{0,24}喷出")
SPRAY_REQUIRED_TERMS = (
    "按压喷头",
    "离开喷口立即分散",
    "均匀细密的雾化微滴",
    "短暂悬浮",
    "极细小水珠",
)
CONSISTENCY_FORBIDDEN_TERMS = (
    "断句", "分段", "台词", "语义", "句界", "替换为", "无停顿", "动作轨迹",
    "硬切", "不得", "禁止", "不能", "只能", "字幕", "水印", "BGM",
)
STANDALONE_CONTEXT_FORBIDDEN_PHRASES = (
    "重新生成当前成片", "当前成片", "现有成片", "已有成片", "沿用上一版",
    "沿用之前版本", "修复上一版", "修复上一次", "修复之前版本",
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def add(checks: list[dict], name: str, passed: bool, detail: str) -> None:
    checks.append({"name": name, "status": "PASS" if passed else "FAIL", "detail": detail})


def normalize_dialogue(text: str) -> str:
    return re.sub(r"[\s，。！？、；：,.!?;:'\"“”‘’（）()\-—…]", "", text or "")


def apply_declared_edits(source: str, edits: list[dict]) -> tuple[str, list[str]]:
    value = source
    errors = []
    for index, edit in enumerate(edits, start=1):
        if not isinstance(edit, dict):
            errors.append(f"edit {index} is not an object")
            continue
        old = str(edit.get("from") or "")
        new = str(edit.get("to") or "")
        if not old:
            errors.append(f"edit {index} has an empty from value")
            continue
        count = value.count(old)
        if count != 1:
            errors.append(f"edit {index} expected one occurrence of {old!r}, found {count}")
            continue
        value = value.replace(old, new, 1)
    return value, errors


def prompt_stages(prompt: str) -> dict[str, str]:
    matches = list(STAGE_RE.finditer(prompt))
    stages = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(prompt)
        stages[match.group(1)] = (match.group(2) + prompt[match.end():end]).strip()
    return stages


def prompt_section(prompt: str, header: str) -> str:
    marker = f"【{header}】"
    start = prompt.find(marker)
    if start < 0:
        return ""
    body_start = start + len(marker)
    next_header = re.search(r"\n【[^】]+】", prompt[body_start:])
    body_end = body_start + next_header.start() if next_header else len(prompt)
    return prompt[body_start:body_end].strip()


def directive_evidence_ok(edit: dict, directives_text: str) -> bool:
    quote = str(edit.get("evidence_quote") or "").strip()
    return bool(quote and quote in directives_text)


def semantic_block_ok(text: str, unit: str) -> tuple[bool, str]:
    normalized = normalize_dialogue(text)
    minimum = 2 if unit == "standalone_utterance" else 5
    incomplete = bool(INCOMPLETE_END_RE.search(normalized))
    return (
        len(normalized) >= minimum and not incomplete,
        f"unit={unit!r}, chars={len(normalized)}, incomplete_ending={incomplete}",
    )


def assess(
    *,
    source_rhythm_path: Path,
    traceability_path: Path,
    prompt_path: Path,
    user_directives_path: Path,
    depth_qc_path: Path | None = None,
) -> dict:
    checks: list[dict] = []
    source_rhythm = json.loads(source_rhythm_path.read_text(encoding="utf-8"))
    traceability = json.loads(traceability_path.read_text(encoding="utf-8"))
    prompt = prompt_path.read_text(encoding="utf-8")
    directives_text = user_directives_path.read_text(encoding="utf-8")
    depth_qc = json.loads(depth_qc_path.read_text(encoding="utf-8")) if depth_qc_path else None

    rhythm_hash = file_sha256(source_rhythm_path)
    prompt_hash = hashlib.sha256(prompt.strip().encode("utf-8")).hexdigest()
    beats = [beat for beat in source_rhythm.get("beats") or [] if isinstance(beat, dict)]
    events = [event for event in traceability.get("events") or [] if isinstance(event, dict)]
    speech_groups = [group for group in traceability.get("speech_groups") or [] if isinstance(group, dict)]
    beat_by_id = {str(beat.get("id") or ""): beat for beat in beats}
    expected_ids = [str(beat.get("id") or "") for beat in beats]
    actual_ids = [str(event.get("source_beat_id") or "") for event in events]
    audio_mode = str(traceability.get("audio_mode") or "")

    add(checks, "contract_schema", traceability.get("schema_version") == 5,
        f"found={traceability.get('schema_version')!r}, expected=5")
    add(checks, "fidelity_mode", traceability.get("fidelity_mode") == "source_locked",
        f"found={traceability.get('fidelity_mode')!r}, expected='source_locked'")
    add(checks, "audio_mode", audio_mode in ALLOWED_AUDIO_MODES,
        f"found={audio_mode!r}, allowed={sorted(ALLOWED_AUDIO_MODES)!r}")
    add(checks, "source_rhythm_hash", traceability.get("source_rhythm_sha256") == rhythm_hash,
        f"contract={traceability.get('source_rhythm_sha256')!r}, actual={rhythm_hash}")
    add(checks, "source_event_coverage_order", actual_ids == expected_ids,
        f"expected={expected_ids!r}, actual={actual_ids!r}")

    internal_labels = sorted(set(match.group(0) for match in INTERNAL_LABEL_RE.finditer(prompt)))
    add(checks, "prompt_has_no_internal_labels", not internal_labels,
        f"found={internal_labels!r}")
    context_phrases = [value for value in STANDALONE_CONTEXT_FORBIDDEN_PHRASES if value in prompt]
    add(checks, "prompt_is_standalone_task", not context_phrases,
        f"forbidden_context_phrases={context_phrases!r}")

    stages = prompt_stages(prompt)
    stage_order = list(stages)
    stage_positions = {stage: index for index, stage in enumerate(stage_order)}
    consistency = prompt_section(prompt, "保持一致")
    consistency_lines = [line.strip() for line in consistency.splitlines() if line.strip()]
    forbidden_consistency = [term for term in CONSISTENCY_FORBIDDEN_TERMS if term in consistency]
    consistency_ok = (
        len(consistency_lines) == 1
        and len(consistency) <= 120
        and consistency.startswith("保持")
        and consistency.endswith("稳定。")
        and not forbidden_consistency
    )
    add(checks, "prompt_consistency_minimal_scope", consistency_ok,
        f"lines={len(consistency_lines)}, chars={len(consistency)}, forbidden={forbidden_consistency!r}")

    event_positions = []
    spray_stage_names = []
    for index, event in enumerate(events, start=1):
        beat_id = str(event.get("source_beat_id") or "")
        beat = beat_by_id.get(beat_id)
        if beat is None:
            add(checks, f"event_{index}_source_binding", False, f"unknown source beat={beat_id!r}")
            continue
        source_action = str(beat.get("visual_action") or "")
        target_action = str(event.get("target_visual_action") or "")
        visual_edits = event.get("visual_edits") or []
        compiled_action, errors = apply_declared_edits(source_action, visual_edits)
        for edit in visual_edits:
            if not isinstance(edit, dict):
                continue
            kind = edit.get("edit_kind")
            authorization = edit.get("authorization")
            if kind not in ALLOWED_VISUAL_EDIT_KINDS:
                errors.append(f"unsupported visual edit kind={kind!r}")
            if authorization not in ALLOWED_VISUAL_AUTHORIZATIONS:
                errors.append(f"unsupported visual authorization={authorization!r}")
            if authorization == "explicit_user_request" and not directive_evidence_ok(edit, directives_text):
                errors.append("visual edit lacks an exact user directive quote")
            if authorization == "source_cleanup" and kind != "visible_text_removal":
                errors.append("source_cleanup only authorizes visible_text_removal")
        add(checks, f"{beat_id}_visual_fidelity", not errors and compiled_action == target_action,
            "; ".join(errors) or f"compiled={compiled_action!r}, target={target_action!r}")
        stage_name = str(event.get("stage") or "")
        event_positions.append(stage_positions.get(stage_name, -1))
        stage_text = stages.get(stage_name, "")
        add(checks, f"{beat_id}_prompt_action", bool(target_action and target_action in stage_text),
            f"stage={stage_name!r}; exact target action {'found' if target_action in stage_text else 'missing'}")
        if SPRAY_TRIGGER_RE.search(target_action):
            spray_stage_names.append(stage_name)
            missing = [term for term in SPRAY_REQUIRED_TERMS if term not in target_action or term not in stage_text]
            add(checks, f"{beat_id}_atomized_mist_physics", not missing,
                f"stage={stage_name!r}, missing={missing!r}")
    add(checks, "event_stage_order", bool(event_positions) and all(value >= 0 for value in event_positions)
        and event_positions == sorted(event_positions), f"positions={event_positions!r}")

    expected_speech_beat_ids = [
        str(beat.get("id") or "") for beat in beats
        if str(beat.get("confirmed_source_line") or "").strip()
    ]
    expected_source_text = "".join(
        str(beat.get("confirmed_source_line") or "") for beat in beats
        if str(beat.get("confirmed_source_line") or "").strip()
    )
    actual_speech_beat_ids = []
    actual_source_text = ""
    expected_target_lines = []
    occupied_stage_positions = []
    for index, group in enumerate(speech_groups, start=1):
        group_id = str(group.get("id") or f"speech_group_{index}")
        unit = str(group.get("semantic_unit") or "")
        add(checks, f"{group_id}_semantic_unit", unit in ALLOWED_SEMANTIC_UNITS,
            f"found={unit!r}, allowed={sorted(ALLOWED_SEMANTIC_UNITS)!r}")
        source_parts = [part for part in group.get("source_parts") or [] if isinstance(part, dict)]
        part_ids = [str(part.get("source_beat_id") or "") for part in source_parts]
        part_text = "".join(str(part.get("text") or "") for part in source_parts)
        actual_speech_beat_ids.extend(part_ids)
        actual_source_text += part_text
        source_line = str(group.get("source_line") or "")
        add(checks, f"{group_id}_source_line", bool(source_parts)
            and normalize_dialogue(part_text) == normalize_dialogue(source_line),
            f"parts={part_text!r}, source_line={source_line!r}")
        semantic_ok, semantic_detail = semantic_block_ok(source_line, unit)
        add(checks, f"{group_id}_semantic_completeness", semantic_ok, semantic_detail)

        target_line = str(group.get("target_line") or "")
        edits = group.get("line_edits") or []
        compiled_line, line_errors = apply_declared_edits(source_line, edits)
        for edit in edits:
            if not isinstance(edit, dict):
                continue
            authorization = edit.get("authorization")
            if authorization not in ALLOWED_LINE_AUTHORIZATIONS:
                line_errors.append(f"unsupported line authorization={authorization!r}")
            if authorization == "explicit_user_request" and not directive_evidence_ok(edit, directives_text):
                line_errors.append("line edit lacks an exact user directive quote")
        add(checks, f"{group_id}_line_fidelity", not line_errors and compiled_line == target_line,
            "; ".join(line_errors) or f"compiled={compiled_line!r}, target={target_line!r}")
        target_semantic_ok, target_semantic_detail = semantic_block_ok(target_line, unit)
        add(checks, f"{group_id}_target_semantic_completeness", target_semantic_ok,
            target_semantic_detail)
        expected_target_lines.append(target_line)

        span = [str(value) for value in group.get("stage_span") or []]
        positions = [stage_positions.get(stage, -1) for stage in span]
        contiguous = bool(positions) and all(value >= 0 for value in positions)
        contiguous = contiguous and positions == list(range(positions[0], positions[0] + len(positions)))
        add(checks, f"{group_id}_stage_span", contiguous,
            f"span={span!r}, positions={positions!r}")
        occupied_stage_positions.extend(positions)
        delivery = group.get("delivery")
        add(checks, f"{group_id}_delivery", delivery == "single_continuous_block",
            f"found={delivery!r}, expected='single_continuous_block'")

        if span and audio_mode == "generated_voiceover":
            anchor_text = stages.get(span[0], "")
            anchor_quotes = QUOTE_RE.findall(anchor_text)
            other_quotes = [quote for stage in span[1:] for quote in QUOTE_RE.findall(stages.get(stage, ""))]
            range_bound = len(span) == 1 or (span[0] in anchor_text and span[-1] in anchor_text)
            add(checks, f"{group_id}_prompt_block", anchor_quotes == [target_line]
                and not other_quotes and range_bound,
                f"anchor={span[0]!r}, anchor_quotes={anchor_quotes!r}, other_quotes={other_quotes!r}, range_bound={range_bound}")

    add(checks, "speech_source_coverage", actual_speech_beat_ids == expected_speech_beat_ids
        and normalize_dialogue(actual_source_text) == normalize_dialogue(expected_source_text),
        f"expected_ids={expected_speech_beat_ids!r}, actual_ids={actual_speech_beat_ids!r}")
    add(checks, "speech_group_stage_order", occupied_stage_positions == sorted(occupied_stage_positions)
        and len(occupied_stage_positions) == len(set(occupied_stage_positions)),
        f"positions={occupied_stage_positions!r}")

    prompt_quotes = QUOTE_RE.findall(prompt)
    prompt_audio_refs = re.findall(r"@音频\d+", prompt)
    reference_duties = prompt_section(prompt, "参考素材职责")
    if audio_mode == "generated_voiceover":
        add(checks, "prompt_dialogue_blocks", prompt_quotes == expected_target_lines,
            f"expected={expected_target_lines!r}, actual={prompt_quotes!r}")
        clean_sample_ok = not prompt_audio_refs or ("干净" in reference_duties and "音色" in reference_duties)
        add(checks, "clean_timbre_reference", clean_sample_ok,
            f"audio_refs={prompt_audio_refs!r}, clean={'干净' in reference_duties}, timbre={'音色' in reference_duties}")
    elif audio_mode == "original_master_postmix":
        add(checks, "postmix_prompt_has_no_dialogue", not prompt_quotes and not prompt_audio_refs,
            f"quotes={prompt_quotes!r}, audio_refs={prompt_audio_refs!r}")

    depth_contract = traceability.get("depth_reference")
    depth_enabled = isinstance(depth_contract, dict) and depth_contract.get("enabled") is True
    depth_disabled = isinstance(depth_contract, dict) and depth_contract.get("enabled") is False
    prompt_video_refs = re.findall(r"@视频\d+", prompt)
    add(checks, "depth_decision_declared", depth_enabled or depth_disabled,
        f"depth_reference={depth_contract!r}")
    source_video_hash = str(source_rhythm.get("source_sha256") or "")
    depth_output_hash = ""
    if depth_enabled:
        depth_source_hash = str((depth_qc or {}).get("source_sha256") or "")
        depth_output_hash = str((depth_qc or {}).get("output_sha256") or "")
        depth_ok = depth_qc is not None and depth_qc.get("overall") == "PASS"
        depth_ok = depth_ok and depth_source_hash == source_video_hash and len(prompt_video_refs) == 1
        add(checks, "enabled_depth_binding", depth_ok,
            f"source={source_video_hash!r}, depth_source={depth_source_hash!r}, refs={prompt_video_refs!r}")
    elif depth_disabled:
        add(checks, "disabled_depth_absent", depth_qc is None and not prompt_video_refs,
            f"depth_qc_supplied={depth_qc is not None}, refs={prompt_video_refs!r}")

    expected_transcript = "".join(expected_target_lines)
    overall = "PASS" if checks and all(item["status"] == "PASS" for item in checks) else "FAIL"
    report = {
        "schema_version": 2,
        "overall": overall,
        "audio_mode": audio_mode,
        "depth_reference_enabled": depth_enabled,
        "source_rhythm_path": str(source_rhythm_path),
        "source_rhythm_sha256": rhythm_hash,
        "source_video_sha256": source_video_hash,
        "traceability_path": str(traceability_path),
        "traceability_sha256": file_sha256(traceability_path),
        "prompt_path": str(prompt_path),
        "prompt_sha256": prompt_hash,
        "user_directives_path": str(user_directives_path),
        "user_directives_sha256": file_sha256(user_directives_path),
        "expected_transcript": expected_transcript,
        "depth_output_sha256": depth_output_hash,
        "spray_stages": spray_stage_names,
        "checks": checks,
    }
    if depth_qc_path:
        report["depth_qc_path"] = str(depth_qc_path)
        report["depth_qc_sha256"] = file_sha256(depth_qc_path)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-rhythm", type=Path, required=True)
    parser.add_argument("--traceability", type=Path, required=True)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--depth-qc", type=Path)
    parser.add_argument("--user-directives", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = assess(
        source_rhythm_path=args.source_rhythm.resolve(),
        traceability_path=args.traceability.resolve(),
        prompt_path=args.prompt.resolve(),
        user_directives_path=args.user_directives.resolve(),
        depth_qc_path=args.depth_qc.resolve() if args.depth_qc else None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Seedance 2.5 source fidelity {report['overall']}: {args.output}")
    return 0 if report["overall"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
