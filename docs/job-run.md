# Job Run

`Job Run` is the durable coordinator above the existing stage workers and
gates. It does not replace video craft or the sealed stage-execution plans.

New Jobs enter through `tools/job_intake.py`. Both `scripts/new-task.py` and
`scripts/sync-inbox-to-jobs.py` are thin adapters to that same append-only
creation path, so they share duration, person, handoff, ID allocation, intake
evidence, and product-profile rules.

`tools/lifecycle_registry.py` is the single lifecycle interpretation interface.
It reads `rules/STAGE_RULES.json` for ordered status rules and owns terminal
state, canonical-stage resolution, and the five-stage user progress view.

## Normal behavior

- A Stage Run completes maker, deterministic checks, the QC Risk Ledger,
  at most one requested semantic review, writeback, and transition.
- A Job Run immediately starts the next free Stage Run after a PASS.
- A usable artifact moves forward. Semantic defects become delivery warnings.
- Image work is authorized by the formal Job and gets at most one targeted
  retry for the failed image scope.
- Seedance and MediaKit still require explicit paid approval.
- Video generation is never retried automatically.
- Every stage attempt is checkpointed at
  `output/<job-id>/checks/job_run_checkpoint.json`.
- A completed checkpoint is reused. An ambiguous external submission stops for
  reconciliation instead of being submitted again.

The only hard stops are missing required input, unusable media, a stale or
wrong-Job binding, missing paid approval, and conflicting state.

## Coordinator command

The existing entrypoint owns Job Run:

```bash
./run-loop.sh --job-run \
  --root . \
  --job-id "<job-id>" \
  --executor-command "<stage-executor-command>"
```

`--initial-stage` is optional. New work may pass it explicitly. Legacy work
reconstructs it from a valid checkpoint first, then from the single matching
`jobs.csv` row. Ambiguous state stops.

The stage executor is a narrow worker adapter. The coordinator calls it with
one `operation` at a time:

```json
{
  "operation": "maker",
  "root": "/absolute/repo",
  "job_id": "job-001",
  "stage": "image_batch",
  "attempt": 1,
  "scope": "stage",
  "idempotency_key": "job-001:image_batch:1:stage",
  "authorization": "job_image_scope"
}
```

The operations and replies are:

- `maker` → current-Job `artifact`, candidate `next_stage`, and boolean
  `usable`;
- `deterministic_qc` → boolean `passed`, plus optional hard `blocker` and
  `reason`;
- `risk_ledger` → boolean `semantic_review_required`;
- `semantic_qc` (only when requested) → boolean `passed`, optional `reason`,
  and the complete `retry_scopes` list.

The coordinator validates that the artifact exists under the active Job,
performs the shared runner writeback itself, and resolves the next canonical
stage from `jobs.csv` plus `rules/STAGE_RULES.json`. Executor-supplied status or
stage jumps are not trusted.

The injected executor may call local command packets or an agent-backed maker.
Shared state, gates, retry budgets, and final transitions remain coordinator
writes.

Paid generation still uses the existing cost gate. Record the user's current-Job
approval once through the runner, including the exact planned Part count:

```bash
./run-loop.sh \
  --job-id "<job-id>" \
  --allow-paid \
  --approval-recorded \
  --approval-scope current_job \
  --approval-task-count "<part-count>" \
  --planned-task-count "<part-count>" \
  --record-gate-result PASS \
  --apply-transition
```

Then restart Job Run. It reads the passed cost gate from `RUNNER_STATE.json`;
no CLI string can create approval. Approval authorizes the first video
submission only and never authorizes an automatic retry.
