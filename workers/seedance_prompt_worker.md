# Seedance Prompt Worker

## Canonical Stage

`seedance_prompt`

## Purpose

Rebuild Seedance prompts and request-prep notes from approved storyboard images, product references, identity reference, and the source video's subtitle + ASR + visual rhythm.

Reuse the exact-input family PASS from `tools/storyboard_visual_acceptance.py`. Prompt changes run only prompt/reference synchronization checks; they do not open another storyboard visual review.

## Inputs

- Approved final Part images.
- `output/<job-id>/visual-assets/approved_visual_manifest.json`.
- Product group manifest and identity group manifest.
- `output/<job-id>/product_profile.json`.
- Passing visual asset manifest QC.
- Current unified storyboard visual acceptance PASS.
- Story analysis with subtitle + ASR + visual shot table.
- Seam design or boundary notes.
- Product front reference, tightly cropped.
- Product material/open reference only when required by the product profile.
- Approved single identity reference.
- Dedicated generated after-wash face reference only when the product profile explicitly requires it.
- `.agents/skills/video-replication/references/seedance-20-prompt-standard.md`.
- `PRODUCT_CONSTRAINTS.md`.
- `QC_RULES.md`.
- `gates/seedance_prompt_gate.md`.

## Actions

1. Read the source shot table, ASR, and subtitle layer together.
2. Read the approved visual manifest and confirm the Part images are current-job `AI改好分镜图`, while product/identity and any profile-required after-wash refs are binding-group reusable refs.
3. Run or reuse a passing `tools/visual_asset_manifest_qc.py --stage seedance_prompt` report before writing the gate review.
4. Rebuild the shot rhythm map so every time block maps to source shot function.
5. Bind each spoken line to the correct shot, with source speaker mode and target speaker mode recorded separately. Preserve the source mode exactly: source口播/同期声 stays target口播/同期声, source画外音旁白 stays target画外音旁白.
6. Wrap all spoken script in Chinese quotation marks.
7. Create a material-role table:
   - storyboard image controls shot order, framing, and action
   - identity reference controls the approved person and clothing only; it does not control scene/background or Shot-specific skin state
   - product front controls the current product form and label
   - product material/open reference controls product texture only when required by the profile
   - after-wash reference controls only post-wash skin quality when required by the profile and must not be a crop from the storyboard
8. Write clean Seedance 2.0 prompts using the numbered-storyboard audio-visual format:
   - open `.agents/skills/video-replication/references/seedance-20-prompt-standard.md` and its validated example first, then copy only their structure
   - start with model-facing reference roles, not internal file provenance
   - use ordered `time | Shot 01–02` execution blocks for a 15 second Part
   - bind `画面 / 声音` inside every block; add `音效` only for a useful visible action sound and never write `音效：无`; never create a separate audio-execution section
   - split blocks at scene, visual-function, or speaker-mode changes; in-frame sync speech and narration cannot share a block, and short still-life B-roll is standalone
   - for hard cuts around B-roll, match the source scene, product framing, and product position before and after the B-roll instead of adding a dissolve or restarting the action
   - use a compact per-Part Shot scene map when scenes vary or the identity reference background differs from the source
   - cover every current shot-line map row and every storyboard Shot; broad `Shot 1/2/3` paragraphs are invalid
   - keep each row's target speaker mode identical to the row's source speaker mode
   - preserve must-keep source beats, source hard cuts, and only source-supported or explicit product-translated actions
   - require every sound effect to correspond to the visible target action
   - bind each quoted line to the matching source shot function
   - no internal notes
   - no old failure history
   - no irrelevant negative terms
   - no generic ad rewrite
   - no `Part1最终分镜图`, `AI改好分镜图`, `current-job`, `source rhythm board`, or similar loop-only terms in final prompt text
9. Run `python3 tools/seedance_prompt_contract_qc.py --job-id <job-id> --stage seedance_prompt` and require PASS.
10. Run a prompt hygiene check against `.agents/skills/video-replication/references/seedance-qc-gates.md`.
11. For skincare results, write the exact brief/profile outcome in the wash-finished Shot. Do not automatically add “保留真实毛孔/皮肤纹理” when it weakens the required commercial result.
12. Write seam wording so the next part starts in motion, not as a static face frame.
13. Stop before paid or batch Seedance generation.

## Outputs

Write under `output/<job-id>/seedance/`:

- `seedance_part1_prompt.txt`
- `seedance_part2_prompt.txt`
- `seedance_素材角色表.md`
- `seedance_prompt_qc.md`
- `output/<job-id>/checks/seedance_prompt_seedance_prompt_contract_qc.md`
- `output/<job-id>/checks/seedance_prompt_visual_asset_manifest_qc.json`
- `output/<job-id>/checks/seedance_prompt_visual_asset_manifest_qc.md`
- request-prep notes if available

Do not submit Seedance generation from this worker.

## Gate

Run:

`gates/seedance_prompt_gate.md`

## PASS Next Status

`seedance_prompt_done`

## FAIL Retry Variables

Choose exactly one:

- `shot_rhythm_mapping`
- `voiceover_binding`
- `material_role_table`
- `seedance_20_prompt_structure`
- `product_reference_order`
- `seam_motion_wording`

## Stop Conditions

- Required approved reference is missing.
- Prompt would require subjective rhythm approval.
- Next action would submit paid or batch generation.
