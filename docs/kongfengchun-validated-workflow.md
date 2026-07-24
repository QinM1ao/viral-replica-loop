# Kongfengchun Validated Workflow

## Current Status (2026-07-17)

The current Seedance workflow standard is the provider-validated complete `job-011` Part1+Part2 case:

```text
.agents/skills/video-replication/references/kongfengchun-final-26s-standard.md
output/job-011/final-delivery/
```

It replaces the Part2-only and older fermented-toner examples as the preferred complete-flow standard. The 2026-06-17 `job-001` material below remains a historical web-packaging record only; its mandatory after-wash image and older prompt wording must not be copied into new jobs.

Date: 2026-06-17

This document records the validated web-side Seedance handoff for `孔凤春清洁泥膜`.

## Scope

- Job: `job-001`
- Product: `孔凤春清洁泥膜`
- Source video: private local source video used for the validated run; not included in the repository.
- Final handoff directory: `output/job-001/seedance_web_final/`
- Result: the user ran the final Seedance web step and confirmed the output effect is acceptable.

Codex stopped before paid/API Seedance generation. The validated final generation happened in the user's web membership account.

## Final Upload Area

Use only files under:

```text
output/job-001/seedance_web_final/
```

The directory must contain active upload assets only:

```text
Part1_上传素材/
Part2_上传素材/
prompts/
manifests/
README_网页端上传说明.md
素材修正记录.md
```

Do not upload deprecated drafts, archived prompts, old audio, old yellow-mud Part1 images, or files from sibling output folders.

## Upload Order

For each part, upload files by filename prefix:

```text
01 final storyboard image
02 product front image
03 open white-mud jar image
04 approved male identity image
05 generated after-wash face close-up
06 original-hit audio reference
```

Then paste the matching prompt from:

```text
output/job-001/seedance_web_final/prompts/
```

Active prompt lengths on 2026-06-17:

- Part1: 1423 characters
- Part2: 1435 characters

The short prompt version was rolled back. Use the active prompt files in the final handoff directory.

## Validated Visual Asset Groups

Reusable references are registered as binding groups:

```text
output/shared/kongfengchun/products/kongfengchun_clean_mud_mask/
output/shared/kongfengchun/identities/kongfengchun_male_content4/
```

The per-job approved visual manifest is:

```text
output/job-001/visual-assets/approved_visual_manifest.json
```

For future `孔凤春清洁泥膜` jobs, the product group refs may be reused only when the product asset folder matches. The identity and after-wash face refs may be reused only when the active model identity is the same `content 4.png` identity. Each new job still needs its own current-job `AI改好分镜图` for `01_图片1`; do not reuse `job-001` Part storyboard images as another job's Part storyboard.

## Required Checks Before Handoff

- `output/job-001/seedance_web_final/` contains only active upload files and notes.
- Both final audio files pass `tools/audio_duration_qc.py` with `<=15.00s`; target duration is `14.90s`.
- `tools/visual_asset_manifest_qc.py --job-id job-001 --stage request_qc --check-final-dir` passes.
- Part1 face-applied mud and open-jar mud are white or milky-white thick paste, not yellow, beige, tan, cream-yellow, gray, or watery.
- The after-wash proof is a generated face close-up from the approved model identity, not a crop from a storyboard panel.
- Product front and open-jar white-mud references are separate upload files.
- The single male identity anchor is `content 4.png`; do not mix in `content 5.png` or female model images.
- Multi-part output defaults to no BGM unless the brief explicitly requests music.

## What Was Fixed

- Part1 was rejected after the new mud-color rule because the face mud looked yellow/beige.
- The rejected Part1 is archived under `output/job-001/final-images/deprecated_yellow_mud_part1_20260616/`.
- The approved Part1 replacement is synced to:

```text
output/job-001/final-images/part1_seedance_ref.png
output/job-001/seedance/seedance_refs/01_part1_clean_storyboard.png
output/job-001/seedance_web_final/Part1_上传素材/01_图片1_Part1最终分镜.png
```

- The after-wash reference was replaced by a generated face close-up and synced to:

```text
output/job-001/seedance/seedance_refs/06_afterwash_generated_face_closeup.png
output/job-001/seedance_web_final/Part1_上传素材/05_图片5_生成洗后脸部特写.png
output/job-001/seedance_web_final/Part2_上传素材/05_图片5_生成洗后脸部特写.png
```

## Future Kongfengchun Runs

For `job-002`, `job-003`, or new `孔凤春清洁泥膜` videos:

1. Read `client-profiles/kongfengchun/README.md` before generic product rules.
2. Use only the project Matpool GPT-Image-2 route for image sample, image batch, any profile-required after-wash reference, and localized repair.
3. Deprecated GPT Image routes are not fallback options.
4. Preserve the source video's subtitle, ASR, visual rhythm, and sales function.
5. Reject wrong mud color before writing Seedance prompts or request handoff.
6. Use fast repair for localized failures; do not rerun the whole image pipeline when one panel or one material cue fails.
7. Package the web-side handoff into one final output directory before stopping.
8. Stop before paid/API Seedance generation unless the user explicitly approves that route.

## Prompt Standard Update

Historical prompt baseline date: 2026-06-20

`job-001` remains the historical web-side packaging baseline and `job-002` remains the storyboard-geometry baseline. For current prompt writing and final assembly, use the 2026-07-17 `job-011` complete case above.

Historical prompt files:

```text
output/job-002/seedance_web_final/prompts/Part1_Seedance提示词.txt
output/job-002/seedance_web_final/prompts/Part2_Seedance提示词.txt
```

For future `孔凤春清洁泥膜` prompts:

- Write model-facing reference roles, not internal loop names.
- Use ordered `time | Shot 01–02` execution blocks with `画面 / 声音` bound inside every block; add `音效：<...>` only for a useful visible action sound and omit the line otherwise.
- Preserve source key beats and hard cuts; do not turn a phone proof shot, product-name close-up, wash proof, or final product close-up into generic talking-head footage.
- Do not invent setup actions that the source does not show, and do not add an action merely to justify a sound effect.
- Keep product-name lines on product close-ups.
- Keep mud white or milky-white and thick; reject yellow, beige, tan, cream-yellow, gray, watery, or source-contaminated mud before handoff.
- Split execution blocks whenever scene, visual function, or speaker mode changes. A short still-life B-roll beat is its own block and cannot share a block with presenter sync speech.
- Keep the source hard cut around B-roll. Match the presenter/product framing before and after the B-roll instead of adding a dissolve or restarting the product push.
- The identity reference locks the presenter, not its background or the skin result. Current profile defaults use prompt-controlled after-wash improvement and do not require an extra after-wash image.
- For the current profile, the after-wash Shot must state the full commercial result and must not add “保留真实毛孔/皮肤纹理”.
