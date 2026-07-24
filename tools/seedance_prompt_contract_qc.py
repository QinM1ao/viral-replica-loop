#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from speech_budget import assess_speech_groups, spoken_units
from presenter_gender import presenter_gender_pair, presenter_gender_text_issues


STATUS_ORDER = {"PASS": 0, "FAIL": 1, "STOP": 2}
TIME_RANGE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:-|–|—|~|至|到)\s*(\d+(?:\.\d+)?)\s*(?:秒|s|S)"
)
PANEL_RANGE_RE = re.compile(
    r"分镜\s*(\d+)\s*(?:(?:-|\u2013|\u2014|~|至|到)\s*(?:分镜\s*)?(\d+))?"
)
PART_RE = re.compile(r"^##\s*Part\s*([0-9]+)\b", re.IGNORECASE | re.MULTILINE)
EXECUTION_BLOCK_RE = re.compile(
    r"(?m)^(\d+(?:\.\d+)?)\s*(?:-|\u2013|\u2014|~|至|到)\s*(\d+(?:\.\d+)?)\s*秒\s*[｜|]\s*"
    r"Shot\s*0*(\d+)\s*(?:(?:-|\u2013|\u2014|~|至|到)\s*(?:Shot\s*)?0*(\d+))?(?:延续)?\s*$",
    re.IGNORECASE,
)
QUOTE_RE = re.compile(r"“[^”]{2,}”|\{[^{}\n]{2,}\}")
CANONICAL_VOICE_LINE_RE = re.compile(
    r"^声音：(?:无台词|[^“”{}\n；]+\{[^{}\n]+\}(?:；[^“”{}\n；]+\{[^{}\n]+\})*)。$"
)
CANONICAL_SFX_LINE_RE = re.compile(
    r"^音效：<[^<>；;\n]+>(?:；<[^<>；;\n]+>)*$"
)
DURATION_DECLARATION_RE = re.compile(
    r"生成(?:一条)?(?:约)?\s*(\d+(?:\.\d+)?)\s*秒",
    re.IGNORECASE,
)
MAX_EXECUTION_BLOCK_PANELS = 5
MAX_GLOBAL_RULE_CHARS = 180

PROFILE_EFFECT_WEAKENING_PHRASES = {
    "孔凤春清洁泥膜": ["保留真实毛孔", "保留真实皮肤纹理"],
}

BANNED_PHRASES = [
    "Part1最终分镜图",
    "Part2最终分镜图",
    "Part3最终分镜图",
    "AI改好分镜图",
    "current-job",
    "source rhythm board",
    "contact sheet",
    "素材角色表",
]

UNBOUND_SOURCE_CONTEXT_PHRASES = [
    "原片",
    "源片",
    "原视频",
    "按分镜",
    "分镜手位",
    "source video",
    "source rhythm",
    "source beat",
]

RESOLVED_OBJECT_NEGATIVE_PROMPT_PATTERNS = [
    re.compile(r"前景[^，。；\n]{0,16}(?:无产品|不陈列产品)"),
    re.compile(r"不出现旧(?:人物|产品|字样)(?:、旧(?:人物|产品|字样))*"),
]

AMBIGUOUS_KEY_SHOT_PATTERNS = [
    "或者",
    " or ",
    "或瓶身",
    "手持瓶身或",
    "掌心或",
    "产品或",
    "手机或",
    "台面或",
]

SPEAKER_LABELS = [
    "男主播说",
    "女主播说",
    "男主说",
    "女主说",
    "主播说",
    "人物说",
    "旁白",
    "画外音旁白",
    "画面内同期",
    "同期口播",
    "男配同期声",
    "同事同期声",
    "群体反应",
]

SOURCE_SPEAKER_TERMS = [
    "source speaker",
    "source line",
    "source voice",
    "source spoken",
    "原片说话",
    "原片声音",
    "原视频说话",
    "原视频声音",
    "源片说话",
    "源片声音",
]

TARGET_SPEAKER_TERMS = [
    "target speaker",
    "target line",
    "target voice",
    "target spoken",
    "目标说话",
    "目标声音",
    "改写说话",
    "复刻说话",
]


def normalize_range(start, end):
    return (round(float(start), 1), round(float(end), 1))


def display_range(time_range):
    start, end = time_range
    return f"{start:.1f}-{end:.1f}s"


def add_check(checks, name, status, detail):
    checks.append({"name": name, "status": status, "detail": detail})


def overall_status(checks):
    if not checks:
        return "STOP"
    return max((check["status"] for check in checks), key=lambda value: STATUS_ORDER[value])


def read_text(path):
    try:
        return path.read_text(encoding="utf-8"), None
    except OSError as exc:
        return None, str(exc)


def default_prompt_files(root, job_id):
    output_dir = root / "output" / job_id
    web_prompts = sorted((output_dir / "seedance_web_final" / "prompts").glob("*.txt"))
    if web_prompts:
        return web_prompts
    return sorted((output_dir / "seedance").glob("seedance_part*_prompt.txt"))


def is_managed_prompt_output(root, job_id, path):
    job_dir = (root / "output" / job_id).resolve()
    path = path.resolve()
    canonical_dir = job_dir / "seedance"
    if path.parent == canonical_dir and re.fullmatch(
        r"seedance_part\d+_prompt\.txt", path.name, re.IGNORECASE
    ):
        return True
    web_prompt_dir = job_dir / "seedance_web_final" / "prompts"
    if path.parent == web_prompt_dir and path.suffix.lower() == ".txt":
        return True
    web_final_dir = job_dir / "seedance_web_final"
    if (
        path.parent.parent == web_final_dir
        and re.fullmatch(r"Part\d+_上传素材", path.parent.name, re.IGNORECASE)
        and re.fullmatch(r"00_.+\.txt", path.name, re.IGNORECASE)
    ):
        return True
    return False


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compilation_manifest_prompt_bindings(root, job_id):
    path = root / "output" / job_id / "seedance" / "part_compilation_manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, f"missing compilation manifest: {path}"
    except (OSError, json.JSONDecodeError) as exc:
        return {}, f"unreadable compilation manifest: {exc}"
    if manifest.get("job_id") != job_id:
        return {}, f"compilation manifest job_id does not match {job_id}"
    director_plan_path = root / "output" / job_id / "seedance" / "director_plan.json"
    expected_plan_sha256 = str(manifest.get("director_plan_sha256", "")).strip()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_plan_sha256):
        return {}, f"compilation manifest has no valid director_plan_sha256: {path}"
    try:
        actual_plan_sha256 = file_sha256(director_plan_path)
    except OSError as exc:
        return {}, f"cannot hash current director plan: {exc}"
    if actual_plan_sha256 != expected_plan_sha256:
        return {}, (
            "compilation manifest is stale for the current director plan: "
            f"expected={expected_plan_sha256}, actual={actual_plan_sha256}"
        )
    by_part = {}
    for part in manifest.get("parts") or []:
        part_no = infer_part_number(Path(str(part.get("part_id", ""))), 0)
        if part_no <= 0:
            continue
        prompt_files = {}
        for item in part.get("files") or []:
            relative_path = str(item.get("path", "")).strip()
            sha256 = str(item.get("sha256", "")).strip()
            if (
                relative_path.lower().endswith("_prompt.txt")
                and re.fullmatch(r"[0-9a-f]{64}", sha256)
            ):
                prompt_files[Path(relative_path).as_posix()] = sha256
        if prompt_files:
            by_part[part_no] = prompt_files
    if not by_part:
        return {}, f"compilation manifest has no rendered prompt bindings: {path}"
    return by_part, None


