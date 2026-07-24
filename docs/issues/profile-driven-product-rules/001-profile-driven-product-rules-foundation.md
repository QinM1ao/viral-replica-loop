---
title: Build the profile-driven product-rule foundation
labels:
  - ready-for-agent
status: ready
parent: docs/prd/2026-07-02-profile-driven-product-rules.md
---

# Build The Profile-Driven Product-Rule Foundation

## Goal

Make new products run through a generic product contract by default, while allowing category and SKU-specific rules only when the job product profile explicitly loads them.

The first implementation must prevent Kongfengchun fermented toner and future new products from inheriting cleansing mud-mask rules, while preserving the existing cleansing mud-mask behavior when the job is actually a clay-mask product.

## Scope

- Add a minimal product profile artifact for every job.
- Add a generic product contract that always loads.
- Add initial category rules for toner and clay mask.
- Split Kongfengchun brand-level behavior from Kongfengchun cleansing mud-mask SKU behavior.
- Add or migrate a Kongfengchun fermented-toner product profile.
- Update intake so brand name alone no longer loads mud-mask behavior.
- Update image/QC workers and gates so required refs/checks come from loaded product rules.
- Update QC tools so they stop using product-name keyword heuristics for mud-mask checks.
- Migrate existing known jobs into explicit product profiles.

## Acceptance Criteria

1. A new unknown product gets a product profile with generic rules only.
2. Kongfengchun fermented toner gets toner rules and does not load clay-mask rules.
3. Kongfengchun cleansing mud mask gets clay-mask rules and keeps the existing white thick paste/fingertip application expectations.
4. Brand-level Kongfengchun rules do not imply white mud, open jar, after-wash proof, or single-male identity by themselves.
5. Visual manifest QC uses profile-declared required refs.
6. GPT Image contract QC uses profile-declared product/action/material checks.
7. Hard image QC runs mud-mask checks only for jobs whose loaded rules require them.
8. Existing path-based intake remains valid for users.
9. Gate reviews show which product rules were loaded and which special rules were skipped.
10. Tests cover toner, clay mask, and unknown product behavior.

## Testing Seam

Use the highest practical seam: intake/profile loading plus QC behavior.

Prefer tests that create representative job rows and product profiles, then run the same public QC/runner commands that the loop uses. Avoid tests that assert helper function names or internal branching.

## Notes

Do not implement paid generation or visual-quality improvements for an existing job in this slice. The deliverable is the rule architecture and the regression protection that prevents product-specific rule leakage.

## Applied Follow-Up

Date: 2026-07-02

After the foundation landed, `job-001` for `孔凤春发酵水` exposed two regression surfaces:

- GPT Image preserved bottle shape/color but erased readable product text.
- A two-person source storyboard was treated like a single-identity scene, so the male support role risked becoming the female protagonist identity.

The reusable fix is part of the profile-driven contract: add `visible_text_patterns`, require `product_visible_text` and `no_blank_label`, replace `single_identity` with protagonist/secondary-role review flags, and evaluate this through `vrep-output-visible-label-role-map` in `.agents/skills/video-replication/evals/output_cases.json`.
