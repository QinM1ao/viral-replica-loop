# Image Sample Review Gate

## Stage

`image_sample_review`

## Purpose

Stop bad image samples before they become batch storyboard images or Seedance references.

## Required Inputs

- Image sample output.
- Source storyboard or shot table.
- Product assets.
- `output/<job-id>/product_profile.json`.
- Approved identity reference for the protagonist/product-host role.
- `PRODUCT_CONSTRAINTS.md`.
- Relevant `QC_RULES.md` image generation rules.
- Approved visual manifest draft or update for the sample candidate.
- Visual manifest schema v2 Shot-label evidence for the promoted sample.
- `tools/visual_asset_manifest_qc.py` output when the sample is being recorded as passed.
- `codex_imagegen_contract.json` and `tools/codex_imagegen_contract_qc.py` output proving route `matpool_gpt_image_2_edit`.

## Required Output Artifact

The worker must create a sample review artifact under the job output folder.

It must include:

- Sample path.
- Reference manifest.
- Matpool GPT-Image-2 invocation evidence: actual local image inputs were submitted, with roles for source storyboard, product profile-declared product/material refs, and identity ref.
- Layout check.
- Identity check.
- Product check.
- Scene and wardrobe check.
- Contamination check.
- Result: `PASS`, `FAIL`, or `STOP`.
- Image generation route used: `matpool_gpt_image_2_edit`.
- Asset type: `AI改好分镜图`.
- Updated `output/<job-id>/visual-assets/approved_visual_manifest.json` if this PASS promotes a sample image.
- Visual asset manifest QC JSON/Markdown.
- Deterministic Shot-label metadata-only evidence matching the promoted sample hash, proving zero panel-pixel changes, and carrying identical before/after panel-content fingerprints.
- GPT Image contract QC JSON/Markdown for Matpool-routed samples.
- API-effect baseline note: the artifact must say the Matpool GPT-Image-2 edit route and real local reference-image contract were used.
- Simple replacement edit note: the artifact must say the source storyboard was the edit target, product/person images were replacement references only, panel-content subtitles/old overlays were removed, and the original scene/crops/action rhythm plus Shot labels were preserved.
- Character role map when the source has multiple people.

## PASS

Return `PASS` only if:

- A real generated or edited sample image exists on disk and is listed as the sample path.
- The sample is recorded as `AI改好分镜图`, belongs to the current job output directory, and was generated/edited through `matpool_gpt_image_2_edit`.
- The artifact proves this was a Matpool image-edit/reference run, not text-only generation from paths or written descriptions.
- `tools/visual_asset_manifest_qc.py` returns `PASS` when this PASS is recorded through the runner.
- The promoted sample is the hash-matched output of the mandatory Shot-label metadata step.
- `tools/codex_imagegen_contract_qc.py` returns `PASS` and proves source storyboard/product-profile/identity refs were submitted as actual Matpool image inputs.
- Layout and shot order match the intended source Part storyboard as one complete edited Part storyboard image.
- Deterministic Shot-label evidence lists the ordered labels, and the geometry review confirms the same grid positions and panel mapping. Do not repeat manual label OCR or fail the labels as subtitles/old-text contamination.
- The source scene, camera crops, hand/action placement, and overall storyboard composition remain the source storyboard's scene. Only person, product/tool/mud, and subtitles/old overlays are changed.
- The edited storyboard canvas ratio matches the source Part storyboard ratio; landscape source storyboards must remain landscape unless an explicit vertical-adaptation plan is recorded.
- The protagonist/product-host follows the approved identity reference; secondary people keep their source role and gender and do not become the approved protagonist identity.
- Product form, label, and texture follow the target product.
- For Kongfengchun brand profiles, close product panels show the active product packaging rather than a blank/generic/invented package. The green marker alone is not enough.
- When the product profile declares visible label text, designated hero close-ups keep the major brand/product-name identity and label design. Distant, oblique, multi-bottle, and storyboard-scale microtext follows `small_or_distant_product_text=visual_match_only` and does not require character-for-character reproduction.
- Old source tube/stick/brush/arm-swatch usage is translated to the loaded product profile's target action. Only clay-mask profiles require hand/finger jar usage.
- No unknown packaging, old product, old model, subtitles, or wrong props appear.
- Any product-specific constraints in `PRODUCT_CONSTRAINTS.md` are satisfied.
- No deprecated GPT Image route was used.

A source-video frame board, rhythm board, contact sheet, or cropped source reference is not a valid generated sample, even if the artifact says it is "motion-only" or "role-limited".

## FAIL

Return `FAIL` if:

- The sample image is missing, not saved, or described only as an unpersisted Codex image-generation direction.
- The sample was made by text-only generation without actual image references submitted.
- The sample is a 9:16 single frame, standalone product/person poster, split-panel export, or externally recomposed grid instead of one AI-edited full storyboard image.
- The sample forces a landscape source storyboard into portrait/3:4 layout without explicit approval.
- The worker substitutes source-video frames, a rhythm board, or a contact sheet for the generated sample.
- The worker uses a Python/PIL composite, validated-anchor拼图, old-job storyboard image, cropped source frame, or unsaved generation claim as the sample. The only exception is the Shot-label metadata-only output defined by `codex-imagegen-direct.md`, with passing zero-panel-change evidence.
- The sample path is outside the current job output directory.
- Visual asset manifest QC is missing, `FAIL`, or `STOP`.
- Schema-v2 Shot-label evidence is missing, hash-mismatched, reports any panel-pixel change, or has mismatched panel-content fingerprints.
- GPT Image contract QC is missing, `FAIL`, or `STOP`.
- Unknown package boxes, blank jars, generic leaf-only jars, invented marks, wrong product/brand labels, old-source labels, or clearly wrong label designs appear. Storyboard-scale microtext differences alone do not satisfy this failure condition.
- A designated hero product close-up shows the wrong product/brand, wrong label design, old-source label, blank/smoothed label, or clearly wrong/missing major brand or product-name anchor. Small or distant microtext differences alone are a `VISUAL_WARNING`, not a failure.
- The model resembles the source video host more than the provided model.
- The approved protagonist identity is applied to a secondary source role, or a secondary source male role is changed into the female protagonist.
- The scene, clothing, product texture, or product action is polluted by old source-video details.
- The candidate shows a source tool/material/action that contradicts the loaded product profile; for clay-mask profiles this includes tube applicators, stick applicators, brush heads, cotton swabs, arm swatches, gray/yellow/beige mud, or an action other than finger pickup from the jar and fingertip application.
- The artifact says old product/person/mud/text remains visible but should be ignored by Seedance or constrained by a role table.
- The worker used a deprecated GPT Image route or gateway probe.
- The worker changes the Matpool route, prompt style, reference order, quality, or size in order to make a failed result pass.
- The worker uses a failed generated candidate as the next edit target after that candidate changed scene, storyboard geometry, shot order, or subject proportions.

Retry variable:

Choose exactly one:

- `identity_reference`
- `product_reference`
- `scene_prompt`
- `local_panel_repair`
- `storyboard_geometry`

Locked variables:

Approved storyboard layout, source aspect ratio, and shot order.

## STOP

Return `STOP` if:

- The sample passes hard checks and user taste review was explicitly requested for this stage.
- One retry has already failed on the same hard issue.

In `--self-audit` mode, the independent checker may return `PASS` without user taste review when the sample passes hard checks and the user did not configure this stage as a stop point.

## Next Status

On pass:

```text
image_sample_passed
```
