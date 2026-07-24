# Image Batch Worker

## Canonical Stage

`image_batch_qc`

## Purpose

Generate or repair all required storyboard images immediately after storyboard PASS.

The default batch image task is a simple source-storyboard replacement edit, not a creative regeneration task. For each Part, preserve the original source scene, camera crops, panel grid, hand/action placement, shot order, and existing `Shot 01-12` labels; replace only old person, old product/tool/mud, and old subtitles/overlays inside panels. Shot labels are storyboard navigation metadata, not subtitle contamination. Do not run a separate image sample first unless the job explicitly asks for a sample stop; a 45s job should edit Part1, Part2, and Part3 together in this stage through Part-level fanout when possible.

For multi-Part jobs, the default execution shape is:

1. Write `output/<job-id>/image-batch/part_execution_specs.json` with every required Part exactly once. Each entry must name its approved `prompt_path`, ordered existing local `references` (`role` plus `path`), and explicit `depends_on`; do not guess missing references.
2. Run `tools/image_batch_fanout.py plan`. Missing, incomplete, or unreadable execution specs are `STOP`, so the default worker cannot emit a non-executable plan.
3. Generate each Part with an isolated `--contract output/<job-id>/image-batch/contracts/partX_contract.json` and an isolated invocation manifest.
4. Dispatch only the plan's sealed `stage_execution` packets to bounded sub-agents (or the local command dispatcher); each packet may execute only its declared Matpool command and write only its candidate, contract, invocation, log, and completion paths. For `storyboard_derived`, dispatch only the dependency-ready wave.
5. Run `tools/image_batch_fanout.py merge` once all required Part contracts exist.
6. Run the normal shared QC against the merged `output/<job-id>/image-batch/codex_imagegen_contract.json`.

Never let concurrent Part tasks write the shared `codex_imagegen_contract.json` directly. Shared contract merge, checker review, QC scripts, `jobs.csv`, `RUNNER_STATE.json`, and `STATE.md` writes stay serialized.

After deterministic image contracts and the approved visual manifest are ready, run `python3 tools/qc_risk_ledger.py --root . --job-id <job-id> --stage image_batch_qc`. It calls `tools/storyboard_visual_acceptance.py`, the sole semantic image interface. If deterministic preflight fails, stop without a checker. If it emits `image_batch_qc_semantic_review_request.json`, invoke the independent checker exactly once against the canonical overview and its bound original artifacts; the response must name every requested family separately. Do not run separate geometry, cross-Part, or skincare checker passes.

Default person replacement is complete appearance replacement. Use the person/model reference for face, hair, body, and clothing. Keep source-video clothing only when the user explicitly says this is a face-only swap or asks to preserve source wardrobe.

For multi-person source stories, first write a role map from the story analysis. The approved identity applies only to the source-defined protagonist/product-host role. Secondary people must preserve their story role and gender, can be replaced or de-identified as generic context identities, and must not be turned into the approved protagonist identity.

When intake uses `person_assets=storyboard_derived`, read `.agents/skills/video-replication/references/storyboard-derived-identities.md` before planning ImageGen. This branch has an intentional dependency: edit the first source Part with product refs but no person ref, approve that storyboard, derive photoreal identity images for speaking/close-up/recurring roles, then pass recurring identities into later-Part storyboard edits. Only Parts with no unresolved cross-Part identity dependency may fan out in parallel.

## Inputs

- Passed storyboard and contamination audit.
- Source Part storyboard images for every target Part.
- Product assets.
- `output/<job-id>/product_profile.json`.
- Person/model assets, or the explicit `storyboard_derived` mode when the user supplied none.
- `PRODUCT_CONSTRAINTS.md`.
- `QC_RULES.md`.
- `gates/image_batch_gate.md`.
- Golden rolemap prompt sample: `output/job-001/image-batch/prompts/part1_label_rolemap_repair_prompt.md` as structure only.

## Actions

Before calling GPT Image, read and follow `.agents/skills/video-replication/references/codex-imagegen-direct.md`. An image attempt is valid only when the project Matpool GPT-Image-2 route submits actual local image files and the generated image is saved into the current job output.

Before writing each Matpool prompt, open the golden rolemap prompt sample listed in `codex-imagegen-direct.md`. Copy only its structure, not its product or scene content. The current prompt must include explicit `Reference roles`, role mapping when people appear, a hard source-scene rule, task bullets, and rejection bullets. It must state that source storyboard controls scene family, room/background cues, camera crops, hand/body placement, shot order, and action rhythm; product, identity, and after-wash refs must not transfer their own room/background/lighting/staging.

