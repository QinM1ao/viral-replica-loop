# Final Video Finishing Gate

## Stage

`finishing`

## Purpose

Confirm that approved generated Parts were assembled into one auditable final video without hidden paid work or loss of required content.

## Required Inputs

- Approved generated Part videos.
- `output/<job-id>/finishing/edit_plan.json`.
- `output/<job-id>/final/finish_report.json`.
- `output/<job-id>/final/final_video.mp4`.
- `output/<job-id>/final/product_still_guard.json` when the approved visual manifest contains `product_*` reusable references.
- For any cut, omission, reorder, or speed change: `output/<job-id>/seedance/director_plan.json` and `output/<job-id>/剧情分析/source_rhythm.json`.

## PASS

Return `PASS` only when:

- `edit_plan.json` uses schema version 1 and an explicit ordered keep timeline.
- Every timeline interval is inside its source Part and uses speed `0.5`–`2.0`.
- The output exists, is readable, and contains video and audio streams.
- Actual duration matches the plan duration within the renderer tolerance.
- The plan satisfies `.agents/skills/video-replication/references/source-locked-finishing-duration.md`.
- `finish_report.json` has `overall=PASS`, `executor=local_ffmpeg`, and `paid_tasks_submitted=0`.
- The report's plan, input Part, and output hashes match the current files; stale PASS evidence is rejected.
- The report inputs exactly match `generation/selected_outputs.json`.
- When approved product references exist, `edit_plan.json` enables `product_still_guard=auto_repair`, the guard report is bound to the current references and final output, and its verification contains no reference-dominant interval.
- A guard repair changes only video pixels: the before/after audio packet hashes are identical, duration remains inside renderer tolerance, and `paid_tasks_submitted=0`.
- No required source beat, spoken product anchor, product close-up, proof shot, or final product close is removed.
- The `finishing_story_integrity` semantic family is bound to the current plan/output/director/rhythm hashes and passes one independent checker review.
- `edit_plan.json` contains no `subtitles` field and `finish_report.json` records `caption_free=true`.

## FAIL

Return `FAIL` if:

- The plan is invalid or references a missing/failed Part.
- Rendering fails or the output duration does not match the plan.
- The output loses video/audio, removes a required beat, breaks a spoken line, or reorders the story.
- An approved product reference directly dominates consecutive final-video frames, or a claimed local repair changes the audio/duration or leaves the same finding behind.
- The finishing plan tries to add captions or any other visible text overlay.

Retry variable: choose exactly one:

- `edit_plan`
- `part_selection`
- `segment_regeneration`

Locked variables: approved Parts and keep-ranges that already passed.

## STOP

Return `STOP` when:

- The defect needs a paid Seedance regeneration and no targeted approval exists.
- The repair needs a paid MediaKit/Vibe task but the applicable cost gate has not passed or the user has not explicitly approved it.
- Removing the defect would also remove a required beat or make speech incoherent.
- The product-reference still is confirmed but no clean moving product interval from the same video can replace it safely.

## Next Status

On pass:

```text
subtitle_removal
```
