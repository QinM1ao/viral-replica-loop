---
title: Cost-policy enforcement
labels:
  - implemented
status: done
parent: docs/prd/2026-06-22-loop-speed-v2.md
---

# Cost-policy enforcement

## Parent

`docs/prd/2026-06-22-loop-speed-v2.md`

## What to build

Make the written Seedance cost policy enforceable in runner behavior and gate recording.

Direct user requests to run Seedance, directly generate the final video, or directly produce the video should count as Generation Approval for the current explicit job. That approval covers every required Part for that job once. It must not become batch approval unless the user explicitly names batch, all jobs, or a concrete job group. Failed-Part retries and final-video regeneration retries require new targeted approval. Final objective failures can trigger at most one targeted Seedance retry.

## Acceptance criteria

- [x] The machine-readable cost policy is parsed and exposed to runner decisions.
- [x] Current-job Generation Approval covers every required Part once.
- [x] Current-job Generation Approval does not approve batch jobs, all jobs, or unnamed variants.
- [x] Batch generation is blocked unless approval explicitly covers batch/all/named jobs.
- [x] Failed-Part retry requires new targeted approval.
- [x] Final-video objective failure allows at most one targeted Seedance retry.
- [x] A second paid retry is blocked or stopped with clear evidence.
- [x] Runner summaries show approval scope, approved task count, submitted task count, and Seedance run count.
- [x] Tests cover direct current-job approval, batch non-approval, explicit batch approval, failed-Part retry approval, and second-retry blocking.

## Implementation

- `COST_POLICY.md`
- runner cost gate summaries and generation approval scope handling
- `tests/test_cost_policy_enforcement.py`

## Verification

```bash
python3 -m unittest tests/test_cost_policy_enforcement.py
```

## User stories covered

19, 20, 21, 22, 23, 33, 36, 38

## Blocked by

None - can start immediately.
