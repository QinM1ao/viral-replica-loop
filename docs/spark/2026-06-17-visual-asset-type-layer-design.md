# Visual Asset Type Layer Design

Date: 2026-06-17
Project: `viral-replica-loop`
Scope: Add a visual asset type layer to stop future loop runs from confusing analysis images, reusable references, generated storyboard images, and final Seedance upload assets.

## Problem

The current loop can be derailed when an agent invents substitute visual assets during `image_sample` or `image_batch`.

The specific failure pattern:

- Source-video frame boards or rhythm references were treated as final Seedance upload images.
- Python/PIL-composited images were treated as image-generation outputs.
- Validated images from an old job were reused as if they were the current job's storyboard result.
- Text such as "motion-only", "ignore old product", or "material-role table will constrain it" was used to justify passing contaminated or non-generated images.

This breaks the core rule: the image stage must output the already-correct target storyboard images that Seedance can directly use.

## Goals

- Make visual asset types explicit and machine-checkable.
- Allow useful reusable assets, such as cropped product images and model-bound after-wash face references.
- Forbid analysis images, source-video boards, Python/PIL composites, or old-job anchors from becoming active image-stage outputs.
- Require `image_sample` and `image_batch` to produce AI-generated or AI-edited target storyboard images.
- Prevent `run-loop.sh --record-gate-result PASS` from advancing when required visual asset QC has failed.
- Keep self-audit mode, but make the checker inspect asset type manifests and real image paths.

## Non-Goals

- This design does not implement image generation.
- This design does not change the story analysis or storyboard method.
- This design does not allow local script-composited images to become image-stage outputs.
- This design does not approve paid/API Seedance generation.

## Asset Types

### 1. Analysis Evidence Image

Chinese label: `分析证据图`

Allowed locations:

- `output/<job-id>/story-analysis/`
- `output/<job-id>/剧情分析/`
- `output/<job-id>/分镜/`
- `output/<job-id>/storyboard_source_refs/`

Purpose:

- Understand source rhythm, subtitles, shot order, visual proof, and contamination risks.

Forbidden locations:

- `output/<job-id>/改图小样/`
- `output/<job-id>/image-batch/`
- `output/<job-id>/final-images/`
- `output/<job-id>/seedance/seedance_refs/`
- `output/<job-id>/seedance_web_final/`

Rule:

- If an analysis evidence image enters an image-stage, final, Seedance reference, or web handoff directory, the gate must return `FAIL`.

### 2. Reusable Reference Image

Chinese label: `可复用参考图`

Purpose:

- Stable references that can be reused across jobs only when their binding group matches the active job.

Examples:

- Product front crop.
- Product open white-mud crop.
- Active model identity image.
- After-wash face close-up bound to that exact model identity.

Rule:

- Reusable references may be uploaded as Seedance support images, such as product front, open mud, identity, or after-wash skin.
- Reusable references must not pretend to be the current job's storyboard image.
- Product references are product-group bound.
- After-wash references are identity-group bound.

### 3. AI-Corrected Storyboard Image

Chinese label: `AI改好分镜图`

Purpose:

- The only valid output of `image_sample` and `image_batch`.
- This is the image that Seedance can directly use as the current job's storyboard/reference image.

Requirements:

- Generated or edited through `matpool_gpt_image_2_edit`.
- Saved on disk.
- Belongs to the current job.
- Preserves the current source video's shot rhythm and sales function.
- Replaces source people with the approved identity.
- Replaces source product with the active product.
- Removes old source product, old source person, subtitles, watermarks, old mud, old props, and source-frame contamination.
- For `孔凤春清洁泥膜`, face-applied and open-jar mud must be white or milky-white thick paste.

Forbidden substitutes:

- Python/PIL composites.
- Source-video frame boards.
- Contact sheets.
- Cropped source frames.
- Old job storyboard images.
- Validated anchors pasted or assembled into a new job result.
- Unsaved "Codex generated a direction" claims.

Rule:

- If this image does not exist, the image stage must `FAIL` or `STOP`.
- If the image is not a real AI-generated or AI-edited target storyboard image, the image stage must `FAIL`.

### 4. Final Upload Image

Chinese label: `最终上传图`

Purpose:

- Files collected under `seedance_web_final/` for browser-side Seedance handoff.

Allowed source mapping:

- `01_图片1`: current job `AI改好分镜图`.
- `02_图片2`: active product group front reference.
- `03_图片3`: active product group open white-mud reference.
- `04_图片4`: active identity group identity reference.
- `05_图片5`: active identity group after-wash face reference.
- `06_音频1`: current job audio reference, `<=15.00s`, target `14.90s`.

