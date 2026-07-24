# Loop Runbook

Date: 2026-06-17

This runbook is for operating the Viral Replica Loop Kit without repeating avoidable work.

## Intake

Simple user intake is enough:

```text
视频目录：
产品名：
产品图路径：
人物/主播图路径：
声音参考：
目标时长：
备注：
```

Convert it into loop files with:

```bash
python3 scripts/new-task.py \
  --root . \
  --video-dir "<video-dir>" \
  --product-name "<product-name>" \
  --product-assets "<product-assets>" \
  --person-assets "<person-assets>" \
  --audio-assets "extract_from_original" \
  --target-duration "<duration>" \
  --notes "<notes>"
```

Then run:

```bash
./run-loop.sh
```

For requests like "做到 Seedance 生成视频前停" or "我自己去网页端跑", use self-audit mode:

```bash
./run-loop.sh --self-audit --job-id <job-id>
```

The loop has only two user-facing delivery outcomes:

- Pre-Seedance handoff: upload-ready images, audio, prompts, manifests, and notes.
- Final video: generated Seedance video outputs after explicit generation approval or a direct user request to run Seedance.

Do not stop for image sample review as a user-facing checkpoint. Image samples, visual warnings, repairs, and checker decisions are internal loop work.

The **看懂原片** semantic lane is mandatory: `tools/prepare_story_analysis.py` concurrently calls Wujie Higress `doubao-seed-2-0-mini-260215` for full-video 2fps understanding and opening 0–3s 5fps rapid-hook review while running one Qwen ASR. The blueprint aligns hook semantics to measured cuts in `剧情分析/video_understanding/hook_review/aligned_timeline.json`. A provider/model/hash/request/alignment failure stops the stage; contact sheets and manual prose cannot substitute for the calls. Setup, smoke test, evidence contract, and troubleshooting are in `docs/video-understanding.md`.

New pending jobs first run one `source_blueprint` round: prepare ASR/contact sheet/Part boards plus measured source rhythm in parallel, then author evidence-backed beats in `剧情分析/source_rhythm.json`. That artifact uses real cut points, 5fps evidence, raw-ASR spans, speaker mode, emphasis, pauses, action peaks, and emotion functions; `checks/source_rhythm_qc.json` must pass before the stage can pass. After image batch PASS, the default next stage is one compact Pre-Seedance pack. Author a v5 `seedance/director_plan.json` once, bind every target beat to ordered `source_beat_ids`, set `script_fidelity.mode=source_locked`, and declare every localized dialogue change in `speech_group.line_edits`. Then render `source_script_fidelity.md`, voiceover, shot-line map, seam notes, material-role table, Seedance prompts, reference-audio boundary evidence, and the selected web/API delivery surface with `tools/pre_seedance_pack.py`. The QC bundle rejects undeclared dialogue rewrites, uncovered/reordered beats, overstretched rapid hooks, and target speech below 80% of mapped source pace. Final prompts start with `定义为 -> 只控制/锁定 -> 不传递`, then use ordered `time | Shot 01–02` blocks; every block binds visual and voice, with sound effect only when useful and visible. A separate `声音执行` section is invalid. `tools/seedance_prompt_contract_qc.py` must pass before the stage can pass. The older `story_analysis -> storyboard` and `voiceover -> seam -> seedance_prompt -> audio_boundary_qc -> request_qc` sequences are legacy fallbacks for historical statuses or focused repair, not the default route.

If the user supplies no person/model assets and the source has many different people, intake records `person_assets=storyboard_derived`. Follow `.agents/skills/video-replication/references/storyboard-derived-identities.md`: edit and approve the source storyboard without a person ref, derive dedicated photoreal identities from the passed current-job storyboard for speaking/close-up/recurring roles, then reuse recurring identities in later-Part edits. This branch changes only person-asset handling; source understanding, script lock, image QC, Pre-Seedance, approval, generation, and final QC remain the standard flow.

Do not stop final video delivery for subjective effect review. Final QC defaults to a fast delivery check: missing/unreadable output, missing video/audio streams, wrong duration, freeze/black/blank frames, broken seam, obvious wrong person/product/wardrobe/mud/scene, static shots, and obvious audio defects from quick spot review. Do not run final ASR by default; it is only for user-requested audio/script verification or targeted `voiceover_timing` debugging. If final technical QC passes, immediately deliver a clickable video path or embedded video and let the user judge subjective effect.

