#!/usr/bin/env python3
"""Single source of truth for Seedance taskCode request serialization."""

from __future__ import annotations

import json
import re
from typing import Any, Optional
from urllib.parse import urlparse


TASK_CREATE_URL = (
    "https://higress-api.wujieai.com/wj-open/v2/open-platform/task/task_create"
)
ACQUIRE_RESOURCE_TIMEOUT_SECONDS = 60
MIN_DURATION_SECONDS = 4
MAX_DURATION_SECONDS = 15
SEEDANCE25_MAX_DURATION_SECONDS = 30
SEEDANCE25_MODEL = "doubao-seedance-2-5-260628"
SEEDANCE25_TASK_CODE = 2509
IMAGE_REFERENCE_RE = re.compile(r"@?图片(\d+)")
AUDIO_REFERENCE_RE = re.compile(r"@?音频(\d+)")
VIDEO_REFERENCE_RE = re.compile(r"@?视频(\d+)")
ACTIVE_ASSET_RE = re.compile(r"^asset://asset-[A-Za-z0-9_-]+$")


def _is_http_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_public_mp3_url(value: Any) -> bool:
    return _is_http_url(value) and urlparse(value).path.lower().endswith(".mp3")


def _is_image_reference_url(value: Any) -> bool:
    return (
        isinstance(value, str)
        and (value.startswith("asset://") or _is_http_url(value))
    )


def decode_taskcode_param(request: dict) -> tuple[dict, dict]:
    body = request.get("body") if isinstance(request, dict) else None
    if not isinstance(body, dict):
        raise ValueError("request_body: request.body must be an object")
    raw_param = body.get("param")
    if not isinstance(raw_param, str):
        raise ValueError(
            "param_json_string: request.body.param must be a JSON string"
        )
    try:
        param = json.loads(raw_param)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"param_json_string: request.body.param is not valid JSON: {exc}"
        ) from exc
    if not isinstance(param, dict):
        raise ValueError(
            "param_json_string: decoded request.body.param must be an object"
        )
    return body, param


def _check(name: str, passed: bool, detail: str) -> dict:
    return {
        "name": name,
        "status": "PASS" if passed else "FAIL",
        "detail": detail,
    }