Rule:

- `seedance_web_final/` must be built only from approved manifest entries.
- Deprecated files, drafts, analysis evidence, script composites, source frames, and wrong binding-group assets must fail request QC.

## Shared Asset Groups

Reusable assets are organized by binding group, not as loose files.

### Identity Group

Example:

```text
output/shared/kongfengchun/identities/kongfengchun_male_content4/
  identity_ref.png
  afterwash_face_closeup.png
  manifest.json
```

Manifest shape:

```json
{
  "asset_group_type": "identity_group",
  "identity_id": "kongfengchun_male_content4",
  "identity_ref": "identity_ref.png",
  "afterwash_face_ref": "afterwash_face_closeup.png",
  "allowed_when": {
    "person_asset": "/path/to/kongfengchun/model-assets/male/content-4.png"
  },
  "binding_rule": "afterwash_face_ref can only be used when identity_ref is the active model identity"
}
```

Rules:

- The after-wash face belongs to the exact identity group.
- `04_身份图` and `05_洗后脸` in final upload must come from the same identity group.
- If the active job changes model identity, a new identity group and after-wash face must be created.
- A face close-up cropped from a storyboard image is not valid as an after-wash reference.

### Product Group

Example:

```text
output/shared/kongfengchun/products/kongfengchun_clean_mud_mask/
  product_front_tight.png
  product_open_white_mud_tight.png
  manifest.json
```

Manifest shape:

```json
{
  "asset_group_type": "product_group",
  "product_id": "kongfengchun_clean_mud_mask",
  "product_name": "孔凤春清洁泥膜",
  "source_assets": "/path/to/kongfengchun/product-assets",
  "front_ref": "product_front_tight.png",
  "open_mud_ref": "product_open_white_mud_tight.png",
  "binding_rule": "front_ref and open_mud_ref can only be reused when product_id and source_assets match the active job"
}
```

Rules:

- `02_产品正面` and `03_开盖白泥` in final upload must come from the same product group.
- If product, packaging, SKU, color, or source asset folder changes, a new product group is required.
- Product group assets can be reused across jobs only when product binding matches.

## Per-Job Approved Visual Manifest

Every job needs an approved visual manifest before downstream prompt/request stages can pass.

Example:

```json
{
  "job_id": "job-002",
  "product_group_id": "kongfengchun_clean_mud_mask",
  "identity_group_id": "kongfengchun_male_content4",
  "part_storyboards": {
    "part1": {
      "asset_type": "AI改好分镜图",
      "image_route": "matpool_gpt_image_2_edit",
      "path": "output/job-002/final-images/part1_seedance_ref.png",
      "contains_source_video_pixels": false
    },
    "part2": {
      "asset_type": "AI改好分镜图",
      "image_route": "matpool_gpt_image_2_edit",
      "path": "output/job-002/final-images/part2_seedance_ref.png",
      "contains_source_video_pixels": false
    }
  },
  "reusable_refs": {
    "product_front": "output/shared/kongfengchun/products/kongfengchun_clean_mud_mask/product_front_tight.png",
    "product_open": "output/shared/kongfengchun/products/kongfengchun_clean_mud_mask/product_open_white_mud_tight.png",
    "identity_ref": "output/shared/kongfengchun/identities/kongfengchun_male_content4/identity_ref.png",
    "afterwash_face": "output/shared/kongfengchun/identities/kongfengchun_male_content4/afterwash_face_closeup.png"
  }
}
```

Required checks:

- `part_storyboards.*.asset_type` must be `AI改好分镜图`.
- `part_storyboards.*.image_route` must be `matpool_gpt_image_2_edit`.
- `contains_source_video_pixels` must be `false`.
- Part storyboard paths must be under the active job output directory.
- Product references must match the active job product group.
- Identity and after-wash references must match the active job identity group.

## Gate Behavior

### Image Sample Gate

Must pass only when:

- A real saved `AI改好分镜图` exists.
- The generation route is recorded.
- The asset type is valid.
- The image has no old source product, person, subtitles, gray/yellow mud, or source-frame contamination.
- It is suitable to become a Seedance reference after approval.

Must fail when:

- The image is missing.
- The output is a Python/PIL composite.
- The output is a source-video rhythm board, contact sheet, cropped source frame, old job anchor, or unsaved generation claim.
- The maker says the old pixels should be ignored by prompt wording, material-role notes, or "motion-only" usage.

### Image Batch Gate

Must pass only when:

- Part1 and Part2 final images are both `AI改好分镜图`.
- The Kongfengchun white-mud and single-identity rules pass.
- The images are promoted to final locations through the approved manifest.

Must fail when:

- Any final/promoted image is not a valid AI-corrected storyboard image.
- Any image contains old product, old person, subtitles, source mud, source props, or other visible source contamination.
- Any product-introduction or texture shot lacks the target product or shows non-white mud.

### Seedance Prompt Gate

Must pass only when:

- It references only approved visual manifest assets.
- Material-role table does not ask Seedance to ignore contaminated pixels.
- After-wash reference belongs to the active identity group.
- Product front and open-mud references belong to the active product group.

### Request Gate

Must pass only when:

- `seedance_web_final/` contains only approved final upload images, audio, prompts, manifests, and notes.
- Upload image order matches the approved visual manifest.
- Final audio files are `<=15.00s`, target `14.90s`.

Must fail when:

- The final upload directory contains source frames, rhythm boards, composites, old job images, deprecated drafts, or binding-mismatched references.

## Runner Enforcement

`run-loop.sh --record-gate-result PASS` must refuse to record a PASS for image/prompt/request stages unless the relevant machine QC outputs pass.

Required QC before recording PASS:

- `image_sample`: checker review QC plus visual asset manifest QC.
- `image_batch_qc`: checker review QC plus visual asset manifest QC.
- `seedance_prompt`: checker review QC plus visual asset manifest QC.
- `request_qc`: checker review QC plus visual asset manifest QC plus audio duration QC.

If checker review QC or visual asset manifest QC returns `FAIL` or `STOP`, the runner must not advance the job.

## Visual Asset Manifest QC Tool

Add a tool conceptually named:

```text
tools/visual_asset_manifest_qc.py
```

Responsibilities:

- Load active `jobs.csv` row.
- Load product group manifest.
- Load identity group manifest.
- Load job approved visual manifest.
- Confirm paths exist.
- Confirm asset types are valid for the stage.
- Confirm product group matches active job product.
- Confirm identity group matches active job person asset.
- Confirm `01_图片1` is current job `AI改好分镜图`.
- Confirm `02/03` come from the same product group.
- Confirm `04/05` come from the same identity group.
- Reject forbidden asset types in final, Seedance refs, or image-stage outputs.
- Emit JSON and Markdown QC reports.

## Self-Audit Mode

Self-audit remains allowed, but the checker is an auditor only.

Checker responsibilities:

- Inspect the actual image paths.
- Read the job approved visual manifest.
- Read product and identity group manifests.
- Decide `PASS`, `FAIL`, or `STOP`.
- Explain asset type, product group, identity group, and final directory status.

Checker restrictions:

- Must not repair images.
- Must not rewrite manifests.
- Must not approve a visual stage when machine QC is missing.
- Must not accept text workarounds such as "motion-only", "ignore old pixels", or "role table constrains contamination".

## Reuse Policy

Reusable:

- Product front crop when product group matches.
- Product open white-mud crop when product group matches.
- Identity image when identity group matches.
- After-wash face close-up when identity group matches.
- Prompt and manifest templates.
- Final handoff directory structure.

Not reusable as final storyboards:

- Old job storyboard images.
- Source-video frame boards.
- Contact sheets.
- Cropped source frames.
- Python/PIL composites.
- Validated anchor composites.

Each job must produce its own `AI改好分镜图` for every Seedance part.

## Test Scenarios

PASS scenarios:

- `01_图片1` is current job `AI改好分镜图`.
- Product front and open-mud refs come from the active product group.
- Identity and after-wash refs come from the active identity group.
- Final upload directory has only approved files.
- Audio duration QC passes.

FAIL scenarios:

- `01_图片1` is a source-video rhythm board.
- `01_图片1` is a Python/PIL composite.
- `01_图片1` is an old job storyboard image.
- `05_洗后脸` belongs to a different identity group.
- `02/03` belong to a different product group.
- Final directory contains deprecated drafts.
- Checker PASS reason says "motion-only", "ignore old pixels", or "role table constrains contamination".
- Codex generated an image direction but no image was saved.

## Success Criteria

- Future sessions cannot advance from image stages without a valid `AI改好分镜图`.
- Reusable assets are reused only when product or identity binding matches.
- Final Seedance handoff contains only approved assets.
- Self-audit can still run quickly, but it cannot override failed visual asset QC.
- The loop stops instead of inventing substitute image routes.

## Open Implementation Notes

- Existing `tools/checker_review_qc.py` can keep red-flag phrase checks, but the primary source of truth should become visual asset manifest QC.
- Existing `tools/image_hard_gate_qc.py` remains useful for color/layout/product marker checks, but it cannot decide asset provenance by itself.
- Existing job-001 validated outputs can seed the first product group and identity group if their binding data is captured in manifests.
