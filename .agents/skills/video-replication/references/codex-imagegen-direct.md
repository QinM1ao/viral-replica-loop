# Matpool GPT-Image-2 Direct Edit

This file keeps its historical name because workers and QC still reference
`codex_imagegen_contract.json`. The active GPT Image route is the project
Matpool GPT-Image-2 script:

```bash
python3 .agents/skills/video-replication/scripts/generate.py
```

Do not try any deprecated GPT Image route or gateway probe in this project.

## When The Route Is Valid

PASS this route only when all are true:

- `MATPOOL_API_KEY` is provided through the environment or a private local config.
- The source Part storyboard image is submitted as a local multipart `image` file.
- Every product/material reference declared by `output/<job-id>/product_profile.json` is submitted as a local multipart `image` file.
- The identity/model reference is submitted as a local multipart `image` file.
- After-wash reference is submitted when the Part needs post-wash proof.
- The generated result is saved as a real image file and copied into the current job output.

Local paths in text are not enough. If the route cannot submit real image files,
return `STOP` with missing image-input evidence instead of trying an older API.

## Direct Edit Steps

1. **Preflight the edit target.**
   Open the source Part storyboard and record its canvas, panel order, and every
   `Shot` label. A 12-panel source is ready only when `Shot 01-12` are readable,
   ordered, and attached to the intended panels.

2. **Bind refs before prompting.**
   Build the role list from the current product profile:

   ```text
   A source storyboard: output/<job-id>/storyboard_source_refs/source_storyboard_partX.jpg
   B product front: output/shared/.../product_front...
   C optional profile-declared product/material ref: output/shared/...
   D identity/model: output/shared/.../identity_ref...
   E optional after-wash face: output/shared/.../afterwash_face...
   ```

3. **Write the production prompt.**
   Use the `Prompt Skeleton` below. Fill every role from the current job and
   include `Hard Shot-label rule`. The prompt is ready when source scene,
   replacement roles, target product action, panel-text cleanup, and Shot-label
   preservation are all explicit.

4. **Call Matpool with local files.**
   Use repeated `-i/--image` arguments. The script submits every reference as
   multipart field name `image`.

   ```bash
   MATPOOL_API_KEY="$MATPOOL_API_KEY" \
   python3 .agents/skills/video-replication/scripts/generate.py \
     --prompt-file "<prompt.txt>" \
     --job-id "<job-id>" \
     --stage "image_batch_qc" \
     --part "part1" \
     -i "<source-storyboard.jpg>" \
     --reference-role source_storyboard \
     -i "<product-front.jpg>" \
     --reference-role product_front \
     -i "<identity-ref.jpg>" \
     --reference-role identity_ref \
     --size "<source-matched-size>" \
     --quality medium \
     --format png \
     --file "output/<job-id>/image-batch/candidates/part1_matpool.png" \
     --invocation-manifest "output/<job-id>/image-batch/invocations/part1_matpool_invocation.json" \
     --contract "output/<job-id>/image-batch/codex_imagegen_contract.json"
   ```

5. **Normalize Shot-label metadata.**
   Run the deterministic label tool on every saved Matpool candidate before
   any content inspection, compare-sheet generation, or promotion. Derive `cols` and `rows` from the source
   storyboard manifest.

   ```bash
   python3 tools/restore_storyboard_shot_labels.py \
     --input "output/<job-id>/image-batch/candidates/partX_matpool.png" \
     --output "output/<job-id>/image-batch/candidates/partX_labels_restored.png" \
     --evidence "output/<job-id>/checks/partX_shot_label_restore.json" \
     --cols "<source-cols>" \
     --rows "<source-rows>"
   ```

   If Matpool preserved only some label bars, bind a same-canvas approved
   storyboard as the metadata template instead of guessing from panel pixels:

   ```bash
   python3 tools/restore_storyboard_shot_labels.py \
     --input "output/<job-id>/image-batch/candidates/partX_matpool.png" \
     --output "output/<job-id>/image-batch/candidates/partX_labels_restored.png" \
     --evidence "output/<job-id>/checks/partX_shot_label_restore.json" \
     --label-template "output/<job-id>/final-images/partX_previous_approved.png" \
     --cols "<source-cols>" \
     --rows "<source-rows>"
   ```

   The template must have the same canvas size. Candidate-detected bars keep
   their candidate positions; the template supplies only missing metadata
   regions. The evidence records each band's source and still requires zero
   changes outside the resolved label regions.

   This is the only allowed deterministic image postprocess. It redraws the
   existing Shot-label bars and changes zero panel pixels; it does not assemble,
   crop, replace, or repair storyboard content. A Shot-number-only defect takes
   this branch and does not call Matpool again. The evidence includes an identical
   before/after panel-content fingerprint. When it passes, the checker validates
   the evidence instead of manually OCR-reading all 12 labels, and label normalization
   must not trigger a second geometry, continuity, skincare, identity, or product
   review. If label bars cannot be detected
   or the zero-panel-change evidence fails, return `FAIL` with retry variable
   `storyboard_geometry`.

   Register the normalized image in visual manifest schema v2:

   ```json
   {
     "shot_label_metadata": {
       "type": "shot_label_metadata_only",
       "evidence": "output/<job-id>/checks/partX_shot_label_restore.json",
       "panel_pixels_modified": false
     }
   }
   ```

6. **Save, inspect once, then promote.**
   The script writes the invocation manifest and updates `codex_imagegen_contract.json`
   with the prompt, refs, hashes, route, quality, size, output path, and elapsed time.
   Inspect the normalized candidate against the source. Set
   `shot_labels_preserved=true` from passing deterministic label evidence plus
   the source-matched grid/geometry check. Promote by candidate hash only
   after contract, geometry, visual-manifest, and stage gates pass.

