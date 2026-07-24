# Pre-Seedance Pack Worker

## Canonical Stage

`pre_seedance_pack`

## Purpose

Build the complete generation-ready package after image batch PASS from one authored `director_plan.json`: render voiceover, seam plan, shot-line map, Seedance prompts, audio boundary evidence, the selected request or web-side handoff, and lightweight sync QC.

This replaces the old default chain of separate `voiceover -> seam -> seedance_prompt -> audio_boundary_qc -> request_qc` worker rounds. Keep those older workers for legacy statuses and targeted repairs.

## Inputs

- Passed story analysis with ASR/subtitle/visual shot table.
- Passed schema-v3 `source_rhythm.json` containing evidence-confirmed source lines plus source scene, camera, framing, action type/timing, and transitions.
- Passed storyboard and approved final Part images.
- `output/<job-id>/visual-assets/approved_visual_manifest.json`.
- The current role map and identity-group `presenter_gender`; source, target, identity, director plan, voice labels, and final Prompt must all agree.
- `output/<job-id>/product_profile.json`.
- Product group and identity group references.
- Source audio or client reference audio when sound is enabled.
- Seedance route decision and `rules/SEEDANCE_MODEL.json`.
- Existing image batch QC reports and active visual hashes.
- `gates/pre_seedance_pack_gate.md`.
- Golden Seedance prompt samples from `.agents/skills/video-replication/references/seedance-20-prompt-standard.md`.
- `.agents/skills/video-replication/references/source-replication-contract.md`.
- `.agents/skills/video-replication/references/source-script-lock.md`.
- For `person_assets=storyboard_derived`, `.agents/skills/video-replication/references/storyboard-derived-identities.md` and the per-Part identity mappings in the approved visual manifest.

## Actions

1. Reuse passed image-batch evidence by hash when active images, approved visual manifest, material roles, prompt reference roles, and user-visible defect state have not changed.
   - The semantic image source is the family-level result from `tools/storyboard_visual_acceptance.py`; do not create geometry, continuity, or skincare compare/review files in this worker.
   - If the user asks to improve the prompt on the existing storyboard, enter prompt-only repair: record the current approved Part-image hashes, do not run source-blueprint/storyboard/ImageGen workers, do not change the manifest, and edit only `director_plan.json` plus mechanically rendered prompt/voice/request artifacts.
   - A v4 director plan must bind the exact current `source_rhythm.json` hash. If source analysis changes, the old plan and prompt are stale and must fail QC even when beat ids remain unchanged.
   - Internal source evidence is compile-time only. Final model-facing prompts may reference only assets actually submitted in the request (`@image` / `@audio`) and explicit executable actions. Any `原片`, `源片`, `原视频`, `按分镜`, `source video/rhythm/beat` wording is an unbound reference and must fail prompt QC.
2. Write or refresh one compact generation package:
   - first write `output/<job-id>/seedance/director_plan.json` as the only authored target plan for downstream timing, actions, speaker modes, lines, reference bindings, shot groups, and seam state; new plans use `version >= 6`, `script_fidelity.mode=source_locked`, and `replication_fidelity.change_policy=necessary_only`
   - `剧情分析/source_rhythm.json` is required; in `source_length` mode every target beat binds exactly one source beat, while only `execution_blocks` may group adjacent target beats
   - first build `source_functions` from complete ASR, subtitles, and visual rhythm; mark each function must_keep / mergeable / removable and bind preserved functions to target beats or speech groups
   - keep `beats` and `speech_groups` separate internally: every visual beat remains explicit, while one speech group may cover several consecutive beats with the same source speaker mode
   - author `execution_blocks` separately: a block cannot cross a scene, visual-function, or speaker-mode boundary; in-frame sync speech and narration must be separate, and short still-life B-roll gets its own block
   - for a source `presenter/product close -> B-roll -> presenter/product close` hard cut, end the first presenter block at product-close framing and start the final presenter block in the same source scene at matched framing; do not add a dissolve or restart the push
   - when a Part contains multiple scenes or an identity reference has a different background, write a compact per-Part `scene_rule`; identity refs never control scene or after-wash skin state
   - every beat must include `sound_effect`; it can only describe source-supported environment/action sound or sound caused by the visible target action
   - voiceover/script with speaker roles; every speech group copies its evidence-confirmed source line and declares a `line_edits` list, even when that list is empty
   - `voiceover/source_script_fidelity.md`, showing the source line, every declared localized edit, and the target line
   - every beat copies the bound source-rhythm visual action, source line, and source speaker mode; declares a `visual_edits` list even when empty; and records matching source/target scene, camera, framing, action stage, and transition in `visual_fidelity`
   - `voiceover/source_replication_fidelity.md`, showing the source action, every necessary localized visual edit, the target action, and all locked visual dimensions
   - shot-line map from story analysis to target actions, including source speaker mode/line and target speaker mode/line for every row
   - seam boundary notes for every Part boundary
   - `seedance_素材角色表.md`
   - per-Part Seedance 2.0 prompts
   - reference audio files and boundary notes when sound is enabled
   - exactly the selected delivery surface: `web`, `api`, or explicitly requested `both`
