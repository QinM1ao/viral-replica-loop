# Viral Replica Loop Kit

This repository is a runnable loop kit for batch viral video replication.

It is not a single prompt and not only a `SKILL.md`. It is a versionable system:

```text
brief -> jobs.csv -> runner -> worker -> gate -> STATE.md -> next round or stop
```

## Quick Start

For normal Codex use, the user should only need to say:

```text
视频目录：
产品名：
产品图路径：
人物/主播图路径：
声音参考：
目标时长：
备注：
```

Codex should fill the internal files and run the loop.

Manual setup is also available:

```bash
cd viral-replica-loop
./install.sh
cp BRIEF.example.md BRIEF.md
```

Fill `BRIEF.md`, then add one row per source video in `jobs.csv`.

Run the next loop decision:

```bash
./run-loop.sh
```

## Simple Intake Command

Codex can create the internal files from simple paths:

```bash
python3 scripts/new-task.py \
  --root . \
  --video-dir "/path/to/source-videos" \
  --product-name "Product Name" \
  --product-assets "/path/to/product-images" \
  --person-assets "/path/to/person-images" \
  --audio-assets "extract_from_original" \
  --target-duration "30s" \
  --handoff-mode web \
  --notes "close replication; preserve source rhythm"
```

If no person/model images are supplied, omit `--person-assets`. Intake records `storyboard_derived`; multi-person sources then keep the standard workflow but derive necessary role identities from passed current-job storyboards.

`scripts/new-task.py` writes a product profile for the current job. Brand, category, and SKU rules load through:

```text
output/<job-id>/product_profile.json
```

For Kongfengchun products, brand-level rules do not imply mud-mask behavior. Read `client-profiles/kongfengchun/README.md` only when the product profile loads `category:clay_mask` or `sku:kongfengchun_clean_mud_mask`.

Verify the kit:

```bash
./scripts/verify.sh
```

## Reusable Client Workspace

This repository is structured as the reusable Kongfengchun loop workspace. A client can clone the repo, install dependencies, add a new job from local asset paths, and run the same gated loop.

```bash
git clone <repo-url>
cd viral-replica-loop
python3 -m pip install -r requirements.txt
./install.sh
```

The root queue starts empty on purpose. Create the next Kongfengchun task with:

```bash
python3 scripts/new-task.py \
  --root . \
  --video-dir "/absolute/path/to/source-videos" \
  --product-name "孔凤春清洁泥膜" \
  --product-assets "/absolute/path/to/product-assets" \
  --person-assets "/absolute/path/to/person-assets" \
  --audio-assets "extract_from_original" \
  --target-duration "30s" \
  --notes "基本全复刻；到 Seedance 生成视频前停；交付网页端素材图、音频和提示词"
```

For a no-model multi-person source, omit the `--person-assets` line rather than inventing a placeholder folder.

Then run:

```bash
./run-loop.sh --self-audit --job-id job-001 --stop-at seedance_inputs_prepared
```

Kongfengchun experience is preserved in `client-profiles/kongfengchun/`, `rules/product-profiles/`, `docs/kongfengchun-validated-workflow.md`, and `examples/kongfengchun-reference-job-008/`.

If you need to create a separate zip handoff from a live working copy, use `scripts/export-client-workspace.sh`. See `docs/client-workspace-handoff.md`.

## What To Edit For A New Client

- `BRIEF.md`: this client's product, assets, target duration, notes.
- `jobs.csv`: one row per source video.
- `PRODUCT_CONSTRAINTS.md`: product-specific hard rules.
- `QC_RULES.md`: reusable rejection rules learned from feedback.
- `client-profiles/<client>/`: client-specific mined experience, passed standards, failed cases, and reference manifests.

## What Codex Reads

