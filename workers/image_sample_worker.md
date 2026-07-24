# Image Sample Worker

## Canonical Stage

`image_sample`

## Purpose

Generate one image sample and run hard checks before any batch image work.

The default image task is a minimal replacement edit of the source storyboard: keep the source scene, storyboard sheet, and existing Shot labels intact; replace the old person with the approved identity, replace the old product/tool/material with the current product profile's product refs and usage action, and remove panel-content subtitles or old overlays. Shot labels are preserved as storyboard navigation metadata. Do not reinterpret this as a new beauty ad, poster, bathroom scene, product mockup, or recomposed storyboard.

## Inputs

- Passed storyboard.
- Contamination audit.
- Product assets.
- `output/<job-id>/product_profile.json`.
- Single approved identity reference.
- `PRODUCT_CONSTRAINTS.md`.
- `QC_RULES.md`.

## Actions

Before calling GPT Image, read and follow `.agents/skills/video-replication/references/codex-imagegen-direct.md`. A sample is valid only when the project Matpool GPT-Image-2 route submits actual local image files and the generated image is saved into the current job output.

1. Build a reference manifest before generation.
   - Also build `output/<job-id>/改图小样/codex_imagegen_contract.json` before calling image generation.
   - This contract records the Matpool GPT-Image-2 edit call. It must state that the source storyboard controls layout, shot order, framing, action rhythm, scene family, and `shot_labels`, and must not control old product, old tool, old host identity, old mud color, or panel-content subtitles.
   - Record `api_effect_baseline.source=matpool_gpt_image_2_edit`, `preserve_api_route=true`, `matpool_uses_real_image_inputs=true`, and the Matpool quality/size target in the contract.
   - Translate any old source tube/stick/brush/arm-swatch action into the target action declared by the product profile. Only clay-mask profiles use finger pickup from the open jar and fingertip face application. Do not put old tool words into the generation prompt as negative anchors.
2. Generate one sample only.
   - Use `.agents/skills/video-replication/scripts/generate.py` as the only GPT Image route.
   - The Matpool route must edit the full source storyboard image directly. Submit the actual source storyboard image, product profile-declared product/material images, and approved identity image as multipart `image` files; mentioning local paths in text is not enough.
   - The source storyboard is the edit target. Product and identity images are replacement references only; do not use an older generated candidate as the edit target unless it has already passed source-storyboard geometry and visual review.
   - If the generated sample changes the original scene, panel geometry, camera crop, hand/action placement, or visually squeezes the person, discard it and restart from the source storyboard. Do not keep repairing that failed candidate.
   - Use this reference order: source storyboard first, active product refs next, active identity ref next, after-wash ref only when needed.
   - Output must be one complete edited Part storyboard image with the same panel layout, shot order, Shot labels, and canvas ratio as the source Part storyboard. Keep every Shot number in its original label position and mapped to the same panel. The `job-001`/`job-002` 4-column x 3-row, about 3:4 pattern applies only when the source Part storyboard uses that portrait layout.
   - For landscape source storyboards, keep the edited storyboard landscape; do not force it into 9:16 or 3:4. Do not generate a 9:16 single frame, product poster, hero image, split-panel set, or Python/PIL recomposite.
   - Source storyboard controls only layout, shot order, framing, and action rhythm. Product refs control the current product's real package, label layout, material, and usage action. Identity ref controls only the target person.
   - Do not try any deprecated GPT Image route or gateway probe.
   - Run `Deterministic Shot-label normalization` from `codex-imagegen-direct.md` on the saved candidate before review. A Shot-number-only defect uses this branch without another Matpool call.
   - Record the image route in the review artifact.
3. Save prompt, reference manifest, invocation evidence, and output image.
   - For `matpool_gpt_image_2_edit`, record that image inputs were actually submitted, plus each reference role, path, and hash when available.
   - If Matpool produces no saved image or a text-only result from paths, the stage is missing evidence and must not pass.
   - The saved contract must include the source storyboard path, product profile-declared product ref paths, identity path, prompt path/text, candidate path, route `matpool_gpt_image_2_edit`, and a visual-review checklist for the actual saved candidate.
4. Record the normalized output as asset type `AI改好分镜图` only if it is a real current-job generated/edited target storyboard image. The sole deterministic exception is the Shot-label metadata-only branch with zero-panel-change evidence. Do not record other Python/PIL composites, source rhythm boards, contact sheets, cropped source frames, validated-anchor拼图, old-job storyboards, or unsaved image directions.
5. Run hard checks:
   - layout
   - Shot labels preserved and still mapped to the same panels
   - single identity
   - product label/form
   - product texture
   - scene and wardrobe
   - old-source contamination
6. Update `output/<job-id>/visual-assets/approved_visual_manifest.json` as schema v2 with required Shot-label evidence when the sample is promoted.
7. Run `tools/visual_asset_manifest_qc.py` for the stage before any PASS is recorded.
8. Run `tools/codex_imagegen_contract_qc.py` for the stage before any PASS is recorded.
9. If hard checks pass, stop for user visual review when needed. Shot-label completion comes from the passing deterministic evidence plus unchanged grid/panel mapping; do not spend a second review manually reading all 12 labels.

## Scripted Part

Use this script for hard image checks:

```bash
python3 viral-replica-loop/tools/image_hard_gate_qc.py \
  --candidate "<candidate-image>" \
  --expected-ratio-from-image "<source-storyboard-part-image>" \
  --part1-anchor "<approved-part1-image>" \
  --refs "<approved-identity-ref>" \
  --required-ref-name "<identity-file-name>" \
  --out-json viral-replica-loop/output/<job-id>/改图小样/image_hard_gate.json \
  --out-md viral-replica-loop/output/<job-id>/改图小样/image_hard_gate.md
```

The script checks layout, banned refs, required identity ref, product marker, and optional skin-color consistency. When the product profile loads clay-mask rules, it also checks white/gray/yellow mud metrics and cool-white mud presence. A script pass is not enough when the product is blank/generic/invented or when a clay-mask profile's mud still looks yellow by visual inspection; the reviewer must fail it and return to image edit/repair.

Run this contract QC after the candidate and visual manifest exist:

```bash
python3 viral-replica-loop/tools/codex_imagegen_contract_qc.py \
  --root viral-replica-loop \
  --job-id <job-id> \
  --stage image_sample \
  --contract viral-replica-loop/output/<job-id>/改图小样/codex_imagegen_contract.json
```

## Outputs

Write under `output/<job-id>/改图小样/`:

- `sample_prompt.md`
- `sample_refs_manifest.json`
- `codex_imagegen_contract.json`
- `imagegen_invocation_manifest.json` or equivalent invocation evidence
- sample image
- `output/<job-id>/checks/sample_shot_label_restore.json`
- `sample_review.md`
- `output/<job-id>/visual-assets/approved_visual_manifest.json` when promoted
- `output/<job-id>/checks/image_sample_visual_asset_manifest_qc.json`
- `output/<job-id>/checks/image_sample_visual_asset_manifest_qc.md`
- `output/<job-id>/checks/image_sample_codex_imagegen_contract_qc.json`
- `output/<job-id>/checks/image_sample_codex_imagegen_contract_qc.md`

## Gate

Run:

`gates/image_sample_review_gate.md`

## PASS Next Status

`sample_image_waiting_review`

## FAIL Retry Variables

Choose exactly one:

- `identity_reference`
- `product_reference`
- `scene_prompt`
- `local_panel_repair`
- `storyboard_geometry`

## Stop Conditions

- Image sample passes hard checks and needs user review.
- One retry fails on the same hard issue.
