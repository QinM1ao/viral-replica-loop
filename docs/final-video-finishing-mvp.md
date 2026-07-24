# Final Video Finishing MVP

## Decision

The final-video MVP uses one explicit edit plan and a local FFmpeg executor.

Vibe Editing is an orchestration layer: it converts natural-language intent into editing parameters and calls the underlying synthesis service plus other AI MediaKit tools when needed. Atomic tools expose one operation directly. They are composable, not mutually exclusive. This matches the [official Vibe Editing documentation](https://docs.volcengine.com/docs/6448/2549864?lang=zh): `vibe-editing` parses intent and invokes the underlying multi-track synthesis capability, while the workflow may also call other MediaKit tools.

For production predictability, this MVP does not let an LLM infer the final timeline. The same plan can later be routed to:

- `local_ffmpeg` — default, free, deterministic;
- `mediakit_atomic` — focused cloud repair such as hard-subtitle erasure, only after cost-gate PASS and explicit user approval;
- `vibe_editing` — experimental multi-track render after regression validation, cost-gate PASS, and explicit user approval.

## Supported Plan

```json
{
  "version": 1,
  "executor": "local_ffmpeg",
  "inputs": [
    {"id": "part1", "path": "../generation/videos/part1.mp4"},
    {"id": "part2", "path": "../generation/videos/part2.mp4"}
  ],
  "timeline": [
    {"input": "part1", "start": 0.0, "end": 12.8, "speed": 1.0},
    {"input": "part2", "start": 0.2, "end": 12.9, "speed": 1.0}
  ],
  "output": {
    "filename": "final_video.mp4",
    "audio_fade_out_seconds": 0.2
  }
}
```

The timeline lists kept intervals. To remove a bad interval, split the surrounding good ranges and omit the bad range. This makes every deletion visible in review.

## Commands

Initialize a hard-cut plan from approved Parts:

```bash
python3 tools/finish_video.py init \
  --input output/<job-id>/generation/videos/part1.mp4 \
  --input output/<job-id>/generation/videos/part2.mp4 \
  --plan output/<job-id>/finishing/edit_plan.json
```

Render after reviewing or editing the plan:

```bash
python3 tools/finish_video.py render \
  --plan output/<job-id>/finishing/edit_plan.json \
  --out-dir output/<job-id>/final
```

Then run the conditional `subtitle_removal` worker against that exact `output/<job-id>/final/final_video.mp4`. It classifies the master only as `clean` or `burned_in`, skips clean output for free, and uses at most one standing-approved MediaKit Pro repair when pixels contain accidental captions. Final Technical QC consumes the passing subtitle-removal report's active `output_video`. Explicit final captions, when requested, run afterward in `caption_finishing`.

The render report binds the edit plan, every source Part, and the caption-free final MP4 by SHA-256. The local executor rejects any `subtitles` field. A new render attempt invalidates old PASS reports first, so a failed or changed plan cannot reuse stale evidence. Inputs with different aspect ratios are rejected instead of stretched; normalize the approved Parts before finishing.

## Deliberate Exclusions

- no beauty/face retouching;
- no automatic semantic defect detection;
- no automatic transition invention;
- no paid Vibe Editing or MediaKit submission;
- no SRT, ASS, or other caption rendering in the local finishing executor.

Wrong identity, wrong product, incoherent speech, or a required story beat that cannot be safely cut must go to targeted segment regeneration instead of being hidden by editing.
