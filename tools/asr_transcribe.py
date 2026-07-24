#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from pathlib import Path


DEFAULT_CONTEXT = (
    "中文短视频广告口播。关键词：清洁泥膜，男生有黑头，没黑头，两种状态，"
    "懒人的福音，有黑头闭口，壬二酸，冰河泥，油光，黑头，洗完之后，"
    "紧绷感，毛孔会呼吸，控油面膜，矿物泥，运动完，瓶瓶罐罐，早买早享受。"
)


def run(cmd):
    result = subprocess.run(cmd, text=True, capture_output=True)
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)
    return result


def transcribe_qwen(input_path, out_dir, model_name, context):
    root = Path(__file__).resolve().parents[1]
    cli = root / ".venv-qwen3-asr" / "bin" / "mlx-qwen3-asr"
    if not cli.exists():
        raise SystemExit(f"Qwen3-ASR env not found: {root / '.venv-qwen3-asr'}")
    run([
        str(cli), str(input_path),
        "--model", model_name,
        "--language", "Chinese",
        "--context", context,
        "--output-dir", str(out_dir),
        "--output-format", "json",
        "--quiet",
    ])
    json_files = sorted(out_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not json_files:
        raise SystemExit("Qwen3-ASR did not write a JSON output")
    return json_files[0]


def load_result(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("text", ""), data.get("chunks", [])


def write_markdown(json_path, md_path):
    text, chunks = load_result(json_path)
    lines = [
        "# 原口播 ASR（Qwen3-ASR）",
        "",
        f"- JSON: `{json_path}`",
        "- Engine: `Qwen/Qwen3-ASR-0.6B` via MLX",
        "",
        "## Full Text",
        "",
        text.strip(),
        "",
        "## Chunks",
        "",
    ]
    if chunks:
        for chunk in chunks:
            lines.append(
                f"- {chunk.get('start', 0):.2f}-{chunk.get('end', 0):.2f}: "
                f"{chunk.get('text', '').strip()}"
            )
    else:
        lines.append("- 未输出 chunk。需要人工按句子边界切分。")
    lines.extend([
        "",
        "## QC Reminder",
        "",
        "- 商品名、品牌名、成分词、福利话术必须人工校对。",
        "- 带声音 Seedance 前，必须按完整句子边界切 reference audio。",
        "- 不确定词写入疑似错词清单，不要直接带进最终口播。",
    ])
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--model", default="Qwen/Qwen3-ASR-0.6B")
    parser.add_argument("--context", default=DEFAULT_CONTEXT)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = transcribe_qwen(args.input, args.out_dir, args.model, args.context)
    md_path = args.out_dir / "原口播ASR_qwen.md"
    write_markdown(json_path, md_path)
    print(md_path)


if __name__ == "__main__":
    main()
