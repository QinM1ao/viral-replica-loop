# Voiceover Gate

## Stage

`voiceover`

## Purpose

Confirm that rewritten copy preserves source timing, shot function, and product-name placement.

## Required Inputs

- Story analysis with ASR, subtitle layer, and visual shot table.
- Approved storyboard images.
- Product name and product constraints.
- Target duration.

## PASS

Return `PASS` only if:

- Voiceover is based on source story analysis, not a generic ad rewrite.
- Each line maps to a source shot or shot group.
- Product name appears at the intended product reveal or product close-up.
- Every shot-line row records source speaker mode/line and target speaker mode/line.
- Source speaker mode is preserved exactly: source口播/同期声 stays target口播/同期声, source画外音旁白 stays target画外音旁白.
- Copy length fits the target duration without rushed speech.

## FAIL

Return `FAIL` if:

- ASR and subtitle timing are not used.
- Product name is detached from the visual product shot.
- A source口播/同期声 beat is changed into旁白, or a source旁白 beat is changed into口播/同期声.
- The shot-line map lacks source speaker mode for any spoken row.
- Copy is too long for the duration.
- Source hook, proof, or call to action is missing.

Retry variable:

Choose exactly one:

- `source_timing`
- `shot_line_binding`
- `copy_length`
- `speaker_role`

Locked variables:

Approved storyboard images and product identity.

## STOP

Return `STOP` if:

- Key source words are unclear and need human confirmation.

## Next Status

On pass:

```text
voiceover_done
```
