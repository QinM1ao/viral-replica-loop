# Actual Validation: Kongfengchun Part2

Date: 2026-07-16

Status: provider-backed PASS for the current preferred Seedance prompt case.

## Scope

- Job: `job-011`
- Part: Part2 only; Part1 stayed locked
- Model: ordinary Seedance 2.0, `ep-20260521101914-nwv8j`
- Task code: `2509`
- Duration: 13 seconds, 9:16, 720p, audio enabled
- Submitted tasks: 1
- Paid retries after creation: 0

## Canonical Prompt

```text
.agents/skills/video-replication/references/examples/seedance-20-kongfengchun-part2-validated.txt
```

The provider submission used the same four active image references, including the approved male identity image, plus the same Part2 reference audio.

## Variables Changed

1. The identity image continued to lock the same male presenter and clothing but explicitly stopped controlling background and post-wash skin state.
2. The post-wash Shot requested a clearly flawless commercial result instead of `保留真实毛孔和皮肤纹理`.
3. Shot 09–10, Shot 11 B-roll, and Shot 12 became separate execution blocks because scene, visual function, and speaker mode change.
4. Shot 10 ended with the jar already close to camera. Shot 12 started in the same warm room at matched product-close framing instead of restarting the push.

## Result

- User accepted the new Part2 as correct and requested that it become the workflow standard.
- Same male presenter remained stable.
- The identity-reference bathroom did not replace the source scene in the tail.
- Post-wash skin read visibly brighter, cleaner, smoother, and more even.
- Shot 11 remained a brief blurred still-life B-roll beat.
- The B-roll-to-final-product hard cut read more naturally without adding a dissolve.
- Part2 duration: `13.096009s`
- Part2 video/audio: H.264 720x1280 + AAC
- Exact freeze events: `0`
- Black-frame events: `0`
- Low-motion holds versus source: `0`
- Stitched duration: `26.215283s`
- Part2 and stitched technical QC: PASS

## Evidence

```text
output/job-011/experiments/part2_flawless_matchcut_retry_20260716/part2/video.mp4
output/job-011/experiments/part2_flawless_matchcut_retry_20260716/job-011_新版Part2_26s.mp4
output/job-011/experiments/part2_flawless_matchcut_retry_20260716/validation_report.md
output/job-011/experiments/part2_flawless_matchcut_retry_20260716/generation_log.md
output/job-011/experiments/part2_flawless_matchcut_retry_20260716/qc/final_qc.md
output/job-011/experiments/part2_flawless_matchcut_retry_20260716/qc_full/final_qc.md
```

## Remaining Evidence Gap

This validates one provider-backed prompt revision and its stitched result. It is not a blind A/B review and does not by itself prove every category or source video will benefit from the same profile-specific skin wording.
