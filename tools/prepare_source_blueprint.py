#!/usr/bin/env python3
import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from . import stage_execution
except ImportError:
    import stage_execution


CACHE_SCHEMA_VERSION = 8
TASK_NAMES = (
    "prepare_story_analysis",
    "build_part_storyboards",
    "prepare_source_rhythm",
    "prepare_face_expression",
)
TEXT_SUFFIXES = {".json", ".md", ".txt"}
TOOLS_DIR = Path(__file__).resolve().parent
SOURCE_TOOL_FILES = (
    "prepare_story_analysis.py",
    "video_understanding.py",
    "asr_transcribe.py",
    "build_part_storyboards.py",
    "prepare_source_rhythm.py",
    "detect_face_expression.py",
    "run_face_expression_detector.py",
)


def parse_duration_seconds(value):
    text = str(value).strip().lower().replace(" ", "")
    for source, target in [
        ("hours", "h"),
        ("hour", "h"),
        ("hrs", "h"),
        ("hr", "h"),
        ("minutes", "m"),
        ("minute", "m"),
        ("mins", "m"),
        ("min", "m"),
        ("seconds", "s"),
        ("second", "s"),
        ("secs", "s"),
        ("sec", "s"),
        ("小时", "h"),
        ("分钟", "m"),
        ("秒", "s"),
        ("分", "m"),
    ]:
        text = text.replace(source, target)

    seconds = None
    if ":" in text:
        parts = text.split(":")
        if len(parts) not in {2, 3} or any(not part for part in parts):
            raise ValueError(f"invalid duration: {value}")
        try:
            numbers = [float(part) for part in parts]
        except ValueError as exc:
            raise ValueError(f"invalid duration: {value}") from exc
        if len(numbers) == 2:
            minutes, seconds_part = numbers
            if seconds_part >= 60:
                raise ValueError(f"invalid duration: {value}")
            seconds = minutes * 60 + seconds_part
        else:
            hours, minutes, seconds_part = numbers
            if minutes >= 60 or seconds_part >= 60:
                raise ValueError(f"invalid duration: {value}")
            seconds = hours * 3600 + minutes * 60 + seconds_part
    else:
        try:
            seconds = float(text)
        except ValueError:
            match = re.fullmatch(
                r"(?:(?P<hours>\d+(?:\.\d+)?)h)?"
                r"(?:(?P<minutes>\d+(?:\.\d+)?)m)?"
                r"(?:(?P<seconds>\d+(?:\.\d+)?)s)?",
                text,
            )
            if not match or not any(match.groupdict().values()):
                raise ValueError(f"invalid duration: {value}")
            seconds = (
                float(match.group("hours") or 0) * 3600
                + float(match.group("minutes") or 0) * 60
                + float(match.group("seconds") or 0)
            )

    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError(f"duration must be greater than zero: {value}")
    return seconds


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_runtime_root(output_dir):
    output_dir = Path(output_dir).expanduser().resolve()
    for candidate in (output_dir, *output_dir.parents):
        if (candidate / "workspace.yaml").is_file():
            return candidate / ".viral-replica" / "runtime"
    return TOOLS_DIR.parent


def blueprint_parameters(target_duration_seconds, contact_fps="1/2", cols=0, thumb_long_edge=360):
    groups = math.ceil(target_duration_seconds / 15)
    return {
        "target_duration_seconds": float(target_duration_seconds),
        "groups": groups,
        "total_frames": groups * 12,
        "contact_fps": str(contact_fps),
        "run_asr": True,
        "asr": json.loads(
            (TOOLS_DIR.parent / "rules" / "ASR_MODEL.json").read_text(
                encoding="utf-8"
            )
        ),
        "video_understanding": json.loads(
            (TOOLS_DIR.parent / "rules" / "VIDEO_UNDERSTANDING_MODEL.json").read_text(
                encoding="utf-8"
            )
        ),
        "rapid_hook_review": {
            "mode": "rapid_hook",
            "start_seconds": 0.0,
            "duration_seconds": 3.0,
            "fps": 5.0,
        },
        "face_expression": json.loads(
            (TOOLS_DIR.parent / "rules" / "FACE_EXPRESSION_DETECTOR.json").read_text(
                encoding="utf-8"
            )
        ),
        "expression_prompt_policy": json.loads(
            (TOOLS_DIR.parent / "rules" / "EXPRESSION_PROMPT_POLICY.json").read_text(
                encoding="utf-8"
            )
        ),
        "storyboard_cols": int(cols),
        "thumb_long_edge": int(thumb_long_edge),
        "source_tool_sha256": {
            name: sha256_file(TOOLS_DIR / name)
            for name in SOURCE_TOOL_FILES
        },
    }


def build_cache_key(source_sha256, parameters):
    payload = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "source_sha256": source_sha256,
        "parameters": parameters,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def run_command(command):
    started_at = utc_now()
    started = time.perf_counter()
    try:
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        returncode = result.returncode
        stdout = result.stdout
        stderr = result.stderr
    except OSError as exc:
        returncode = None
        stdout = ""
        stderr = str(exc)
    return {
        "status": "PASS" if returncode == 0 else "FAIL",
        "duration_seconds": round(time.perf_counter() - started, 3),
        "started_at": started_at,
        "finished_at": utc_now(),
        "returncode": returncode,
        "command": [str(part) for part in command],
        "stdout_tail": stdout[-1000:],
        "stderr_tail": stderr[-1000:],
    }


