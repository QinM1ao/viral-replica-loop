---
title: One-Pass Storyboard Visual Acceptance
labels:
  - ready-for-agent
status: ready
created: 2026-07-20
---

# One-Pass Storyboard Visual Acceptance PRD

## Problem Statement

The loop already knows how to reuse unchanged visual QC by exact input fingerprint, but the first review of a changed image batch is still fragmented.

From the user's perspective, one set of promoted Part storyboards is being judged repeatedly. Storyboard geometry, cross-Part continuity, skincare progression, identity, product, material, and the checker review all inspect substantially the same pixels, but they create separate compare images, separate review artifacts, and repeated explanations. A technically acceptable image can therefore spend more time moving through machine review than being produced.

The user does not want weaker QC. Wrong people, wrong products, source contamination, changed shot order, squeezed subjects, gray or yellow mud, and false skincare progression must still block the loop. The problem is that the same visual fact is interpreted more than once, while facts that can be proven deterministically are still mixed with facts that require an actual visual judgment.

Hash-gated reuse solved the repeated-review problem after a PASS has already been recorded. It did not yet solve the first changed-state review, where three shallow visual QC flows and the checker still overlap. This optimization must close that gap without changing the validated 26-second Kongfengchun video result, its Seedance prompt standard, or the paid-generation boundary.

## Solution

Replace the fragmented image-batch visual review with one deep Storyboard Visual Acceptance pass.

The loop first runs cheap deterministic preflight checks for file presence, exact input binding, active manifest membership, source/current reference binding, canvas and grid facts, panel count, Shot metadata, and measurable shot order. If a deterministic hard check fails, the image batch stops without invoking visual judgment.

After deterministic preflight, the QC Risk Ledger selects only the changed semantic risk families. A single canonical compare context and one structured visual-review request are then sent to the checker at most once. The checker evaluates every requested family in that one pass and returns a separate result for each family. The Ledger records those results independently, so one local defect does not invalidate unrelated PASS families.

The semantic families cover geometry appearance, identity/product/material integrity, cross-Part continuity, and skincare progression when the product profile requires it. Unchanged families reuse their exact-input PASS. A completely unchanged image state invokes no visual checker and regenerates no compare image.

The result is fewer visual calls and fewer artifacts while keeping every existing hard protection. User-facing workflow language remains unchanged: the visible outcome is still a Pre-Seedance Handoff or Final Video, not a new review step.

## User Stories

