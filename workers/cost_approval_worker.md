# Cost Approval Worker

## Canonical Stage

`generation_approval`

## Purpose

Prepare a clear generation approval summary before paid or batch Seedance generation.

## Inputs

- Passed request QC artifact.
- Prepared request JSON files.
- Number of Seedance tasks to submit.
- Expected part count.
- `gates/cost_approval_gate.md`.

## Actions

1. List every request file that would be submitted.
2. Count the Seedance tasks.
3. State whether it is a test, retry, or batch generation.
4. Confirm request QC has passed.
5. If the current user message directly asks to run Seedance, generate the final video, or directly produce the video, record that message as explicit approval for the current explicit job/generation round.
6. Treat current-job approval as covering each required Part once. Do not ask again just because the job has Part1 and Part2.
7. Treat a failed-Part retry as a new approval boundary.
8. Treat approval as batch approval only when the user explicitly says to run a batch, all jobs, or a named group.
9. Ask for explicit user approval only when no current or recorded approval exists.
10. Do not submit generation unless approval exists and runner is invoked with `--allow-paid`.

## Outputs

Write under `output/<job-id>/seedance/`:

- `generation_approval.md`

## Gate

Run:

`gates/cost_approval_gate.md`

## PASS Next Status

`generation_approved`

## FAIL Retry Variables

`request_preparation`

## Stop Conditions

- User has not explicitly approved generation.
- A failed-Part retry is planned without new retry approval.
- Batch generation is planned but approval covers only the current job.
- Task count or request files are unclear.
- Request QC has not passed.
