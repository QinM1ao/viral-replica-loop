---
title: Profile-Driven Product Rules
labels:
  - ready-for-agent
status: ready
created: 2026-07-02
---

# Profile-Driven Product Rules PRD

## Problem Statement

The viral-replica loop currently lets product-specific and client-specific rules leak into unrelated jobs.

From the user's perspective, this is most visible with Kongfengchun: a job for Kongfengchun fermented toner can still be treated like Kongfengchun cleansing mud mask because the loop recognizes the brand name but does not reliably distinguish brand, category, and SKU. The result is that a new or different product may inherit white mud, open jar, fingertip clay application, after-wash proof, single-male model, or other rules that only belong to an already-run mud-mask product.

This makes the loop less reusable. The user wants the opposite default: every new product should run on the generic viral-replication contract unless the loop has explicit evidence that a category or SKU-specific rule applies. The universal behavior should remain strong: preserve the viral source rhythm, preserve story function, replace the old product with the current product, keep product packaging and text consistent, remove old-source contamination, and prove the generated image/video assets are backed by current product references.

## Solution

The loop should become profile-driven.

Every job should have a minimal product profile artifact generated from the current intake and product assets. The product profile is the single source of truth for brand, category, SKU/profile identity, required reference roles, product form, label details, usage action, material/texture, and special rules.

The default product contract should be generic. It should apply to every product, including brand-new products with no known category. It should enforce product consistency, source-rhythm preservation, current product references, old-product removal, old-person removal, subtitle cleanup, and proof that image generation used real references.

Category rules should be optional white-listed plugins. A clay-mask job may load clay-mask rules. A toner job may load toner rules. A food job may load food rules when such rules exist. Unknown products should not inherit any special category checks.

Brand and SKU rules should be even narrower. Kongfengchun brand rules may apply to all Kongfengchun products only when they are genuinely brand-level. Kongfengchun cleansing mud mask rules must apply only to the cleansing mud mask product or a clearly declared clay-mask profile. Kongfengchun fermented toner rules must apply only to the toner product/profile and must explicitly prevent mud-mask rules from loading.

QC and worker decisions must stop guessing from product-name keywords alone. They should read the job product profile and the loaded category/profile rules. When classification is uncertain, the loop should continue with the generic contract instead of blocking or applying the wrong special rules.

## User Stories

