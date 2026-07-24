# Source Blueprint Gate

## Layer

`source_blueprint`

## Purpose

Confirm in one gate that the fast preparation command produced reusable source facts without cache contamination and that the current-job story analysis plus storyboard plan are complete enough to enter ImageGen.

## Required Inputs

- Current job source video.
- Current job target duration.
- `output/<job-id>/checks/source_blueprint_report.json`.
- `output/<job-id>/剧情分析/video_understanding/analysis.json`, `request_manifest.json`, and `raw_response.json`.
- `output/<job-id>/剧情分析/video_understanding/hook_review/analysis.json`, `request_manifest.json`, `raw_response.json`, and `aligned_timeline.json`.
- `output/<job-id>/剧情分析/source_rhythm.json` and its 5fps evidence frames.
- `output/<job-id>/checks/source_rhythm_qc.json`.
- `output/<job-id>/checks/source_rhythm_visual_review.json` and `source_rhythm_visual_review_qc.json`.
- Every artifact listed in that report.
- Current `product_profile.json`.
- Current-job story analysis, visual timeline, subtitle layer, canonical shot table, storyboard/seam audit, and contamination audit.

## PASS

Return `PASS` only if:

- `overall` is `PASS`.
- `source_sha256` matches the current source video bytes.
- `groups` equals `ceil(target_duration_seconds / 15)`.
- `total_frames` equals `groups * 12`.
- All entries under `task_timings` are `PASS` on a miss or `CACHE_HIT` on a hit.
- Video understanding is `status=PASS`, uses the provider/model/FPS in `rules/VIDEO_UNDERSTANDING_MODEL.json`, records HTTP 200, and its source SHA-256 matches the current source video.
- Rapid-hook understanding is `status=PASS`, uses the same provider/model with `mode=rapid_hook`, `fps=5`, and source segment 0–3s. Its aligned timeline is non-empty and uses measured scene cuts rather than model timestamps.
- The worker used Seed 2.0 Mini for semantic coverage but resolved exact words, hard cuts, action peaks, and physical state changes against raw ASR and measured pixel evidence; unresolved model/direct-evidence conflicts are not PASS.
- Probe JSON, contact sheet, ASR markdown, and source-material index exist.
- The preparation report includes a passing `prepare_source_rhythm` task. The rhythm artifact contains real scene-score cut points, audio-energy samples when the source has audio, 5fps evidence frames, and the unchanged raw ASR text.
- `source_rhythm_qc.json` is `PASS`: beats are non-empty and ordered; exact lines come from ASR character spans; every correction cites visible-text evidence; claimed hard cuts match detected cut points; speaker mode, emphasis, pause, action peaks, visual action, emotion function, rhythm class, priority, transition type, and evidence frames are present.
- Every schema-v3 beat declares pixel-derived scene, camera, framing, and `visual_action_type`. A `physical_change` beat cites distinct real before/peak/after frames and records the observed motion, before-state, after-state, and visible result.
- Every `spoken_product_names` item is an exact substring of the confirmed source line and the checker confirms it is actually a product/brand entity; hook text or a whole selling sentence cannot be mislabeled as a product name.
- The storyboard manifest reports the requested `groups` and `total_frames`.
- The final storyboard manifest reports `selection_mode=source_rhythm`; every `must_keep` / `mergeable` beat appears exactly once, and beats with action peaks use `selection_reason=action_peak`.
- Every expected `source_storyboard_partX.jpg` exists and the manifest contains exactly one Part entry per group.
- Every path listed under `artifacts` resolves inside the current job output.
- Cache restoration preserved any pre-existing product-specific analysis prose in the job output.
- The cache entry contains source facts only.
- Story analysis preserves the source narrative skeleton, complete line/speaker evidence, and source speaker mode row by row.
- `source_rhythm.json` is the canonical timing/line/rhythm record. The shot table and storyboard documents reference its beat ids instead of freely rewriting the same facts.
- Multi-person role mapping applies the approved identity only to the protagonist/product-host role.
- Product actions are translated to the loaded product profile before ImageGen, with old hardware/material/text explicitly excluded.
- Part assignment preserves source order, 12-panel geometry, action rhythm, and safe seam candidates.
- Independent checker review and checker QC pass for `source_blueprint` in self-audit mode.
- The independent checker reviews every source beat, including `removable`, cites only real frame refs already attached to that beat, confirms both the action description and `visual_action_type` against pixels, and verifies every declared `spoken_product_names` entry is actually a product or brand entity. The QC report must bind schema v3 and the exact source-rhythm hash. `source_rhythm_visual_review_qc.json` must be `PASS`; a prose summary or author-declared substring alone cannot pass.

## FAIL

Return `FAIL` if:

- The report is missing, malformed, or says `FAIL`.
- The source hash or duration-derived Part math does not match.
- A task failed or a required artifact is missing.
- Either Seed 2.0 Mini video-understanding request is absent, failed, points at a different source, or uses a different provider/model/mode/FPS/segment.
- A rapid hook is collapsed into broad model blocks, keeps coarse model timestamps instead of measured cut points, or lacks candidate pixel evidence for a claimed physical change.
- A cache hit restored paths that still point into `.cache/source-blueprint/` or another job.
- The cache contains target-product analysis, replacement strategy, contamination decisions, or action-remapping prose.
- Existing current-job analysis prose was deleted or overwritten during restoration.
- Source-rhythm beats are empty, a source line differs from its evidence-backed ASR span, a correction lacks timestamped visible-text evidence, a claimed hard cut is not measured, or source-rhythm QC is missing/failing.
- A physical-change beat lacks verified before/peak/after states, the checker skipped a required beat, or the rhythm-aware storyboard selection is missing/duplicated.

Retry variable:

`source_rhythm_authorship`

Locked variables:

Source video bytes and target duration.

## STOP

Return `STOP` if the source video cannot be read, target duration cannot be parsed, the Higress key is unavailable, or the Seed 2.0 Mini provider request still fails after one retry.

## Next

On pass, advance directly to `storyboard_passed`, whose next runnable stage is `image_batch_qc`. Keep the old `story_analysis -> storyboard` route only for legacy statuses and focused repair.
