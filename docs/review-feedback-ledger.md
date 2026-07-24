# Review Feedback Ledger

`logs/review_feedback.jsonl` records what the user accepted, edited, rejected, or left pending after an inner-loop run.

The ledger is input to `$viral-replica-improver`. It helps the outer loop distinguish:

- a one-off human preference
- missing context
- a weak gate
- a checker miss
- a prompt-quality issue
- an approval or handoff governance issue

## Record Feedback

```bash
python3 tools/record_review_feedback.py \
  --root . \
  --job-id job-003 \
  --stage request_qc \
  --outcome visual_warning_accepted \
  --feedback "User accepted tiny non-material geometry drift after checking the active handoff." \
  --meaning "Tiny metric drift is not a blocker when identity, wardrobe, product, white mud, source-like structure, and no visible squeeze all hold." \
  --classification human_judgment \
  --suggested-surface eval \
  --evidence-path output/job-003/checks/request_qc_storyboard_geometry_qc.md \
  --evidence-path output/job-003/seedance_web_final/
```

## Ledger Fields

- `job_id`: job id or broader scope.
- `stage`: stage or review point.
- `review_outcome`: `accepted_unchanged`, `edited_accepted`, `rejected`, `pending`, `manual_override`, `visual_warning_accepted`, or `web_validated`.
- `user_feedback`: what the user changed, accepted, rejected, or noticed.
- `meaning`: what the feedback means for future runs.
- `context_to_preserve`: reusable context that should be available to future inner-loop runs.
- `classification`: outer-loop category such as `gate_gap`, `prompt_quality`, `context_gap`, or `human_judgment`.
- `suggested_surface`: likely durable surface such as `eval`, `reference`, `worker`, `gate`, `script`, or `report_only`.
- `apply_status`: whether this is still `proposal_only`, accepted, applied, rejected, or superseded.
- `evidence_paths`: local paths supporting the record.

## Safety

Do not store raw private conversation logs, secrets, browser state, provider keys, or unrelated personal data in this ledger. Record concise summaries and local artifact paths.
