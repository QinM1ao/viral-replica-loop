#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from speech_budget import MAX_GROUP_CHARS_PER_SECOND, spoken_units


def compact(text):
    return "".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", str(text or "")))


def speaker_mode_kind(value):
    text = str(value or "").strip().casefold()
    if text in {"silent", "none"} or any(
        marker in text for marker in ("无台词", "静音", "环境声")
    ):
        return "silent"
    if text in {"voiceover", "narration"} or any(
        marker in text for marker in ("旁白", "画外音")
    ):
        return "voiceover"
    if text in {"sync", "dialogue"} or any(
        marker in text for marker in ("同期", "画面内", "口播", "对白")
    ):
        return "sync"
    return text


def duration_seconds(value):
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*s?\s*", str(value or ""))
    return float(match.group(1)) if match else None


def action_timing_signature(beat):
    start = beat.get("source_start")
    end = beat.get("source_end")
    if (
        not isinstance(start, (int, float))
        or not isinstance(end, (int, float))
        or float(end) <= float(start)
    ):
        return ""
    span = float(end) - float(start)
    fractions = [
        (float(peak) - float(start)) / span
        for peak in beat.get("action_peak_times") or []
        if isinstance(peak, (int, float)) and not isinstance(peak, bool)
    ]
    return "peak_fractions=" + ",".join(f"{value:.3f}" for value in fractions)


def hard_cut_signature(beat):
    return (
        f"entry={beat.get('entry_transition', '')};"
        f"exit={beat.get('exit_transition', '')}"
    )


def asr_full_text(markdown):
    match = re.search(
        r"^## Full Text\s*$\n+(.*?)(?=\n## |\Z)",
        markdown,
        flags=re.MULTILINE | re.DOTALL,
    )
    return match.group(1).strip() if match else ""


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_bound_elevenlabs_evidence(source_evidence, source_sha256=None):
    issues = []
    asr_source_value = str(source_evidence.get("asr_source") or "")
    asr_source = Path(asr_source_value).expanduser()
    expected_dir = asr_source.parent.resolve() if asr_source_value else None
    bindings = {
        "timeline": ("asr_timeline", "asr_timeline.json"),
        "raw": ("asr_raw_response", "elevenlabs_scribe_v1.json"),
        "manifest": ("asr_request_manifest", "request_manifest.json"),
    }
    payloads = {}
    for label, (field, filename) in bindings.items():
        binding = source_evidence.get(field)
        if not isinstance(binding, dict):
            issues.append({"code": f"missing_asr_{label}_binding"})
            continue
        path = Path(str(binding.get("path") or "")).expanduser()
        if not path.is_file():
            issues.append({"code": f"missing_asr_{label}", "path": str(path)})
            continue
        if expected_dir is not None and path.resolve() != expected_dir / filename:
            issues.append({"code": f"asr_{label}_path_mismatch", "path": str(path)})
            continue
        actual_sha256 = sha256_file(path)
        if binding.get("sha256") != actual_sha256:
            issues.append(
                {
                    "code": f"asr_{label}_hash_mismatch",
                    "expected": binding.get("sha256"),
                    "actual": actual_sha256,
                }
            )
            continue
        try:
            payloads[label] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            issues.append({"code": f"invalid_asr_{label}"})

    timeline = payloads.get("timeline")
    raw = payloads.get("raw")
    manifest = payloads.get("manifest")
    timeline_binding = source_evidence.get("asr_timeline")
    timeline_binding = timeline_binding if isinstance(timeline_binding, dict) else {}
    raw_binding = source_evidence.get("asr_raw_response")
    raw_binding = raw_binding if isinstance(raw_binding, dict) else {}
    if isinstance(timeline, dict) and isinstance(raw, dict):
        if raw.get("text") != source_evidence.get("asr_text"):
            issues.append({"code": "asr_raw_text_mismatch"})
        if raw.get("transcription_id") != timeline.get("transcription_id"):
            issues.append({"code": "asr_transcription_id_mismatch"})
    if isinstance(timeline, dict) and isinstance(manifest, dict):
        if manifest.get("timeline_sha256") != timeline_binding.get("sha256"):
            issues.append({"code": "asr_manifest_timeline_hash_mismatch"})
        if manifest.get("raw_response_sha256") != raw_binding.get("sha256"):
            issues.append({"code": "asr_manifest_raw_hash_mismatch"})
        if manifest.get("http_status") != 200:
            issues.append({"code": "asr_request_status_not_pass"})
        if manifest.get("provider") != "elevenlabs":
            issues.append({"code": "asr_request_provider_mismatch"})
        if manifest.get("model") != timeline.get("model"):
            issues.append({"code": "asr_request_model_mismatch"})
        if manifest.get("transcription_id") != timeline.get("transcription_id"):
            issues.append({"code": "asr_request_transcription_id_mismatch"})
        if source_sha256 and manifest.get("source_sha256") != source_sha256:
            issues.append({"code": "asr_source_video_hash_mismatch"})
        if (
            source_sha256
            and source_evidence.get("asr_source_video_sha256") != source_sha256
        ):
            issues.append({"code": "asr_embedded_source_video_hash_mismatch"})
    return timeline, issues


