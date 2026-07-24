# Output Quality Scorecard

Skill: `viral-replica-improver`

Evidence mode: `file-backed fixture` plus deterministic proposal smoke test.

## Summary

| Area | Current status | Notes |
|---|---|---|
| Trigger cases | present | Positives, near neighbors, and negatives separate outer-loop improvement from inner-loop execution. |
| Output cases | present | Proposal shape, loop separation, and eval growth are covered. |
| Deterministic scripts | present | `collect-improvement-evidence.py` can write or dry-run a proposal; `record_review_feedback.py` appends review entries. |
| Production readiness | release ready | Ready for local production proposal generation, not public/governed distribution. |

## Current Quality Claims

- The skill improves loop rules through proposals and reviewed patches, not hidden source edits.
- It preserves `$viral-replica` as the inner loop and `$video-replication` as craft.
- It requires evidence paths and verification commands for every durable recommendation.
- It reads review feedback as evidence, not automatic instruction.

## Required Before Governed Promotion

- Add provider-backed model-executed output eval if proposals become fully automated.
- Add blind review decisions for proposal usefulness.
- Add runtime permission probes for any packaged adapter that can write source patches.
