# After-Wash Reference Gate

## Stage

`afterwash_reference_review`

## Purpose

Decide whether a cleaned-skin face reference is safe to use for post-wash Seedance shots.

## Required Inputs

- Original approved identity reference.
- Generated or edited after-wash face close-up.
- Approved storyboard and shot list.
- `PRODUCT_CONSTRAINTS.md`.

## Required Output Artifact

The worker must create an after-wash reference review artifact under the job output folder.

It must include:

- Input identity reference path.
- After-wash reference path.
- Face likeness check.
- Skin improvement check.
- Lighting and color consistency check.
- Allowed shot usage list.
- Result: `PASS`, `FAIL`, or `STOP`.

## PASS

Return `PASS` only if:

- The face still looks like the approved model.
- Skin looks cleaner, clearer, less oily, and more refined.
- The improvement is natural, not a new cold-white studio face.
- Lighting and skin tone can match the surrounding segment.
- The reference is restricted to wash-finished or proof shots only.

## FAIL

Return `FAIL` if:

- The face no longer matches the approved model.
- Skin tone changes too much compared with earlier shots.
- The image changes wardrobe, scene, hairstyle, or identity.
- The reference would cause the whole segment to start with washed-skin tone.

Retry variable:

`skin_improvement_strength`

Locked variables:

Identity, wardrobe, scene, camera angle.

## STOP

Return `STOP` if:

- The after-wash image passes hard checks and user visual approval was explicitly requested for this stage.
- The second attempt still causes identity or color drift.

In `--self-audit` mode, the independent checker may return `PASS` without user visual approval when the after-wash reference passes hard checks and the user did not configure this stage as a stop point.

## Next Status

On pass:

```text
afterwash_ref_passed
```
