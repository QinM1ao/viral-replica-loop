# Audio Boundary Gate

## Stage

`audio_boundary_qc`

## Purpose

Confirm sound-enabled multi-part video references do not duplicate, drop, or cross boundary lines.

## Required Inputs

- Voiceover script.
- Reference audio files, if used.
- ASR transcript for each reference audio part.
- Part duration target.

## PASS

Return `PASS` only if:

- Each reference audio file is `<=15.00s`; target `14.90s` to leave encoder/UI tolerance.
- Each part starts and ends on sentence boundaries.
- Adjacent parts do not repeat the same line.
- No line needed for the next part leaks into the previous part.
- Silent jobs include a written skip note.

## FAIL

Return `FAIL` if:

- Audio is longer than 15.00s, including files such as 15.01s or 15.15s that may fail web upload.
- Boundary line is duplicated or missing.
- ASR does not match the approved script closely enough.

Retry variable:

Choose exactly one:

- `audio_cut_point`
- `script_length`
- `audio_format`
- `asr_confirmation`

Locked variables:

Approved voiceover content and storyboard timing.

## STOP

Return `STOP` if:

- ASR cannot recover unclear source speech and no subtitle layer exists.
- A reference audio file remains over 15.00s after one targeted recut.

## Next Status

On pass:

```text
audio_boundary_qc_done
```
