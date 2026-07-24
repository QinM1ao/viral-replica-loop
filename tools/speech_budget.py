#!/usr/bin/env python3
"""Shared speech-capacity rules for one 15-second Seedance Part."""

import re


PART_DURATION_SECONDS = 15.0
MAX_SPEECH_GROUPS = 3
MAX_SOURCE_MATCHED_SPEECH_GROUPS = 6
MAX_TOTAL_SPOKEN_UNITS = 85
MAX_SOURCE_MATCHED_TOTAL_SPOKEN_UNITS = 90
MAX_GROUP_CHARS_PER_SECOND = 6.2
MIN_SILENCE_SECONDS = 0.5
MAX_SYNC_LINE_UNITS = 22

HAN_RE = re.compile(r"[\u3400-\u9fff]")
DIGIT_RE = re.compile(r"\d")
LATIN_WORD_RE = re.compile(r"[A-Za-z]+")
SYNC_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?；;]+")


def spoken_units(text):
    """Estimate Mandarin delivery load, including numbers and short Latin terms."""
    value = str(text or "")
    units = len(HAN_RE.findall(value))
    units += len(DIGIT_RE.findall(value))
    units += 3 * value.count("%")  # 52% is spoken as roughly "百分之五十二".
    units += 2 * len(LATIN_WORD_RE.findall(value))
    return units


def _group_value(group, key, default=None):
    return group.get(key, default) if isinstance(group, dict) else default


