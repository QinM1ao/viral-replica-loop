# Caption Finishing Gate

## Stage

`caption_finishing`

## Purpose

Approve the optional captioned delivery only when the user explicitly requested
captions and the final post-production render is bound to the already-approved
clean video.

## Required Inputs

- Valid `caption_finishing/request.json` with `request_source=explicit_user_request`.
- Passing subtitle-removal report and final technical QC.
- Source video and source caption-grammar blueprint.
- Corrected actual-final-audio alignment and compiled caption timeline.
- Passing HyperFrames check, caption visual review, and caption QC.
- Hash-bound `caption_finishing_report.json`.

## PASS

Return `PASS` only when:

- the request is an explicit opt-in for this job;
- Seedance was not asked to generate captions;
- the caption input path/hash is the exact final-QC-approved active video;
- the source video supplies style only, while actual final audio supplies text
  and timing;
- ASR spelling correction is bound to the approved spoken script without adding
  unspoken words;
- source-supported ordinary, emphasis, repeated impact, placement, and motion
  grammar is represented;
- HyperFrames check and `caption_qc.json` are `PASS`;
- the visual review proves no collision, clipping, face/product obstruction,
  missing event, or illegible frame;
- the captioned MP4 is a distinct, hash-bound output file.

Run:

```bash
python3 tools/caption_finishing_qc.py check \
  --root . \
  --job-id "<job-id>" \
  --json-out "output/<job-id>/checks/caption_finishing_qc.json"
```

## FAIL

Return `FAIL` for stale hashes, wrong input/output binding, mismatched spoken
text, missing caption roles/events, layout defects, failed visual evidence, or
an output that overwrites its immutable input.

## STOP

Return `STOP` when the request marker is absent/invalid or required source,
audio, script, final-QC, or caption-grammar evidence is unavailable.

## Next Status

On PASS:

```text
done
```
