# Generated Subtitle Removal Gate

## Stage

`subtitle_removal`

## Purpose

Ensure accidental generated hard subtitles are conditionally removed without paying on clean videos, hiding damage, replacing the original, or retrying a paid task automatically.

## Required Inputs

- Original `output/<job-id>/final/final_video.mp4`.
- Hash-bound schema-2 `output/<job-id>/subtitle_removal/subtitle_detection.json` for that exact finished master.
- `output/<job-id>/subtitle_removal/subtitle_removal_report.json`.
- `output/<job-id>/subtitle_removal/visual_qc.json` for repaired outputs.
- The actual active output video.

## PASS

Run `tools/subtitle_workflow_qc.py removal` and return `PASS` only when it passes.

For a clean detection branch:

- `action=skipped_clean`.
- `paid_tasks_submitted=0`.
- The active output is the unchanged finished video.
- The final file has zero subtitle streams.
- The independent `subtitle_presence_classification` family passes against the current master and its full-timeline evidence; maker self-classification is not sufficient.

For a `burned_in` branch:

- The detection report binds the exact finished master and contains at least one timed hard-subtitle interval.
- `action=mediakit_pro`, `paid_tasks_submitted=1`, and a task ID is recorded.
- The standing approval token is `workflow_generated_hard_subtitle_v1`.
- A durable schema-1 attempt record was written before submission, records the report's attempt number and the same task ID/source hash, and ends in `completed`. Attempt 1 uses `paid_attempt.json`; explicitly approved retries use append-only `paid_attempt_<n>.json` plus `retry_approval=explicit_user_targeted_retry`.
- The original and repaired output are distinct and hash-bound.
- Full visual QC passes on every former subtitle interval and at least two high-risk temporal windows.
- Every high-risk window has hash-bound timestamped frame evidence at 8fps or denser, and the independent `subtitle_repair_quality` checker family passes for the exact source/output/QC hashes.
- The result has no residual glyphs, blur band, scene-text damage, foreground damage, or repair flicker.
- `automatic_retry_allowed=false`.

## FAIL

Return `FAIL` when the one produced repair artifact exists but visual or technical QC fails. Keep the candidate separate from delivery and report exact defective times.

Retry variable: `subtitle_repair_quality`. It remains locked after failure; a paid retry is not automatic and requires a new explicit user decision.

## STOP

Return `STOP` when:

- Detection or file-hash evidence is missing or stale.
- A hard-subtitle report is marked skipped.
- MediaKit failed or another paid attempt would be required.
- The current official input limits reject the final video.

## Next Status

On pass:

```text
final_qc
```
