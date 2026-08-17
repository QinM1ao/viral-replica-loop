# Final QC Worker

## Canonical Stage

`final_qc`

## Purpose

Run objective technical checks on generated part videos or final stitched video, then deliver when technical QC passes.

## Inputs

- Passing `output/<job-id>/subtitle_removal/subtitle_removal_report.json`.
- Its passing `output/<job-id>/checks/subtitle_removal_qc_risk_ledger.json`.
- The target duration recorded for the current job.
- Reference audio and ASR artifacts only when debugging a reported audio problem.
- `gates/final_video_gate.md`.

## Actions

1. Read the passing subtitle-removal report and use its `output_video` as the only final-QC input. This is the original finished video on a clean branch and the distinct repaired video on a MediaKit branch.
2. Run one objective technical scan covering readability, required streams, duration, full decode, freeze, black frames, and the exact video hash.
3. Read `final_qc.json`. Do not run an independent checker and do not write another gate-review summary.
4. If the report is `PASS`, record `PASS` and apply the `done` transition immediately.
5. Open the contact sheet only when the technical report is not `PASS`, an upstream hash is missing, or the user reports a visible defect.
6. If technical QC fails, allow at most one targeted Seedance retry; a repeated failure or second paid retry stops.

Run final ASR for every sound-enabled Seedance 2.5 `source_locked` job, then compare it with the request-bound transcript using `tools/seedance25_output_dialogue_qc.py`. Other jobs run final ASR only when the user asks to verify audio/script, when the generated video has a reported audio defect, or when a specific retry is about missing/duplicated speech.

## Scripted Part

Use this script for technical final QC:

```bash
python3 viral-replica-loop/tools/final_video_qc.py \
  --videos "<active-output-video-path>" \
  --target-duration <job-target-duration-seconds> \
  --duration-tolerance 3 \
  --out-dir viral-replica-loop/output/<job-id>/final

python3 -c 'import json,sys; report=json.load(open(sys.argv[1])); raise SystemExit(0 if report.get("overall") == "PASS" else 1)' \
  viral-replica-loop/output/<job-id>/final/final_qc.json \
&& viral-replica-loop/run-loop.sh \
  --job-id <job-id> \
  --record-gate-result PASS \
  --apply-transition \
  --artifact output/<job-id>/final/final_qc.md \
  --note "objective final QC passed"
```

The script checks video/audio streams, duration, full decode, freeze detection, black-screen detection, and creates a diagnostic contact sheet in one FFmpeg pass. A passing report goes directly to delivery; the contact sheet does not create another routine review step.

Required for sound-enabled Seedance 2.5 `source_locked`; optional audio/script debugging for other jobs:

```bash
python3 viral-replica-loop/tools/asr_transcribe.py \
  "<final-or-part-video-path>" \
  --out-dir viral-replica-loop/output/<job-id>/final/asr_debug

python3 viral-replica-loop/tools/final_video_qc.py \
  --videos "<active-output-video-path>" \
  --target-duration <job-target-duration-seconds> \
  --duration-tolerance 3 \
  --brand-term "<product-name>" \
  --asr-md viral-replica-loop/output/<job-id>/final/asr_debug/原口播ASR_elevenlabs.md \
  --out-dir viral-replica-loop/output/<job-id>/final

python3 viral-replica-loop/tools/seedance25_output_dialogue_qc.py \
  --source-fidelity-qc viral-replica-loop/output/<job-id>/seedance25_upload/<unit>/source_fidelity_qc.json \
  --video "<active-output-video-path>" \
  --asr-request-manifest viral-replica-loop/output/<job-id>/final/asr_debug/request_manifest.json \
  --asr-timeline viral-replica-loop/output/<job-id>/final/asr_debug/asr_timeline.json \
  --output viral-replica-loop/output/<job-id>/final/output_dialogue_qc.json
```

## Outputs

Write under `output/<job-id>/final/`:

- `ffprobe.txt`
- `freezedetect.txt`
- frame contact sheet
- `final_qc.md`
- `asr_debug/` and `output_dialogue_qc.json` for sound-enabled Seedance 2.5 `source_locked`; optional for other jobs

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
