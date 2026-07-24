# Video Replication Loop Spec

## Purpose

This loop turns a batch of benchmark videos into replicated product videos while reducing repeated human correction.

The loop is not just "continue next step". It is a fixed system:

```text
jobs.csv -> runner -> one selected job -> one stage worker -> gate -> state writeback
                                      |                 |
                                      |                 +-> pass -> next stage
                                      |                 +-> fail -> retry policy /废稿
                                      +-> stop rule -> wait for human / cost approval
```

## Core Files

| File | Role |
|---|---|
| `jobs.csv` | Task queue. One row per video. |
| `STATE.md` | Human-readable current state and attempt log. |
| `LOOP.md` | This fixed system contract. |
| `RUNNER_STATE.json` | Machine-readable retry state: gate result, failure type, failure count, retry count, spent runs. |
| `COST_POLICY.md` | Cost and approval policy for image generation, Seedance, retries, and batch generation. |
| `CONTEXT.md` | Shared loop vocabulary and canonical user-facing outcome definitions. |
| `QC_RULES.md` | Cross-job gates and reusable failure rules. |
| `PRODUCT_CONSTRAINTS.md` | Product-specific rules. |
| `output/<job-id>/product_profile.json` | Profile-driven product rule artifact: generic rules always load; category, brand, and SKU rules load only when recorded here. |
| `rules/STAGE_RULES.json` | Machine-readable stage rules: status match, decision, worker, gate, expected next status. |
| `rules/SEEDANCE_MODEL.json` | Loop-wide Seedance model route. Current default: `SD 2.0 mini`, `model=ep-20260625155850-zpss5`. |
| `gates/*.md` | Stage gate contracts: required inputs, PASS/FAIL/STOP rules, retry variable, locked variables. |
| `workers/*.md` | Stage worker contracts: exact inputs, actions, outputs, linked gate, stop conditions. |
| `docs/loop-runbook.md` | Operator runbook for intake, self-audit, speed rules, QC commands, and stop points. |
| `docs/loop-speed-v2-handoff.md` | Implementation handoff for Loop Speed v2 behavior and verification. |
| `docs/issues/loop-speed-v2/` | Completed implementation issues for the Loop Speed v2 slices. |
| `docs/adr/` | ADRs for hash-gated visual QC reuse and direct Seedance approval scope. |
| `docs/kongfengchun-validated-workflow.md` | Validated `孔凤春清洁泥膜` web-side Seedance handoff for `job-001`. |
| `.agents/skills/video-replication/SKILL.md` | Actual video-replication craft method. Must be read before worker execution. |
| `.agents/skills/viral-replica/SKILL.md` | Loop adapter. It maps the craft method into this repository's stages. |
| `workers/checker_worker.md` | Independent checker contract for self-audit mode. |
| `.codex/agents/viral-replica-checker.toml` | Checker agent instructions: review only, no repair. |
| `logs/loop_events.jsonl` | Machine-readable event log for decisions and gate results. |
| `tools/run_next_loop_round.py` | Minimal runner: selects one job, checks stop rules, writes next decision. |
| `tools/checker_review_qc.py` | Validates checker review structure before gate result recording. |
| `tools/qc_outcomes.py` | Normalizes PASS/FAIL/STOP into Hard Failure, Visual Warning, Evidence STOP, provider failure, cost gate, or human review. |
| `tools/visual_asset_manifest_qc.py` | Validates visual asset types, product/identity binding groups, current-job storyboard paths, and final Seedance web upload mapping. |
| `tools/hash_gated_visual_qc.py` | Records active image hashes and reference mappings so downstream stages can reuse heavy visual QC when inputs have not changed. |
| `tools/codex_imagegen_contract_qc.py` | Validates Matpool GPT-Image-2 edit/reference evidence before image-stage PASS. |
| `tools/cross_part_continuity_qc.py` | Generates side-by-side Part comparisons and blocks multi-Part handoff when identity, clothing, scene, lighting, mud/product style, or seam continuity does not read as one stitched video. |
| `tools/skincare_progression_qc.py` | Generates skincare before/after comparisons and blocks handoff when pre-wash skin is already after-wash bright or the improvement appears before wash/wipe proof. |
| `tools/storyboard_geometry_qc.py` | Generates source-vs-final storyboard comparisons and blocks handoff when the promoted image changes the source 12-panel canvas, panel sizes, shot order, or no longer reads like the `job-002` API edit baseline. |
| `tools/storyboard_loop_qc.py` | Current automated storyboard gate. |
| `tools/prepare_story_analysis.py` | Scripted source-video material prep: probe, contact sheet, optional ASR. |
| `tools/image_hard_gate_qc.py` | Scripted image hard gate: layout, refs, mud color, product marker, skin color. |
| `tools/request_body_qc.py` | Scripted request body QC: JSON, taskCode, model EP, URLs, asset refs, prompt embedding. |
| `tools/final_video_qc.py` | Scripted final video technical QC: existence, ffprobe, audio/video streams, duration, freeze detect, black detect, ASR terms, and contact sheet. |
| `tools/timing_report.py` | Builds Markdown timing reports from loop event logs so slow stages are visible. |
| `output/<job-id>/...` | Job artifacts, reviews,废稿说明, prompts, request bodies, videos. |