For `storyboard_derived`, write `visual-assets/role_map.json` before the first call. The first edit for a role submits the source storyboard plus product refs and asks GPT Image to replace every old person with a new photoreal person of the same role and gender; it does not invent one universal protagonist. After that Part passes, generate a dedicated single-person upper-body identity image for each `identity_required` role from the approved current-job storyboard. Record its provenance and reuse that identity for every later Part containing the same role. Never crop an old/source face and never derive from a failed storyboard.

Record the actual reference contract precisely. The first no-person edit uses `person_asset_mode=storyboard_derived`, `identity_strategy=generate_from_source_roles_then_derive`, a real loaded `role_map`, and no fake `identity_ref`. A later edit that receives derived identities uses `identity_strategy=reuse_storyboard_derived_roles` and records every submitted `identity_role_*` in both `refs_loaded` and `reference_order`.

1. Build a reference manifest for each generated image.
   - For multi-Part fanout, build per-Part contracts under `output/<job-id>/image-batch/contracts/partX_contract.json` before generation or repair, then merge them into `output/<job-id>/image-batch/codex_imagegen_contract.json` after all required Part commands finish.
   - For a single-Part job or a targeted local repair, the same per-Part contract path is still preferred; the shared `codex_imagegen_contract.json` is only a merged QC artifact.
   - Treat this as a Matpool GPT-Image-2 edit request: each Part must submit a source storyboard image plus product profile-declared product/material refs and, when available for that role, identity and profile-required after-wash references as multipart `image` files. The first `storyboard_derived` appearance is the explicit exception to the identity-input requirement.
   - Match the Matpool edit effect for the current source storyboard: keep the source Part storyboard canvas, panel sizing, panel positions, and shot order. Portrait sources commonly use 4 columns x 3 rows; landscape sources should use 3 columns x 4 rows. A result that re-composes a new 12-panel template, changes panel sizes, adds a different border/label system, or squeezes the person is a failure even if product, clothing, and mud color look acceptable.
   - Record `api_effect_baseline.source=matpool_gpt_image_2_edit`, `preserve_api_route=true`, `matpool_uses_real_image_inputs=true`, and the Matpool quality/size target in the contract.
   - The contract must say what the source storyboard is allowed to transfer (`layout`, `shot_order`, `framing`, `action_rhythm`, `scene_family`, `shot_labels`) and what it cannot transfer (`old_product`, `old_tool`, `old_host_identity`, `old_person_clothing`, `old_mud_color`, panel-content `subtitles`).
   - Translate any old source tube/stick/brush/arm-swatch beat into the current product profile's real usage action. Only clay-mask profiles translate that action to finger pickup from the open jar and fingertip face application. The ImageGen prompt should be positive and target-scene-only; do not use old tool words as negative anchors.
2. Generate only the required image set for the current job stage.
   - The required image set is all target Parts for the job, not one sample Part. Use the target duration and storyboard manifest to decide the count: 30s normally means Part1 and Part2; 45s normally means Part1, Part2, and Part3.
   - Build prompts, refs manifests, and invocation evidence for every Part before recording PASS for the stage.
   - Do not stop for client/sample review between Parts in the default loop. If one Part fails, keep passed Part outputs locked and repair only the failed Part or failed panel.
   - Use `.agents/skills/video-replication/scripts/generate.py` as the only GPT Image route.
   - For each Part, edit the full source Part storyboard image directly with local image references submitted to Matpool: source storyboard, active product profile-declared product refs, active identity refs for roles already derived, and after-wash ref only when the product profile requires it.
   - Treat the source Part storyboard as the edit target. Treat product/person/after-wash images as replacement references only. Do not use a generated candidate as the next edit target unless it already preserves the source scene, source geometry, shot order, and unsqueezed subject proportions.
   - If Part1 is failing source-storyboard geometry, subject proportions, scene fidelity, or identity/product replacement, do not use Part1 as a continuity reference for Part2. Rebuild Part1 from the source storyboard first.
   - Use this reference order: source storyboard first, active product refs next, active identity ref next, after-wash ref only when needed.
   - Output for each Part must be one complete edited storyboard image with the same panel layout, shot order, Shot labels, and canvas ratio as that Part's source storyboard. Preserve each Shot number in the same location and keep its original panel correspondence. The `job-001`/`job-002` 4-column x 3-row, about 3:4 format is a portrait-source precedent, not a universal rule. Do not output 9:16 single frames, product posters, split-panel files, or a recomposed grid assembled outside image gen.
   - For landscape source storyboards, keep the edited storyboard landscape unless the user explicitly approved a vertical adaptation.
   - Source storyboard controls layout, shot order, camera framing, action rhythm, and scene family; it must not control old product, old face, subtitles, gray/yellow mud, old tools, or old-person clothing.
   - Product refs control the current product's real package, label, visible label text, form, material, and usage action as declared by the product profile. Product refs must not transfer their photo background, studio lighting, crop edges, packshot staging, or scene composition. When the product profile declares `visible_text_patterns`, designated hero close-ups preserve the major brand/product-name identity and label design. Distant, oblique, multi-bottle, and storyboard-scale microtext only needs the same overall color, line layout, and brand impression; character-for-character mismatch alone is a visual warning, not a repair trigger. Blank/smoothed labels, wrong product/brand, old-source labels, wrong label design, or clearly wrong/missing major hero-label anchors remain failures. Clay-mask profiles additionally lock the jar, open white thick paste, and fingertip application. Identity/model refs control only the target person's face, hair, age feel, identity consistency, body impression, and clothing; they must not transfer the model-reference room, background, lighting, camera angle, or selfie composition.
   - Do not try any deprecated GPT Image route or gateway probe.
   - After every saved Matpool candidate, run `Deterministic Shot-label normalization` from `codex-imagegen-direct.md` before review or promotion. The normalized candidate becomes the only promotable path; a Shot-number-only defect takes this branch without another Matpool call.
   - For a localized failure, use fast repair instead of regenerating the full Part.