def infer_part_number(path, fallback):
    match = re.search(r"part\s*([0-9]+)|Part([0-9]+)", path.name, re.IGNORECASE)
    if not match:
        return fallback
    return int(next(group for group in match.groups() if group))


def parse_time_ranges(text):
    return [normalize_range(match.group(1), match.group(2)) for match in TIME_RANGE_RE.finditer(text)]


def parse_panel_ranges(text):
    ranges = []
    for match in PANEL_RANGE_RE.finditer(text or ""):
        start = int(match.group(1))
        end = int(match.group(2) or start)
        ranges.append((start, end))
    return ranges


def display_panel_range(panel_range):
    start, end = panel_range
    return f"分镜{start}" if start == end else f"分镜{start}-{end}"


def split_markdown_row(line):
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def header_matches(cell, terms):
    lowered = cell.lower()
    compact = lowered.replace(" ", "")
    return any(term in lowered or term.replace(" ", "") in compact for term in terms)


def find_header_index(headers, terms):
    for index, header in enumerate(headers):
        if header_matches(header, terms):
            return index
    return None


def table_indices(headers):
    target_time_index = find_header_index(headers, ["target time", "目标时间"])
    storyboard_panels_index = find_header_index(
        headers, ["storyboard panels", "storyboard panel", "分镜编号", "分镜范围", "分镜"]
    )
    source_time_index = find_header_index(headers, ["source time", "原片时间", "原视频时间", "源片时间"])
    source_visual_index = find_header_index(headers, ["source visual", "原片画面", "原视频画面", "源片画面"])
    target_visual_index = find_header_index(headers, ["target visual", "目标画面", "改写画面", "复刻画面"])
    source_speaker_index = find_header_index(headers, SOURCE_SPEAKER_TERMS)
    target_speaker_index = find_header_index(headers, TARGET_SPEAKER_TERMS)
    legacy_speaker_index = find_header_index(headers, ["speaker mode", "speaker", "说话方式", "声音方式"])
    speech_group_index = find_header_index(headers, ["speech group", "说话组", "口播组", "声音组"])
    speech_time_index = find_header_index(headers, ["speech time", "说话时间", "口播时间", "声音时间"])

    if target_speaker_index is None:
        target_speaker_index = legacy_speaker_index

    return {
        "target_time": 0 if target_time_index is None else target_time_index,
        "storyboard_panels": storyboard_panels_index,
        "source_time": 1 if source_time_index is None else source_time_index,
        "source_visual_action": 2 if source_visual_index is None else source_visual_index,
        "source_speaker_mode_line": source_speaker_index,
        "target_visual_action": 3 if target_visual_index is None else target_visual_index,
        "target_speaker_mode_line": 4 if target_speaker_index is None else target_speaker_index,
        "speech_group": speech_group_index,
        "speech_time": speech_time_index,
    }


def safe_cell(cells, index, default=""):
    if index is None or index >= len(cells):
        return default
    return cells[index]


def speaker_kind(text):
    if not text or not text.strip():
        return "missing"
    lowered = text.lower()
    if any(term in text for term in ["群体反应", "群体同期"]):
        return "group"
    if any(term in text for term in ["画外音", "旁白"]) or any(
        term in lowered for term in ["voiceover", "voice-over", "narration", "off-screen"]
    ):
        return "narration"
    if any(term in text for term in ["画面内同期", "同期口播", "同期声", "口播"]) or re.search(
        r"(?:男主播|女主播|男主|女主|主播|人物)说", text
    ) or any(
        term in lowered for term in ["sync", "lip-sync", "on-camera", "in-frame", "says"]
    ):
        return "sync"
    if any(term in text for term in ["无台词", "不说话", "停止说话", "只留环境声"]) or any(
        term in lowered for term in ["no dialogue", "silence", "silent"]
    ):
        return "silent"
    return "unknown"


def mode_label(kind):
    return {
        "narration": "旁白",
        "sync": "口播",
        "group": "群体反应",
        "silent": "无台词",
        "missing": "缺失",
        "unknown": "未知",
    }.get(kind, kind)


def first_quote(text):
    match = QUOTE_RE.search(text or "")
    return match.group(0) if match else ""


def quote_text(value):
    return str(value or "").strip().strip("“”{}")


def spoken_prompt_quotes(text):
    spoken = []
    for line in text.splitlines():
        for match in QUOTE_RE.finditer(line):
            before = line[: match.start()]
            content = quote_text(match.group(0))
            if content in SPEAKER_LABELS:
                continue
            if any(label in before for label in SPEAKER_LABELS):
                spoken.append(content)
    return spoken


def check_spoken_product_anchor(anchor, prompt_text_by_part):
    if not isinstance(anchor, dict):
        return None
    if anchor.get("enabled") is False:
        return None
    full_name = str(anchor.get("full_name", "")).strip()
    part_match = re.search(r"(\d+)$", str(anchor.get("part_id", "")))
    if not full_name or not part_match:
        return False, "anchor requires full_name and numbered part_id"
    anchor_part = int(part_match.group(1))
    if anchor_part not in prompt_text_by_part:
        return None
    spoken = [
        (part_no, line)
        for part_no, text in prompt_text_by_part.items()
        for line in spoken_prompt_quotes(text)
    ]
    full_name_count = sum(line.count(full_name) for _part_no, line in spoken)
    anchor_lines = [
        line for part_no, line in spoken if part_no == anchor_part and full_name in line
    ]
    passed = bool(anchor_lines)
    detail = (
        f"full_name_count={full_name_count}, anchor_part=part{anchor_part}, "
        f"anchor_mentions={len(anchor_lines)}; total count and sentence placement "
        "are source-locked by director-plan fidelity"
    )
    return passed, detail