## Job Row Contract

Every `jobs.csv` row must keep these fields:

| Field | Meaning |
|---|---|
| `id` | Stable job id, e.g. `job-001`. |
| `status` | Current stage or terminal status. |
| `video_path` | Source benchmark video. |
| `product_name` | Target product name. |
| `product_assets` | Product image folder. |
| `person_assets` | Person/model folder. |
| `audio_assets` | `extract_from_original` or explicit audio folder. |
| `target_duration` | Desired final duration. |
| `notes` | User intent and constraints. |
| `output_dir` | Artifact root for the job. |
| `last_artifact` | Most important artifact from the last stage. |
| `next_stage` | Intended next stage. |
| `needs_user_confirmation` | `true` means runner must stop. |

## User-Visible Stages

When explaining progress to the user, lead with these five stages and keep internal `status`, `next_stage`, and canonical stage names as secondary debugging details:

1. 看懂原片
2. 改好分镜
3. 写视频脚本
4. 生成视频
5. 质检交付

## Canonical Stages

The current loop has historical status names. The runner maps them into this canonical structure.

| Canonical stage | Main worker | Pass gate | Next |
|---|---|---|---|
| `story_analysis` | `$video-replication` story analysis + loop adapter | Story analysis doc includes ASR, subtitles, visual timeline, product strategy | `storyboard` |
| `storyboard` | `$video-replication` storyboard extraction and contamination audit | `分镜表与缝点审查.md` + `分镜污染审查.md` exist | `image_batch_qc` |
| `image_batch_qc` | `$video-replication` direct all-Part image batch or fast repair through Matpool GPT-Image-2 | All required Part storyboard images are edited together, `改图审核.md` passes, visual manifest QC passes, artifacts promoted to final image locations | `voiceover` |
| `image_sample` | Optional `$video-replication` image sample through Matpool GPT-Image-2 | Legacy or explicitly requested sample-only stop; not the default route | `image_batch_qc` |
| `voiceover` | `$video-replication` original subtitle + ASR + rewritten script | Script maps lines to shots and source rhythm | `seam` |
| `seam` | `$video-replication` seam design | Boundary states and no-freeze plan written | `seedance_prompt` |
| `seedance_prompt` | `$video-replication` Seedance prompt rebuild | Clean Seedance 2.0 prompts, model-facing reference roles, 3-shot execution groups, no pollution terms | `audio_boundary_qc` |
| `audio_boundary_qc` | `$video-replication` Qwen ASR on reference audio | No duplicated boundary line, every audio <=15.00s, target 14.90s | `request_qc` |
| `request_qc` | `$video-replication` upload refs/audio, build taskCode request JSON | Request body has correct images/audio/order/taskCode and `SD 2.0 mini` EP | `generation_approval` |
| `generation_approval` | Human/cost gate | User explicitly approves paid/batch Seedance generation | `generation` |
| `generation` | Seedance task create + poll + download | Part videos downloaded | `final_qc` |
| `final_qc` | ffprobe, freezedetect, final ASR, contact sheet | Objective technical QC passes; final video delivered | `done` |

## Current Custom Stage Mapping

| Existing status | Canonical stage | Meaning |
|---|---|---|
| `pending` | `story_analysis` | New job waiting for story analysis. |
| `part2_storyboard_loop_passed` | `seedance_prompt` | Storyboard repair has passed; next rebuild Seedance prompt/request. |
| `seedance_inputs_prepared*` | `generation_approval` | Must stop before paid/batch generation. |
| `seedance_generating*` | `generation` | Generation has been approved and is running. |
| `final_qc*` | `final_qc` | Run objective final technical QC; PASS advances to `done` and delivers the final video. |
| `done` | terminal | Complete. |
| `blocked` | terminal | Blocked. |

