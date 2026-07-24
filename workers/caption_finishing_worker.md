# Caption Finishing Worker

## Canonical Stage

`caption_finishing`

## Boundary

This is an opt-in, last-step post-production worker. Run it only when
`output/<job-id>/caption_finishing/request.json` is valid and records an
`explicit_user_request`. The default workflow does not enter this stage.

Seedance generation remains subtitle-free. This worker may only add captions
to the immutable video that already passed `final_qc`.

## Required Skill

Read and follow:

`~/.codex/skills/source-faithful-captions/SKILL.md`

The explicit caption request is approval to perform the local HyperFrames
render. It is not approval for another Seedance or paid MediaKit task.

## Inputs

- Job source video: caption style and visual grammar only.
- `subtitle_removal/subtitle_removal_report.json`: active clean final video.
- Passing `final_qc/final_qc.json`: proves the active input passed technical QC.
- Actual audio from that active final video: caption text and output timing authority.
- Approved spoken script or submitted Seedance prompt: spelling correction authority only.
- The explicit caption request marker.

Never copy source-video timestamps onto the generated video. Never force the
intended script over words that were not actually spoken.

## Actions

1. Validate the request and resolve the exact final-QC-approved input video.
2. Extract or transcribe the actual final audio. Correct ASR typos against the
   approved spoken script while preserving what was actually spoken.
3. Reuse a hash-matched `caption_blueprint.json`; otherwise extract the source
   caption grammar once, using the source video only for typography, hierarchy,
   placement, repeated impact captions, and motion.
4. Compile actual-audio-aligned semantic caption groups with the
   `$source-faithful-captions` scripts.
5. Build and check the HyperFrames project, then render one captioned MP4.
6. Create the required 1 fps contact sheet and focused evidence for impact or
   mixed-size captions. Pass `qc_caption_video.py` and its visual review.
7. Write and validate `caption_finishing_report.json` with the local wrapper.

## Commands

The global skill documents the compile, build, HyperFrames check/render, and
caption QC commands. After they pass, bind the result to this job:

```bash
python3 tools/caption_finishing_qc.py report \
  --root . \
  --job-id "<job-id>" \
  --caption-blueprint "<caption-output>/caption_blueprint.json" \
  --caption-timeline "<caption-output>/caption_timeline.json" \
  --hyperframes-check "<caption-output>/hyperframes-project/hyperframes_check.json" \
  --visual-review "<caption-output>/visual_review.json" \
  --caption-qc "<caption-output>/caption_qc.json" \
  --output-video "<caption-output>/hyperframes-project/captioned.mp4"

python3 tools/caption_finishing_qc.py check \
  --root . \
  --job-id "<job-id>" \
  --json-out "output/<job-id>/checks/caption_finishing_qc.json"
```

## Outputs

Write all caption artifacts under:

`output/<job-id>/caption_finishing/`

Required final artifacts:

- `request.json`
- `caption_blueprint.json`
- `caption_timeline.json`
- HyperFrames project and `hyperframes_check.json`
- `visual_review.json` plus its contact sheet/focused frames
- `caption_qc.json`
- captioned MP4
- `caption_finishing_report.json`
- `checks/caption_finishing_qc.json`

## PASS Next Status

`done`

## Stop Conditions

- No explicit request marker.
- Final audio alignment is missing or stale.
- Source grammar evidence is missing.
- HyperFrames check, caption QC, or visual review is not PASS.
- Output text does not equal the corrected actual spoken content.
- Caption collision, clipping, obstruction, or missing special events remain.
