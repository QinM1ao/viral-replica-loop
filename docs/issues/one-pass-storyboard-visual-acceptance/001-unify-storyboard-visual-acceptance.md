---
title: Unify storyboard visual acceptance
labels:
  - ready-for-agent
status: ready
parent: docs/prd/2026-07-20-one-pass-storyboard-visual-acceptance.md
---

# Unify Storyboard Visual Acceptance

## Goal

Make one active set of promoted storyboard images require at most one real visual judgment while preserving deterministic hard checks, exact-input evidence reuse, profile-driven risk selection, and every existing hard visual failure.

## Scope

- Add one authoritative Storyboard Visual Acceptance contract.
- Separate deterministic preflight evidence from semantic visual families.
- Build one canonical compare context for the selected semantic families.
- Emit one batched semantic request for changed families only.
- Bind one checker response to every requested family fingerprint.
- Record family-specific PASS, FAIL, or STOP results and scoped retry variables.
- Preserve per-family reuse after a localized repair.
- Route image-batch worker, checker, gate, and downstream visual reuse through the unified result.
- Remove duplicate geometry, continuity, and skincare semantic review/compare generation from the active call chain.
- Record compare count, checker invocation count, requested/reused families, active time, and wait time.
- Update the operator and skill contracts only after behavior is verified.

## Acceptance Criteria

1. A changed multi-Part skincare storyboard batch emits exactly one semantic review request.
2. The request contains every changed profile-selected family and no unchanged family.
3. One canonical compare context is produced for one active image fingerprint.
4. The checker is invoked at most once for that fingerprint.
5. The checker response contains one explicit result for every requested family.
6. The checker response is bound to the current family fingerprints and visual context.
7. Missing, extra, or stale family results cannot pass the gate.
8. The top-level result is the worst requested family result.
9. A local family failure preserves unrelated family PASS evidence.
10. A localized repair reopens only affected semantic families.
11. An unchanged active fingerprint emits no semantic request and invokes no checker.
12. An unchanged active fingerprint does not regenerate the canonical compare context.
13. Missing inputs, stale bindings, invalid manifest membership, invalid canvas/grid facts, or invalid Shot metadata block before visual review.
14. Single-Part jobs omit cross-Part continuity.
15. Jobs without profile-declared skincare progression omit that family.
16. Wrong person, wardrobe, product, product text, or source contamination remains a hard failure.
17. Changed shot order, visible squeeze, or scene recomposition remains a hard failure.
18. Gray, yellow, watery, thin, or source-contaminated mud remains a hard failure for the cleansing-mud-mask profile.
19. Non-material pixel warnings require an explicit reason not to fail and cannot excuse a hard-failure category.
20. Downstream prompt/request stages reuse the unified visual PASS when bound active inputs are unchanged.
21. The old three specialized semantic reviews and compare sheets are no longer produced by the active image-batch path.
22. The validated Kongfengchun prompts and videos are unchanged.
23. No paid image or video generation is called during implementation verification.
24. Focused and full repository test suites pass.

## Testing Seam

Use the image-batch runner/gate boundary as the single primary seam. Tests should construct representative active artifacts and execute public gate-recording behavior, then assert gate outcome, request count, family results, evidence binding, reuse behavior, and produced artifacts.

Keep focused unit tests only for deterministic validators whose external contracts cannot be diagnosed clearly through the high seam. Do not create separate semantic test harnesses for geometry, continuity, and skincare.

## Execution Order

1. Add a failing high-seam test that reproduces multiple visual-family review work for one changed image state.
2. Define the unified acceptance input, family-result, evidence-binding, and performance-evidence contract.
3. Move deterministic geometry and metadata facts into preflight and keep visually interpreted geometry in the semantic family set.
4. Make product profile and Part count select the semantic families.
5. Route the QC Risk Ledger and checker binding through the unified result.
6. Route worker and gate contracts through the unified result.
7. Delete duplicate active compare/review generation and update affected tests.
8. Replay existing job-012 assets without generation and verify one-call/zero-call behavior.
9. Run focused tests, the full suite, and update durable project documentation.

## Verification

```bash
python3 -m unittest \
  tests.test_qc_risk_ledger \
  tests.test_qc_risk_ledger_checker \
  tests.test_qc_risk_ledger_runner \
  tests.test_runner_enforcement
python3 -m unittest discover -s tests
```

The replay check must use already-generated assets and must not submit GPT Image or Seedance work.

## User Stories Covered

1-45

## Blocked By

None. Exact-input QC Risk Ledger reuse and batched checker-family binding are already implemented dependencies.

## Out of Scope

- Pre-Seedance compiler redesign.
- Broad pixel-threshold policy changes.
- Critical-path timing-report redesign.
- Source understanding, image generation, prompt craft, or paid-generation changes.
