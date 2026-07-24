# Non-Image 20-Minute Fast Path

## Objective

From task intake to `seedance_inputs_prepared`, all non-image work must finish within 20 minutes. Matpool provider wait, image review, image repair, and paid Seedance generation are measured separately.

## First-Principles Shape

Before paid generation, the loop only needs to prove three things:

1. The source story, speaker modes, shot order, and product-action translations are correct.
2. The approved images and reusable references are clean and correctly bound.
3. The final prompts, audio, and chosen delivery surface are internally consistent.

The default path is therefore:

```text
source_blueprint -> image_batch_qc -> director_plan/rendered pre_seedance_pack -> seedance_inputs_prepared
```

`source_blueprint` combines source analysis and storyboard work in one checked round. It prepares ASR, storyboard refs, real scene cuts, 5fps evidence, and audio energy in parallel; the worker then authors evidence-backed beats in `source_rhythm.json` and must pass `source_rhythm_qc`. `pre_seedance_pack` uses `director_plan.json` as the single authored target plan, binds target beats to ordered `source_beat_ids`, and renders the repeated voiceover, shot-line, seam, prompt, and handoff views mechanically.

The source-analysis lane also calls Wujie Higress `doubao-seed-2-0-mini-260215` for structured semantic video understanding. The model call, ASR, and contact sheet run together; measured rhythm remains a separate concurrent lane. Provider failure stops the stage. Source cache identity includes the exact video-understanding config and tool hashes, so changing the model or integration invalidates old cache entries.

## Budget

| Work | Target |
|---|---:|
| Source blueprint, including checker | 8 minutes |
| Pre-Seedance director pack, including checker and deterministic QC | 10 minutes |
| Runner and writeback reserve | 2 minutes |
| Total non-image time | 20 minutes |

## Delivery Modes

- `web`: build the browser upload package and its QC only.
- `api`: build prepared request JSON and its QC only.
- `both`: build both only when explicitly requested.

Stop-before-generation intake defaults to `web`; direct final-video intake defaults to `api`. This avoids creating and validating an output with no consumer.

## Reuse Rules

- Source video facts are cached by source hash, exact video-understanding config, tool hashes, and preparation parameters. Product-specific interpretation is never cached.
- Heavy image QC is reused only while active image hashes and role mappings remain unchanged.
- A changed image, manifest, role mapping, or user-reported defect invalidates reuse.
- Independent checker review, product-profile boundaries, speaker-mode preservation, audio duration, and the paid-generation cost gate remain mandatory.

## Measurement

Runner decisions start a stage attempt; gate results record `duration_seconds`. Generate the report with:

```bash
python3 tools/timing_report.py --root . --job <job-id> --fail-on-budget --out output/<job-id>/checks/timing_report.md
```

The report marks the non-image Pre-Seedance budget as `PASS` or `OVER` using `rules/PERFORMANCE_BUDGET.json`.