def prompt_speaker_kind_for_quote(text, quote):
    content = quote_text(quote)
    matches = list(re.finditer(re.escape(content), text))
    if not matches:
        return "missing"
    label_re = re.compile(
        r"(男主播说|女主播说|男主说|女主说|主播说|人物说|画外音旁白|画外音|旁白|画面内同期口播|画面内同期|同期口播|同期声|口播|男配同期声|同事同期声|群体反应|voiceover|voice-over|narration|off-screen|on-camera|in-frame|lip-sync|sync)",
        re.IGNORECASE,
    )
    for match in matches:
        window = text[max(0, match.start() - 120) : match.start()]
        label_matches = list(label_re.finditer(window))
        if label_matches:
            return speaker_kind(label_matches[-1].group(0))
    return "unknown"


def parse_execution_blocks(text):
    matches = list(EXECUTION_BLOCK_RE.finditer(text))
    blocks = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        panel_start = int(match.group(3))
        panel_end = int(match.group(4) or panel_start)
        blocks.append(
            {
                "target_time": normalize_range(match.group(1), match.group(2)),
                "storyboard_panels": (panel_start, panel_end),
                "text": text[match.end() : end].strip(),
            }
        )
    return blocks


def extract_global_rules(text):
    first_block = EXECUTION_BLOCK_RE.search(text)
    prefix = text[: first_block.start()] if first_block else text
    lines = []
    for raw_line in prefix.splitlines():
        line = raw_line.strip()
        if not line or line == "参考图角色：":
            continue
        if line.startswith(("@图片", "@音频", "音频")):
            continue
        lines.append(line)
    return "".join(lines)


def range_contains(container, item):
    return container[0] <= item[0] and container[1] >= item[1]


def parse_shot_line_map(path):
    text, error = read_text(path)
    if text is None:
        return {}, error

    matches = list(PART_RE.finditer(text))
    parts = {}
    for index, match in enumerate(matches):
        part_no = int(match.group(1))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section = text[start:end]
        rows = []
        indices = table_indices([])
        for line in section.splitlines():
            stripped = line.strip()
            if not stripped.startswith("|"):
                continue
            cells = split_markdown_row(stripped)
            if "---" in stripped:
                continue
            if any(header_matches(cell, ["target time", "目标时间"]) for cell in cells):
                indices = table_indices(cells)
                continue
            if len(cells) < 5:
                continue
            time_match = TIME_RANGE_RE.search(safe_cell(cells, indices["target_time"]))
            if not time_match:
                continue
            target_speaker = safe_cell(cells, indices["target_speaker_mode_line"])
            speech_time_text = safe_cell(cells, indices["speech_time"])
            speech_time_match = TIME_RANGE_RE.search(speech_time_text)
            rows.append(
                {
                    "target_time": normalize_range(time_match.group(1), time_match.group(2)),
                    "storyboard_panels": (
                        parse_panel_ranges(safe_cell(cells, indices["storyboard_panels"])) or [None]
                    )[0],
                    "source_time": safe_cell(cells, indices["source_time"]),
                    "source_visual_action": safe_cell(cells, indices["source_visual_action"]),
                    "source_speaker_mode_line": safe_cell(cells, indices["source_speaker_mode_line"]),
                    "target_visual_action": safe_cell(cells, indices["target_visual_action"]),
                    "target_speaker_mode_line": target_speaker,
                    "speaker_mode_line": target_speaker,
                    "speech_group": safe_cell(cells, indices["speech_group"]),
                    "speech_group_column_present": indices["speech_group"] is not None,
                    "speech_time": (
                        normalize_range(speech_time_match.group(1), speech_time_match.group(2))
                        if speech_time_match
                        else None
                    ),
                }
            )
        parts[part_no] = rows
    return parts, None


def speech_groups_from_rows(map_rows):
    explicit = any(row.get("speech_group_column_present") for row in map_rows)
    groups = []
    by_id = {}
    errors = []
    for index, row in enumerate(map_rows, start=1):
        source_kind = speaker_kind(row.get("source_speaker_mode_line", ""))
        target_kind = speaker_kind(row.get("target_speaker_mode_line", ""))
        quote = quote_text(first_quote(row.get("target_speaker_mode_line", "")))
        group_id = str(row.get("speech_group", "")).strip()

        if explicit:
            if source_kind == "silent":
                if group_id:
                    errors.append(f"silent row {display_range(row['target_time'])} has {group_id}")
                continue
            if not group_id:
                errors.append(f"spoken row {display_range(row['target_time'])} has no speech group")
                continue
            if group_id not in by_id:
                speech_time = row.get("speech_time")
                if not speech_time or not quote:
                    errors.append(f"{group_id} first row needs speech time and one quoted line")
                    continue
                group = {
                    "id": group_id,
                    "target_start": speech_time[0],
                    "target_end": speech_time[1],
                    "speaker_kind": target_kind,
                    "line": quote,
                }
                by_id[group_id] = group
                groups.append(group)
            else:
                group = by_id[group_id]
                if quote and quote != group["line"]:
                    errors.append(f"{group_id} contains more than one spoken line")
                if target_kind != group["speaker_kind"]:
                    errors.append(f"{group_id} changes speaker mode")
        elif quote:
            start, end = row["target_time"]
            groups.append(
                {
                    "id": f"legacy-speech-{index}",
                    "target_start": start,
                    "target_end": end,
                    "speaker_kind": target_kind,
                    "line": quote,
                }
            )
    return groups, errors


def source_rate_from_rows(map_rows):
    spoken_rows = [
        row
        for row in map_rows
        if speaker_kind(row.get("source_speaker_mode_line", "")) not in {"silent", "missing", "unknown"}
    ]
    intervals = []
    units = 0
    for row in spoken_rows:
        match = TIME_RANGE_RE.search(row.get("source_time", ""))
        quote = quote_text(first_quote(row.get("source_speaker_mode_line", "")))
        if not match or not quote:
            continue
        intervals.append(normalize_range(match.group(1), match.group(2)))
        units += spoken_units(quote)
    if not intervals:
        return None
    duration = max(end for _start, end in intervals) - min(start for start, _end in intervals)
    return units / duration if duration > 0 else None