1. As a viral-replica operator, I want one visual review for one active storyboard batch, so that the same pixels are not interpreted repeatedly.
2. As a viral-replica operator, I want unchanged storyboard evidence reused, so that a later stage does not reopen an already-passed visual fact.
3. As a viral-replica operator, I want changed semantic risks grouped into one request, so that checker waiting happens at most once per image state.
4. As a viral-replica operator, I want each requested risk family to receive its own result, so that one local failure does not erase unrelated PASS evidence.
5. As a viral-replica operator, I want deterministic checks to run before visual review, so that obvious machine-verifiable failures do not consume visual-checker time.
6. As a viral-replica operator, I want missing files to stop deterministically, so that the checker is not asked to judge incomplete inputs.
7. As a viral-replica operator, I want exact active-image bindings checked deterministically, so that stale review evidence cannot pass a changed image.
8. As a viral-replica operator, I want manifest membership checked deterministically, so that deprecated or failed images cannot enter the active batch.
9. As a viral-replica operator, I want current product and identity reference bindings checked deterministically, so that old-job support assets cannot masquerade as current assets.
10. As a viral-replica operator, I want canvas, orientation, grid, and panel-count facts checked programmatically, so that visual review focuses on appearance rather than metadata.
11. As a viral-replica operator, I want Shot-label metadata and measurable shot order checked programmatically, so that numbering normalization never triggers an image-model repair.
12. As a viral-replica operator, I want visible squeeze and recomposition judged visually, so that a numerically valid canvas cannot hide a bad composition.
13. As a viral-replica operator, I want wrong-person and wrong-wardrobe defects to remain hard failures, so that speed does not weaken identity replacement.
14. As a viral-replica operator, I want wrong-product and unreadable-label defects to remain hard failures, so that speed does not weaken product fidelity.
15. As a viral-replica operator, I want source-person, source-product, source-tool, and subtitle contamination to remain hard failures, so that the promoted storyboard is safe for Seedance.
16. As a cleansing-mud-mask operator, I want gray, yellow, watery, or thin mud to remain a hard failure, so that the validated white thick-paste standard is preserved.
17. As a cleansing-mud-mask operator, I want finger pickup and fingertip application checked in the same visual pass, so that product-action translation is not reviewed separately.
18. As a skincare-product operator, I want progression review selected by the product profile, so that irrelevant jobs do not pay for before/after analysis.
19. As a skincare-product operator, I want pre-wash and post-wash skin states judged together, so that lighting-only improvement cannot pass as product effect.
20. As a multi-Part operator, I want Part images judged side by side once, so that wardrobe, identity, setting, product, and effect continuity share one context.
21. As a single-Part operator, I want cross-Part checks omitted, so that nonexistent risks do not create empty work.
22. As a later-stage worker, I want to consume one authoritative visual-acceptance artifact, so that I do not search for three separate review families.
23. As a gate recorder, I want one aggregate outcome derived from per-family results, so that PASS, FAIL, and STOP remain unambiguous.
24. As a gate recorder, I want the worst requested family to determine the top-level outcome, so that a local failure cannot be hidden by other PASS results.
25. As a retry coordinator, I want a failed family to identify one scoped retry variable, so that only the affected Part or visual property is repaired.
26. As a retry coordinator, I want unrelated passed families to stay reusable after a localized repair, so that a small fix does not restart all visual review.
27. As a checker, I want one canonical compare context, so that I can inspect all requested visual risks without opening duplicate sheets.
28. As a checker, I want the request to exclude unchanged families, so that I do not second-guess locked PASS evidence.
29. As a checker, I want the request to name profile-selected families and required flags, so that I do not invent review scope.
30. As a checker, I want deterministic evidence summarized with the visual context, so that I can trust program-proven facts without re-evaluating them visually.
31. As an evidence auditor, I want the single review bound to the exact image, manifest, profile, and relevant source-reference fingerprints, so that mtime changes or copied reports cannot create false freshness.
32. As an evidence auditor, I want missing or inconsistent family results to STOP, so that partial checker output cannot be treated as PASS.
33. As an evidence auditor, I want one recorded checker invocation count, so that duplicate visual calls are measurable.
34. As a performance reviewer, I want compare generation count, requested family count, reused family count, active time, and wait time recorded, so that the speed gain is evidence-based.
35. As a performance reviewer, I want parallel work measured without double counting, so that later critical-path work can use clean visual-review spans.
36. As a maintainer, I want the old geometry, continuity, and skincare semantic review paths removed from the active call chain, so that duplicate behavior cannot quietly return.
37. As a maintainer, I want deterministic logic preserved as focused validators, so that consolidation does not turn cheap proof into model judgment.
38. As a maintainer, I want one high-level integration seam, so that tests survive internal module cleanup.
39. As a maintainer, I want existing risk-ledger fingerprints and mixed-family result behavior reused, so that this change builds on the completed architecture instead of replacing it.
40. As a maintainer, I want product-profile family selection reused, so that category and SKU rules remain authoritative.
41. As a maintainer, I want the validated Kongfengchun prompt and generation artifacts left unchanged, so that an architecture optimization cannot rewrite a successful creative result.
42. As a maintainer, I want the implementation verified without calling GPT Image or Seedance, so that this refactor has no paid-generation cost.
43. As a user stopping before generation, I want the same complete Pre-Seedance Handoff, so that speed work does not remove required upload assets or prompts.
44. As a user generating a final video, I want the same approval and retry boundaries, so that QC consolidation does not broaden paid authorization.
45. As a user, I want the final explanation to say which repeated checks were removed and which protections remain, so that the speed improvement is understandable in plain language.

## Implementation Decisions

- Scope this specification to architecture-review item 2: consolidating the visual judgment for promoted storyboard images. Hash-gated reuse is an already-completed dependency and remains the foundation.
- Introduce one deep Storyboard Visual Acceptance module as the only active semantic visual-review interface for the image-batch gate.
- Keep deterministic preflight separate from semantic review. Deterministic preflight owns file existence, exact input fingerprints, active manifest membership, reference bindings, image readability, canvas facts, grid facts, panel count, Shot metadata, and other reproducible contracts.
- Keep visually interpreted geometry separate from numeric geometry. Subject squeeze, crop drift, scene recomposition, and the perceived preservation of the source storyboard remain semantic risks even when dimensions pass.
- Model the semantic result as independent risk families: geometry appearance; identity, product, material, and source-contamination integrity; cross-Part continuity; and skincare progression when selected by the product profile.
- Let the product profile select optional families and family-specific expectations. Multi-Part continuity is selected only for multi-Part jobs, and skincare progression is selected only when declared by the loaded product rules.
- Generate one canonical compare context per active image fingerprint. It must include the promoted Part images and only the source or support references needed by the selected semantic families.
- Generate one semantic review request per active image fingerprint. The request names only changed families, carries each family fingerprint, and records an invocation count of one.
- Accept one checker response containing an explicit result for every requested family. Missing family results or unexpected family names are evidence failures, not implicit PASS.
- Bind the checker response to every requested family fingerprint and to the canonical visual context before the result can satisfy the gate.
- Preserve family-level reuse. A localized repair invalidates only the families whose inputs or user-visible defect scopes changed; unrelated family PASS evidence remains reusable.
- Derive the top-level outcome from the worst requested family while retaining each family result and retry scope.
- Preserve existing hard-failure policy for wrong person, wardrobe, product, label, source contamination, shot order, squeeze, unsaved output, and invalid mud color or texture.
- Preserve Visual Warning only for non-material signals with an explicit reason not to fail. A warning cannot excuse any existing hard-failure category.
- Remove the three duplicate semantic-review and compare-generation paths from the active worker and checker contracts. Any temporarily retained compatibility entry point must consume the unified acceptance result and must not create another visual judgment or compare asset.
- Make the QC Risk Ledger the sole selector of whether a visual call is required. Workers and gates must not independently reopen families that the Ledger marked as reused.
- Make the unified acceptance artifact the visual source of truth for downstream prompt and request stages. Those stages may run deterministic synchronization checks but may not re-run image semantics when the bound image state is unchanged.
- Record performance evidence as counts and spans: canonical compare generations, checker invocations, requested families, reused families, active seconds, and wait seconds.
- Use call-count and artifact-count reductions as the primary acceptance metric because provider wall time varies. A replay measurement may report wall-clock savings but must not be the only proof.
- Implement in four bounded phases: first add a failing high-seam regression test; second add the unified acceptance contract and profile-driven family selection; third route the Ledger, checker, worker, and gate through it and delete duplicate active paths; fourth replay existing assets, run regression tests, and update operator documentation.
- Do not alter job state files manually. Any later live-state validation must use the normal runner and gate-recording path.
- Do not call paid image or video generation as part of implementation or verification.