def inspect_taskcode_request(
    request: dict,
    *,
    for_submission: bool = False,
    require_active_visual_assets: bool = False,
    require_seedance_prompt_format: bool = False,
) -> dict:
    checks = []
    metrics = {
        "duration": None,
        "image_count": 0,
        "audio_count": 0,
        "video_count": 0,
        "image_refs": [],
        "audio_refs": [],
        "video_refs": [],
    }

    body = request.get("body") if isinstance(request, dict) else None
    checks.append(
        _check(
            "request_body",
            isinstance(body, dict),
            "request.body is an object"
            if isinstance(body, dict)
            else "request.body must be an object",
        )
    )
    if not isinstance(body, dict):
        return {"overall": "FAIL", "checks": checks, "metrics": metrics}

    raw_param = body.get("param")
    param = None
    param_error = ""
    if not isinstance(raw_param, str):
        param_error = "request.body.param must be a JSON string"
    else:
        try:
            candidate = json.loads(raw_param)
        except json.JSONDecodeError as exc:
            param_error = f"request.body.param is not valid JSON: {exc}"
        else:
            if isinstance(candidate, dict):
                param = candidate
            else:
                param_error = "decoded request.body.param must be an object"
    checks.append(
        _check(
            "param_json_string",
            param is not None,
            "body.param is a JSON string containing an object"
            if param is not None
            else param_error,
        )
    )

    timeout = body.get("acquireResourceTimeoutSeconds")
    checks.append(
        _check(
            "acquire_resource_timeout",
            timeout == ACQUIRE_RESOURCE_TIMEOUT_SECONDS,
            f"found={timeout!r}, expected={ACQUIRE_RESOURCE_TIMEOUT_SECONDS}",
        )
    )

    body_task_code = body.get("taskCode")
    top_level_task_code = request.get("taskCode")
    task_code_ok = (
        isinstance(body_task_code, int)
        and not isinstance(body_task_code, bool)
        and (
            top_level_task_code is None
            or top_level_task_code == body_task_code
        )
    )
    checks.append(
        _check(
            "task_code_consistency",
            task_code_ok,
            (
                f"body={body_task_code!r}, top_level={top_level_task_code!r}; "
                "top-level taskCode may be omitted but cannot disagree"
            ),
        )
    )

    method = request.get("method", "POST")
    checks.append(
        _check(
            "http_method",
            method == "POST",
            f"found={method!r}, expected='POST'",
        )
    )
    request_url = request.get("url")
    checks.append(
        _check(
            "task_create_url",
            request_url == TASK_CREATE_URL,
            f"found={request_url!r}, expected={TASK_CREATE_URL!r}",
        )
    )
    prepared_value = request.get("prepared_only", False)
    do_not_submit_value = request.get("do_not_submit", False)
    prepared_flags_are_booleans = (
        isinstance(prepared_value, bool)
        and isinstance(do_not_submit_value, bool)
    )
    prepared_only = prepared_value is True
    do_not_submit = do_not_submit_value is True
    prepared_state_consistent = (
        prepared_flags_are_booleans
        and prepared_only == do_not_submit
    )
    checks.append(
        _check(
            "submission_state",
            (
                prepared_state_consistent
                and (
                    not for_submission
                    or (not prepared_only and not do_not_submit)
                )
            ),
            (
                f"for_submission={for_submission}, "
                f"prepared_only={prepared_only}, do_not_submit={do_not_submit}"
            ),
        )
    )

    if param is None:
        return {
            "overall": "FAIL",
            "checks": checks,
            "metrics": metrics,
        }

    model = param.get("model")
    is_seedance25 = model == SEEDANCE25_MODEL
    max_duration = (
        SEEDANCE25_MAX_DURATION_SECONDS if is_seedance25 else MAX_DURATION_SECONDS
    )
    duration = param.get("duration")
    metrics["duration"] = duration
    integer_duration = isinstance(duration, int) and not isinstance(duration, bool)
    checks.append(
        _check(
            "integer_duration",
            integer_duration,
            f"found={duration!r}; taskCode duration must be an integer",
        )
    )
    checks.append(
        _check(
            "duration_range",
            integer_duration
            and MIN_DURATION_SECONDS <= duration <= max_duration,
            (
                f"found={duration!r}, expected="
                f"{MIN_DURATION_SECONDS}..{max_duration}"
            ),
        )
    )

    content = param.get("content")
    content_ok = isinstance(content, list) and bool(content)
    checks.append(
        _check(
            "content_list",
            content_ok,
            "decoded body.param.content must be a non-empty list",
        )
    )
    if not content_ok:
        return {
            "overall": "FAIL",
            "checks": checks,
            "metrics": metrics,
        }

    prompt_text = "\n".join(
        item.get("text", "")
        for item in content
        if isinstance(item, dict)
        and item.get("type") == "text"
        and isinstance(item.get("text"), str)
    )
    image_items = [
        item
        for item in content
        if isinstance(item, dict) and item.get("type") == "image_url"
    ]
    audio_items = [
        item
        for item in content
        if isinstance(item, dict) and item.get("type") == "audio_url"
    ]
    video_items = [
        item
        for item in content
        if isinstance(item, dict) and item.get("type") == "video_url"
    ]
    image_refs = sorted({int(value) for value in IMAGE_REFERENCE_RE.findall(prompt_text)})
    audio_refs = sorted({int(value) for value in AUDIO_REFERENCE_RE.findall(prompt_text)})
    video_refs = sorted({int(value) for value in VIDEO_REFERENCE_RE.findall(prompt_text)})
    metrics.update(
        {
            "image_count": len(image_items),
            "audio_count": len(audio_items),
            "video_count": len(video_items),
            "image_refs": image_refs,
            "audio_refs": audio_refs,
            "video_refs": video_refs,
        }
    )

    if is_seedance25:
        audio_mode = request.get("audio_mode")
        expected_generate_audio = audio_mode == "generated_voiceover"
        expected_types = (
            ["text"]
            + ["image_url"] * len(image_items)
            + ["video_url"] * len(video_items)
            + ["audio_url"] * len(audio_items)
        )
        actual_types = [
            item.get("type") if isinstance(item, dict) else None for item in content
        ]
        route_shape_ok = (
            body_task_code == SEEDANCE25_TASK_CODE
            and param.get("omni_reference_task_type") == "reference"
            and audio_mode in {"generated_voiceover", "original_master_postmix"}
            and param.get("generate_audio") is expected_generate_audio
            and param.get("watermark") is False
            and param.get("resolution") == "720p"
            and len(video_items) <= 1
            and len(audio_items) <= 1
            and (audio_mode != "original_master_postmix" or not audio_items)
            and actual_types == expected_types
        )
        checks.append(
            _check(
                "seedance25_route_shape",
                route_shape_ok,
                (
                    f"model={model!r}, taskCode={body_task_code!r}, "
                    f"audio_mode={audio_mode!r}, generate_audio={param.get('generate_audio')!r}, "
                    f"omni_reference_task_type={param.get('omni_reference_task_type')!r}, "
                    f"content_types={actual_types!r}; expected taskCode=2509, ordered "
                    "text/images/optional-video/optional-audio, at most one depth video, "
                    "audio mode matched generate_audio, 720p, watermark=false"
                ),
            )
        )

    if require_seedance_prompt_format:
        h3_experiment = request.get("prompt_experiment") == (
            "preserve_original_h3_once"
        )
        forbidden_prompt_markers = (
            "subject_definitions",
            "retention_analysis",
            "detailed_description",
            "<Picture",
            "<Video",
            "<Audio",
            "[Shot",
        )
        prompt_format_ok = h3_experiment or (
            200 <= len(prompt_text) <= 2600
            and not any(marker in prompt_text for marker in forbidden_prompt_markers)
            and (
                not image_items
                or sorted({int(value) for value in re.findall(r"@图片(\d+)", prompt_text)})
                == list(range(1, len(image_items) + 1))
            )
            and (
                not video_items
                or sorted({int(value) for value in re.findall(r"@视频(\d+)", prompt_text)})
                == list(range(1, len(video_items) + 1))
            )
            and (
                not audio_items
                or sorted({int(value) for value in re.findall(r"@音频(\d+)", prompt_text)})
                == list(range(1, len(audio_items) + 1))
            )
        )
        checks.append(
            _check(
                "seedance_prompt_format",
                prompt_format_ok,
                (
                    f"chars={len(prompt_text)}; h3_experiment={h3_experiment}; "
                    "otherwise require compact Seedance @图片/@视频/@音频 bindings "
                    "and forbid MiniMax H3 wrapper markers"
                ),
            )
        )
        if is_seedance25:
            required_sections = (
                "【生成目标】",
                "【参考素材职责】",
                "【主体与道具】",
                "【事件脚本】",
                "【保持一致】",
            )
            internal_marker = re.search(
                r"source_rhythm|\bsr\d+\b|shot",
                prompt_text,
                flags=re.IGNORECASE,
            )
            stage_blocks = re.findall(r"(?m)^阶段\s*[一二三四五六七八九十\d]+", prompt_text)
            section_positions = [prompt_text.find(section) for section in required_sections]
            stage_prompt_ok = (
                all(section in prompt_text for section in required_sections)
                and section_positions == sorted(section_positions)
                and len(stage_blocks) >= 2
                and internal_marker is None
            )
            internal_marker_text = (
                repr(internal_marker.group(0)) if internal_marker else "None"
            )
            checks.append(
                _check(
                    "seedance25_stage_prompt",
                    stage_prompt_ok,
                    (
                        f"required_sections_present="
                        f"{all(section in prompt_text for section in required_sections)}, "
                        f"section_order={section_positions}, stage_blocks={len(stage_blocks)}, "
                        f"internal_marker={internal_marker_text}; "
                        "require staged Seedance 2.5 prompt and no internal labels"
                    ),
                )
            )

    image_items_ok = all(
        item.get("role") == "reference_image"
        and isinstance(item.get("image_url"), dict)
        and _is_image_reference_url(item["image_url"].get("url"))
        and "role" not in item["image_url"]
        for item in image_items
    )
    checks.append(
        _check(
            "image_item_shape",
            image_items_ok,
            (
                f"image_count={len(image_items)}; each role must be beside "
                "image_url and each URL must be http(s) or asset://"
            ),
        )
    )

    video_items_ok = all(
        item.get("role") == "reference_video"
        and isinstance(item.get("video_url"), dict)
        and _is_image_reference_url(item["video_url"].get("url"))
        and "role" not in item["video_url"]
        for item in video_items
    )
    checks.append(
        _check(
            "video_item_shape",
            video_items_ok,
            (
                f"video_count={len(video_items)}; each role must be beside "
                "video_url and each URL must be http(s) or asset://"
            ),
        )
    )

    if require_active_visual_assets:
        visual_urls = [item["image_url"].get("url") for item in image_items]
        visual_urls.extend(item["video_url"].get("url") for item in video_items)
        active_assets_ok = bool(visual_urls) and all(
            isinstance(url, str) and ACTIVE_ASSET_RE.fullmatch(url)
            for url in visual_urls
        )
        checks.append(
            _check(
                "active_visual_asset_refs",
                active_assets_ok,
                (
                    f"visual_count={len(visual_urls)}; every image/video submitted "
                    "through the verified all-reference route must use asset://asset-..."
                ),
            )
        )

    prepared_placeholders_allowed = (
        not for_submission and prepared_only and do_not_submit
    )
    audio_items_ok = all(
        item.get("role") == "reference_audio"
        and isinstance(item.get("audio_url"), dict)
        and (
            _is_http_url(item["audio_url"].get("url"))
            or (
                prepared_placeholders_allowed
                and isinstance(item["audio_url"].get("url"), str)
                and item["audio_url"]["url"].startswith("asset://UPLOAD_")
            )
        )
        and "role" not in item["audio_url"]
        for item in audio_items
    )
    checks.append(
        _check(
            "audio_item_shape",
            audio_items_ok,
            (
                f"audio_count={len(audio_items)}; each role must be beside "
                "audio_url; submission URLs must be public http(s), while "
                "prepared packs may use asset://UPLOAD_ placeholders"
            ),
        )
    )
    if for_submission:
        audio_urls = [item["audio_url"].get("url") for item in audio_items]
        checks.append(
            _check(
                "public_mp3_reference_audio",
                all(_is_public_mp3_url(url) for url in audio_urls),
                (
                    f"audio_count={len(audio_urls)}; every submitted reference "
                    "audio must be the public HTTPS/HTTP .mp3 exported from the "
                    "same approved master; WAV and asset:// audio are forbidden"
                ),
            )
        )

    image_refs_ok = all(1 <= index <= len(image_items) for index in image_refs)
    audio_refs_ok = all(1 <= index <= len(audio_items) for index in audio_refs)
    video_refs_ok = all(1 <= index <= len(video_items) for index in video_refs)
    checks.append(
        _check(
            "image_reference_bounds",
            image_refs_ok,
            f"image_count={len(image_items)}, prompt_refs={image_refs}",
        )
    )
    checks.append(
        _check(
            "video_reference_bounds",
            video_refs_ok,
            f"video_count={len(video_items)}, prompt_refs={video_refs}",
        )
    )
    checks.append(
        _check(
            "audio_reference_bounds",
            audio_refs_ok,
            f"audio_count={len(audio_items)}, prompt_refs={audio_refs}",
        )
    )

    overall = (
        "PASS"
        if all(check["status"] == "PASS" for check in checks)
        else "FAIL"
    )
    return {"overall": overall, "checks": checks, "metrics": metrics}