When a new ad-hoc status appears, add it here and to `rules/STAGE_RULES.json` before teaching the runner to advance it.

## Validated Web-Side Seedance Handoff

As of 2026-06-17, `job-001` for `孔凤春清洁泥膜` has a browser-side Seedance handoff that the user ran and accepted.

Use this as the packaging standard for future web-side handoffs:

```text
output/job-001/seedance_web_final/
```

The loop still stops before paid/API Seedance generation. Browser-side user validation should be recorded in `STATE.md` and docs, not treated as approval for the loop to submit paid/API generation.

## Seedance 2.0 Prompt Standard

As of 2026-06-20, use `job-002` as the prompt-writing baseline:

```text
docs/seedance-20-prompt-standard.md
.agents/skills/video-replication/references/seedance-20-prompt-standard.md
output/job-002/seedance_web_final/prompts/
```

The final prompt must be written for Seedance, not for the loop operator. Use model-facing reference roles, `主目标 / 次目标 / 简化`, and `Shot 1/2/3` execution groups. Preserve key source beats inside those groups, including phone proof shots, product-name close-ups, rinse/wipe proof shots, and final product close-ups when the source has them.

## Visual Asset Type Contract

Image batch may promote only current-job `AI改好分镜图`: saved AI-generated or AI-edited storyboard images that Seedance can directly use as `01_图片1`. The default route skips `image_sample`; after storyboard PASS, generate every required Part storyboard image together in `image_batch_qc` (for example, a 45s job generates Part1, Part2, and Part3 in one batch round). `image_sample` remains only for legacy jobs or explicit sample-stop requests.

The default image-stage operation is simple source-storyboard replacement editing. The source Part storyboard is the edit target; product/person/profile-declared support images are replacement references. The intended edits are limited to replacing the old person, replacing the old product/tool/material with the current product's profile-declared form, material, and usage action, and removing subtitles or old overlays. The original scene, camera crops, hand/action placement, panel grid, shot order, canvas ratio, and action rhythm must remain source-storyboard faithful.

Default person replacement means complete model appearance replacement. The approved model/person reference controls face, hair, body, and clothing. The source storyboard controls only background/scene family, camera crop, shot order, action rhythm, and hand/action placement. Source-video clothing is old-person appearance and must be replaced unless the user explicitly asks for a face-only swap or says to keep source wardrobe.

If a generated candidate changes the source scene, recomposes the storyboard, squeezes the person, changes panel geometry, or changes shot order, do not continue repairing that candidate. Discard it and restart from the source Part storyboard. If Part1 is failing this contract, it cannot be used as a continuity reference for Part2; rebuild Part1 first.

The promoted `AI改好分镜图` must preserve the corresponding source Part storyboard layout and canvas ratio. Portrait precedents such as `job-001` and `job-002` do not authorize forcing a landscape source video into 9:16, 3:4, 4x3-wide, or portrait storyboard panels. By default, portrait source storyboards use 4 columns x 3 rows; landscape source storyboards use 3 columns x 4 rows so each panel remains readable instead of becoming an overlong strip.

Forbidden substitutes:

- source rhythm boards, contact sheets, or cropped source frames
- Python/PIL composites or validated-anchor拼图
- old-job storyboard images
- unsaved image-generation directions

Reusable references are binding-group assets, not storyboards. The required roles come from `output/<job-id>/product_profile.json`:

- generic products: `01_当前job AI改好分镜图`, `02_产品主参考`, `04_身份图`
- clay-mask profiles: additionally require `03_开盖白泥/材质参考`, and may require `05_洗后脸`
- toner and unknown profiles must not inherit `03_开盖白泥` or `05_洗后脸` unless their product profile explicitly declares those roles

Every job that reaches image/prompt/request stages must have:

```text
output/<job-id>/visual-assets/approved_visual_manifest.json
output/<job-id>/product_profile.json
```

`./run-loop.sh --record-gate-result PASS` refuses visual-stage PASS unless the checker review QC and visual asset manifest QC both pass. Image sample and image batch PASS also require passing GPT Image contract QC. Image batch, Seedance prompt, and request handoff PASS also require passing storyboard geometry / API-effect QC against the `job-002` baseline. Multi-Part image batch, Seedance prompt, and request handoff PASS also require passing cross-Part continuity QC. Skincare progression QC is required only when the loaded product profile declares `requires_skincare_progression=true`; a brand name alone must not trigger it. For request QC with audio, final audio duration QC must also pass.

