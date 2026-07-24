# Image Repair Worker

## Canonical Stage

`image_batch_qc`

## Purpose

Repair or regenerate failed storyboard images while preserving already approved variables.

## Inputs

- Failed candidate image.
- Gate failure reason.
- Retry variable from `RUNNER_STATE.json`.
- Approved storyboard layout.
- Product assets.
- `output/<job-id>/product_profile.json`.
- Single approved identity reference.
- Previous passed reference images.
- `QC_RULES.md`.

## Actions

Before repair, read `.agents/skills/video-replication/references/codex-imagegen-direct.md`; it remains the single GPT Image edit contract for repair runs.

1. Read the gate failure reason.
2. Identify the one retry variable that may change.
   - If the only failure is Shot navigation text, run `Deterministic Shot-label normalization` from `codex-imagegen-direct.md`, preserve every panel pixel, write its evidence, skip Matpool, and skip all content-heavy QC. Only visual asset manifest QC is required for this metadata repair.
3. Lock all approved variables.
   - Preserve the source storyboard Shot-label bars, their positions, and panel correspondence; the deterministic branch restores only their navigation text.
4. Prefer fast local repair when only one panel or one material attribute fails.
   - Use `.agents/skills/video-replication/scripts/generate.py` as the only GPT Image route.
   - Do not try any deprecated GPT Image route or gateway probe.
   - Do not regenerate the whole Part for a localized issue such as mud color, product label, or one missing product panel.
5. Save every attempt with prompt, refs manifest, QC output, and failed/pass note.
6. Promote only passed outputs into `最终改图/`.
7. Sync passed repairs into `final-images/`, `seedance/seedance_refs/`, and the final web handoff directory when those already exist.
8. For a panel-content repair, rerun only its affected content checks plus visual asset manifest QC. For a Shot-label-only normalization, run only visual asset manifest QC; the matching panel-content fingerprint preserves earlier geometry, continuity, skincare, identity, and product results.

## Scripted Part

After each repaired candidate, run the hard image check:

```bash
python3 viral-replica-loop/tools/image_hard_gate_qc.py \
  --candidate "<repaired-candidate>" \
  --part1-anchor "<approved-part1-image>" \
  --refs "<approved-identity-ref>" \
  --required-ref-name "<identity-file-name>" \
  --out-json viral-replica-loop/output/<job-id>/改图重试/image_hard_gate.json \
  --out-md viral-replica-loop/output/<job-id>/改图重试/image_hard_gate.md
```

When the product profile loads clay-mask rules, the reviewer must also visually compare face-applied mud and open-jar mud against the product material reference. If the script passes but the mud still reads yellow, beige, tan, or skin-toned, record `FAIL` and keep repairing in image generation. For non-clay-mask products, repair against the profile-declared product form, material, label, and usage action instead.

## Outputs

Write under `output/<job-id>/改图重试/`:

- repair prompt
- refs manifest
- repaired candidate
- QC JSON or markdown
- `废稿说明.md` or `通过说明.md`

Promote final passed image to:

- `output/<job-id>/最终改图/`

## Gate

Run the same gate that failed, normally:

`gates/image_sample_review_gate.md`

or a future image batch gate when added.

## PASS Next Status

Use the linked stage rule's next status.

## FAIL Retry Variables

Use the failed gate's retry variable list. Change only one variable.

## Stop Conditions

- Same failure repeats after one targeted retry in fast-repair mode.
- User review is required.
- Repair would require changing an already approved variable.
