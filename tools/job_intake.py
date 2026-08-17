#!/usr/bin/env python3
"""Create formal Jobs consistently from explicit and inbox adapters."""

from dataclasses import dataclass, replace
import csv
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Callable, Optional, Sequence, Tuple

from lifecycle_registry import LifecycleRegistry
from product_profile import write_product_profile


VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
STORYBOARD_DERIVED_PERSON_ASSETS = "storyboard_derived"
JOB_FIELDS = [
    "id",
    "workflow_run_id",
    "status",
    "video_path",
    "product_name",
    "client_profile",
    "product_assets",
    "person_assets",
    "audio_assets",
    "target_duration",
    "handoff_mode",
    "notes",
    "output_dir",
    "last_artifact",
    "next_stage",
    "needs_user_confirmation",
]


@dataclass(frozen=True)
class JobIntakeRequest:
    product_name: str
    product_assets: str
    person_assets: str = STORYBOARD_DERIVED_PERSON_ASSETS
    audio_assets: str = "extract_from_original"
    target_duration: Optional[str] = None
    handoff_mode: str = "auto"
    notes: str = ""
    client_profile: str = ""
    duplicate_video_policy: str = "allow"
    max_new_jobs: Optional[int] = None


@dataclass(frozen=True)
class JobIntakeResult:
    scanned_videos: Tuple[Path, ...]
    created_jobs: Tuple[dict, ...]
    request: JobIntakeRequest
    existing_job_count: int


def detect_client_profile(product_name: str, explicit_profile: str) -> str:
    if explicit_profile:
        return explicit_profile
    if "孔凤春" in product_name:
        return "kongfengchun"
    return ""


def infer_handoff_mode(explicit_mode: str, notes: str) -> str:
    if explicit_mode != "auto":
        return explicit_mode
    text = str(notes or "")
    web_markers = (
        "生成视频前停",
        "Seedance 生成前停",
        "网页端",
        "素材图和提示词",
        "不需要最终视频",
    )
    api_markers = (
        "直接出视频",
        "生成最终视频",
        "直接生成视频",
        "跑 Seedance",
    )
    if any(marker in text for marker in web_markers):
        return "web"
    if any(marker in text for marker in api_markers):
        return "api"
    return "web"


def discover_videos(
    video_dir: str = "",
    explicit_videos: Sequence[str] = (),
) -> Tuple[Path, ...]:
    if explicit_videos:
        videos = tuple(
            Path(value).expanduser().resolve() for value in explicit_videos
        )
    else:
        directory = Path(video_dir).expanduser().resolve()
        if not directory.is_dir():
            raise ValueError(f"video directory is unavailable: {directory}")
        videos = tuple(
            path.resolve()
            for path in sorted(directory.iterdir())
            if path.is_file() and path.suffix.lower() in VIDEO_EXTS
        )
    if not videos:
        raise ValueError("no source videos were found")
    for video in videos:
        if not video.is_file():
            raise ValueError(f"source video is unavailable: {video}")
        if video.suffix.lower() not in VIDEO_EXTS:
            raise ValueError(f"unsupported source video: {video}")
    return videos


def video_duration_seconds(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(
            f"could not read source video duration: {path}: "
            f"{result.stderr.strip()}"
        )
    try:
        duration = float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"could not parse source video duration: {path}"
        ) from exc
    if duration <= 0:
        raise ValueError(f"source video duration must be positive: {path}")
    return duration


def formatted_duration(seconds: float) -> str:
    return f"{float(seconds):.3f}".rstrip("0").rstrip(".") + "s"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_person_assets(value: str) -> str:
    raw = str(value or "").strip()
    if not raw or raw == STORYBOARD_DERIVED_PERSON_ASSETS:
        return STORYBOARD_DERIVED_PERSON_ASSETS
    return str(Path(raw).expanduser().resolve())