def build_task_roots(root):
    root = Path(root)
    return {
        "prepare_story_analysis": (
            root / "prepare_story_analysis" / "story_analysis"
        ),
        "build_part_storyboards": (
            root / "build_part_storyboards" / "storyboard_source_refs"
        ),
        "prepare_source_rhythm": (
            root / "prepare_source_rhythm" / "source_rhythm"
        ),
        "prepare_face_expression": (
            root / "prepare_face_expression" / "face_expression"
        ),
    }


def rewrite_packet_staging_references(packet):
    for binding in packet.get("_stage_path_map") or []:
        staged = Path(binding["staged"])
        if not staged.is_dir():
            continue
        rewrite_text_references(
            staged,
            [(str(staged), str(binding["canonical"]))],
        )


def run_parallel_tasks(
    commands,
    *,
    execution_root,
    job_id,
    task_roots,
    max_workers=4,
):
    execution_root = Path(execution_root).resolve()
    execution_root.mkdir(parents=True, exist_ok=True)
    if set(commands) != set(TASK_NAMES):
        raise ValueError("source blueprint source-task set is incomplete")
    if set(task_roots) != set(TASK_NAMES):
        raise ValueError("source blueprint task roots are incomplete")

    packets = []
    for name in TASK_NAMES:
        task_root = Path(task_roots[name]).resolve()
        packets.append(
            {
                "packet_id": name,
                "executor_kind": "command",
                "command": [str(value) for value in commands[name]],
                "allowed_write_roots": [str(task_root)],
                "completion_path": str(
                    execution_root
                    / "output"
                    / job_id
                    / "source_blueprint_completions"
                    / f"{name}.json"
                ),
                "depends_on": [],
            }
        )
    plan = stage_execution.seal_plan(
        execution_root,
        {
            "schema_version": 1,
            "job_id": job_id,
            "stage": "source_blueprint",
            "packets": packets,
        },
    )

    timings = {}
    timings_lock = threading.Lock()

    def dispatch(packet):
        packet_temp = packet["_packet_staging_root"]
        timing = run_command(
            [
                "/usr/bin/env",
                f"TMPDIR={packet_temp}",
                *packet["command"],
            ]
        )
        rewrite_packet_staging_references(packet)
        outputs = []
        for value in packet["allowed_write_roots"]:
            write_root = Path(value)
            if not write_root.is_dir():
                continue
            outputs.extend(
                str(path)
                for path in sorted(write_root.rglob("*"))
                if path.is_file()
            )
        with timings_lock:
            timings[packet["packet_id"]] = timing
        return {
            "status": timing["status"],
            "outputs": outputs,
            "returncode": timing.get(
                "returncode",
                0 if timing["status"] == "PASS" else 1,
            ),
            "stdout": timing.get("stdout_tail", ""),
            "stderr": timing.get("stderr_tail", ""),
        }

    stage_report = stage_execution.execute_plan(
        execution_root,
        plan,
        dispatcher=dispatch,
        max_workers=max_workers,
    )
    for completion in stage_report["completions"]:
        name = completion["packet_id"]
        timing = timings.get(
            name,
            {
                "duration_seconds": 0.0,
                "started_at": None,
                "finished_at": None,
                "returncode": completion.get("returncode"),
                "stdout_tail": "",
                "stderr_tail": "",
            },
        )
        timing["status"] = completion["status"]
        timing["command"] = [str(value) for value in commands[name]]
        if completion.get("error"):
            timing["error"] = completion["error"]
        timings[name] = timing
    return {name: timings[name] for name in TASK_NAMES}


def build_commands(video, staging_root, parameters, runtime_root=None):
    runtime_root = Path(runtime_root or TOOLS_DIR.parent).expanduser().resolve()
    task_roots = build_task_roots(staging_root)
    story_dir = task_roots["prepare_story_analysis"]
    storyboard_dir = task_roots["build_part_storyboards"]
    rhythm_dir = task_roots["prepare_source_rhythm"]
    face_expression_dir = task_roots["prepare_face_expression"]
    face_config = parameters["face_expression"]
    return {
        "prepare_story_analysis": [
            sys.executable,
            str(TOOLS_DIR / "prepare_story_analysis.py"),
            "--video",
            str(video),
            "--out-dir",
            str(story_dir),
            "--contact-fps",
            parameters["contact_fps"],
            "--run-asr",
            "--rapid-hook-seconds",
            str(parameters["rapid_hook_review"]["duration_seconds"]),
            "--rapid-hook-fps",
            str(parameters["rapid_hook_review"]["fps"]),
        ],
        "build_part_storyboards": [
            sys.executable,
            str(TOOLS_DIR / "build_part_storyboards.py"),
            "--input",
            str(video),
            "--output",
            str(storyboard_dir),
            "--total-frames",
            str(parameters["total_frames"]),
            "--groups",
            str(parameters["groups"]),
            "--cols",
            str(parameters["storyboard_cols"]),
            "--thumb-long-edge",
            str(parameters["thumb_long_edge"]),
        ],
        "prepare_source_rhythm": [
            sys.executable,
            str(TOOLS_DIR / "prepare_source_rhythm.py"),
            "--video",
            str(video),
            "--output",
            str(rhythm_dir / "source_rhythm.json"),
        ],
        "prepare_face_expression": [
            sys.executable,
            str(TOOLS_DIR / "run_face_expression_detector.py"),
            "--no-bootstrap",
            "--video",
            str(video),
            "--out-dir",
            str(face_expression_dir),
            "--closed-threshold",
            str(face_config["closed_threshold"]),
            "--open-threshold",
            str(face_config["open_threshold"]),
            "--closed-ear-max",
            str(face_config["closed_ear_max"]),
            "--open-ear-min",
            str(face_config["open_ear_min"]),
            "--min-closed-frames",
            str(face_config["min_closed_frames"]),
        ],
    }