3. Save prompt, refs manifest, invocation evidence, candidate image, and QC output for every attempt.
   - For `matpool_gpt_image_2_edit`, record that image inputs were actually submitted, plus each reference role, path, and hash when available.
   - Text-only generation, unsaved previews, or images generated without the storyboard/product/person refs cannot be promoted.
   - For each promoted Part, update that Part's isolated contract with candidate path, prompt path/text, actual refs loaded, source-risk translations, and an explicit checker visual checklist. After fanout, merge isolated contracts before running shared contract QC.
4. Treat promoted Part images as `AI改好分镜图` only when they are real current-job generated/edited target storyboard images. The only permitted deterministic postprocess is the Shot-label metadata-only branch defined by `codex-imagegen-direct.md`, with zero-panel-change evidence. Never promote other Python/PIL composites, source rhythm boards, contact sheets, cropped source frames, validated-anchor拼图, old-job storyboards, or unsaved image directions.
5. Run hard checks for layout, identity, product, scene, color, and contamination.
   - Confirm the Shot-label metadata evidence passes and the source-matched grid is unchanged. Do not manually OCR all 12 labels after deterministic normalization, and do not fail them as subtitles or old-text contamination.
   - Layout checks must compare against the source Part storyboard ratio, not a hard-coded 3:4 ratio.
   - For profiles that load `category:clay_mask` or `sku:kongfengchun_clean_mud_mask`, reject yellow, beige, tan, cream-yellow, gray, watery, or source-contaminated mud.
   - Face-applied mud and open-jar mud must both match the product reference as white/milky-white thick paste before promotion.
   - Color thresholds are not enough for mud-mask jobs. The checker must visually confirm raised, opaque, thick clay-paste body with ridges/edges/peaks; thin lotion-like or foundation-like white smears fail even when white/cool-white metrics pass.
   - Reject blank jars, generic leaf-only jars, invented flower logos, fake package boxes, and labels that do not visually read as the active Kongfengchun product in product-close panels.
   - For products with visible label text, reject the wrong product/brand, blank or smoothed labels, old-source labels, clearly wrong label design, or a designated hero close-up with a missing/incorrect major brand or product-name anchor. Distant, oblique, multi-bottle, and storyboard-scale microtext differences remain `VISUAL_WARNING`, not a rejection trigger.
   - For multi-person source stories, reject any candidate that applies the approved protagonist identity to a secondary role, changes a source male support role into the female protagonist, or loses the required role/gender map.
   - For multi-Part jobs, inspect Part images side by side as one future stitched video. Part1 and Part2 must keep the same primary identity, approved model outfit family, same scene family, compatible lighting/skin, and same product/mud style unless the source story explicitly changes outfit or scene.
   - When the product profile declares `requires_skincare_progression=true`, inspect the before/after skin progression. Pre-wash panels should still show the use-case problem or normal skin state; after-wash brightness/cleanliness must appear only after wash/wipe proof. Do not let the after-wash face reference contaminate opening or pre-wash panels.
6. Promote only passed images into `output/<job-id>/final-images/`.
7. Update `output/<job-id>/visual-assets/approved_visual_manifest.json` as schema v2 with the normalized current-job Part images, required Shot-label evidence, and product/identity binding groups.
   - Record `source_presenter_gender` from the current job role map and `target_presenter_gender` from the approved identity.
   - Require the identity-group manifest to declare `presenter_gender`; all three values must be `male` or `female` and identical. Do not replace a male source presenter with a female identity or vice versa.
   - For `storyboard_derived`, record `person_asset_mode`, `role_map`, `identity_role_manifests`, `part_identity_roles`, and per-Part `part_reusable_refs`. Each identity manifest must bind its role, gender, current job, source Part, approved source storyboard, and generated identity image.