def build_asr_timing_summary(source_evidence, beats, source_sha256=None):
    provider = str(source_evidence.get("asr_provider") or "")
    timeline = None
    issues = []
    if provider == "elevenlabs":
        timeline, binding_issues = load_bound_elevenlabs_evidence(
            source_evidence, source_sha256
        )
        issues.extend(binding_issues)
    words = (
        timeline.get("words")
        if isinstance(timeline, dict)
        else source_evidence.get("asr_words")
    )
    if not words and provider != "elevenlabs":
        return {}, []
    if not isinstance(words, list) or not words:
        issues.append({"code": "missing_asr_word_timeline"})
        return {}, issues

    if isinstance(timeline, dict):
        for field in ("words", "speaker_turns", "sentence_segments", "audio_events"):
            evidence_field = f"asr_{field}" if field == "words" else field
            if source_evidence.get(evidence_field) != timeline.get(field):
                issues.append({"code": f"embedded_asr_{field}_mismatch"})
    normalized_words = []
    previous_start = -1.0
    for index, item in enumerate(words):
        if not isinstance(item, dict):
            issues.append({"code": "invalid_asr_word_timeline", "index": index})
            continue
        start = item.get("start")
        end = item.get("end")
        text = str(item.get("text") or "")
        if (
            not text
            or isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, (int, float))
            or not isinstance(end, (int, float))
            or float(start) < previous_start
            or float(end) < float(start)
        ):
            issues.append({"code": "invalid_asr_word_timeline", "index": index})
            continue
        previous_start = float(start)
        normalized_words.append(item)

    spoken_words = [
        item for item in normalized_words if item.get("type") != "audio_event"
    ]
    timeline_text = compact(
        "".join(str(item.get("text") or "") for item in spoken_words)
    )
    evidence_text = compact(source_evidence.get("asr_text"))
    if timeline_text != evidence_text:
        issues.append(
            {
                "code": "asr_word_timeline_text_mismatch",
                "expected": evidence_text,
                "actual": timeline_text,
            }
        )

    characters = []
    for item in spoken_words:
        for character in compact(item.get("text")):
            characters.append(
                {
                    "start": float(item["start"]),
                    "end": float(item["end"]),
                    "speaker_id": item.get("speaker_id"),
                }
            )
    beat_timings = []
    if source_evidence.get("asr_span_basis", "compact_alnum") == "compact_alnum":
        for beat in beats:
            span = beat.get("asr_span")
            if not isinstance(span, dict):
                continue
            start = span.get("start")
            end = span.get("end")
            if (
                isinstance(start, bool)
                or isinstance(end, bool)
                or not isinstance(start, int)
                or not isinstance(end, int)
                or start < 0
                or end <= start
                or end > len(characters)
            ):
                continue
            selected = characters[start:end]
            speaker_ids = sorted(
                {
                    str(item["speaker_id"])
                    for item in selected
                    if item.get("speaker_id")
                }
            )
            if not speaker_ids:
                issues.append(
                    {
                        "code": "missing_asr_speaker_binding",
                        "beat_id": beat.get("id"),
                    }
                )
            beat_timings.append(
                {
                    "beat_id": beat.get("id"),
                    "start": selected[0]["start"],
                    "end": selected[-1]["end"],
                    "speaker_ids": speaker_ids,
                }
            )

    if provider == "elevenlabs":
        timed_ids = {item.get("beat_id") for item in beat_timings}
        for beat in beats:
            if (
                compact(beat.get("confirmed_source_line"))
                and speaker_mode_kind(beat.get("speaker_mode")) != "silent"
                and beat.get("id") not in timed_ids
            ):
                issues.append(
                    {
                        "code": "missing_asr_beat_timing",
                        "beat_id": beat.get("id"),
                    }
                )

    speaker_ids = sorted(
        {
            str(item["speaker_id"])
            for item in spoken_words
            if item.get("speaker_id")
        }
    )
    return {
        "provider": provider or None,
        "speaker_ids": speaker_ids,
        "speaker_count": len(speaker_ids),
        "word_count": len(spoken_words),
        "sentence_segment_count": len(
            source_evidence.get("sentence_segments") or []
        ),
        "audio_event_count": len(source_evidence.get("audio_events") or []),
        "beat_timings": beat_timings,
    }, issues