def assess_speech_groups(
    groups,
    part_duration=PART_DURATION_SECONDS,
    source_units_per_second=None,
    source_speech_group_count=None,
    source_spoken_beat_count=None,
    source_total_spoken_units=None,
    allowed_localized_expansion_units=0,
    source_pause_seconds=None,
):
    """Return a deterministic PASS/FAIL report for already-bound speech groups."""
    groups = list(groups or [])
    failures = []
    warnings = []
    details = []
    intervals = []
    total_units = 0
    max_cps = 0.0
    max_sync_units = 0
    max_allowed_group_cps = MAX_GROUP_CHARS_PER_SECOND
    max_allowed_sync_units = MAX_SYNC_LINE_UNITS

    max_speech_groups = MAX_SPEECH_GROUPS
    source_group_capacity = 0
    for value in (source_speech_group_count, source_spoken_beat_count):
        if isinstance(value, int) and not isinstance(value, bool):
            source_group_capacity = max(source_group_capacity, value)
    if source_group_capacity > MAX_SPEECH_GROUPS:
        max_speech_groups = min(MAX_SOURCE_MATCHED_SPEECH_GROUPS, source_group_capacity)

    if len(groups) > max_speech_groups:
        failures.append("speech_group_count")
        details.append(f"speech groups={len(groups)} exceeds {max_speech_groups}")
    elif len(groups) > MAX_SPEECH_GROUPS:
        warnings.append("source_matched_extra_speech_group")

    seen_ids = set()
    for index, group in enumerate(groups, start=1):
        group_id = str(_group_value(group, "id", f"speech{index}")).strip()
        if not group_id or group_id in seen_ids:
            failures.append("speech_group_ids")
            details.append(f"invalid or duplicate speech group id: {group_id!r}")
        seen_ids.add(group_id)

        start = _group_value(group, "target_start")
        end = _group_value(group, "target_end")
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, (int, float))
            or not isinstance(end, (int, float))
            or start < 0
            or end > part_duration
            or end <= start
        ):
            failures.append("speech_group_time")
            details.append(f"{group_id} has invalid target time {start!r}-{end!r}")
            continue

        line = str(_group_value(group, "line", "")).strip()
        units = spoken_units(line)
        duration = float(end) - float(start)
        cps = units / duration if duration else float("inf")
        allowed_group_cps = MAX_GROUP_CHARS_PER_SECOND
        source_group_units = _group_value(group, "source_spoken_units")
        source_group_duration = _group_value(group, "source_duration_seconds")
        group_expansion = _group_value(
            group,
            "allowed_localized_expansion_units",
            0,
        )
        if (
            isinstance(source_group_units, int)
            and not isinstance(source_group_units, bool)
            and source_group_units >= 0
            and isinstance(source_group_duration, (int, float))
            and not isinstance(source_group_duration, bool)
            and source_group_duration > 0
            and isinstance(group_expansion, int)
            and not isinstance(group_expansion, bool)
            and group_expansion >= 0
        ):
            allowed_group_cps = max(
                allowed_group_cps,
                (source_group_units + group_expansion)
                / float(source_group_duration),
            )
        max_allowed_group_cps = max(
            max_allowed_group_cps,
            allowed_group_cps,
        )
        total_units += units
        max_cps = max(max_cps, cps)
        intervals.append((float(start), float(end), group_id))

        if not line:
            failures.append("speech_group_line")
            details.append(f"{group_id} has no spoken line")
        if cps > allowed_group_cps + 1e-6:
            failures.append("max_group_chars_per_second")
            details.append(
                f"{group_id}={cps:.2f} units/s exceeds {allowed_group_cps:.2f}"
            )

        speaker_kind = str(_group_value(group, "speaker_kind", "")).strip().lower()
        if speaker_kind == "sync":
            allowed_sync_units = MAX_SYNC_LINE_UNITS
            source_max_sync_units = _group_value(
                group,
                "source_max_sync_units",
            )
            if (
                isinstance(source_max_sync_units, int)
                and not isinstance(source_max_sync_units, bool)
                and source_max_sync_units >= 0
                and isinstance(group_expansion, int)
                and not isinstance(group_expansion, bool)
                and group_expansion >= 0
            ):
                allowed_sync_units = max(
                    allowed_sync_units,
                    source_max_sync_units + group_expansion,
                )
            max_allowed_sync_units = max(
                max_allowed_sync_units,
                allowed_sync_units,
            )
            sentence_units = [
                spoken_units(sentence)
                for sentence in SYNC_SENTENCE_SPLIT_RE.split(line)
                if sentence.strip()
            ]
            group_max_sync_units = max(sentence_units, default=0)
            max_sync_units = max(max_sync_units, group_max_sync_units)
            if group_max_sync_units > allowed_sync_units:
                failures.append("sync_line_units")
                details.append(
                    f"{group_id} sync sentence units={group_max_sync_units} exceeds {allowed_sync_units}"
                )

    intervals.sort()
    speech_seconds = 0.0
    previous_end = 0.0
    for start, end, group_id in intervals:
        if start < previous_end - 1e-6:
            failures.append("speech_group_overlap")
            details.append(f"{group_id} overlaps a previous speech group")
        speech_seconds += end - start
        previous_end = max(previous_end, end)

    silence_seconds = max(0.0, float(part_duration) - speech_seconds)
    min_silence_seconds = MIN_SILENCE_SECONDS
    if (
        isinstance(source_pause_seconds, (int, float))
        and not isinstance(source_pause_seconds, bool)
        and source_pause_seconds >= 0
    ):
        min_silence_seconds = min(
            MIN_SILENCE_SECONDS,
            float(source_pause_seconds),
        )
    max_total_units = MAX_TOTAL_SPOKEN_UNITS
    if isinstance(source_units_per_second, (int, float)) and not isinstance(
        source_units_per_second, bool
    ):
        source_matched_units = round(
            min(float(source_units_per_second), MAX_GROUP_CHARS_PER_SECOND)
            * (float(part_duration) - MIN_SILENCE_SECONDS)
        )
        max_total_units = min(
            MAX_SOURCE_MATCHED_TOTAL_SPOKEN_UNITS,
            max(MAX_TOTAL_SPOKEN_UNITS, source_matched_units),
        )
    if (
        isinstance(source_total_spoken_units, int)
        and not isinstance(source_total_spoken_units, bool)
        and source_total_spoken_units >= 0
        and isinstance(allowed_localized_expansion_units, int)
        and not isinstance(allowed_localized_expansion_units, bool)
        and allowed_localized_expansion_units >= 0
    ):
        max_total_units = min(
            MAX_SOURCE_MATCHED_TOTAL_SPOKEN_UNITS,
            max(
                max_total_units,
                source_total_spoken_units + allowed_localized_expansion_units,
            ),
        )
    if total_units > max_total_units:
        failures.append("total_spoken_units")
        details.append(
            f"spoken units={total_units} exceeds {max_total_units} per 15 seconds"
        )
    elif total_units > MAX_TOTAL_SPOKEN_UNITS:
        warnings.append("source_matched_high_density")
    if silence_seconds < min_silence_seconds - 1e-6:
        failures.append("silence_seconds")
        details.append(
            f"silence={silence_seconds:.2f}s is below {min_silence_seconds:.2f}s"
        )

    failed_rules = list(dict.fromkeys(failures))
    return {
        "overall": "FAIL" if failed_rules else "PASS",
        "failed_rules": failed_rules,
        "warnings": warnings,
        "details": details,
        "metrics": {
            "speech_group_count": len(groups),
            "total_spoken_units": total_units,
            "speech_seconds": round(speech_seconds, 3),
            "silence_seconds": round(silence_seconds, 3),
            "max_group_chars_per_second": round(max_cps, 3),
            "max_sync_line_units": max_sync_units,
        },
        "limits": {
            "max_speech_groups": max_speech_groups,
            "default_max_speech_groups": MAX_SPEECH_GROUPS,
            "max_source_matched_speech_groups": MAX_SOURCE_MATCHED_SPEECH_GROUPS,
            "max_total_spoken_units": max_total_units,
            "default_max_total_spoken_units": MAX_TOTAL_SPOKEN_UNITS,
            "max_source_matched_total_spoken_units": MAX_SOURCE_MATCHED_TOTAL_SPOKEN_UNITS,
            "max_group_chars_per_second": round(max_allowed_group_cps, 3),
            "default_max_group_chars_per_second": MAX_GROUP_CHARS_PER_SECOND,
            "min_silence_seconds": round(min_silence_seconds, 3),
            "default_min_silence_seconds": MIN_SILENCE_SECONDS,
            "max_sync_line_units": max_allowed_sync_units,
            "default_max_sync_line_units": MAX_SYNC_LINE_UNITS,
        },
    }