Speed rule: visual QC is evidence, not a reason to restart analysis. After image batch PASS, downstream stages should cite the existing PASS files and active image hashes. Do not rerun image generation, re-open rejected candidates, or redo broad visual review unless the active image hashes, approved visual manifest, material-role table, prompt reference mapping, or a user-reported visual defect changed.

## Cross-Part Continuity Contract

Part1 and Part2 are adjacent slices of the same final video, not independent posters. Before a multi-Part image batch, Seedance prompt, or request handoff can pass, run:

```bash
python3 tools/cross_part_continuity_qc.py --job-id <job-id> --stage <stage>
```

The checker must inspect `output/<job-id>/checks/cross_part_continuity_compare.jpg` and write `output/<job-id>/checks/cross_part_continuity_review.json`.

PASS requires all of these to be true:

- same primary identity
- same wardrobe family
- no obvious clothing change
- same scene family
- compatible lighting and skin
- same product and mud style
- seam feels like one video

Obvious clothing, neckline, sleeve, jacket, hair, scene, lighting, skin, or identity mismatch is a hard FAIL unless the source story explicitly changes outfit or scene and the Seedance prompt carries that transition. Judge wardrobe against the approved model/person reference by default, plus Part-to-Part continuity. Do not judge target wardrobe against source-video clothing unless the user explicitly requested source wardrobe preservation.

## Storyboard Geometry / API-Effect Contract

For image batch, Seedance prompt, and request handoff stages, run:

```bash
python3 tools/storyboard_geometry_qc.py --job-id <job-id> --stage <stage>
```

The checker must inspect `output/<job-id>/checks/storyboard_geometry_compare.jpg` and write `output/<job-id>/checks/storyboard_geometry_review.json`.

PASS requires all of these to be true:

- same 12-panel source storyboard template
- panel sizes match the source storyboard
- shot order matches the source storyboard
- no recomposed/new storyboard collage
- no visually squeezed or flattened subject
- final image reads like the `job-002` API edit baseline

Tiny API output-size drift is allowed, as in `job-002`; changing the source Part canvas from one size class to another, changing the source panel geometry, adding a different border/label system, or visually squeezing the person is `FAIL`.

## Skincare Progression Contract

For skincare, beauty, cleansing mask, cleanser, and mask jobs, before image batch, Seedance prompt, or request handoff can pass, run:

```bash
python3 tools/skincare_progression_qc.py --job-id <job-id> --stage <stage>
```

The checker must inspect `output/<job-id>/checks/skincare_progression_compare.jpg` and write `output/<job-id>/checks/skincare_progression_review.json`.

PASS requires all of these to be true:

- pre-wash skin has a visible use-case problem or normal pre-use texture
- pre-wash skin is not already after-wash bright
- after-wash state appears only after cleaning/wash/wipe proof
- post-wash skin is visibly improved
- improvement is not only lighting/exposure/wet reflection
- real skin texture remains
- the before/after effect reads in the right order

If the opening or pre-wash panels already look as white/clean/polished as the after-wash reference, the image set is a hard FAIL. This must return to image batch repair before Seedance.

## GPT Image Contract

Matpool GPT-Image-2 must follow the project edit/reference discipline. Treat it as an image-edit/reference call with real local image files, not as text-only generation from paths.

Before image batch can pass, write and validate. If a job explicitly uses image sample, the sample must satisfy the same contract:

```text
output/<job-id>/改图小样/codex_imagegen_contract.json
output/<job-id>/image-batch/codex_imagegen_contract.json
output/<job-id>/checks/<stage>_codex_imagegen_contract_qc.json
```

The contract must include:

- `image_route=matpool_gpt_image_2_edit`
- `api_effect_baseline.source=matpool_gpt_image_2_edit`
- `preserve_api_route=true`
- `matpool_uses_real_image_inputs=true`
- API-equivalent reference order from the product profile, for example generic/toner uses `source_storyboard`, `product_front`, `identity_ref`; clay-mask profiles use `source_storyboard`, `product_front`, `product_open_mud`, `identity_ref`, then optional after-wash refs
- API-equivalent generation settings: `quality`, `size`, and `ratio_source` bound to the source Part storyboard canvas
- actual source storyboard, product profile-declared product/material refs, identity, and when needed after-wash image inputs
- invocation or refs evidence proving those image inputs were actually attached/loaded, not merely mentioned as local paths
- source storyboard transfer list: `layout`, `shot_order`, `framing`, `action_rhythm`
- source storyboard exclusion list: `old_product`, `old_tool`, `old_host_identity`, `old_mud_color`, `subtitles`
- per-Part candidate path, prompt path/text, source-risk translations, and checker visual checklist

