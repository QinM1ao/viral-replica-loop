#!/usr/bin/env python3
"""Create Active Pixmax material-library image assets from public image URLs."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image

try:
    import httpx
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "httpx", "-q"])
    import httpx


DEFAULT_BASE_URL = "https://higress-api.wujieai.com"
DEFAULT_PROJECT_NAME = "tianwenyue-2"
COMMON_IMAGE_ASPECTS = {
    "9:16": 9 / 16,
    "2:3": 2 / 3,
    "3:4": 3 / 4,
    "4:5": 4 / 5,
    "1:1": 1.0,
    "5:4": 5 / 4,
    "4:3": 4 / 3,
    "3:2": 3 / 2,
    "16:9": 16 / 9,
}
ASPECT_RELATIVE_TOLERANCE = 0.03


def gateway_key() -> str:
    return os.environ.get("GATEWAY_API_KEY") or os.environ.get("SEEDANCE_API_KEY") or ""


def headers(api_key: str) -> dict[str, str]:
    if not api_key:
        raise SystemExit("Missing GATEWAY_API_KEY or SEEDANCE_API_KEY")
    return {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}


def openapi_url(base_url: str, action: str) -> str:
    return f"{base_url.rstrip('/')}/pixmax/ai-api/volcengine/openapi/?Action={action}&Version=2024-01-01"


def extract_id(data: dict) -> str:
    for container in (data.get("Result"), data.get("data"), data):
        if isinstance(container, dict) and isinstance(container.get("Id"), str):
            return container["Id"]
    return ""


def extract_status(data: dict) -> str:
    for container in (data.get("Result"), data.get("data"), data):
        if isinstance(container, dict):
            status = container.get("Status") or container.get("status")
            if isinstance(status, str):
                return status
    return ""


def is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def safe_name(value: str, fallback: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
    return (text or fallback)[:64]


def inspect_source_geometry(paths: list[Path]) -> list[dict]:
    results = []
    for path in paths:
        if not path.is_file():
            raise SystemExit(f"source image missing: {path}")
        try:
            with Image.open(path) as image:
                width, height = image.size
        except Exception as exc:
            raise SystemExit(f"source image is not readable: {path}: {exc}") from exc
        if width <= 0 or height <= 0:
            raise SystemExit(f"source image has invalid dimensions: {path}: {width}x{height}")
        ratio = width / height
        matched = min(
            COMMON_IMAGE_ASPECTS,
            key=lambda name: abs(ratio - COMMON_IMAGE_ASPECTS[name]) / COMMON_IMAGE_ASPECTS[name],
        )
        relative_error = abs(ratio - COMMON_IMAGE_ASPECTS[matched]) / COMMON_IMAGE_ASPECTS[matched]
        results.append(
            {
                "path": str(path),
                "width": width,
                "height": height,
                "aspect_ratio": round(ratio, 6),
                "matched_aspect": matched if relative_error <= ASPECT_RELATIVE_TOLERANCE else None,
                "relative_error": round(relative_error, 6),
                "status": "PASS" if relative_error <= ASPECT_RELATIVE_TOLERANCE else "FAIL",
            }
        )
    return results


def create_group(client: httpx.Client, args: argparse.Namespace, api_key: str) -> tuple[str, dict]:
    response = client.post(
        openapi_url(args.base_url, "CreateAssetGroup"),
        headers=headers(api_key),
        json={
            "Name": args.group_name or f"viral_replica_{int(time.time())}",
            "GroupType": "AIGC",
            "ProjectName": args.project_name,
        },
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    group_id = extract_id(data)
    if not group_id:
        raise RuntimeError(f"CreateAssetGroup returned no Id: {json.dumps(data, ensure_ascii=False)[:1200]}")
    return group_id, data


def create_asset(
    client: httpx.Client,
    args: argparse.Namespace,
    api_key: str,
    group_id: str,
    url: str,
    role: str,
    index: int,
) -> tuple[str, dict]:
    last_data: dict = {}
    name = safe_name(role, f"image_{index}")
    for attempt in range(1, args.create_retries + 1):
        response = client.post(
            openapi_url(args.base_url, "CreateAsset"),
            headers=headers(api_key),
            json={
                "GroupId": group_id,
                "URL": url,
                "AssetType": "Image",
                "Name": name,
                "ProjectName": args.project_name,
            },
            timeout=60,
        )
        if response.status_code == 429 and attempt < args.create_retries:
            time.sleep(args.retry_wait * attempt)
            continue
        response.raise_for_status()
        last_data = response.json()
        asset_id = extract_id(last_data)
        if asset_id:
            return asset_id, last_data
        time.sleep(args.retry_wait * attempt)
    raise RuntimeError(f"CreateAsset returned no Id: {json.dumps(last_data, ensure_ascii=False)[:1200]}")


def wait_active(
    client: httpx.Client,
    args: argparse.Namespace,
    api_key: str,
    asset_id: str,
) -> tuple[str, dict]:
    start = time.monotonic()
    latest: dict = {}
    while time.monotonic() - start < args.max_wait:
        response = client.post(
            openapi_url(args.base_url, "GetAsset"),
            headers=headers(api_key),
            json={"Id": asset_id, "ProjectName": args.project_name},
            timeout=60,
        )
        response.raise_for_status()
        latest = response.json()
        status = extract_status(latest)
        print(f"asset {asset_id}: {status or 'UNKNOWN'}", flush=True)
        if status == "Active":
            return status, latest
        if status in {"Failed", "Rejected"}:
            return status, latest
        time.sleep(args.poll_interval)
    return "TIMEOUT", latest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--urls", nargs="+", required=True, help="Public http(s) image URLs to create as Pixmax assets.")
    parser.add_argument(
        "--source-files",
        nargs="+",
        type=Path,
        help="Local image files aligned with --urls; checked before any network asset creation.",
    )
    parser.add_argument(
        "--allow-unverified-remote-geometry",
        action="store_true",
        help="Allow URL-only creation when the original local files are genuinely unavailable.",
    )
    parser.add_argument("--roles", nargs="*", default=[], help="Optional role names aligned with --urls.")
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--base-url", default=os.environ.get("SEEDANCE_GATEWAY_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--project-name", default=os.environ.get("SEEDANCE_PIXMAX_PROJECT_NAME", DEFAULT_PROJECT_NAME))
    parser.add_argument("--group-name", default="")
    parser.add_argument("--poll-interval", type=float, default=5)
    parser.add_argument("--max-wait", type=int, default=900)
    parser.add_argument("--create-retries", type=int, default=5)
    parser.add_argument("--retry-wait", type=float, default=20)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.roles and len(args.roles) != len(args.urls):
        raise SystemExit("--roles must have the same length as --urls")
    if args.source_files and len(args.source_files) != len(args.urls):
        raise SystemExit("--source-files must have the same length as --urls")
    if not args.source_files and not args.allow_unverified_remote_geometry:
        raise SystemExit(
            "--source-files is required so image geometry is checked before Pixmax; "
            "use --allow-unverified-remote-geometry only when local originals are unavailable"
        )
    for url in args.urls:
        if not is_http_url(url):
            raise SystemExit(f"Pixmax asset creation needs public http(s) URLs, not: {url}")

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    roles = args.roles or [f"image_{index}" for index in range(1, len(args.urls) + 1)]
    report = {
        "base_url": args.base_url,
        "project_name": args.project_name,
        "group_id": "",
        "overall": "STOP",
        "items": [],
    }
    if args.source_files:
        report["geometry_preflight"] = inspect_source_geometry(args.source_files)
        failures = [item for item in report["geometry_preflight"] if item["status"] != "PASS"]
        if failures:
            report["overall"] = "FAIL"
            args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            failed = failures[0]
            raise SystemExit(
                "non-standard aspect ratio before Pixmax asset creation: "
                f"{failed['path']} is {failed['width']}x{failed['height']}; "
                "create a non-distorted transport copy on a common canvas first"
            )
    else:
        report["geometry_preflight"] = [
            {
                "status": "SKIP",
                "reason": "local source unavailable; caller explicitly allowed unverified remote geometry",
            }
        ]

    api_key = gateway_key()
    with httpx.Client(timeout=httpx.Timeout(60.0), trust_env=False) as client:
        group_id, group_raw = create_group(client, args, api_key)
        report["group_id"] = group_id
        report["group_raw"] = group_raw

        for index, (role, url) in enumerate(zip(roles, args.urls), start=1):
            asset_id, create_raw = create_asset(client, args, api_key, group_id, url, role, index)
            status, latest = wait_active(client, args, api_key, asset_id)
            item = {
                "role": role,
                "source_url": url,
                "asset_id": asset_id,
                "asset_ref": f"asset://{asset_id}",
                "status": status,
                "create_raw": create_raw,
                "latest_raw": latest,
            }
            report["items"].append(item)
            args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            if status != "Active":
                report["overall"] = "FAIL" if status in {"Failed", "Rejected"} else "STOP"
                args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                return 3

    report["overall"] = "PASS"
    args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("asset refs:", " ".join(item["asset_ref"] for item in report["items"]), flush=True)
    print(f"wrote: {args.out_json}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