### Completion criterion

The GPT Image step is complete only when every required Part has:

- one saved, current-job AI-edited storyboard image;
- a `PASS` Matpool invocation with real local reference images;
- a schema-v2 visual manifest entry whose Shot-label evidence is `PASS`, lists
  the expected labels in order, matches the promoted image hash, records
  `outside_label_changed_pixels=0`, records `panel_pixels_modified=false`, and
  has identical before/after panel-content fingerprints;
- `shot_labels` in `source_storyboard_controls`;
- `shot_labels_preserved=true` in `storyboard_geometry_review.json` after visual inspection;
- deterministic `Shot 01-12` in source order on the source-matched grid; and
- passing GPT Image contract, storyboard geometry, and visual asset manifest QC.

## Contract Fields

Use these route fields:

```json
{
  "image_route": "matpool_gpt_image_2_edit",
  "api_effect_baseline": {
    "source": "matpool_gpt_image_2_edit",
    "preserve_api_route": true
  },
  "matpool_uses_real_image_inputs": true,
  "reference_order": [
    "source_storyboard",
    "product_front",
    "identity_ref"
  ]
}
```

Insert any additional product/material roles declared by the current product
profile between `product_front` and `identity_ref`.

The contract must also state:

- source storyboard transfers only `layout`, `shot_order`, `framing`, `action_rhythm`, `scene_family`, and the existing `shot_labels`
- product and identity references are replacement references only; they must not transfer background, room, lighting, crop edges, packshot/selfie staging, or scene composition
- source storyboard must not transfer `old_product`, `old_tool`, `old_host_identity`, `old_person_clothing`, `old_mud_color`, or panel-content `subtitles`; existing storyboard `Shot 01-12` labels are preserved
- every submitted reference path exists and has a recorded hash
- the saved candidate path exists and is a current-job AI-edited storyboard image

## Prompt Skeleton

Before writing the current prompt, open the validated rolemap prompt sample:

```text
output/job-001/image-batch/prompts/part1_label_rolemap_repair_prompt.md
```

Use it as a structure sample only. Do not copy its product, toner, restaurant,
office, restroom, or label content into another job. The reusable structure is:

- `Reference roles`
- `Hard role map`
- `Hard source-scene rule`
- `Hard Shot-label rule`
- `Task`
- `Do not`

For every current job, fill that skeleton from the current source storyboard,
product profile, role map, and active references. The prompt is not ready to
submit if it lacks a hard source-scene rule that names the source scene family
and explicitly blocks product-reference or identity-reference background
transfer.

```text
Edit Image A into one complete 12-panel storyboard image.

Reference roles:
- Image A controls only the panel layout, shot order, camera framing, hand/action placement, scene family, and source rhythm.
- Image A must not transfer the old person identity, old person clothing, old product, old tool, old mud color, subtitles, captions, or overlays.
- Image B controls the target product front: [product shape, label, marker].
- Image B must not transfer its photo background, studio lighting, crop edges, packshot staging, or scene composition.
- When the product profile requires Image C, it controls only the declared open-product/material state and must not transfer its photo background, crop, lighting, or staging.
- Image D controls the target model's face, hair, body impression, skin tone, age feel, and clothing. Default is complete person replacement, not face-only.
- Image D must not transfer the model-reference room, background, lighting, camera angle, or selfie composition.
- Image E controls only post-wash skin state after wash/wipe proof. Do not apply E to opening or pre-wash panels.

Hard Shot-label rule:
- Preserve every source black Shot-label bar and the cyan labels `Shot 01` through `Shot 12` in their original positions.
- Keep each label attached to the same panel. Do not delete, rewrite, renumber, reorder, translate, restyle, or move the labels.
- Shot labels are storyboard navigation metadata, not subtitles or panel contamination.
- Remove unwanted text only from inside each panel's video-image area. Do not remove the Shot-label bars beneath the panels.

Task:
Keep the same source storyboard structure, panel count, panel order, camera crops, source scene, source room/background, scene transitions, action rhythm, and existing Shot label system. Preserve every source `Shot 01-12` label in the same panel position and keep its panel correspondence unchanged.
Replace the old person completely with the target model from Image D, including the model clothing.
Replace all old product/tool/material appearances with the target product refs declared by the current product profile.
Translate source actions into the current profile's real product action; clay-mask profiles use finger pickup from the open jar and fingertip face application.
Remove subtitles, dialogue captions, stickers, watermarks, and old text overlays inside panels. Do not remove or rewrite the storyboard Shot labels.

Hard source-scene rule:
- Preserve the current source scene family and concrete source room/background cues from Image A.
- Do not use the model-reference room, product-reference studio background, packshot staging, selfie staging, lighting, table, wall, shelf, cup, window, or crop as the generated scene.
```

## Completion Gate

Run the stage-required QC after the candidate and visual manifest exist:

```bash
python3 tools/codex_imagegen_contract_qc.py --root . --job-id <job-id> --stage <stage>
python3 tools/visual_asset_manifest_qc.py --job-id <job-id> --stage <stage>
python3 tools/storyboard_geometry_qc.py --job-id <job-id> --stage <stage>
```

Before storyboard geometry QC, the checker must inspect the source and candidate
side by side and write `shot_labels_preserved=true` only after reading every
Shot label in order and confirming the same panel mapping.

An explicit `image_sample` stop still needs saved image evidence, contract QC,
visual asset manifest QC, and the same Shot-label visual review. Production
promotion additionally requires storyboard geometry QC.

## Validated evidence

The real `0/12 -> 12/12` Matpool comparison, fixed inputs, invocation record,
candidate hash, and limits of the check are recorded in:

```text
docs/validated-gpt-image-shot-label-retention.md
```
