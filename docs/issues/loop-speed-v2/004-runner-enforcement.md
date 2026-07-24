---
title: Runner delivery and stop enforcement
labels:
  - implemented
status: done
parent: docs/prd/2026-06-22-loop-speed-v2.md
---

# Runner delivery and stop enforcement

## Parent

`docs/prd/2026-06-22-loop-speed-v2.md`

## What to build

Make the runner enforce the Loop Speed v2 delivery model end to end.

The loop should have only two user-facing delivery outcomes: Pre-Seedance Handoff and Final Video. Image samples, visual warnings, internal repairs, checker decisions, per-Part Seedance confirmations, and subjective final-video effect review are not user-facing stop points by default.

Self-audit auto-run should keep one pinned job and keep advancing one stage at a time until a hard stop, explicit stop point, Pre-Seedance Handoff, or Final Video.

## Acceptance criteria

- [x] Runner decisions treat Pre-Seedance Handoff and Final Video as the only default user-facing delivery outcomes.
- [x] Image sample review is internal by default in self-audit mode unless the user explicitly asked to preview samples.
- [x] Visual Warning does not set a user-confirmation stop.
- [x] Direct current-job Generation Approval prevents repeated per-Part confirmation.
- [x] Final Technical QC PASS advances to done instead of stopping for subjective review.
- [x] Stop summaries include concrete inspection paths for stop, handoff, blocked, and done outcomes.
- [x] Self-audit auto-run stays on one pinned job and still advances only one stage per iteration.
- [x] Runner does not let job lanes race shared state.
- [x] Tests cover image-sample internal flow, pre-Seedance handoff flow, direct Seedance approval flow, final-video done flow, and explicit stop point behavior.

## User stories covered

1, 2, 19, 20, 24, 26, 27, 34, 35, 36, 38

## Blocked by

- `001-qc-outcome-taxonomy.md`
- `002-cost-policy-enforcement.md`
- `003-hash-gated-reuse.md`

## Implementation

- `tools/run_next_loop_round.py`
- `rules/STAGE_RULES.json`
- runner report output in `output/loop-report.md`
- `tests/test_runner_enforcement.py`

## Verification

```bash
python3 -m unittest tests/test_runner_enforcement.py
```
