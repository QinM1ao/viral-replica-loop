# Audio Boundary Worker

## Canonical Stage

`audio_boundary_qc`

## Purpose

Prepare and verify reference audio for sound-enabled multi-part generation.

## Inputs

- Approved voiceover.
- Source or client reference audio.
- Target part durations.
- `tools/asr_transcribe.py`.
- `gates/audio_boundary_gate.md`.

## Actions

1. If the job is silent, write a skip note and pass the gate.
2. Cut each reference audio part on sentence boundaries, not mechanical 15.00s cuts.
3. Keep every part `<=15.00s`; target `14.90s` to leave encoder/UI tolerance. If preserving a full sentence would exceed 15.00s, shorten the script, move the boundary earlier, or speed up slightly.
4. Run ASR on each part.
5. Confirm adjacent parts do not duplicate or drop boundary lines.
6. Save audio paths and ASR outputs.

## Scripted Part

After cutting audio, run strict duration QC:

```bash
python3 viral-replica-loop/tools/audio_duration_qc.py \
  --audio viral-replica-loop/output/<job-id>/audio-boundary/reference_audio_part1.mp3 \
          viral-replica-loop/output/<job-id>/audio-boundary/reference_audio_part2.mp3 \
  --max-seconds 15.0 \
  --out-json viral-replica-loop/output/<job-id>/audio-boundary/audio_duration_qc.json \
  --out-md viral-replica-loop/output/<job-id>/audio-boundary/audio_duration_qc.md
```

## Outputs

Write under `output/<job-id>/audio-boundary/`:

- `reference_audio_partX.mp3`
- `reference_audio_partX_asr.md`
- `audio_duration_qc.md`
- `audio_boundary_qc.md`

## Gate

Run:

`gates/audio_boundary_gate.md`

## PASS Next Status

`audio_boundary_qc_done`

## FAIL Retry Variables

Choose exactly one:

- `audio_cut_point`
- `script_length`
- `audio_format`
- `asr_confirmation`

## Stop Conditions

- ASR cannot recover unclear source speech and no subtitle layer exists.
- A reference audio file remains over 15.00s after one targeted recut.
