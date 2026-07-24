# AGENTS.md

This repository is a Viral Replica Loop Kit.

## Operating Rules

- If the user gives only simple paths such as video folder, product name, product image folder, person image folder, voice source, target duration, or notes, treat that as a valid task intake.
- Do not ask the user to mention `BRIEF.md`, `jobs.csv`, `STATE.md`, or runner internals.
- For user-facing progress, use the five-stage language: 看懂原片, 改好分镜, 写视频脚本, 生成视频, 质检交付. Keep internal `status`, `next_stage`, and canonical stage names as secondary debugging details.
- Convert simple intake into internal files yourself with `scripts/new-task.py`, then run `./run-loop.sh`.
- If intake omits target duration, `scripts/new-task.py` must probe and record each source video's real duration; never substitute a generic 30-second default. A shorter target is compression only when `output/<job-id>/intake.json` proves the user explicitly supplied it.
- If the intake says or implies "做到...停", "到...前停", "中间不用问", "自己检查", "直接出", "给我素材图和提示词", "我自己去网页端跑", "不需要最终视频", or "到 Seedance 生成视频前停", treat it as a self-audit auto-run request even if the user never says `self-audit`, `auto-run`, or "一路跑到底".
- Start by reading `BRIEF.md`, `STATE.md`, `LOOP.md`, `jobs.csv`, and `rules/STAGE_RULES.json`.
- Use `.agents/skills/viral-replica/SKILL.md` as the loop wrapper.
- Use `.agents/skills/video-replication/SKILL.md` as the actual video-replication method. The loop wrapper must not replace this skill.
- Always read `output/<job-id>/product_profile.json` when it exists. Load the generic rule plus exactly the category/brand/SKU rules listed in `loaded_rules`; when no category/SKU rule is listed, use the generic rule. Load `client-profiles/kongfengchun/README.md` when `loaded_rules` includes `category:clay_mask` or `sku:kongfengchun_clean_mud_mask`. Keep routing internal: user-facing progress and handoffs name only the active product and its loaded rules, never unselected categories.
- Work on one job only.
- Advance one stage only.
- Sub-agents are explicitly authorized in this repository for bounded independent maker, checker, audit, research, and test work. Use them when parallel work helps; serialize shared runner/state writes through the coordinator.
- Parallel stage work must use a sealed `tools/stage_execution.py` plan. A sub-agent or command lane may write only its declared job-local roots and completion artifact; one coordinator owns fan-in, shared manifests, gates, cost/retry state, `jobs.csv`, `RUNNER_STATE.json`, and `STATE.md`.
- If the user asks or implies self-audit auto-run, keep one pinned job but repeat one-stage iterations until a hard stop, explicit stop point, or final delivery.
- In self-audit auto-run, do not end the assistant turn after an intermediate PASS. Run the next loop decision and continue unless the target stop point has been reached.
- Do not skip the linked worker or gate.
- In self-audit mode, run the maker worker first, then build the stage QC Risk Ledger. Reuse unchanged families, accept changed deterministic families from program evidence, and invoke the independent checker contract at most once only when the ledger emits a changed Semantic QC request. Bind that review with `tools/checker_review_qc.py --risk-request ...` before recording the gate result.
- Write every round back to `STATE.md`.
- Record gate results through `./run-loop.sh --record-gate-result ...`.
- Do not submit paid or batch generation unless the cost gate has passed and the user explicitly approved it. A direct request to run Seedance, directly generate the final video, or directly produce the video is explicit approval for the current explicit job by default and covers every required Part once; do not ask for a second or per-Part confirmation. Batch approval requires an explicit batch/all/named-jobs scope. Failed-Part retries require new targeted approval.
- If the user manually runs the web-side Seedance step and confirms the result, record that validation in `STATE.md` and docs, but do not retroactively submit paid/API generation from the loop.
- Whenever a job stops, hands off before Seedance generation, blocks on QC, or fully completes, the assistant's final response must include concrete inspection paths for the user. Include the active handoff/output directory when ready, plus the key images, prompts/audio/manifests/QC reports or the failed QC report when blocked. Do this even if the user did not ask for paths in that turn.
- Final delivery QC must be fast by default: confirm the video is readable, has required streams, duration is close, no freeze/black/static shots or obvious visual bug, then give the user a clickable video or absolute video path. Do not run final ASR routinely; use it only for user-requested audio/script verification or a targeted audio defect.
- Before generation can PASS, bind every selected downloaded Part in `generation/selected_outputs.json`. Seedance outputs flattened video pixels with optional audio and never a separate subtitle track; do not add a track-based branch to the project flow.
- Local `finishing` must remain caption-free. After it passes, always run the conditional `subtitle_removal` stage against the exact single `final/final_video.mp4` master. Classify only `clean` or `burned_in` from current hash-bound, timestamped full-timeline frames, and require one independent semantic checker for that classification even when the maker says `clean`. Clean results skip with zero paid tasks. A current `burned_in` result authorizes exactly one automatic project `$video-subtitle-removal` / MediaKit Pro task under `workflow_generated_hard_subtitle_v1`; persist attempt 1 before submission, count failures as spent, preserve the original, require hash-bound 8fps repair evidence in the same batched checker, and never retry automatically without a new explicit user decision. Final QC must mechanically bind its sole input path and hash to the passing report's `output_video`.
- Final captions are opt-in only and run after Final Technical QC through `caption_finishing`. Use the actual final audio for timing/text and the source video only for caption visual grammar; never ask Seedance or local finishing to add them.
- Do not present file hashes as a user workflow step. `CONTEXT.md` `Artifact Hash` is the definition: hashes remain internal for stale-evidence detection, QC reuse, and request/prompt/output provenance; they are not Seed and cannot reproduce generation.
- After image batch PASS, the default next stage is a compact Pre-Seedance pack that builds voiceover, shot-line map, seam notes, Seedance prompts, audio-boundary evidence, and request/web handoff QC together. The old separate `voiceover -> seam -> seedance_prompt -> audio_boundary_qc -> request_qc` route is legacy/focused-repair fallback, not the default path.
- New `pending` jobs default to one `source_blueprint` round that prepares ASR/contact sheet/Part storyboards in parallel and checks story analysis plus storyboard together. Keep `story_analysis -> storyboard` only for legacy statuses or focused repair.
- Every source-video understanding run must call Wujie Higress `POST https://higress-api.wujieai.com/v1/chat/completions` with `model=doubao-seed-2-0-mini-260215`; `rules/VIDEO_UNDERSTANDING_MODEL.json` is authoritative. This is Seed 2.0 Mini semantic understanding, not Seedance video generation. Save the structured result and request evidence under `output/<job-id>/剧情分析/video_understanding/`. Provider failure, a mismatched provider/model/source hash, or missing HTTP-200 evidence is a hard stop for `source_blueprint` and legacy `story_analysis`; contact sheets, an optional visual MCP, or manual prose cannot substitute. Use raw ASR, measured cuts, visible text, and cited frames to verify model claims and override them when direct evidence conflicts.
- The non-image path from intake through `seedance_inputs_prepared` has a 20-minute budget. Author one `output/<job-id>/seedance/director_plan.json`, render repeated downstream artifacts with `tools/pre_seedance_pack.py`, and measure the result with `tools/timing_report.py`.
- Build only the delivery surface that has a consumer: stop-before-generation/web handoff defaults to `handoff_mode=web`; direct final-video generation defaults to `handoff_mode=api`; build `both` only when explicitly requested.

