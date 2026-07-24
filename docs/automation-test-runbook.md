# Automation Test Runbook

Date: 2026-06-20

This document describes the test-phase automation target for the loop engineer. It is not the production switch.

## Current Test Scope

- Cadence: daily once.
- Source video inbox: `/path/to/kongfengchun/source-videos`.
- Product assets: `/path/to/kongfengchun/product-assets`.
- Person/model assets: `/path/to/kongfengchun/model-assets`.
- Product name: `孔凤春清洁泥膜`.
- Audio source: `extract_from_original`.
- Target stop: prepare `output/<job-id>/seedance_web_final/`, then stop before Seedance generation.

## Intake Sync

Use this safe incremental sync before selecting jobs:

```bash
python3 scripts/sync-inbox-to-jobs.py \
  --root . \
  --video-dir "/path/to/kongfengchun/source-videos" \
  --product-name "孔凤春清洁泥膜" \
  --product-assets "/path/to/kongfengchun/product-assets" \
  --person-assets "/path/to/kongfengchun/model-assets" \
  --audio-assets "extract_from_original" \
  --target-duration "30s"
```

This appends only missing videos. It must not rewrite existing job rows, reset `STATE.md`, or replace current artifacts.

## Model Selection Rule

The source-video story analysis decides the host gender before image generation:

- Source male host -> randomly choose one male model from the model library.
- Source female host -> randomly choose one female model from the model library.
- Avoid reusing the same identity across mud-mask benchmark videos when there are viable alternatives.
- Record the selected identity reference in the job artifacts and visual manifest before image generation.

For this test phase, this overrides the older single-male Kongfengchun default, but all product, white-mud, prompt, QC, audio, and stop rules still apply.

## Loop Run Target

For each selected job, run self-audit mode until the web-side Seedance handoff is ready:

```bash
./run-loop.sh --self-audit --job-id <job-id> --stop-at seedance_inputs_prepared
```

The automation must still follow:

- maker worker first
- independent checker review
- checker review QC
- visual asset manifest QC
- audio duration QC when audio exists
- request QC / final handoff QC
- `./run-loop.sh --record-gate-result ...`
- `STATE.md` writeback each round

## Parallel Lanes

Parallel processing is allowed only with fixed job isolation:

- One thread handles one fixed job id.
- Do not let multiple threads run plain `./run-loop.sh` without `--job-id`.
- Use `scripts/parallel-lanes.py` to choose lanes and skip jobs that already reached `seedance_inputs_prepared` or `generation_approved`.
- `tools/run_next_loop_round.py` uses `.run-loop.lock` when reading or writing shared runner files, so gate commits serialize even when workers are parallel.
- Workers may generate per-job artifacts in parallel under `output/<job-id>/`.
- Workers may use shared product/identity groups only through manifest files; when creating a missing identity reference, save it once under `output/shared/...` and rerun visual manifest QC.

Recommended test limit: 3 worker threads at once.

Plan the current lanes with:

```bash
python3 scripts/parallel-lanes.py --root . --self-audit --max-workers 3
```

Each lane must run the printed command. The scheduler or lead agent then reviews the lane outputs and records/continues gates with the same fixed job ids.

## Evidence Ledger And Repair Planning

Use the evidence ledger before starting a daily run. It combines `jobs.csv` with blocking QC results, so the runner does not treat a job as ready when a later hard check has already failed.

```bash
python3 tools/evidence_ledger.py --root . --self-audit --report-md output/evidence-ledger-report.md
```

For image-batch failures, create one repair plan before generating more images:

```bash
python3 tools/image_batch_run.py --root . --job-id <job-id>
```

The plan is written to:

```text
output/<job-id>/image-batch/run-plan/
```

When a failure teaches a reusable rule, record it as a lesson:

```bash
python3 tools/record_lesson.py --root . --job-id <job-id> --from-qc auto
```

This appends a structured entry to:

```text
client-profiles/kongfengchun/lesson-registry.jsonl
```

## Image Generation Route

For image sample, image batch, after-wash references, and local repairs:

- Before ImageGen, require `output/<job-id>/storyboard_source_refs/source_storyboard_manifest.json`.
- Preserve the source Part storyboard's aspect ratio. Portrait precedents such as `job-001`/`job-002` do not justify forcing a landscape source video into 9:16, 3:4, 4x3-wide, or portrait panels. Default storyboard layout is 4 columns x 3 rows for portrait sources and 3 columns x 4 rows for landscape sources.
- Use the project Matpool GPT-Image-2 route only.
- Generated files must be written directly to the current job output path with `--file`.
- Copy selected outputs into the job or shared identity/product folder before recording any PASS.
- Record `image_route=matpool_gpt_image_2_edit`.
- Do not try any deprecated GPT Image route or gateway probe.

## Automation Prompt Draft

```text
Daily test-phase loop engineer for viral-replica-loop.

First sync the source inbox with scripts/sync-inbox-to-jobs.py using:
- video inbox: /path/to/kongfengchun/source-videos
- product name: 孔凤春清洁泥膜
- product assets: /path/to/kongfengchun/product-assets
- model assets: /path/to/kongfengchun/model-assets
- audio: extract_from_original
- target duration: 30s

Then select runnable jobs with `python3 scripts/parallel-lanes.py --root . --self-audit --max-workers 3`. During testing, run up to 3 parallel lanes by default. Each worker must be pinned to one job id and must not run plain ./run-loop.sh without --job-id.

For each job, read AGENTS.md, BRIEF.md, STATE.md, LOOP.md, jobs.csv, rules/STAGE_RULES.json, .agents/skills/viral-replica/SKILL.md, .agents/skills/video-replication/SKILL.md, client-profiles/kongfengchun/README.md and its required profile files, plus the current worker/gate/reference files.

Run self-audit loop stages until output/<job-id>/seedance_web_final/ is ready, then stop before Seedance generation. Follow the canonical Seedance 2.0 prompt standard in `.agents/skills/video-replication/references/seedance-20-prompt-standard.md`. Final prompts must use ordered `time | Shot 01–02` blocks with bound visual/voice/SFX and must not contain internal workflow labels.

Model selection: infer source host gender during story analysis, then randomly choose a gender-matched model from the client-local model asset folder. Avoid reusing the same identity across benchmark jobs when viable alternatives exist. Record the selected identity before image generation.

Identity reference clothing is not target clothing. Use the selected model image for face/hair/identity only; wardrobe follows the source video unless the user explicitly asks to transfer the model outfit.

Speed rule: after a job has image batch PASS with recorded active image hashes, later voiceover/seam/prompt/request lanes should reuse those PASS QC artifacts by hash. Do not reopen image repair or broad visual QC unless active image hashes, approved manifests, material roles, prompt reference mappings, or a user-reported visual defect changed.

Never submit paid/API Seedance generation, never skip maker/checker/gates/QC, and never promote source frames, contact sheets, old-job images, or Python/PIL composites as final upload images. Stop and report missing assets, repeated failures, subjective review needs, cost approval, or any Seedance generation boundary.
```