1. As a viral-replica operator, I want a brand-new product to run through a generic product contract, so that old client-specific rules do not pollute the job.
2. As a viral-replica operator, I want every job to have a minimal product profile, so that image, prompt, request, and QC stages all share the same product facts.
3. As a viral-replica operator, I want the loop to distinguish brand, product category, and SKU profile, so that products from the same brand can have different behavior.
4. As a viral-replica operator, I want Kongfengchun fermented toner to be treated as toner, so that it does not inherit cleansing mud-mask white-mud rules.
5. As a viral-replica operator, I want Kongfengchun cleansing mud mask to keep its clay-mask rules, so that the existing validated mud-mask quality bar is preserved.
6. As a viral-replica operator, I want product-category rules to load only when a category is explicitly declared or confidently detected, so that uncertain products do not get the wrong special checks.
7. As a viral-replica operator, I want SKU rules to load only when a product profile is explicitly matched, so that one previously successful SKU cannot constrain unrelated SKUs.
8. As a viral-replica operator, I want unknown products to continue through the generic contract, so that the loop remains usable without manual profile setup.
9. As a viral-replica operator, I want product-name matching to be conservative, so that a shared brand name does not imply a shared material, action, or packaging rule.
10. As a viral-replica operator, I want the generic contract to enforce current product consistency, so that the target product replaces the source product in every relevant shot.
11. As a viral-replica operator, I want the generic contract to preserve viral source rhythm, so that new products still inherit the benchmark video's story function and shot order.
12. As a viral-replica operator, I want the generic contract to preserve source storyboard geometry, so that image generation does not become a new ad layout or poster.
13. As a viral-replica operator, I want the generic contract to remove old-product contamination, so that source packaging, source texture, source tools, and old captions do not survive into final references.
14. As a viral-replica operator, I want product labels and visible text to come from current product assets, so that generated product close-ups do not invent packaging.
15. As a viral-replica operator, I want product usage action to come from the current product profile, so that a toner pours or pats while a clay mask uses paste application.
16. As a viral-replica operator, I want a category profile to define required references, so that toner does not require open white mud and clay mask can require an open material reference.
17. As a viral-replica operator, I want category profiles to define required checks, so that only relevant QC runs for each product.
18. As a viral-replica operator, I want category profiles to define forbidden checks, so that toner explicitly excludes white-mud and jar-finger checks.
19. As a viral-replica operator, I want brand profiles to contain only brand-level preferences, so that brand-level rules do not accidentally become product material rules.
20. As a viral-replica operator, I want product profiles to contain SKU-specific facts, so that a product's bottle, jar, label, cap, texture, and action are grounded in the provided assets.
21. As a viral-replica operator, I want the product profile to record confidence, so that low-confidence category detection does not silently become a hard rule.
22. As a viral-replica operator, I want low-confidence classification to load only the generic contract, so that the loop prefers under-specialization over wrong specialization.
23. As a viral-replica operator, I want profile generation to be automatic, so that simple path-based intake remains enough to start a task.
24. As a viral-replica operator, I want profile generation to stop only when product assets are missing or unusable, so that normal new products do not require manual profile approval.
25. As a viral-replica operator, I want the loop to record which rules were loaded, so that later agents can understand why a QC check ran.
26. As a viral-replica operator, I want the loop to record which rules were not loaded, so that false positives like mud-mask rules on toner are easy to diagnose.
27. As a viral-replica operator, I want visual-asset manifest QC to use product profile declarations, so that required references match the current category.
28. As a viral-replica operator, I want GPT Image contract QC to use product profile declarations, so that source-transfer and product-action checks match the product.
29. As a viral-replica operator, I want hard image QC to use product profile declarations, so that white-mud metrics do not run on non-mud products.
30. As a viral-replica operator, I want skincare progression QC to run only for products that declare skincare/beauty before-after requirements, so that unrelated products are not blocked by irrelevant skin checks.
31. As a viral-replica operator, I want the image workers to ask for product refs by semantic role, so that different categories can provide different valid reference sets.
32. As a viral-replica operator, I want the prompt workers to read loaded product rules, so that Seedance prompt constraints match the current product.
33. As a viral-replica operator, I want the request workers to package only relevant product references, so that the final upload set does not include irrelevant support images.
34. As a viral-replica operator, I want existing Kongfengchun mud-mask jobs to remain valid, so that validated workflow knowledge is not lost.
35. As a viral-replica operator, I want existing Kongfengchun fermented-toner jobs to be repairable under toner rules, so that they no longer fight mud-mask gates.
36. As a viral-replica operator, I want migration for existing jobs, so that old rows can get product profiles without manually recreating the queue.
37. As a viral-replica operator, I want new-task intake to infer only safe profile metadata, so that the job queue starts with useful product structure.
38. As a viral-replica operator, I want inbox sync to follow the same profile rules as new-task intake, so that task creation paths behave consistently.
39. As a later agent, I want one documented rule-loading algorithm, so that I do not have to rediscover profile precedence from scattered worker instructions.
40. As a later agent, I want the rule-loading algorithm to be testable at a high seam, so that changes in internals do not break the intended behavior.
41. As a later agent, I want profile-driven QC tests for toner and clay mask examples, so that future edits do not reintroduce keyword-based contamination.
42. As a later agent, I want unknown-product tests, so that the generic path remains first-class.
43. As a later agent, I want all product-specific rules removed from global instructions unless they are clearly labeled as examples, so that global instructions remain reusable.
44. As a later agent, I want every stop or fail report to cite the loaded product/category/profile rules, so that debugging is concrete.
45. As a later agent, I want every promoted asset to record the product profile used, so that downstream stages can verify they are using the current product facts.

## Implementation Decisions

