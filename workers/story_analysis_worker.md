# Story Analysis Worker

## Canonical Stage

`story_analysis`

## Purpose

Turn one source video into a usable replication brief before any image, voice, seam, or Seedance work.

## Inputs

- Selected `jobs.csv` row.
- Source video path.
- Product name.
- Product assets folder.
- Person/model assets folder.
- Audio setting from `jobs.csv`.
- `PRODUCT_CONSTRAINTS.md`.
- `QC_RULES.md`.
- ASR tool: `tools/asr_transcribe.py`.

## Actions

1. Read the selected job row and `PRODUCT_CONSTRAINTS.md`.
2. Extract or inspect source audio.
3. Run `tools/prepare_story_analysis.py`; its required Wujie Higress Seed 2.0 Mini call supplies semantic video understanding. Run Qwen ASR when original speech is needed.
4. Extract subtitles if the source video has visible subtitles.
5. Create a visual timeline or contact sheet from the source video.
6. Build a shot table with:
   - timestamp
   - visual action
   - subtitle text
   - ASR text
   - product/person replacement strategy
   - contamination risks
7. Preserve original rhythm and product-name placement.

## Scripted Part

This script prepares the mechanical materials:

```bash
python3 viral-replica-loop/tools/prepare_story_analysis.py \
  --video "<source-video-path>" \
  --out-dir viral-replica-loop/output/<job-id>/剧情分析 \
  --run-asr
```

It creates required Seed 2.0 Mini structured video understanding, probe data, a contact sheet, and optional ASR output. Codex/human review must reconcile model claims against direct ASR/subtitle/pixel evidence.

## Outputs

Write under `output/<job-id>/剧情分析/`:

- `原口播ASR.md`
- `字幕层整理.md`, if subtitles exist
- `画面时间线.md`
- `剧情分析.md`
- contact sheet or extracted key frames
- `video_understanding/analysis.json`, `analysis.md`, `request_manifest.json`, and `raw_response.json`

## Gate

Run:

`gates/story_analysis_gate.md`

## PASS Next Status

`story_analyzed`

## FAIL Retry Variables

Choose exactly one:

- `asr_layer`
- `subtitle_layer`
- `visual_timeline`
- `replacement_strategy`

## Stop Conditions

- Source video cannot be read.
- Seed 2.0 Mini provider/model/hash/request evidence is unavailable or invalid.
- ASR and subtitle layers are both unavailable.
- Product or person asset folder is missing.
