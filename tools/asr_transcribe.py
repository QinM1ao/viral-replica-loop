#!/usr/bin/env python3
"""Transcribe source audio with ElevenLabs Scribe through Wujie Higress."""

import argparse
import hashlib
import json
import mimetypes
import os
import shlex
import time
from pathlib import Path

try:
    import httpx
except ModuleNotFoundError:  # Thin no-spend/plugin checks do not make ASR requests.
    httpx = None


class _UnavailableHttpxError(Exception):
    pass


HTTPX_ERROR = httpx.HTTPError if httpx is not None else _UnavailableHttpxError

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "rules" / "ASR_MODEL.json"
DEFAULT_ENV_FILE = Path.home() / ".config" / "wujieai" / "env"
KEY_NAMES = ("HIGRESS_API_KEY", "WUJIEAI_API_KEY", "GATEWAY_API_KEY")
SENTENCE_ENDINGS = frozenset("。！？!?；;")


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


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_config(path=DEFAULT_CONFIG):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    required = {
        "provider",
        "endpoint",
        "model",
        "language_code",
        "diarize",
        "tag_audio_events",
        "timestamps_granularity",
        "timeout_seconds",
    }
    missing = sorted(required - set(config))
    if missing:
        raise ValueError(f"ASR config missing: {', '.join(missing)}")
    if config["provider"] != "elevenlabs":
        raise ValueError("ASR provider must be elevenlabs")
    if config["timestamps_granularity"] not in {"word", "character"}:
        raise ValueError("ASR timestamps must remain word- or character-level")
    return config


def check_asr_provider(config_path=DEFAULT_CONFIG, env_file=DEFAULT_ENV_FILE):
    config = load_config(config_path)
    _key, key_name = resolve_api_key(env_file=env_file)
    return f"elevenlabs:{config['model']} via {key_name}"


def _normalized_word(item):
    text = str(item.get("text") or "")
    start = item.get("start")
    end = item.get("end")
    if not text:
        raise ValueError("ElevenLabs word item has no text")
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        raise ValueError("ElevenLabs word item has invalid timestamps")
    if float(start) < 0 or float(end) < float(start):
        raise ValueError("ElevenLabs word item timestamps are out of order")
    normalized = {
        "text": text,
        "start": float(start),
        "end": float(end),
        "type": str(item.get("type") or "word"),
        "speaker_id": item.get("speaker_id"),
    }
    if isinstance(item.get("logprob"), (int, float)):
        normalized["logprob"] = float(item["logprob"])
    if isinstance(item.get("channel_index"), int):
        normalized["channel_index"] = item["channel_index"]
    return normalized


def _finish_segment(items):
    if not items:
        return None
    speakers = sorted(
        {str(item["speaker_id"]) for item in items if item.get("speaker_id")}
    )
    return {
        "speaker_id": speakers[0] if len(speakers) == 1 else None,
        "speaker_ids": speakers,
        "start": items[0]["start"],
        "end": items[-1]["end"],
        "text": "".join(item["text"] for item in items),
    }


def _speaker_changed(items, item):
    incoming = item.get("speaker_id")
    if not incoming:
        return False
    previous = next(
        (entry.get("speaker_id") for entry in reversed(items) if entry.get("speaker_id")),
        None,
    )
    return bool(previous and incoming != previous)


def _speaker_turns(words, gap_seconds=0.8):
    turns = []
    current = []
    for item in words:
        if item["type"] == "audio_event":
            continue
        speaker_changed = _speaker_changed(current, item)
        gap = item["start"] - current[-1]["end"] if current else 0
        if current and (speaker_changed or gap > gap_seconds):
            turns.append(_finish_segment(current))
            current = []
        current.append(item)
    if current:
        turns.append(_finish_segment(current))
    return turns


