#!/usr/bin/env python3
"""Understand a local source video with Seed 2.0 Mini through Wujie Higress."""

import argparse
import base64
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import httpx


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "rules" / "VIDEO_UNDERSTANDING_MODEL.json"
DEFAULT_ENV_FILE = Path.home() / ".config" / "wujieai" / "env"
KEY_NAMES = ("HIGRESS_API_KEY", "WUJIEAI_API_KEY", "GATEWAY_API_KEY")
PROMPT_VERSION = "viral-replica-source-video-v1"
RAPID_HOOK_PROMPT_VERSION = "viral-replica-rapid-hook-v1"

ANALYSIS_PROMPT = """你是爆款视频复刻项目的原片理解器。请逐段理解整个视频，同时分析画面、声音、字幕和叙事功能。

只输出一个合法 JSON 对象，不要 Markdown，不要解释。结构如下：
{
  "summary": "一句话概括原片",
  "story_structure": ["按顺序列出剧情/销售结构"],
  "timeline": [
    {
      "start_seconds": 0.0,
      "end_seconds": 1.2,
      "shot_type": "景别和镜头运动",
      "visual_action": "画面中实际发生的动作和可见状态变化",
      "spoken_content": "该段听到的原话；无则为空字符串",
      "speaker_mode": "in_frame_sync|voiceover|dialogue|music_only|silent|uncertain",
      "visible_text": ["字幕、花字、产品包装文字；无则空数组"],
      "story_function": "hook|problem|demonstration|proof|benefit|transition|cta|other",
      "confidence": 0.0
    }
  ],
  "characters": [{"role": "人物剧情角色", "gender_presentation": "male|female|uncertain", "appearance": "可见特征"}],
  "products_and_props": [{"name_or_description": "名称或外观", "visible_text": ["可辨文字"], "usage_actions": ["真实动作"]}],
  "hard_cuts": [0.0],
  "action_peaks": [{"time_seconds": 0.0, "description": "动作峰值或可见状态变化"}],
  "audio_summary": {"speech_style": "语速、情绪、重音、停顿", "music_and_sfx": "音乐和音效"},
  "replication_must_keep": ["复刻时不能丢的原片节拍、证据镜头或声音模式"],
  "uncertainties": ["看不清、听不清或需用抽帧/ASR核验的内容"]
}

要求：
1. timeline 覆盖从开头到结尾，按时间排序，尽量在硬切、说话人或动作功能变化处拆段。
2. 只写视频中实际可见或可听的内容，不脑补产品名称、台词和动作。
3. 口播与画外音必须区分；看不准写 uncertain。
4. confidence 是 0 到 1 的数字。"""

RAPID_HOOK_PROMPT = """你是爆款视频复刻项目的快速动作复核器。这里只分析给定短片内真实可见的连续动作，不从静止帧猜动作。

只输出一个合法 JSON 对象，不要 Markdown，不要解释。结构如下：
{
  "summary": "一句话概括短片内按顺序发生的节拍",
  "timeline": [
    {
      "start_seconds": 0.0,
      "end_seconds": 0.5,
      "visual_action": "画面中实际发生的动作和可见状态变化",
      "visual_action_type": "gesture|physical_change|product_display|talking|other",
      "physical_change_evidence": {
        "contact_visible": true,
        "motion_visible": true,
        "state_before": "动作前可见状态",
        "state_after": "动作后可见状态",
        "visible_result": "画面中可确认的结果"
      },
      "confidence": 0.0
    }
  ],
  "uncertainties": ["看不清或无法确认的内容"]
}

要求：
1. 时间使用原视频绝对秒数，timeline 按动作顺序拆分，不把多个动作合成一段。
2. physical_change 必须同时核对接触、动作过程和动作后状态；缺任一项就如实标 false 或写不确定。
3. 只写短片中实际可见内容，不脑补台词、产品名、动作或结果。
4. 非 physical_change 的 physical_change_evidence 可省略。"""


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_config(path=DEFAULT_CONFIG):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    required = {"provider", "base_url", "endpoint", "model", "fps", "max_inline_video_bytes", "timeout_seconds"}
    missing = sorted(required - set(config))
    if missing:
        raise ValueError(f"video understanding config missing: {', '.join(missing)}")
    return config