- `AGENTS.md`: repo-level operating rules.
- `.agents/skills/viral-replica/SKILL.md`: loop wrapper and stage adapter.
- `.agents/skills/video-replication/SKILL.md`: real video-replication method and hard-earned craft rules.
- `CONTEXT.md`: shared loop vocabulary such as Pre-Seedance Handoff, Final Video, Visual Warning, Evidence STOP, and Hash-Gated Visual QC.
- `docs/loop-runbook.md`: operator runbook for intake, self-audit, QC, and handoff.
- `docs/video-understanding.md`: Wujie Higress Seed 2.0 Mini setup, architecture, smoke test, evidence contract, and troubleshooting.
- `docs/loop-speed-v2-handoff.md`: current Loop Speed v2 implementation and verification handoff.
- `docs/fast-path-20min.md`: current 20-minute non-image fast path, delivery-mode split, and measurement contract.
- `docs/issues/loop-speed-v2/`: implemented issue set for runner enforcement, QC taxonomy, hash reuse, final QC, cost policy, and timing reports.
- `docs/adr/`: design decisions behind hash-gated QC reuse and Seedance approval scope.
- `docs/kongfengchun-validated-workflow.md`: validated `孔凤春清洁泥膜` web-side Seedance handoff.
- `docs/seedance-20-prompt-standard.md`: current Seedance 2.0 prompt standard, with the 2026-07-17 `job-011` complete 26-second case as the preferred validated example.
- `LOOP.md`: loop contract and stop rules.
- `STATE.md`: current cross-round memory.
- `rules/STAGE_RULES.json`: stage routing table.
- `workers/*.md`: how to do each stage.
- `gates/*.md`: how to judge each stage.

## Validated Web Handoff

As of 2026-06-17, `job-001` for `孔凤春清洁泥膜` has a validated browser-side Seedance workflow. Codex prepared the final upload images, audio, prompts, manifests, and notes, stopped before paid/API generation, and the user confirmed the browser-generated result was acceptable.

Use this handoff directory only:

```text
output/job-001/seedance_web_final/
```

Key rules from the validated run:

- Final web-upload audio files must be `<=15.00s`; target `14.90s`.
- The final handoff directory must contain only active upload assets, prompts, manifests, and notes.
- `孔凤春清洁泥膜` mud must be white or milky-white thick paste; yellow/beige/tan/cream-yellow/gray/watery mud is a failure.
- After-wash proof images must be generated face close-ups from the approved identity, not cropped storyboard panels.
- GPT Image outputs use the Matpool GPT-Image-2 project route only. Do not try any deprecated GPT Image route or gateway probe.
- GPT Image sample and image batch must also pass `tools/codex_imagegen_contract_qc.py`, proving the run used actual source storyboard/product/open-mud/identity image references and did not inherit old tools, products, host identity, mud color, or subtitles from the source video.
- When the product profile declares visible text, designated hero close-ups must keep the major brand/product-name identity and label design. Distant, oblique, multi-bottle, and storyboard-scale microtext only needs visual similarity; microtext-only mismatch is a warning, while wrong product/brand, blank/smoothed/old-source labels, wrong label design, or missing hero-label anchors remain hard failures.
- Multi-person source videos need an explicit role map: only the source-defined protagonist/product host receives the approved identity; secondary roles preserve story function and gender as generic/de-identified people.

## Seedance 2.0 Prompt Standard

As of 2026-07-17, the complete `job-011` Part1+Part2 result is the preferred provider-validated prompt and final-assembly standard:

```text
output/job-011/final-delivery/
docs/seedance-20-prompt-standard.md
.agents/skills/video-replication/references/seedance-20-prompt-standard.md
.agents/skills/video-replication/references/kongfengchun-final-26s-standard.md
```

Final prompts must be model-facing: reference roles, a compact global rule, and ordered `time | Shot 01–02` blocks with `画面 / 声音` plus optional visible-action sound effects. Local repair changes only the failed block; accepted blocks and Parts stay locked. Do not write internal loop terms or dangling context such as `Part1最终分镜图`, `AI改好分镜图`, `current-job`, `原片`, or `source rhythm board` inside the prompt pasted into Seedance.

## Seedance Model Route

The loop-wide video generation route is configured in:

```text
rules/SEEDANCE_MODEL.json
```

Current default: ordinary `Seedance 2.0` with `model=ep-20260521101914-nwv8j`. Model wording is exact: `Seedance 2.0` is ordinary 2.0, `Seedance 2.0 mini` is Mini, and `Seedance 2.0 Fast` is Fast. Explicit user wording overrides the default. Request QC enforces the selected EP; changing the model route must not change story analysis, storyboard, image repair, voiceover, seam, prompt, audio-boundary, cost, or final QC flow.

## What Must Stop

The loop must stop before:

- missing product/person/source assets.
- paid or batch Seedance generation without current scoped approval.
- image, evidence, provider, or final-video technical failure after the retry budget.
- a second paid Seedance retry for the same final objective failure.
- repeated failure with no useful progress.

Final subjective effect review is not a blocking loop gate. If objective final technical QC passes, deliver the Final Video and let the user judge taste after delivery.

## Folder Map

```text
viral-replica-loop/
├── README.md
├── AGENTS.md
├── LOOP.md
├── STATE.md
├── BRIEF.example.md
├── jobs.csv
├── rules/
├── workers/
├── gates/
├── tools/
├── scripts/
├── client-profiles/
├── .agents/skills/viral-replica/
├── .agents/skills/video-replication/
├── output/
└── examples/
```

## Normal Operating Loop

1. Run `./run-loop.sh`.
2. Read `RUNNER_LAST_DECISION.md`.
3. Execute the named worker contract.
4. Run the named gate contract and any script checks.
5. Record the result:

```bash
./run-loop.sh --record-gate-result PASS --artifact output/job-001/path-to-artifact.md
```

Apply the transition only after the gate result is trustworthy:

```bash
./run-loop.sh --record-gate-result PASS --artifact output/job-001/path-to-artifact.md --apply-transition
```

Paid generation needs explicit approval:

```bash
./run-loop.sh --allow-paid --approval-recorded
```

## Self-Audit Auto Mode

When you want Codex to keep going through intermediate stages, use self-audit mode:

```bash
./run-loop.sh --self-audit --job-id job-001
```

Users do not need to say "self-audit". These natural requests mean the same thing:

- "做到生成视频前停"
- "做到 Seedance 前停"
- "中间不用问我，自己检查"
- "直接出素材图和提示词"
- "我自己去网页端跑"
- "不需要最终视频"

Self-audit mode keeps the same job pinned and repeats one-stage iterations:

```text
runner decision -> maker worker -> independent checker -> checker QC -> gate record -> next decision
```

The checker uses:

```text
.codex/agents/viral-replica-checker.toml
workers/checker_worker.md
tools/checker_review_qc.py
tools/codex_imagegen_contract_qc.py for image sample/image batch
```

Checker reviews are saved under:

```text
output/<job-id>/checks/<stage>_gate_review.md
```

To stop at a specific point, add `--stop-at`:

```bash
./run-loop.sh --self-audit --job-id job-001 --stop-at seedance_prompt
```

`--stop-at` matches an achieved status, current rule id, or current canonical stage. It does not stop early on a planned next status.

Self-audit mode does not approve paid/batch Seedance generation. Final video subjective effect review happens after delivery; the loop only blocks on objective technical failure.

## Loop Speed v2

Loop Speed v2 keeps the user-facing flow to two outcomes:

- `Pre-Seedance Handoff`: active upload images, audio, prompts, manifests, and notes are ready before Seedance generation.
- `Final Video`: Seedance has run and objective final technical QC passed.

Intermediate image samples, visual warnings, checker notes, per-Part confirmations, and subjective final-video effect review are internal by default. Heavy visual QC is reused by active image hash when the final images and reference mappings have not changed.

The last delivery stage is deliberately linear: download the generated Parts → build one caption-free master → inspect that exact master for burned-in captions → skip when clean or repair once when needed → run Final Technical QC → add final captions only when the user explicitly requested them. Seedance is never treated as producing a separate subtitle track.

New jobs use `source_blueprint` to combine source analysis and storyboard work. The Pre-Seedance worker authors one `director_plan.json` and renders the repeated files. Stop-before-generation jobs build the web package only; direct-generation jobs build API requests only. The measured non-image target is 20 minutes.

Source-video understanding is now a required part of `source_blueprint`: `tools/video_understanding.py` sends the local source video to Wujie Higress `doubao-seed-2-0-mini-260215`, while ASR and measured frames remain the exact-word/pixel evidence. Set `HIGRESS_API_KEY`, `WUJIEAI_API_KEY`, or `GATEWAY_API_KEY` in the process environment or `~/.config/wujieai/env`. See `docs/video-understanding.md` for the direct smoke command, output contract, architecture, and troubleshooting.

Useful verification commands:

```bash
python3 -m unittest discover -s tests
./scripts/verify.sh
python3 tools/timing_report.py --root . --out output/timing-report.md --job job-003 --job job-005 --job job-006
```