def _sentence_segments(words, gap_seconds=0.8):
    segments = []
    current = []
    for item in words:
        if item["type"] == "audio_event":
            continue
        speaker_changed = _speaker_changed(current, item)
        gap = item["start"] - current[-1]["end"] if current else 0
        if current and (speaker_changed or gap > gap_seconds):
            segments.append(_finish_segment(current))
            current = []
        current.append(item)
        if item["text"] and item["text"][-1] in SENTENCE_ENDINGS:
            segments.append(_finish_segment(current))
            current = []
    if current:
        segments.append(_finish_segment(current))
    return segments


def build_timeline(result, model="scribe_v1"):
    text = result.get("text")
    raw_words = result.get("words")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("ElevenLabs response has no transcript text")
    if not isinstance(raw_words, list) or not raw_words:
        raise ValueError("ElevenLabs response has no word timestamps")
    words = [_normalized_word(item) for item in raw_words]
    spoken_text = "".join(
        item["text"] for item in words if item["type"] != "audio_event"
    )
    if spoken_text != text:
        raise ValueError("ElevenLabs word timeline does not reconstruct transcript text")
    return {
        "schema_version": 1,
        "provider": "elevenlabs",
        "model": model,
        "transcription_id": result.get("transcription_id"),
        "language_code": result.get("language_code"),
        "language_probability": result.get("language_probability"),
        "audio_duration_secs": result.get("audio_duration_secs"),
        "words": words,
        "speaker_turns": _speaker_turns(words),
        "sentence_segments": _sentence_segments(words),
        "audio_events": [item for item in words if item["type"] == "audio_event"],
    }


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def transcribe_elevenlabs(
    input_path,
    out_dir,
    *,
    config_path=DEFAULT_CONFIG,
    api_key=None,
    env_file=DEFAULT_ENV_FILE,
    client=None,
    model=None,
    language_code=None,
    num_speakers=None,
):
    input_path = Path(input_path).expanduser().resolve()
    out_dir = Path(out_dir).expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"ASR input is unavailable: {input_path}")
    config = load_config(config_path)
    if api_key is None:
        api_key, key_name = resolve_api_key(env_file=env_file)
    else:
        key_name = "explicit"
    model = model or config["model"]
    language_code = language_code or config["language_code"]
    form = {
        "model_id": model,
        "language_code": language_code,
        "diarize": str(bool(config["diarize"])).lower(),
        "tag_audio_events": str(bool(config["tag_audio_events"])).lower(),
        "timestamps_granularity": config["timestamps_granularity"],
    }
    if num_speakers is not None:
        if not 1 <= int(num_speakers) <= 32:
            raise ValueError("num_speakers must be between 1 and 32")
        form["num_speakers"] = str(int(num_speakers))

    out_dir.mkdir(parents=True, exist_ok=True)
    owned_client = client is None
    if owned_client:
        if httpx is None:
            raise RuntimeError("ElevenLabs transcription requires the httpx package")
        client = httpx.Client(timeout=float(config["timeout_seconds"]))
    started = time.perf_counter()
    try:
        for attempt in range(2):
            with input_path.open("rb") as source:
                response = client.post(
                    config["endpoint"],
                    headers={"Authorization": f"Bearer {api_key}"},
                    data=form,
                    files={
                        "file": (
                            input_path.name,
                            source,
                            mimetypes.guess_type(input_path.name)[0]
                            or "application/octet-stream",
                        )
                    },
                )
            response.raise_for_status()
            try:
                result = response.json()
            except ValueError as exc:
                if attempt == 1:
                    raise RuntimeError(
                        "ElevenLabs returned an empty response after retry"
                    ) from exc
                time.sleep(attempt + 1)
                continue
            if attempt == 1 or str(result.get("text") or "").strip() or result.get("words"):
                break
            time.sleep(attempt + 1)
    finally:
        if owned_client:
            client.close()
    elapsed = round(time.perf_counter() - started, 3)
    timeline = build_timeline(result, model=model)

    json_path = out_dir / "elevenlabs_scribe_v1.json"
    timeline_path = out_dir / "asr_timeline.json"
    manifest_path = out_dir / "request_manifest.json"
    _write_json(json_path, result)
    _write_json(timeline_path, timeline)
    _write_json(
        manifest_path,
        {
            "schema_version": 1,
            "provider": "elevenlabs",
            "gateway": "wujie_higress",
            "endpoint": config["endpoint"],
            "model": model,
            "key_source": key_name,
            "source": str(input_path),
            "source_sha256": sha256_file(input_path),
            "source_bytes": input_path.stat().st_size,
            "parameters": form,
            "http_status": response.status_code,
            "elapsed_seconds": elapsed,
            "transcription_id": result.get("transcription_id"),
            "raw_response_sha256": sha256_file(json_path),
            "timeline_sha256": sha256_file(timeline_path),
        },
    )
    return json_path


