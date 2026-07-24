---
title: Final-video objective QC
labels:
  - implemented
status: done
parent: docs/prd/2026-06-22-loop-speed-v2.md
---

# Final-video objective QC

## Parent

`docs/prd/2026-06-22-loop-speed-v2.md`

## What to build

Make final-video QC objectively verifiable and non-subjective.

Final Technical QC should block missing or unreadable videos, missing video/audio streams, wrong duration, freeze frames, black/blank frames, duplicated or missing speech, broken seams, and obvious wrong person/product/wardrobe/mud/scene. It should not block on subjective effect quality. If objective technical QC passes, the job should be deliverable as Final Video.

## Acceptance criteria

- [x] Final-video QC script reports video existence and readability.
- [x] Final-video QC script reports video and audio stream presence.
- [x] Final-video QC script reports duration against configured target and tolerance.
- [x] Final-video QC script runs freeze detection.
- [x] Final-video QC script runs black-screen detection.
- [x] Final-video QC script can check required brand terms in ASR text.
- [x] Final-video QC script creates a contact sheet for objective spot checks.
- [x] Final-video gate treats subjective effect review as post-delivery user judgment, not a loop stop.
- [x] Final-video gate stops after one targeted retry if objective failure repeats or another paid retry would be required.
- [x] Tests cover missing file, missing stream, duration failure, freeze event, black event, missing ASR term, and contact sheet generation.

## Implementation

- `tools/final_video_qc.py`
- `gates/final_video_gate.md`
- runner final-video delivery behavior
- `tests/test_final_video_qc.py`

## Verification

```bash
python3 -m unittest tests/test_final_video_qc.py
```

## User stories covered

23, 24, 25, 26, 27, 36, 38, 39

## Blocked by

- `002-cost-policy-enforcement.md`
