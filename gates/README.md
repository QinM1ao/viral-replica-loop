# Gate Contracts

This folder defines the loop's stage gates.

A gate is a decision contract. It does not do the worker's job. It decides whether the worker output can advance.

Every gate must return exactly one result:

```text
PASS
FAIL
STOP
```

Each review may also record the QC outcome taxonomy:

```text
Outcome type: PASS / HARD_FAILURE / VISUAL_WARNING / EVIDENCE_STOP / PROVIDER_FAILURE / COST_GATE / HUMAN_REVIEW
Why not fail:
```

Use `VISUAL_WARNING` only with `Result: PASS`, and only when `Why not fail` explains why the concern is not a hard failure. It cannot cover wrong person, wrong product, wrong wardrobe, source contamination, changed shot order, visible squeeze, missing or unsaved outputs, or thin/watery/gray/yellow mud. Use `EVIDENCE_STOP` when the image may be usable but required proof is missing or inconsistent.

## Result Meaning

| Result | Meaning | Runner behavior |
|---|---|---|
| `PASS` | Output meets the gate. | Advance to the next status. |
| `FAIL` | Output is unusable, but retry is allowed. | Retry the same stage with one changed variable. |
| `STOP` | Human judgment, cost approval, or blocked condition is required. | Stop and ask the user. |

## Required Gate Output

Every gate review artifact must include:

```text
Gate:
Job:
Stage:
Input artifacts:
Checks:
Result: PASS / FAIL / STOP
Reason:
Failed item:
Retry variable:
Locked variables:
Next status:
Needs user confirmation:
Outcome type:
Why not fail:
```

## Retry Rule

Retry is not "try again".

Each retry must change only one variable, and must keep the other approved variables locked.

If the same failure repeats twice after changing the intended variable, the loop must step back to the previous stage or stop for user review.

## Relationship To QC_RULES.md

`QC_RULES.md` is the shared rule library.

Files in `gates/` are stage-specific contracts. They should reference the relevant section in `QC_RULES.md` and make it executable for one stage.

## Maker / Checker Split

In self-audit mode, the maker does not grade its own output.

Use this split:

| Role | Allowed | Not allowed |
|---|---|---|
| Maker | Create or repair the stage artifact. | Decide final `PASS` / `FAIL` / `STOP`. |
| Checker | Inspect the maker artifact against the linked gate and write a checker review. | Rewrite, repair, or improve the maker artifact. |
| Orchestrator | Record the checker result through `./run-loop.sh --record-gate-result ...`. | Override the checker result casually. |

Checker reviews must be saved under:

```text
output/<job-id>/checks/<stage>_gate_review.md
```

Before recording a checker result, validate its structure with:

```bash
python3 tools/checker_review_qc.py \
  --review output/<job-id>/checks/<stage>_gate_review.md \
  --gate gates/<stage>_gate.md \
  --out-json output/<job-id>/checks/<stage>_gate_review_qc.json \
  --out-md output/<job-id>/checks/<stage>_gate_review_qc.md
```