def source_total_units_from_rows(map_rows):
    return sum(
        spoken_units(quote_text(first_quote(row.get("source_speaker_mode_line", ""))))
        for row in map_rows
        if speaker_kind(row.get("source_speaker_mode_line", ""))
        not in {"silent", "missing", "unknown"}
    )


def allowed_localized_expansion_from_part(part):
    return max(0, sum(
        spoken_units(edit.get("to", "")) - spoken_units(edit.get("from", ""))
        for group in (part or {}).get("speech_groups") or []
        for edit in group.get("line_edits") or []
        if isinstance(edit, dict)
    ))


def source_pause_seconds_from_part(part):
    return sum(
        max(0.0, float(beat.get("source_pause_after_seconds") or 0.0))
        for beat in (part or {}).get("beats") or []
        if speaker_kind(beat.get("source_speaker_mode", ""))
        not in {"silent", "missing", "unknown"}
    )


def source_group_capacities_from_part(part):
    part = part or {}
    beats = {
        str(beat.get("id") or ""): beat
        for beat in part.get("beats") or []
        if isinstance(beat, dict)
    }
    capacities = {}
    for group in part.get("speech_groups") or []:
        if not isinstance(group, dict):
            continue
        group_id = str(group.get("id") or "").strip()
        bound = [
            beats[beat_id]
            for beat_id in group.get("beat_ids") or []
            if beat_id in beats
        ]
        source_text = "".join(
            str(beat.get("source_line", ""))
            for beat in bound
        )
        capacities[group_id] = {
            "target_start": group.get("target_start"),
            "target_end": group.get("target_end"),
            "source_spoken_units": sum(
                spoken_units(beat.get("source_line", ""))
                for beat in bound
            ),
            "source_duration_seconds": sum(
                max(
                    0.0,
                    float(beat.get("source_end") or 0.0)
                    - float(beat.get("source_start") or 0.0)
                    - max(
                        0.0,
                        float(beat.get("source_pause_after_seconds") or 0.0),
                    ),
                )
                for beat in bound
            ),
            "source_max_sync_units": max(
                (
                    spoken_units(sentence)
                    for sentence in re.split(r"[。！？!?；;]+", source_text)
                    if sentence.strip()
                ),
                default=0,
            ),
            "allowed_localized_expansion_units": max(0, sum(
                spoken_units(edit.get("to", ""))
                - spoken_units(edit.get("from", ""))
                for edit in group.get("line_edits") or []
                if isinstance(edit, dict)
            )),
        }
    return capacities


def source_speech_group_count_from_rows(map_rows):
    count = 0
    previous_kind = None
    for row in map_rows:
        kind = speaker_kind(row.get("source_speaker_mode_line", ""))
        if kind == "silent":
            previous_kind = None
            continue
        if kind in {"missing", "unknown"}:
            continue
        if kind != previous_kind:
            count += 1
        previous_kind = kind
    return count


def source_spoken_beat_count_from_rows(map_rows):
    return sum(
        1
        for row in map_rows
        if speaker_kind(row.get("source_speaker_mode_line", ""))
        not in {"silent", "missing", "unknown"}
    )