def create_jobs(
    root: Path,
    videos: Sequence[Path],
    request: JobIntakeRequest,
    *,
    dry_run: bool = False,
    duration_probe: Callable[[Path], float] = video_duration_seconds,
) -> JobIntakeResult:
    """Validate one intake and atomically append its formal Jobs."""
    root = Path(root).resolve()
    scanned_videos = tuple(Path(video).expanduser().resolve() for video in videos)
    if not scanned_videos:
        raise ValueError("job intake requires at least one source video")
    for video in scanned_videos:
        if not video.is_file():
            raise ValueError(f"source video is unavailable: {video}")
        if video.suffix.lower() not in VIDEO_EXTS:
            raise ValueError(f"unsupported source video: {video}")

    if not str(request.product_name or "").strip():
        raise ValueError("product_name is required")
    product_assets = Path(request.product_assets).expanduser().resolve()
    if not product_assets.exists():
        raise ValueError(f"product assets are unavailable: {product_assets}")
    person_assets = normalized_person_assets(request.person_assets)
    if (
        person_assets != STORYBOARD_DERIVED_PERSON_ASSETS
        and not Path(person_assets).exists()
    ):
        raise ValueError(f"person assets are unavailable: {person_assets}")
    client_profile = detect_client_profile(
        request.product_name,
        request.client_profile,
    )
    if (
        client_profile
        and not (root / "client-profiles" / client_profile).is_dir()
    ):
        raise ValueError(
            "client profile is unavailable: "
            f"{root / 'client-profiles' / client_profile}"
        )
    if request.duplicate_video_policy not in {"allow", "skip"}:
        raise ValueError("duplicate_video_policy must be `allow` or `skip`")
    if request.handoff_mode not in {"auto", "web", "api", "both"}:
        raise ValueError("handoff_mode must be auto, web, api, or both")
    if (
        request.target_duration is not None
        and not str(request.target_duration).strip()
    ):
        raise ValueError("target_duration cannot be empty")
    if request.max_new_jobs is not None and request.max_new_jobs < 1:
        raise ValueError("max_new_jobs must be positive when provided")

    lifecycle = LifecycleRegistry.load(root)
    if lifecycle.legacy_partial:
        raise ValueError(
            "new Job intake requires complete lifecycle rules with "
            "version, initial state, and five-stage progress"
        )
    initial_status, initial_stage = lifecycle.initial()
    effective_request = replace(
        request,
        product_assets=str(product_assets),
        person_assets=person_assets,
        client_profile=client_profile,
        handoff_mode=infer_handoff_mode(
            request.handoff_mode,
            request.notes,
        ),
    )
    if dry_run:
        rows, _fieldnames = _read_jobs(root / "jobs.csv")
        created = _plan_jobs(
            root,
            scanned_videos,
            effective_request,
            rows,
            initial_status,
            initial_stage,
            duration_probe,
        )
        return JobIntakeResult(
            scanned_videos=scanned_videos,
            created_jobs=tuple(created),
            request=effective_request,
            existing_job_count=len(rows),
        )

    lock_path = root / ".job-intake.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        jobs_path = root / "jobs.csv"
        rows, fieldnames = _read_jobs(jobs_path)
        existing_count = len(rows)
        created = _plan_jobs(
            root,
            scanned_videos,
            effective_request,
            rows,
            initial_status,
            initial_stage,
            duration_probe,
        )
        if not created:
            return JobIntakeResult(
                scanned_videos=scanned_videos,
                created_jobs=tuple(created),
                request=effective_request,
                existing_job_count=existing_count,
            )

        created_dirs = []
        try:
            for row in created:
                output_dir = root / row["output_dir"]
                output_dir.mkdir(parents=True, exist_ok=False)
                created_dirs.append(output_dir)
                evidence = None
                if effective_request.target_duration is not None:
                    evidence = {
                        "source": "intake",
                        "quote": (
                            "--target-duration "
                            f"{effective_request.target_duration}"
                        ),
                    }
                _write_json_atomic(
                    output_dir / "intake.json",
                    {
                        "schema_version": 1,
                        "job_id": row["id"],
                        "source_video": {
                            "path": row["video_path"],
                            "sha256": file_sha256(Path(row["video_path"])),
                        },
                        "target_duration": {
                            "value": row["target_duration"],
                            "explicitly_requested": (
                                effective_request.target_duration is not None
                            ),
                            "request_evidence": evidence,
                        },
                        "user_request": {
                            "notes": effective_request.notes,
                        },
                    },
                )
                write_product_profile(root, row)
            _write_jobs_atomic(jobs_path, rows + created, fieldnames)
        except Exception:
            for output_dir in reversed(created_dirs):
                _remove_created_job_dir(output_dir)
            raise

    return JobIntakeResult(
        scanned_videos=scanned_videos,
        created_jobs=tuple(created),
        request=effective_request,
        existing_job_count=existing_count,
    )


