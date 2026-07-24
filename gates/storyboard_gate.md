# Storyboard Gate

## Stage

`storyboard`

## Purpose

Confirm the storyboard preserves the source video's rhythm while removing old-product, old-person, caption, prop, and texture contamination before image-generation work begins.

## Required Inputs

- Story analysis artifact.
- Source video contact sheet or extracted shot frames.
- Product constraints.
- Product assets.
- Person/model assets.
- `QC_RULES.md` Storyboard and image generation rules.

## Required Output Artifact

The worker must create a storyboard review artifact under the job output folder.

It must include:

- Shot table.
- Seam or part split notes.
- Part-level source storyboard reference image paths for every target Part.
- Source video width, height, aspect ratio, orientation, and the intended storyboard canvas ratio for every target Part.
- Contamination audit.
- Product action remapping.
- Image-generation reference plan.
- Result: `PASS`, `FAIL`, or `STOP`.

## PASS

Return `PASS` only if:

- Key source shots are represented in order.
- Every target Part has a saved source storyboard reference image, normally one 12-panel image, intended as the direct ImageGen edit base.
- Every source storyboard reference preserves the source video's frame aspect inside its panels; a landscape source must stay visually landscape unless the user explicitly approved a vertical adaptation plan.
- The storyboard artifact includes source aspect metadata or a manifest proving the intended output ratio before image generation.
- The image-generation reference plan points to those Part-level source storyboard images. A story-analysis contact sheet may be support evidence, but it is not enough as the direct edit base.
- Cuts or part splits do not break spoken sentences, product reveal, or major visual actions.
- Each shot records what to preserve and what to replace.
- Old product packaging, old tool shape, old mud texture, old captions, and old model identity are identified.
- Skincare/clay-mask actions are remapped to the new product's real usage.
- Product-specific contamination risks in `PRODUCT_CONSTRAINTS.md` are blocked before image generation or Seedance.

## FAIL

Return `FAIL` if:

- The storyboard rewrites the ad into a generic new script.
- The cut point creates a frozen or static seam risk.
- Contamination sources are not named.
- Part-level source storyboard reference images are missing, or the plan only offers a general story-analysis contact sheet for image generation.
- The source storyboard reference stretches, crops, or squeezes the source frame into 9:16/3:4 without an explicit vertical-adaptation decision.
- The artifact assumes 9:16, portrait, or 3:4 output without checking the source video's actual aspect ratio.
- Product action remapping is missing.
- The storyboard would send old gray mud or tube applicator into image/video generation.

Retry variable:

Choose exactly one:

- `shot_selection`
- `seam_point`
- `contamination_audit`
- `product_action_remap`

Locked variables:

Source video order, target product, target model, target duration.

## STOP

Return `STOP` if:

- The source video has no safe split under the current duration limit.
- The story analysis is missing or too weak to support storyboard decisions.

## Next Status

On pass:

```text
storyboard_passed
```
