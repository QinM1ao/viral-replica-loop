# Seam Worker

## Canonical Stage

`seam`

## Purpose

Design part boundaries so multi-part generation can be stitched without static starts or speech overlap.

## Inputs

- Approved storyboard images.
- Voiceover with shot-line mapping.
- Source shot table.
- Target part duration.
- `gates/seam_gate.md`.

## Actions

1. For each boundary, inspect the previous part's last two shots and the next part's first two shots.
2. Record previous ending state: face, hand, product, camera, light, scene, and speech.
3. Define next starting state: begin in motion, continue product/hand/action state, then open the next line.
4. Add speech buffers around the seam.
5. Keep multi-part videos no-BGM unless `BRIEF.md` explicitly asks for music.

## Outputs

Write under `output/<job-id>/seam/`:

- `seam_design.md`
- optional boundary contact sheet

## Gate

Run:

`gates/seam_gate.md`

## PASS Next Status

`seam_done`

## FAIL Retry Variables

Choose exactly one:

- `seam_point`
- `boundary_motion`
- `speech_boundary`
- `continuity_anchor`

## Stop Conditions

- No safe seam exists under the requested part count or duration.