def _build_notes(request: JobIntakeRequest) -> str:
    notes = request.notes
    if request.client_profile:
        suffix = (
            f"client_profile={request.client_profile}; read "
            f"client-profiles/{request.client_profile}/README.md"
        )
        return f"{notes}; {suffix}" if notes else suffix
    return notes


def _plan_jobs(
    root: Path,
    videos: Sequence[Path],
    request: JobIntakeRequest,
    rows: Sequence[dict],
    initial_status: str,
    initial_stage: str,
    duration_probe: Callable[[Path], float],
) -> list:
    existing_videos = {
        str(Path(row.get("video_path", "")).expanduser().resolve())
        for row in rows
        if row.get("video_path", "").strip()
    }
    selected = [
        video
        for video in videos
        if (
            request.duplicate_video_policy == "allow"
            or str(video) not in existing_videos
        )
    ]
    if request.max_new_jobs is not None:
        selected = selected[: request.max_new_jobs]

    next_number = _next_job_number(root, rows)
    timestamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    created = []
    for video in selected:
        job_id = f"job-{next_number:03d}"
        next_number += 1
        target_duration = request.target_duration or formatted_duration(
            duration_probe(video)
        )
        created.append(
            {
                "id": job_id,
                "workflow_run_id": f"{job_id}-{timestamp}",
                "status": initial_status,
                "video_path": str(video),
                "product_name": request.product_name,
                "client_profile": request.client_profile,
                "product_assets": request.product_assets,
                "person_assets": request.person_assets,
                "audio_assets": request.audio_assets,
                "target_duration": target_duration,
                "handoff_mode": request.handoff_mode,
                "notes": _build_notes(request),
                "output_dir": f"output/{job_id}",
                "last_artifact": "",
                "next_stage": initial_stage,
                "needs_user_confirmation": "false",
            }
        )
    return created


def _read_jobs(path: Path):
    if not path.is_file():
        return [], JOB_FIELDS[:]
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or JOB_FIELDS)


def _next_job_number(root: Path, rows: Sequence[dict]) -> int:
    numbers = []
    for row in rows:
        match = re.fullmatch(
            r"job-(\d+)(?:-.+)?",
            str(row.get("id") or "").strip(),
        )
        if match:
            numbers.append(int(match.group(1)))
    output_root = root / "output"
    if output_root.is_dir():
        for path in output_root.iterdir():
            if not path.is_dir():
                continue
            match = re.fullmatch(r"job-(\d+)(?:-.+)?", path.name)
            if match:
                numbers.append(int(match.group(1)))
    return max(numbers, default=0) + 1


def _merged_fields(fieldnames: Sequence[str]) -> list:
    merged = list(fieldnames)
    for field in JOB_FIELDS:
        if field not in merged:
            merged.append(field)
    return merged


def _write_jobs_atomic(
    path: Path,
    rows: Sequence[dict],
    fieldnames: Sequence[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=_merged_fields(fieldnames),
            )
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _write_json_atomic(path: Path, value: dict) -> None:
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _remove_created_job_dir(path: Path) -> None:
    shutil.rmtree(path)
