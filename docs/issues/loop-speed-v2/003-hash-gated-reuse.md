---
title: Hash-gated visual QC reuse
labels:
  - implemented
status: done
parent: docs/prd/2026-06-22-loop-speed-v2.md
---

# Hash-gated visual QC reuse

## Parent

`docs/prd/2026-06-22-loop-speed-v2.md`

## What to build

Build hash-gated reuse for heavy visual QC after image batch PASS.

When active final image hashes, approved visual manifest mapping, material-role mapping, and prompt reference roles have not changed, downstream stages should reuse existing heavy visual QC evidence. Prompt and request stages should still run lightweight sync checks every time.

Heavy visual QC must rerun when an active image hash changes, manifest mapping changes, material-role mapping changes, prompt reference role changes, or the user reports a visible defect.

## Acceptance criteria

- [x] The loop records active final image hashes and the mappings that make a heavy visual QC PASS valid.
- [x] Downstream stages can cite a previous heavy visual QC PASS when active hashes and mappings are unchanged.
- [x] Prompt/request stages still run lightweight sync checks even when heavy visual QC is reused.
- [x] Heavy visual QC reruns when active image hashes change.
- [x] Heavy visual QC reruns when manifest mapping changes.
- [x] Heavy visual QC reruns when material-role or prompt reference roles change.
- [x] Heavy visual QC reruns when a user-reported visible defect is recorded.
- [x] Reuse summaries say which QC reports were reused and which lightweight checks ran.
- [x] Tests cover unchanged-hash reuse, changed-hash invalidation, mapping invalidation, and user-visible-defect invalidation.

## Implementation

- `tools/hash_gated_visual_qc.py`
- runner downstream reuse summaries
- `tests/test_hash_gated_visual_qc.py`

## Verification

```bash
python3 -m unittest tests/test_hash_gated_visual_qc.py
```

## User stories covered

7, 8, 9, 10, 11, 31, 32, 36, 37, 38, 39

## Blocked by

- `001-qc-outcome-taxonomy.md`