def check_prompt(
    path,
    part_no,
    text,
    map_rows,
    target_presenter_gender="",
    product_name="",
    plan_version=0,
    allowed_localized_expansion_units=0,
    source_group_capacities=None,
    source_pause_seconds=None,
):
    checks = []
    metrics = {
        "part": part_no,
        "prompt_chars": len(text.strip()),
        "map_rows": len(map_rows),
    }
    duration_match = DURATION_DECLARATION_RE.search(text)
    declared_duration = float(duration_match.group(1)) if duration_match else 15.0
    metrics["declared_duration_seconds"] = declared_duration

    gender_issues = presenter_gender_text_issues(text, target_presenter_gender)
    add_check(
        checks,
        f"part{part_no}_presenter_gender_consistent",
        "PASS" if not gender_issues else "FAIL",
        f"target={target_presenter_gender}; presenter terms match"
        if not gender_issues
        else f"target={target_presenter_gender}; " + "; ".join(gender_issues),
    )

    required_terms = ["参考图角色", "@图片1", "@图片2"]
    for term in required_terms:
        add_check(
            checks,
            f"part{part_no}_has_{term}",
            "PASS" if term in text else "FAIL",
            f"`{term}` {'found' if term in text else 'missing'}",
        )

    if plan_version >= 5:
        reference_lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip().startswith("@图片")
        ]
        standard_reference_preamble = bool(reference_lines) and all(
            "定义为" in line
            and any(term in line for term in ("只控制", "只锁定"))
            and "不传递" in line
            for line in reference_lines
        )
        standard_reference_preamble = (
            standard_reference_preamble and "控制校准" not in text
        )
        add_check(
            checks,
            f"part{part_no}_standard_reference_preamble",
            "PASS" if standard_reference_preamble else "FAIL",
            "all image roles use definition, lock/control, and exclusion statements"
            if standard_reference_preamble
            else "v5 image roles must use 定义为 + 只控制/只锁定 + 不传递",
        )

    no_subtitles = "无字幕" in text
    add_check(
        checks,
        f"part{part_no}_no_subtitles",
        "PASS" if no_subtitles else "FAIL",
        "`无字幕` found" if no_subtitles else "`无字幕` missing",
    )
    no_bgm = (
        "不生成任何背景音乐" in text
        or "无背景音乐" in text
        or "禁止BGM" in text
        or "无BGM" in text
    )
    add_check(
        checks,
        f"part{part_no}_no_bgm",
        "PASS" if no_bgm else "FAIL",
        "background music is explicitly disabled" if no_bgm else "no explicit no-BGM rule",
    )

    weakening_hits = [
        phrase
        for phrase in PROFILE_EFFECT_WEAKENING_PHRASES.get(product_name, [])
        if phrase in text
    ]
    add_check(
        checks,
        f"part{part_no}_profile_effect_not_weakened",
        "PASS" if not weakening_hits else "FAIL",
        f"product={product_name or 'generic'}; no profile-specific weakening phrase"
        if not weakening_hits
        else f"product={product_name}; hits={weakening_hits}",
    )

    global_rules = extract_global_rules(text)
    metrics["global_rule_chars"] = len(global_rules)
    add_check(
        checks,
        f"part{part_no}_compact_global_rules",
        "PASS" if len(global_rules) <= MAX_GLOBAL_RULE_CHARS else "FAIL",
        f"chars={len(global_rules)}, max={MAX_GLOBAL_RULE_CHARS}",
    )

    blocks = parse_execution_blocks(text)
    metrics["execution_block_count"] = len(blocks)
    add_check(
        checks,
        f"part{part_no}_shot_range_blocks",
        "PASS" if 3 <= len(blocks) <= 8 else "FAIL",
        f"blocks={len(blocks)}, required=3..8",
    )
    malformed_blocks = []
    for index, block in enumerate(blocks, start=1):
        missing = [label for label in ("画面：", "声音：") if label not in block["text"]]
        if missing:
            malformed_blocks.append(f"block {index} missing {','.join(missing)}")
    add_check(
        checks,
        f"part{part_no}_blocks_bind_visual_voice_optional_sfx",
        "PASS" if blocks and not malformed_blocks else "FAIL",
        "every block binds visual and voice; sound effects are included only when useful"
        if blocks and not malformed_blocks
        else "; ".join(malformed_blocks) or "no execution blocks",
    )
    empty_sfx_lines = re.findall(
        r"(?m)^音效：\s*(?:无|无音效|无额外音效)\s*[。.]?\s*$",
        text,
    )
    add_check(
        checks,
        f"part{part_no}_omits_empty_sound_effect_lines",
        "PASS" if not empty_sfx_lines else "FAIL",
        "no placeholder sound-effect lines"
        if not empty_sfx_lines
        else f"placeholder_count={len(empty_sfx_lines)}",
    )
    sound_lines = [
        line.strip()
        for line in text.splitlines()
        if re.match(r"^(?:声音|音效)\s*[:：]", line.strip())
    ]
    voice_lines = [
        line for line in sound_lines if re.match(r"^声音\s*[:：]", line)
    ]
    malformed_voice_lines = [
        line for line in voice_lines if not CANONICAL_VOICE_LINE_RE.fullmatch(line)
    ]
    add_check(
        checks,
        f"part{part_no}_canonical_voice_delimiters",
        "PASS" if voice_lines and not malformed_voice_lines else "FAIL",
        "spoken lines use `{...}` and silent blocks use `声音：无台词。`"
        if voice_lines and not malformed_voice_lines
        else f"malformed={malformed_voice_lines or ['missing 声音 line']}",
    )
    sfx_lines = [
        line for line in sound_lines if re.match(r"^音效\s*[:：]", line)
    ]
    malformed_sfx_lines = [
        line for line in sfx_lines if not CANONICAL_SFX_LINE_RE.fullmatch(line)
    ]
    add_check(
        checks,
        f"part{part_no}_canonical_sfx_delimiters",
        "PASS" if not malformed_sfx_lines else "FAIL",
        "sound effects use `<...>` with one wrapper per effect"
        if not malformed_sfx_lines
        else f"malformed={malformed_sfx_lines}",
    )
    oversized_blocks = [
        f"block {index} Shot {block['storyboard_panels'][0]:02d}–{block['storyboard_panels'][1]:02d}"
        for index, block in enumerate(blocks, start=1)
        if block["storyboard_panels"][1] - block["storyboard_panels"][0] + 1
        > MAX_EXECUTION_BLOCK_PANELS
    ]
    add_check(
        checks,
        f"part{part_no}_execution_block_scope",
        "PASS" if not oversized_blocks else "FAIL",
        f"each block covers at most {MAX_EXECUTION_BLOCK_PANELS} storyboard panels"
        if not oversized_blocks
        else "; ".join(oversized_blocks),
    )
    add_check(
        checks,
        f"part{part_no}_no_split_audio_execution",
        "PASS" if "声音执行" not in text else "FAIL",
        "audio is bound inside Shot ranges" if "声音执行" not in text else "found split `声音执行` section",
    )

    time_continuous = bool(blocks) and abs(blocks[0]["target_time"][0]) < 1e-6
    for previous, current in zip(blocks, blocks[1:]):
        if abs(previous["target_time"][1] - current["target_time"][0]) > 0.11:
            time_continuous = False
            break
    if blocks and abs(blocks[-1]["target_time"][1] - declared_duration) > 0.11:
        time_continuous = False
    panel_ordered = bool(blocks)
    for previous, current in zip(blocks, blocks[1:]):
        previous_start, previous_end = previous["storyboard_panels"]
        current_start, _current_end = current["storyboard_panels"]
        if current_start < previous_start or current_start > previous_end + 1:
            panel_ordered = False
            break
    add_check(
        checks,
        f"part{part_no}_ordered_continuous_execution",
        "PASS" if time_continuous and panel_ordered else "FAIL",
        f"time_continuous={time_continuous}, panel_ordered={panel_ordered}",
    )

    map_panel_ranges = [row.get("storyboard_panels") for row in map_rows]
    panel_mode = bool(map_panel_ranges) and all(map_panel_ranges)
    all_ranges = [
        block["storyboard_panels"] if panel_mode else block["target_time"]
        for block in blocks
    ]
    unique_ranges = set(all_ranges)
    metrics["time_range_count"] = len(all_ranges)
    metrics["unique_time_range_count"] = len(unique_ranges)
    metrics["visual_address_mode"] = "storyboard_panels" if panel_mode else "target_time"
    minimum_ranges = 3
    add_check(
        checks,
        f"part{part_no}_variable_time_axis",
        "PASS" if len(unique_ranges) >= minimum_ranges else "FAIL",
        f"mode={metrics['visual_address_mode']}, unique_ranges={len(unique_ranges)}, required>={minimum_ranges}",
    )

    source_target_mismatches = []
    prompt_mode_mismatches = []
    speech_groups = []
    speech_group_errors = []
    expected_lines = []

    if not map_rows:
        add_check(
            checks,
            f"part{part_no}_shot_line_map_rows",
            "STOP",
            "no shot-line map rows found for this Part",
        )
    else:
        if panel_mode:
            missing_ranges = [
                row["storyboard_panels"]
                for row in map_rows
                if not any(range_contains(block_range, row["storyboard_panels"]) for block_range in unique_ranges)
            ]
            add_check(
                checks,
                f"part{part_no}_covers_shot_line_map_panels",
                "PASS" if not missing_ranges else "FAIL",
                "all storyboard panel ranges are present"
                if not missing_ranges
                else "missing " + ", ".join(display_panel_range(item) for item in missing_ranges),
            )
        else:
            missing_ranges = [
                row["target_time"]
                for row in map_rows
                if not any(range_contains(block_range, row["target_time"]) for block_range in unique_ranges)
            ]
            add_check(
                checks,
                f"part{part_no}_covers_shot_line_map_times",
                "PASS" if not missing_ranges else "FAIL",
                "all map target ranges are present"
                if not missing_ranges
                else "missing " + ", ".join(display_range(item) for item in missing_ranges),
            )

        mixed_mode_blocks = []
        for index, block in enumerate(blocks, start=1):
            block_range = (
                block["storyboard_panels"] if panel_mode else block["target_time"]
            )
            speaker_kinds = {
                speaker_kind(row.get("target_speaker_mode_line", ""))
                for row in map_rows
                if range_contains(
                    block_range,
                    row["storyboard_panels"] if panel_mode else row["target_time"],
                )
            }
            spoken_kinds = speaker_kinds & {"narration", "sync", "group"}
            if len(spoken_kinds) > 1:
                mixed_mode_blocks.append(
                    f"block {index} mixes {', '.join(sorted(spoken_kinds))}"
                )
        add_check(
            checks,
            f"part{part_no}_execution_blocks_respect_speaker_mode_boundaries",
            "PASS" if not mixed_mode_blocks else "FAIL",
            "no execution block crosses a spoken speaker-mode boundary"
            if not mixed_mode_blocks
            else "; ".join(mixed_mode_blocks),
        )

        missing_source_modes = [
            display_range(row["target_time"])
            for row in map_rows
            if speaker_kind(row.get("source_speaker_mode_line", "")) in {"missing", "unknown"}
        ]
        add_check(
            checks,
            f"part{part_no}_source_speaker_modes_present",
            "PASS" if not missing_source_modes else "FAIL",
            "all rows include source speaker mode"
            if not missing_source_modes
            else "missing/unknown source speaker mode at " + ", ".join(missing_source_modes),
        )

        for row in map_rows:
            source_kind = speaker_kind(row.get("source_speaker_mode_line", ""))
            target_kind = speaker_kind(row.get("target_speaker_mode_line", ""))
            if source_kind in {"missing", "unknown"} or target_kind in {"missing", "unknown"}:
                source_target_mismatches.append(
                    f"{display_range(row['target_time'])}: {mode_label(source_kind)} -> {mode_label(target_kind)}"
                )
            elif source_kind != target_kind:
                source_target_mismatches.append(
                    f"{display_range(row['target_time'])}: {mode_label(source_kind)} -> {mode_label(target_kind)}"
                )
        add_check(
            checks,
            f"part{part_no}_preserves_source_speaker_modes",
            "PASS" if not source_target_mismatches else "FAIL",
            "target speaker modes match source speaker modes"
            if not source_target_mismatches
            else "; ".join(source_target_mismatches[:5]),
        )

        for row in map_rows:
            quote = first_quote(row.get("target_speaker_mode_line", ""))
            if not quote:
                continue
            expected_kind = speaker_kind(row.get("target_speaker_mode_line", ""))
            actual_kind = prompt_speaker_kind_for_quote(text, quote)
            if actual_kind != expected_kind:
                prompt_mode_mismatches.append(
                    f"{display_range(row['target_time'])} {quote}: expected {mode_label(expected_kind)}, got {mode_label(actual_kind)}"
                )
        add_check(
            checks,
            f"part{part_no}_prompt_matches_target_speaker_modes",
            "PASS" if not prompt_mode_mismatches else "FAIL",
            "prompt speaker labels match shot-line map target modes"
            if not prompt_mode_mismatches
            else "; ".join(prompt_mode_mismatches[:5]),
        )

        speech_groups, speech_group_errors = speech_groups_from_rows(map_rows)
        for group in speech_groups:
            group.update(
                (source_group_capacities or {}).get(group["id"], {})
            )
        source_rate = source_rate_from_rows(map_rows)
        source_speech_group_count = source_speech_group_count_from_rows(map_rows)
        source_spoken_beat_count = source_spoken_beat_count_from_rows(map_rows)
        budget = assess_speech_groups(
            speech_groups,
            part_duration=declared_duration,
            source_units_per_second=source_rate,
            source_speech_group_count=source_speech_group_count,
            source_spoken_beat_count=source_spoken_beat_count,
            source_total_spoken_units=source_total_units_from_rows(map_rows),
            allowed_localized_expansion_units=allowed_localized_expansion_units,
            source_pause_seconds=source_pause_seconds,
        )
        metrics.update(budget["metrics"])
        metrics["source_units_per_second"] = round(source_rate, 3) if source_rate is not None else None
        metrics["source_speech_group_count"] = source_speech_group_count
        metrics["source_spoken_beat_count"] = source_spoken_beat_count
        budget_detail = (
            f"groups={budget['metrics']['speech_group_count']}, "
            f"units={budget['metrics']['total_spoken_units']}, "
            f"max_rate={budget['metrics']['max_group_chars_per_second']:.2f}/s, "
            f"silence={budget['metrics']['silence_seconds']:.2f}s, "
            f"source_rate={source_rate:.2f}/s, "
            f"max_units={budget['limits']['max_total_spoken_units']}, "
            f"max_groups={budget['limits']['max_speech_groups']}"
            if source_rate is not None
            else (
                f"groups={budget['metrics']['speech_group_count']}, "
                f"units={budget['metrics']['total_spoken_units']}, "
                f"max_rate={budget['metrics']['max_group_chars_per_second']:.2f}/s, "
                f"silence={budget['metrics']['silence_seconds']:.2f}s, "
                f"source_rate=missing, max_units={budget['limits']['max_total_spoken_units']}, "
                f"max_groups={budget['limits']['max_speech_groups']}"
            )
        )
        if budget["warnings"]:
            budget_detail += f"; warnings={budget['warnings']}"
        if budget["overall"] != "PASS":
            budget_detail += f"; failed={budget['failed_rules']}; details={budget['details']}"
        add_check(
            checks,
            f"part{part_no}_speech_groups_well_formed",
            "PASS" if not speech_group_errors else "FAIL",
            "speech groups are explicit and bound"
            if not speech_group_errors
            else "; ".join(speech_group_errors[:5]),
        )
        add_check(
            checks,
            f"part{part_no}_speech_budget",
            budget["overall"],
            budget_detail,
        )

        expected_lines = [group["line"] for group in speech_groups]
        actual_lines = spoken_prompt_quotes(text)
        add_check(
            checks,
            f"part{part_no}_prompt_has_exact_speech_lines",
            "PASS" if Counter(actual_lines) == Counter(expected_lines) else "FAIL",
            f"expected={expected_lines}, actual={actual_lines}",
        )

    banned_hits = [phrase for phrase in BANNED_PHRASES if phrase in text]
    add_check(
        checks,
        f"part{part_no}_no_loop_only_labels",
        "PASS" if not banned_hits else "FAIL",
        f"hits={banned_hits}",
    )

    unbound_source_hits = [
        phrase for phrase in UNBOUND_SOURCE_CONTEXT_PHRASES if phrase.lower() in text.lower()
    ]
    add_check(
        checks,
        f"part{part_no}_no_unbound_source_context",
        "PASS" if not unbound_source_hits else "FAIL",
        f"hits={unbound_source_hits}",
    )

    resolved_object_negative_hits = [
        match.group(0)
        for pattern in RESOLVED_OBJECT_NEGATIVE_PROMPT_PATTERNS
        for match in pattern.finditer(text)
    ]
    add_check(
        checks,
        f"part{part_no}_no_resolved_object_negative_prompts",
        "PASS" if not resolved_object_negative_hits else "FAIL",
        "storyboard-resolved object removals are omitted from model-facing prompts"
        if not resolved_object_negative_hits
        else f"hits={resolved_object_negative_hits}",
    )

    ambiguous_hits = [pattern for pattern in AMBIGUOUS_KEY_SHOT_PATTERNS if pattern in text]
    add_check(
        checks,
        f"part{part_no}_no_ambiguous_key_shot_alternatives",
        "PASS" if not ambiguous_hits else "FAIL",
        f"hits={ambiguous_hits}",
    )

    role_lines = [line.strip() for line in text.splitlines()]
    storyboard_role_line = next((line for line in role_lines if "@图片1" in line), "")
    product_role_line = next((line for line in role_lines if "@图片2" in line), "")
    product_identity_bound = any(
        term in product_role_line for term in ("只校准", "锁定", "定义为")
    )
    product_defers_composition = (
        "构图" in product_role_line
        and (
            "不控制" in product_role_line
            or ("@图片1" in product_role_line and "为准" in product_role_line)
        )
    )
    storyboard_controls_execution = "@图片1" in storyboard_role_line and any(
        term in storyboard_role_line
        for term in ("控制镜头顺序", "控制 Shot 顺序", "控制Shot顺序", "产品出现节奏")
    )
    product_binding_ok = (
        bool(product_role_line)
        and product_identity_bound
        and product_defers_composition
        and storyboard_controls_execution
    )
    add_check(
        checks,
        f"part{part_no}_product_ref_identity_not_composition",
        "PASS" if product_binding_ok else "FAIL",
        "product identity is named/calibrated while storyboard controls composition and action",
    )

    motion_ok = (
        "不出现连续静止" in text
        or "保持可见动作" in text
        or "不生成冻结帧" in text
    )
    add_check(
        checks,
        f"part{part_no}_global_motion_constraint",
        "PASS" if motion_ok else "FAIL",
        "requires visible motion / no continuous static shot wording",
    )

    quotes = list(QUOTE_RE.finditer(text))
    unlabeled_quotes = []
    for quote in quotes:
        if quote_text(quote.group(0)) not in expected_lines:
            continue
        window = text[max(0, quote.start() - 100) : quote.start()]
        if not any(label in window for label in SPEAKER_LABELS):
            unlabeled_quotes.append(quote.group(0))
    metrics["quoted_line_count"] = len(quotes)
    add_check(
        checks,
        f"part{part_no}_quoted_lines_have_speaker_mode",
        "PASS" if not unlabeled_quotes else "FAIL",
        f"unlabeled={unlabeled_quotes[:3]}",
    )

    add_check(
        checks,
        f"part{part_no}_proof_shots_follow_source_speaker_mode",
        "PASS" if map_rows and not source_target_mismatches and not prompt_mode_mismatches else "FAIL",
        "product/hand/phone/proof shots use the source speaker mode instead of object-type defaults",
    )

    return {
        "path": str(path),
        "part": part_no,
        "overall": overall_status(checks),
        "checks": checks,
        "metrics": metrics,
    }


