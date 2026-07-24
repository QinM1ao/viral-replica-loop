# Generation Gate

## Stage

`generation`

## Purpose

Confirm approved paid generation produced downloadable part videos and generation logs.

## Required Inputs

- Explicit approval record.
- Passed request QC artifact.
- Submitted request bodies.
- Task keys or provider job IDs.
- Downloaded videos.

## PASS

Return `PASS` only if:

- Submitted task count matches approval.
- Every generated part is downloaded.
- Task keys and request bodies are saved.
- No unapproved batch or extra paid task was submitted.
- Every submitted Part has `request_contract.json` with `overall=PASS`, bound to the exact saved request hash.
- Every Part with reference audio has `reference_audio_preflight.json` with `overall=PASS`, the same request hash, a non-zero byte count, and a decodable audio stream.
- `generation/selected_outputs.json` binds every selected Part ID, current video hash, and measured duration.
- A `quality_retake` replaces exactly one Part only after a new targeted approval, hash-bound baseline `selected_outputs.json` and `final/final_video.mp4`, and a PASS Attempt 2 completion; a failed retake leaves both prior artifacts unchanged, and terminal-job repair state remains job-local.

## FAIL

Return `FAIL` if:

- Provider task failed.
- Output is missing or cannot be downloaded.
- Submitted request differs from the approved request.
- A request contract or reference-audio preflight fails before submission. This is a free local failure and does not spend the approved provider attempt.

Retry variable:

Choose exactly one:

- `provider_retry`
- `request_body`
- `reference_url`
- `audio_input`

Locked variables:

Approval scope, passed request QC, and task count.

## STOP

Return `STOP` if:

- Another paid retry would be required.
- Provider failure reason is unclear after one exact retry.
- A second targeted Seedance retry would be needed for the same final output.
- A quality retake lacks a new one-Part targeted approval or its selected-output baseline changed.

## Next Status

On pass:

```text
finishing
```
