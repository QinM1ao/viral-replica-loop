#!/usr/bin/env python3
"""Validate the frozen non-client Product Fixture suite without side effects."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

from provider_fixture_recorder import (
    RecorderStop,
    ZeroSubmissionRecorder,
    canonical_json_bytes,
)


REQUIRED_FAMILIES = [
    "PF-01 core-audible-source-locked",
    "PF-02 branch-table",
    "PF-03 failure-mutations",
    "PF-04 local-finalization",
    "PF-05 sealed-independent-checker-verdicts",
]
REQUIRED_ORIGIN_FIELDS = {
    "fixture_id",
    "source",
    "license_or_authorization",
    "non_client",
    "content_summary",
    "expected_logical_roles",
    "sha256",
    "creation_tool",
    "redistribution_rights",
    "files",
}
REQUIRED_ORIGIN_MANIFEST_FIELDS = {
    "schema_version",
    "suite_id",
    "non_client_statement",
    "fixtures",
    "suite_files",
    "forbidden_source_classes_absent",
}
EXPECTED_FIXTURE_FILES = {
    "PF-01 core-audible-source-locked": [
        "core/source.y4m",
        "core/source_4s.mkv",
        "core/source_audio.pcm_u8",
        "core/source_audio_4s.wav",
        "core/product_reference.svg",
        "core/storyboard.svg",
        "core/source_script.json",
        "core/input_binding.json",
        "provider/request.json",
        "provider/response.json",
        "provider/recording.json",
        "provider/wujie_request_contract.json",
        "provider/wujie_response.json",
        *[
            f"core/source_frames/frame_{index:03d}.png"
            for index in range(1, 21)
        ],
    ],
    "PF-02 branch-table": [
        "branches/branch_table.json",
    ],
    "PF-03 failure-mutations": [
        "failures/single_variable_mutations.json",
    ],
    "PF-04 local-finalization": [
        "finalization/part-01.y4m",
        "finalization/part-02.y4m",
        "finalization/final-master.y4m",
        "finalization/part-01.mp4",
        "finalization/part-02.mp4",
        "finalization/final-master.mp4",
        "finalization/media_expectations.json",
        "finalization/subtitle-clean.mp4",
        "finalization/subtitle-burned-in.mp4",
    ],
    "PF-05 sealed-independent-checker-verdicts": [
        "checker/sealed_stage_verdicts.json",
        "image/source_storyboard.png",
        "image/current_job_storyboard.png",
        "image/product_front.png",
        "image/product_open.png",
        "image/identity_ref.png",
        "image/image_prompt.txt",
        "image/sealed_image_contract.json",
        "provider/image_request.json",
        "provider/image_response.json",
        "provider/image_recording.json",
    ],
}
EXPECTED_SUITE_FILES = [
    "README.md",
    "suite.json",
    "shared/runtime_contract.json",
    "shared/effective_profile.json",
    "shared/approval.json",
    "shared/expected_logical_roles.json",
]
EXPECTED_NON_CLIENT_STATEMENT = (
    "Every byte was newly hand-authored for product validation and represents "
    "no live or historical client work."
)
EXPECTED_FORBIDDEN_SOURCE_CLASSES = [
    "real client Job",
    "historical delivery",
    "identifiable private person authorization evidence",
    "Development Workspace run material",
    "provider credential or task evidence",
]
FORBIDDEN_ORIGIN_TERMS = (
    "customer",
    "client job",
    "historical job",
    "workspace-dev",
    "development workspace",
)


class FixtureValidationError(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise FixtureValidationError(f"invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise FixtureValidationError(f"JSON root must be an object: {path}")
    return payload


def checked_path(root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative:
        raise FixtureValidationError("fixture path is missing")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise FixtureValidationError(f"fixture path escapes root: {relative}") from exc
    if not candidate.is_file() or candidate.is_symlink():
        raise FixtureValidationError(f"fixture file is missing or linked: {relative}")
    return candidate


def file_projection(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": entry["path"],
        "sha256": entry["sha256"],
        "bytes": entry["bytes"],
    }


def projection_digest(entries: list[dict[str, Any]]) -> str:
    return hashlib.sha256(canonical_json_bytes(entries)).hexdigest()


def validate_file_entry(
    root: Path, entry: object, inventory: set[str]
) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise FixtureValidationError("file provenance entry must be an object")
    if set(entry) != {"path", "sha256", "bytes"}:
        raise FixtureValidationError("file provenance fields are not exact")
    path = checked_path(root, entry["path"])
    relative = path.relative_to(root).as_posix()
    if relative in inventory:
        raise FixtureValidationError(f"fixture file is declared twice: {relative}")
    inventory.add(relative)
    if file_sha256(path) != entry["sha256"]:
        raise FixtureValidationError(f"fixture digest changed: {relative}")
    if path.stat().st_size != entry["bytes"]:
        raise FixtureValidationError(f"fixture byte count changed: {relative}")
    return file_projection(entry)


def validate_y4m(path: Path, *, expected_frames: int, expected_duration: float) -> int:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg is None or ffprobe is None:
        raise FixtureValidationError(
            "full Y4M validation requires ffmpeg and ffprobe"
        )

    try:
        decoded = subprocess.run(
            [
                ffmpeg,
                "-nostdin",
                "-v",
                "error",
                "-xerror",
                "-i",
                str(path),
                "-map",
                "0:v:0",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FixtureValidationError(
            f"Y4M full decode could not run: {path.name}"
        ) from exc
    if decoded.returncode != 0:
        raise FixtureValidationError(
            f"Y4M fixture does not fully decode: {path.name}: "
            f"{decoded.stderr.strip()}"
        )

    try:
        probed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-count_frames",
                "-show_entries",
                (
                    "stream=codec_type,codec_name,pix_fmt,width,height,"
                    "r_frame_rate,nb_read_frames,duration"
                ),
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        streams = json.loads(probed.stdout)["streams"]
    except (
        KeyError,
        OSError,
        ValueError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        raise FixtureValidationError(
            f"Y4M stream facts are unreadable: {path.name}"
        ) from exc

    expected_stream = {
        "codec_type": "video",
        "codec_name": "rawvideo",
        "pix_fmt": "gray",
        "width": 2,
        "height": 2,
        "r_frame_rate": "2/1",
        "duration": f"{expected_duration:.6f}",
        "nb_read_frames": str(expected_frames),
    }
    if streams != [expected_stream]:
        raise FixtureValidationError(
            f"Y4M stream, duration, or frame facts changed: {path.name}"
        )
    return expected_frames


def validate_av_mp4(
    path: Path,
    *,
    expected_frames: int,
    expected_duration: float,
) -> int:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg is None or ffprobe is None:
        raise FixtureValidationError(
            "full MP4 validation requires ffmpeg and ffprobe"
        )
    decoded = subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-xerror",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if decoded.returncode != 0:
        raise FixtureValidationError(
            f"MP4 fixture does not fully decode: {path.name}: "
            f"{decoded.stderr.strip()}"
        )
    probed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-count_frames",
            "-show_entries",
            "format=duration:stream=codec_type,width,height,nb_read_frames",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    facts = json.loads(probed.stdout)
    streams = facts.get("streams") or []
    video = next(
        (item for item in streams if item.get("codec_type") == "video"),
        None,
    )
    audio = next(
        (item for item in streams if item.get("codec_type") == "audio"),
        None,
    )
    frame_count = int((video or {}).get("nb_read_frames") or 0)
    duration = float((facts.get("format") or {}).get("duration") or 0)
    if (
        video is None
        or audio is None
        or video.get("width") != 320
        or video.get("height") != 480
        or frame_count != expected_frames
        or not math.isclose(
            duration,
            expected_duration,
            rel_tol=0,
            abs_tol=1e-6,
        )
    ):
        raise FixtureValidationError(
            f"MP4 stream contract changed: {path.name}"
        )
    return frame_count


def validate_pcm_u8(
    path: Path,
    *,
    sample_rate_hz: int,
    channels: int,
    expected_samples: int,
    expected_duration: float,
) -> dict[str, Any]:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise FixtureValidationError("full PCM validation requires ffmpeg")
    if (
        not isinstance(sample_rate_hz, int)
        or sample_rate_hz <= 0
        or not isinstance(channels, int)
        or channels <= 0
        or not isinstance(expected_samples, int)
        or expected_samples <= 0
        or not isinstance(expected_duration, (int, float))
        or expected_duration <= 0
    ):
        raise FixtureValidationError("PCM expectations are invalid")

    payload = path.read_bytes()
    if len(payload) != expected_samples * channels:
        raise FixtureValidationError("PCM sample count changed")
    measured_duration = expected_samples / sample_rate_hz
    if not math.isclose(
        measured_duration,
        float(expected_duration),
        rel_tol=0,
        abs_tol=1e-9,
    ):
        raise FixtureValidationError("PCM duration does not match sample count")

    centered = [sample - 128 for sample in payload]
    peak = max(abs(sample) for sample in centered)
    rms = math.sqrt(sum(sample * sample for sample in centered) / len(centered))
    if peak <= 16 or rms <= 8.0:
        raise FixtureValidationError("PCM fixture is silent or lacks audible energy")

    input_options = [
        "-f",
        "u8",
        "-ar",
        str(sample_rate_hz),
        "-ac",
        str(channels),
    ]
    try:
        decoded = subprocess.run(
            [
                ffmpeg,
                "-nostdin",
                "-v",
                "error",
                "-xerror",
                *input_options,
                "-i",
                str(path),
                "-map",
                "0:a:0",
                "-f",
                "u8",
                "-acodec",
                "pcm_u8",
                "-",
            ],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FixtureValidationError(
            f"PCM full decode could not run: {path.name}"
        ) from exc
    if decoded.returncode != 0:
        raise FixtureValidationError(
            f"PCM fixture does not fully decode: {path.name}: "
            f"{decoded.stderr.decode('utf-8', errors='replace').strip()}"
        )
    if len(decoded.stdout) != expected_samples * channels:
        raise FixtureValidationError(
            f"PCM decoded sample count changed: {path.name}"
        )

    return {
        "sample_count": expected_samples,
        "duration_seconds": measured_duration,
        "rms_from_silence": rms,
        "peak_from_silence": peak,
    }


def validate_audible_av_pair(
    source_path: Path,
    audio_path: Path,
    *,
    expected_duration: float,
    expected_samples: int,
) -> None:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg is None or ffprobe is None:
        raise FixtureValidationError(
            "audio-bearing fixture validation requires ffmpeg and ffprobe"
        )

    try:
        source_probe = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                (
                    "format=duration:"
                    "stream=index,codec_type,codec_name,pix_fmt,width,height,"
                    "sample_rate,channels"
                ),
                "-of",
                "json",
                str(source_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        source_facts = json.loads(source_probe.stdout)
        audio_probe = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_type,codec_name,sample_rate,channels",
                "-of",
                "json",
                str(audio_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        audio_facts = json.loads(audio_probe.stdout)
    except (
        OSError,
        ValueError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        raise FixtureValidationError(
            "audio-bearing fixture stream facts are unreadable"
        ) from exc

    source_streams = source_facts.get("streams")
    if source_streams != [
        {
            "index": 0,
            "codec_name": "ffv1",
            "codec_type": "video",
            "width": 320,
            "height": 480,
            "pix_fmt": "yuv420p",
        },
        {
            "index": 1,
            "codec_name": "pcm_u8",
            "codec_type": "audio",
            "sample_rate": "8000",
            "channels": 1,
        },
    ]:
        raise FixtureValidationError("source AV stream facts changed")
    if audio_facts.get("streams") != [
        {
            "codec_name": "pcm_u8",
            "codec_type": "audio",
            "sample_rate": "8000",
            "channels": 1,
        }
    ]:
        raise FixtureValidationError("reference WAV stream facts changed")
    for facts in (source_facts, audio_facts):
        measured = float((facts.get("format") or {}).get("duration") or 0)
        if not math.isclose(
            measured,
            expected_duration,
            rel_tol=0,
            abs_tol=1e-6,
        ):
            raise FixtureValidationError(
                "audio-bearing fixture duration changed"
            )

    decoded = subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-xerror",
            "-i",
            str(audio_path),
            "-map",
            "0:a:0",
            "-f",
            "u8",
            "-acodec",
            "pcm_u8",
            "-",
        ],
        capture_output=True,
        timeout=10,
    )
    if decoded.returncode != 0 or len(decoded.stdout) != expected_samples:
        raise FixtureValidationError(
            "reference WAV did not fully decode to the expected samples"
        )
    centered = [sample - 128 for sample in decoded.stdout]
    rms = math.sqrt(sum(sample * sample for sample in centered) / len(centered))
    if rms <= 8.0:
        raise FixtureValidationError("reference WAV is silent")


def apply_mutation(request: dict[str, Any], mutation: dict[str, Any]) -> dict[str, Any]:
    changed = copy.deepcopy(request)
    target: Any = changed
    parts = mutation["json_path"].split(".")
    for key in parts[:-1]:
        if not isinstance(target, dict) or key not in target:
            raise FixtureValidationError(
                f"mutation path does not exist: {mutation['json_path']}"
            )
        target = target[key]
    if not isinstance(target, dict) or parts[-1] not in target:
        raise FixtureValidationError(
            f"mutation path does not exist: {mutation['json_path']}"
        )
    target[parts[-1]] = mutation["value"]
    return changed


def validate_fixture_suite(fixture_root: Path) -> dict[str, Any]:
    root = Path(fixture_root).resolve()
    if not root.is_dir():
        raise FixtureValidationError(f"fixture root is missing: {root}")
    origin = read_json(root / "fixture_origin.json")
    suite = read_json(root / "suite.json")
    if set(origin) != REQUIRED_ORIGIN_MANIFEST_FIELDS:
        raise FixtureValidationError("origin manifest fields are not exact")
    if (
        origin["schema_version"] != 1
        or origin["suite_id"] != "viral-replica-non-client-parity-v1"
        or origin["non_client_statement"] != EXPECTED_NON_CLIENT_STATEMENT
        or origin["forbidden_source_classes_absent"]
        != EXPECTED_FORBIDDEN_SOURCE_CLASSES
    ):
        raise FixtureValidationError("origin manifest provenance is invalid")

    fixtures = origin.get("fixtures")
    if not isinstance(fixtures, list):
        raise FixtureValidationError("origin manifest fixtures must be a list")
    if [item.get("fixture_id") for item in fixtures] != REQUIRED_FAMILIES:
        raise FixtureValidationError("fixture families are missing or reordered")

    inventory: set[str] = set()
    for fixture in fixtures:
        if not isinstance(fixture, dict) or set(fixture) != REQUIRED_ORIGIN_FIELDS:
            raise FixtureValidationError("fixture provenance fields are not exact")
        if fixture["non_client"] is not True:
            raise FixtureValidationError(
                f"fixture is not declared non-client: {fixture.get('fixture_id')}"
            )
        for field in (
            "source",
            "license_or_authorization",
            "content_summary",
            "creation_tool",
            "redistribution_rights",
        ):
            if not isinstance(fixture[field], str) or not fixture[field].strip():
                raise FixtureValidationError(
                    f"fixture provenance field is empty: {field}"
                )
        source_lower = fixture["source"].lower()
        if any(term in source_lower for term in FORBIDDEN_ORIGIN_TERMS):
            raise FixtureValidationError(
                f"fixture source is client or workspace derived: {fixture['fixture_id']}"
            )
        roles = fixture["expected_logical_roles"]
        if (
            not isinstance(roles, list)
            or not roles
            or any(not isinstance(role, str) or not role for role in roles)
        ):
            raise FixtureValidationError("expected logical roles are missing")
        file_entries = fixture["files"]
        if not isinstance(file_entries, list):
            raise FixtureValidationError("fixture file provenance is missing")
        declared_paths = [
            entry.get("path") if isinstance(entry, dict) else None
            for entry in file_entries
        ]
        expected_paths = EXPECTED_FIXTURE_FILES[fixture["fixture_id"]]
        if declared_paths != expected_paths:
            raise FixtureValidationError(
                f"fixture file allowlist changed: {fixture['fixture_id']}"
            )
        projections = [
            validate_file_entry(root, entry, inventory)
            for entry in file_entries
        ]
        if projection_digest(projections) != fixture["sha256"]:
            raise FixtureValidationError(
                f"fixture aggregate digest changed: {fixture['fixture_id']}"
            )

    suite_files = origin.get("suite_files")
    if not isinstance(suite_files, list):
        raise FixtureValidationError("suite file provenance is missing")
    suite_paths = [
        entry.get("path") if isinstance(entry, dict) else None
        for entry in suite_files
    ]
    if suite_paths != EXPECTED_SUITE_FILES:
        raise FixtureValidationError("suite file allowlist changed")
    for entry in suite_files:
        validate_file_entry(root, entry, inventory)
    actual_inventory = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "fixture_origin.json"
    }
    if inventory != actual_inventory:
        missing = sorted(actual_inventory - inventory)
        extra = sorted(inventory - actual_inventory)
        raise FixtureValidationError(
            f"fixture inventory mismatch; undeclared={missing}; absent={extra}"
        )

    if suite.get("fixture_families") != REQUIRED_FAMILIES:
        raise FixtureValidationError("suite fixture family binding changed")
    shared = suite.get("shared_binding")
    layouts = suite.get("layout_bindings")
    if not isinstance(shared, dict) or not isinstance(layouts, dict):
        raise FixtureValidationError("layout bindings are missing")
    if set(layouts) != {"LegacyLayout", "CanonicalLayout"}:
        raise FixtureValidationError("both layout bindings are required")
    for name, binding in layouts.items():
        if binding != {
            "fixture_suite_id": suite.get("suite_id"),
            "binding": "shared_binding",
        }:
            raise FixtureValidationError(f"{name} does not use the shared binding")

    for key in (
        "runtime_contract",
        "effective_profile",
        "approval",
        "expected_logical_roles",
        "provider_request",
        "wujie_request_contract",
        "wujie_response",
        "sealed_checker_verdicts",
    ):
        binding = shared.get(key)
        if not isinstance(binding, dict):
            raise FixtureValidationError(f"shared binding is missing {key}")
        path = checked_path(root, binding.get("path"))
        if file_sha256(path) != binding.get("sha256"):
            raise FixtureValidationError(f"shared binding changed: {key}")

    runtime = read_json(root / shared["runtime_contract"]["path"])
    profile = read_json(root / shared["effective_profile"]["path"])
    approval = read_json(root / shared["approval"]["path"])
    roles = read_json(root / shared["expected_logical_roles"]["path"])
    request = read_json(root / shared["provider_request"]["path"])
    wujie_request = read_json(
        root / shared["wujie_request_contract"]["path"]
    )
    wujie_response = read_json(root / shared["wujie_response"]["path"])
    sealed_verdicts = read_json(
        root / shared["sealed_checker_verdicts"]["path"]
    )
    if (
        runtime.get("network_allowed") is not False
        or runtime.get("provider_submission_allowed") is not False
        or runtime.get("media_generation_allowed") is not False
    ):
        raise FixtureValidationError("runtime contract is not zero-submission")
    if request.get("approval") != approval:
        raise FixtureValidationError("request approval differs from shared approval")
    if (
        sealed_verdicts.get("fixture_id")
        != "PF-05 sealed-independent-checker-verdicts"
        or sealed_verdicts.get("reviewer")
        != "independent_product_fixture_checker"
        or sealed_verdicts.get("non_client") is not True
        or set(sealed_verdicts.get("stages", {}))
        != {"source_blueprint", "image_batch_qc", "pre_seedance_pack"}
        or set(sealed_verdicts.get("subtitle_classification", {}))
        != {"clean", "burned_in"}
    ):
        raise FixtureValidationError("sealed checker verdict contract changed")
    profile_projection = [
        {
            "component_id": component["component_id"],
            "version": component["version"],
        }
        for component in profile.get("components", [])
    ]
    if request.get("effective_profile_components") != profile_projection:
        raise FixtureValidationError(
            "request Effective Profile components are not exact or ordered"
        )
    if request.get("reference_order") != shared.get("reference_order"):
        raise FixtureValidationError("request reference order differs from shared order")
    if wujie_request != {
        "schema_version": 1,
        "provider": "wujie_higress",
        "endpoint": (
            "https://higress-api.wujieai.com/v1/chat/completions"
        ),
        "model": "doubao-seed-2-0-mini-260215",
        "analysis_mode": "full",
        "sampling_fps": 2,
        "source_sha256": file_sha256(root / "core" / "source_4s.mkv"),
        "submitted_video_sha256": (
            "a69acf0c32bb0f5e94334072706021c50db020d1206fc36d816042302a65f5af"
        ),
        "submitted_video_size_bytes": 32518,
        "prompt_sha256": (
            "827b76761fa5f8fc8556c536a76f524a468104719060fdada3a9ab73dcfb1990"
        ),
        "http_status": 200,
        "network_allowed": False,
        "real_submit": False,
    }:
        raise FixtureValidationError("Wujie request contract changed")
    if (
        wujie_response.get("model") != wujie_request["model"]
        or not isinstance(wujie_response.get("choices"), list)
        or len(wujie_response["choices"]) != 1
    ):
        raise FixtureValidationError("Wujie response fixture changed")
    all_roles = {
        role
        for fixture in fixtures
        for role in fixture["expected_logical_roles"]
    }
    if set(roles.get("roles", [])) != all_roles:
        raise FixtureValidationError("shared expected logical roles are incomplete")
    if not set(request.get("expected_logical_roles", [])).issubset(all_roles):
        raise FixtureValidationError("provider request declares an unknown logical role")

    input_binding = read_json(root / "core" / "input_binding.json")
    frozen_input = request.get("frozen_input", {})
    if frozen_input != {
        "binding_id": input_binding.get("binding_id"),
        "binding_path": "core/input_binding.json",
        "sha256": file_sha256(root / "core" / "input_binding.json"),
    }:
        raise FixtureValidationError("provider request frozen input binding changed")
    if request.get("runtime_contract") != {
        "runtime_contract_id": runtime.get("runtime_contract_id"),
        "sha256": shared["runtime_contract"]["sha256"],
    }:
        raise FixtureValidationError("provider request Runtime Contract changed")
    for reference in input_binding.get("ordered_references", []):
        path = checked_path(root, reference.get("path"))
        if file_sha256(path) != reference.get("sha256"):
            raise FixtureValidationError(
                f"frozen input changed: {reference.get('role')}"
            )
    audio_facts = input_binding.get("audio_facts", {})
    if audio_facts != {
        "codec": "pcm_u8_wav",
        "sample_rate_hz": 8000,
        "channels": 1,
        "sample_count": 32000,
        "duration_seconds": 4.0,
        "audible": True,
    }:
        raise FixtureValidationError("core fixture must be audible")
    validate_pcm_u8(
        root / "core" / "source_audio.pcm_u8",
        sample_rate_hz=audio_facts["sample_rate_hz"],
        channels=audio_facts["channels"],
        expected_samples=8000,
        expected_duration=1.0,
    )
    validate_y4m(
        root / "core" / "source.y4m",
        expected_frames=2,
        expected_duration=1.0,
    )
    validate_audible_av_pair(
        root / "core" / "source_4s.mkv",
        root / "core" / "source_audio_4s.wav",
        expected_duration=audio_facts["duration_seconds"],
        expected_samples=audio_facts["sample_count"],
    )

    branches = read_json(root / "branches" / "branch_table.json")
    branch_ids = [case.get("case_id") for case in branches.get("cases", [])]
    if branch_ids != [
        "missing-required-input",
        "generic-profile-routing",
        "clay-mask-profile-routing",
        "toner-profile-routing",
        "storyboard-derived-identity",
        "generation-approval-boundary",
        "failed-part-retry-boundary",
        "request-rejection",
        "local-finishing",
        "subtitle-clean-classification",
        "subtitle-burned-in-classification",
        "final-technical-qc",
    ]:
        raise FixtureValidationError("branch table coverage changed")
    if any(
        not isinstance(case.get("input"), dict)
        or not isinstance(case.get("expected"), dict)
        for case in branches.get("cases", [])
    ):
        raise FixtureValidationError("branch table case is incomplete")

    expectations = read_json(root / "finalization" / "media_expectations.json")
    finishing = expectations.get("finishing", {})
    part_frames = sum(
        validate_av_mp4(
            checked_path(root, path),
            expected_frames=12,
            expected_duration=1.0,
        )
        for path in finishing.get("ordered_inputs", [])
    )
    final_qc = expectations.get("final_technical_qc", {})
    master_frames = validate_av_mp4(
        checked_path(root, final_qc.get("input")),
        expected_frames=final_qc.get("expected_frames"),
        expected_duration=final_qc.get("expected_duration_seconds"),
    )
    if part_frames != master_frames or finishing.get("expected_frames") != 23:
        raise FixtureValidationError("finishing master does not cover both Parts")
    if (
        final_qc.get("expected_readable") is not True
        or final_qc.get("expected_conclusion") != "PASS"
        or final_qc.get("required_streams") != ["video", "audio"]
        or finishing.get("output")
        != "output/job-001/final/final_video.mp4"
    ):
        raise FixtureValidationError("Final Technical QC media binding changed")

    recorder = ZeroSubmissionRecorder(
        checked_path(root, suite.get("provider_recorder")),
        now="2026-07-30T12:00:00Z",
    )
    image_recorder = ZeroSubmissionRecorder(
        checked_path(root, suite.get("image_provider_recorder")),
        now="2026-07-30T12:00:00Z",
    )
    image_response = image_recorder.replay(
        read_json(root / "provider" / "image_request.json")
    )
    if image_response.get("receipt") != {
        "mode": "sealed_offline_replay",
        "real_submit": False,
        "task_created": False,
        "paid_task_count": 0,
        "media_generation_task_count": 0,
        "external_effects": [],
    }:
        raise FixtureValidationError(
            "sealed image-maker replay created an external effect"
        )
    image_result = image_response.get("result") or {}
    image_output = checked_path(root, image_result.get("path"))
    if (
        file_sha256(image_output) != image_result.get("sha256")
        or image_result.get("asset_type") != "AI改好分镜图"
        or image_result.get("image_route") != "matpool_gpt_image_2_edit"
    ):
        raise FixtureValidationError(
            "sealed image-maker replay does not bind its saved candidate"
        )
    mutations = read_json(
        root / "failures" / "single_variable_mutations.json"
    ).get("mutations", [])
    for mutation in mutations:
        try:
            recorder.replay(apply_mutation(request, mutation))
        except RecorderStop as exc:
            if exc.code != mutation.get("expected_stop_code"):
                raise FixtureValidationError(
                    f"mutation {mutation.get('mutation_id')} stopped as {exc.code}"
                ) from exc
        else:
            raise FixtureValidationError(
                f"mutation did not stop: {mutation.get('mutation_id')}"
            )

    layout_runs: dict[str, list[str]] = {}
    response_receipt: dict[str, Any] | None = None
    for layout in ("LegacyLayout", "CanonicalLayout"):
        layout_runs[layout] = []
        for _ in range(suite.get("consecutive_runs_per_layout", 0)):
            response = recorder.replay(copy.deepcopy(request))
            response_receipt = response["receipt"]
            layout_runs[layout].append(
                hashlib.sha256(canonical_json_bytes(response)).hexdigest()
            )
    if (
        len(layout_runs["LegacyLayout"]) != 2
        or layout_runs["LegacyLayout"] != layout_runs["CanonicalLayout"]
        or len(set(layout_runs["LegacyLayout"])) != 1
    ):
        raise FixtureValidationError("layout replay is unstable or unequal")
    if response_receipt is None:
        raise FixtureValidationError("provider replay did not run")
    expected_effects = suite.get("expected_side_effects", {})
    actual_effects = {
        "external_effects": response_receipt.get("external_effects"),
        "paid_task_count": response_receipt.get("paid_task_count"),
        "media_generation_task_count": response_receipt.get(
            "media_generation_task_count"
        ),
    }
    if actual_effects != expected_effects:
        raise FixtureValidationError("fixture validation created an external effect")

    return {
        "status": "PASS",
        "suite_id": suite["suite_id"],
        "fixture_families": REQUIRED_FAMILIES,
        "layout_bindings": {
            "LegacyLayout": copy.deepcopy(shared),
            "CanonicalLayout": copy.deepcopy(shared),
        },
        "layout_runs": layout_runs,
        "media": {
            "audible_source": True,
            "local_finishing": True,
            "final_technical_qc": True,
        },
        **actual_effects,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture_root")
    args = parser.parse_args()
    try:
        report = validate_fixture_suite(Path(args.fixture_root))
    except FixtureValidationError as exc:
        print(f"STOP fixture_validation_failed: {exc}")
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