def expected_line(beat, source_evidence):
    evidence = beat.get("evidence") or {}
    span = beat.get("asr_span") or {}
    source_asr = str(source_evidence.get("asr_text") or "")
    span_basis = str(source_evidence.get("asr_span_basis") or "compact_alnum")
    raw_asr = source_asr if span_basis == "raw_text" else compact(source_asr)
    if span:
        start = span.get("start")
        end = span.get("end")
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end <= start
            or end > len(raw_asr)
        ):
            return "", ["invalid ASR character span"]
        line = raw_asr[start:end]
    else:
        line = str(evidence.get("asr_text") or "")
    beat_start = beat.get("source_start")
    beat_end = beat.get("source_end")
    observations = []
    for item in source_evidence.get("subtitle_observations") or []:
        observed_at = item.get("time") if isinstance(item, dict) else None
        if (
            isinstance(beat_start, (int, float))
            and isinstance(beat_end, (int, float))
            and isinstance(observed_at, (int, float))
            and float(beat_start) - 0.2 <= float(observed_at) <= float(beat_end) + 0.2
        ):
            observations.append(item)
    visible_values = list(evidence.get("visible_text") or [])
    visible_values.extend(item.get("text", "") for item in observations)
    visible_text = compact("".join(visible_values))
    correction_issues = []
    for correction in beat.get("corrections") or []:
        source = str(correction.get("from") or "")
        target = str(correction.get("to") or "")
        evidence_type = correction.get("evidence_type")
        if not source or source not in line:
            correction_issues.append("correction source is absent from ASR evidence")
            continue
        if evidence_type == "visible_text":
            if compact(target) not in visible_text:
                correction_issues.append(
                    "correction target is not backed by visible-text evidence"
                )
                continue
        elif evidence_type == "semantic_review":
            confidence = correction.get("confidence")
            reason = str(correction.get("reason") or "").strip()
            if (
                isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
                or float(confidence) < 0.9
                or not reason
            ):
                correction_issues.append(
                    "semantic correction lacks high-confidence rationale"
                )
                continue
        else:
            correction_issues.append("unsupported correction evidence type")
            continue
        line = line.replace(source, target, 1)
    return compact(line), correction_issues


