# Teardown Guide

Use this when the current stage is `story_analysis` or `storyboard`.

## What To Extract

- Source video duration and target duration.
- Full spoken script from ASR.
- Subtitle text if the video has visible captions.
- Shot table with timestamp, visual action, subtitle text, ASR text, and replication strategy.
- Story structure: hook, conflict, proof, product reveal, offer, call to action.
- Contamination risks: old person, old product, old packaging, old texture, captions, props, scene drift.

## Rule

Do not summarize the source into a generic ad. Preserve the source video function by shot.

## Required Artifact

Write under `output/<job-id>/story-analysis/`:

- `source_probe.json`
- `contact_sheet.jpg`
- `original_asr.md` when audio exists
- `story_analysis.md`
- `shot_table.md`

## PASS Shape

The stage can pass only when a later worker can rebuild the video rhythm without rereading the source video.