## Hard Stops

Stop when:

- source video or product assets are missing; person assets are a hard stop only when intake is not explicitly using the `storyboard_derived` no-model/multi-person branch
- Image sample needs client review only when a job explicitly requests a sample stop; default flow goes directly from storyboard to all-Part image batch.
- image repair repeats the same failure
- Seedance or another paid generation action would run without generation approval
- final objective technical QC needs more than one targeted Seedance retry
- two rounds have no useful progress

## Video Replication Rules

- Before any worker stage, read `.agents/skills/video-replication/SKILL.md` and the needed files under `.agents/skills/video-replication/references/`.
- Treat `.agents/skills/video-replication/SKILL.md` as the source of truth for the craft: story analysis, storyboard, image generation/repair, image audit, voiceover, seam, Seedance prompts, audio boundary QC, generation, and final QC.
- Treat `.agents/skills/viral-replica/SKILL.md` as the runner adapter only: it tells Codex how to fit the craft into this repository's stages.
- First understand the source video story, subtitles, ASR, and shot rhythm.
- Default replication is `source_locked + necessary_only`, not inspiration or semantic adaptation. Preserve source wording, hooks, sentence order, repetitions, speaker/voice layer, emphasis, pauses, shot order, scene, camera/framing, action stage/timing, hard cuts, roles, and product-proof placement. Change only the smallest user-requested or product-fact-conflicting slot, record every text change in `line_edits` and every visual change in `visual_edits`, and apply `.agents/skills/video-replication/references/source-replication-contract.md`. Function coverage alone is never sufficient for PASS.
- New `source_blueprint` jobs must complete `output/<job-id>/剧情分析/source_rhythm.json` from measured scene cuts, 5fps evidence frames, raw-ASR spans, speaker mode, emphasis, pauses, action peaks, and emotion functions, then pass `tools/source_rhythm_qc.py`. The 12 storyboard panels are Shot navigation, not the rhythm source of truth.
- New `source_blueprint` rhythm records use schema v3. Every beat declares pixel-derived scene, camera, framing, `visual_action_type`, action peaks, and entry/exit transitions; every `physical_change` cites distinct real before/peak/after frames and the visible state change. After rhythm QC, rebuild Part storyboards with `tools/build_part_storyboards.py --source-rhythm ...`; the final manifest must be `selection_mode=source_rhythm`, cover each `must_keep` / `mergeable` beat exactly once, and use action peaks. In source-length director plans, each target beat binds exactly one source beat; only execution blocks may group adjacent beats. The independent checker must submit a per-beat `source_rhythm_visual_review.json` and pass `tools/source_rhythm_visual_review_qc.py`; a prose summary cannot pass the gate.
- Do not write voiceover or Seedance prompts from storyboard images alone.
- After image generation, audit before using the images downstream.
- Default image-stage intent is simple source-storyboard editing, not creative regeneration: use the source Part storyboard as the edit target, replace only the old person with the approved person, replace only the old product/tool/mud with the approved product/open-white-mud/fingertip use, remove subtitles/old overlays, and keep the original scene, camera crops, hand positions, panel grid, shot order, and action rhythm. The user should not need to restate this per job.
- GPT Image storyboard edits must satisfy `.agents/skills/video-replication/references/codex-imagegen-direct.md`, the single source of truth for reference roles, prompt shape, Shot-label preservation, evidence, and completion. The final Seedance video prompt must still keep storyboard grid, borders, and Shot labels out of the generated video.
- Default person replacement means complete model appearance replacement: face, hair, body, and clothing come from the approved model/person reference. The source video/storyboard keeps only background, camera crop, shot order, action rhythm, and hand/action placement. Source-video clothing must not remain unless the user explicitly says to keep source wardrobe or to do a face-only swap.
- For multi-person source stories, write a role map before ImageGen. The approved identity applies only to the source-defined protagonist/product-host role; secondary people keep their story role and gender and may be generic/de-identified. Do not replace a male support role with the female protagonist or apply the protagonist identity to every person in the storyboard.
- When the user supplies no person/model assets and the source contains many different people, set `person_assets=storyboard_derived` and follow `.agents/skills/video-replication/references/storyboard-derived-identities.md`: edit the original Part storyboard with product refs but no person ref, approve it, derive dedicated photoreal identity images from that passed current-job storyboard for speaking/close-up/recurring roles, and reuse recurring identities in later-Part storyboard edits. Each Seedance Part receives only the identities used in that Part. This is an image branch inside the standard workflow, not a separate workflow.
- When the product profile declares visible label text, designated hero close-ups must preserve the major brand/product-name identity and real label design. Distant, oblique, multi-bottle, and storyboard-scale microtext only needs the same overall color, line layout, and brand impression; it does not require character-for-character reproduction, and microtext-only mismatch is a non-blocking visual warning. Wrong product/brand, a blank or smoothed label, an old-source label, wrong label design, or a clearly wrong/missing major hero-label anchor is `FAIL`.
- Source storyboard layout is orientation-aware: portrait sources default to 4 columns x 3 rows; landscape sources default to 3 columns x 4 rows so the board is not too long to edit reliably.
- Do not use a failed generated candidate as the next edit target when it is squeezed, recomposed, scene-changed, or otherwise not source-storyboard faithful. Discard it and restart from the source Part storyboard with product/person references.
- Do not use a failed Part as cross-Part continuity reference. If Part1 is squeezed, recomposed, wrong-scene, or otherwise failing, rebuild Part1 from its source storyboard before using it to guide Part2.
- Image batch outputs can only be real saved `AI改好分镜图`: current-job AI-generated or AI-edited storyboard/reference images that Seedance can directly use. The sole deterministic exception is the Shot-label metadata-only normalization defined by `.agents/skills/video-replication/references/codex-imagegen-direct.md`; it must prove zero panel-pixel changes and cannot turn a non-AI board into a valid output. Do not use other Python/PIL composites, source rhythm boards, contact sheets, cropped source frames, validated anchor composites, old-job storyboard images, or unsaved image directions as image-stage outputs.
- Every job must have `output/<job-id>/visual-assets/approved_visual_manifest.json` before Seedance prompt or request stages can pass. Run `tools/visual_asset_manifest_qc.py` and require `PASS`.
- Image batch must also have a passing `tools/codex_imagegen_contract_qc.py` report for Matpool GPT-Image-2. If a job explicitly requests image sample, the sample must meet the same contract. The contract must prove actual image references were submitted as local image files and that source storyboard pixels only control layout/shot order/framing/action rhythm, not old product/tool/person/mud/text.
- Active image batch uses `tools/storyboard_visual_acceptance.py` as the sole semantic storyboard-image conclusion. It combines geometry/appearance, identity/product/material integrity, cross-Part continuity, and profile-required skincare progression into one bound checker request. Prompt and request stages reuse those family PASS results and run only lightweight manifest/material-role/prompt-reference synchronization checks; they must not create separate geometry, continuity, or skincare reviews.
- Reusable references must be binding-group based: `02/03` product refs come from the same active product group, and `04/05` identity/after-wash refs come from the same active identity group. Reusable product or after-wash refs may be support uploads, but they cannot pretend to be the current job's `01` storyboard image.
- `./run-loop.sh --record-gate-result PASS` refuses image/prompt/request-stage PASS when checker review QC, visual asset manifest QC, or required final audio duration QC is missing or failing.
- A source-video rhythm board, contact sheet, cropped source frame, or any image with visible old product/person/mud/subtitles cannot be promoted as a final Seedance upload image. A material-role table or prompt cannot make contaminated pixels safe.
- If GPT Image produces a direction but no saved candidate image, the image stage has missing evidence and must `FAIL` or `STOP`; do not substitute extracted source frames.
- For GPT Image batch, explicit sample, after-wash reference, and local repair, use the project Matpool GPT-Image-2 route only: `.agents/skills/video-replication/scripts/generate.py` with `MATPOOL_API_KEY`. Do not try any deprecated GPT Image route or gateway probe.
- For 孔凤春/cleaning mud-mask jobs, old tube/stick/brush/arm-swatch source actions must be translated into finger pickup from the open jar and fingertip face application before ImageGen. Do not leave old tool words in the ImageGen prompt as negative anchors.
- For a localized image problem, use a fast-repair path: repair only the failed image/panel, run one hard check plus visual check, sync the passed image into the final output locations, and defer broad documentation cleanup until after the artifact is usable.
- Speed rule: once image batch has PASS with fixed active image hashes, downstream voiceover/seam/prompt/request work should reuse those PASS QC artifacts by hash and must not reopen broad image repair or repeat visual debate unless an active image, manifest, prompt role table, or user-visible defect changed.
- Shot-label speed rule: normalize every Matpool candidate before its first content review. A later full-file hash change caused only by proven Shot-label-bar normalization reuses content QC by panel-content fingerprint; it must not call an image model, manually OCR 12 labels, or rerun geometry, continuity, skincare, identity, and product reviews.
- For 孔凤春/cleaning mud-mask jobs, image audit must reject yellow, beige, tan, cream-yellow, gray, watery, or source-contaminated mud. The face-applied mud and open-jar mud must be white/milky-white thick paste before any Seedance prompt or request stage.
- If an after-wash proof image is needed, generate a dedicated face close-up from the approved person reference with cleaner, brighter skin. Do not crop a post-wash panel out of a storyboard and reuse it as the after-wash reference.
- When the user asks for web-side Seedance handoff, collect all upload images, audio, prompts, manifests, and notes into one final output directory before stopping.
- The final web-side handoff directory must contain active upload assets only. Keep deprecated drafts, archived prompts, old audio, and failed images outside that directory.
- For sound-enabled multi-part videos, run audio boundary QC before video generation.
- For Seedance/web upload audio, every reference audio file must be `<=15.00s`; target `14.90s` to leave encoder/UI tolerance. Files longer than 15.00s are `FAIL` even if a provider API mentions a looser limit.
- For real faces, use the approved face-safe Seedance route and public URLs.
- Default Seedance model route is ordinary `Seedance 2.0` with `model=ep-20260521101914-nwv8j`. Model names are exact: `Seedance 2.0` means ordinary 2.0, `Seedance 2.0 mini` means Mini, and `Seedance 2.0 Fast` means Fast. An explicit user model name overrides the default without reinterpretation. Request QC must enforce the selected route, and changing the EP must not change the rest of the loop flow.
- Multi-part videos default to no BGM unless the brief explicitly asks for music.
- Final Seedance 2.0 prompts must be model-facing production briefs: reference roles followed by ordered `time | Shot 01–02` execution blocks. Every block binds `画面 / 声音`; add `音效：<...>` only when the visible action has a useful matching sound, and omit the entire line instead of writing `音效：无`. Split blocks at scene, visual-function, or spoken speaker-mode changes; in-frame sync speech and narration cannot share a block, and short still-life B-roll is standalone. Do not create broad `Shot 1/2/3` summaries or a separate `声音执行` section. Do not write loop-only labels such as `Part1最终分镜图`, `AI改好分镜图`, `current-job`, or `source rhythm board` inside final prompt text.
- Final prompt reference roles must use the standard `定义为 -> 只控制/锁定 -> 不传递` form. Do not alternate to a free-form `控制校准` preamble.
- For new-flow jobs, every target beat in `director_plan.json` must bind ordered `source_beat_ids`. Pre-Seedance source-rhythm QC must reject missing or reordered required beats, rapid hooks stretched beyond whole-video scaling tolerance, and speech blocks below 80% of mapped source speaking pace.
- New-flow dialogue defaults to `script_fidelity.mode=source_locked`. Copy evidence-confirmed source wording, order, repetitions, speaker mode, emphasis, and pauses. Change only a user- or product-fact-specific slot recorded in `speech_group.line_edits` with `from`, `to`, `reason`, and `reason_detail`; semantic-equivalent rewrites are failures. Render and inspect `voiceover/source_script_fidelity.md` before PASS.
- Every target action must be supported by the source video/storyboard or an explicit product-profile translation. Do not invent setup steps, merge a source hard cut into one continuous action, or add an action to justify a sound effect. Preserve must-have source beats, including phone proof shots, product-name close-ups, rinse/wipe proof shots, and final product close-ups when present.

