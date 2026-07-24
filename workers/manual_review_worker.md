# Manual Review Worker

## Canonical Stage

Manual review or confirmation stop.

## Purpose

Prepare the exact artifact and decision question for the user when a stage must stop.

## Inputs

- Current job row.
- Current `STATE.md`.
- Artifact needing review.
- Gate contract that triggered `STOP`.
- Current `RUNNER_STATE.json`.

## Actions

1. Identify the artifact that needs review.
2. Summarize the decision needed in plain language.
3. Do not hide known failures.
4. Write what will happen if approved.
5. Write what will be retried if rejected.
6. Update `STATE.md` with the review request.

## Outputs

Update:

- `STATE.md`

Optional job artifact:

- `manual_review_request.md`

## Gate

Usually one of:

- `gates/manual_confirmation_gate.md`
- `gates/image_sample_review_gate.md`
- `gates/afterwash_reference_gate.md`
- `gates/final_video_gate.md`

## PASS Next Status

Use the linked stage rule or user-approved next status.

## FAIL Retry Variables

Use the failed gate's retry variable.

## Stop Conditions

- User has not answered yet.
