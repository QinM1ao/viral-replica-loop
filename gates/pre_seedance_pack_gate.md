# Pre-Seedance Pack Gate

## Stage

`pre_seedance_pack`

## Purpose

Decide whether the job is ready to stop at Pre-Seedance Handoff or continue to paid Seedance approval.

This gate replaces the old default sequence of separate voiceover, seam, Seedance prompt, audio boundary, and request gates. The older gates remain valid for legacy statuses and focused repairs.

## Required Inputs

- Passed story analysis with ASR/subtitle/visual shot table.
- Approved final Part images and `approved_visual_manifest.json`.
- Existing image batch QC or hash-gated reuse summary.
- Voiceover/script with speaker roles.
- `voiceover/source_script_fidelity.md` generated from a v6 `source_locked` director plan, with a `line_edits` list for every speech group.
- `voiceover/source_replication_fidelity.md` generated from the same plan, with a `visual_edits` list for every target beat.
- Shot-line map from source beats to target actions.
- Replication function coverage ledger rendered from complete source evidence.
- Seam boundary notes when there is more than one Part.
- Per-Part Seedance prompts.
- Seedance prompt contract QC showing ordered `time | Shot 01–02` blocks cover every shot-line map range, every block binds visual/voice, optional SFX appears only for visible action sounds, and every source speaker mode is preserved.
- The same prompt contract QC must PASS the per-Part speech budget and exact prompt-to-plan spoken-line match.
- Material-role table.
- `output/<job-id>/seedance/director_plan.json` and rendered `seedance/handoff_mode.json`.
- Reference audio files and audio duration QC when sound is enabled.
- Request body QC for `api|both`, or final-directory web handoff QC for `web|both`.
- Checker review QC.
- `checks/pre_seedance_pack_qc_bundle.json` showing every mode-appropriate deterministic QC task passed.

## Required Output Artifact

The worker must create a Pre-Seedance pack review artifact under:

```text
output/<job-id>/checks/pre_seedance_pack_gate_review.md
```

It must include:

- Current task and stage.
- Active image hashes or reused visual QC evidence.
- Prompt paths.
- Request or web-side handoff paths.
- Seedance prompt contract QC path.
- Audio duration evidence when audio exists.
- Verification commands and results.
- Result: `PASS`, `FAIL`, or `STOP`.

## PASS

Return `PASS` when all of these are true:

