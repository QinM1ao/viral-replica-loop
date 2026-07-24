# Storyboard Worker

## Canonical Stage

`storyboard`

## Purpose

Turn passed story analysis into a source-aligned storyboard, seam plan, and contamination audit.

## Inputs

- Passed story analysis artifacts.
- Source video contact sheet or key frames.
- Product assets.
- Person/model assets.
- `PRODUCT_CONSTRAINTS.md`.
- `QC_RULES.md`.

## Actions

1. Read the story analysis artifact.
2. Preserve source shot order and rhythm.
3. Choose safe part split or seam points.
4. Create the storyboard table.
5. Create Part-level source storyboard reference images for image editing:
   - one full source storyboard image per target Part, normally 12 panels
   - preserve the source video's frame aspect inside every panel; do not stretch a landscape source into 9:16 or 3:4
   - use 4 columns x 3 rows when there are 12 panels, but let the final canvas ratio follow the source panel ratio
   - save under a stable path such as `output/<job-id>/storyboard_source_refs/source_storyboard_part1.jpg`
   - save `output/<job-id>/storyboard_source_refs/source_storyboard_manifest.json` with source width, height, aspect ratio, orientation, grid, and part paths
   - these images are the future ImageGen edit base; the story-analysis contact sheet is not enough
6. Create the contamination audit:
   - old product
   - old model
   - captions/subtitles
   - old packaging
   - old texture
   - old applicator/tool
7. Remap product actions to the target product's real usage.
8. Define what each future image-generation reference should control.

## Outputs

Write under `output/<job-id>/分镜/`:

- `分镜表与缝点审查.md`
- `分镜污染审查.md`
- `storyboard_source_refs/source_storyboard_partX.jpg` for every target Part
- `storyboard_source_refs/source_storyboard_manifest.json`
- storyboard contact sheet or shot references as support evidence only

## Gate

Run:

`gates/storyboard_gate.md`

## PASS Next Status

`storyboard_passed`

## FAIL Retry Variables

Choose exactly one:

- `shot_selection`
- `seam_point`
- `contamination_audit`
- `product_action_remap`

## Stop Conditions

- Story analysis is missing.
- No safe split exists under the current duration target.
- Product action cannot be mapped without user decision.
