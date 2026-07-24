# Viral Replica Loop Operating Contract

This is the production operating contract for `$viral-replica`. It preserves the existing loop kit assets and delegates video craft to `$video-replication`.

## Owned By This Skill

- Simple intake conversion into loop files.
- One-job runner selection.
- One-stage worker/gate sequencing.
- Self-audit checker handoff.
- State and gate result recording.
- Cost approval and stop-point enforcement.
- Final response inspection paths.
- Release and route-boundary evidence for the loop wrapper.

## Not Owned By This Skill

- Story, storyboard, image replacement, compact Pre-Seedance pack craft, generation craft, or final video QC method.
- Provider-specific video-generation strategy except where cost approval and stop boundaries apply.
- Replacing existing `workers/*.md`, `gates/*.md`, `rules/STAGE_RULES.json`, or `$video-replication`.

## Required Inputs

Read these before loop work:

- `BRIEF.md`
- `STATE.md`
- `jobs.csv`
- `LOOP.md`
- `rules/STAGE_RULES.json`
- `output/<job-id>/product_profile.json` when it exists
- selected `workers/*.md`
- linked `gates/*.md`
- `.agents/skills/video-replication/SKILL.md`

For `孔凤春清洁泥膜` jobs, also read the client profile only when `output/<job-id>/product_profile.json` loads `category:clay_mask` or `sku:kongfengchun_clean_mud_mask`:

- `client-profiles/kongfengchun/README.md`

Do not load the Kongfengchun mud-mask profile for `category:toner`, `category:unknown`, or other Kongfengchun products whose profile does not load the clay-mask rule.

## Runner Rules

1. Use `./run-loop.sh` or `tools/run_next_loop_round.py` to decide the next stage.
2. Work on one selected job unless a coordinator explicitly plans fixed job lanes.
3. Advance at most one stage per runner decision.
4. Do not skip the selected worker or linked gate.
5. Write every completed round back through the existing state/gate path.
6. Treat missing evidence as `FAIL` or `STOP`, not `PASS`.
7. New pending jobs combine source analysis and storyboard preparation in `source_blueprint`; the two old stages remain legacy/focused-repair entry points. Every entry point must call Wujie Higress `doubao-seed-2-0-mini-260215` for semantic source-video understanding and preserve provider/model/source-hash/request evidence before PASS.
8. Use `handoff_mode=web|api|both` to build only the selected delivery surface. Stop-before-generation intake defaults to `web`; direct generation defaults to `api`.
9. Measure explicit decision-to-gate durations and keep non-image work through `seedance_inputs_prepared` within `rules/PERFORMANCE_BUDGET.json`.
10. Final captions are opt-in only. An explicit user request must be recorded with `tools/caption_finishing_qc.py request`; otherwise final technical QC transitions directly to `done`. When requested, keep Seedance subtitle-free and run `$source-faithful-captions` only after final technical QC passes.
11. Generation binds downloaded Parts only. Local finishing creates one caption-free master; `subtitle_removal` then inspects that exact file once and accepts only `clean` or `burned_in`. The standalone subtitle skill may support separate-track remuxing, but the loop adapter must not expose that branch.

## Self-Audit Rules

Use self-audit when the user asks or implies:

- "做到...停"
- "到...前停"
- "中间不用问"
- "自己检查"
- "直接出"
- "给我素材图和提示词"
- "我自己去网页端跑"
- "不需要最终视频"
- "到 Seedance 生成视频前停"

Self-audit sequence:

1. Maker executes the selected worker.
2. Build `output/<job-id>/checks/<stage>_qc_risk_ledger.json`; unchanged families become `REUSED_PASS` and deterministic families use program evidence.
3. Only when the ledger emits `<stage>_semantic_review_request.json`, run one checker using `workers/checker_worker.md` and `.codex/agents/viral-replica-checker.toml` for the requested families.
4. Save and validate that single review with `tools/checker_review_qc.py --risk-request ...`, then rebuild the ledger.
5. Normalize Shot labels before the first image-content review. Passing metadata-only evidence is a lightweight proof, not a reason to run the content review twice.
6. Run the stage-specific QC scripts required by `LOOP.md` and `rules/STAGE_RULES.json`.
7. Record gate result through `./run-loop.sh --record-gate-result ...`.
8. Continue only until the requested stop point, a hard stop, or a final judgment stop.

## Hard Boundaries

- Do not submit paid/API Seedance generation without explicit approval scope.
- Batch approval requires explicit batch, all, or named-job scope.
- A direct request to run Seedance covers only the current explicit job by default.
- Failed-Part retries require new targeted approval.
- Browser-side manual validation may be recorded, but must not retroactively authorize API generation.
- Parallel work must use fixed job lanes or image-batch Part fanout. Image-batch Part fanout must write isolated per-Part contracts and invocation evidence, then serially merge before shared QC. Coordinator-owned shared-state writes remain serialized.

## Visual And Handoff Boundaries

Image/prompt/request PASS must preserve the hard gates already enforced by the loop:

- checker review QC
- visual asset manifest QC
- Codex ImageGen contract QC where Codex ImageGen is used
- storyboard geometry QC for image batch, prompt, and request stages
- cross-Part continuity QC for multi-Part handoffs
- skincare progression QC for skincare, beauty, cleanser, cleansing mask, and mud-mask jobs
- final audio duration QC for web upload audio

Only the Shot-label metadata-only normalization defined by the video-replication image fact source may postprocess a current-job AI-edited storyboard, and it must prove zero panel-pixel changes. Do not promote source rhythm boards, contact sheets, cropped source frames, other Python/PIL composites, old-job images, deprecated drafts, or unsaved image directions as final Seedance upload assets.

## Output Contract

Stop, handoff, blocked, and completion responses must include concrete inspection paths:

- active handoff or output directory
- key images
- prompts
- audio
- manifest or request files
- checker/gate/QC reports
- failed QC report when blocked

Keep user-facing handoff directories thin: upload images, audio, prompt files, active manifests, and minimal README only.