def check_source_rhythm(payload):
    issues = []
    source_evidence = payload.get("source_evidence") or {}
    asr_timing, asr_timing_issues = build_asr_timing_summary(
        source_evidence,
        payload.get("beats") or [],
        payload.get("source_sha256"),
    )
    issues.extend(asr_timing_issues)
    asr_source = source_evidence.get("asr_source")
    asr_text_sha256 = source_evidence.get("asr_text_sha256")
    if asr_source and asr_text_sha256:
        asr_path = Path(asr_source).expanduser()
        if not asr_path.is_file():
            issues.append(
                {
                    "code": "missing_asr_source",
                    "path": str(asr_path),
                }
            )
        else:
            current_asr_text = asr_full_text(asr_path.read_text(encoding="utf-8"))
            actual_sha256 = hashlib.sha256(current_asr_text.encode("utf-8")).hexdigest()
            if actual_sha256 != asr_text_sha256:
                issues.append(
                    {
                        "code": "asr_source_hash_mismatch",
                        "path": str(asr_path),
                        "expected": asr_text_sha256,
                        "actual": actual_sha256,
                    }
                )
    beats = payload.get("beats") or []
    if not beats:
        issues.append(
            {
                "code": "missing_source_beats",
                "message": "mechanical evidence must be turned into authored source rhythm beats",
            }
        )
    cut_times = [
        float(item["time"])
        for item in payload.get("actual_cut_points") or []
        if isinstance(item, dict) and isinstance(item.get("time"), (int, float))
    ]
    evidence_frames = {
        str(item.get("path") or ""): item
        for item in payload.get("evidence_frames") or []
        if isinstance(item, dict) and str(item.get("path") or "")
    }
    for beat in beats:
        expected, correction_issues = expected_line(beat, source_evidence)
        beat_id = beat.get("id") or "unknown"
        for message in correction_issues:
            issues.append(
                {
                    "code": "unsupported_correction",
                    "beat_id": beat_id,
                    "message": message,
                }
            )
        actual = compact(beat.get("confirmed_source_line"))
        if not correction_issues and expected != actual:
            issues.append(
                {
                    "code": "confirmed_line_mismatch",
                    "beat_id": beat_id,
                    "expected": expected,
                    "actual": actual,
                }
            )
        required_fields = (
            "speaker_mode",
            "emphasis_tokens",
            "pause_after_seconds",
            "action_peak_times",
            "visual_action",
            "emotion_function",
            "rhythm_class",
            "replication_priority",
            "evidence_frame_refs",
            "entry_transition",
            "exit_transition",
        )
        for field in required_fields:
            value = beat.get(field)
            missing = value is None
            if field in {"speaker_mode", "visual_action", "emotion_function"}:
                missing = not str(value or "").strip()
            if field == "evidence_frame_refs":
                missing = not isinstance(value, list) or not value
            if field in {"emphasis_tokens", "action_peak_times"}:
                missing = not isinstance(value, list)
            if missing:
                issues.append(
                    {
                        "code": "missing_rhythm_field",
                        "beat_id": beat_id,
                        "field": field,
                    }
                )
        if int(payload.get("schema_version") or 1) >= 2 and not str(
            beat.get("visual_action_type") or ""
        ).strip():
            issues.append(
                {
                    "code": "missing_rhythm_field",
                    "beat_id": beat_id,
                    "field": "visual_action_type",
                }
            )
        if int(payload.get("schema_version") or 1) >= 3:
            for field in ("scene", "camera", "framing"):
                if not str(beat.get(field) or "").strip():
                    issues.append(
                        {
                            "code": "missing_rhythm_field",
                            "beat_id": beat_id,
                            "field": field,
                        }
                    )
            for frame_ref in beat.get("evidence_frame_refs") or []:
                frame = evidence_frames.get(str(frame_ref))
                if not frame:
                    continue
                frame_time = frame.get("time")
                guard_band = frame.get("cut_guard_band_seconds")
                if not isinstance(guard_band, (int, float)):
                    evidence_fps = payload.get("evidence_fps")
                    guard_band = (
                        1.0 / float(evidence_fps)
                        if isinstance(evidence_fps, (int, float))
                        and float(evidence_fps) > 0
                        else 0.2
                    )
                computed_distance = (
                    min(abs(float(frame_time) - cut) for cut in cut_times)
                    if isinstance(frame_time, (int, float)) and cut_times
                    else None
                )
                unsafe = frame.get("safe_for_beat_evidence") is False or (
                    computed_distance is not None
                    and computed_distance + 1e-9 < float(guard_band)
                )
                if unsafe:
                    issues.append(
                        {
                            "code": "unsafe_cut_boundary_evidence",
                            "beat_id": beat_id,
                            "frame_ref": str(frame_ref),
                            "time": frame.get("time"),
                            "distance_to_nearest_cut": frame.get(
                                "distance_to_nearest_cut"
                            )
                            if frame.get("distance_to_nearest_cut") is not None
                            else computed_distance,
                            "required_distance": guard_band,
                        }
                    )
            product_names = beat.get("spoken_product_names")
            if product_names is not None:
                if not isinstance(product_names, list) or any(
                    not normalized
                    or normalized not in compact(beat.get("confirmed_source_line"))
                    for normalized in [compact(name) for name in product_names]
                ):
                    issues.append(
                        {
                            "code": "invalid_spoken_product_name_evidence",
                            "beat_id": beat_id,
                        }
                    )
        requires_physical_action_evidence = (
            int(payload.get("schema_version") or 1) >= 2
            and beat.get("visual_action_type") == "physical_change"
        )
        if requires_physical_action_evidence:
            action_evidence = beat.get("action_evidence")
            if not isinstance(action_evidence, dict):
                issues.append(
                    {
                        "code": "missing_physical_action_evidence",
                        "beat_id": beat_id,
                        "message": "must-keep action commands require before/peak/after physical state-change evidence",
                    }
                )
            else:
                required_action_fields = (
                    "kind",
                    "before_frame_ref",
                    "peak_frame_ref",
                    "after_frame_ref",
                    "motion",
                    "state_before",
                    "state_after",
                    "visible_result",
                )
                missing_action_fields = [
                    field
                    for field in required_action_fields
                    if not str(action_evidence.get(field) or "").strip()
                ]
                if action_evidence.get("kind") != "physical_change":
                    missing_action_fields.append("kind=physical_change")
                if missing_action_fields:
                    issues.append(
                        {
                            "code": "incomplete_physical_action_evidence",
                            "beat_id": beat_id,
                            "missing_fields": missing_action_fields,
                        }
                    )
                else:
                    action_frame_refs = [
                        str(action_evidence[field])
                        for field in (
                            "before_frame_ref",
                            "peak_frame_ref",
                            "after_frame_ref",
                        )
                    ]
                    beat_frame_refs = {
                        str(value) for value in beat.get("evidence_frame_refs") or []
                    }
                    missing_files = [
                        value
                        for value in action_frame_refs
                        if not Path(value).expanduser().is_file()
                    ]
                    outside_beat_refs = [
                        value for value in action_frame_refs if value not in beat_frame_refs
                    ]
                    if (
                        len(set(action_frame_refs)) != 3
                        or missing_files
                        or outside_beat_refs
                    ):
                        issues.append(
                            {
                                "code": "unverified_physical_action_evidence",
                                "beat_id": beat_id,
                                "missing_files": missing_files,
                                "outside_beat_refs": outside_beat_refs,
                                "distinct_frame_count": len(set(action_frame_refs)),
                            }
                        )
        source_start = beat.get("source_start")
        source_end = beat.get("source_end")
        if isinstance(source_start, (int, float)) and isinstance(source_end, (int, float)):
            for peak in beat.get("action_peak_times") or []:
                if (
                    not isinstance(peak, (int, float))
                    or isinstance(peak, bool)
                    or not float(source_start) <= float(peak) <= float(source_end)
                ):
                    issues.append(
                        {
                            "code": "action_peak_outside_beat",
                            "beat_id": beat_id,
                            "time": peak,
                            "source_start": source_start,
                            "source_end": source_end,
                        }
                    )
        for field, boundary_field in (
            ("entry_transition", "source_start"),
            ("exit_transition", "source_end"),
        ):
            if beat.get(field) != "hard_cut":
                continue
            boundary = beat.get(boundary_field)
            if not isinstance(boundary, (int, float)) or isinstance(boundary, bool):
                continue
            if not cut_times or min(abs(float(boundary) - cut) for cut in cut_times) > 0.12:
                issues.append(
                    {
                        "code": "unverified_hard_cut",
                        "beat_id": beat_id,
                        "field": field,
                        "time": boundary,
                    }
                )
    for previous, current in zip(beats, beats[1:]):
        previous_end = previous.get("source_end")
        current_start = current.get("source_start")
        if not isinstance(previous_end, (int, float)) or not isinstance(
            current_start, (int, float)
        ):
            continue
        delta = float(current_start) - float(previous_end)
        if delta > 0.12:
            issues.append(
                {
                    "code": "source_beat_timeline_gap",
                    "after_beat_id": previous.get("id"),
                    "before_beat_id": current.get("id"),
                    "gap_seconds": round(delta, 3),
                }
            )
        elif delta < -0.12:
            issues.append(
                {
                    "code": "source_beat_timeline_overlap",
                    "after_beat_id": previous.get("id"),
                    "before_beat_id": current.get("id"),
                    "overlap_seconds": round(-delta, 3),
                }
            )
    return {
        "overall": "FAIL" if issues else "PASS",
        "issues": issues,
        "asr_timing": asr_timing,
    }


