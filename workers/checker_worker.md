# Checker Worker

## Canonical Stage

`checker_review`

## Purpose

Run an independent checker after a maker worker finishes a stage.

The checker is not allowed to repair, rewrite, or improve the maker output. It only decides whether the linked gate returns `PASS`, `FAIL`, or `STOP`.

For active `image_batch_qc`, `storyboard_visual_acceptance` is the sole semantic image interface. Inspect its canonical overview plus every bound original artifact exactly once, return one explicit result for each requested family, and make the top-level result equal the worst family result. Do not create or invoke separate geometry, continuity, or skincare reviews; those names are families inside the one request. Missing/unexpected families or stale context must return `STOP`.

## Inputs

- Current `RUNNER_LAST_DECISION.md`.
- The maker output artifact for the current stage.
- The linked `workers/*.md` file.
- The linked `gates/*.md` file.
- `BRIEF.md`.
- `STATE.md`.
- `jobs.csv`.
- `LOOP.md`.
- `QC_RULES.md`.
- `PRODUCT_CONSTRAINTS.md`.
- `output/<job-id>/product_profile.json`.
- Relevant `client-profiles/<client>/` files only when the product profile explicitly loads that client/category/SKU rule.
- Any stage script QC outputs, when the stage has a script.
- For image sample, image batch, Seedance prompt, and request handoff gates: `output/<job-id>/visual-assets/approved_visual_manifest.json`, product group manifest, identity group manifest, and `tools/visual_asset_manifest_qc.py` output.
- For image sample and image batch gates: `codex_imagegen_contract.json` plus `tools/codex_imagegen_contract_qc.py` output.
- For active image batch: the `tools/storyboard_visual_acceptance.py` report, its one canonical compare, and every original artifact bound by the request. Geometry/appearance, identity/product/material integrity, cross-Part continuity, and profile-required skincare progression are families inside this request, not separate artifacts.
- For `pre_seedance_pack`: complete source ASR/subtitles/visual analysis, `voiceover/replication_function_coverage.md`, `voiceover/shot_line_map.md`, and the source-aware speech-budget result.
- For `source_blueprint`: `剧情分析/video_understanding/analysis.json` plus request manifest/raw response, `剧情分析/source_rhythm.json`, its 5fps evidence frames, raw ASR source, and passing `checks/source_rhythm_qc.json`.
- For `subtitle_removal`: the current detection/selected-output manifests, original and repaired videos, every detected subtitle interval, the source/result contact evidence, both 8fps high-risk windows, `visual_qc.json`, and the paid-attempt record. The maker's booleans are claims, not proof.
- For new-flow `pre_seedance_pack`: passing `checks/pre_seedance_pack_source_rhythm_qc.json`, produced by comparing `source_rhythm.json` with `seedance/director_plan.json`.
- `output/<job-id>/checks/<stage>_semantic_review_request.json`. Inspect only the changed Semantic QC families named there; `REUSED_PASS` families are locked evidence and must not be reopened.

## Agent

Use:

```text
.codex/agents/viral-replica-checker.toml
```

## Actions

Before invoking this worker, run `python3 tools/qc_risk_ledger.py --root . --job-id <job-id> --stage <stage>`. If the ledger is `PASS`, do not invoke the checker. If it emits a semantic review request, invoke the checker exactly once for every family in that one request.