3. Before writing final Seedance prompts, open `.agents/skills/video-replication/references/seedance-20-prompt-standard.md` and its current validated example. The reference preamble must use `定义为 -> 只控制/锁定 -> 不传递`; do not author a separate `控制校准` format. Keep beats and speech groups separate in the plan, then bind them together in the model prompt. Each source-locked target line appears exactly once inside its Shot range; the renderer may not rewrite it and there is no separate audio-execution block. For storyboard-derived people, include only the `identity_role_*` refs used by that Part.
4. Compare every `source_visual_action` with `target_visual_action` before render. The source action must mechanically equal the bound `source_rhythm.json` action. Target actions may only preserve it or perform an explicit product-profile/user-required translation recorded in `visual_edits`; keep shot order, scene, camera, framing, action stage/timing, and hard cuts locked. Do not complete an action by inventing its missing start. Reject any sound effect that requires an invented visual action.
5. For sound-enabled multi-Part jobs, cut reference audio by sentence boundary, keep every upload audio file `<=15.00s`, and run audio duration QC. Run ASR boundary checks only on the reference audio files, not on the final generated video.
6. Render the repeated files with `python3 tools/pre_seedance_pack.py render --root . --job-id <job-id>`. The renderer keeps director-plan validation, archive/replace, shared voice/seam semantics, route selection, and final handoff writes serial. Its `tools/pre_seedance_part_compiler.py` adapter freezes the director plan, model route, approved manifest, source rhythm, referenced images, and audio; compiles each Part's prompt/audio/selected web-or-API files in isolated staging with bounded local concurrency; then promotes all Parts once in stable order and writes `seedance/part_compilation_manifest.json`. Do not assign Part semantics to LLM sub-agents. Stop-before-generation intake defaults to `web`; direct final-video intake defaults to `api`; do not build `both` without an explicit need.
7. Run prompt/request hygiene and lightweight sync checks:
   - prompt text matches approved prompts
   - request JSON embeds the approved prompts
   - taskCode/model EP matches the selected route
   - image/audio order matches the material-role table
   - final web-side handoff contains only active upload assets
   - product references calibrate product identity/material only and do not override source storyboard composition
   - final prompts use ordered `time | Shot 01–02` blocks and cover every shot-line map storyboard-panel range
   - every prompt block includes visual and voice; include a sound-effect line only for a useful visible action sound, and never write `音效：无`
   - target visual actions and sound effects have source or explicit product-profile evidence; no invented action steps
   - final prompts preserve source speaker mode for every row and do not use object type as a speaker-mode default
   - no execution block contains more than one spoken speaker-mode kind
   - every 15-second Part passes the source-aware speech budget and the independent replication-function coverage review defined in `voiceover-capacity-and-compression.md`
   - prompt spoken lines exactly match the director plan; no extra model-facing dialogue is allowed
   - director-plan lines equal the source lines after applying only the declared `line_edits`; a semantically similar rewrite is not acceptable
   - `product_fact` / `price_or_offer` edits bind the current product profile plus exact source/target slots; `person_or_role` edits bind the current request; the semantic review request lists every line edit for an explicit per-edit checker result
   - source-length jobs cover every source beat exactly once and in order with one source beat per target beat, including beats previously labeled removable; compressed jobs require hash-bound explicit intake evidence
   - source visual actions equal the bound rhythm facts, and every target visual difference has one necessary, evidence-backed `visual_edits` record
   - product-name mentions retain the source count, location, repetition, and sentence structure; every edit binds the selected occurrence to its current source-rhythm beat and passing product-entity review; disable the product anchor when the source has no spoken product name
