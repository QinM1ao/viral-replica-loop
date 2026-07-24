# Request Gate

## Stage

`request_qc`

## Purpose

Confirm request bodies are ready for Seedance task submission.

`tools/storyboard_visual_acceptance.py` is the sole semantic storyboard-image conclusion. Reuse its exact-input family PASS; this gate checks request-body, manifest, material-role, prompt-reference, route, and audio synchronization without another visual review.

## Required Inputs

- Seedance prompt files.
- Material-role table.
- Uploaded public URLs for required images and audio.
- Or, for explicit web-side manual Seedance handoff, a final local upload directory containing required images, audio, prompts, manifests, and notes.
- Draft request JSON files.
- Seedance API route choice.
- Seedance model route config: `rules/SEEDANCE_MODEL.json`.
- Approved visual manifest, product group manifest, identity group manifest, and passing visual asset manifest QC.
- Current unified storyboard visual acceptance PASS.
- Passing final audio duration QC when the final handoff contains audio.

## Required Output Artifact

The worker must create `request_qc_*.md` under the job output folder.

It must include:

- API endpoint.
- taskCode.
- Seedance model name and EP.
- Image URL list and role mapping.
- Audio URL list and boundary mapping.
- Prompt file path.
- Request JSON path.
- Final web upload directory mapping to the approved visual manifest when using web-side handoff.
- Visual asset manifest QC path.
- Storyboard geometry / API-effect QC path.
- Audio duration QC path.
- Result: `PASS`, `FAIL`, or `STOP`.

## PASS

Return `PASS` only if:

- API route matches the chosen Seedance route.
- Request body uses the exact selected model route. With no explicit model request, ordinary `Seedance 2.0` uses `model=ep-20260521101914-nwv8j`. Explicit `Seedance 2.0 mini` uses `ep-20260625155850-zpss5`; explicit `Seedance 2.0 Fast` uses `ep-20260521101842-4q4lc`. All other flow variables stay unchanged.
- For taskCode route, audio inputs are public `http(s)` URLs.
- For `taskCode=2509` real-face/Pixmax route, activated material-library `asset://...` references are valid with `role: reference_image`. Identity face inputs must use this face-safe asset route; storyboard/product images may also use Active `asset://...` refs when following the Magic Mirror material-library route or when mixed public-image + asset routing has failed.
- For explicit web-side manual upload, local file paths are allowed only inside the final handoff directory and public URLs are not required.
- For explicit web-side manual upload, every image in the final handoff directory has already passed image sample/batch gates as a target-product/person image. Source-video rhythm boards, contact sheets, cropped source frames, or images with visible old product/person/mud/text cannot pass as upload images.
- For explicit web-side manual upload, `01_图片1` matches the current job `AI改好分镜图`, `02/03` match the active product group, and `04/05` match the active identity group by approved visual manifest.
- `tools/visual_asset_manifest_qc.py` returns `PASS` for `request_qc`.
- The unified geometry/appearance family remains current for the exact uploaded storyboard hash and manifest mapping.
- The body does not mix incompatible routes. For taskCode=2509, public `http(s)` references and Active Pixmax `asset://...` references are both valid, but every `asset://...` image must be an activated material-library asset with `role: reference_image`, and every audio reference must remain a reachable `http(s)` URL unless the provider explicitly supports an audio asset route.
- Human-face inputs use the face-safe taskCode when required.
- Image order matches the material-role table.
- Audio boundaries do not duplicate or drop lines.
- Every image/audio upload listed for web or taskCode route exists, and every audio file is `<=15.00s` by `ffprobe`.
- Prompt files in the final handoff are exactly the approved Seedance prompt files and remain model-facing: no loop-only labels such as `Part1最终分镜图`, `AI改好分镜图`, `current-job`, or `source rhythm board`.
- Request body is saved and can be submitted without further rewriting.

## FAIL

Return `FAIL` if:

- Image order is unclear.
- A local file path is used where public URL is required.
- Web-side manual upload is selected but the final handoff directory is missing images, audio, prompts, manifests, or notes.
- Web-side manual upload contains source-video rhythm boards, contact sheets, cropped source frames, visible old product, visible old person, visible subtitles, visible gray/yellow old mud, or any image that depends on "ignore this part" prompt wording.
- Web-side manual upload contains Python/PIL composites, validated-anchor拼图, old-job Part storyboards for `01`, deprecated drafts, or binding-mismatched reusable references.
- `01/02/03/04/05` final upload images do not match the approved visual manifest.
- Visual asset manifest QC is missing, `FAIL`, or `STOP`.
- Storyboard geometry / API-effect QC is missing, `FAIL`, or `STOP`.
- Any final upload audio file is longer than 15.00s.
- `asset://` is used in a taskCode request outside the `taskCode=2509` activated Pixmax material-library route, or an `asset://` image is not proven Active / not passed with `role: reference_image`.
- taskCode does not match the face/person requirement.
- Request body omits the model EP or does not match the exact default/user-selected route config used for request QC.
- Prompt text in request differs from the approved prompt.
- Final handoff prompt text contains loop-only labels or old internal provenance instead of model-facing reference roles.

Retry variable:

Choose exactly one:

- `upload_urls`
- `image_order`
- `task_code`
- `model_ep`
- `request_body_shape`
- `geometry_appearance`

Locked variables:

Approved prompts, approved references, approved audio boundaries.

## STOP

Return `STOP` if:

- Upload credentials or public URL hosting is unavailable.
- The next action would submit paid/batch generation without approval.

## Next Status

On pass:

```text
seedance_inputs_prepared
```
