# Generated Subtitle Removal Worker

## Canonical Stage

`subtitle_removal`

## Purpose

Conditionally clean accidental subtitles from the finished generated video. A clean detection result costs nothing. A hash-bound `burned_in` result authorizes exactly one automatic Volcengine AI MediaKit Pro task for the current job.

## Required Reading

- `.agents/skills/video-subtitle-removal/SKILL.md`
- `.agents/skills/video-subtitle-removal/references/visual-qc.md`
- `gates/subtitle_removal_gate.md`

When the paid branch is selected, also read the installed `volcengine-ai-mediakit` skill and its `references/core-api.md` and `references/subtitle-removal.md` before submission.

## Inputs

- `output/<job-id>/final/final_video.mp4`
- `output/<job-id>/final/finish_report.json`

First inspect only that exact finished master. Sample the complete visible timeline at least every 0.5 seconds, keep timestamped hash-bound frames under `subtitle_removal/subtitle_detection_evidence/`, and write schema-2 `subtitle_removal/subtitle_detection.json` with:

- `finishing_master` and `finishing_master_sha256` bound to `final/final_video.mp4`;
- measured `duration_seconds`;
- exactly one `classification`: `clean` or `burned_in`;
- `subtitle_intervals` for every `burned_in` interval, otherwise an empty list;
- full-timeline `evidence_frames` with path, hash, and timestamp.

Seedance/local finishing has no separate subtitle-track branch. A detected subtitle stream is contradictory evidence and must stop the project flow instead of creating a remux path.

Validate the new detection artifact:

```bash
python3 tools/subtitle_workflow_qc.py detection \
  --report "output/<job-id>/subtitle_removal/subtitle_detection.json" \
  --json-out "output/<job-id>/checks/subtitle_detection_qc.json"
```

Missing, pending, stale, or contradictory detection evidence is `STOP`. Do not infer permission from a loose note or an old contact sheet.

## Branch A: No Burned-In Subtitle

When the finished master is classified as `clean`:

1. Do not submit MediaKit.
2. Keep `final/final_video.mp4` as the active output.
3. Write `subtitle_removal_report.json` with:
   - `action=skipped_clean`
   - `paid_tasks_submitted=0`
   - `output_video` equal to `source_video`
   - `final_subtitle_streams=0`

## Branch B: Confirmed Burned-In Subtitle

When the current finished master is classified as `burned_in`:

1. Treat the user's project instruction as standing approval token `workflow_generated_hard_subtitle_v1` for exactly one current-job MediaKit Pro subtitle-removal task.
2. Recheck the current official tool limits and billing basis, then inspect the final input metadata.
3. Preserve `final/final_video.mp4` unchanged.
4. Before invoking any paid endpoint, write `subtitle_removal/paid_attempt.json` with schema version 1, `attempt_number=1`, the standing approval, current source path/hash, `status=authorized`, and a null task ID. This durable marker blocks automatic stage re-entry from submitting again.
5. Invoke `$video-subtitle-removal` once and write the candidate to:

   ```text
   output/<job-id>/final/final_video_no_subtitles.mp4
   ```

6. Update the same paid-attempt record with the task ID and terminal `completed` or `failed` status. A failed submission or failed result ends the attempt; do not retry automatically. Record the spent task with `--spent-mediakit-subtitle-removal-runs 1` even when the gate fails or stops.
7. Run every check in the project's subtitle-removal visual QC reference. Save the machine evidence at:

   ```text
   output/<job-id>/subtitle_removal/visual_qc.json
   ```

The QC JSON must bind the source and result hashes and include `decode_passed`, `required_audio_preserved`, `subtitles_absent`, `valid_scene_text_preserved`, `foreground_subjects_undamaged`, `temporally_stable`, reviewed subtitle intervals, and at least two high-risk temporal windows. Every high-risk window must contain timestamped, hash-bound frame evidence sampled at 8fps or denser.

## Output

Write:

```text
output/<job-id>/subtitle_removal/subtitle_removal_report.json
```

Required common fields:

```json
{
  "schema_version": 1,
  "overall": "PASS",
  "detection_report": "/absolute/path/to/subtitle_detection.json",
  "detection_sha256": "...",
  "source_video": "/absolute/path/to/final_video.mp4",
  "source_sha256": "...",
  "action": "skipped_clean | mediakit_pro",
  "paid_tasks_submitted": 0,
  "task_id": null,
  "output_video": "/absolute/path/to/active-output.mp4",
  "output_sha256": "...",
  "visual_qc_report": null,
  "paid_attempt_record": null,
  "paid_attempt_sha256": null,
  "standing_approval": null,
  "automatic_retry_allowed": false,
  "attempt_number": null,
  "retry_approval": null,
  "final_subtitle_streams": 0
}
```

For `mediakit_pro`, set `paid_tasks_submitted=1`, provide `task_id`, `visual_qc_report`, the completed `paid_attempt_record` plus its hash, and `standing_approval=workflow_generated_hard_subtitle_v1`.

If the user later explicitly approves a retry, run the stage only with `--allow-paid --approval-recorded --approval-scope targeted_retry --approve-mediakit-subtitle-retry`. Set the next `attempt_number`, write a distinct append-only `paid_attempt_<n>.json`, and set `retry_approval=explicit_user_targeted_retry` in the new report. Never overwrite `paid_attempt.json` or any prior retry evidence.

Validate before the gate:

```bash
python3 tools/subtitle_workflow_qc.py removal \
  --report "output/<job-id>/subtitle_removal/subtitle_removal_report.json" \
  --json-out "output/<job-id>/checks/subtitle_removal_qc.json"
```

Then build the stage QC Risk Ledger:

```bash
python3 tools/qc_risk_ledger.py \
  --root . \
  --job-id <job-id> \
  --stage subtitle_removal
```

Every branch emits `subtitle_presence_classification`, because deciding whether visible pixels contain captions is semantic even when the maker wrote `clean`. A `mediakit_pro` branch also emits `subtitle_repair_quality`. Batch all emitted families into one independent checker invocation, bind the real semantic request path/hash with `tools/checker_review_qc.py`, rebuild the ledger, and require `PASS` before recording the gate.

Record a paid PASS with:

```bash
./run-loop.sh \
  --record-gate-result PASS \
  --spent-mediakit-subtitle-removal-runs 1 \
  --artifact output/<job-id>/checks/subtitle_removal_gate_review.md \
  --apply-transition
```

## PASS Next Status

`final_qc`

The final QC worker must use `output_video` from the passing subtitle-removal report, not assume the pre-removal filename.

## Stop Conditions

- Detection evidence is missing, stale, or still pending.
- MediaKit input is outside the current documented limits.
- The one automatic task fails.
- Visual QC finds residual glyphs, blur bands, scene-text loss, foreground damage, or temporal flicker.
- Another paid task would be required.
