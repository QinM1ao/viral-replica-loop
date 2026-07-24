# Seam Gate

## Stage

`seam`

## Purpose

Confirm multi-part video boundaries can join without static starts, speech overlap, or visual jumps.

## Required Inputs

- Approved storyboard images.
- Voiceover draft with timing.
- Source shot table.
- Target part durations.

## PASS

Return `PASS` only if:

- Every part boundary records previous ending state and next starting state.
- The next part starts in motion, not with a static face.
- Speech ends before the seam and starts after the seam buffer.
- Product, hand, face, light, and scene continuity are defined.
- Multi-part videos default to no BGM.

## FAIL

Return `FAIL` if:

- Boundary is a frozen face or unrelated restart.
- Speech crosses the seam.
- Next part ignores previous part state.
- Seam plan depends on a generated frame that does not exist yet.

Retry variable:

Choose exactly one:

- `seam_point`
- `boundary_motion`
- `speech_boundary`
- `continuity_anchor`

Locked variables:

Approved storyboard order and approved voiceover lines.

## STOP

Return `STOP` if:

- No safe seam exists under the requested part count or duration.

## Next Status

On pass:

```text
seam_done
```
