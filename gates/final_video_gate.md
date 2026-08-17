# Final Video Gate

## Stage

`final_qc`

## Purpose

Decide whether generated part videos or the final stitched video have objective technical failures. Subjective final effect review belongs to the user after delivery and is not a loop stop.

## Required Inputs

- Passing subtitle-removal report; its `output_video` is the active final input.
- Passing subtitle-removal QC Risk Ledger proving full-timeline subtitle classification already completed.
- `final_qc.json` from the one objective technical scan.
- For sound-enabled Seedance 2.5 `source_locked`, passing `output_dialogue_qc.json` bound to the submitted source-fidelity report and generated-master ASR.

## Required Output Artifact

The worker must create `final/final_qc.json` and `final/final_qc.md` under the job output folder.

It must include:

- Video paths.
- Duration check.
- Freeze check.
- Black-frame and full-decode check.
- Audio/video stream check.
- Active-video path and hash binding.
- Result: `PASS`, `FAIL`, or `STOP`.

Final ASR is required for sound-enabled Seedance 2.5 `source_locked`. It remains optional for other jobs unless the user requests audio/script verification, a generated video has an audio/script defect, or the retry variable is `voiceover_timing`.

This is a deterministic gate. 不需要独立 checker，也不需要再写一份人工 PASS 结论。The contact sheet is diagnostic evidence; open it only on a technical alert, missing upstream binding, or a user-reported defect.

## PASS

Return `PASS` when objective technical QC passes:

- Duration is close to target.
- The full video decodes successfully.
- No freeze or black-frame event exceeds the allowed threshold.
- Video and audio streams are present when the job is sound-enabled.
- The checked video path and hash match the active `output_video` from `subtitle_removal_report.json`.
- The passing subtitle-removal ledger still binds the current report, including its completed full-timeline subtitle and obvious-visual-blocker classification.
- A sound-enabled Seedance 2.5 `source_locked` result has exact normalized ASR equality with the locked target transcript and completes its final line.

## FAIL

Return `FAIL` if:

- The video cannot be read or fully decoded.
- A required video/audio stream is missing.
- Duration is outside tolerance.
- Freeze or black-frame detection fails.
- The final video path/hash no longer matches the passing subtitle-removal result.
- The passing subtitle-removal ledger or its report binding is missing or stale.
- A required Seedance 2.5 dialogue report is missing, stale, changed, duplicated, or truncated.

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