## Testing Decisions

- Use one highest practical seam: the image-batch runner/gate boundary. A test job supplies active images, manifest, product profile, deterministic evidence, and a checker response, then exercises the same gate-recording behavior used by the loop.
- A good test asserts externally visible behavior: whether the gate blocks or passes, how many semantic requests were emitted, which families were requested or reused, whether one checker response was bound, and which artifacts were produced. Tests should not assert private helper names or internal call order beyond the public deterministic-before-semantic contract.
- Reuse the existing runner-enforcement, QC Risk Ledger, checker-binding, input-binding, product-profile, and storyboard-geometry test patterns as prior art.
- Add a changed-image scenario where geometry appearance, identity/product/material integrity, continuity, and skincare progression are all required. It must emit one semantic request, one canonical compare context, and one checker invocation.
- Add an unchanged-image scenario. It must reuse the family PASS results, emit no semantic request, invoke no checker, and avoid regenerating the compare context.
- Add a mixed-result scenario. One family fails while the other requested families pass; the top level fails, the failing family names one retry scope, and the passed families remain independently reusable.
- Add a localized-repair scenario. Changing one Part or one scoped defect invalidates only affected family fingerprints and does not reopen unrelated families.
- Add a deterministic-failure scenario for missing input, broken binding, invalid canvas/grid metadata, or Shot-order evidence. It must block before any semantic request.
- Add a missing-family-result scenario. A checker response that omits a requested family must STOP as incomplete evidence.
- Add a profile-selection matrix covering single-Part, multi-Part, skincare-required, and skincare-not-required jobs.
- Add a hard-failure matrix covering wrong identity, wrong product, source contamination, visible squeeze, and invalid mud material. These cases must remain failures after consolidation.
- Add a warning case proving that a non-material pixel signal may pass only with an explicit reason not to fail.
- Replay the already-generated job-012 image assets without paid generation. Verify that three old compare/review paths are replaced by one active visual acceptance and that an unchanged replay requires zero semantic calls.
- Run the existing 28-test Ledger and timing baseline, all affected image-batch/runner tests, and then the full repository test suite.
- Do not require a real visual model in automated tests. Use a deterministic checker-response fixture at the public binding interface.

## Out of Scope

- Re-running or changing the validated Kongfengchun Seedance generations.
- Rewriting the validated 26-second Part1 and Part2 prompts, voiceover, director plan, or final video.
- Redesigning the Pre-Seedance compiler and its prompt/request reverse-parsing contracts; that is architecture-review item 3.
- Broadly changing pixel thresholds or downgrading product errors to warnings; that is architecture-review item 4.
- Rebuilding the entire timing report around critical-path accounting; that is architecture-review item 5.
- Changing source-blueprint understanding, ASR, rhythm extraction, storyboard generation, GPT Image prompting, or paid-generation approval.
- Adding new user-facing review steps or exposing internal hashes as part of the user workflow.
- General code cleanup outside the visual-acceptance call chain.

## Further Notes

Current evidence supports this order of work:

- The QC Risk Ledger dependency is implemented and its focused Ledger/timing suite passes 28 tests.
- A read-only Ledger evaluation on job-012 reuses existing semantic visual PASS evidence with no new semantic request when the active fingerprint is unchanged.
- The same job still contains three separate visual compare images and three specialized review artifacts from the original image-batch pass, plus the checker review. This is the duplication targeted by this specification.
- The validated 26-second Kongfengchun result is regression evidence only. It must not be regenerated or creatively modified.

Success is defined primarily by behavior:

1. A changed active storyboard state causes at most one checker invocation.
2. One active fingerprint produces at most one canonical visual compare context.
3. An unchanged fingerprint causes zero checker invocations and zero compare regeneration.
4. Deterministic failures block before semantic review.
5. Mixed family results preserve unrelated PASS evidence.
6. Existing hard visual failures remain hard failures.
7. The complete repository test suite passes without paid generation.

The next optimization should be architecture-review item 3 only after this slice is implemented and its replay evidence is accepted. Critical-path timing work should remain last because it improves measurement accuracy more than runtime itself.
