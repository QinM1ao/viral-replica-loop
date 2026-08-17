---
name: seedance-25-replica
description: Build, preflight, submit, poll, finish, and download source-faithful Seedance 2.5 replication tasks through the verified Wujie taskCode 2509 route. Use when the user explicitly requests Seedance 2.5, asks to adapt an existing replica Job, or asks to generate a prepared 2.5 Job. Do not use for other Seedance versions or ordinary prompt polishing.
---

# Seedance 2.5 Replica

## Boundary

Own the Seedance 2.5 handoff after source understanding, storyboard acceptance, target identity,
product references, and dialogue approval. Reuse accepted Job artifacts and preserve the ShotLoom
QC and paid-generation stop.

## Required Reading

Before prompt work, read [references/prompt-standard.md](references/prompt-standard.md) and
[references/source-fidelity-contract.md](references/source-fidelity-contract.md). Before request
assembly or submission, also read [references/api-route.md](references/api-route.md).

## Steps

1. Write or validate `seedance25_route_lock.json` with `model_family=Seedance 2.5`,
   `generation_owner=seedance-25-replica`, and `fallback_policy=stop`. Completion: all three values
   match and no generation artifact selects Seedance 2.0.
2. Confirm source duration and accepted storyboard timing. Split in source order at natural
   boundaries so every unit is at most 30 seconds. Completion: the units cover the source interval
   once, in order, without compression or overlap.
3. Select exactly one audio mode and record it in `internal_traceability.json`:
   - `generated_voiceover`: Seedance generates the approved dialogue. A supplied audio reference
     must be a clean timbre sample; the event script owns every spoken word.
   - `original_master_postmix`: Seedance generates visuals without dialogue audio. The approved
     original master is excluded from the provider request and deterministically replaces the raw
     output audio after visual acceptance.
   Completion: the selected mode, prompt, request, and finishing path agree.
4. Decide depth use. Default `depth_reference.enabled=false`. Enable one same-interval camera-only
   depth video only from an explicit user request or accepted Job decision. When enabled it controls
   shot order, cuts, camera position, framing changes, camera movement, and overall camera rhythm;
   storyboard states and the event script own every person, hand, product, trajectory, and state
   change. Completion: the prompt and upload pack contain zero or one depth reference matching the
   recorded decision.
5. Compile the Prompt only from [references/prompt-standard.md](references/prompt-standard.md).
   Visual stages preserve accepted events; speech uses semantic blocks bound to one or more
   consecutive stages. Completion: no internal identifiers appear, every accepted event appears
   once in order, and generated dialogue appears once in complete semantic blocks.
6. Build schema-v5 traceability and run `tools/seedance25_source_fidelity_qc.py`. Completion:
   `source_fidelity_qc.json.overall=PASS`; a fragmented phrase, stale audio mode, undeclared depth,
   internal label, missing event, changed wording, or incomplete spray atomization is a failure.
7. Assemble references in the Prompt's exact numbering order. Include the depth video only when
   enabled and include a clean timbre MP3 only for `generated_voiceover`. Completion: every Prompt
   reference has exactly one uploaded asset and no unreferenced asset is active.
8. Build and preflight the request with [references/api-route.md](references/api-route.md).
   Completion: request QC and runner `--preflight-only` both pass and no `task_create` occurred.
9. Stop before paid generation unless the current Job has explicit approval. With approval, submit
   exactly once through the existing approval/reservation path and poll the same task key.
10. Finish according to audio mode. For `generated_voiceover`, run generated-output ASR and require
    exact normalized transcript equality. For `original_master_postmix`, preserve the raw visual
    output, replace its audio with the approved master, and verify the delivered audio is bound to
    that master. Completion: the selected finishing gate passes.

## Optional Depth Command

Run only when `depth_reference.enabled=true`:

```bash
SKILL_DIR="$(cd "$(dirname "<absolute-path-to-this-SKILL.md>")" && pwd)"
python3 "$SKILL_DIR/../../../tools/depth_reference_pack.py" \
  --source "<source-video>" \
  --output "<unit-folder>/05_仅运镜深度参考.mp4" \
  --source-start "<start-seconds>" \
  --source-end "<end-seconds>" \
  --target-duration "<source-end-minus-start>" \
  --long-edge 1280 \
  --evidence "<unit-folder>/depth_reference_qc.json"
```

## Upload Pack

```text
00_Seedance2.5_提示词.txt
01_分镜参考_<n>.png
02_产品参考.<ext>
03_开盖与液体参考.<ext>        # only when needed
04_女主身份参考.<ext>          # only when needed
05_仅运镜深度参考.mp4          # optional; camera only
06_干净人物音色参考.mp3        # optional; generated_voiceover only
internal_traceability.json
source_fidelity_qc.json
```

Renumber references when optional files are absent. The `@图片N`、`@视频N`、`@音频N` order in
the Prompt must exactly match upload order.