1. Read the linked gate contract and the semantic review request. Do not inspect risk families absent from that request.
2. Read the maker artifact directly.
3. Read the required shared rules and product profile. Read a client profile only when the product profile explicitly loads that client/category/SKU rule.
4. Check whether required script QC artifacts exist and whether they passed.
5. For image stages, first validate schema-v2 Shot-label evidence. If it is missing or fails, return the evidence failure before broad visual inspection. If it passes, inspect the normalized image exactly once; do not OCR the 12 deterministic labels or reopen content inspection because of label metadata.
6. For image sample and image batch stages, inspect the actual image files against `codex_imagegen_contract.json`. The checker must verify the target protagonist/product host visually matches the active identity, secondary characters preserve the source role/gender map without becoming the protagonist identity, the product is the target product, source tool/product/person/text contamination is absent, and the source storyboard was used as the edit target rather than a failed generated candidate.
7. For image sample and image batch stages, enforce the simple replacement edit contract: scene, camera crops, hand/action placement, panel grid, shot order, and subject proportions must remain source-storyboard faithful; only person, product/tool/mud, and subtitles/old overlays should change.
8. For active image batch, inspect the canonical overview and bound originals once. Return an explicit result for every requested family. The geometry/appearance family covers source grid, Shot order, proportions, squeeze/crop drift, and recomposition; continuity covers adjacent Parts; skincare progression is included only when required by the loaded profile. Do not write family-specific compare or review files.
9. Apply the request's label review policy literally. `small_or_distant_product_text=visual_match_only` means distant, oblique, multi-bottle, or storyboard-scale microtext is judged by overall label color, line layout, brand impression, and product identity; it need not reproduce every tiny character. `microtext_only_mismatch_outcome=VISUAL_WARNING` means such microtext variation must not be the sole reason for hard `FAIL`. For this label warning, write `Failure type: product_label_microtext_only`; no other label-related failure type may use `VISUAL_WARNING`. A hard label failure remains valid for a wrong product or brand, wrong bottle/package form, invented spray/mist hardware, wrong label design, blank or smoothed label, old-source label, or a designated hero close-up whose major brand/product-name anchor is missing or clearly wrong.
11. For visual stages, require passing visual asset manifest QC before returning `PASS`.
12. For image sample and image batch stages, require passing GPT Image contract QC before returning `PASS`.
13. For `source_blueprint`, first confirm the Seed 2.0 Mini analysis used the exact configured Wujie provider/model, HTTP 200, and current source hash. Then inspect the real source video plus cited 5fps frames. Treat model output as semantic coverage, not ground truth: any conflict with raw ASR, visible text, measured cuts, or pixels must be resolved in favor of direct evidence. Confirm every source beat's line, speaker mode, scene, camera, framing, hard-cut/continuous transition, emphasis, pause, action peak, emotion function, visual action, and `visual_action_type`. Confirm every `spoken_product_names` item is literally a product/brand entity in the line, never a hook or selling sentence. For every `physical_change`, inspect all three before/peak/after refs and confirm that contact/motion and the visible after-state really occur. A plausible model or prose summary cannot override raw ASR or visible-text evidence; any unsupported word correction or imagined action is `FAIL`.
14. For `source_blueprint`, write `output/<job-id>/checks/source_rhythm_visual_review.json` with one item for every source beat, including `removable`: `beat_id`, `reviewed_frame_refs`, `description_matches_evidence`, `action_type_matches_evidence`, optional `physical_action_matches`, and concrete `notes`. When `spoken_product_names` is non-empty, also include the exact `confirmed_spoken_product_names` list and `spoken_product_names_are_product_entities=true` only after the cited pixels confirm that the words name a product or brand rather than an arbitrary phrase. Then run:

```bash
python3 tools/source_rhythm_visual_review_qc.py \
  --root . \
  --source-rhythm output/<job-id>/剧情分析/source_rhythm.json \
  --review output/<job-id>/checks/source_rhythm_visual_review.json \
  --out-json output/<job-id>/checks/source_rhythm_visual_review_qc.json \
  --out-md output/<job-id>/checks/source_rhythm_visual_review_qc.md
```

