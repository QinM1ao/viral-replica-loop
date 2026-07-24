# Seedance Prompt Gate

## Stage

`seedance_prompt`

## Purpose

Confirm Seedance prompts and request-prep notes are clean, shot-accurate, and safe to turn into task request bodies.

`tools/storyboard_visual_acceptance.py` is the sole semantic storyboard-image conclusion. Reuse its exact-input family PASS; this gate only validates prompt, manifest, material-role, and reference-role synchronization.

## Required Inputs

- Approved final storyboard images.
- `output/<job-id>/visual-assets/approved_visual_manifest.json`.
- Product group manifest and identity group manifest.
- `output/<job-id>/product_profile.json`.
- Passing visual asset manifest QC.
- Current unified storyboard visual acceptance PASS.
- Product front reference, tightly cropped.
- Product material/open reference only when required by the product profile.
- Approved single identity reference.
- Dedicated generated after-wash face reference only when the product profile explicitly requires it.
- Story analysis artifact with subtitle + ASR + visual shot mapping.
- Seam design or boundary notes.
- Seedance 2.0 prompt standard: `.agents/skills/video-replication/references/seedance-20-prompt-standard.md`.
- Seedance prompt contract QC showing every shot-line map row appears inside an ordered `time | Shot 01–02` block with bound visual/voice and optional visible-action SFX.
- `PRODUCT_CONSTRAINTS.md`.
- Relevant `QC_RULES.md` Voice, Seam, Audio, and Seedance rules.

## Required Output Artifacts

The worker must create:

- Seedance Part prompt files.
- Material-role table.
- Request-prep notes or request body drafts.
- Prompt QC artifact.
- Seedance prompt contract QC artifact.
- Visual asset manifest QC artifact.
- Storyboard geometry / API-effect QC artifact.

## PASS

Return `PASS` only if:

- Prompt uses the source video's shot rhythm, not a generic ad rhythm.
- Prompt references only assets approved by the visual manifest.
- The current job Part storyboard images are `AI改好分镜图`; product/identity/after-wash support refs are not used as substitute Part storyboards.
- Product support references come from the same active product group.
- Identity reference and after-wash face reference come from the same active identity group.
- `tools/visual_asset_manifest_qc.py` returns `PASS`.
- The unified geometry/appearance family remains current for the exact active storyboard hashes and manifest mapping.
- Subtitle layer, ASR layer, and visual shot table are all reflected.
- Voiceover lines are bound to the correct shots.
- Source speaker mode is recorded and preserved row by row: source口播/同期声 stays target口播/同期声, source画外音旁白 stays target画外音旁白.
- Spoken lines are wrapped in Chinese quotation marks.
- Prompt explicitly preserves shot order and does not add, delete, or reorder shots.
- 15 second Seedance 2.0 Parts use a model-facing production brief: reference roles followed by ordered `time | Shot 01–02` blocks.
- Every block binds `画面 / 声音`; `音效` appears only for a useful visible action sound. Source speaker mode and hard cuts are preserved, and actions are source-supported or explicit product translations.
- No block crosses a scene, visual-function, or spoken speaker-mode boundary. In-frame sync speech and narration are separate, and short still-life B-roll is standalone.
- Identity references do not transfer their background or override Shot-specific skin state. Multi-scene Parts include a compact Shot scene map.
- Presenter/product blocks before and after a source B-roll hard cut use matched source-scene framing and do not add a dissolve or restart the product push.
- Skincare after-wash wording reaches the brief/profile result and does not automatically weaken it with “保留真实毛孔/皮肤纹理”.
- A standalone `声音执行` section or generic `Shot 1/2/3` summary is invalid.
- `tools/seedance_prompt_contract_qc.py` returns `PASS`.
- Final prompt text names reference roles by model meaning, not loop internals; it must not say `Part1最终分镜图`, `Part2最终分镜图`, `AI改好分镜图`, `current-job`, `source rhythm board`, `contact sheet`, or `素材角色表`.
- Prompt is clean: no internal complaints, old failure history, or irrelevant negative words.
- Product front and any required product material/open references are split, not merged into a wide sheet.
- Clay mask texture is described as white, thick, creamy mud with a stable peak only when the loaded product profile is clay-mask.
- Washed-skin reference is required only when the product profile declares it; when used, it is a dedicated generated face close-up and appears only after washing or proof shots, not at the start of a segment.
- Seam wording starts the next part in motion and does not ask for a static face frame.
- The prompt stops before paid or batch Seedance generation.

## FAIL

Return `FAIL` if:

- Prompt ignores the original shot rhythm.
- Voiceover is detached from the product or shot timing.
- Source speaker mode is missing from the shot-line map, or the prompt changes source口播 into旁白 / source旁白 into口播.
- Product references are merged into a wide sheet when separate refs are available.
- The prompt includes pollution terms that are not in the approved references.
- The prompt uses loop-internal labels such as `Part1最终分镜图`, `Part2最终分镜图`, `AI改好分镜图`, `current-job`, `source rhythm board`, `contact sheet`, or `素材角色表` as if the video model understands them.
- The prompt collapses the source video's key beats into generic product display, talking-head, or skincare routine rhythm.
- The prompt omits shot-line map target-time rows or only writes three broad Shot ranges without internal timing.
- An execution block mixes narration with in-frame sync speech, merges still-life B-roll into a presenter block, or inherits the identity-reference background.
- The source has a phone proof shot, product-name close-up, rinse/wipe proof, or final product close-up, but the final prompt does not describe the matching beat.
- It says gray mud, tube applicator, zipper, bathroom, or other old rejected details when they are not present in the final references.
- It binds washed-skin reference before the wash action.
- It uses a cropped storyboard panel as the washed-skin reference.
- It uses more than one male identity reference.
- It asks Seedance to ignore visible old pixels, source products, old hosts, old mud, subtitles, or "motion-only" contamination.
- It references source rhythm boards, contact sheets, Python/PIL composites, old-job storyboards, or deprecated drafts as upload/support images.
- The visual manifest or visual asset manifest QC is missing or failing.
- Storyboard geometry / API-effect QC is missing or failing.

Retry variable:

Choose exactly one:

- `shot_rhythm_mapping`
- `voiceover_binding`
- `material_role_table`
- `seedance_20_prompt_structure`
- `product_reference_order`
- `seam_motion_wording`
- `geometry_appearance`

Locked variables:

Approved storyboard images, approved product references, approved identity reference.

## STOP

Return `STOP` if:

- Any required approved reference image is missing.
- The next action would submit a paid or batch Seedance generation.
- The prompt depends on subjective rhythm tradeoffs that need user approval.

## Next Status

On pass:

```text
seedance_prompt_done
```
