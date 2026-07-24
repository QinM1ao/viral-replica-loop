---
name: viral-replica
description: Batch viral video replication loop adapter for Codex. Use when a user wants to run or audit viral-replica-loop, turn simple intake into jobs, advance one queued job through workers/gates, self-audit until a stop point, prepare Seedance web handoff before paid generation, enforce cost approval, or inspect loop state. Do not use for craft-only one-shot video replication, standalone Seedance prompt polishing, or general video critique without loop state.
---

# Viral Replica

## Boundary

This production skill owns loop operation, not video craft.

- Owns: intake-to-queue, runner decision, worker/gate sequencing, self-audit checker flow, state writeback, stop points, cost approval boundary, and handoff inspection paths.
- Delegates: story analysis, storyboard, image replacement, compact Pre-Seedance pack craft, generation method, and final QC craft to `.agents/skills/video-replication/SKILL.md`.
- Preserves: existing `workers/*.md`, `gates/*.md`, `rules/STAGE_RULES.json`, `tools/run_next_loop_round.py`, and checker contracts.

If this skill conflicts with `$video-replication`, use the stricter craft rule unless it would bypass this loop's stop, checker, cost, or state boundary.

## Required Reading

Before loop work, read:

- `BRIEF.md`
- `STATE.md`
- `jobs.csv`
- `LOOP.md`
- `rules/STAGE_RULES.json`
- `output/<job-id>/product_profile.json` when it exists
- `.agents/skills/video-replication/SKILL.md`
- the selected `workers/*.md`
- the linked `gates/*.md`

Load the generic rule plus exactly the category/brand/SKU rules listed in the product profile's `loaded_rules`; if no category/SKU rule is listed, use the generic rule. When `loaded_rules` includes `category:clay_mask` or `sku:kongfengchun_clean_mud_mask`, also read `client-profiles/kongfengchun/README.md` before image, prompt, request, or generation work. Keep routing internal: user-facing progress and handoffs name only the active product and its loaded rules, never unselected categories.

## Operating Contract

Use `references/loop-operating-contract.md` for the full production contract. The short form is:

1. Select or create exactly one active job.
2. Advance at most one stage per runner decision.
3. Run the selected worker before the linked gate.
4. In self-audit mode, build the stage QC Risk Ledger after the maker. Skip unchanged `REUSED_PASS` families, let deterministic families pass from program evidence, and run at most one independent checker only for the changed semantic families emitted in the review request.
5. Record gate results only through the runner.
6. Stop before paid/batch generation unless the cost gate has explicit approval scope.
7. For multi-Part image batch, use Part fanout with isolated contracts and a serialized merge before QC.
8. Include concrete inspection paths whenever a job stops, hands off, blocks, or completes.
9. New pending jobs use one `source_blueprint` worker/gate round. The round must run the full-video 2fps and opening 0–3s 5fps Wujie Higress analyses concurrently with one Qwen ASR, then save a measured-cut-aligned rapid-hook timeline; it cannot pass until both provider requests are valid, `剧情分析/source_rhythm.json` has evidence-backed beats, and `checks/source_rhythm_qc.json` passes. Legacy `story_analysis -> storyboard` statuses remain valid for repair but use the same mandatory video-understanding route.
10. Keep non-image work through `seedance_inputs_prepared` within the configured 20-minute budget: source facts are parallel/cacheable, repeated Pre-Seedance views are rendered from `director_plan.json`, and only the selected web/API delivery surface is built.
11. A new version-6 `director_plan.json` must author `speech_groups`, `execution_blocks`, `script_fidelity.mode=source_locked`, and `replication_fidelity.change_policy=necessary_only` separately. Every speech group declares `line_edits`, every target beat declares `visual_edits` plus `visual_fidelity`, and source-length work maps every source beat to exactly one target beat in order; only execution blocks may group beats. The renderer rejects undeclared dialogue/visual rewrites, locked transition changes, blocks wider than five storyboard panels, speech groups that cross blocks, and bloated global rules before any generation request is usable. Product-name count, placement, sentence structure, and repetition follow the source; disable `spoken_product_anchor` when the source never says the product name.
12. If simple intake omits person/model assets, store `person_assets=storyboard_derived` instead of blocking. The craft skill then decides whether the no-model/multi-person storyboard-derived identity branch applies and enforces its role map, current-job identity provenance, and per-Part identity uploads.
13. Generation PASS requires hash-bound subtitle classification evidence. After local finishing, run the conditional project `$video-subtitle-removal` stage: skip clean outputs, or use the one-task workflow standing approval only for a current `burned_in` result; no automatic paid retry. Final QC consumes the stage report's `output_video`.
14. Final captions are a separate opt-in post-production stage. Only when the user explicitly requests captions, record `caption_finishing/request.json`; keep every Seedance prompt subtitle-free, finish the existing flow through final technical QC, then run `$source-faithful-captions` as the last step. Without that marker, `final_qc -> done` remains unchanged.

## Commands

Simple intake becomes queue files:

```bash
python3 scripts/new-task.py \
  --root . \
  --video-dir "<video-folder>" \
  --product-name "<product-name>" \
  --product-assets "<product-image-folder>" \
  --person-assets "<person-image-folder>" \
  --audio-assets "extract_from_original" \
  --target-duration "30s" \
  --notes "<user-notes>"
```

If the user supplied no person/model folder, omit `--person-assets`; intake records `storyboard_derived` automatically.

Get the next decision:

```bash
./run-loop.sh
```

Self-audit one pinned job:

```bash
./run-loop.sh --self-audit --job-id "<job-id>"
```

Record an explicit final-caption request without changing the default intake or generation path:

```bash
python3 tools/caption_finishing_qc.py request \
  --root . \
  --job-id "<job-id>" \
  --explicit-user-request \
  --note "<user request>"
```

Record a gate result:

```bash
./run-loop.sh --record-gate-result PASS --job-id "<job-id>" --stage "<stage>"
```

## Production Assets

- `manifest.json` declares owner, lifecycle, inputs, output contract, exclusions, and rollback boundary.
- `agents/interface.yaml` is the Codex interface contract.
- `references/loop-operating-contract.md` holds detailed loop rules.
- `evals/trigger_cases.json` separates loop work from video craft and prompt-only neighbors.
- `evals/output_cases.json` captures production output assertions.
- `reports/skill_ir.md` preserves the skill contract.
- `reports/output_quality_scorecard.md` summarizes production evidence.
- `reports/trust_report.md` scopes scripts, permissions, cost, and secrets.

## Output Shape

Every worker round should leave a concise artifact with:

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

Failure artifacts should name:

```text
Conclusion:
Gate:
Reason:
Retry variable:
Locked variables:
Inspection paths:
```