def check_director_plan(source_rhythm, plan):
    issues = []
    if (
        int(plan.get("version") or 0) >= 6
        and int(source_rhythm.get("schema_version") or 0) < 3
    ):
        issues.append(
            {
                "code": "director_plan_v6_requires_source_rhythm_v3",
                "actual_schema_version": source_rhythm.get("schema_version"),
            }
        )
    plan_version = int(plan.get("version") or 0)
    replication_fidelity = plan.get("replication_fidelity") or {}
    full_fidelity = (
        plan_version >= 6
        and replication_fidelity.get("mode") == "source_locked"
        and replication_fidelity.get("change_policy") == "necessary_only"
        and replication_fidelity.get("duration_mode") == "source_length"
    )
    source_duration = source_rhythm.get("duration")
    target_duration = duration_seconds((plan.get("job") or {}).get("target_duration"))
    if not isinstance(source_duration, (int, float)) or not target_duration:
        return [
            {
                "code": "missing_duration_for_rhythm_scaling",
                "message": "source duration and target duration are required",
            }
        ]
    overall_stretch = target_duration / float(source_duration)
    source_beats = {
        beat.get("id"): beat
        for beat in source_rhythm.get("beats") or []
        if beat.get("id")
    }
    source_order = {beat_id: index for index, beat_id in enumerate(source_beats)}
    mapped_ids_in_order = []
    director_source_lines = []
    for part in plan.get("parts") or []:
        target_beats = {
            beat.get("id"): beat
            for beat in part.get("beats") or []
            if beat.get("id")
        }
        for beat in target_beats.values():
            if str(beat.get("source_line") or "").strip():
                director_source_lines.append(str(beat.get("source_line")))
            source_ids = beat.get("source_beat_ids") or []
            if not isinstance(source_ids, list) or not source_ids:
                issues.append(
                    {
                        "code": "missing_source_beat_mapping",
                        "part_id": part.get("id"),
                        "beat_id": beat.get("id"),
                    }
                )
                continue
            if full_fidelity and len(source_ids) != 1:
                issues.append(
                    {
                        "code": "source_length_target_beat_must_bind_one_source_beat",
                        "part_id": part.get("id"),
                        "beat_id": beat.get("id"),
                        "source_beat_ids": source_ids,
                    }
                )
            unknown_ids = [source_id for source_id in source_ids if source_id not in source_beats]
            if unknown_ids:
                issues.append(
                    {
                        "code": "unknown_source_beat_mapping",
                        "part_id": part.get("id"),
                        "beat_id": beat.get("id"),
                        "source_beat_ids": unknown_ids,
                    }
                )
            excluded_ids = [
                source_id
                for source_id in source_ids
                if source_id in source_beats
                and source_beats[source_id].get("replication_priority") == "exclude"
            ]
            if excluded_ids:
                issues.append(
                    {
                        "code": "excluded_source_beat_mapped",
                        "part_id": part.get("id"),
                        "beat_id": beat.get("id"),
                        "source_beat_ids": excluded_ids,
                    }
                )
            mapped_ids_in_order.extend(
                source_id for source_id in source_ids if source_id in source_beats
            )
            mapped = [source_beats[source_id] for source_id in source_ids if source_id in source_beats]
            if not mapped:
                continue
            if plan_version >= 6:
                expected_visual_action = " → ".join(
                    str(item.get("visual_action") or "") for item in mapped
                )
                if compact(beat.get("source_visual_action")) != compact(
                    expected_visual_action
                ):
                    issues.append(
                        {
                            "code": "director_plan_source_visual_action_not_verbatim",
                            "part_id": part.get("id"),
                            "beat_id": beat.get("id"),
                            "expected": expected_visual_action,
                            "actual": beat.get("source_visual_action"),
                        }
                    )
                expected_beat_line = "".join(
                    str(item.get("confirmed_source_line") or "") for item in mapped
                )
                if compact(beat.get("source_line")) != compact(expected_beat_line):
                    issues.append(
                        {
                            "code": "director_plan_beat_source_line_not_verbatim",
                            "part_id": part.get("id"),
                            "beat_id": beat.get("id"),
                            "expected": expected_beat_line,
                            "actual": beat.get("source_line"),
                        }
                    )
                expected_modes = {
                    speaker_mode_kind(item.get("speaker_mode")) for item in mapped
                }
                actual_mode = speaker_mode_kind(beat.get("source_speaker_mode"))
                if len(expected_modes) != 1 or actual_mode not in expected_modes:
                    issues.append(
                        {
                            "code": "director_plan_beat_source_speaker_mode_changed",
                            "part_id": part.get("id"),
                            "beat_id": beat.get("id"),
                            "expected": sorted(expected_modes),
                            "actual": actual_mode,
                        }
                    )
                visual_fidelity = beat.get("visual_fidelity")
                if (
                    int(source_rhythm.get("schema_version") or 0) >= 3
                    and len(mapped) == 1
                ):
                    source_beat = mapped[0]
                    expected_visual_fidelity = {
                        "scene": str(source_beat.get("scene") or ""),
                        "camera": str(source_beat.get("camera") or ""),
                        "framing": str(source_beat.get("framing") or ""),
                        "action_stage": str(
                            source_beat.get("visual_action_type") or ""
                        ),
                        "action_timing": action_timing_signature(source_beat),
                        "transition": (
                            f"{source_beat.get('entry_transition', '')} -> "
                            f"{source_beat.get('exit_transition', '')}"
                        ),
                        "hard_cuts": hard_cut_signature(source_beat),
                    }
                    if not isinstance(visual_fidelity, dict):
                        issues.append(
                            {
                                "code": "missing_director_plan_visual_fidelity",
                                "part_id": part.get("id"),
                                "beat_id": beat.get("id"),
                            }
                        )
                    else:
                        for field, expected_value in expected_visual_fidelity.items():
                            actual_value = visual_fidelity.get(f"source_{field}")
                            if compact(actual_value) != compact(expected_value):
                                issues.append(
                                    {
                                        "code": (
                                            f"director_plan_source_{field}_not_verbatim"
                                        ),
                                        "part_id": part.get("id"),
                                        "beat_id": beat.get("id"),
                                        "expected": expected_value,
                                        "actual": actual_value,
                                    }
                                )
                if full_fidelity and len(mapped) == 1:
                    target_start = beat.get("target_start")
                    target_end = beat.get("target_end")
                    if isinstance(target_start, (int, float)) and isinstance(
                        target_end, (int, float)
                    ):
                        source_span = float(mapped[0]["source_end"]) - float(
                            mapped[0]["source_start"]
                        )
                        expected_target_span = source_span * overall_stretch
                        actual_target_span = float(target_end) - float(target_start)
                        tolerance = max(0.12, expected_target_span * 0.12)
                        if abs(actual_target_span - expected_target_span) > tolerance:
                            issues.append(
                                {
                                    "code": "source_length_beat_timing_changed",
                                    "part_id": part.get("id"),
                                    "beat_id": beat.get("id"),
                                    "expected_seconds": round(expected_target_span, 3),
                                    "actual_seconds": round(actual_target_span, 3),
                                    "tolerance_seconds": round(tolerance, 3),
                                }
                            )
            if not any(item.get("rhythm_class") == "rapid_hook" for item in mapped):
                continue
            source_start = min(float(item["source_start"]) for item in mapped)
            source_end = max(float(item["source_end"]) for item in mapped)
            target_start = beat.get("target_start")
            target_end = beat.get("target_end")
            if not isinstance(target_start, (int, float)) or not isinstance(target_end, (int, float)):
                continue
            source_span = source_end - source_start
            target_span = float(target_end) - float(target_start)
            if source_span > 0 and target_span / source_span > overall_stretch * 1.2:
                issues.append(
                    {
                        "code": "rapid_hook_overstretched",
                        "part_id": part.get("id"),
                        "beat_id": beat.get("id"),
                        "source_seconds": round(source_span, 3),
                        "target_seconds": round(target_span, 3),
                        "max_target_seconds": round(source_span * overall_stretch * 1.2, 3),
                    }
                )
        for group in part.get("speech_groups") or []:
            mapped_source = []
            for target_beat_id in group.get("beat_ids") or []:
                target_beat = target_beats.get(target_beat_id) or {}
                for source_id in target_beat.get("source_beat_ids") or []:
                    source_beat = source_beats.get(source_id)
                    if source_beat and source_beat not in mapped_source:
                        mapped_source.append(source_beat)
            spoken_source = [
                beat
                for beat in mapped_source
                if beat.get("speaker_mode") != "silent" and beat.get("rhythm_class") != "pause"
            ]
            if not spoken_source:
                continue
            source_seconds = sum(
                float(beat["source_end"]) - float(beat["source_start"])
                for beat in spoken_source
            )
            source_units = sum(
                spoken_units(beat.get("confirmed_source_line")) for beat in spoken_source
            )
            target_start = group.get("target_start")
            target_end = group.get("target_end")
            if (
                source_seconds <= 0
                or not isinstance(target_start, (int, float))
                or not isinstance(target_end, (int, float))
                or target_end <= target_start
            ):
                continue
            source_rate = source_units / source_seconds
            target_rate = spoken_units(group.get("line")) / (float(target_end) - float(target_start))
            minimum_target_rate = min(
                source_rate * 0.8,
                MAX_GROUP_CHARS_PER_SECOND,
            )
            if source_rate > 0 and target_rate < minimum_target_rate:
                issues.append(
                    {
                        "code": "speech_too_sparse_for_source_pace",
                        "part_id": part.get("id"),
                        "speech_group_id": group.get("id"),
                        "source_units_per_second": round(source_rate, 3),
                        "target_units_per_second": round(target_rate, 3),
                        "minimum_target_units_per_second": round(minimum_target_rate, 3),
                    }
                )
    required_source_ids = (
        {
            beat_id
            for beat_id, beat in source_beats.items()
            if beat.get("replication_priority") != "exclude"
        }
        if full_fidelity
        else {
            beat_id
            for beat_id, beat in source_beats.items()
            if beat.get("replication_priority") in {"must_keep", "mergeable"}
        }
    )
    missing_source_ids = sorted(required_source_ids - set(mapped_ids_in_order))
    for source_id in missing_source_ids:
        issues.append(
            {
                "code": "uncovered_source_beat",
                "source_beat_id": source_id,
            }
        )
    mapping_counts = Counter(mapped_ids_in_order)
    for source_id in sorted(required_source_ids):
        if mapping_counts[source_id] > 1:
            issues.append(
                {
                    "code": "duplicate_source_beat_mapping",
                    "source_beat_id": source_id,
                    "count": mapping_counts[source_id],
                }
            )
    mapped_positions = [source_order[source_id] for source_id in mapped_ids_in_order]
    if any(right < left for left, right in zip(mapped_positions, mapped_positions[1:])):
        issues.append(
            {
                "code": "source_beat_order_changed",
                "source_beat_ids": mapped_ids_in_order,
            }
        )
    if plan_version >= 5:
        seen_source_ids = set()
        expected_source_lines = []
        for source_id in mapped_ids_in_order:
            if source_id in seen_source_ids:
                continue
            seen_source_ids.add(source_id)
            source_beat = source_beats[source_id]
            if source_beat.get("speaker_mode") == "silent" or source_beat.get("rhythm_class") == "pause":
                continue
            expected_source_lines.append(str(source_beat.get("confirmed_source_line") or ""))
        expected_source_text = compact("".join(expected_source_lines))
        actual_source_text = compact("".join(director_source_lines))
        if expected_source_text != actual_source_text:
            issues.append(
                {
                    "code": "director_plan_source_line_not_verbatim",
                    "expected": expected_source_text,
                    "actual": actual_source_text,
                }
            )
    return issues


