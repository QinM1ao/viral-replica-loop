# Skill IR: viral-replica

## Recurring Job

Run or audit a file-backed viral video replication loop without losing worker/gate/state/cost boundaries.

## Trigger Description

Use `$viral-replica` when a user wants to run or audit `viral-replica-loop`, turn simple intake into jobs, advance one queued job through workers/gates, self-audit until a stop point, prepare Seedance web handoff before paid generation, enforce cost approval, or inspect loop state.

Do not use it for craft-only one-shot video replication, standalone Seedance prompt polishing, or general video critique without loop state.

## Inputs

- `BRIEF.md`
- `STATE.md`
- `jobs.csv`
- `LOOP.md`
- `rules/STAGE_RULES.json`
- selected `workers/*.md`
- linked `gates/*.md`
- `.agents/skills/video-replication/SKILL.md`
- optional client profile such as `client-profiles/kongfengchun/README.md`

## Outputs

- runner decision
- stage artifact
- checker review
- gate result
- state writeback
- handoff or blocked inspection paths

## Workflow

1. Read loop state and stage rules.
2. Select or create one active job.
3. Read the selected worker, linked gate, and `$video-replication` craft instructions.
4. Execute one stage.
5. Run checker and required QC evidence.
6. Record the gate result through the runner.
7. Stop at explicit stop points, cost boundaries, hard failures, or completion.

## Near Neighbors

- `$video-replication`: owns craft-only replication work.
- Seedance prompt skills: own standalone prompt polishing or route-specific prompt work.
- General video critique: should not activate loop state.

## Resources

- `references/loop-operating-contract.md`
- `evals/trigger_cases.json`
- `evals/output_cases.json`
- `reports/output_quality_scorecard.md`
- `reports/trust_report.md`
- `scripts/extract-reference.py`

## Risk Profile

- Wrong activation can bypass gates or cost approval.
- Wrong deactivation can leave daily loop work manual and inconsistent.
- Handoff packaging can accidentally include deprecated or internal assets.
- Parallel lanes can corrupt shared state if they write directly.

## Production Evidence

- Trigger fixture includes positive, negative, and near-neighbor cases.
- Output fixture records assertions for stop boundaries, hard gate evidence, and scope separation.
- `scripts/skill-release-check.py --skill viral-replica` checks package structure.
- `scripts/release-check.sh` runs install validation, tests, and runner dry-run.
