# Voiceover Worker

## Canonical Stage

`voiceover`

## Purpose

Rewrite the source voiceover for the target product while preserving source shot rhythm.

## Inputs

- Story analysis artifact.
- ASR transcript.
- Subtitle layer, if available.
- Approved storyboard images.
- Product name and product constraints.
- `gates/voiceover_gate.md`.

## Actions

1. Read ASR, subtitle text, and visual shot table together.
2. Preserve source hook, proof, product reveal, offer, and close.
3. Bind every spoken line to a shot or shot group.
4. Keep product name placement aligned with product close-up or reveal.
5. Keep total speech short enough for the target duration.
6. For every shot-line row, record the source speaker mode/line from ASR + visual evidence and the target speaker mode/line. Preserve the source mode exactly: source口播/同期声 stays target口播/同期声, source画外音旁白 stays target画外音旁白.
7. Do not change speaker mode because the target action is product, hand, phone, label, jar, bottle, or proof. If the source beat is口播, adjust the target visual action so the speaker can naturally appear and speak.

## Outputs

Write under `output/<job-id>/voiceover/`:

- `voiceover.md`
- `shot_line_map.md` with columns for source speaker mode/line and target speaker mode/line
- optional `voiceover_timing_qc.md`

## Gate

Run:

`gates/voiceover_gate.md`

## PASS Next Status

`voiceover_done`

## FAIL Retry Variables

Choose exactly one:

- `source_timing`
- `shot_line_binding`
- `copy_length`
- `speaker_role`

## Stop Conditions

- Key source line is unclear and requires human confirmation.