For profiles that load `category:clay_mask` or `sku:kongfengchun_clean_mud_mask`, old tube/stick/brush/arm-swatch source actions must become hand/finger jar usage. For toner or unknown profiles, source tool actions must become the profile-declared current product action instead. If a promoted image still shows the wrong model, wrong active product, old-source product/person/text, or an action/material forbidden by the loaded profile, the image stage fails even if layout, manifest, or color metrics pass.

## Stage Gate Contract

Every stage must have a matching contract in `gates/*.md`.

Every executable stage should also have a matching worker contract in `workers/*.md`.

Every stage must also write a review or QC artifact with this minimum shape:

```text
Current task:
Current stage:
This round did:
Artifacts:
Verification:
Next:
Needs user confirmation:
Inspection paths:
```

`Inspection paths` must list concrete user-checkable paths whenever a job stops, reaches Seedance web handoff, blocks on QC, or fully completes. Include the active handoff/output directory when ready, plus key images, prompts/audio/manifests/QC reports or the failed QC report when blocked.

Every maker artifact must also include:

```text
Video-replication skill check:
- Skill path read:
- Skill step followed:
- Relevant reference files read:
- Hard rules enforced:
```

If a candidate fails:

```text
Conclusion: 废稿 / failed
Reason:
Which gate failed:
What variable changes next:
What stays locked:
```

## Self-Audit Mode

Default mode remains conservative: one selected job, one selected stage, then stop for the user or next prompt.

When the user explicitly asks for self-audit, auto-run, or "一路跑到底", the loop may repeat one-stage iterations for the same pinned job.

Natural-language requests also count. Examples:

- "做到...停"
- "到...前停"
- "中间不用问"
- "自己检查"
- "直接出"
- "给我素材图和提示词"
- "我自己去网页端跑"
- "不需要最终视频"
- "到 Seedance 生成视频前停"

Use:

```bash
./run-loop.sh --self-audit --job-id job-001
```

The loop still must not skip workers or gates. Each iteration has this shape:

```text
runner decision -> maker worker -> checker review -> checker review QC -> required stage QC -> record gate result -> transition -> next runner decision
```

The orchestrator must not stop after an intermediate `PASS` in self-audit mode. It must run the next decision and continue until the requested stop point or a hard stop.

The maker/checker split is mandatory in self-audit mode:

| Role | Does | Does not do |
|---|---|---|
| Maker | Produces the stage artifact from the worker contract. | Decide whether its own artifact passes. |
| Checker | Reviews the maker artifact against the linked gate. | Repair or rewrite the artifact. |
| Orchestrator | Records the checker result and repeats the loop. | Casually override checker output. |

Checker reviews are saved under:

```text
output/<job-id>/checks/<stage>_gate_review.md
```

Then validated with:

```bash
python3 tools/checker_review_qc.py \
  --review output/<job-id>/checks/<stage>_gate_review.md \
  --gate gates/<stage>_gate.md \
  --out-json output/<job-id>/checks/<stage>_gate_review_qc.json \
  --out-md output/<job-id>/checks/<stage>_gate_review_qc.md
```

If the user wants the loop to stop at a specific stage, pass:

```bash
./run-loop.sh --self-audit --job-id job-001 --stop-at seedance_prompt
```

`--stop-at` can match a job status, `next_stage`, stage rule id, canonical stage, or expected next status.

Self-audit mode can replace intermediate client taste review only when the stage rule explicitly allows it. It cannot approve paid generation by itself, missing assets, or repeated failures. A direct current user request to run Seedance or generate the final video is generation approval for the current explicit job by default and covers every required Part once.

## Retry Policy

Retry is not "try again". Retry changes one variable.

| Failure | Change only this | Keep locked |
|---|---|---|
| Double/multiple model identity | Identity reference set | Layout, product refs |
| Face unlike target | Identity reference, face-binding prompt | Product, scene, layout |
| Cross-Part color mismatch | Part1 color anchor | Product and identity refs |
| Product blank/unknown jar | Product front/open refs | Identity, color, layout |
| Mud is gray | Product open ref + white mud wording | Layout, identity |
| Mud is white but thin | Local Shot06/10 mud texture repair | Whole grid, face, color, product label |
| Localized material/product issue | Fast repair with Matpool GPT-Image-2 | Whole Part, approved panels, downstream prompts |
| Seedance rhythm drift | Subtitle + ASR + visual shot table | Approved images |
| Seam freeze | Boundary motion prompt or continuity frame | Approved shot order |