def write_md(path, report):
    lines = [
        "# Seedance Prompt Contract QC",
        "",
        f"- Overall: **{report['overall']}**",
        f"- Shot-line map: `{report.get('shot_line_map', '')}`",
        "",
        "## Global Checks",
        "",
    ]
    for check in report.get("checks", []):
        lines.append(f"- {check['status']}: `{check['name']}` - {check['detail']}")
    lines.extend(
        [
            "",
            "## Prompt Files",
            "",
        ]
    )
    for item in report["prompts"]:
        lines.append(f"### `{item['path']}`")
        lines.append("")
        lines.append(f"- Overall: **{item['overall']}**")
        metrics = item.get("metrics", {})
        lines.append(
            "- Metrics: "
            f"part={metrics.get('part')}, "
            f"chars={metrics.get('prompt_chars')}, "
            f"map_rows={metrics.get('map_rows')}, "
            f"time_ranges={metrics.get('unique_time_range_count')}, "
            f"quoted_lines={metrics.get('quoted_line_count')}"
            f", speech_groups={metrics.get('speech_group_count')}, "
            f"spoken_units={metrics.get('total_spoken_units')}, "
            f"max_rate={metrics.get('max_group_chars_per_second')}, "
            f"silence={metrics.get('silence_seconds')}"
        )
        for check in item["checks"]:
            lines.append(f"- {check['status']}: `{check['name']}` - {check['detail']}")
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def build_report(args):
    root = Path(args.root).resolve()
    prompt_files = [
        path if path.is_absolute() else root / path
        for path in (Path(value) for value in args.prompt_files)
    ]
    if not prompt_files and args.job_id:
        prompt_files = default_prompt_files(root, args.job_id)

    checks = []
    plan = {}
    target_presenter_gender = ""
    presenter_detail = "missing director plan presenter_gender"
    if args.job_id:
        plan_path = root / "output" / args.job_id / "seedance" / "director_plan.json"
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            source_gender, target_presenter_gender = presenter_gender_pair(
                plan.get("presenter_gender")
            )
            presenter_ok = (
                source_gender in {"male", "female"}
                and target_presenter_gender in {"male", "female"}
                and source_gender == target_presenter_gender
            )
            presenter_detail = (
                f"source={source_gender}, target={target_presenter_gender}, plan={plan_path}"
            )
        except (OSError, json.JSONDecodeError):
            presenter_ok = False
    else:
        presenter_ok = False
    add_check(
        checks,
        "presenter_gender_contract",
        "PASS" if presenter_ok else "STOP",
        presenter_detail,
    )
    add_check(
        checks,
        "prompt_files_present",
        "PASS" if prompt_files else "STOP",
        f"count={len(prompt_files)}",
    )
    unmanaged_prompt_files = (
        [
            str(path)
            for path in prompt_files
            if not is_managed_prompt_output(root, args.job_id, path)
        ]
        if args.job_id
        else []
    )
    add_check(
        checks,
        "prompt_files_are_managed_outputs",
        "PASS" if not unmanaged_prompt_files else "FAIL",
        "all prompt files are canonical renderer or handoff outputs"
        if not unmanaged_prompt_files
        else f"unmanaged={unmanaged_prompt_files}",
    )
    manifest_prompt_bindings, manifest_error = (
        compilation_manifest_prompt_bindings(root, args.job_id)
        if args.job_id
        else ({}, "job_id is required")
    )
    prompt_hash_errors = []
    if manifest_error is None:
        job_dir = (root / "output" / args.job_id).resolve()
        canonical_dir = job_dir / "seedance"
        for index, path in enumerate(prompt_files, start=1):
            try:
                prompt_hash = file_sha256(path)
            except OSError as exc:
                prompt_hash_errors.append(f"{path}: {exc}")
                continue
            part_no = infer_part_number(path, index)
            part_bindings = manifest_prompt_bindings.get(part_no, {})
            resolved_path = path.resolve()
            if resolved_path.parent == canonical_dir:
                relative_path = resolved_path.relative_to(job_dir).as_posix()
                expected_hash = part_bindings.get(relative_path)
                matches = expected_hash == prompt_hash
            else:
                matches = prompt_hash in set(part_bindings.values())
            if not matches:
                prompt_hash_errors.append(
                    f"{path}: part={part_no}, sha256={prompt_hash} is not compiler-bound"
                )
    add_check(
        checks,
        "prompt_files_match_compilation_manifest",
        (
            "PASS"
            if manifest_error is None and not prompt_hash_errors
            else "STOP"
            if manifest_error is not None
            else "FAIL"
        ),
        (
            "every prompt path, Part, hash, and director plan are compiler-bound"
            if manifest_error is None and not prompt_hash_errors
            else manifest_error
            if manifest_error is not None
            else "; ".join(prompt_hash_errors)
        ),
    )

    shot_line_map = Path(args.shot_line_map) if args.shot_line_map else None
    if shot_line_map is None and args.job_id:
        shot_line_map = root / "output" / args.job_id / "voiceover" / "shot_line_map.md"
    map_rows_by_part, map_error = parse_shot_line_map(shot_line_map) if shot_line_map else ({}, "missing path")
    add_check(
        checks,
        "shot_line_map_readable",
        "PASS" if map_error is None else "STOP",
        str(shot_line_map) if map_error is None else map_error,
    )

    prompt_reports = []
    prompt_text_by_part = {}
    plan_parts_by_number = {
        infer_part_number(Path(str(part.get("id") or "")), index): part
        for index, part in enumerate(plan.get("parts") or [], start=1)
        if isinstance(part, dict)
    }
    for index, path in enumerate(prompt_files, start=1):
        text, error = read_text(path)
        if text is None:
            prompt_reports.append(
                {
                    "path": str(path),
                    "part": infer_part_number(path, index),
                    "overall": "STOP",
                    "checks": [{"name": "prompt_readable", "status": "STOP", "detail": error}],
                    "metrics": {},
                }
            )
            continue
        part_no = infer_part_number(path, index)
        prompt_text_by_part[part_no] = text
        prompt_reports.append(
            check_prompt(
                path,
                part_no,
                text,
                map_rows_by_part.get(part_no, []),
                target_presenter_gender,
                str((plan.get("job") or {}).get("product_name", "")).strip(),
                int(plan.get("version") or 0),
                allowed_localized_expansion_from_part(
                    plan_parts_by_number.get(part_no)
                ),
                source_group_capacities_from_part(
                    plan_parts_by_number.get(part_no)
                ),
                source_pause_seconds_from_part(
                    plan_parts_by_number.get(part_no)
                ),
            )
        )

    anchor_result = check_spoken_product_anchor(
        plan.get("spoken_product_anchor"), prompt_text_by_part
    )
    if anchor_result is not None:
        anchor_ok, anchor_detail = anchor_result
        add_check(
            checks,
            "spoken_product_anchor_bound",
            "PASS" if anchor_ok else "FAIL",
            anchor_detail,
        )

    all_checks = checks[:]
    for item in prompt_reports:
        all_checks.extend(item["checks"])

    return {
        "overall": overall_status(all_checks),
        "checks": checks,
        "shot_line_map": str(shot_line_map) if shot_line_map else "",
        "prompts": prompt_reports,
    }