Before generation PASS, bind the exact selected Part set in `generation/selected_outputs.json`. Local finishing then creates one caption-free `final/final_video.mp4` and passes a bound `finishing_story_integrity` checker. When approved `product_*` references exist, finishing automatically detects reference-dominant still inserts and replaces only the bad visual interval with a clean moving product interval from the same video; it must preserve the audio packet hash and duration, pass a second scan, and stop when no safe replacement exists. After finishing, always run `subtitle_removal` on that exact master and classify only `clean` or `burned_in` from current hashes and timestamped full-timeline evidence. The `subtitle_presence_classification` semantic family always needs one independent checker, including clean results. Clean results submit zero paid tasks; current `burned_in` evidence persists attempt 1 and automatically invokes the project `$video-subtitle-removal` skill once under `workflow_generated_hard_subtitle_v1`, then adds repair quality to the same checker batch. Count failures as spent, preserve the original, require hash-bound 8fps residual/damage/flicker evidence, and do not retry automatically. Final QC must bind its sole video path and hash to the passing removal report's `output_video`. Explicit final captions, when requested, run only after this Final Technical QC.

If final QC fails and Seedance regeneration is needed, allow at most one targeted retry. A repeated technical failure or second paid retry stops. If the user instead approves a quality retake of one already successful Part, use `generation_intent=quality_retake`: bind the current `generation/selected_outputs.json` and `final/final_video.mp4`, keep the accepted Part/final active until the new Part passes, replace only that Part at merge, then rerun finishing through final QC. For a terminal job, persist this repair only in `generation/quality_retake_state.json`; do not overwrite the global current round used by another task.

If the user asks to run Seedance, directly generate the final video, or directly produce the video, that request is generation approval for the current explicit job/generation round by default. Record it as the approval source and continue through the cost gate without asking again.

For a multi-Part current job, that approval covers every required Part once. Do not stop between Part1 and Part2 for another confirmation when both Parts are needed for the same final video. Failed-Part retries require new targeted approval.

Do not infer batch approval. Only run multiple jobs or variants when the user explicitly says the batch scope, such as "这批都跑", "全部跑", "今天这些都跑", or a concrete job list.

## Stage Discipline

The loop shape stays fixed:

```text
runner decision -> maker worker -> checker review -> gate record -> state writeback
```

Rules:

- Work on one job only.
- Advance one stage only.
- Read `.agents/skills/video-replication/SKILL.md` before worker work.
- Use `.agents/skills/viral-replica/SKILL.md` only as the runner adapter.
- In self-audit mode, run `workers/checker_worker.md` before recording a gate result.
- Record gate results through `./run-loop.sh --record-gate-result ...`.
- Write every round back to `STATE.md`.

## Speed Rules

Use the shortest reliable path:

- Matpool GPT-Image-2 is the only GPT Image route for image sample, batch, after-wash reference, and repair.
- Do not try any deprecated GPT Image route or gateway probe.
- For one bad image or panel, use fast repair: repair the failed target, run hard QC, visually inspect, then sync the passed file into final locations.
- Do not crop a storyboard panel to fake a missing after-wash reference; generate the face close-up directly from the approved identity.
- Do not rebuild voiceover, seam, prompts, or request bodies when the approved upstream artifacts did not change.
- Use hash-gated visual QC after image batch PASS: if the active `final-images/part*_seedance_ref.png` hashes and approved visual manifest mapping have not changed, the Pre-Seedance pack should cite the existing visual PASS evidence instead of rerunning heavy image QC.
- Always rerun lightweight sync checks at prompt/request stages: visual manifest final-dir mapping, Seedance prompt contract QC, prompt/request text sync, final handoff cleanliness, final audio duration, and runner stop/cost gates.
- Rerun heavy visual QC only when an active image hash changes, manifest mapping changes, material-role/prompt reference roles change, or the user reports a visible defect. Heavy visual QC includes storyboard geometry, cross-Part continuity, skincare progression, white-mud color/thickness review, and GPT Image contract QC.
- Treat visual warnings as non-blocking. If a machine metric or tiny local visual concern is not a true Seedance-input failure, continue automatically and write `why_not_fail` in the review. Do not ask the user to confirm a warning during local pre-Seedance handoff preparation.
- A pre-Seedance handoff is not a user-confirmation gate. If the requested stop point is before Seedance generation, finish the local handoff and give the paths; the user reviews the delivered artifacts themselves.
- Image sample review is internal by default. Do not stop the loop for user sample approval unless the user explicitly asks to preview samples before continuing.