If the same failure repeats twice after changing the intended variable, step back to the previous stage instead of continuing to spend attempts.

## Stop Rules

The runner must stop when:

- No job is available.
- Selected job is `done` or `blocked`.
- `needs_user_confirmation=true`.
- Required source video, product assets, person assets, or explicit audio assets are missing.
- Next stage is paid or batch Seedance generation and `--allow-paid` plus an approval record are not both present. A direct current user request to run Seedance or generate the final video can be recorded as approval for the current explicit job and its required Parts once. Batch generation still needs explicit batch/all/named-jobs approval; failed-Part retries need new targeted approval.
- `COST_POLICY.md` hard budget is reached.
- Image sample needs user review only when the job explicitly requests a sample stop.
- Image repair failed after the allowed retry budget.
- Same gate failure type reaches `RUNNER_STATE.json` retry limit.
- Final objective technical QC needs more than one targeted Seedance retry.
- Two consecutive rounds have no effective progress.

## Runner State Contract

`RUNNER_STATE.json` records machine-readable gate outcomes.

Minimum shape:

```json
{
  "version": 1,
  "retry_limit": 2,
  "jobs": {
    "job-001": {
      "current_failure_type": null,
      "failure_count": 0,
      "retry_count": 0,
      "consecutive_no_progress": 0,
      "last_gate_result": null,
      "spent": {
        "gpt_image_runs": 0,
        "seedance_runs": 0
      },
      "gate_history": []
    }
  }
}
```

Gate results are recorded with:

```bash
python3 tools/run_next_loop_round.py \
  --root viral-replica-loop \
  --record-gate-result FAIL \
  --failure-type rhythm_drift \
  --retry-variable shot_rhythm_mapping \
  --artifact output/job-001/...
```

`PASS` resets failure count. `FAIL` increments failure count for the same `failure_type`. `STOP` records the stop point without counting it as a repeated failure.

## Event Log Contract

The runner appends structured events to:

```text
logs/loop_events.jsonl
```

Current event types:

- `decision`: selected job, matched rule, worker, gate, and expected next status.
- `gate_result`: recorded gate `PASS` / `FAIL` / `STOP`, artifact, failure type, retry variable, and transition proposal.

Markdown files remain useful for humans, but event history should be reconstructed from JSONL.

## State Transition Contract

Gate result recording can produce a transition proposal in:

```text
RUNNER_LAST_TRANSITION.md
```

Default behavior:

- `PASS` proposes advancing `jobs.csv status` to the decision's expected next status.
- `FAIL` proposes staying on the same status and retrying one variable.
- `STOP` proposes staying on the same status and setting `needs_user_confirmation=true`.

The runner does not edit `jobs.csv` unless explicitly called with:

```bash
--record-gate-result PASS --apply-transition
```

This keeps auto-advance controlled.

## Minimal Runner Responsibilities

The first runner does these things:

1. Read `jobs.csv`, `STATE.md`, `QC_RULES.md`.
2. Read `rules/STAGE_RULES.json`.
3. Read `RUNNER_STATE.json`.
4. Read `COST_POLICY.md`.
5. Select the first non-terminal job.
   - If `--job-id` is provided, select only that job.
6. Apply stop rules, retry-limit rules, and cost-policy rules.
7. Resolve the canonical stage, worker contract, suggested next worker action, and gate contract.
8. Check that the worker and gate contract files exist.
9. Write `RUNNER_LAST_DECISION.md`.
10. When requested, record gate `PASS` / `FAIL` / `STOP` into `RUNNER_STATE.json`.
11. Append structured events to `logs/loop_events.jsonl`.
12. When explicitly requested, apply a safe transition to `jobs.csv`.

It does not call image generation, Seedance, or edit artifacts automatically. In self-audit mode, Codex repeats the runner/maker/checker/record cycle for the pinned job; paid generation still requires explicit approval. A direct user request to run Seedance or generate the final video is explicit approval for the current explicit job and its required Parts once by default.

## Future Runner Upgrades

Detailed roadmap: `LOOP_ROADMAP.md`.

Add in this order:

1. Stage-specific gate scripts.
2. Stage-specific worker commands or adapters.
3. Actual `jobs.csv` mutation after successful worker output.
4. Cost controls for image generation and Seedance.
5. Parallel jobs only after single-job stage logic is stable.
