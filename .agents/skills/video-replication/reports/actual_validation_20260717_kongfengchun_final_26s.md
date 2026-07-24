# Actual Validation: Kongfengchun Final 26s Pair

Date: 2026-07-17

Status: provider-backed PASS for the current complete Seedance workflow standard.

## Scope

- Job: `job-011`
- Model: ordinary Seedance 2.0, `ep-20260521101914-nwv8j`
- Task code: `2509`
- Part1: latest accepted opening-only repair; all later prompt blocks stayed in the previously accepted explicit-Shot format
- Part2: accepted flawless after-wash and matched B-roll hard-cut repair
- Submitted tasks for the two accepted outputs: one Part1 task and one Part2 task; no paid retry after either accepted task was created

## Variables Changed

Part1 changed only `0.0–2.2秒｜Shot 01–02`: the hook now specifies two real fingertip applications with contact, movement, and visible white-mud residue. The accepted `2.2–13.0秒` blocks were not simplified or rewritten.

Part2 changed the after-wash result to the profile-defined flawless commercial state and split `Shot 09–10`, `Shot 11` B-roll, and `Shot 12` into separate execution blocks with matched product-close framing around the hard cut.

## Result

- The user accepted the latest Part1 and the previously accepted Part2 and requested that they be combined and made the workflow standard.
- Final duration: `26.192109s`
- Video/audio: H.264 `720x1280` at `24fps` + AAC stereo
- Freeze events: `0`
- Black-frame events: `0`
- The Part1-to-Part2 seam is an intentional action hard cut.
- Final technical QC: PASS

## Evidence

```text
output/job-011/final-delivery/孔凤春清洁泥膜_最终版_26s.mp4
output/job-011/final-delivery/prompts/Part1_实际提交提示词.txt
output/job-011/final-delivery/prompts/Part2_实际提交提示词.txt
output/job-011/final-delivery/requests/
output/job-011/final-delivery/parts/
output/job-011/final-delivery/qc/final_qc.md
output/job-011/final-delivery/最终版制作流程.md
```

## Reusable Claim Boundary

This validates the complete two-Part control pattern, locked-block prompt repair, independent Part generation, accepted-Part concatenation, and fast technical QC for this case. Product-specific skin and mud wording remains profile-scoped and must not be copied into unrelated categories.