8. Run `tools/visual_asset_manifest_qc.py --stage image_batch_qc` before recording PASS.
9. Run `tools/codex_imagegen_contract_qc.py --stage image_batch_qc` before recording PASS.
10. Build the one-pass ledger. Its deterministic preflight proves file readability, input binding, canvas/aspect, grid, panel count, Shot metadata/order, manifest binding, and GPT Image contract before any semantic request exists. The one checker response then records explicit results for geometry/appearance, identity/product/material integrity, cross-Part continuity, and profile-required skincare progression.
11. If the failure is only incorrect Shot navigation text, run the deterministic Shot-label branch and skip image generation. For a local panel-content failure inside an otherwise source-faithful storyboard, such as one product close-up, one mud color issue, or one removed product label, prefer local panel repair over full regeneration.
12. If the failure changes scene, storyboard geometry, shot order, subject proportions, or uses a failed Part as continuity input, discard the candidate and restart from the source Part storyboard. Do not loop on cosmetic repairs.
13. After a panel-content repair, sync the final image to all active downstream locations and rerun only the affected family. After a Shot-label-only normalization, sync the normalized file and evidence, run visual asset manifest QC, and reuse every unchanged semantic family.
14. Once the active final image hashes have PASS evidence, downstream stages should cite the unified family PASS evidence instead of reopening image repair. Only rerun image QC or image generation if an active image hash, manifest mapping, material role, prompt reference role, or user-visible defect changed.

## Scripted Part

Use `tools/image_hard_gate_qc.py` where applicable.

Create the fanout plan before multi-Part image generation:

```bash
python3 viral-replica-loop/tools/image_batch_fanout.py \
  --root viral-replica-loop \
  --job-id <job-id> \
  plan
```

When calling Matpool for each Part, add the plan's isolated evidence flags:

```bash
--part partX \
--contract viral-replica-loop/output/<job-id>/image-batch/contracts/partX_contract.json \
--invocation-manifest viral-replica-loop/output/<job-id>/image-batch/invocations/partX_matpool_invocation.json
```

After every required Part contract exists, merge serialized evidence:

```bash
python3 viral-replica-loop/tools/image_batch_fanout.py \
  --root viral-replica-loop \
  --job-id <job-id> \
  merge
```

Run this contract QC after candidates and the approved visual manifest exist:

```bash
python3 viral-replica-loop/tools/codex_imagegen_contract_qc.py \
  --root viral-replica-loop \
  --job-id <job-id> \
  --stage image_batch_qc \
  --contract viral-replica-loop/output/<job-id>/image-batch/codex_imagegen_contract.json
```

Build the single visual decision after the deterministic contracts pass:

```bash
python3 viral-replica-loop/tools/qc_risk_ledger.py \
  --root viral-replica-loop \
  --job-id <job-id> \
  --stage image_batch_qc
```

## Outputs

Write under `output/<job-id>/image-batch/`:

- prompts
- refs manifests
- `fanout/fanout_plan.json`
- `fanout/fanout_merge_report.json`
- `contracts/partX_contract.json` for every required Part in multi-Part jobs
- `codex_imagegen_contract.json`
- image generation invocation manifests or equivalent invocation evidence
- candidate images
- `checks/partX_shot_label_restore.json` for every promoted Part
- QC JSON or markdown
- failed/pass notes

Promote final passed images to:

- `output/<job-id>/final-images/`
- `output/<job-id>/visual-assets/approved_visual_manifest.json`
- `output/<job-id>/checks/image_batch_qc_visual_asset_manifest_qc.json`
- `output/<job-id>/checks/image_batch_qc_visual_asset_manifest_qc.md`
- `output/<job-id>/checks/image_batch_qc_codex_imagegen_contract_qc.json`
- `output/<job-id>/checks/image_batch_qc_codex_imagegen_contract_qc.md`
- `output/<job-id>/checks/storyboard_visual_acceptance_compare.jpg`
- `output/<job-id>/checks/image_batch_qc_storyboard_visual_acceptance.json`
- `output/<job-id>/checks/image_batch_qc_semantic_review_request.json` only when a family changed
- `output/<job-id>/checks/image_batch_qc_gate_review_qc.json`
- `output/<job-id>/checks/image_batch_qc_qc_risk_ledger.json`

## Gate

Run:

`gates/image_batch_gate.md`

## PASS Next Status

`image_qc_passed`

## FAIL Retry Variables

Choose exactly one:

- `identity_reference`
- `product_reference`
- `scene_prompt`
- `color_anchor`
- `cross_part_continuity`
- `skin_progression`
- `local_panel_repair`
- `mud_thickness`
- `geometry_appearance`

## Stop Conditions

- Same failure repeats twice.
- A candidate has been recomposed, scene-changed, or visually squeezed and a fresh source-storyboard edit route is not available.
- Client review is required.
- Repair would require changing an already approved variable.
