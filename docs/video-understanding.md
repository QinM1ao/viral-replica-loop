# Source Video Understanding

## Purpose

Every new source-video analysis in this repository uses Doubao Seed 2.0 Mini through the Wujie Higress gateway. This is the semantic-video-understanding layer for **看懂原片**; it is not the Seedance video-generation route.

| Setting | Project value |
|---|---|
| Provider | Wujie Higress |
| Base URL | `https://higress-api.wujieai.com/v1` |
| Endpoint | `POST /chat/completions` |
| Protocol | OpenAI Chat Completions |
| Model | `doubao-seed-2-0-mini-260215` |
| Video sampling | full video `fps=2`; opening 0–3s rapid-hook review `fps=5` |
| Source of truth | `rules/VIDEO_UNDERSTANDING_MODEL.json` |

Volcengine's official video-understanding contract accepts a `video_url` content item. A local file can be submitted as a `data:video/mp4;base64,...` URL; the documented local-file limit is 50 MB and the whole request-body limit is 64 MB. This project uses a conservative 45,000,000-byte inline threshold. Larger sources are converted to a temporary 720p H.264/AAC understanding proxy before submission. See [Video understanding](https://docs.volcengine.com/docs/82379/1895586?lang=zh).

## Setup

Set one of these environment variables:

```bash
HIGRESS_API_KEY
WUJIEAI_API_KEY
GATEWAY_API_KEY
```

`tools/video_understanding.py` checks the process environment first, then safely reads the same names from `~/.config/wujieai/env`. It never executes that file and never writes the key to output.

## Direct Smoke Test

```bash
python3 tools/video_understanding.py \
  --video "<local-source-video.mp4>" \
  --out-dir "output/gateway-smoke/video-understanding"
```

Expected files:

- `analysis.json`: normalized project envelope plus the model's structured analysis.
- `analysis.md`: readable summary and timeline.
- `request_manifest.json`: endpoint, model, FPS, hashes, sizes, HTTP status, and token usage; no key or base64.
- `raw_response.json`: complete gateway JSON response for audit.

For a focused rapid-action check, add `--mode rapid_hook --fps 5 --start-seconds 0 --duration-seconds 3`. The normal blueprint command runs this automatically and saves it under `video_understanding/hook_review/`.

## Pipeline Integration

The normal command remains:

```bash
python3 tools/prepare_source_blueprint.py \
  --video "<source-video>" \
  --output-dir "output/<job-id>" \
  --target-duration "<duration>"
```

On a cache miss, `prepare_story_analysis.py` runs four source-reading operations concurrently:

```text
local source video
  ├─ Seed 2.0 Mini full-video understanding at 2fps
  ├─ Seed 2.0 Mini opening rapid-hook review at 5fps
  ├─ Qwen ASR for exact source words
  └─ contact sheet for broad visual inspection

measured source-rhythm lane
  ├─ real cut points
  ├─ 5fps evidence frames
  └─ audio-energy windows

rapid-hook semantics + measured cuts -> hook_review/aligned_timeline.json
all evidence -> checked source_rhythm.json -> current-job story analysis
```

Seed 2.0 Mini is the primary semantic reading: story structure, visual actions, visible text, character roles, product use, speaker mode, and uncertainties. The 5fps rapid-hook result supplies the order and type of sub-second actions, but its model timestamps are not treated as exact. `aligned_timeline.json` snaps those semantic blocks to measured scene cuts and attaches candidate before/contact/after frames. Raw Qwen ASR controls exact spoken words; measured cuts and cited pixels control timing, hard cuts, action peaks, and physical state changes. When the model conflicts with direct evidence, the direct evidence wins and the checker records the conflict.

The model response is cached only with source facts. The cache key includes the source-video SHA-256, the exact video-understanding config, and the hashes of the relevant tools. A model/config/tool change invalidates the cache.

## Gate Behavior

`source_blueprint` cannot record `PASS` unless:

- the understanding request returned HTTP 200;
- provider and model match `rules/VIDEO_UNDERSTANDING_MODEL.json`;
- the analysis source hash matches the current source video;
- the rapid-hook request is `mode=rapid_hook`, `fps=5`, covers the opening 0–3s, and has a non-empty measured-cut-aligned timeline;
- the structured analysis object exists;
- raw ASR, measured rhythm, per-beat frame review, and storyboard-rhythm QC also pass.

Provider failure is a stop condition. The explicit `--skip-video-understanding` flag exists only for offline debugging; its output is not gate-eligible.

## Troubleshooting

| Symptom | Check |
|---|---|
| Missing key | Confirm one supported key name exists in the environment or `~/.config/wujieai/env`. |
| HTTP 401/403 | Confirm the Wujie key is current and authorized for `doubao-seed-2-0-mini-260215`. |
| HTTP 404 | Confirm the Base URL includes `/v1` and the endpoint is `/chat/completions`; do not use Seedance task routes. |
| Timeout/5xx | Retry the same source once. Do not mark the stage understood from contact sheets alone. |
| File too large | Confirm `ffmpeg` and `ffprobe` are installed so the temporary inline proxy can be made. |
| Plausible but wrong detail | Inspect `uncertainties`, raw ASR, visible subtitles, and cited 5fps frames; direct evidence overrides the model. |

The 2026-07-17 job-011 hybrid test is under `output/job-011/experiments/source-blueprint-hybrid-20260717/`: both provider calls returned HTTP 200; the raw 5fps review found `问题 → 鼻部真实涂抹 → 第二个问题 → 下巴真实涂抹`; measured-cut alignment recovered `0.600 / 1.133 / 1.700 / 2.167s`; the complete preparation wall time was 57.688s. No Seedance generation ran.
