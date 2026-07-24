# Skill Improvement Proposal

Generated: 2026-06-25T08:10:19

## Observed Signals

- `cross_part_continuity` as `gate_gap` from `STATE.md`; matched: cross-Part, cross_part, continuity
- `skincare_progression` as `gate_gap` from `STATE.md`; matched: skincare, progression, after-wash, too white
- `storyboard_geometry` as `gate_gap` from `STATE.md`; matched: storyboard geometry, geometry, squeez
- `codex_imagegen_contract` as `checker_contract` from `STATE.md`; matched: codex_imagegen_contract, API-equivalence, reference order
- `prompt_pollution` as `prompt_quality` from `STATE.md`; matched: workflow context, AI改好分镜图, current-job
- `handoff_clutter` as `handoff_governance` from `STATE.md`; matched: deprecated, 废稿, final upload
- `approval_scope` as `approval_safety` from `STATE.md`; matched: approval, paid, generation_approved, batch
- `automation_drift` as `automation_drift` from `STATE.md`; matched: parallel, lane, heartbeat, no runnable
- `cross_part_continuity` as `gate_gap` from `RUNNER_STATE.json`; matched: cross-Part, cross_part, continuity
- `skincare_progression` as `gate_gap` from `RUNNER_STATE.json`; matched: skincare, progression, after-wash, too white
- `storyboard_geometry` as `gate_gap` from `RUNNER_STATE.json`; matched: storyboard geometry, geometry, squeez
- `codex_imagegen_contract` as `checker_contract` from `RUNNER_STATE.json`; matched: codex_imagegen_contract, API-equivalence

## Evidence Paths

- `RUNNER_STATE.json`
- `STATE.md`
- `client-profiles/kongfengchun/lesson-registry.jsonl`
- `logs/loop_events.jsonl`
- `logs/review_feedback.jsonl`

## Job Snapshot

Status counts: seedance_inputs_prepared: 6

- job-001: seedance_inputs_prepared -> generation_approved; confirmation=true
- job-002: seedance_inputs_prepared -> generation_approved; confirmation=true
- job-003: seedance_inputs_prepared -> generation_approved; confirmation=true
- job-004: seedance_inputs_prepared -> generation_approved; confirmation=true
- job-005: seedance_inputs_prepared -> generation_approved; confirmation=true
- job-006: seedance_inputs_prepared -> generation_approved; confirmation=true

## Review Feedback

Outcome counts: visual_warning_accepted: 1

Suggested surfaces: eval: 1

- review-20260622-234326-33c5a2e5: job-003/request_qc `visual_warning_accepted` -> Tiny metric drift is not a blocker when complete person/wardrobe replacement, product replacement, thick white mud, source-like structure, and no visible subject squeeze all hold. (surface: `eval`; evidence: output/job-003/checks/request_qc_storyboard_geometry_qc.md, output/job-003/checks/request_qc_gate_review.md, output/job-003/seedance_web_final/)

## Classification

- `gate_gap`: 13
- `checker_contract`: 3
- `prompt_quality`: 2
- `handoff_governance`: 3
- `approval_safety`: 4
- `automation_drift`: 2
- `human_judgment`: 1

## Recommended Action

`gate_or_eval_patch`: Add an eval case first; patch the gate only if current gate text cannot catch the evidence.

## Proposed Durable Surface

- Start with `evals/output_cases.json` or the relevant skill `references/*.md`.
- Patch `workers/*.md`, `gates/*.md`, or `tools/*.py` only when the proposal names concrete evidence that the current runtime contract is insufficient.
- Do not patch source files from an unattended scheduled run.

## Suggested Eval Case

Add a case that reproduces the missed QC pattern and names the expected blocker.

## Verification Command

```bash
python3 scripts/skill-release-check.py --root . --skill viral-replica-improver --strict
python3 scripts/skill-release-check.py --root . --skill viral-replica --strict
bash scripts/release-check.sh
```

## Approval Boundary

This proposal is safe to generate automatically. Applying patches to skill, worker, gate, eval, or script files requires explicit approval or an explicit implementation request.