def write_markdown(json_path, md_path):
    json_path = Path(json_path)
    md_path = Path(md_path)
    result = json.loads(json_path.read_text(encoding="utf-8"))
    timeline_path = json_path.parent / "asr_timeline.json"
    timeline = (
        json.loads(timeline_path.read_text(encoding="utf-8"))
        if timeline_path.is_file()
        else build_timeline(result)
    )
    lines = [
        "# 原口播 ASR（ElevenLabs Scribe v1）",
        "",
        f"- JSON: `{json_path}`",
        f"- Timeline: `{timeline_path}`",
        "- Provider: `ElevenLabs Scribe v1` through Wujie Higress",
        f"- Transcription ID: `{timeline.get('transcription_id') or ''}`",
        f"- Language: `{timeline.get('language_code') or ''}`",
        f"- Audio duration: `{float(timeline.get('audio_duration_secs') or 0):.3f}s`",
        "",
        "## Full Text",
        "",
        result["text"].strip(),
        "",
        "## Speaker Turns",
        "",
    ]
    for turn in timeline["speaker_turns"]:
        lines.append(
            f"- {turn['start']:.2f}-{turn['end']:.2f} "
            f"[{turn.get('speaker_id') or 'unknown'}]: {turn['text'].strip()}"
        )
    if not timeline["speaker_turns"]:
        lines.append("- 未检测到说话人片段。")
    lines.extend(["", "## Sentence Segments", ""])
    for segment in timeline["sentence_segments"]:
        lines.append(
            f"- {segment['start']:.2f}-{segment['end']:.2f} "
            f"[{segment.get('speaker_id') or 'unknown'}]: {segment['text'].strip()}"
        )
    if timeline["audio_events"]:
        lines.extend(["", "## Audio Events", ""])
        for event in timeline["audio_events"]:
            lines.append(
                f"- {event['start']:.2f}-{event['end']:.2f}: {event['text'].strip()}"
            )
    lines.extend(
        [
            "",
            "## QC Reminder",
            "",
            "- 原始 ASR、时间戳和 speaker_id 必须原样保留作为证据层。",
            "- 商品名、品牌名、成分词和明显语义错词由审校层修正，不覆盖原始证据。",
            "- speaker_id 只能区分声音；画外音、画内同期声仍需结合画面判断。",
            "- 音频切分优先复用 Sentence Segments，不再人工猜句子边界。",
        ]
    )
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, nargs="?")
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--model")
    parser.add_argument("--language-code")
    parser.add_argument("--num-speakers", type=int)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    if args.check:
        try:
            print(check_asr_provider(args.config, args.env_file))
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            parser.error(str(exc))
        return
    if args.input is None or args.out_dir is None:
        parser.error("input and --out-dir are required unless --check is used")

    try:
        json_path = transcribe_elevenlabs(
            args.input,
            args.out_dir,
            config_path=args.config,
            env_file=args.env_file,
            model=args.model,
            language_code=args.language_code,
            num_speakers=args.num_speakers,
        )
        md_path = args.out_dir / "原口播ASR_elevenlabs.md"
        write_markdown(json_path, md_path)
    except (OSError, RuntimeError, ValueError, HTTPX_ERROR) as exc:
        parser.error(str(exc))
    print(md_path)


if __name__ == "__main__":
    main()
