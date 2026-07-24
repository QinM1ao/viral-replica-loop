# Story Analysis Gate

## Stage

`story_analysis`

## Purpose

Confirm the loop has actually understood the source video before any storyboard, image generation, voiceover, or Seedance work begins.

## Required Inputs

- Source benchmark video from `jobs.csv`.
- Product name and product assets from `jobs.csv`.
- Person/model assets from `jobs.csv`.
- `PRODUCT_CONSTRAINTS.md`.
- ASR transcript, preferably from `tools/asr_transcribe.py`.
- Subtitle layer, if the source video has subtitles.
- Visual timeline or contact sheet.
- Wujie Higress Seed 2.0 Mini `video_understanding/analysis.json` and request evidence.

## Required Output Artifact

The worker must create a story analysis artifact under the job output folder.

It must include:

- Original spoken script or ASR transcript.
- Subtitle text, if present.
- Visual timeline with key shot timestamps.
- Shot-level mapping: visual action, subtitle text, ASR text, replication strategy.
- Product replacement strategy.
- Known contamination risks from old product, old model, captions, props, texture, or packaging.

## PASS

Return `PASS` only if:

- ASR and subtitle layers were both checked when subtitles exist.
- Seed 2.0 Mini understanding uses the configured provider/model, records HTTP 200, and matches the current source hash.
- Key shots have visual action, subtitle text, ASR text, and replacement strategy.
- Product name and user product assets override the old product in the source video.
- Skincare or clay-mask product actions are mapped to the target product's real action.
- The next stage can build a storyboard without rereading the full source video.

## FAIL

Return `FAIL` if:

- The analysis only summarizes the story without shot-level timing.
- Seed 2.0 Mini understanding evidence is absent, failed, mismatched, or used as a substitute for checking exact ASR/subtitle/pixel evidence.
- The source has subtitles but the analysis only uses ASR.
- The source has no subtitles and no ASR transcript is saved.
- Old product texture, packaging, or tool contamination is not identified.

Retry variable:

`analysis_source_layer`

Locked variables:

Product name, product assets, person assets, target duration.

## STOP

Return `STOP` if:

- The source video cannot be read.
- ASR fails and there is no subtitle layer to recover the spoken script.
- The Seed 2.0 Mini provider call fails after one retry or its key is unavailable.
- The product/person assets are missing.

## Next Status

On pass:

```text
story_analyzed
```
