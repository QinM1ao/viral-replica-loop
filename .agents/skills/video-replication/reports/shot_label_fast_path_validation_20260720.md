# Shot-label Fast-path Validation — 2026-07-20

Job: `job-012`

## Failure reproduced

The old handling treated one wrong Shot number as an image-content failure. Two unnecessary image-model label repairs consumed 58s and 56s, followed by repeated visual checks; the label detour occupied about 31 minutes wall time.

## New contract

1. Normalize every saved Matpool candidate before its first content review.
2. The deterministic tool may change only detected Shot-label bars.
3. Evidence must record zero outside-band pixel changes and equal before/after panel-content fingerprints.
4. A proven label-only change skips Matpool, manual 12-label OCR, and geometry, continuity, skincare, identity, and product revalidation.
5. Any true panel-content change still invalidates prior content QC.

## Actual result

- Part1 and Part2 label normalization ran concurrently in 1 second total.
- Promoted-image hashes remained unchanged:
  - Part1: `ce67a81437d07836d3c60790829d6507cb17b1230604ab61717fbdc21a06d9f4`
  - Part2: `2aa7cbf84ce47a2a0c37849e8fbe081b832b708809eac055ee470f1ef95a3261`
- Part1 panel-content fingerprint matched before/after: `4005aca0f1ff5b4f765e4af0006869dbd16685bdf073dc50ee3f7c701caabcf1`.
- Part2 panel-content fingerprint matched before/after: `795fc400835bb27783746d1bf3f0a613cbaff42dbb440c773b0888b786d3c48f`.
- `visual_asset_manifest_qc.py` returned `PASS` for both fingerprints.
- Hash-gated reuse returned `PASS` and reused GPT Image contract, storyboard geometry, cross-Part continuity, and skincare progression reports.
- Full regression: 193 tests passed, including the real `job-012` from-zero acceptance case.

## Evidence

- `output/job-012/checks/part1_shot_label_restore.json`
- `output/job-012/checks/part2_shot_label_restore.json`
- `output/job-012/checks/image_batch_qc_visual_asset_manifest_qc.json`
- `output/job-012/checks/visual_qc_reuse_state.json`
- `output/job-012/checks/request_qc_visual_qc_reuse_summary.json`
