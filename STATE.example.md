# Loop State

## Goal

Batch replicate source videos into target-product videos while preserving source story rhythm, shot order, and sales function.

## Acceptance

- One row exists in `jobs.csv` for each source video.
- Each round selects one non-terminal job.
- Each round advances only one stage.
- Each stage writes an artifact and runs the linked gate.
- Paid generation and subjective review stop for approval.

## Current Round

- Date:
- Current task:
- Current stage:
- This round did:
- Artifacts:
- Verification:
- Next:
- Needs user confirmation:

## Attempts

- No attempts yet.

## Stop Rules

- Stop when there are no runnable jobs.
- Stop when a sample or final video needs human review.
- Stop before paid or batch generation.
- Stop after repeated failure or no effective progress.