8. Do not reopen broad image repair. If active images or role mappings changed, rerun the relevant heavy visual QC; otherwise cite the existing PASS reports.
9. Stop before paid Seedance generation.

## Scripted Part

Initialize and render the single-source plan:

```bash
python3 tools/pre_seedance_pack.py init --root . --job-id <job-id>
# Fill only director_plan.json, then:
python3 tools/pre_seedance_pack.py render --root . --job-id <job-id>
```

Use the existing scripts as checks inside this one worker. Run request QC only for `api` or `both`; web mode is covered by final-directory visual-manifest QC, prompt contract QC, and audio duration QC:

```bash
python3 tools/pre_seedance_pack_qc.py --root . --job-id <job-id>
```

For new-flow jobs the QC bundle automatically reruns `tools/source_rhythm_qc.py` against `source_rhythm.json` plus `director_plan.json`. It must reject missing/changed source beats, source-order changes, overstretched rapid hooks, and speech blocks below 80% of mapped source pace.

This wrapper dynamically discovers every Part and runs visual-manifest, prompt-contract, audio-duration, and mode-appropriate request QC concurrently. It does not run the independent checker and does not submit Seedance.

After the deterministic bundle finishes, build the stage QC Risk Ledger before invoking any checker:

```bash
python3 tools/qc_risk_ledger.py \
  --root . \
  --job-id <job-id> \
  --stage pre_seedance_pack
```

- Ledger `PASS`: all required families are `PASS` or `REUSED_PASS`; skip the checker and record the gate.
- Semantic review request emitted: run one checker invocation for every changed family in that request, bind its QC output with `--risk-request`, then rebuild the ledger.
- Never reopen a visual family marked `REUSED_PASS`. Prompt, audio, or request changes do not invalidate unchanged storyboard pixels.

## Outputs

Write under `output/<job-id>/`:

- `voiceover/voiceover.md`
- `voiceover/source_script_fidelity.md`
- `voiceover/source_replication_fidelity.md`
- `voiceover/shot_line_map.md` or equivalent shot-line section
- `voiceover/replication_function_coverage.md`
- `seam/seam_design.md`
- `seedance/seedance_素材角色表.md`
- `seedance/seedance_partX_prompt.txt`
- `seedance/part_compilation_manifest.json`
- `audio-boundary/audio_boundary_qc.md` and reference audio files when sound is enabled
- `seedance/handoff_mode.json`
- `seedance/requests/partX_request_prepared.json` for `api|both`, or `seedance_web_final/` for `web|both`
- `seedance/requests/request_qc.md` only for `api|both`
- `checks/pre_seedance_pack_seedance_prompt_contract_qc.md`
- `output/<job-id>/checks/pre_seedance_pack_gate_review.md`
- `output/<job-id>/checks/pre_seedance_pack_visual_asset_manifest_qc.md`

## Gate

Run:

`gates/pre_seedance_pack_gate.md`

## PASS Next Status

`seedance_inputs_prepared`

## FAIL Retry Variables

Choose exactly one:

- `shot_line_binding`
- `source_script_binding`
- `seam_boundary`
- `material_role_table`
- `seedance_prompt`
- `audio_cut_point`
- `request_body`

## Stop Conditions

- Story analysis, approved images, product profile, or visual manifest is missing.
- Sound-enabled reference audio remains over 15.00s after one targeted recut.
- Request QC fails and cannot be fixed without changing approved prompts or assets.
- Any fix would require paid Seedance generation before the cost gate.
- Prompt-only repair detects changed approved Part-image hashes or requires a new/missing visual state; stop instead of silently regenerating the storyboard.
- A v6 speech group or visual beat contains an undeclared rewrite, or cannot fit without changing locked source wording, shots, actions, hard cuts, or rhythm beyond an allowed localized edit.