## Visual Asset Types

Image stages produce only one active asset type:

```text
AI改好分镜图
```

That means a saved current-job AI-generated or AI-edited storyboard image that can go directly into Seedance as `01_图片1`.

Do not use these as image-stage outputs or final upload images:

- Python/PIL composites
- source rhythm boards or contact sheets
- cropped source frames
- validated-anchor拼图
- old-job storyboards
- unsaved image-generation directions

Reusable assets are allowed only through binding groups:

- Product group: `02_产品正面` and `03_开盖白泥`
- Identity group: `04_身份图` and `05_洗后脸`

Every job must write:

```text
output/<job-id>/visual-assets/approved_visual_manifest.json
```

Before recording PASS for image sample, image batch, Pre-Seedance pack, Seedance prompt, or request QC, run:

```bash
python3 tools/visual_asset_manifest_qc.py \
  --job-id <job-id> \
  --stage <image_sample|image_batch_qc|pre_seedance_pack|seedance_prompt|request_qc>
```

For web-side handoff request QC, add:

```bash
--check-final-dir
```

The runner refuses visual-stage `PASS` if checker review QC or visual asset manifest QC is missing or failing.

For image sample and image batch, Matpool GPT-Image-2 needs an edit/reference contract:

For multi-Part image batch, create isolated Part evidence first and merge before QC:

```bash
python3 tools/image_batch_fanout.py --root . --job-id <job-id> plan
# run each Part with --contract output/<job-id>/image-batch/contracts/partX_contract.json
python3 tools/image_batch_fanout.py --root . --job-id <job-id> merge
```

```bash
python3 tools/codex_imagegen_contract_qc.py \
  --root . \
  --job-id <job-id> \
  --stage <image_sample|image_batch_qc> \
  --contract output/<job-id>/<改图小样|image-batch>/codex_imagegen_contract.json
```

This contract must prove actual local image inputs were submitted to Matpool and that the source storyboard transfers only layout, shot order, framing, and action rhythm. It must not transfer old product, old tools, old host identity, old mud color, subtitles, or source product texture.

## Product Profile Label And Role-Map Rules

Product profiles are the source of truth for product-specific image requirements.

- If `output/<job-id>/product_profile.json` declares `visible_text_patterns`, keep the major brand/product-name identity and label design in designated hero close-ups. Distant, oblique, multi-bottle, and storyboard-scale microtext is visual-match-only and does not require character-for-character reproduction. Microtext-only mismatch is `VISUAL_WARNING`; wrong product/brand, blank/smoothed/old-source labels, wrong label design, or missing hero-label anchors remain hard failures.
- The visible-text prompt should name the real words from the product asset, not just say "label clear". The contract review must include `product_visible_text=true` and `no_blank_label=true`.
- Multi-person sources need a role map before ImageGen. The approved identity applies only to the source-defined protagonist/product-host role. Secondary people keep their source story role and gender, can be generic/de-identified, and must not become the protagonist identity.
- Do not repair a blank-label or wrong-role candidate forward if it also changed source scene, role structure, storyboard geometry, or shot order. Restart from the source Part storyboard with the corrected product text and role-map prompt.

## Kongfengchun Hard Rules

For `孔凤春清洁泥膜` only, when the job product profile loads `category:clay_mask` or `sku:kongfengchun_clean_mud_mask`:

- Load `client-profiles/kongfengchun/README.md`.
- Use one approved male identity anchor.
- Product must stay the real white square-round jar with white cap and green mark.
- Face-applied mud and open-jar mud must be white or milky-white thick paste.
- Reject yellow, beige, tan, cream-yellow, gray, watery, or source-contaminated mud.
- Reject invented boxes, gift packaging, blank jars, tube applicators, stick applicators, brush heads, and arm swatches.
- Source tube/stick/brush/arm-swatch beats must be translated to finger pickup from the open jar and fingertip face application before ImageGen. Do not leave old tool words in the generation prompt as negative anchors.
- Put the product name line on the product close-up beat.

