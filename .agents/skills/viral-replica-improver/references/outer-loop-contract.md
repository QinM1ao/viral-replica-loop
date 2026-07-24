# Viral Replica Outer Loop Contract

This contract turns the Zach Lloyd inner/outer loop pattern into a local SkillOps loop for `viral-replica-loop`.

## Goal

Make the loop easier to run over time by converting repeated failures, user corrections, checker findings, and QC evidence into reviewed improvements to skills, workers, gates, evals, or scripts.

## Inner Loop Versus Outer Loop

Inner loop:

```text
jobs.csv -> runner -> worker -> gate -> checker/QC -> STATE/logs/handoff
```

Outer loop:

```text
STATE/logs/QC/review feedback ledger -> classify -> proposal -> reviewed patch -> release-check -> next inner loop
```

## Evidence Sources

Use explicit local evidence only:

- `STATE.md`
- `RUNNER_STATE.json`
- `jobs.csv`
- `logs/loop_events.jsonl`
- `logs/review_feedback.jsonl`
- `output/<job-id>/checks/*`
- `client-profiles/kongfengchun/lesson-registry.jsonl`
- `evals/*.json`
- user-provided feedback in the active conversation

Do not implicitly scan private browser history, unrelated logs, or raw conversation archives.

## Classification

Classify each signal into the smallest useful category:

- `skill_boundary`: wrong skill routed or responsibilities blurred
- `gate_gap`: missing or weak gate evidence
- `eval_gap`: repeated failure is not yet an eval case
- `worker_contract`: worker output shape or required inputs are unclear
- `checker_contract`: checker missed a visible or objective problem
- `prompt_quality`: model-facing prompt leaked internal workflow or became unreadable
- `handoff_governance`: final handoff contains deprecated/internal clutter
- `approval_safety`: cost, batch, retry, or manual web validation boundary is unclear
- `automation_drift`: scheduled/lane behavior no longer matches current queue state
- `report_only`: useful observation with insufficient evidence for a durable change
- `context_gap`: review revealed missing history, source, preference, or constraint needed before future work
- `human_judgment`: review reflects subjective judgment that should be preserved as context but not automatically converted into a blocking rule

## Review Feedback Ledger

Use `logs/review_feedback.jsonl` to record what the user accepted, edited, rejected, left pending, or validated manually.

Each record should capture:

- job and stage
- artifact before and after review, when available
- review outcome
- concise user feedback
- meaning for future runs
- context to preserve
- classification
- suggested durable surface
- evidence paths

The ledger turns review into evidence without pretending every edit is a rule. A review entry can mean:

- add missing context to future runs
- add an eval case
- patch a worker or gate
- preserve a human judgment as non-blocking context
- do nothing yet

## Decision Policy

1. Prefer the smallest durable surface.
2. Add or update evals when a failure can recur.
3. Patch `SKILL.md` only when routing or core skeleton changes.
4. Patch `references/` when the rule is detailed policy.
5. Patch `workers/` or `gates/` only when runtime contracts need to change.
6. Patch scripts only when deterministic evidence is more reliable than prose.
7. Keep scheduled runs proposal-only.

## Proposal Template

Every proposal must include:

- `Observed signals`
- `Evidence paths`
- `Review Feedback`
- `Classification`
- `Recommended action`
- `Proposed durable surface`
- `Suggested eval case`
- `Verification command`
- `Approval boundary`

## Apply Boundary

The outer loop may automatically write proposal reports. It may not automatically write source patches unless the user explicitly asks to apply or implement the proposal.

After a patch is applied, run:

```bash
python3 scripts/skill-release-check.py --root . --skill viral-replica-improver --strict
python3 scripts/skill-release-check.py --root . --skill viral-replica --strict
bash scripts/release-check.sh
```

If the proposal touches `$video-replication`, also run:

```bash
python3 scripts/skill-release-check.py --root . --skill video-replication
```
