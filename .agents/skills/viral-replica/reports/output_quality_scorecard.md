# Output Quality Scorecard

Skill: `viral-replica`

Evidence mode: `file-backed fixture` plus deterministic structural checks.

## Summary

| Area | Current status | Notes |
|---|---|---|
| Trigger cases | present | `evals/trigger_cases.json` includes positives, negatives, and near neighbors. |
| Output cases | present | `evals/output_cases.json` records baseline risks and with-skill assertions. |
| Production structural check | present | `scripts/skill-release-check.py --skill viral-replica` validates package shape. |
| Full repo release check | present | `scripts/release-check.sh` validates install, tests, and runner dry-run. |
| Release readiness | production ready | Ready as local production loop adapter; not claiming governed/public distribution. |

## Current Quality Claims

- The loop adapter owns queue, gate, state, checker, approval, and handoff boundaries.
- It should not be used for craft-only video prompt work.
- It should not allow paid generation without explicit approval.

## Required Before Governed Promotion

- Run provider-backed trigger eval.
- Run output eval with baseline and with-skill model outputs.
- Record blind review decisions.
- Add package checksum and install evidence.
- Add runtime permission probes for packaged adapters.