Do not apply these mud-mask rules to `孔凤春发酵水`, toner jobs, unknown products, or other Kongfengchun products unless their product profile explicitly loads the clay-mask rule.

## Web-Side Seedance Handoff

When the user will run Seedance in the browser:

1. Prepare one final handoff directory:

```text
output/<job-id>/seedance_web_final/
```

2. Include upload images, audio, prompts, manifests, and notes.
3. Keep deprecated drafts outside the final handoff directory.
4. Use clear filename prefixes to define upload order.
5. Stop before paid/API generation.

When the user instead asks the loop to run Seedance directly, do not create a confirmation checkpoint here. Treat that request as approval for the current explicit job and continue toward final video delivery after request QC and cost-gate recording pass.

For the validated `job-001` Kongfengchun handoff, see:

```text
docs/kongfengchun-validated-workflow.md
```

## Seedance 2.0 Prompt Standard

For 15 second web-side or request-body handoff, use:

```text
docs/seedance-20-prompt-standard.md
.agents/skills/video-replication/references/seedance-20-prompt-standard.md
```

The final prompt should follow this shape:

```text
参考图角色：
@图片1 控制镜头顺序、景别、动作节奏；不复制网格、边框、编号或文字。
@图片2 控制产品正面包装。
@图片3 控制开盖白泥质感。
@图片4 控制人物身份。
@图片5 只在洗净后控制皮肤状态。
音频1 控制语速、停顿和口播节奏。

生成 15 秒、9:16 真实短视频。无字幕，无画面文字，无BGM。

0.0–2.8秒｜Shot 01–02
画面：...
声音：...
音效：...

2.8–5.9秒｜Shot 03–04
画面：...
声音：...
音效：...
```

Do not write loop-only labels in final prompts:

```text
Part1最终分镜图
Part2最终分镜图
AI改好分镜图
current-job
source rhythm board
contact sheet
素材角色表
```

Run this hygiene scan before `PASS`:

```bash
rg -n 'Part[12]最终分镜图|AI改好分镜图|current-job|source rhythm board|contact sheet|素材角色表|同Part1|后续继承|焦点锁' \
  output/<job-id>/seedance/seedance_part*_prompt.txt \
  output/<job-id>/seedance_web_final/prompts/*.txt
```

## Required QC Commands

Validate generated subtitle detection and the conditional repair:

```bash
python3 tools/subtitle_workflow_qc.py detection \
  --report output/<job-id>/subtitle_removal/subtitle_detection.json

python3 tools/subtitle_workflow_qc.py removal \
  --report output/<job-id>/subtitle_removal/subtitle_removal_report.json
```

Validate audio duration:

```bash
python3 tools/audio_duration_qc.py \
  --audio <part1-audio> <part2-audio> \
  --max-seconds 15.0 \
  --out-json <qc-json> \
  --out-md <qc-md>
```

Validate image hard gates:

```bash
python3 tools/image_hard_gate_qc.py <args from the worker or gate artifact>
```

Validate GPT Image edit/reference contracts:

```bash
python3 tools/image_batch_fanout.py \
  --root . \
  --job-id <job-id> \
  merge

python3 tools/codex_imagegen_contract_qc.py \
  --root . \
  --job-id <job-id> \
  --stage image_batch_qc
```

Validate request bodies when using API/taskCode route:

```bash
python3 tools/request_body_qc.py \
  --model-route-config rules/SEEDANCE_MODEL.json \
  <args from workers/request_build_worker.md>
```

Validate visual asset manifests and final upload mapping:

```bash
python3 tools/visual_asset_manifest_qc.py \
  --job-id <job-id> \
  --stage request_qc \
  --check-final-dir
```

Validate stage rules JSON:

```bash
python3 -m json.tool rules/STAGE_RULES.json >/dev/null
```

## Stop Points

Stop when:

- required source, product, person, or explicit audio assets are missing
- image repair repeats the same failure
- final handoff would submit paid/API Seedance generation
- two rounds make no useful progress

If the user manually completes the web-side Seedance generation and confirms the effect, record that in `STATE.md` and do not run paid/API generation retroactively.
