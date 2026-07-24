---
name: video-subtitle-removal
description: Remove subtitles from a generated or supplied video. Use the lossless remux branch for a separate subtitle track and Volcengine AI MediaKit Pro for captions baked into video pixels. Excludes ASR, subtitle extraction or addition, watermarks, and general editing.
---

# Video Subtitle Removal

Within `viral-replica-loop`, preserve the source and choose the cheapest branch that actually removes the subtitle.

## 1. Classify the subtitle

Inspect streams with `ffprobe`, then inspect representative frames.

Inside `viral-replica-loop`, first validate `output/<job-id>/subtitle_removal/subtitle_detection.json` with `tools/subtitle_workflow_qc.py detection`. That adapter checks only the exact finished master and accepts only `clean` or `burned_in`; the standalone skill's separate-track/remux capability does not become a project-flow branch. Missing, stale, or pending evidence is `STOP`.

- No visible subtitle: return the original unchanged with the inspection evidence.
- Separate subtitle track only: remux video and audio without subtitle streams.
- Text baked into the video pixels: continue to the MediaKit branch.

For the remux branch, write a new file with `ffmpeg -i <input> -map 0:v -map 0:a? -c copy <output>` and verify it decodes.

Completion criterion: the subtitle is classified from stream metadata and visible frames, and the selected input is unambiguous.

## 2. Gate the paid repair

Invoke `volcengine-ai-mediakit`. Read its `references/core-api.md` and `references/subtitle-removal.md`, rechecking the official limits and billing rule before a paid call.

Inspect input duration, resolution, codecs, file size, and expected charge. Write to a new output path.

One paid task is authorized by either of these narrow routes:

- the user directly instructs removal from the current named video; or
- inside `viral-replica-loop`, the current generated-video detection report passes, contains `classification=burned_in`, and the subtitle-removal stage records standing approval token `workflow_generated_hard_subtitle_v1`.

The workflow token authorizes only the current job's finished video, only the Pro subtitle-removal endpoint, and only one submission. A clean loop result remains free. In standalone use, a real separate subtitle track can still use the free remux branch, but that capability is outside the loop adapter. Discovery outside the authorized route remains read-only until the user approves the task.

Completion criterion: the input fits current limits, the expected charge is stated, the original is preserved, and exactly one task is authorized.

## 3. Remove baked-in subtitles

Run the shared deterministic client:

```bash
python3 <mediakit-skill-dir>/scripts/mediakit.py erase-subtitles \
  --video /absolute/input.mp4 \
  --output /absolute/input.no-subtitles.mp4
```

Keep the returned task ID. Let a failed task end the paid attempt; a retry is a new approval decision.

Completion criterion: one task reaches a terminal state and a completed artifact is downloaded locally.

## 4. Prove the repair

Read [references/visual-qc.md](references/visual-qc.md) and apply every acceptance check to the actual source and result.

Completion criterion: the result passes metadata, decode, subtitle-residual, temporal-repair, and scene-text preservation checks, or is handed off as `FAIL` with the exact defective times.

## 5. Hand off

Report the method, task ID and status, output metadata, estimated charge, observed limitations, and clickable absolute paths to the result and QC evidence. A failed result remains separate from the deliverable.

Completion criterion: the user can inspect the final video and the evidence without locating any internal task state.

Inside the loop, also write and validate `output/<job-id>/subtitle_removal/subtitle_removal_report.json`. Final QC must use the report's hash-bound `output_video`; a failed or unreviewed candidate never replaces the deliverable.

For the automatic workflow branch, persist `subtitle_removal/paid_attempt.json` before submission and record every submitted task as spent, including failures. A `mediakit_pro` result is not complete from maker-authored booleans: it must carry timestamped hash-bound repair frames and pass the independent `subtitle_repair_quality` checker family. Final QC must contain exactly that active output path and hash.

## Maintenance

When changing the trigger boundary, rerun [evals/trigger_cases.json](evals/trigger_cases.json) with [evals/semantic_config.json](evals/semantic_config.json).
