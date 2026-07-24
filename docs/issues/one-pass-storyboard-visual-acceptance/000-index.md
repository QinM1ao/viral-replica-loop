---
title: One-Pass Storyboard Visual Acceptance Issue Index
labels:
  - ready-for-agent
status: ready
parent: docs/prd/2026-07-20-one-pass-storyboard-visual-acceptance.md
---

# One-Pass Storyboard Visual Acceptance Issue Index

Parent PRD: `docs/prd/2026-07-20-one-pass-storyboard-visual-acceptance.md`

Ready implementation slice:

1. `001-unify-storyboard-visual-acceptance.md` - Replace duplicate image-batch visual reviews with one family-aware acceptance pass - ready-for-agent

Verification target:

```bash
python3 -m unittest \
  tests.test_qc_risk_ledger \
  tests.test_qc_risk_ledger_checker \
  tests.test_qc_risk_ledger_runner \
  tests.test_runner_enforcement
python3 -m unittest discover -s tests
```

Paid GPT Image and Seedance calls are not part of verification.
