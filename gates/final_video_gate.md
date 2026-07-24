# Final Video Gate

## Stage

`final_qc`

## Purpose

Decide whether generated part videos or the final stitched video have objective technical failures. Subjective final effect review belongs to the user after delivery and is not a loop stop.

## Required Inputs

- Generated part videos.
- Final stitched video, if already stitched.
- Passing subtitle-removal report; its `output_video` is the active final input.
- Approved prompt and request files.
- Source story analysis.
- ffprobe output.
- freezedetect output.
- Contact sheet or sampled frames.

## Required Output Artifact

The worker must create a final QC artifact under the job output folder.

It must include:

- Video paths.
- Duration check.
- Freeze check.
- Seam check.
- Audio/video stream check.
- Product and identity spot check.
- Frame contact sheet path.
- Result: `PASS`, `FAIL`, or `STOP`.

Final ASR is optional, not a routine PASS requirement. Use it only when the user requests audio/script verification, a generated video has an audio/script defect, or the retry variable is `voiceover_timing`.

## PASS

Return `PASS` when objective technical QC passes:

- Duration is close to target.
- No seam freeze above the allowed threshold.
- Video and audio streams are present when the job is sound-enabled.
- No obvious silent tail, duplicated boundary line, or missing speech is visible/audible in quick spot review.
- Product, face, mud texture, wardrobe, and scene are not obviously broken.
- The final video is ready to deliver.
- The checked video path and hash match the active `output_video` from `subtitle_removal_report.json`.

## FAIL

Return `FAIL` if:

- Freeze occurs near a seam.
- Quick spot review or optional ASR shows rushed, duplicated, missing, or boundary-crossing speech.
- Product texture changes from approved white thick mud to gray or watery mud.
- Face, skin tone, or wardrobe changes too much across parts.
- Product shape or label becomes unrecognizable.

Retry variable:

Choose exactly one:

- `seam_motion_prompt`
- `voiceover_timing`
- `product_reference_binding`
- `identity_binding`
- `segment_regeneration`

Locked variables:

Passed segments, approved references, approved prompt sections that did not fail.

## STOP

Return `STOP` when:

- Technical QC failure repeats after one targeted retry.
- A second paid Seedance retry would be required.
- More paid generation would be required outside the one allowed targeted retry.

## Next Status

On technical pass:

```text
done
```
