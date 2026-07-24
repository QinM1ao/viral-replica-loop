# Image Batch Gate

## Stage

`image_batch_qc`

## Purpose

Decide whether full storyboard image outputs are safe to become downstream Seedance references.

## Active One-Pass Decision Path

The active gate decision is `tools/qc_risk_ledger.py --stage image_batch_qc`, which consumes `tools/storyboard_visual_acceptance.py` first. Deterministic preflight must pass before any visual request exists. When semantic families changed, the gate accepts exactly one `output/<job-id>/checks/image_batch_qc_semantic_review_request.json` and one checker response that explicitly returns every requested family.

Gate `PASS` requires the unified ledger to bind the current compare context, original artifact hashes, and every family fingerprint. Missing or unexpected families, stale fingerprints, a changed compare/original artifact, or a top-level result that differs from the worst family is `STOP`. Legacy geometry, continuity, and skincare reports may remain during expand-contract only as compatibility evidence; they cannot request another checker, generate another active compare, or independently satisfy this gate.

## Required Inputs

- Passed storyboard and contamination audit.
- Source Part storyboard images for every required target Part.
- Generated or repaired storyboard images.
- Reference manifest.
- For multi-Part default runs: `output/<job-id>/image-batch/fanout/fanout_plan.json` and `output/<job-id>/image-batch/fanout/fanout_merge_report.json`, proving Part generation used isolated per-Part contracts before the shared contract was merged.
- `output/<job-id>/product_profile.json`.
- Approved visual manifest.
- Product group manifest and either the user-provided identity group manifest or the complete storyboard-derived role/identity manifests.
- Product constraints.
- `QC_RULES.md`.
- `tools/visual_asset_manifest_qc.py` output.
- Visual manifest schema v2 Shot-label evidence for every promoted Part, verified by `tools/visual_asset_manifest_qc.py`.
- `codex_imagegen_contract.json` and `tools/codex_imagegen_contract_qc.py` output proving route `matpool_gpt_image_2_edit`.
- `tools/storyboard_visual_acceptance.py` deterministic preflight and its one family-scoped semantic request when inputs changed.

## Required Output Artifact

The worker must create an image batch review artifact under the job output folder.

It must include:

- Candidate paths.
- Reference manifest.
- Evidence that every required target Part was attempted or explicitly repaired in the same image batch stage; for a 45s job this means Part1, Part2, and Part3.
- For multi-Part runs, fanout evidence showing each Part wrote an isolated `contracts/partX_contract.json` and the shared `codex_imagegen_contract.json` was produced by the serialized merge step, not written concurrently by multiple generators.
- Matpool GPT-Image-2 invocation evidence: actual local image inputs were submitted, with roles for source storyboard, product profile-declared product/material refs, identity ref, and after-wash ref when used.
- Image generation route used for each candidate or repair.
- Matpool prompt path and a note that the prompt used the source-storyboard rolemap structure, including a hard source-scene rule and product/identity background-transfer exclusions.
- Asset type for each promoted storyboard image: `AI改好分镜图`.
- Updated `output/<job-id>/visual-assets/approved_visual_manifest.json`.
- Deterministic Shot-label evidence for every promoted Part, using the metadata-only contract in `codex-imagegen-direct.md`.
- Visual asset manifest QC JSON/Markdown.
- GPT Image contract QC JSON/Markdown for Matpool-routed candidates.
- One canonical compare bound to the current source/promoted Part images and support references.
- One checker response with explicit family results for geometry/appearance, identity/product/material integrity, cross-Part continuity, and profile-required skincare progression.
- Explicit full-person replacement: approved model/person reference controls face, hair, body, and clothing. Source-video clothing is forbidden unless the user explicitly asks for a face-only swap or source-wardrobe preservation.
- Explicit character role map for multi-person sources: approved identity controls only the protagonist/product-host role; secondary roles preserve story function and gender and may use generic/de-identified identities.
- For `storyboard_derived`: each required identity originates from a passed current-job storyboard; recurring roles reuse that identity in later-Part edits; the approved visual manifest lists per-Part identity roles and refs.
- Explicit white-mud thickness review when the loaded product profile is clay-mask: color metrics are not enough. Face-applied mud and jar mud must look like raised, opaque, thick clay paste with visible body, edges, ridges, or small peaks; thin lotion, translucent cream, foundation-like smear, or flat white paint is a hard failure even if white/cool-white thresholds pass.
- API-effect baseline note: the artifact must say the Matpool GPT-Image-2 edit route and real local reference-image contract were used.
- Simple replacement edit note for each Part: the source Part storyboard was the edit target, product/person/after-wash images were replacement references only, panel-content subtitles/old overlays were removed, and original scene/crops/hand positions/action rhythm plus Shot labels were preserved.
- Layout and shot-order check.
- Identity check.
- Product check.
- Cross-part color and lighting check.
- Contamination check.
- Result: `PASS`, `FAIL`, or `STOP`.

## PASS

Return `PASS` only if:

- Every promoted Seedance/storyboard reference image is generated, edited, or repaired for the target product/person. Raw source-video rhythm boards, contact sheets, or cropped source frames cannot pass.
- Every required target Part has a promoted current-job storyboard image, or the review explicitly records a targeted Part failure and returns `FAIL`/`STOP`.
- Every promoted Part image is listed in the approved visual manifest as current-job `AI改好分镜图`.
- For multi-Part default image batch, `tools/image_batch_fanout.py merge` has `PASS` evidence and the merged shared contract contains every required Part from the source storyboard manifest.
- The artifact proves the image was edited through Matpool from the actual source storyboard with product/person references submitted as local files, not generated text-only from local path names or descriptions.
- The Matpool prompt itself binds the source storyboard as the scene/camera/action edit target and says product/identity/after-wash references are replacement references only, not background, lighting, room, selfie, crop, packshot, or scene-composition sources.
- `tools/visual_asset_manifest_qc.py` returns `PASS`.
- Every promoted Part is the hash-matched output of the mandatory Shot-label metadata step; its evidence records the expected ordered labels, zero panel-pixel changes, and identical before/after panel-content fingerprints. This proof replaces repeated manual label OCR and cannot trigger a second content review.
- `tools/codex_imagegen_contract_qc.py` returns `PASS` and proves every promoted Part was generated through Matpool from the source storyboard plus product profile-declared refs.
- The unified checker returns `PASS` for every requested family. Geometry/appearance rejects changed canvas/grid/order, visible squeeze/crop drift, or recomposition; continuity and skincare progression are evaluated inside the same response when applicable.
- The review records that the Matpool GPT-Image-2 edit/reference contract was used.
- Product refs are bound to the active product group and identity/after-wash refs are bound to the active identity group.
- All required images preserve storyboard layout, source aspect, and shot order as one complete edited Part storyboard image.
- All required images preserve the source `Shot 01-12` labels, label positions, ordering, and panel correspondence. Shot labels are not treated as subtitle contamination.
- All required images keep the original source scene, camera crops, hand/action placement, and storyboard composition. The intended changes are limited to old person, old product/tool/mud, and subtitles/old overlays.
- All required images preserve the source Part storyboard canvas geometry: portrait source boards usually keep 4 columns x 3 rows, landscape source boards usually keep 3 columns x 4 rows, panel positions remain source-sized, the image is not visually squeezed, and the output reads as a source-storyboard edit/reference result rather than a newly generated storyboard collage.
- The edited Part image canvas ratio matches the corresponding source Part storyboard ratio; landscape source storyboards must remain landscape unless a vertical adaptation was explicitly approved.
- Person identity, target wardrobe, and scene are stable across Parts as one stitched video. If Part1 and Part2 are meant to be adjacent slices of the same source video, the clothing must read as the same approved model outfit family; an obvious shirt/jacket/neckline/color change is a hard failure unless the source story explicitly changes outfit/scene and the Seedance prompt explains that transition. Clothing visible in the model reference is required target wardrobe by default.
- Product form, label, and texture match client assets.
- For Kongfengchun brand profiles, product-close panels show the active product packaging from current product assets, not a blank/generic/invented package. The green marker alone is not enough.
- When the product profile declares visible label text, designated hero close-ups preserve the major brand/product-name identity and overall label design. Apply `small_or_distant_product_text=visual_match_only`: distant, oblique, multi-bottle, and storyboard-scale microtext only needs the same overall color, line layout, and brand impression, not exact character-for-character reproduction. Apply `microtext_only_mismatch_outcome=VISUAL_WARNING`: microtext variation alone must not be the sole reason for hard `FAIL`. Wrong product/brand, a blank or smoothed label, an old-source label, a wrong label design, or a clearly wrong/missing major hero-label anchor still cannot pass.
- For multi-person source stories, only the source-defined protagonist/product-host role uses the approved identity. Secondary characters keep their source role and gender as generic/de-identified context identities.
- When `person_asset_mode=storyboard_derived`, the role map predates ImageGen, every identity manifest binds a passed current-job storyboard, recurring roles use one identity across Parts, and each Part upload mapping contains only its own required `identity_role_*` refs.
- The Matpool contract truthfully distinguishes `generate_from_source_roles_then_derive` first edits from `reuse_storyboard_derived_roles` later edits. The first has a loaded role map and no fake identity input; later edits list every real `identity_role_*` input and preserve reference order.
- For mud-mask products, face-applied mud and open-jar mud match the approved white/milky-white thick paste reference.
- For mud-mask products, face-applied mud and open-jar mud have visible thickness and paste body. A thin white smear is not acceptable just because it is white.
- When the loaded product profile declares skincare progression, the image set preserves a real before/after progression: before wash may be mildly dull, oily, textured, pore-visible, or closed-comedone visible; after wash is cleaner/brighter/smoother only after the wash/wipe proof. The before state cannot already look like the after-wash beauty reference.
- For clay-mask profiles, old source tube/stick/brush/arm-swatch actions are translated into finger pickup from the open jar and fingertip face application. For other profiles, old source tools are translated into the current product's real usage action.
- Old product/person/caption/prop contamination is removed.
- Cross-part color, skin tone, scene, lighting, wardrobe, and mud/product style are close enough to avoid video mismatch.
- No deprecated GPT Image route was used.