- Introduce a product-profile layer for every job. The profile records the current product's brand, category, SKU/profile identity, visible product form, label details, material or texture, usage action, reference roles, banned source carryover, loaded rules, and classification confidence.
- Keep simple path-based intake. The user should not need to mention internal profile files. Intake should create or update the minimal product profile automatically.
- Separate rule scopes into generic contract, category rules, brand rules, and SKU/product rules.
- The generic contract is always loaded. It contains product consistency, source rhythm, story function, current product references, person replacement, old-source contamination removal, subtitle cleanup, and evidence requirements.
- Category rules are loaded only by explicit profile declaration or confident category detection. Category rules may define required references, optional references, required checks, forbidden checks, product-action transformations, prompt constraints, and QC expectations.
- Brand rules are loaded only for brand-level preferences and must not contain category- or SKU-specific material rules.
- SKU/product rules are loaded only when the product profile explicitly matches a known SKU or product profile.
- Rule precedence is generic first, then category, then brand, then SKU/product. Narrower rules may add or refine requirements, but unrelated rules must not load.
- If category detection is uncertain, the product profile records low confidence and loads only the generic contract plus any explicit user-provided facts.
- A profile may explicitly forbid a category rule. Kongfengchun fermented toner should explicitly forbid clay-mask rules.
- Product name keyword matching alone is not enough to load a special rule. It may propose a candidate category/profile, but the final loaded rules must be recorded in the product profile.
- Existing Kongfengchun cleansing mud-mask behavior should migrate into a clay-mask category rule plus a Kongfengchun cleansing-mud-mask SKU rule.
- Existing Kongfengchun fermented toner behavior should migrate into a toner category rule plus a Kongfengchun fermented-toner SKU rule.
- The current client profile should become a brand profile when the rule is genuinely brand-level. It should not act as a catch-all for every product under the brand.
- The image workers should consume semantic reference roles from the product profile instead of assuming product-front plus open-white-mud references for every product.
- Visual manifest validation should use the profile's required and optional references instead of hard-coded mud-mask references.
- GPT Image contract validation should use the profile's required transfer/exclusion/action checks instead of inferring mud-mask checks from product name.
- Hard image checks should use declared category checks, not product-name heuristics.
- Skincare progression checks should run only when the loaded category/profile declares before-after skin proof.
- Existing file names and QC report names that are part of runner compatibility can remain, but their human-facing wording should become GPT Image/product-profile oriented instead of hard-coded to older route names or mud-mask assumptions.
- Existing jobs should be migratable without recreating the queue. The migration should map the current cleansing mud-mask job to clay-mask rules and the fermented-toner job to toner rules.
- The rule-loading result should be visible in job artifacts and gate reviews: loaded rules, skipped special rules, category confidence, and product profile path.
- The first implementation slice should focus on eliminating false mud-mask triggering for new products and for Kongfengchun fermented toner, while preserving Kongfengchun cleansing mud-mask behavior.

## Testing Decisions

- The highest-value test seam is job intake plus rule loading plus QC behavior. Tests should verify externally visible behavior: generated product profile, loaded rules, required refs, skipped refs, and pass/fail behavior.
- Tests should avoid asserting internal helper names. They should assert the behavior an operator cares about: toner does not require white mud, clay mask still requires clay-mask refs/checks, unknown product uses generic contract only.
- Add intake tests for three representative jobs: Kongfengchun fermented toner, Kongfengchun cleansing mud mask, and an unknown new product.
- Add rule-loading tests that prove brand alone does not load SKU/category rules.
- Add visual manifest QC tests that prove toner does not require open-white-mud references and clay mask still does.
- Add GPT Image contract QC tests that prove toner requires toner action evidence and forbids clay-mask action checks, while clay mask still checks white thick paste and fingertip application.
- Add hard image QC tests that prove mud color/thickness checks are category-driven.
- Add runner/gate recording tests only where the behavior crosses stage boundaries, such as refusing PASS when required product-profile evidence is missing.
- Reuse existing unit-test style and the existing runner/QC seams. Do not add a large new test harness unless a profile loader seam is needed.
- Do not run real GPT Image, Seedance, or paid generation in tests.
- A good test should fail if a future agent reintroduces product-name-only matching for special rules.

## Out of Scope

- Rewriting the whole viral-replica loop.
- Redesigning Seedance prompt craft beyond making it consume loaded product rules.
- Building a web UI for product profile editing.
- Requiring manual review for every new product profile.
- Creating exhaustive category profiles for every possible product type in the first slice.
- Changing the Matpool GPT-Image-2 invocation route.
- Running paid Seedance generation.
- Improving the visual quality of any single existing job as part of this PRD.
- Cleaning every historical artifact or old draft in the repository.

## Further Notes

The user's core requirement is generality: a new product should not inherit constraints from products that happened to be run before. The minimum universal standard is product consistency plus faithful viral rhythm replication. Special rules should improve quality only when they are known to apply.

The most important failure to prevent is a false positive special rule. The loop should prefer generic behavior over wrong specialization. A missing special rule can be added later; a wrong special rule can poison the entire image, prompt, request, and QC pipeline.

The first ready-for-agent implementation should deliver a working profile-driven foundation, not an exhaustive product taxonomy.

## Validated Lesson: Visible Text And Multi-Person Role Maps

Date: 2026-07-02

The `孔凤春发酵水` repair confirmed two profile-driven rules that should remain reusable:

- Product profiles may declare `visible_text_patterns`. When they do, product-close panels must preserve readable real product text, and GPT Image contract review must require `product_visible_text=true` plus `no_blank_label=true`. A package that is the right color/shape but has a blank, smoothed, pseudo-text, or logo-only label is a failure.
- Multi-person source videos need a source-story role map. The approved identity applies only to the protagonist/product-host role. Secondary characters preserve story function and gender, can be generic/de-identified, and must not be replaced by the protagonist identity.

This lesson is backed by `output/job-001/image-batch/candidates/part1_label_rolemap_repair.png` and `output/job-001/checks/part1_label_rolemap_repair_contract_qc.json`.
