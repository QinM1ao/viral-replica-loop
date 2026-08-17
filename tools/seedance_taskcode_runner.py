#!/usr/bin/env python3
"""Submit a prepared Wujie taskCode request and save recoverable evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

from seedance_request_contract import (
    SEEDANCE25_MAX_DURATION_SECONDS,
    SEEDANCE25_MODEL,
    decode_taskcode_param,
    inspect_taskcode_request,
    reference_audio_urls,
    reference_visual_urls,
)

try:
    import httpx
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "httpx", "-q"])
    import httpx


SEEDANCE_CONFIG = Path("<client-owned-seedance-config>")


def load_gateway_key() -> str:
    config = {}
    if SEEDANCE_CONFIG.exists():
        config = json.loads(SEEDANCE_CONFIG.read_text(encoding="utf-8"))
    return (
        os.environ.get("GATEWAY_API_KEY")
        or os.environ.get("SEEDANCE_API_KEY")
        or config.get("gateway_api_key", "")
    )


def extract_video_url(result: dict) -> str:
    if isinstance(result.get("video_url"), str):
        return result["video_url"]

    content = result.get("content")
    if isinstance(content, dict):
        video_url = content.get("video_url")
        if isinstance(video_url, str):
            return video_url
        if isinstance(video_url, dict) and isinstance(video_url.get("url"), str):
            return video_url["url"]
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "video_url":
                continue
            video_url = item.get("video_url")
            if isinstance(video_url, dict) and isinstance(video_url.get("url"), str):
                return video_url["url"]

    data = result.get("data")
    if isinstance(data, dict):
        if isinstance(data.get("video_url"), str):
            return data["video_url"]
        outputs = data.get("outputs")
        if isinstance(outputs, list):
            for item in outputs:
                if not isinstance(item, dict):
                    continue
                if isinstance(item.get("video_url"), str):
                    return item["video_url"]
                video_url = item.get("video_url")
                if isinstance(video_url, dict) and isinstance(video_url.get("url"), str):
                    return video_url["url"]
    return ""


def probe_video(path: Path) -> dict:
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=index,codec_type,codec_name,width,height,duration",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        return {"error": str(exc)}
    return json.loads(proc.stdout)


def extract_last_frame(video_path: Path, cover_path: Path) -> bool:
    probe = probe_video(video_path)
    try:
        duration = float((probe.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0
    seek_at = max(duration - 0.08, 0)
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{seek_at:.3f}",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(cover_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False
    return cover_path.exists() and cover_path.stat().st_size > 0


def parse_result(raw_result: str) -> dict:
    if not raw_result or raw_result == "任务排队中":
        return {"status": "queueing"}
    try:
        result = json.loads(raw_result)
    except json.JSONDecodeError:
        return {"status": "unknown", "raw_result": raw_result}
    if isinstance(result, dict):
        return result
    return {"status": "unknown", "raw_result": raw_result}


def probe_audio_file(path: Path) -> dict:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_type,codec_name,sample_rate,channels:format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise ValueError(f"ffprobe could not decode reference audio: {proc.stderr.strip()}")
    report = json.loads(proc.stdout)
    streams = report.get("streams") or []
    if not streams or streams[0].get("codec_type") != "audio":
        raise ValueError("ffprobe found no audio stream in reference audio")
    return {
        **streams[0],
        "duration": (report.get("format") or {}).get("duration"),
    }


def validate_reference_audio_urls(request: dict, client) -> list[dict]:
    _body, param = decode_taskcode_param(request)
    max_duration = (
        SEEDANCE25_MAX_DURATION_SECONDS
        if param.get("model") == SEEDANCE25_MODEL
        else 15.0
    )
    reports = []
    with tempfile.TemporaryDirectory(prefix="seedance-audio-preflight-") as directory:
        temp_dir = Path(directory)
        for index, url in enumerate(reference_audio_urls(request), start=1):
            response = client.get(url, timeout=60, follow_redirects=True)
            response.raise_for_status()
            payload = response.content
            if not payload:
                raise ValueError(f"reference audio {index} returned an empty response body: {url}")
            suffix = Path(urlparse(url).path).suffix.lower() or ".audio"
            local_path = temp_dir / f"audio_{index}{suffix}"
            local_path.write_bytes(payload)
            probe = probe_audio_file(local_path)
            duration = float(probe.get("duration") or 0)
            if duration <= 0 or duration > max_duration:
                raise ValueError(
                    f"reference audio {index} must be 0–{max_duration:.2f} seconds, "
                    f"found {duration:.3f}: {url}"
                )
            reports.append(
                {
                    "index": index,
                    "url": url,
                    "http_status": response.status_code,
                    "byte_size": len(payload),
                    **probe,
                }
            )
    return reports


def validate_existing_preflight(path: Path, request_sha256: str) -> dict:
    if not path.is_file():
        raise ValueError(f"reference audio preflight evidence is missing: {path}")
    report = json.loads(path.read_text(encoding="utf-8"))
    if str(report.get("overall") or "").upper() != "PASS":
        raise ValueError(f"reference audio preflight is not PASS: {path}")
    if report.get("request_sha256") != request_sha256:
        raise ValueError(
            f"reference audio preflight request hash does not match: {path}"
        )
    return report


def validate_source_fidelity_qc(request: dict, path: Path) -> dict:
    if not path.is_file():
        raise ValueError(f"source fidelity QC is missing: {path}")
    payload = path.read_bytes()
    report = json.loads(payload.decode("utf-8"))
    if report.get("overall") != "PASS":
        raise ValueError(f"source fidelity QC is not PASS: {path}")
    actual_hash = hashlib.sha256(payload).hexdigest()
    if request.get("source_fidelity_qc_sha256") != actual_hash:
        raise ValueError(
            "source fidelity QC hash does not match the prepared request: "
            f"request={request.get('source_fidelity_qc_sha256')!r}, actual={actual_hash}"
        )
    _body, param = decode_taskcode_param(request)
    prompt = next(
        (
            item.get("text", "")
            for item in param.get("content") or []
            if isinstance(item, dict) and item.get("type") == "text"
        ),
        "",
    )
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    if report.get("prompt_sha256") != prompt_hash:
        raise ValueError("source fidelity QC prompt hash does not match the submitted prompt")
    expected_transcript = str(report.get("expected_transcript") or "")
    transcript_hash = hashlib.sha256(expected_transcript.encode("utf-8")).hexdigest()
    if not expected_transcript or request.get("expected_transcript_sha256") != transcript_hash:
        raise ValueError("source fidelity QC expected transcript is missing or unbound")
    return {
        "overall": "PASS",
        "qc_path": str(path),
        "qc_sha256": actual_hash,
        "source_rhythm_sha256": report.get("source_rhythm_sha256"),
        "prompt_sha256": prompt_hash,
        "expected_transcript_sha256": transcript_hash,
    }


def default_active_asset_manifest_path(request_path: Path) -> Path:
    suffix = "_request_prepared.json"
    if not request_path.name.endswith(suffix):
        return request_path.with_name(f"{request_path.stem}_asset_binding.json")
    part_id = request_path.name[: -len(suffix)]
    return request_path.with_name(f"{part_id}_asset_binding.json")


def validate_active_asset_manifest(request: dict, manifest_path: Path) -> dict:
    if not manifest_path.is_file():
        raise ValueError(f"Active visual asset manifest is missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    items = manifest.get("visual_assets")
    if not isinstance(items, list) or not items:
        raise ValueError(
            "Active visual asset manifest must contain a non-empty visual_assets list"
        )
    inactive = [
        item
        for item in items
        if not isinstance(item, dict) or item.get("status") != "Active"
    ]
    if inactive:
        raise ValueError("Every visual asset manifest item must have Status=Active")
    manifest_refs = [item.get("asset_ref") for item in items]
    request_refs = reference_visual_urls(request)
    if sorted(manifest_refs) != sorted(request_refs):
        raise ValueError(
            "Request visual refs must exactly match the Active asset manifest; "
            f"request={request_refs!r}, manifest={manifest_refs!r}"
        )
    return {
        "overall": "PASS",
        "manifest_path": str(manifest_path),
        "visual_count": len(request_refs),
        "visual_refs": request_refs,
    }


def prior_submission_evidence(out_dir: Path) -> list[Path]:
    return [
        path
        for path in (out_dir / "create_response.json", out_dir / "task_key.txt")
        if path.exists()
    ]


def download(client: httpx.Client, url: str, output: Path) -> None:
    with client.stream("GET", url, timeout=180) as response:
        response.raise_for_status()
        with output.open("wb") as f:
            for chunk in response.iter_bytes():
                if chunk:
                    f.write(chunk)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--active-asset-manifest", type=Path)
    parser.add_argument("--source-fidelity-qc", type=Path)
    parser.add_argument("--poll-interval", type=float, default=10)
    parser.add_argument("--max-wait", type=int, default=5400)
    preflight_group = parser.add_mutually_exclusive_group()
    preflight_group.add_argument("--preflight-only", action="store_true")
    preflight_group.add_argument(
        "--require-existing-preflight",
        action="store_true",
    )
    args = parser.parse_args()

    request_source_bytes = args.request.read_bytes()
    request = json.loads(request_source_bytes.decode("utf-8"))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    request_copy = args.out_dir / "request.json"
    request_contract_path = args.out_dir / "request_contract.json"
    create_response_path = args.out_dir / "create_response.json"
    task_key_path = args.out_dir / "task_key.txt"
    task_info_path = args.out_dir / "task_info.json"
    history_path = args.out_dir / "task_info_history.jsonl"
    summary_path = args.out_dir / "summary.json"
    ffprobe_path = args.out_dir / "ffprobe.json"
    audio_preflight_path = args.out_dir / "reference_audio_preflight.json"
    active_asset_preflight_path = args.out_dir / "active_visual_asset_preflight.json"
    source_fidelity_preflight_path = args.out_dir / "source_fidelity_preflight.json"
    cover_path = args.out_dir / "cover_last_frame.jpg"
    request_copy.write_bytes(request_source_bytes)

    request_contract = inspect_taskcode_request(
        request,
        for_submission=True,
        require_active_visual_assets=True,
        require_seedance_prompt_format=True,
    )
    request_contract["request_path"] = str(request_copy)
    request_contract["request_sha256"] = hashlib.sha256(
        request_copy.read_bytes()
    ).hexdigest()
    request_contract_path.write_text(
        json.dumps(request_contract, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if request_contract["overall"] != "PASS":
        print(
            f"Seedance request contract failed: {request_contract_path}",
            file=sys.stderr,
            flush=True,
        )
        return 2

    _body, request_param = decode_taskcode_param(request)
    if request_param.get("model") == SEEDANCE25_MODEL:
        try:
            if args.source_fidelity_qc is None:
                raise ValueError("Seedance 2.5 requires --source-fidelity-qc")
            fidelity_report = validate_source_fidelity_qc(request, args.source_fidelity_qc)
        except Exception as exc:
            fidelity_report = {
                "overall": "FAIL",
                "qc_path": str(args.source_fidelity_qc or ""),
                "error": str(exc),
            }
            source_fidelity_preflight_path.write_text(
                json.dumps(fidelity_report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"Source fidelity preflight failed: {exc}", file=sys.stderr, flush=True)
            return 2
        source_fidelity_preflight_path.write_text(
            json.dumps(fidelity_report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    active_asset_manifest_path = (
        args.active_asset_manifest
        or default_active_asset_manifest_path(args.request)
    )
    try:
        active_asset_report = validate_active_asset_manifest(
            request,
            active_asset_manifest_path,
        )
    except Exception as exc:
        active_asset_report = {
            "overall": "FAIL",
            "manifest_path": str(active_asset_manifest_path),
            "error": str(exc),
        }
        active_asset_preflight_path.write_text(
            json.dumps(active_asset_report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Active visual asset preflight failed: {exc}", file=sys.stderr, flush=True)
        return 2
    active_asset_preflight_path.write_text(
        json.dumps(active_asset_report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    url = request["url"]
    body = request["body"]
    api_key = load_gateway_key()
    if not api_key:
        print("Missing gateway API key", file=sys.stderr, flush=True)
        return 2

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    with httpx.Client(timeout=httpx.Timeout(60.0), trust_env=False) as client:
        if args.require_existing_preflight:
            try:
                validate_existing_preflight(
                    audio_preflight_path,
                    request_contract["request_sha256"],
                )
            except Exception as exc:
                print(
                    f"Existing reference audio preflight is invalid: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
                return 2
        else:
            try:
                audio_reports = validate_reference_audio_urls(request, client)
            except Exception as exc:
                audio_preflight_path.write_text(
                    json.dumps(
                        {
                            "overall": "FAIL",
                            "request_sha256": request_contract["request_sha256"],
                            "error": str(exc),
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                print(f"Reference audio preflight failed: {exc}", file=sys.stderr, flush=True)
                return 2
            audio_preflight_path.write_text(
                json.dumps(
                    {
                        "overall": "PASS",
                        "request_sha256": request_contract["request_sha256"],
                        "items": audio_reports,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        if args.preflight_only:
            print(
                f"Seedance request preflight PASS: {args.request}",
                flush=True,
            )
            return 0
        prior_submission_files = prior_submission_evidence(args.out_dir)
        if prior_submission_files:
            print(
                "Refusing duplicate Seedance task_create; prior submission evidence exists: "
                + ", ".join(str(path) for path in prior_submission_files),
                file=sys.stderr,
                flush=True,
            )
            return 2
        print(f"Creating Seedance task from {args.request}", flush=True)
        create_response = client.post(url, json=body, headers=headers)
        create_response_path.write_text(create_response.text, encoding="utf-8")
        print("create HTTP", create_response.status_code, flush=True)
        print(create_response.text[:2000], flush=True)
        create_response.raise_for_status()
        create_data = create_response.json()
        if not create_data.get("success"):
            return 3

        create_result = ((create_data.get("data") or {}).get("create_result") or [{}])[0]
        task_key = create_result.get("task_key")
        if not task_key:
            print("No task_key in create response", file=sys.stderr, flush=True)
            return 3
        task_key_path.write_text(task_key + "\n", encoding="utf-8")
        print("Task created:", task_key, flush=True)

        info_url = url.rsplit("/", 1)[0] + "/v2/task_info"
        start = time.monotonic()
        last_result: dict = {}
        while time.monotonic() - start < args.max_wait:
            time.sleep(args.poll_interval)
            info_response = client.get(
                info_url,
                params={"taskKey": task_key},
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=60,
            )
            task_info_path.write_text(info_response.text, encoding="utf-8")
            with history_path.open("a", encoding="utf-8") as f:
                f.write(info_response.text.strip() + "\n")

            try:
                info_data = info_response.json().get("data") or {}
            except json.JSONDecodeError:
                print("non-json task_info:", info_response.text[:500], flush=True)
                continue

            last_result = parse_result(info_data.get("result") or "")
            result_status = last_result.get("status") or ("error" if last_result.get("error") else "unknown")
            elapsed = time.monotonic() - start
            print(f"poll {elapsed:.0f}s gateway={info_data.get('status')} result={result_status}", flush=True)

            if last_result.get("error"):
                print(json.dumps(last_result.get("error"), ensure_ascii=False)[:2000], flush=True)
                return 4
            if result_status in {"failed", "expired"}:
                print(json.dumps(last_result, ensure_ascii=False)[:3000], flush=True)
                return 5

            video_url = extract_video_url(last_result)
            if not video_url:
                continue

            print("Video ready:", video_url[:140], flush=True)
            download(client, video_url, args.output)
            probe = probe_video(args.output)
            ffprobe_path.write_text(json.dumps(probe, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            cover_ok = extract_last_frame(args.output, cover_path)
            streams = probe.get("streams") or []
            summary = {
                "model_family": request.get("model_family") or "",
                "model": decode_taskcode_param(request)[1].get("model") or "",
                "request_source": str(args.request),
                "request": str(request_copy),
                "request_contract": str(request_contract_path),
                "reference_audio_preflight": str(audio_preflight_path),
                "create_response": str(create_response_path),
                "task_key": task_key,
                "task_info": str(task_info_path),
                "history": str(history_path),
                "status": "succeeded",
                "video": str(args.output),
                "video_size_bytes": args.output.stat().st_size,
                "video_url": video_url,
                "ffprobe": str(ffprobe_path),
                "cover_last_frame": str(cover_path) if cover_ok else "",
                "has_audio": any(stream.get("codec_type") == "audio" for stream in streams),
                "duration_seconds_actual": float((probe.get("format") or {}).get("duration") or 0),
            }
            summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print("Downloaded:", args.output, args.output.stat().st_size, flush=True)
            print("Summary:", summary_path, flush=True)
            return 0

    print(f"Timeout after {args.max_wait}s", file=sys.stderr, flush=True)
    return 6


if __name__ == "__main__":
    raise SystemExit(main())
