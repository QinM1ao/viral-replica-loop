# Loop Speed v2 Handoff

Date: 2026-06-22

## Current State

Loop Speed v2 is implemented and verified.

The loop should now feel simpler from the user side:

- Default delivery outcomes are only `Pre-Seedance Handoff` and `Final Video`.
- Image samples, visual warnings, checker notes, per-Part Seedance confirmations, and subjective final-video effect review are internal by default.
- Final video delivery is blocked only by objective technical failures, not taste judgment.
- Seedance cost approval is scoped: a direct "run Seedance" request approves the current job only.
- Failed Seedance retries are targeted and limited; final objective failures allow at most one paid retry.
- Heavy visual QC can be reused when active image hashes and role mappings have not changed.
- After image batch PASS, the default route now uses one compact Pre-Seedance pack instead of serial voiceover, seam, Seedance prompt, audio boundary, and request QC rounds.

## Implemented Issue Slices

| Slice | Status | Main evidence |
|---|---|---|
| QC outcome taxonomy | Done | `tools/qc_outcomes.py`, `tools/checker_review_qc.py`, `tests/test_qc_outcomes.py` |
| Cost-policy enforcement | Done | `COST_POLICY.md`, runner summaries, `tests/test_cost_policy_enforcement.py` |
| Hash-gated reuse | Done | `tools/hash_gated_visual_qc.py`, `tests/test_hash_gated_visual_qc.py` |
| Runner enforcement | Done | `tools/run_next_loop_round.py`, `tests/test_runner_enforcement.py` |
| Final-video objective QC | Done | `tools/final_video_qc.py`, `tests/test_final_video_qc.py` |
| Timing report | Done | `tools/timing_report.py`, `tests/test_timing_report.py`, `output/timing-report.md` |

## Commands To Trust

```bash
python3 -m unittest discover -s tests
./scripts/verify.sh
python3 tools/timing_report.py --root . --out output/timing-report.md --job job-003 --job job-005 --job job-006
```

## Operating Notes

When continuing the loop, start from `AGENTS.md`, `LOOP.md`, `docs/loop-runbook.md`, and this file. Do not restore old behavior that asks for user confirmation at image sample, visual warning, per-Part Seedance submission, or final subjective effect review.

If image hashes, approved visual manifest mapping, material-role mapping, prompt reference roles, or a user-reported visual defect change, rerun the relevant heavy visual QC. Otherwise cite the existing PASS reports and run only the lightweight downstream sync checks.

The old five-stage post-image route remains available for legacy statuses and focused repair, but new `image_qc_passed` jobs should default to `pre_seedance_pack`.

The 2026-07-10 fast path further combines new-job story analysis and storyboard work into `source_blueprint`, and uses `director_plan.json` plus `tools/pre_seedance_pack.py` to render repeated downstream artifacts. Stop-before-generation jobs build the web handoff only; API requests are deferred until generation is actually requested. The measured non-image target is 20 minutes; see `docs/fast-path-20min.md` and `rules/PERFORMANCE_BUDGET.json`.

On 2026-07-17, source understanding gained a required semantic-video lane: `tools/video_understanding.py` calls Wujie Higress `doubao-seed-2-0-mini-260215`, saves auditable structured evidence, and blocks source-blueprint PASS when provider/model/hash/request evidence is missing or invalid. See `docs/video-understanding.md`.

Use `output/loop-report.md` and `output/timing-report.md` when explaining progress or why a run was slow.