Do not return `PASS` when this QC is missing or not `PASS`. A gate-review paragraph is not a substitute for the per-beat JSON.
15. For `pre_seedance_pack`, first apply `.agents/skills/video-replication/references/source-replication-contract.md`. Compare every source beat—not only the maker's `must_keep` / `mergeable` labels—against the complete source ASR, subtitles, source visuals, target beats, target speech groups, `source_script_fidelity.md`, and `source_replication_fidelity.md`. In `source_length` mode require exact-once source-beat coverage in original order, exactly one source beat per target beat, and source-scaled beat timing. Verify every source line and speaker mode at its own beat, every unchanged hook remains verbatim, every `line_edits` / `visual_edits` item is genuinely necessary and limited to the stated slot, no product name was injected when the source did not say one, and source actions, scenes, camera/framing, action stages, hard cuts, emphasis, pauses, and rhythm are not creatively rewritten. A capacity or function-coverage PASS is insufficient.
   - When the semantic review request contains `source_to_generation_fidelity.scope.line_edit_audit`, return one `Line edit results` JSON entry for every requested edit ID. Each entry must contain `result`, boolean `necessary`, boolean `minimal`, `evidence_checked=true`, and a concrete `note`. A source-family PASS requires every edit to be both necessary and minimal; an overall sentence such as “all line edits pass” is not coverage. Treat a missing profile field as absence, not contradiction: reject any frequency edit justified only by “资料未提及”; frequency may change only when the bound current profile directly states a different target frequency.
   - For prompt-only repairs, distinguish internal deletion evidence from model-facing instructions. If the approved storyboard already removed an object, confirm the final prompt describes only the retained scene/actions and does not repeat the deleted object through phrases such as “前景无产品”, “不陈列产品”, or “不出现旧产品”.
16. For `pre_seedance_pack`, compare every beat's `source_visual_action` and `target_visual_action` against the actual source video/storyboard and product profile. The target may preserve the source action or perform an explicit product translation; it may not invent an earlier setup step, merge a source hard cut into one continuous action, or add an action merely to justify a sound effect. Compare every `sound_effect` to the visible target action. Any unsupported action or sound is `FAIL` with retry variable `shot_line_binding`.
17. Require source-rhythm-to-director-plan QC to reject changed source order, uncovered required beats, rapid hooks stretched beyond the whole-video scaling allowance, or speech blocks below 80% of the mapped source speaking rate. These are `FAIL`, not creative discretion.
18. When one semantic review request contains multiple risk families, add `Family results` as one compact JSON object that names every requested family separately, for example `{"visual_integrity":"PASS","source_to_generation_fidelity":"FAIL"}`. The top-level result is the worst family result. This prevents one local failure from invalidating unrelated passed families.
18a. For `subtitle_removal`, inspect the actual source and repaired videos plus all bound frame sequences. Confirm every intended subtitle is absent, valid scene text remains, foreground subjects are undamaged, and repaired pixels do not flicker or crawl. Return the `subtitle_repair_quality` family result; do not repair or request another paid task.
19. Return exactly one result: `PASS`, `FAIL`, or `STOP`.
20. Record `Outcome type` as `PASS`, `HARD_FAILURE`, `VISUAL_WARNING`, `EVIDENCE_STOP`, `PROVIDER_FAILURE`, `COST_GATE`, or `HUMAN_REVIEW`.
21. If using `VISUAL_WARNING`, keep `Result: PASS` and write `Why not fail`. Do not use warnings for wrong person/product/wardrobe, source contamination, changed shot order, visible squeeze, missing or unsaved output, or thin/watery/gray/yellow mud.
22. If required proof is missing or inconsistent, use `Result: STOP` with `Outcome type: EVIDENCE_STOP`.
23. If `FAIL`, choose exactly one retry variable from the gate contract.
24. Write the checker review under:

```text
output/<job-id>/checks/<stage>_gate_review.md
```

25. Bind the single checker result to the requested family fingerprints before recording it:

```bash
python3 tools/checker_review_qc.py \
  --review output/<job-id>/checks/<stage>_gate_review.md \
  --gate gates/<stage-gate>.md \
  --risk-request output/<job-id>/checks/<stage>_semantic_review_request.json \
  --out-json output/<job-id>/checks/<stage>_gate_review_qc.json \
  --out-md output/<job-id>/checks/<stage>_gate_review_qc.md
```

## Output Shape

```text
Gate:
Job:
Stage:
Input artifacts:
Checks:
Result: PASS / FAIL / STOP
Family results: {"<requested-family>":"PASS / FAIL / STOP"}
Line edit results: {"<part:speech-group:index>":{"result":"PASS / FAIL / STOP","necessary":true,"minimal":true,"evidence_checked":true,"note":"<evidence-based reason>"}}
Outcome type: PASS / HARD_FAILURE / VISUAL_WARNING / EVIDENCE_STOP / PROVIDER_FAILURE / COST_GATE / HUMAN_REVIEW
Why not fail:
Reason:
Failed item:
Failure type:
Retry variable:
Locked variables:
Next status:
Needs user confirmation:
```

