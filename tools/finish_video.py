#!/usr/bin/env python3
"""Render a deterministic final video from an explicit finishing plan.

The MVP is intentionally local-only.  It never submits MediaKit or Seedance
tasks; cloud tools can later consume the same plan as alternative executors.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

from product_still_guard import GuardError as ProductStillGuardError
from product_still_guard import guard_video as run_product_still_guard


class PlanError(ValueError):
    pass


def run(command):
    return subprocess.run(command, text=True, capture_output=True, check=False)


def require_tools():
    missing = [name for name in ("ffmpeg", "ffprobe") if not shutil.which(name)]
    if missing:
        raise PlanError(f"missing required tools: {', '.join(missing)}")


def probe(path):
    result = run([
        "ffprobe",
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(path),
    ])
    if result.returncode != 0:
        raise PlanError(f"cannot read media {path}: {result.stderr.strip()}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PlanError(f"invalid ffprobe response for {path}: {exc}") from exc

    streams = data.get("streams", [])
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if video is None:
        raise PlanError(f"input has no video stream: {path}")
    if audio is None:
        raise PlanError(f"input has no audio stream: {path}")

    duration = float(data.get("format", {}).get("duration") or 0)
    if duration <= 0:
        raise PlanError(f"input has invalid duration: {path}")
    frame_rate_text = video.get("avg_frame_rate") or video.get("r_frame_rate") or "25/1"
    try:
        frame_rate = float(Fraction(frame_rate_text))
    except (ValueError, ZeroDivisionError):
        frame_rate = 25.0
    return {
        "path": str(path),
        "duration": duration,
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": frame_rate,
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
        "audio_sample_rate": int(audio.get("sample_rate") or 0),
    }


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PlanError(f"plan does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PlanError(f"plan is not valid JSON: {exc}") from exc


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_media_path(plan_dir, value):
    path = Path(str(value))
    if not path.is_absolute():
        path = plan_dir / path
    return path.resolve()


def validate_product_still_guard(plan_path, plan):
    config = plan.get("product_still_guard")
    if config is None:
        return None
    if not isinstance(config, dict):
        raise PlanError("product_still_guard must be an object")
    if config.get("mode") != "auto_repair":
        raise PlanError("product_still_guard mode must be auto_repair")
    raw_references = config.get("references")
    if not isinstance(raw_references, list) or not raw_references:
        raise PlanError("product_still_guard references must be a non-empty list")
    references = []
    for value in raw_references:
        path = resolve_media_path(plan_path.parent, value)
        if not path.is_file():
            raise PlanError(f"product still guard reference does not exist: {path}")
        if path not in references:
            references.append(path)
    try:
        sample_fps = float(config.get("sample_fps", 4))
    except (TypeError, ValueError) as exc:
        raise PlanError("product_still_guard sample_fps must be a number") from exc
    if not 1 <= sample_fps <= 12:
        raise PlanError("product_still_guard sample_fps must be between 1 and 12")
    return {
        "mode": "auto_repair",
        "references": references,
        "sample_fps": sample_fps,
    }


def validate_plan(plan_path):
    plan = read_json(plan_path)
    if plan.get("version") != 1:
        raise PlanError("plan version must be 1")
    executor = str(plan.get("executor") or "local_ffmpeg")
    if executor != "local_ffmpeg":
        raise PlanError("MVP executor must be local_ffmpeg")

    raw_inputs = plan.get("inputs")
    if not isinstance(raw_inputs, list) or not raw_inputs:
        raise PlanError("plan inputs must be a non-empty list")

    inputs = {}
    input_reports = {}
    for item in raw_inputs:
        if not isinstance(item, dict):
            raise PlanError("each input must be an object")
        input_id = str(item.get("id") or "").strip()
        if not input_id or input_id in inputs:
            raise PlanError(f"input id is missing or duplicated: {input_id!r}")
        path = resolve_media_path(plan_path.parent, item.get("path", ""))
        if not path.is_file():
            raise PlanError(f"input file does not exist: {path}")
        inputs[input_id] = path
        input_reports[input_id] = probe(path)
        input_reports[input_id]["sha256"] = file_sha256(path)

    first_report = next(iter(input_reports.values()))
    if first_report["width"] <= 0 or first_report["height"] <= 0:
        raise PlanError("input video dimensions must be positive")
    first_ratio = first_report["width"] / first_report["height"]
    for input_id, report in input_reports.items():
        if report["width"] <= 0 or report["height"] <= 0:
            raise PlanError(f"input {input_id} video dimensions must be positive")
        ratio = report["width"] / report["height"]
        if abs(ratio - first_ratio) > 0.001:
            raise PlanError(
                f"input {input_id} aspect ratio differs from the first input; "
                "normalize the approved Parts before finishing"
            )

    timeline = plan.get("timeline")
    if not isinstance(timeline, list) or not timeline:
        raise PlanError("plan timeline must be a non-empty list")

    normalized_timeline = []
    expected_duration = 0.0
    for index, item in enumerate(timeline, start=1):
        if not isinstance(item, dict):
            raise PlanError(f"timeline item {index} must be an object")
        input_id = str(item.get("input") or "").strip()
        if input_id not in inputs:
            raise PlanError(f"timeline item {index} references unknown input: {input_id}")
        try:
            start = float(item.get("start", 0))
            end = float(item["end"])
            speed = float(item.get("speed", 1))
        except (KeyError, TypeError, ValueError) as exc:
            raise PlanError(f"timeline item {index} has invalid start/end/speed") from exc
        if start < 0 or end <= start:
            raise PlanError(f"timeline item {index} must satisfy 0 <= start < end")
        if not 0.5 <= speed <= 2.0:
            raise PlanError(f"timeline item {index} speed must be between 0.5 and 2.0")
        input_duration = input_reports[input_id]["duration"]
        if end > input_duration + 0.05:
            raise PlanError(
                f"timeline item {index} end {end:.3f}s exceeds input duration {input_duration:.3f}s"
            )
        normalized = {"input": input_id, "start": start, "end": end, "speed": speed}
        normalized_timeline.append(normalized)
        expected_duration += (end - start) / speed

    output = plan.get("output") or {}
    filename = str(output.get("filename") or "final_video.mp4").strip()
    if filename != "final_video.mp4":
        raise PlanError("MVP output filename must be final_video.mp4")
    try:
        fade = float(output.get("audio_fade_out_seconds", 0))
    except (TypeError, ValueError) as exc:
        raise PlanError("audio_fade_out_seconds must be a number") from exc
    if fade < 0 or fade >= expected_duration:
        raise PlanError("audio_fade_out_seconds must be non-negative and shorter than the output")

    if "subtitles" in plan:
        raise PlanError(
            "local finishing must remain caption-free; use caption_finishing "
            "after Final Technical QC"
        )

    product_guard = validate_product_still_guard(plan_path, plan)

    return {
        "plan": plan,
        "executor": executor,
        "inputs": inputs,
        "input_reports": input_reports,
        "timeline": normalized_timeline,
        "expected_duration": expected_duration,
        "output_filename": filename,
        "audio_fade_out_seconds": fade,
        "product_still_guard": product_guard,
    }


def number(value):
    return f"{value:.6f}".rstrip("0").rstrip(".")


def build_filter(validated):
    input_ids = list(validated["inputs"])
    input_indexes = {input_id: index for index, input_id in enumerate(input_ids)}
    first = validated["input_reports"][input_ids[0]]
    width = first["width"]
    height = first["height"]
    fps = first["fps"] or 25.0
    chains = []
    concat_inputs = []

    for index, item in enumerate(validated["timeline"]):
        source_index = input_indexes[item["input"]]
        start = number(item["start"])
        end = number(item["end"])
        speed = number(item["speed"])
        chains.append(
            f"[{source_index}:v]trim=start={start}:end={end},"
            f"setpts=(PTS-STARTPTS)/{speed},scale={width}:{height},setsar=1,"
            f"fps={number(fps)},format=yuv420p[v{index}]"
        )
        chains.append(
            f"[{source_index}:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS,"
            f"atempo={speed},aresample=48000,"
            f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[a{index}]"
        )
        concat_inputs.append(f"[v{index}][a{index}]")

    chains.append(
        "".join(concat_inputs)
        + f"concat=n={len(validated['timeline'])}:v=1:a=1[vcat][acat]"
    )

    chains.append("[vcat]null[vout]")

    fade = validated["audio_fade_out_seconds"]
    if fade > 0:
        fade_start = max(0.0, validated["expected_duration"] - fade)
        chains.append(f"[acat]afade=t=out:st={number(fade_start)}:d={number(fade)}[aout]")
    else:
        chains.append("[acat]anull[aout]")
    return ";".join(chains)


def write_markdown(path, report):
    lines = [
        "# Final Video Finishing Report",
        "",
        f"- Overall: **{report['overall']}**",
        f"- Output: `{report['output']}`",
        f"- Expected duration: `{report['expected_duration']:.3f}s`",
        f"- Actual duration: `{report['actual_duration']:.3f}s`",
        f"- Timeline segments: `{len(report['timeline'])}`",
        "- Caption-free master: `yes`",
        "",
        "## Timeline",
        "",
    ]
    guard = report.get("product_still_guard")
    if guard:
        lines.insert(8, f"- Product still guard: `{guard['status']}`")
    for item in report["timeline"]:
        lines.append(
            f"- `{item['input']}` {item['start']:.3f}s–{item['end']:.3f}s at {item['speed']:.2f}x"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_render_inputs_unchanged(plan_path, plan_sha256, validated):
    if file_sha256(plan_path) != plan_sha256:
        raise PlanError("edit plan changed during rendering; rerun with the current plan")
    for input_id, report in validated["input_reports"].items():
        if file_sha256(Path(report["path"])) != report["sha256"]:
            raise PlanError(f"input {input_id} changed during rendering; rerun with the current Part")


def render(plan_path, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    for report_name in (
        "finish_report.json",
        "finish_report.md",
        "product_still_guard.json",
    ):
        (out_dir / report_name).unlink(missing_ok=True)
    require_tools()
    plan_sha256 = file_sha256(plan_path)
    validated = validate_plan(plan_path)
    if file_sha256(plan_path) != plan_sha256:
        raise PlanError("edit plan changed while it was being validated; rerun")
    output = out_dir / validated["output_filename"]
    input_args = []
    for path in validated["inputs"].values():
        input_args.extend(["-i", str(path)])

    with tempfile.TemporaryDirectory(prefix="finish-video-", dir=out_dir) as temporary:
        temporary_root = Path(temporary)
        temporary_output = temporary_root / "pre_guard_render.mp4"
        command = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            *input_args,
            "-filter_complex",
            build_filter(validated),
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-shortest",
            str(temporary_output),
        ]
        result = run(command)
        if result.returncode != 0:
            raise PlanError(f"ffmpeg render failed: {result.stderr.strip()}")
        output_report = probe(temporary_output)
        tolerance = max(0.15, 2 / max(output_report["fps"], 1))
        if abs(output_report["duration"] - validated["expected_duration"]) > tolerance:
            raise PlanError(
                "rendered duration differs from plan: "
                f"actual={output_report['duration']:.3f}s "
                f"expected={validated['expected_duration']:.3f}s"
            )
        ensure_render_inputs_unchanged(plan_path, plan_sha256, validated)
        guard_report = None
        guard_config = validated["product_still_guard"]
        if guard_config:
            guarded_output = temporary_root / validated["output_filename"]
            try:
                guard_report = run_product_still_guard(
                    temporary_output,
                    guard_config["references"],
                    guarded_output,
                    sample_fps=guard_config["sample_fps"],
                )
            except ProductStillGuardError as exc:
                raise PlanError(f"product still guard failed: {exc}") from exc
            temporary_output = guarded_output
            output_report = probe(temporary_output)
        ensure_render_inputs_unchanged(plan_path, plan_sha256, validated)
        os.replace(temporary_output, output)

    guard_binding = None
    if guard_report is not None:
        guard_report_path = out_dir / "product_still_guard.json"
        guard_report["input_video"] = "ephemeral_pre_guard_render"
        guard_report["output_video"] = str(output.resolve())
        guard_report["output_sha256"] = file_sha256(output)
        write_json(guard_report_path, guard_report)
        guard_binding = {
            "report": str(guard_report_path.resolve()),
            "report_sha256": file_sha256(guard_report_path),
            "status": guard_report["status"],
            "audio_preserved": guard_report["audio_preserved"],
            "repairs": guard_report["repairs"],
            "references": guard_report["references"],
        }

    report = {
        "overall": "PASS",
        "plan": str(plan_path.resolve()),
        "plan_sha256": plan_sha256,
        "output": str(output.resolve()),
        "output_sha256": file_sha256(output),
        "expected_duration": validated["expected_duration"],
        "actual_duration": output_report["duration"],
        "timeline": validated["timeline"],
        "inputs": validated["input_reports"],
        "caption_free": True,
        "audio_fade_out_seconds": validated["audio_fade_out_seconds"],
        "executor": validated["executor"],
        "paid_tasks_submitted": 0,
    }
    if guard_binding is not None:
        report["product_still_guard"] = guard_binding
    write_json(out_dir / "finish_report.json", report)
    write_markdown(out_dir / "finish_report.md", report)
    print(output)


def init_plan(input_paths, plan_path, fade):
    require_tools()
    if not input_paths:
        raise PlanError("at least one --input is required")
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    inputs = []
    timeline = []
    for index, input_path in enumerate(input_paths, start=1):
        path = input_path.resolve()
        if not path.is_file():
            raise PlanError(f"input file does not exist: {path}")
        metrics = probe(path)
        input_id = f"part{index}"
        relative = os.path.relpath(path, plan_path.parent)
        inputs.append({"id": input_id, "path": relative})
        timeline.append(
            {"input": input_id, "start": 0.0, "end": round(metrics["duration"], 6), "speed": 1.0}
        )
    plan = {
        "version": 1,
        "executor": "local_ffmpeg",
        "inputs": inputs,
        "timeline": timeline,
        "output": {"filename": "final_video.mp4", "audio_fade_out_seconds": fade},
    }
    product_references = discover_product_references(plan_path)
    if product_references:
        plan["product_still_guard"] = {
            "mode": "auto_repair",
            "sample_fps": 4,
            "references": [
                os.path.relpath(path, plan_path.parent)
                for path in product_references
            ],
        }
    with tempfile.NamedTemporaryFile(
        dir=plan_path.parent,
        prefix=f".{plan_path.name}.",
        suffix=".json",
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        write_json(temporary_path, plan)
        validate_plan(temporary_path)
        os.replace(temporary_path, plan_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    print(plan_path)


def discover_product_references(plan_path):
    if plan_path.parent.name != "finishing":
        return []
    job_root = plan_path.parent.parent
    manifest_path = job_root / "visual-assets" / "approved_visual_manifest.json"
    if not manifest_path.is_file():
        return []
    try:
        manifest = read_json(manifest_path)
    except PlanError:
        return []
    reusable_refs = manifest.get("reusable_refs")
    if not isinstance(reusable_refs, dict):
        return []
    repo_root = job_root.parent.parent
    references = []
    for role, value in reusable_refs.items():
        if not str(role).startswith("product_"):
            continue
        path = Path(str(value))
        if not path.is_absolute():
            path = repo_root / path
        path = path.resolve()
        if path.is_file() and path not in references:
            references.append(path)
    return references


def parse_args():
    parser = argparse.ArgumentParser(description="Build a deterministic final video from generated Parts.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create a full-Part edit plan.")
    init_parser.add_argument("--input", action="append", type=Path, required=True)
    init_parser.add_argument("--plan", type=Path, required=True)
    init_parser.add_argument("--audio-fade-out-seconds", type=float, default=0.2)

    render_parser = subparsers.add_parser("render", help="Render and verify an edit plan.")
    render_parser.add_argument("--plan", type=Path, required=True)
    render_parser.add_argument("--out-dir", type=Path, required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        if args.command == "init":
            init_plan(
                args.input,
                args.plan.resolve(),
                args.audio_fade_out_seconds,
            )
        else:
            render(args.plan.resolve(), args.out_dir.resolve())
    except PlanError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
