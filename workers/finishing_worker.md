# Final Video Finishing Worker

## Canonical Stage

`finishing`

## Purpose

Turn the downloaded, approved Seedance Part videos into one deterministic final MP4 before final technical QC.

This stage is local-only. It does not submit Vibe Editing, MediaKit atomic tools, Seedance retries, or any other paid task. Accidental generated subtitles are handled by the following conditional `subtitle_removal` stage.

## Inputs

- Downloaded Part videos under `output/<job-id>/generation/`.
- Generation log and approved Part selection.
- `output/<job-id>/seedance/director_plan.json` and `output/<job-id>/剧情分析/source_rhythm.json` whenever a cut or speed change could affect a required beat or spoken line.
- `gates/finishing_gate.md`.

## Actions

1. Select only the approved Part files. Do not use failed takes.
2. Initialize an explicit keep-timeline plan:

   ```bash
   python3 tools/finish_video.py init \
     --input "<Part1.mp4>" \
     --input "<Part2.mp4>" \
     --plan "output/<job-id>/finishing/edit_plan.json"
   ```

3. For `source_locked` work, apply `.agents/skills/video-replication/references/source-locked-finishing-duration.md`; start with every selected Part kept in full at `speed=1.0`.
4. If an objective repair is needed, edit only `timeline` in `edit_plan.json`:
   - omit the bad interval by splitting the surrounding keep ranges;
   - use `speed` only in the supported `0.5`–`2.0` range;
   - preserve every required `source_beat_id`, product close-up, proof shot, and spoken product anchor;
   - do not add transitions by default; preserve the approved hard-cut rhythm.
5. Keep the plan caption-free. `subtitles` is invalid here; explicit final captions belong only to `caption_finishing` after Final Technical QC.
6. `finish_video.py init` automatically loads the approved `product_*` reusable references into `product_still_guard`. Keep this guard enabled:
   - consecutive frames that are geometrically dominated by an approved product reference are a hard bug;
   - a normal moving product shot is not a failure merely because its label matches the reference;
   - when the bug is found, use a clean moving product interval from the same rendered video to replace only the visual interval;
   - stream-copy the original audio, preserve total duration, and verify the repaired output no longer triggers the detector;
   - if no safe replacement interval exists, stop instead of inventing a shot or submitting a paid retry.
7. Render the final video:

   ```bash
   python3 tools/finish_video.py render \
     --plan "output/<job-id>/finishing/edit_plan.json" \
     --out-dir "output/<job-id>/final"
   ```

8. Inspect the actual final video, `finish_report.json`, and `product_still_guard.json`. Compare every shortened, omitted, reordered, speed-changed, or automatically replaced interval with the director plan and source rhythm.
9. Build the `finishing` QC Risk Ledger. Its `finishing_story_integrity` family must be reviewed once by the independent checker against the actual final video, edit plan, director plan, source rhythm, and any product-still repair. Bind that review with `tools/checker_review_qc.py`, rebuild the ledger, and require `PASS` before recording the gate.

## Outputs

- `output/<job-id>/finishing/edit_plan.json`
- `output/<job-id>/final/final_video.mp4`
- `output/<job-id>/final/finish_report.json`
- `output/<job-id>/final/finish_report.md`
- `output/<job-id>/final/product_still_guard.json` when approved product references exist
- `output/<job-id>/checks/finishing_qc_risk_ledger.json`
- `output/<job-id>/checks/finishing_gate_review_qc.json`

## Vibe Editing / MediaKit Boundary

Vibe Editing is an orchestration layer: it can interpret editing intent and invoke underlying synthesis plus other MediaKit tools. Atomic MediaKit tools can also be called directly for one focused operation. They are composable, not mutually exclusive. A future cloud route may consume the same explicit plan, while this MVP stays on `executor=local_ffmpeg` and `paid_tasks_submitted=0`.

Do not submit a MediaKit atomic or Vibe task from this free stage. The next stage inspects this exact final master once. It skips clean output and may use the project's one-task standing approval only for confirmed `burned_in` pixels. Vibe Editing remains experimental until exact operation order and timing pass real-video regression cases.

## Gate

`gates/finishing_gate.md`

## PASS Next Status

`subtitle_removal`

## FAIL Retry Variables

Choose exactly one:

- `edit_plan`
- `part_selection`
- `segment_regeneration`

## Stop Conditions

- The bad interval cannot be removed without losing a required beat or breaking speech.
- The selected Part is semantically wrong and needs a paid Seedance regeneration.
- A product-reference still is detected but no safe same-video moving product interval can replace it.
- A non-subtitle MediaKit/Vibe paid task would be required.