## PASS Next Step

Record the checker result and apply the transition:

```bash
./run-loop.sh --record-gate-result PASS --artifact output/<job-id>/checks/<stage>_gate_review.md --apply-transition
```

## FAIL Next Step

Record the checker result without applying a transition:

```bash
./run-loop.sh --record-gate-result FAIL \
  --failure-type "<failure_type>" \
  --retry-variable "<retry_variable>" \
  --artifact output/<job-id>/checks/<stage>_gate_review.md
```

## STOP Next Step

Record the checker stop:

```bash
./run-loop.sh --record-gate-result STOP --artifact output/<job-id>/checks/<stage>_gate_review.md --apply-transition
```

## Non-Negotiable Rules

- The checker must not edit maker artifacts.
- The checker must not approve paid or batch generation.
- The checker must not judge subjective final video taste; it only checks objective final technical failures.
- The checker must not pass a stage when required evidence is missing.
- The checker must not repair images, rewrite manifests, copy assets, or create replacement composites.
- For visual gates, the checker must not return `PASS` unless checker review QC and visual asset manifest QC can both pass.
- For image sample and image batch gates, the checker must not return `PASS` unless GPT Image contract QC also passes.
- For image batch, Seedance prompt, and request visual gates, the checker must not return `PASS` unless storyboard geometry / API-effect QC also passes.
- For multi-Part visual gates, the checker must not return `PASS` unless cross-Part continuity QC also passes.
- When required by the product profile, the checker must not return `PASS` unless skincare progression QC also passes.
- `01_图片1` must be current-job `AI改好分镜图`; product support refs must come from the same product group; identity/after-wash refs must come from the same identity group when present.
- For image sample, image batch, Seedance prompt, and request handoff gates, inspect the actual image paths. Do not pass a stage just because a role table says old-source pixels are "motion-only" or should be ignored.
- Part1 and Part2 are adjacent slices of the same final video. Obvious clothing, neckline, jacket, sleeve, hair, scene, lighting, skin, or identity mismatch between adjacent Parts is a hard `FAIL` unless the source story explicitly changes outfit/scene and the prompt carries that transition.
- Do not approve a Part2 continuity repair that used a failing Part1 as reference. If Part1 is squeezed, recomposed, wrong-scene, or otherwise not source-storyboard faithful, Part1 must be rebuilt first.
- Do not approve cosmetic retry loops on a candidate that has already changed the source scene, storyboard grid, shot order, or subject proportions. That must restart from the source storyboard.
- Skincare before/after must progress in the right order. If pre-wash panels already look like the after-wash beauty reference, or if bright clean skin appears before wash/wipe proof, return hard `FAIL`.
- Visible old product, old person, old subtitles/text, gray/yellow source mud, or source-video frame boards in final upload images are hard `FAIL`. Prompt wording and material-role notes cannot override contaminated pixels.
- For clay-mask profiles, visible tube applicators, stick applicators, brush heads, cotton swabs, arm swatches, wrong mud color/texture, or wrong jar action are hard `FAIL`. For all profiles, blank/generic/invented active products, wrong current-product action, or a model who does not match the approved identity are hard `FAIL`.
- For products with visible label text, require major brand/product-name identity in a designated hero close-up, but do not OCR every line. Distant, oblique, multi-bottle, or storyboard-scale microtext follows `small_or_distant_product_text=visual_match_only`; `microtext_only_mismatch_outcome=VISUAL_WARNING` and must not be the sole reason for hard `FAIL`. Wrong product/brand, blank or smoothed labels, old-source labels, and clearly wrong major hero-label anchors remain hard `FAIL`.
- For multi-person source stories, changing a supporting role into the approved protagonist identity, or changing a male support role into the female protagonist, is hard `FAIL`.
- A missing saved Codex image-generation output is missing evidence. Do not accept "Codex generated a direction but it was not saved" as `PASS`.
- The main agent records the checker result; it does not overrule the checker casually.
