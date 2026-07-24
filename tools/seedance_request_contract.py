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
IMAGE_REFERENCE_RE = re.compile(r"@?图片(\d+)")
AUDIO_REFERENCE_RE = re.compile(r"@?音频(\d+)")


def _is_http_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


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
) -> dict:
    checks = []
    metrics = {
        "duration": None,
        "image_count": 0,
        "audio_count": 0,
        "image_refs": [],
        "audio_refs": [],
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
            and MIN_DURATION_SECONDS <= duration <= MAX_DURATION_SECONDS,
            (
                f"found={duration!r}, expected="
                f"{MIN_DURATION_SECONDS}..{MAX_DURATION_SECONDS}"
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
    image_refs = sorted({int(value) for value in IMAGE_REFERENCE_RE.findall(prompt_text)})
    audio_refs = sorted({int(value) for value in AUDIO_REFERENCE_RE.findall(prompt_text)})
    metrics.update(
        {
            "image_count": len(image_items),
            "audio_count": len(audio_items),
            "image_refs": image_refs,
            "audio_refs": audio_refs,
        }
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

    image_refs_ok = all(1 <= index <= len(image_items) for index in image_refs)
    audio_refs_ok = all(1 <= index <= len(audio_items) for index in audio_refs)
    checks.append(
        _check(
            "image_reference_bounds",
            image_refs_ok,
            f"image_count={len(image_items)}, prompt_refs={image_refs}",
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
) -> dict:
    report = inspect_taskcode_request(
        request,
        for_submission=for_submission,
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
        if not _is_http_url(url):
            raise ValueError(
                f"audio_item_shape: reference audio needs public HTTP URL, found {url!r}"
            )
        urls.append(url)
    return urls
