# Final QC Worker

## Canonical Stage

`final_qc`

## Purpose

Run objective technical checks on generated part videos or final stitched video, then deliver when technical QC passes.

## Inputs

- Generated Seedance part videos.
- Final stitched video, if available.
- Passing `output/<job-id>/subtitle_removal/subtitle_removal_report.json`.
- Approved prompts and request files.
- Source story analysis.
- Reference audio and ASR artifacts only when debugging a reported audio problem.
- `gates/final_video_gate.md`.

## Actions

1. Read the passing subtitle-removal report and use its `output_video` as the only final-QC input. This is the original finished video on a clean branch and the distinct repaired video on a MediaKit branch.
2. Run `ffprobe` duration and stream checks.
3. Run freeze detection, especially near seams.
4. Build a contact sheet of sampled frames.
5. Spot-check:
   - product shape and label
   - face consistency
   - wardrobe consistency
   - skin-tone continuity
   - clay-mask color and thickness
   - obvious seam break, blank frame, or frozen shot
6. Write final QC bound to the exact `output_video` hash.
7. If technical QC passes, immediately deliver the clickable active-video path or embedded video. Do not stop for subjective effect review.
8. If technical QC fails, allow at most one targeted Seedance retry; a repeated failure or second paid retry stops.

Do not run final ASR by default. It is too slow for routine delivery. Run final ASR only when the user asks to verify audio/script, when the generated video has a reported audio defect, or when a specific retry is about missing/duplicated speech.

## Scripted Part

Use this script for technical final QC:

```bash
python3 viral-replica-loop/tools/final_video_qc.py \
  --videos "<final-or-part-video-path>" \
  --target-duration 30 \
  --duration-tolerance 3 \
  --out-dir viral-replica-loop/output/<job-id>/final
```

The script checks video/audio streams, duration, freeze detection, black-screen detection, and creates a contact sheet. The contact sheet is for objective spot checks such as blank frames, obvious wrong person/product, static shots, or visible seam break, not open-ended subjective taste review.

Optional audio/script debugging only:

```bash
python3 viral-replica-loop/tools/asr_transcribe.py \
  "<final-or-part-video-path>" \
  --out-dir viral-replica-loop/output/<job-id>/final/asr_debug

python3 viral-replica-loop/tools/final_video_qc.py \
  --videos "<final-or-part-video-path>" \
  --target-duration 30 \
  --duration-tolerance 3 \
  --brand-term "<product-name>" \
  --asr-md viral-replica-loop/output/<job-id>/final/asr_debug/原口播ASR_qwen.md \
  --out-dir viral-replica-loop/output/<job-id>/final
```

## Outputs

Write under `output/<job-id>/final/`:

- `ffprobe.txt`
- `freezedetect.txt`
- frame contact sheet
- `final_qc.md`
- optional `asr_debug/` only when final ASR was explicitly needed

## Gate

Run:

`gates/final_video_gate.md`

## PASS Next Status

`done`

## FAIL Retry Variables

Choose exactly one:

- `seam_motion_prompt`
- `voiceover_timing`
- `product_reference_binding`
- `identity_binding`
- `segment_regeneration`

## Stop Conditions

- Same technical failure repeats after one targeted retry.
- A second paid Seedance retry would be required.
- More paid generation would be required outside the one allowed targeted retry.