## Validated Workflow Notes

- `docs/loop-runbook.md` is the operator runbook for intake, self-audit, speed rules, QC commands, and stop points.
- `docs/kongfengchun-validated-workflow.md` records the 2026-06-17 validated `孔凤春清洁泥膜` web-side Seedance handoff for `job-001`.
- For future `孔凤春清洁泥膜` jobs, use the validated `job-001` handoff structure as the packaging standard, not the deprecated drafts under `output/job-001/deprecated/`.
- `docs/seedance-20-prompt-standard.md` points to the current Seedance 2.0 prompt standard. The preferred provider-validated case is the 2026-07-17 `job-011` complete 26-second Part1+Part2 result; `job-002` remains the historical storyboard-geometry baseline only.

## Client Profiles

Current built-in profile:

- `kongfengchun`: 孔凤春清洁泥膜专用 profile. Load it only when `output/<job-id>/product_profile.json` loads `category:clay_mask` or `sku:kongfengchun_clean_mud_mask`. It contains the mud-mask-only identity, white thick mud, no invented packaging, no gray-mud/source-product contamination, subtitle+ASR+visual rhythm, and Seedance prompt overrides.

## Gate Discipline

- A maker worker cannot casually approve its own output.
- If the user asks to keep running without manual review, use self-audit mode and run `workers/checker_worker.md`.
- A checker must inspect the actual artifacts, not just the maker's summary.
- Missing evidence is `FAIL` or `STOP`, not `PASS`.

## Style

Keep outputs direct and useful. Use concrete artifact paths. Avoid hiding failures behind vague wording.

## Simple Intake Example

When the user says:

```text
视频目录：...
产品名：...
产品图路径：...
人物图路径：...
声音参考：直接用原视频提取
目标时长：30秒
备注：基本全复刻
```

Run:

```bash
python3 scripts/new-task.py \
  --root . \
  --video-dir "<视频目录>" \
  --product-name "<产品名>" \
  --product-assets "<产品图路径>" \
  --person-assets "<人物图路径>" \
  --audio-assets "extract_from_original" \
  --target-duration "30s" \
  --notes "<备注>"
./run-loop.sh
```
