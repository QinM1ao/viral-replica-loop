---
name: minimax-h3-replica
description: Replicate a source video with MiniMax H3 using replacement person, product, and approved audio references. Use only when the user explicitly requests MiniMax H3 for replication or asks to adapt an existing ShotLoom Job to MiniMax H3.
---

# MiniMax H3 Replica

## Boundary

Use MiniMax H3 Ref2VA to edit the source video directly. Replace the storyboard-edit, depth-reference, and Seedance handoff stages with one lightweight H3 lane while preserving ShotLoom's Job isolation, cost approval, request evidence, and final QC.

Keep generic replication on `viral-replica`. Inside an existing ShotLoom Job, reuse accepted source facts and target assets instead of restarting the full flow.

Reuse a timeline, cut list, unit boundary, or transcript only when its recorded source hash matches the current source bytes. Treat facts from another Job or unmatched source hash as unavailable.

## Required Reading

Read [references/ref2va-prompt-standard.md](references/ref2va-prompt-standard.md) before writing or reviewing any H3 prompt. Read [references/wujie-request.md](references/wujie-request.md) before building, submitting, querying, or retrying a Wujie H3 request.

## Workflow

### 1. Bind One Job

Create or reuse exactly one Job and write H3 artifacts under:

```text
jobs/<job-id>/work/minimax-h3/
  source/
  audio/
  unit-01/
  unit-02/
  ...
```

Require the source video and every requested replacement asset to exist. Probe source duration, dimensions, frame rate, and audio streams with `ffprobe`. Record whether target speech is unchanged, locally edited, or newly written.

Completion: every input path resolves, the source media decodes, and the Job records one explicit audio strategy.

### 2. Build the Evidence Timeline

Use ElevenLabs Scribe v1 as the only speech evidence source. Resolve the transcription tool from this Skill and preserve its raw text, word timestamps, speaker turns, sentence segments, and audio events:

```bash
SKILL_DIR="$(cd "$(dirname "<absolute-path-to-this-SKILL.md>")" && pwd)"
python3 "$SKILL_DIR/../../../tools/asr_transcribe.py" \
  "<source-audio-or-video>" \
  --out-dir "<job-root>/work/minimax-h3/source/elevenlabs"
```

Measure visual hard cuts from the source pixels with FFmpeg. Use ElevenLabs times for speech and FFmpeg times for shots; neither source substitutes for the other. Inspect a compact contact sheet only to name visible subjects, actions, framing, product states, and replacement slots.

Completion: the timeline covers the full source once, every spoken phrase has timestamps and a speaker, and every visual interval is bounded by measured cuts or the source endpoints.

### 3. Plan H3 Units

Use one unit when the requested source interval is at most 15 seconds. For longer sources, choose boundaries at or before 15 seconds in this order: hard cut aligned with a sentence end, hard cut aligned with a pause, completed action, then the nearest safe hard cut. Keep source order and duration; do not compress missing beats into another unit.

For each unit, export the exact source interval and remap its timeline to start at `00:00.000`. Cover every source interval exactly once with no gap or overlap.

Completion: every unit is at most 15 seconds, every boundary is safe for both picture and speech, and the ordered units cover the requested source range exactly once.

### 4. Approve One Audio Master per Unit

If speech and voice remain unchanged, extract the exact unit audio. If words, product facts, or voice identity change, synthesize one complete unit master with the configured approved voice route and use the ElevenLabs timing evidence to preserve pace and pauses. Require direct user listening approval before paid video generation when a new voice master was created.

Treat the approved master as the final delivery audio. H3 audio reuse is generation guidance, not a guaranteed waveform passthrough; keep the master available for deterministic postmix.

Make this decision mechanically. Record `speech_change` and the selected strategy in `<pack-root>/audio_contract.json`. Any changed word, product name, product fact, offer, speaker identity, or newly written line sets `speech_change` to `changed` and requires `strategy=tts_approved_master`; never inherit `extract_from_original` from a generic Job intake in that branch. Use `scripts/voxcpm2_generate.py` when the Workspace-approved local VoxCPM2 route is selected.

Run the blocking gate before declaring the upload pack ready:

```bash
python3 "$SKILL_DIR/scripts/audio_master_gate.py" \
  "<pack-root>" \
  --report "<pack-root>/pre_generation_audio_gate.json"
```

The gate must fail until every changed-speech unit has a full-duration TTS master, generation provenance, matching file/hash bindings in `upload_manifest.json`, a `fully_copy` prompt matching the complete master transcript, deterministic postmix policy, and direct user listening approval. `pending`, agent-inferred approval, a short timbre sample, or an H3-generated voice is not approval. Do not convert this failure into a warning.

Completion: every speaking unit has one approved, decodable master matching the unit duration and intended complete wording.

### 5. Write One Ref2VA Prompt per Unit

Follow the prompt standard exactly. Use the source interval as `<Video 1>`, replacement images as `<Picture N>` sources for stable `<Subject N>` identities, and the approved unit master as `<Audio 1>`.

Map every measured visual interval to one ordered `[Shot N]`. Use `[Shot 1]` without a timestamp and `[Shot N] At MM:SS.mmm` for every later cut. Preserve the source shot order, framing, action phase, camera behavior, and hard-cut timing; change only user-requested or product-conflicting subjects and states.

When a person is replaced, compile every prompt against the prompt standard's Complete-Person Replacement Contract: transfer the complete target person and clothing, keep the person picture's background out of the video, and repeat the person, clothing, source-video environment, and product bindings in every relevant Shot.

Use `<Audio 1>: fully_copy` only when the entire reference audio is intended to be the complete and sole final soundtrack. In that branch, cue actions with `When <Audio 1> reaches ...`, keep visible people silent unless the source requires synchronized speech, and request no additional ambience, effects, music, or generated voice. Use `partially_copy` when any audio layer is added, removed, or replaced.

Completion: all six Ref2VA sections are present in order, every label closes, every source shot appears exactly once, all timestamps fit the unit duration, the audio marker matches the actual mix intent, and every replaced role passes the Complete-Person Replacement Contract and Prompt QC.

### 6. Build and Preflight the Request

Use `taskCode=2513`, `model=MiniMax-H3`, the requested supported resolution, the exact unit duration, and the source aspect ratio. Order `content` as text, reference video, reference images, then reference audio. Keep `role` beside each URL object.

Convert local media to stable public HTTPS URLs with the Workspace-configured uploader. Reuse an existing verified URL for unchanged bytes. Before submission, require every URL to return HTTP 200 and decode as its declared media type; validate the nested `param` JSON after serialization.

Completion: the saved request body reconstructs to the intended model, duration, ratio, prompt, asset roles, and reachable media.

### 7. Respect the Paid Boundary

Stop before `task_create` unless the user explicitly requested generation for the current Job. That direct request approves each required unit once. Save the request body and create response before polling.

Create no automatic paid retry. Query the same Task Key through transient gateway errors. A successful create response proves only task creation; generation succeeds only when the embedded MiniMax task reports `succeeded` and provides an output URL.

Completion: each approved unit has at most one new Task Key, and every query or failure remains bound to that key.

### 8. Download, Inspect, and Finish

Preserve the downloaded H3 output as `raw.mp4`. Verify decoding, video and audio streams, dimensions, duration, and obvious black, frozen, missing, invented, or reordered shots. Inspect person identity, product construction, label anchors, physical product use, and burned-in subtitles across the full timeline.

Use the raw H3 audio for user review. When exact wording or voice is required, replace it with the approved unit master after visual acceptance; do not use final ASR by default. Run targeted transcription only when the user requests script verification or a listening defect is found. If the user requires a clean master and H3 burned in subtitles, route the accepted master through `video-subtitle-removal` once.

Re-run `audio_master_gate.py` immediately before upload and again before paid submission. A stale hash, changed prompt, changed master, or missing approval blocks submission.

Completion: preserve the raw file, deliver the accepted master through an absolute path, and report Task Keys, finishing applied, unresolved visual warnings, and paid retry count.

## Stop Conditions

Stop without submitting when an input is missing, a unit exceeds 15 seconds, the target audio is unapproved, a public asset fails preflight, the request does not reconstruct exactly, or paid approval is absent. Stop without retrying when a generated unit fails; preserve its evidence and request one targeted user decision.
