# Viral Replica Loop QC Rules

## Universal Gates

- First do source-video story analysis. Do not write voiceover or Seedance prompts from storyboard images alone.
- Product name and product assets from `BRIEF.md` / `jobs.csv` override source-video old product details.
- Every job must have `output/<job-id>/product_profile.json`; generic product rules always load, and category/brand/SKU rules load only from that profile.
- Read `PRODUCT_CONSTRAINTS.md` before image, prompt, or request stages.
- Advance one job and one stage per round.
- Every stage writes `STATE.md`, a job artifact, and a gate result.

## Story Analysis Gate

- Record ASR, subtitle layer when visible, visual timeline, story function, and shot-level replacement strategy.
- If subtitles exist, use both subtitle timing and ASR timing. Subtitle timing anchors shot rhythm; ASR catches speech, pauses, and missing captions.
- Every key shot should include visual action, subtitle text, ASR text, and replication strategy.
- Identify old-product, old-person, caption, prop, texture, and packaging contamination before storyboard work.

## Storyboard Gate

- Preserve source shot order and sales function.
- For videos over 15 seconds, choose seam points from the full shot flow instead of cutting mechanically at 15.00s.
- Do not cut on a speaking face, summary sentence, restart sentence, or major scene jump.
- Build a contamination audit before GPT Image or Seedance.
- Remap old product actions to the target product's real actions.
- If the source product texture is a high-risk contaminant, that shot may pass only camera/action/beat, not product material.

## GPT Image Gate

- Image sample, image batch, after-wash reference, and repair use the Matpool GPT-Image-2 project route only: `.agents/skills/video-replication/scripts/generate.py` with `MATPOOL_API_KEY`.
- Matpool GPT-Image-2 must be run as a real edit/reference route: actual local source storyboard, product profile-declared product/material refs, and identity images are submitted as multipart `image` files; local paths in text are not enough.
- Do not try any deprecated GPT Image route or gateway probe.
- Before GPT Image sample or image batch PASS, write `codex_imagegen_contract.json` and pass `tools/codex_imagegen_contract_qc.py`. The contract must use route `matpool_gpt_image_2_edit`, prove real image inputs were submitted, and say the source storyboard transfers layout/shot order/framing/action rhythm only, not old product, old tool, old host identity, old mud color, or subtitles.
- Before image batch, Seedance prompt, or request handoff PASS, run `tools/storyboard_geometry_qc.py`. Use `job-002` as the correct API-edit baseline: the generated storyboard may be a uniform higher/lower-resolution output from ImageGen, but it must keep the source Part canvas aspect, orientation-specific grid, relative panel sizing, panel positions, and shot order. A recomposed 12-panel template, changed grid, stretched canvas, or visibly squeezed subject is `FAIL`.
- After image batch PASS, visual QC is hash-gated. If active Part image hashes and approved visual manifest mapping have not changed, downstream stages reuse existing visual PASS evidence instead of rerunning storyboard geometry, cross-Part continuity, skincare progression, mud review, or GPT Image contract QC.
- Prompt and request stages still run lightweight sync checks every time: final-dir manifest mapping, prompt/request text sync, active upload directory cleanliness, final audio duration, and stop/cost gates.
- Heavy visual QC reruns only when an active image hash changes, manifest mapping changes, reference-role mapping changes, or the user reports a visible defect.
- Visual warnings are non-blocking. A warning may continue only when the review records `why_not_fail`, such as: the mud is visibly white and thick despite a tiny threshold miss, or the canvas has tiny uniform API-style drift but no visible squeeze. Warnings cannot cover source contamination, missing evidence, wrong product, wrong person, wrong wardrobe, visible squeeze, changed shot order, or unsaved outputs.
- Translate source tube/stick/brush/arm-swatch actions into the loaded product profile's real usage action before generation. For clay-mask profiles, this means finger pickup from the open jar and fingertip face application. Do not put old tool names into the image prompt as negative anchors; write only the target action.
- For localized failures, use fast repair: one target image/panel, one changed variable, one hard check, one visual check, then sync to final output paths. Do not rerun the whole loop or rebuild unrelated artifacts.
- Run one sample before batch image work only as an internal direction check. Do not stop for user-facing sample approval unless the user explicitly asks to preview samples.
- Reject hard failures internally and repair or stop with evidence. Do not ask the user to adjudicate image-stage hard failures.
- After batch image generation, write image QC before voiceover or Seedance.
- Check layout, shot order, identity, wardrobe, scene, product form, product label, product texture, subtitles, old-source contamination, and cross-part color consistency.
- Unknown packaging, blank products, old host identity, old product texture, wrong tool, wrong scene, or changed grid layout are failures.
- For profiles that load clay-mask rules, yellow/beige/tan/cream-yellow/gray/watery mud is a hard failure. Face-applied mud and open-jar mud must be white/milky-white thick paste before downstream Seedance work.
- For single-model jobs, use one approved identity anchor unless the brief says otherwise.
- Save every attempt with prompt, refs manifest, QC output, and failed/pass note.