def check_source_rhythm_binding(source_path, source_rhythm, plan):
    if int(plan.get("version") or 0) < 4:
        return []
    binding = plan.get("source_rhythm")
    if not isinstance(binding, dict):
        return [
            {
                "code": "missing_source_rhythm_binding",
                "message": "director plan v4 must bind the exact source_rhythm.json used to author it",
            }
        ]
    issues = []
    if not str(binding.get("path") or "").strip():
        issues.append({"code": "missing_source_rhythm_path"})
    expected_analysis_sha256 = str(binding.get("analysis_sha256") or "").strip()
    actual_analysis_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
    if not expected_analysis_sha256:
        issues.append({"code": "missing_source_rhythm_hash"})
    elif expected_analysis_sha256 != actual_analysis_sha256:
        issues.append(
            {
                "code": "stale_source_rhythm_binding",
                "expected": expected_analysis_sha256,
                "actual": actual_analysis_sha256,
            }
        )
    expected_video_sha256 = str(binding.get("source_video_sha256") or "").strip()
    actual_video_sha256 = str(source_rhythm.get("source_sha256") or "").strip()
    if actual_video_sha256 and expected_video_sha256 != actual_video_sha256:
        issues.append(
            {
                "code": "source_video_hash_binding_mismatch",
                "expected": expected_video_sha256,
                "actual": actual_video_sha256,
            }
        )
    return issues