def parse_env_file(path=DEFAULT_ENV_FILE):
    values = {}
    path = Path(path).expanduser()
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if key not in KEY_NAMES:
            continue
        try:
            parts = shlex.split(raw_value, comments=True, posix=True)
        except ValueError:
            continue
        if parts:
            values[key] = parts[0]
    return values


def resolve_api_key(env=None, env_file=DEFAULT_ENV_FILE):
    env = os.environ if env is None else env
    file_values = parse_env_file(env_file)
    for name in KEY_NAMES:
        value = str(env.get(name) or file_values.get(name) or "").strip()
        if value:
            return value, name
    raise RuntimeError(
        "missing Higress key: set HIGRESS_API_KEY, WUJIEAI_API_KEY, or GATEWAY_API_KEY "
        f"(also read from {Path(env_file).expanduser()})"
    )


def ffprobe_duration(video):
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffprobe failed")
    return float(result.stdout.strip())


def make_inline_proxy(video, destination, max_bytes):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("video exceeds inline limit and ffmpeg/ffprobe is unavailable")
    duration = ffprobe_duration(video)
    if duration <= 0:
        raise RuntimeError("source video duration is invalid")

    target_bytes = min(int(max_bytes * 0.88), 40_000_000)
    total_kbps = max(320, int(target_bytes * 8 / duration / 1000))
    audio_kbps = 64
    video_kbps = max(256, min(2500, total_kbps - audio_kbps))
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-vf",
        "scale=720:720:force_original_aspect_ratio=decrease:force_divisible_by=2",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-b:v",
        f"{video_kbps}k",
        "-maxrate",
        f"{video_kbps}k",
        "-bufsize",
        f"{video_kbps * 2}k",
        "-c:a",
        "aac",
        "-b:a",
        f"{audio_kbps}k",
        "-movflags",
        "+faststart",
        str(destination),
    ]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0 or not destination.is_file():
        raise RuntimeError(result.stderr.strip() or "failed to create video understanding proxy")
    if destination.stat().st_size > max_bytes:
        raise RuntimeError(
            f"video understanding proxy is still too large: {destination.stat().st_size} > {max_bytes}"
        )
    return command


def prepare_inline_video(video, max_bytes, temp_dir):
    video = Path(video).expanduser().resolve()
    if not video.is_file():
        raise FileNotFoundError(f"source video not found: {video}")
    if video.suffix.lower() == ".mp4" and video.stat().st_size <= max_bytes:
        return video, False, None
    proxy = Path(temp_dir) / "video_understanding_proxy.mp4"
    command = make_inline_proxy(video, proxy, max_bytes)
    return proxy, True, command


def make_video_segment(video, destination, start_seconds, duration_seconds):
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required for focused video review")
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video),
        "-ss",
        str(start_seconds),
        "-t",
        str(duration_seconds),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        "-movflags",
        "+faststart",
        str(destination),
    ]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0 or not destination.is_file():
        raise RuntimeError(result.stderr.strip() or "failed to create focused video segment")
    return command