## Voice And Seam Gate

- Voiceover must be based on source story analysis, subtitle layer, ASR, and approved images.
- Product name and selling points must land on the correct visual shots.
- Multi-part videos need a seam design with previous ending state and next starting motion.
- The next part cannot start with a static face or frozen proof frame.
- Speech should not cross the seam. Leave a short no-speech buffer around boundaries.
- Multi-part videos default to no BGM; keep dialogue, environment sound, and real operation sound.

## Audio Gate

- For sound-enabled multi-part jobs, cut reference audio on sentence boundaries.
- Run ASR on each reference audio part.
- Confirm adjacent parts do not repeat or drop boundary lines.
- Keep every Seedance/web-upload reference audio file `<=15.00s`; target `14.90s` to leave encoder/UI tolerance. Anything over 15.00s is `FAIL`.
- If the job is silent, write a skip note rather than pretending audio QC ran.

## Seedance Gate

- Use clean, submit-ready prompts only. Do not include internal plans, failure history, or irrelevant negative terms.
- Preserve source shot order and shot function. Avoid broad generic ad blocks.
- Bind every spoken line to the correct shot and wrap spoken lines in Chinese quotation marks.
- Use material-role tables: storyboard controls shot/action, identity image controls face, product images control product, washed-skin image controls only after-use skin if applicable.
- Washed-skin references must be generated face close-ups from the approved identity, not cropped panels from storyboard images.
- Do not use old rejected details in prompts unless they still exist in approved references.
- Use public `http(s)` URLs for taskCode request audio. Images may be public `http(s)` URLs or Active Pixmax material-library `asset://...` refs when using `taskCode=2509`.
- Real-face inputs require the approved face-safe route: create an activated material-library asset first, then pass `asset://...` with `role: reference_image` when using `taskCode=2509`. If mixed public-image + identity-asset routing fails, convert storyboard and product images to Active `asset://...` refs too, keeping audio on public `http(s)` URLs.
- Stop before paid or batch generation.

## Request Gate

- Request JSON must match the approved prompt text.
- Image order must match the material-role table.
- For web-side manual Seedance handoff, final upload images, audio, prompts, manifests, and notes must be collected into one final output area before stopping.
- Every final handoff audio file must be checked with `ffprobe` and be `<=15.00s`; target `14.90s`.
- Audio boundary mapping must match approved audio QC.
- taskCode must match the face/person requirement.
- Local file paths, missing reachable audio URLs, unproven asset refs, or incompatible mixed route references are failures. A taskCode=2509 request that combines public audio with Active Pixmax `asset://...` image refs is valid.

## Final Gate

- Run ffprobe and freeze detection.
- For sound-enabled videos, run final ASR.
- Check product name, product visibility, face continuity, wardrobe continuity, skin/color continuity, seam motion, subtitles, duplicated lines, missing lines, and rushed speech.
- Check only objective hard failures: missing/unreadable video, missing streams, wrong duration, freeze/black/blank frames, duplicated or missing speech, broken seam, or obvious wrong person/product/wardrobe/mud/scene.
- If technical QC passes, deliver the final video. Do not stop for subjective final effect review; the user judges subjective effect after delivery.
- If final QC fails and needs Seedance regeneration, allow at most one targeted retry. A repeated technical failure or second paid retry stops.