- Voiceover, shot-line map, seam notes, Seedance prompts, audio boundary evidence, and request/handoff files are complete for every required Part.
- Final prompts are derived from story analysis and distinguish narration, in-frame synchronous speech, supporting-role speech, and group reactions.
- Every target line is the evidence-confirmed source line after only the declared localized edits. Original wording, sentence order, repetitions, speaker mode, emphasis, and pause structure remain locked.
- Every `product_fact` / `price_or_offer` edit is hash-bound to the current product profile and exact from/to slot; profile omission alone is not a conflict, and a frequency edit requires a directly contradictory profile frequency. Every `person_or_role` edit is bound to the current user request. The independent checker returns one explicit necessity/minimality/evidence result for every requested line edit ID.
- Objects already removed from the approved storyboard remain only in internal `visual_edits` evidence. Final model-facing prompts describe the retained scene and actions without repeating “前景无产品”, “不陈列产品”, “不出现旧产品”, or similar resolved-object negatives.
- Every source-length target covers every source beat exactly once and in order, with exactly one source beat per target beat and source-scaled beat timing. Source actions, source lines, source speaker modes, transitions, and action stages match `source_rhythm.json`; target visual differences are limited to declared necessary edits while shot order, scene, camera, framing, action stage/timing, and hard cuts remain locked.
- Product-name mentions preserve the source count, placement, sentence structure, and repetition. Every product-name edit binds its exact selected occurrence to the current source-rhythm beat and a hash-bound independent product-entity confirmation. The product anchor is disabled when the source has no spoken product name and never authorizes injecting a new line.
- Final prompts preserve source speaker mode row by row: source口播/同期声 stays target口播/同期声, source画外音旁白 stays target画外音旁白.
- Final prompts preserve every shot-line map range inside ordered `time | Shot 01–02` blocks; broad `Shot 1/2/3` summaries are invalid.
- Visual beats and speech groups remain separate internally, then bind together in the final prompt. Every spoken source beat is bound exactly once and no standalone `声音执行` section exists.
- No execution block crosses a scene, visual-function, or spoken speaker-mode boundary. In-frame sync speech and narration are separate; short still-life B-roll is a standalone block.
- Identity references do not transfer their background or override Shot-specific skin state. Multi-scene Parts include a compact Shot scene map.
- Source hard cuts around B-roll remain hard cuts; the presenter/product blocks before and after B-roll use matched source-scene framing instead of adding a dissolve or restarting a push.
- Every target action is supported by the source video/storyboard or an explicit product-profile translation. Source hard cuts stay hard cuts, and every sound effect corresponds to a visible target action.
- Every 15-second Part passes the source-aware capacity and speaker-mode rules in `.agents/skills/video-replication/references/voiceover-capacity-and-compression.md`.
- Independent checker confirms every must_keep / mergeable source function has real target speech or visual evidence; capacity PASS alone is insufficient.
- The final prompt contains exactly the speech-group lines and no additional model-facing dialogue.
- The reference-role preamble uses the standard `定义为 -> 只控制/锁定 -> 不传递` format; it does not switch to a free-form `控制校准` variant. Storyboard-derived multi-person jobs bind only each Part's required identity refs.
- Product references calibrate packaging/label/material only; source storyboard references control composition, hand action, and shot rhythm.
- No loop-only labels appear in final prompt text.
- No unsubmitted-source references appear in final prompt text: internal `原片/源片/原视频/source video/source rhythm/source beat` evidence must be compiled into explicit Shot actions or bound `@image/@audio` references.
- Prompt/request text and material-role table are synced.
- Seedance prompt contract QC passes for the final prompt files and shot-line map.
- Visual asset manifest QC passes for the current final directory or request mapping.
- Request body QC passes when `handoff_mode` includes API requests; web-only jobs do not create or validate unused request JSON.
- Every web-upload audio file is `<=15.00s` when audio is present.
- Heavy visual QC is either current or validly reused by active image hashes and mappings.
- The reused semantic image conclusion comes from `tools/storyboard_visual_acceptance.py`; this gate does not open separate geometry, continuity, or skincare reviews.
- A v4 director plan binds the current `source_rhythm.json` hash; a prompt authored from an older analysis cannot PASS.
- Paid Seedance generation has not been submitted by this stage.

## FAIL

Return `FAIL` if:

- A line, source beat, speaker role, seam state, product proof, or request field is wrong but can be repaired locally.
- A target line is merely semantically similar to the source instead of being the exact source line plus declared `line_edits`, or a prompt/voiceover file rewrites the locked target line.
- A source visual action differs from its bound rhythm beat, a target visual action differs without one allowed `visual_edits` record, or a declared edit changes a locked shot/scene/camera/framing/action-stage/hard-cut dimension.
- A source-length plan drops, duplicates, reorders, or folds away a source beat; or a compressed plan lacks explicit user evidence.
- Final prompts omit any storyboard-panel range, use a generic `Shot 1/2/3` paragraph, or separate audio from its visual block.
- An execution block mixes in-frame sync speech with narration, merges still-life B-roll into a presenter block, or lets the identity-reference background replace a Shot scene.
- A target action invents a missing setup step, merges a source hard cut into one continuous action, or adds an action only to justify a sound effect.
- Shot-line map rows lack source speaker mode, or target speaker mode changes source口播 into旁白 / source旁白 into口播.
- Speech groups exceed any count, density, sync-line, or silence limit; a spoken source beat is unbound or multiply bound; or the prompt adds a spoken line not present in the plan.
- Reference audio has a boundary duplicate/drop or exceeds the strict duration limit.
- Prompt text lets product packshots control scene composition.
- Request JSON does not match the approved prompt, asset order, taskCode, model EP, or audio mapping.

Retry variable:

Choose exactly one:

- `shot_line_binding`
- `source_script_binding`
- `seam_boundary`
- `material_role_table`
- `seedance_prompt`
- `audio_cut_point`
- `request_body`

Locked variables:

Passed story analysis, approved images, product profile, and unchanged visual QC evidence.
For prompt-only repair, the approved manifest and every Part-image hash are additionally locked; storyboard/image regeneration is out of scope.

## STOP

Return `STOP` when:

- Required story analysis, approved images, product profile, or visual manifest evidence is missing.
- A repair would require image regeneration or paid Seedance generation outside the approved stage.
- The same pre-Seedance pack failure repeats after one targeted repair.

## Next Status

On technical pass:

```text
seedance_inputs_prepared
```