def merge_task_outputs(task_roots, destination):
    destination = Path(destination)
    story_target = destination / "story_analysis"
    storyboard_target = destination / "storyboard_source_refs"
    story_source = Path(task_roots["prepare_story_analysis"])
    storyboard_source = Path(task_roots["build_part_storyboards"])
    rhythm_source = Path(task_roots["prepare_source_rhythm"])
    face_expression_source = Path(task_roots["prepare_face_expression"])
    copy_tree(
        story_source,
        story_target,
        [(str(story_source), str(story_target))],
    )
    copy_tree(
        storyboard_source,
        storyboard_target,
        [(str(storyboard_source), str(storyboard_target))],
    )
    copy_tree(
        rhythm_source,
        story_target,
        [(str(rhythm_source), str(story_target))],
    )
    copy_tree(
        face_expression_source,
        story_target / "face_expression",
        [
            (
                str(face_expression_source),
                str(story_target / "face_expression"),
            )
        ],
    )


def build_expression_prompt_profile(
    analysis,
    *,
    source_sha256,
    policy,
    detector_binding=None,
    detector_summary=None,
):
    people_mode = str(analysis.get("people_mode") or "").strip()
    if people_mode not in {
        "single_primary",
        "multi_person",
        "no_person",
        "uncertain",
    }:
        characters = analysis.get("characters") or []
        people_mode = "multi_person" if len(characters) > 1 else "single_primary"
    is_multi = people_mode == "multi_person"
    branch = policy["multi_person" if is_multi else "single_person"]
    profile = {
        "schema_version": 1,
        "source_sha256": source_sha256,
        "mode": branch.get(
            "mode",
            "multi_person_semantic" if is_multi else "single_person_budgeted",
        ),
        "people_mode": people_mode,
        "semantic_source": "existing_video_understanding",
        "blink_policy": "omit" if is_multi else "budgeted",
        "budget": {
            key: branch[key]
            for key in (
                "max_chars_per_shot",
                "max_clauses_per_shot",
            )
            if key in branch
        },
        "semantic_timeline": [],
    }
    if "max_blink_phrases_per_cue" in branch:
        profile["budget"]["max_blink_phrases_per_cue"] = branch[
            "max_blink_phrases_per_cue"
        ]
    if "blink_policy" in branch:
        profile["budget"]["blink_policy"] = branch["blink_policy"]
    for item in analysis.get("timeline") or []:
        expression = str(item.get("expression_and_gaze") or "").strip()
        if not expression:
            continue
        profile["semantic_timeline"].append(
            {
                "start_seconds": item.get("start_seconds"),
                "end_seconds": item.get("end_seconds"),
                "visible_roles": list(item.get("visible_roles") or []),
                "expression_and_gaze": expression,
            }
        )
    if not is_multi and detector_binding:
        profile["detector_timeline"] = dict(detector_binding)
    if not is_multi and isinstance(detector_summary, dict):
        fallback_policy = branch.get("no_blink_fallback") or {}
        eye_events = detector_summary.get("eye_events") or []
        reliable_blinks = [
            event for event in eye_events if event.get("type") == "blink"
        ]
        coverage = float(detector_summary.get("face_detection_coverage") or 0.0)
        min_coverage = float(
            fallback_policy.get("min_face_detection_coverage") or 0.0
        )
        profile["natural_blink_fallback"] = {
            "eligible": bool(fallback_policy.get("enabled"))
            and coverage >= min_coverage
            and not reliable_blinks,
            "face_detection_coverage": coverage,
            "reliable_blink_event_count": len(reliable_blinks),
            "selection_priority": list(
                fallback_policy.get("selection_priority") or []
            ),
            "cue_source_prefix": fallback_policy.get(
                "cue_source_prefix",
                "natural_blink_fallback:",
            ),
        }
    return profile


def write_expression_prompt_profile(root, source_sha256, policy):
    story_dir = Path(root) / "story_analysis"
    understanding_path = story_dir / "video_understanding" / "analysis.json"
    detector_path = (
        story_dir / "face_expression" / "face_expression_timeline.json"
    )
    understanding = json.loads(understanding_path.read_text(encoding="utf-8"))
    detector_binding = None
    detector_summary = None
    if detector_path.is_file():
        detector_summary = json.loads(detector_path.read_text(encoding="utf-8"))
        detector_binding = {
            "path": str(detector_path),
            "sha256": sha256_file(detector_path),
        }
    profile = build_expression_prompt_profile(
        understanding["analysis"],
        source_sha256=source_sha256,
        policy=policy,
        detector_binding=detector_binding,
        detector_summary=detector_summary,
    )
    output = story_dir / "expression_prompt_profile.json"
    output.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output


