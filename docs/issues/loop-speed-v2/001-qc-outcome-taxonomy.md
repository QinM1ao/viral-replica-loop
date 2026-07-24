---
title: QC outcome taxonomy
labels:
  - implemented
status: done
parent: docs/prd/2026-06-22-loop-speed-v2.md
---

# QC outcome taxonomy

## Parent

`docs/prd/2026-06-22-loop-speed-v2.md`

## What to build

Build an end-to-end QC outcome taxonomy that lets the loop distinguish Hard Failure, Visual Warning, and Evidence STOP in stage artifacts, checker reviews, gate records, and runner decisions.

The goal is not to relax true quality gates. The goal is to prevent three different situations from being treated as the same thing:

- Hard Failure: the artifact is actually unusable or violates a core rule.
- Visual Warning: the artifact is usable, but has a tiny non-material metric or local concern.
- Evidence STOP: the artifact may be visually usable, but the required proof is missing or inconsistent.

Visual Warning must require `why_not_fail`. It must never cover wrong person, wrong product, wrong wardrobe, source contamination, changed shot order, visible squeeze, missing or unsaved outputs, or thin/watery/gray/yellow mud.

## Acceptance criteria

- [x] Stage review artifacts can record Hard Failure, Visual Warning, and Evidence STOP as distinct outcomes.
- [x] Gate recording preserves the distinction instead of flattening all non-PASS outcomes into generic failure.
- [x] Visual Warning requires a recorded `why_not_fail` explanation.
- [x] Visual Warning cannot pass hard failures such as wrong person, wrong product, wrong wardrobe, source contamination, changed shot order, visible squeeze, missing output, unsaved output, or thin/watery/gray/yellow mud.
- [x] Evidence STOP is available for missing ImageGen input proof, missing manifest binding, active hash mismatch, missing saved candidate, or missing QC artifact.
- [x] Runner output and stop summaries explain whether the current blocker is visual failure, evidence failure, provider failure, or cost gate.
- [x] Tests cover at least one Hard Failure, one Visual Warning with `why_not_fail`, one rejected Visual Warning without `why_not_fail`, and one Evidence STOP.

## Implementation

- `tools/qc_outcomes.py`
- `tools/checker_review_qc.py`
- gate recording and runner summaries
- `tests/test_qc_outcomes.py`

## Verification

```bash
python3 -m unittest tests/test_qc_outcomes.py
```

## User stories covered

3, 4, 5, 6, 14, 15, 16, 17, 18, 30, 36, 38, 39

## Blocked by

None - can start immediately.