def main():
    parser = argparse.ArgumentParser(description="QC Seedance prompt structure and shot-line map coverage.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--job-id", default="")
    parser.add_argument("--stage", default="pre_seedance_pack")
    parser.add_argument("--shot-line-map", default="")
    parser.add_argument("--prompt-files", nargs="*", default=[])
    parser.add_argument("--out-json", default="")
    parser.add_argument("--out-md", default="")
    args = parser.parse_args()

    report = build_report(args)
    root = Path(args.root).resolve()
    if args.job_id:
        checks_dir = root / "output" / args.job_id / "checks"
        checks_dir.mkdir(parents=True, exist_ok=True)
        out_json = Path(args.out_json) if args.out_json else checks_dir / f"{args.stage}_seedance_prompt_contract_qc.json"
        out_md = Path(args.out_md) if args.out_md else checks_dir / f"{args.stage}_seedance_prompt_contract_qc.md"
    else:
        out_json = Path(args.out_json) if args.out_json else Path("seedance_prompt_contract_qc.json")
        out_md = Path(args.out_md) if args.out_md else Path("seedance_prompt_contract_qc.md")

    from qc_input_binding import attach_input_binding, resolve_path as resolve_binding_path

    binding_inputs = [
        resolve_binding_path(root, report.get("shot_line_map")),
        *[
            resolve_binding_path(root, item.get("path"))
            for item in report.get("prompts") or []
        ],
    ]
    if args.job_id:
        binding_inputs.extend([
            root / "output" / args.job_id / "seedance" / "director_plan.json",
            root / "output" / args.job_id / "product_profile.json",
        ])
    attach_input_binding(report, root, binding_inputs)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_md(out_md, report)
    print(json.dumps({"overall": report["overall"], "out_json": str(out_json), "out_md": str(out_md)}, ensure_ascii=False))
    raise SystemExit(0 if report["overall"] == "PASS" else 1)


if __name__ == "__main__":
    main()