def validate_asr_artifacts(asr_dir, expected, source_sha256=None):
    errors = []
    markdown_path = asr_dir / "原口播ASR_elevenlabs.md"
    raw_path = asr_dir / "elevenlabs_scribe_v1.json"
    timeline_path = asr_dir / "asr_timeline.json"
    manifest_path = asr_dir / "request_manifest.json"
    for path in (markdown_path, raw_path, timeline_path, manifest_path):
        if not path.is_file():
            errors.append(f"missing ASR artifact: {path}")
    if errors:
        return errors
    try:
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"invalid ASR artifact: {exc}"]

    words = timeline.get("words")
    raw_text = raw.get("text")
    if not isinstance(raw_text, str) or not raw_text.strip():
        errors.append("ElevenLabs ASR result has no transcript text")
    if not isinstance(words, list) or not words:
        errors.append("ElevenLabs ASR timeline has no word timestamps")
    elif isinstance(raw_text, str):
        timeline_text = "".join(
            str(item.get("text") or "")
            for item in words
            if isinstance(item, dict) and item.get("type") != "audio_event"
        )
        if timeline_text != raw_text:
            errors.append("ElevenLabs ASR timeline does not reconstruct raw text")
    if timeline.get("provider") != expected["provider"]:
        errors.append("ASR timeline provider does not match project config")
    if timeline.get("model") != expected["model"]:
        errors.append("ASR timeline model does not match project config")
    for field in ("speaker_turns", "sentence_segments", "audio_events"):
        if not isinstance(timeline.get(field), list):
            errors.append(f"ASR timeline is missing {field}")
    if manifest.get("http_status") != 200:
        errors.append("ASR request status is not HTTP 200")
    if manifest.get("provider") != expected["provider"]:
        errors.append("ASR request provider does not match project config")
    if manifest.get("endpoint") != expected["endpoint"]:
        errors.append("ASR request endpoint does not match project config")
    if manifest.get("model") != expected["model"]:
        errors.append("ASR request model does not match project config")
    if source_sha256 and manifest.get("source_sha256") != source_sha256:
        errors.append("ASR request source hash does not match current video")
    if manifest.get("transcription_id") != timeline.get("transcription_id"):
        errors.append("ASR request and timeline transcription IDs differ")
    if raw.get("transcription_id") != timeline.get("transcription_id"):
        errors.append("ASR raw result and timeline transcription IDs differ")
    if manifest.get("raw_response_sha256") != sha256_file(raw_path):
        errors.append("ASR raw response hash does not match request manifest")
    if manifest.get("timeline_sha256") != sha256_file(timeline_path):
        errors.append("ASR timeline hash does not match request manifest")
    return errors


