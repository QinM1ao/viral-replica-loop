# Cost Approval Gate

## Stage

`generation_approval`

## Purpose

Prevent accidental paid or batch Seedance generation.

## Required Inputs

- Prepared Seedance request body or task-create plan.
- Number of parts to generate.
- Whether this is a test run or batch run.
- Current job status and `next_stage`.

## Required Output Artifact

The worker must create or update a cost approval note under the job output folder.

It must include:

- Request files to be submitted.
- Number of Seedance tasks.
- Expected Parts covered by this approval.
- Whether this is paid or batch generation.
- Approval scope: current job, named jobs, or batch.
- User approval status.
- Result: `PASS`, `FAIL`, or `STOP`.

## PASS

Return `PASS` only if:

- User explicitly approved this generation round, including by directly asking to run Seedance or generate the final video for the current explicit job.
- Current-job approval covers every required Part once, and the planned submission count does not exceed that.
- Any failed-Part retry has a new targeted retry approval.
- Batch generation is planned only when the approval explicitly covers the batch, all jobs, or the named job group.
- The runner was invoked with `--allow-paid` when needed.
- Request bodies have already passed request QC.
- The submission count is clear.

## FAIL

Return `FAIL` if:

- Request bodies are missing.
- Request QC has not passed.
- The planned task count is unclear.

Retry variable:

`request_preparation`

Locked variables:

Approved prompts and approved references.

## STOP

Return `STOP` if:

- User has not explicitly approved paid generation, and the current user message is not a direct request to run Seedance or generate the final video for the current explicit job.
- A failed-Part retry is planned without new targeted retry approval.
- Batch generation is planned but the approval does not explicitly cover batch/all/named jobs.
- The next action is a Seedance submit call.
- Cost policy is missing or unclear.

## Next Status

On pass:

```text
generation_approved
```
