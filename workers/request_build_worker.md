# Request Build Worker

## Canonical Stage

`request_qc`

## Purpose

Turn approved Seedance prompts and references into taskCode request bodies, then QC them before generation approval.

Reuse the exact-input family PASS from `tools/storyboard_visual_acceptance.py`. Request assembly validates manifest, material-role, prompt-reference, model-route, audio, and request-body bindings without another storyboard visual review.

## Inputs

- Approved Seedance prompt files.
- Material-role table.
- Product reference image URLs or final web-upload product files.
- Identity reference image URL or final web-upload identity file.
- Storyboard image URLs or final web-upload storyboard files.
- Audio URL or final web-upload audio file and boundary map, if generating with sound.
- Seedance route decision.
- Seedance model route config: `rules/SEEDANCE_MODEL.json` (default ordinary `Seedance 2.0`, `model=ep-20260521101914-nwv8j`). If the user explicitly names Mini or Fast, use a job-scoped route config with that exact EP; never reinterpret `Seedance 2.0` as Mini.
- Approved visual manifest, product group manifest, identity group manifest, and passing visual asset manifest QC.
- Current unified storyboard visual acceptance PASS.
- `gates/request_gate.md`.

## Actions

1. Read approved prompt files and material-role table.
2. Read the approved visual manifest and confirm the selected route uses only approved assets.
3. Confirm the intended API route.
4. Upload or confirm public `http(s)` URLs for taskCode inputs.
5. Build request body drafts.
6. Verify:
   - endpoint
   - taskCode
   - model EP equals `rules/SEEDANCE_MODEL.json`
   - image order
   - for web-side manual upload, `01` matches current-job `AI改好分镜图`, `02/03` match the active product group, and `04/05` match the active identity group
   - reference role mapping
   - audio boundary mapping
   - every audio file is `<=15.00s` by `ffprobe`; target `14.90s`
   - prompt text matches approved prompt
   - final prompt text uses model-facing reference roles and does not contain loop-only labels such as `Part1最终分镜图`, `AI改好分镜图`, `current-job`, or `source rhythm board`
   - for web-side manual upload, final upload assets, prompts, manifests, audio, and notes are collected in one final output directory
7. Run `tools/visual_asset_manifest_qc.py --stage request_qc --check-final-dir`.
8. Save request bodies and request QC.
9. Stop before paid or batch Seedance submission.

## Scripted Part

For web-side manual upload, run strict final audio duration QC:

```bash
python3 viral-replica-loop/tools/audio_duration_qc.py \
  --audio viral-replica-loop/output/<job-id>/seedance_web_final/Part1_上传素材/06_音频1_Part1原爆款声音参考.mp3 \
          viral-replica-loop/output/<job-id>/seedance_web_final/Part2_上传素材/06_音频1_Part2原爆款声音参考.mp3 \
  --max-seconds 15.0 \
  --out-json viral-replica-loop/output/<job-id>/seedance/requests/final_upload_audio_duration_qc.json \
  --out-md viral-replica-loop/output/<job-id>/seedance/requests/final_upload_audio_duration_qc.md
```

Use this script after taskCode request JSON files are created:

```bash
python3 viral-replica-loop/tools/request_body_qc.py \
  --requests viral-replica-loop/output/<job-id>/seedance/requests/part1_request_prepared.json \
             viral-replica-loop/output/<job-id>/seedance/requests/part2_request_prepared.json \
  --prompt-files viral-replica-loop/output/<job-id>/seedance/seedance_part1_prompt.txt \
                 viral-replica-loop/output/<job-id>/seedance/seedance_part2_prompt.txt \
  --allowed-task-codes 2509 2508 2506 \
  --model-route-config viral-replica-loop/rules/SEEDANCE_MODEL.json \
  --require-public-urls \
  --expected-endpoint task_create \
  --out-json viral-replica-loop/output/<job-id>/seedance/requests/request_qc.json \
  --out-md viral-replica-loop/output/<job-id>/seedance/requests/request_qc.md
```

The script checks JSON validity, taskCode, model EP, public URLs, `asset://` misuse, local file paths, and prompt embedding.

## Outputs

Write under `output/<job-id>/seedance/requests/`:

- `part1_request_prepared.json`
- `part2_request_prepared.json`
- `request_qc.md`
- `final_upload_audio_duration_qc.json` / `.md` when audio is present

Write under `output/<job-id>/checks/`:

- `request_qc_visual_asset_manifest_qc.json`
- `request_qc_visual_asset_manifest_qc.md`

## Gate

Run:

`gates/request_gate.md`

## PASS Next Status

`seedance_inputs_prepared`

## FAIL Retry Variables

Choose exactly one:

- `upload_urls`
- `image_order`
- `task_code`
- `model_ep`
- `request_body_shape`

## Stop Conditions

- Public URLs are missing.
- Upload credentials are unavailable.
- Request body would trigger paid generation without approval.
