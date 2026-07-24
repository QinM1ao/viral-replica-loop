# Manual Confirmation Gate

## Stage

`confirmation_gate`

## Purpose

Stop the loop when `needs_user_confirmation=true`.

## Required Inputs

- Current job row from `jobs.csv`.
- Current `STATE.md`.
- The artifact that needs review.
- The reason confirmation was requested.

## Required Output Artifact

The worker must update `STATE.md` with:

- What needs review.
- Artifact path.
- Exact decision requested from the user.
- Current status.
- Next status if approved.

## PASS

Return `PASS` only if the user explicitly approves the artifact or action.

## FAIL

Return `FAIL` if the user rejects the artifact and gives a concrete failure reason.

Retry variable:

The single failed item named by the user.

Locked variables:

All previously approved artifacts.

## STOP

Return `STOP` if the user has not answered yet.

## Next Status

Keep the current status until the user responds.
