# Client Workspace Handoff

Use this when Kongfengchun should receive a reusable Viral Replica Loop workspace, not only one job's delivery files.

This handoff is meant to preserve the current Kongfengchun experience: the client profile, product rules, prompt standards, passed/failed lessons, and QC gates stay in the workspace. The reset only removes the live queue and private run history so the client can start their next video cleanly.

## Online Repo Handoff

The online repository itself should be the handoff workspace:

```bash
git clone <repo-url>
cd viral-replica-loop
python3 -m pip install -r requirements.txt
./install.sh
./scripts/release-check.sh
```

Current validation boundary as of 2026-07-06:

- `./scripts/release-check.sh` passes install validation, structural checks, 59 unit tests, and an empty-queue dry run.
- The packaged `examples/kongfengchun-reference-job-008/` handoff has passing prompt contract QC and request body QC for the current Seedance model route.
- A clean export with `--include-reference-job job-008` has been smoke-tested: release check passes, the strict prompt evidence is present, and `./run-loop.sh` stops with no runnable jobs.
- `STRICT_SKILL_CHECK=1 ./scripts/release-check.sh` is expected to fail until provider-backed trigger eval, blind output review evidence, runtime permission probes, package checksum/install evidence, and missing output-case evidence are filled in.

So the repository is suitable as a Kongfengchun reusable client workspace, but it should not be described as a governed/library-grade release or as already proven on every unseen new video.

The root queue is intentionally empty:

- `jobs.csv` contains only the header
- `RUNNER_STATE.json` has no jobs
- `STATE.md` says the workspace is ready for intake
- `BRIEF.md` is a Kongfengchun starter brief, not a private live job

## Optional Zip Export

If you need to send a zip from a live working copy, do not zip the live directory from Finder. Create a clean handoff copy:

```bash
scripts/export-client-workspace.sh --out /tmp/viral-replica-loop-client --force --zip
```

For a Kongfengchun handoff, include the latest known-good reference package:

```bash
scripts/export-client-workspace.sh \
  --out /tmp/kongfengchun-viral-replica-loop \
  --include-reference-job job-008 \
  --force \
  --zip
```

The export script keeps the loop code, skills, gates, workers, docs, tests, product profiles, and examples. It resets:

- `STATE.md`
- `BRIEF.md`
- `jobs.csv`
- `RUNNER_STATE.json`
- `output/`
- `logs/`
- runner decision files

## What Stays For Kongfengchun

These are intentionally preserved:

- `client-profiles/kongfengchun/`
- `rules/product-profiles/brands/kongfengchun.json`
- `rules/product-profiles/categories/clay_mask.json`
- `rules/product-profiles/categories/toner.json`
- `rules/product-profiles/skus/kongfengchun_clean_mud_mask.json`
- `rules/product-profiles/skus/kongfengchun_fermented_toner.json`
- `docs/kongfengchun-validated-workflow.md`
- `docs/seedance-20-prompt-standard.md`
- `docs/seedance-api-asset-route.md`
- `.agents/skills/video-replication/references/`
- `templates/kongfengchun/simple-intake.md`

When `--include-reference-job job-008` is used, the exported workspace also includes:

```text
output/job-008/seedance_web_final/
output/job-008/final-images/
output/job-008/visual-assets/approved_visual_manifest.json
output/job-008/checks/pre_seedance_pack_*.md
output/job-008/prompt_validation_source_speaker_20260706/
```

That snapshot is reference-only. It is not added to `jobs.csv`, so new runs still begin from a clean queue.

## Client Setup

On the client machine:

```bash
cd viral-replica-loop-client
python3 -m pip install -r requirements.txt
./install.sh
./scripts/release-check.sh
```

System tools:

- `python3`
- `ffmpeg`
- `ffprobe`

The default `source_blueprint` route also requires the local `.venv-qwen3-asr` environment so exact spoken words can be checked independently from the semantic model. If it is absent, new-job source understanding stops rather than silently replacing transcript evidence with a model guess.

Provider keys:

```bash
export MATPOOL_API_KEY="..."
export MATPOOL_BASE_URL="https://token.matpool.com/v1" # optional default
export HIGRESS_API_KEY="..." # required Wujie Seed 2.0 Mini source-video understanding
```

`HIGRESS_API_KEY` may instead be named `WUJIEAI_API_KEY` or `GATEWAY_API_KEY`, and can live in `~/.config/wujieai/env`. The exported workspace uses it before ImageGen to call `doubao-seed-2-0-mini-260215` for required source-video understanding. Seedance generation uses its own configured route and remains a separate paid action; the loop stops before paid generation unless explicitly approved.

## First New Task

For one source video or a folder of source videos:

```bash
python3 scripts/new-task.py \
  --root . \
  --video-dir "/absolute/path/to/source-videos" \
  --product-name "Target Product" \
  --product-assets "/absolute/path/to/product-images" \
  --person-assets "/absolute/path/to/person-images" \
  --audio-assets "extract_from_original" \
  --target-duration "30s" \
  --notes "基本全复刻；到 Seedance 生成视频前停；交付网页端素材图、音频和提示词"
```

用户没有提供模特/人物图时，省略 `--person-assets`。系统记录 `storyboard_derived`；若原片多人，先改分镜，审核后再从已批准分镜派生必要人物图。

Then run one decision:

```bash
./run-loop.sh
```

For an unattended run to the web-side Seedance handoff:

```bash
./run-loop.sh --self-audit --job-id job-001 --stop-at seedance_inputs_prepared
```

The client should inspect:

```text
output/<job-id>/seedance_web_final/
```

That directory contains active upload images, audio, prompts, manifests, and QC notes.

## Normal Operating Rule

One loop round advances one stage. If the runner says to execute a worker, follow the worker and gate it names. For Codex usage, the user can simply provide:

```text
视频目录：
产品名：
产品图路径：
人物图路径：
声音参考：直接用原视频提取
目标时长：30秒
备注：基本全复刻；到 Seedance 生成视频前停
```

Codex should convert that intake with `scripts/new-task.py` and then run the loop.

## What Is Not Portable

The exported workspace does not include:

- private source videos
- private product/person assets
- historical output folders
- provider API keys
- paid Seedance results

Any absolute paths in new jobs must be client-local paths.