## FAIL

Return `FAIL` if:

- Any final/promoted Seedance reference image is a source-video frame board, rhythm board, contact sheet, or cropped source frame with old product, old person, subtitles, gray/yellow mud, or old props still visible.
- Any final/promoted image is a Python/PIL composite, validated-anchor拼图, old-job storyboard image, or unsaved image-generation claim. The sole exception is the hash-matched Shot-label metadata-only output defined by `codex-imagegen-direct.md`, with passing zero-panel-change evidence.
- Any final/promoted image came from text-only generation without actual image references submitted.
- Any Matpool prompt lacks a hard source-scene rule, lets model/product reference backgrounds transfer into the generated storyboard, or fails to say the source storyboard is the scene/camera/action edit target.
- Any concurrent Part generation wrote directly to `output/<job-id>/image-batch/codex_imagegen_contract.json` instead of isolated `contracts/partX_contract.json` files followed by a serialized merge.
- A multi-Part image batch is missing fanout merge evidence, has duplicate Part contracts, or the merged contract lacks any required Part from the source storyboard manifest.
- Any final/promoted image is a 9:16 single frame, standalone product/person poster, split-panel export, or externally recomposed grid instead of one AI-edited full storyboard image.
- Any final/promoted image forces a landscape source storyboard into portrait/3:4 layout without explicit approval.
- A reusable product or after-wash reference is treated as the current job's Part storyboard.
- The approved visual manifest or visual asset manifest QC is missing or failing.
- A schema-v2 Part is missing Shot-label metadata evidence, the evidence hash does not match the promoted image, or any pixel outside the label bars changed.
- GPT Image contract QC is missing or failing.
- Unified storyboard visual acceptance evidence is missing, stale, or failing.
- Any final/promoted image changes the source Part storyboard canvas size beyond tiny API output-size drift, changes the 12-panel template, makes panels materially larger/smaller than the source grid, visibly squeezes/squashes the person, or looks like a recomposed random 12-panel storyboard instead of the `job-002` API edit effect.
- Any worker continues repairing a generated candidate after it changed scene, storyboard geometry, shot order, or subject proportions instead of restarting from the source Part storyboard.
- Any worker uses a failing Part1 image as the continuity reference for Part2.
- Cross-Part continuity QC is missing or failing for a multi-Part job.
- Skincare progression QC is missing or failing when required by the loaded product profile.
- Any candidate changes layout or shot order.
- Person identity drifts too much.
- Part1 and Part2 visually read as different shoots, different outfits, different scenes, or different people when they are supposed to be one continuous video.
- Product becomes invented, blank, generic leaf-only, wrong, yellow, beige, tan, cream-yellow, gray, watery, or old-source contaminated.
- A designated hero product close-up shows the wrong product/brand, wrong label design, old-source label, blank/smoothed label, or clearly wrong/missing major brand or product-name anchor. Small or distant microtext differences do not satisfy this failure condition.
- A secondary character is replaced by the approved protagonist identity, a source male support role becomes the female protagonist, or the candidate ignores the source role/gender map.
- A storyboard-derived identity comes from a failed storyboard, a raw source face, a crop, another job, or an unbound image; or a recurring role changes identity across Parts.
- Mud becomes thin, translucent, lotion-like, foundation-like, flat painted white, or lacks raised thick paste texture, even if automated color thresholds pass.
- Pre-wash face is already too white, too clean, too bright, or too polished to support a visible after-wash improvement.
- After-wash brightness appears before washing/rinsing/wiping, or the after-wash reference contaminates early panels.
- Before/after change is only lighting, exposure, wet reflection, or plastic smoothing rather than a credible clean-skin progression.
- Any candidate shows a source tool or product action that contradicts the loaded product profile's target usage action.
- A product-introduction or texture shot lacks the target product or shows non-white mud.
- Cross-part image color mismatch is already obvious.
- Cross-part source-wardrobe, neckline, sleeve, jacket, hair, scene, or lighting mismatch is already obvious enough that the joined video would feel split.
- A role table, prompt, or checker note asks Seedance to ignore visible old-source contamination. Text constraints cannot override contaminated pixels.
- The worker used a deprecated GPT Image route or gateway probe.
- The worker changes the Matpool route, prompt style, reference order, quality, or size in order to make a failed result pass.

Retry variable:

Choose exactly one:

- `identity_reference`
- `product_reference`
- `scene_prompt`
- `color_anchor`
- `cross_part_continuity`
- `skin_progression`
- `local_panel_repair`
- `geometry_appearance`

Locked variables:

Approved layout, source aspect ratio, shot order, and passed panels.

## STOP

Return `STOP` if:

- Hard checks pass and client taste review is needed.
- The same hard failure repeats after targeted retry.

## Next Status

On pass:

```text
image_qc_passed
```