def validate_generated_artifacts(root, parameters, source_sha256=None):
    story_dir = root / "story_analysis"
    storyboard_dir = root / "storyboard_source_refs"
    errors = []
    for path in [
        story_dir / "video_probe.json",
        story_dir / "contact_sheet.jpg",
        story_dir / "story_analysis_materials.md",
        story_dir / "video_understanding" / "analysis.json",
        story_dir / "video_understanding" / "analysis.md",
        story_dir / "video_understanding" / "request_manifest.json",
        story_dir / "video_understanding" / "raw_response.json",
        story_dir / "video_understanding" / "hook_review" / "analysis.json",
        story_dir / "video_understanding" / "hook_review" / "analysis.md",
        story_dir / "video_understanding" / "hook_review" / "request_manifest.json",
        story_dir / "video_understanding" / "hook_review" / "raw_response.json",
        story_dir / "video_understanding" / "hook_review" / "aligned_timeline.json",
        story_dir / "source_rhythm.json",
        story_dir / "expression_prompt_profile.json",
        story_dir / "face_expression" / "face_expression_timeline.json",
        story_dir / "face_expression" / "frame_metrics.csv",
        story_dir / "face_expression" / "eye_closure_curve.png",
        story_dir / "face_expression" / "face_expression_contact_sheet.jpg",
        storyboard_dir / "source_storyboard_manifest.json",
    ]:
        if not path.is_file():
            errors.append(f"missing artifact: {path}")

    asr_dir = story_dir / "asr"
    errors.extend(
        validate_asr_artifacts(asr_dir, parameters["asr"], source_sha256)
    )

    understanding_path = story_dir / "video_understanding" / "analysis.json"
    if understanding_path.is_file():
        try:
            understanding = json.loads(understanding_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid video understanding analysis: {exc}")
        else:
            expected = parameters["video_understanding"]
            if understanding.get("status") != "PASS":
                errors.append("video understanding status is not PASS")
            if understanding.get("provider") != expected["provider"]:
                errors.append("video understanding provider does not match project config")
            if understanding.get("model") != expected["model"]:
                errors.append("video understanding model does not match project config")
            if not isinstance(understanding.get("analysis"), dict):
                errors.append("video understanding result has no analysis object")
            else:
                model_analysis = understanding["analysis"]
                if not str(model_analysis.get("summary") or "").strip():
                    errors.append("video understanding analysis is missing summary")
                if not isinstance(model_analysis.get("timeline"), list):
                    errors.append("video understanding analysis is missing timeline array")
                if model_analysis.get("people_mode") not in {
                    "single_primary",
                    "multi_person",
                    "no_person",
                    "uncertain",
                }:
                    errors.append("video understanding analysis is missing people_mode")
                for index, item in enumerate(model_analysis.get("timeline") or []):
                    if not isinstance(item.get("expression_and_gaze"), str):
                        errors.append(
                            "video understanding timeline "
                            f"{index} is missing expression_and_gaze"
                        )

    hook_path = story_dir / "video_understanding" / "hook_review" / "analysis.json"
    if hook_path.is_file():
        try:
            hook = json.loads(hook_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid rapid hook analysis: {exc}")
        else:
            expected_model = parameters["video_understanding"]
            expected_hook = parameters["rapid_hook_review"]
            if hook.get("status") != "PASS":
                errors.append("rapid hook status is not PASS")
            if hook.get("provider") != expected_model["provider"]:
                errors.append("rapid hook provider does not match project config")
            if hook.get("model") != expected_model["model"]:
                errors.append("rapid hook model does not match project config")
            if hook.get("analysis_mode") != expected_hook["mode"]:
                errors.append("rapid hook analysis mode does not match project config")
            if hook.get("sampling_fps") != expected_hook["fps"]:
                errors.append("rapid hook sampling fps does not match project config")
            segment = hook.get("source_segment")
            segment_matches = (
                isinstance(segment, dict)
                and segment.get("start_seconds") == expected_hook["start_seconds"]
                and segment.get("timebase") == "source_absolute"
                and isinstance(segment.get("end_seconds"), (int, float))
                and expected_hook["start_seconds"]
                < segment["end_seconds"]
                <= expected_hook["duration_seconds"]
            )
            if not segment_matches:
                errors.append("rapid hook source segment does not match project config")
            hook_analysis = hook.get("analysis")
            if not isinstance(hook_analysis, dict):
                errors.append("rapid hook result has no analysis object")
            else:
                if not str(hook_analysis.get("summary") or "").strip():
                    errors.append("rapid hook analysis is missing summary")
                if not isinstance(hook_analysis.get("timeline"), list):
                    errors.append("rapid hook analysis is missing timeline array")

    aligned_hook_path = (
        story_dir / "video_understanding" / "hook_review" / "aligned_timeline.json"
    )
    if aligned_hook_path.is_file():
        try:
            aligned_hook = json.loads(aligned_hook_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid rapid hook aligned timeline: {exc}")
        else:
            if aligned_hook.get("status") != "PASS":
                errors.append("rapid hook aligned timeline status is not PASS")
            if aligned_hook.get("timing_source") != "measured_scene_cuts":
                errors.append("rapid hook aligned timeline has no measured timing source")
            timeline = aligned_hook.get("timeline")
            if not isinstance(timeline, list) or not timeline:
                errors.append("rapid hook aligned timeline is empty")

    manifest_path = storyboard_dir / "source_storyboard_manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid storyboard manifest: {exc}")
        else:
            if manifest.get("groups") != parameters["groups"]:
                errors.append("storyboard manifest groups do not match requested groups")
            if manifest.get("total_frames") != parameters["total_frames"]:
                errors.append("storyboard manifest total_frames do not match requested total_frames")
            if len(manifest.get("parts") or []) != parameters["groups"]:
                errors.append("storyboard manifest part count does not match requested groups")

    for part in range(1, parameters["groups"] + 1):
        path = storyboard_dir / f"source_storyboard_part{part}.jpg"
        if not path.is_file():
            errors.append(f"missing Part storyboard: {path}")

    rhythm_path = story_dir / "source_rhythm.json"
    if rhythm_path.is_file():
        try:
            rhythm = json.loads(rhythm_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid source rhythm: {exc}")
        else:
            evidence = rhythm.get("source_evidence") or {}
            if not str(evidence.get("asr_text") or "").strip():
                errors.append("source rhythm is missing raw ASR text")

    face_expression_path = (
        story_dir / "face_expression" / "face_expression_timeline.json"
    )
    if face_expression_path.is_file():
        try:
            face_expression = json.loads(
                face_expression_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid face expression timeline: {exc}")
        else:
            expected = parameters["face_expression"]
            detector = face_expression.get("detector") or {}
            if detector.get("name") != expected["detector"]:
                errors.append("face expression detector does not match project config")
            if detector.get("model_sha256") != expected["model_sha256"]:
                errors.append("face expression model does not match project config")
            if not isinstance(face_expression.get("frames"), list):
                errors.append("face expression timeline is missing frames")
            if not isinstance(face_expression.get("eye_events"), list):
                errors.append("face expression timeline is missing eye events")
            coverage = face_expression.get("face_detection_coverage")
            if not isinstance(coverage, (int, float)) or not 0 <= coverage <= 1:
                errors.append("face expression detection coverage is invalid")

    forbidden_names = {
        "剧情分析.md",
        "画面时间线.md",
        "字幕层整理.md",
        "分镜表与缝点审查.md",
        "分镜污染审查.md",
    }
    cached_names = {path.name for path in root.rglob("*") if path.is_file()}
    for name in sorted(forbidden_names & cached_names):
        errors.append(f"product-specific prose must not be cached: {name}")
    return errors


def extract_asr_full_text(markdown):
    match = re.search(
        r"^## Full Text\s*$\n+(.*?)(?=\n## |\Z)",
        markdown,
        flags=re.MULTILINE | re.DOTALL,
    )
    return match.group(1).strip() if match else ""


def align_rapid_hook_timeline(hook_result, source_rhythm, snap_tolerance=0.25):
    segment = hook_result.get("source_segment") or {}
    segment_start = float(segment.get("start_seconds", 0.0))
    segment_end = float(segment.get("end_seconds", segment_start))
    cuts = []
    for item in sorted(
        source_rhythm.get("actual_cut_points") or [],
        key=lambda value: float(value.get("time", 0)),
    ):
        time_value = float(item.get("time", 0))
        if not segment_start < time_value < segment_end:
            continue
        candidate = {"time": round(time_value, 3), "score": float(item.get("score", 0))}
        if cuts and candidate["time"] - cuts[-1]["time"] <= 0.08:
            if candidate["score"] > cuts[-1]["score"]:
                cuts[-1] = candidate
            continue
        cuts.append(candidate)

    cut_times = [item["time"] for item in cuts]
    evidence_frames = sorted(
        source_rhythm.get("evidence_frames") or [],
        key=lambda item: float(item.get("time", 0)),
    )

    def snap(value):
        value = float(value)
        if abs(value - segment_start) < 1e-6:
            return segment_start
        if abs(value - segment_end) < 1e-6:
            return segment_end
        if not cut_times:
            return value
        nearest = min(cut_times, key=lambda cut: abs(cut - value))
        return nearest if abs(nearest - value) <= snap_tolerance else value

    aligned_timeline = []
    for item in hook_result.get("analysis", {}).get("timeline") or []:
        aligned = dict(item)
        model_start = float(item["start_seconds"])
        model_end = float(item["end_seconds"])
        aligned["model_start_seconds"] = model_start
        aligned["model_end_seconds"] = model_end
        aligned["start_seconds"] = round(snap(model_start), 3)
        aligned["end_seconds"] = round(snap(model_end), 3)
        if aligned.get("visual_action_type") == "physical_change":
            before = [
                frame
                for frame in evidence_frames
                if float(frame.get("time", 0)) < aligned["start_seconds"]
            ]
            during = [
                frame
                for frame in evidence_frames
                if aligned["start_seconds"] + 0.09
                <= float(frame.get("time", 0))
                < aligned["end_seconds"]
            ]
            if before and len(during) >= 2:
                aligned["evidence_frame_candidates"] = {
                    "before": before[-1],
                    "contact_motion": during[:-1],
                    "visible_after": during[-1],
                }
        aligned_timeline.append(aligned)

    return {
        "schema_version": 1,
        "status": "PASS",
        "timing_source": "measured_scene_cuts",
        "semantic_source": "seed_2_0_mini_rapid_hook",
        "spoken_content_source": "elevenlabs_scribe_v1",
        "snap_tolerance_seconds": snap_tolerance,
        "source_segment": segment,
        "measured_cut_points": cuts,
        "timeline": aligned_timeline,
    }


def write_aligned_rapid_hook_timeline(root):
    story_dir = root / "story_analysis"
    hook_path = story_dir / "video_understanding" / "hook_review" / "analysis.json"
    rhythm_path = story_dir / "source_rhythm.json"
    hook_result = json.loads(hook_path.read_text(encoding="utf-8"))
    source_rhythm = json.loads(rhythm_path.read_text(encoding="utf-8"))
    aligned = align_rapid_hook_timeline(hook_result, source_rhythm)
    aligned["semantic_source_path"] = str(hook_path)
    aligned["timing_source_path"] = str(rhythm_path)
    output = hook_path.parent / "aligned_timeline.json"
    output.write_text(
        json.dumps(aligned, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output


def bind_story_evidence(story_dir, source_sha256):
    story_dir = Path(story_dir)
    rhythm_path = story_dir / "source_rhythm.json"
    face_expression_path = (
        story_dir / "face_expression" / "face_expression_timeline.json"
    )
    expression_profile_path = story_dir / "expression_prompt_profile.json"
    asr_paths = sorted((story_dir / "asr").rglob("*.md"))
    if not rhythm_path.is_file() or not asr_paths:
        return
    asr_path = asr_paths[0]
    asr_text = extract_asr_full_text(asr_path.read_text(encoding="utf-8"))
    rhythm = json.loads(rhythm_path.read_text(encoding="utf-8"))
    rhythm["source_sha256"] = source_sha256
    evidence = rhythm.setdefault("source_evidence", {})
    evidence["asr_text"] = asr_text
    evidence["asr_source"] = str(asr_path)
    evidence["asr_text_sha256"] = hashlib.sha256(asr_text.encode("utf-8")).hexdigest()
    timeline_path = asr_path.parent / "asr_timeline.json"
    if timeline_path.is_file():
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        evidence["asr_provider"] = timeline.get("provider")
        evidence["asr_model"] = timeline.get("model")
        evidence["asr_transcription_id"] = timeline.get("transcription_id")
        evidence["asr_audio_duration_secs"] = timeline.get("audio_duration_secs")
        evidence["asr_source_video_sha256"] = source_sha256
        evidence["asr_timeline"] = {
            "path": str(timeline_path),
            "sha256": sha256_file(timeline_path),
        }
        raw_path = asr_path.parent / "elevenlabs_scribe_v1.json"
        manifest_path = asr_path.parent / "request_manifest.json"
        if raw_path.is_file():
            evidence["asr_raw_response"] = {
                "path": str(raw_path),
                "sha256": sha256_file(raw_path),
            }
        if manifest_path.is_file():
            evidence["asr_request_manifest"] = {
                "path": str(manifest_path),
                "sha256": sha256_file(manifest_path),
            }
        evidence["asr_words"] = timeline.get("words") or []
        evidence["speaker_turns"] = timeline.get("speaker_turns") or []
        evidence["sentence_segments"] = timeline.get("sentence_segments") or []
        evidence["audio_events"] = timeline.get("audio_events") or []
        evidence.setdefault("asr_span_basis", "compact_alnum")
    if expression_profile_path.is_file():
        profile = json.loads(
            expression_profile_path.read_text(encoding="utf-8")
        )
        evidence["expression_prompt_profile"] = {
            "path": str(expression_profile_path),
            "sha256": sha256_file(expression_profile_path),
            "source_sha256": source_sha256,
            "mode": profile.get("mode"),
        }
    if (
        face_expression_path.is_file()
        and expression_profile_path.is_file()
        and json.loads(
            expression_profile_path.read_text(encoding="utf-8")
        ).get("mode") == "single_person_budgeted"
    ):
        evidence["face_expression_timeline"] = {
            "path": str(face_expression_path),
            "sha256": sha256_file(face_expression_path),
            "source_sha256": source_sha256,
        }
    evidence.setdefault("subtitle_observations", [])
    rhythm_path.write_text(
        json.dumps(rhythm, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def hydrate_source_rhythm_evidence(root, source_sha256):
    return bind_story_evidence(Path(root) / "story_analysis", source_sha256)


def cache_entry_is_valid(cache_entry, cache_key, source_sha256, parameters):
    manifest_path = cache_entry / "cache_manifest.json"
    if not manifest_path.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if manifest.get("version") != CACHE_SCHEMA_VERSION:
        return False
    if manifest.get("cache_key") != cache_key:
        return False
    if manifest.get("source_sha256") != source_sha256:
        return False
    if manifest.get("parameters") != parameters or manifest.get("overall") != "PASS":
        return False
    return not validate_generated_artifacts(
        cache_entry, parameters, source_sha256
    )


def rewrite_text_references(root, replacements):
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        updated = text
        for old, new in replacements:
            if old:
                updated = updated.replace(old, new)
        if updated != text:
            path.write_text(updated, encoding="utf-8")


def clean_deterministic_targets(output_dir):
    story_dir = output_dir / "剧情分析"
    for name in ["video_probe.json", "contact_sheet.jpg", "story_analysis_materials.md"]:
        path = story_dir / name
        if path.exists():
            path.unlink()
    shutil.rmtree(story_dir / "asr", ignore_errors=True)
    shutil.rmtree(story_dir / "video_understanding", ignore_errors=True)
    shutil.rmtree(story_dir / "face_expression", ignore_errors=True)

    storyboard_dir = output_dir / "storyboard_source_refs"
    manifest = storyboard_dir / "source_storyboard_manifest.json"
    if manifest.exists():
        manifest.unlink()
    for pattern in ["source_storyboard_part*.jpg", "source_frames_part*"]:
        for path in storyboard_dir.glob(pattern):
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()


def copy_tree(source, destination, replacements):
    copied = []
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() in TEXT_SUFFIXES:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                shutil.copy2(path, target)
            else:
                for old, new in replacements:
                    if old:
                        text = text.replace(old, new)
                target.write_text(text, encoding="utf-8")
        else:
            shutil.copy2(path, target)
        copied.append(target)
    return copied


def authored_rhythm_fields(output_dir, source_sha256):
    rhythm_path = output_dir / "剧情分析" / "source_rhythm.json"
    if not rhythm_path.is_file():
        return None
    try:
        rhythm = json.loads(rhythm_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if rhythm.get("source_sha256") != source_sha256:
        return None
    beats = rhythm.get("beats") or []
    observations = (rhythm.get("source_evidence") or {}).get("subtitle_observations") or []
    if not beats and not observations:
        return None
    return {"beats": beats, "subtitle_observations": observations}


def restore_cached_artifacts(cache_entry, output_dir, video):
    cache_manifest = json.loads((cache_entry / "cache_manifest.json").read_text(encoding="utf-8"))
    story_target = output_dir / "剧情分析"
    storyboard_target = output_dir / "storyboard_source_refs"
    old_source = cache_manifest.get("source_path", "")
    replacements = [
        (str(cache_entry / "story_analysis"), str(story_target)),
        (str(cache_entry / "storyboard_source_refs"), str(storyboard_target)),
        (str(cache_entry), str(output_dir)),
        (old_source, str(video)),
    ]
    preserved_rhythm = authored_rhythm_fields(output_dir, cache_manifest.get("source_sha256"))

    clean_deterministic_targets(output_dir)
    copied = []
    copied.extend(copy_tree(cache_entry / "story_analysis", story_target, replacements))
    copied.extend(copy_tree(cache_entry / "storyboard_source_refs", storyboard_target, replacements))
    if preserved_rhythm:
        rhythm_path = story_target / "source_rhythm.json"
        rhythm = json.loads(rhythm_path.read_text(encoding="utf-8"))
        rhythm["beats"] = preserved_rhythm["beats"]
        rhythm.setdefault("source_evidence", {})["subtitle_observations"] = preserved_rhythm[
            "subtitle_observations"
        ]
        rhythm_path.write_text(
            json.dumps(rhythm, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    bind_story_evidence(story_target, cache_manifest.get("source_sha256"))
    return sorted(str(path.relative_to(output_dir)) for path in copied)


def write_report(report_path, report):
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def prepare_face_expression_runtime():
    result = subprocess.run(
        [
            sys.executable,
            str(TOOLS_DIR / "run_face_expression_detector.py"),
            "--prepare",
        ],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip()
            or "face-expression project runtime is unavailable"
        )
    return json.loads(result.stdout)


def prepare_asr_provider():
    result = subprocess.run(
        [
            sys.executable,
            str(TOOLS_DIR / "asr_transcribe.py"),
            "--check",
        ],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip()
            or "ElevenLabs ASR provider is unavailable"
        )
    return result.stdout.strip().splitlines()[-1]


def prepare_blueprint(
    video,
    output_dir,
    target_duration,
    cache_dir=Path(".cache/source-blueprint"),
    contact_fps="1/2",
    cols=0,
    thumb_long_edge=360,
    report_path=None,
    runtime_root=None,
):
    started = time.perf_counter()
    video = Path(video).expanduser().resolve()
    output_dir = Path(output_dir).expanduser().resolve()
    cache_dir = Path(cache_dir).expanduser().resolve()
    runtime_root = Path(
        runtime_root or resolve_runtime_root(output_dir)
    ).expanduser().resolve()
    if not video.is_file():
        raise FileNotFoundError(f"source video not found: {video}")

    duration_seconds = parse_duration_seconds(target_duration)
    parameters = blueprint_parameters(duration_seconds, contact_fps, cols, thumb_long_edge)
    source_sha256 = sha256_file(video)
    cache_key = build_cache_key(source_sha256, parameters)
    cache_entry = cache_dir / cache_key
    report_path = (
        Path(report_path).expanduser().resolve()
        if report_path
        else output_dir / "checks" / "source_blueprint_report.json"
    )
    report = {
        "cache_hit": False,
        "cache_key": cache_key,
        "source_sha256": source_sha256,
        "source_video": str(video),
        "parameters": parameters,
        "task_timings": {},
        "artifacts": [],
        "overall": "FAIL",
        "report_path": str(report_path),
        "runtime_root": str(runtime_root),
    }

    cache_dir.mkdir(parents=True, exist_ok=True)
    if cache_entry_is_valid(cache_entry, cache_key, source_sha256, parameters):
        report["cache_hit"] = True
        report["task_timings"] = {
            name: {"status": "CACHE_HIT", "duration_seconds": 0.0}
            for name in TASK_NAMES
        }
        try:
            report["artifacts"] = restore_cached_artifacts(cache_entry, output_dir, video)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            report["errors"] = [f"cache restore failed: {exc}"]
        else:
            report["overall"] = "PASS"
        report["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        write_report(report_path, report)
        return report

    if cache_entry.exists():
        shutil.rmtree(cache_entry)

    try:
        prepare_face_expression_runtime()
        prepare_asr_provider()
    except (RuntimeError, json.JSONDecodeError) as exc:
        report["errors"] = [str(exc)]
        report["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        write_report(report_path, report)
        return report

    staging_root = Path(tempfile.mkdtemp(prefix=f".{cache_key}-", dir=cache_dir))
    try:
        execution_root = staging_root / "sealed_execution"
        stage_job_id = re.sub(r"[^A-Za-z0-9_-]+", "-", output_dir.name).strip("-_")
        if not stage_job_id or not stage_job_id[0].isalnum():
            stage_job_id = f"source-blueprint-{cache_key[:12]}"
        task_root = (
            execution_root
            / "output"
            / stage_job_id
            / "source_blueprint_tasks"
        )
        task_roots = build_task_roots(task_root)
        commands = build_commands(
            video,
            task_root,
            parameters,
            runtime_root=runtime_root,
        )
        task_timings = run_parallel_tasks(
            commands,
            execution_root=execution_root,
            job_id=stage_job_id,
            task_roots=task_roots,
            max_workers=len(TASK_NAMES),
        )
        report["task_timings"] = task_timings
        failed = [name for name, timing in task_timings.items() if timing["status"] != "PASS"]
        if failed:
            report["errors"] = [f"task failed: {name}" for name in failed]
            report["elapsed_seconds"] = round(time.perf_counter() - started, 3)
            write_report(report_path, report)
            return report

        merge_task_outputs(task_roots, staging_root)
        shutil.rmtree(execution_root)
        write_expression_prompt_profile(
            staging_root,
            source_sha256,
            parameters["expression_prompt_policy"],
        )
        hydrate_source_rhythm_evidence(staging_root, source_sha256)
        write_aligned_rapid_hook_timeline(staging_root)
        validation_errors = validate_generated_artifacts(
            staging_root, parameters, source_sha256
        )
        if validation_errors:
            report["errors"] = validation_errors
            report["elapsed_seconds"] = round(time.perf_counter() - started, 3)
            write_report(report_path, report)
            return report

        rewrite_text_references(staging_root, [(str(staging_root), str(cache_entry))])
        artifact_paths = sorted(
            str(path.relative_to(staging_root))
            for path in staging_root.rglob("*")
            if path.is_file()
        )
        cache_manifest = {
            "version": CACHE_SCHEMA_VERSION,
            "cache_key": cache_key,
            "source_sha256": source_sha256,
            "source_path": str(video),
            "parameters": parameters,
            "artifacts": artifact_paths,
            "overall": "PASS",
        }
        (staging_root / "cache_manifest.json").write_text(
            json.dumps(cache_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        if cache_entry.exists():
            if not cache_entry_is_valid(cache_entry, cache_key, source_sha256, parameters):
                shutil.rmtree(cache_entry)
        if not cache_entry.exists():
            staging_root.rename(cache_entry)

        report["artifacts"] = restore_cached_artifacts(cache_entry, output_dir, video)
        report["overall"] = "PASS"
        report["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        write_report(report_path, report)
        return report
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report["errors"] = [str(exc)]
        report["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        write_report(report_path, report)
        return report
    finally:
        if staging_root.exists():
            shutil.rmtree(staging_root)


def main():
    parser = argparse.ArgumentParser(
        description="Prepare cached source-only story analysis and Part storyboard materials."
    )
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        "--job-output-dir",
        "--out-dir",
        dest="output_dir",
        type=Path,
        required=True,
    )
    parser.add_argument("--target-duration", required=True)
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/source-blueprint"))
    parser.add_argument("--contact-fps", default="1/2")
    parser.add_argument("--cols", type=int, default=0)
    parser.add_argument("--thumb-long-edge", type=int, default=360)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--runtime-root", type=Path)
    args = parser.parse_args()

    try:
        report = prepare_blueprint(
            video=args.video,
            output_dir=args.output_dir,
            target_duration=args.target_duration,
            cache_dir=args.cache_dir,
            contact_fps=args.contact_fps,
            cols=args.cols,
            thumb_long_edge=args.thumb_long_edge,
            report_path=args.report,
            runtime_root=args.runtime_root,
        )
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))
    print(report["report_path"])
    return 0 if report["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