def build_payload(video, config, prompt=ANALYSIS_PROMPT):
    mime = "video/mp4"
    encoded = base64.b64encode(Path(video).read_bytes()).decode("ascii")
    return {
        "model": config["model"],
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "video_url",
                        "video_url": {
                            "url": f"data:{mime};base64,{encoded}",
                            "fps": config["fps"],
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "response_format": {"type": "json_object"},
        "stream": False,
    }


def response_content(response_json):
    try:
        content = response_json["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("gateway response has no choices[0].message.content") from exc
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        if parts:
            return "\n".join(parts)
    raise ValueError("gateway response content is not text")


def parse_json_content(content):
    text = content.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("model did not return a JSON object")
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("model JSON output must be an object")
    return parsed


def validate_analysis(analysis):
    if not str(analysis.get("summary") or "").strip():
        raise ValueError("model JSON output is missing summary")
    if not isinstance(analysis.get("timeline"), list):
        raise ValueError("model JSON output is missing timeline array")
    return analysis


def validate_rapid_hook_analysis(analysis):
    validate_analysis(analysis)
    required_evidence = {
        "contact_visible",
        "motion_visible",
        "state_before",
        "state_after",
        "visible_result",
    }
    for index, item in enumerate(analysis["timeline"]):
        if item.get("visual_action_type") != "physical_change":
            continue
        evidence = item.get("physical_change_evidence")
        if not isinstance(evidence, dict) or not required_evidence.issubset(evidence):
            raise ValueError(
                f"rapid hook timeline[{index}] is missing physical_change_evidence"
            )
    return analysis


def call_gateway(payload, config, api_key, client=None):
    url = config["base_url"].rstrip("/") + "/" + config["endpoint"].lstrip("/")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=float(config["timeout_seconds"]))
    try:
        for attempt in range(2):
            try:
                response = client.post(url, headers=headers, json=payload)
            except httpx.TransportError as exc:
                if attempt == 1:
                    raise RuntimeError(f"Higress transport failure after retry: {exc}") from exc
                time.sleep(attempt + 1)
                continue
            if response.status_code < 400:
                return response.json(), response.status_code, url
            if response.status_code not in {429, 500, 502, 503, 504} or attempt == 1:
                raise RuntimeError(f"Higress HTTP {response.status_code}: {response.text[:1000]}")
            time.sleep(attempt + 1)
    finally:
        if owns_client:
            client.close()


def render_markdown(result):
    analysis = result["analysis"]
    lines = [
        "# Seed 2.0 Mini Video Understanding",
        "",
        f"- Provider: `{result['provider']}`",
        f"- Model: `{result['model']}`",
        f"- Source SHA-256: `{result['source_sha256']}`",
        f"- Summary: {analysis.get('summary', '')}",
        "",
        "## Story Structure",
        "",
    ]
    lines.extend(f"- {item}" for item in analysis.get("story_structure") or [])
    lines.extend(["", "## Timeline", ""])
    for item in analysis.get("timeline") or []:
        lines.append(
            f"- {item.get('start_seconds', '?')}–{item.get('end_seconds', '?')}s | "
            f"{item.get('speaker_mode', '')} | {item.get('visual_action', '')} | "
            f"{item.get('spoken_content', '')}"
        )
    lines.extend(["", "## Uncertainties", ""])
    lines.extend(f"- {item}" for item in analysis.get("uncertainties") or [])
    return "\n".join(lines).rstrip() + "\n"


def understand_video(
    video,
    out_dir,
    config_path=DEFAULT_CONFIG,
    env_file=DEFAULT_ENV_FILE,
    client=None,
    mode="full",
    fps=None,
    start_seconds=0,
    duration_seconds=None,
):
    total_started = time.perf_counter()
    video = Path(video).expanduser().resolve()
    out_dir = Path(out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    config = dict(load_config(config_path))
    if mode not in {"full", "rapid_hook"}:
        raise ValueError(f"unsupported analysis mode: {mode}")
    if fps is not None:
        config["fps"] = float(fps)
    if not 0.2 <= float(config["fps"]) <= 5:
        raise ValueError("video understanding fps must be between 0.2 and 5")
    start_seconds = float(start_seconds)
    if start_seconds < 0:
        raise ValueError("start_seconds must be zero or greater")
    if duration_seconds is not None:
        duration_seconds = float(duration_seconds)
        if duration_seconds <= 0:
            raise ValueError("duration_seconds must be greater than zero")
    api_key, key_source = resolve_api_key(env_file=env_file)

    with tempfile.TemporaryDirectory(prefix="video-understanding-") as temp_dir:
        review_video = video
        segment_command = None
        used_segment = duration_seconds is not None
        if used_segment:
            review_video = Path(temp_dir) / "focused_segment.mp4"
            segment_command = make_video_segment(
                video,
                review_video,
                start_seconds,
                duration_seconds,
            )
        submitted, used_proxy, proxy_command = prepare_inline_video(
            review_video, int(config["max_inline_video_bytes"]), temp_dir
        )
        prompt = RAPID_HOOK_PROMPT if mode == "rapid_hook" else ANALYSIS_PROMPT
        prompt_version = (
            RAPID_HOOK_PROMPT_VERSION if mode == "rapid_hook" else PROMPT_VERSION
        )
        payload = build_payload(submitted, config, prompt=prompt)
        gateway_started = time.perf_counter()
        raw_response, http_status, url = call_gateway(payload, config, api_key, client=client)
        gateway_duration_seconds = round(time.perf_counter() - gateway_started, 3)
        analysis = parse_json_content(response_content(raw_response))
        analysis = (
            validate_rapid_hook_analysis(analysis)
            if mode == "rapid_hook"
            else validate_analysis(analysis)
        )
        submitted_sha256 = sha256_file(submitted)
        submitted_size = submitted.stat().st_size

    source_segment = None
    if duration_seconds is not None:
        source_duration = ffprobe_duration(video)
        source_segment = {
            "start_seconds": start_seconds,
            "end_seconds": min(source_duration, start_seconds + duration_seconds),
            "timebase": "source_absolute",
        }
    total_duration_seconds = round(time.perf_counter() - total_started, 3)

    result = {
        "schema_version": 1,
        "status": "PASS",
        "provider": config["provider"],
        "protocol": config.get("protocol", "openai-chat-completions"),
        "model": config["model"],
        "endpoint": url,
        "prompt_version": prompt_version,
        "analysis_mode": mode,
        "sampling_fps": config["fps"],
        "source_segment": source_segment,
        "source_video": str(video),
        "source_sha256": sha256_file(video),
        "submitted_video": {
            "used_segment": used_segment,
            "used_proxy": used_proxy,
            "sha256": submitted_sha256,
            "size_bytes": submitted_size,
        },
        "analysis": analysis,
    }
    manifest = {
        "schema_version": 1,
        "provider": config["provider"],
        "model": config["model"],
        "endpoint": url,
        "http_status": http_status,
        "fps": config["fps"],
        "prompt_version": prompt_version,
        "analysis_mode": mode,
        "source_segment": source_segment,
        "key_source": key_source,
        "source_video": str(video),
        "source_sha256": result["source_sha256"],
        "source_size_bytes": video.stat().st_size,
        "submitted_video": result["submitted_video"],
        "segment_command": segment_command,
        "proxy_command": proxy_command,
        "gateway_duration_seconds": gateway_duration_seconds,
        "total_duration_seconds": total_duration_seconds,
        "usage": raw_response.get("usage", {}),
        "response_id": raw_response.get("id", ""),
    }
    (out_dir / "analysis.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "analysis.md").write_text(render_markdown(result), encoding="utf-8")
    (out_dir / "request_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "raw_response.json").write_text(
        json.dumps(raw_response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Understand a local source video with Seed 2.0 Mini through Wujie Higress."
    )
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--mode", choices=("full", "rapid_hook"), default="full")
    parser.add_argument("--fps", type=float)
    parser.add_argument("--start-seconds", type=float, default=0)
    parser.add_argument("--duration-seconds", type=float)
    args = parser.parse_args()
    result = understand_video(
        args.video,
        args.out_dir,
        args.config,
        args.env_file,
        mode=args.mode,
        fps=args.fps,
        start_seconds=args.start_seconds,
        duration_seconds=args.duration_seconds,
    )
    print(args.out_dir.resolve() / "analysis.json")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