def require_taskcode_request(
    request: dict,
    *,
    for_submission: bool = False,
    require_active_visual_assets: bool = False,
    require_seedance_prompt_format: bool = False,
) -> dict:
    report = inspect_taskcode_request(
        request,
        for_submission=for_submission,
        require_active_visual_assets=require_active_visual_assets,
        require_seedance_prompt_format=require_seedance_prompt_format,
    )
    failures = [
        f"{check['name']}: {check['detail']}"
        for check in report["checks"]
        if check["status"] != "PASS"
    ]
    if failures:
        raise ValueError("; ".join(failures))
    _body, param = decode_taskcode_param(request)
    return param


def build_taskcode_request(
    param: dict,
    *,
    task_code: int,
    url: str = TASK_CREATE_URL,
    metadata: Optional[dict] = None,
) -> dict:
    if not isinstance(param, dict):
        raise TypeError("param must be an object before wire serialization")
    request = dict(metadata or {})
    request.update(
        {
            "url": url,
            "method": "POST",
            "taskCode": task_code,
            "body": {
                "taskCode": task_code,
                "param": json.dumps(
                    param,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "acquireResourceTimeoutSeconds": (
                    ACQUIRE_RESOURCE_TIMEOUT_SECONDS
                ),
            },
        }
    )
    require_taskcode_request(request)
    return request


def reference_audio_urls(request: dict) -> list[str]:
    _body, param = decode_taskcode_param(request)
    content = param.get("content")
    if not isinstance(content, list):
        raise ValueError("content_list: decoded body.param.content must be a list")
    urls = []
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "audio_url":
            continue
        audio_url = item.get("audio_url")
        url = audio_url.get("url") if isinstance(audio_url, dict) else None
        if not _is_public_mp3_url(url):
            raise ValueError(
                "public_mp3_reference_audio: reference audio needs a public "
                f"HTTP(S) .mp3 URL, found {url!r}"
            )
        urls.append(url)
    return urls


def reference_visual_urls(request: dict) -> list[str]:
    _body, param = decode_taskcode_param(request)
    content = param.get("content")
    if not isinstance(content, list):
        raise ValueError("content_list: decoded body.param.content must be a list")
    urls = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "image_url":
            wrapper = item.get("image_url")
        elif item.get("type") == "video_url":
            wrapper = item.get("video_url")
        else:
            continue
        url = wrapper.get("url") if isinstance(wrapper, dict) else None
        if not isinstance(url, str) or not ACTIVE_ASSET_RE.fullmatch(url):
            raise ValueError(
                "active_visual_asset_refs: every reference image/video needs "
                f"asset://asset-..., found {url!r}"
            )
        urls.append(url)
    return urls