def render_markdown(report):
    lines = [
        "# Source Rhythm QC",
        "",
        f"- Overall: **{report['overall']}**",
        f"- Source rhythm: `{report['source_rhythm']}`",
    ]
    if report.get("director_plan"):
        lines.append(f"- Director plan: `{report['director_plan']}`")
    lines.extend(["", "## Issues", ""])
    if not report["issues"]:
        lines.append("- None.")
    else:
        for issue in report["issues"]:
            lines.append(f"- `{issue['code']}`: {json.dumps(issue, ensure_ascii=False)}")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-rhythm", required=True)
    parser.add_argument("--director-plan")
    parser.add_argument("--json-out", required=True)
    parser.add_argument("--md-out")
    args = parser.parse_args()

    source_path = Path(args.source_rhythm).expanduser().resolve()
    report_path = Path(args.json_out).expanduser().resolve()
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    report = check_source_rhythm(payload)
    if args.director_plan:
        plan_path = Path(args.director_plan).expanduser().resolve()
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        report["issues"].extend(check_source_rhythm_binding(source_path, payload, plan))
        report["issues"].extend(check_director_plan(payload, plan))
        report["director_plan"] = str(plan_path)
        report["overall"] = "FAIL" if report["issues"] else "PASS"
    report["source_rhythm"] = str(source_path)
    report["source_rhythm_sha256"] = hashlib.sha256(
        source_path.read_bytes()
    ).hexdigest()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if args.md_out:
        markdown_path = Path(args.md_out).expanduser().resolve()
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"SOURCE_RHYTHM_QC={report['overall']}")
    raise SystemExit(0 if report["overall"] == "PASS" else 1)


if __name__ == "__main__":
    main()
