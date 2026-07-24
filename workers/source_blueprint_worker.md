# Source Blueprint Worker

## Layer

`source_blueprint`

## Purpose

Finish source understanding and storyboard planning in one checked round. The script calls Wujie Higress Seed 2.0 Mini for semantic video understanding while preparing source-only factual materials in parallel and caching them; the worker must reconcile the model reading with measured cuts, 5fps evidence frames, raw ASR, and audio energy before writing a checked source-rhythm record, current product/person interpretation, role map, action translations, seam candidates, and storyboard audit.

## Inputs

- Selected source video path from `jobs.csv`.
- Target duration from the same job row.
- Optional mechanical settings: contact-sheet FPS, storyboard columns, and thumbnail long edge.

Do not load product, person, category, SKU, client-profile, or replacement-strategy prose into the cache key or cache payload. Read the current `product_profile.json` after source materials are ready and use it only in current-job analysis files.

## Command

Run from the repository root:

```bash
python3 tools/prepare_source_blueprint.py \
  --video "<source-video-path>" \
  --output-dir "output/<job-id>" \
  --target-duration "<jobs.csv target_duration>"
```

The command runs `tools/prepare_story_analysis.py --run-asr`, `tools/build_part_storyboards.py`, and `tools/prepare_source_rhythm.py` concurrently on a cache miss. Inside the first lane, one full-video 2fps call and one opening 0–3s 5fps rapid-hook call use `doubao-seed-2-0-mini-260215` concurrently with the single Qwen ASR process. The rhythm lane records real scene cuts, 5fps visual evidence, and 250ms audio-energy windows; it does not invent semantic beats.

Read `video_understanding/analysis.json`, `video_understanding/hook_review/analysis.json`, and `video_understanding/hook_review/aligned_timeline.json` before authoring beats. Use the full analysis for whole-video semantic coverage. For the opening rapid hook, use the hook review for action order/type and the aligned timeline for measured boundaries and candidate frames. Do not copy the model's coarse timestamps or spoken content into source facts. Raw Qwen ASR controls exact words; visible subtitles may correct named words; measured cuts and cited pixels control timing, action peaks, and physical state changes. Record and resolve any conflict in the readable analysis.

## One-Round Craft Work

Before writing prose, complete `output/<job-id>/剧情分析/source_rhythm.json`:

- Keep `source_evidence.asr_text` unchanged. Each spoken beat points to an exact `asr_span`; punctuation may change, words may not.
- Any ASR correction must name `from`, `to`, and `evidence_type=visible_text`, and the corrected words must appear in a timestamped 5fps subtitle observation with an evidence-frame path.
- Split beats at real hard cuts and meaningful action/speech boundaries. Record exact source time, speaker mode, emphasis words, pause after the beat, action-peak times, visual action, emotion function, rhythm class, replication priority, transition type, and evidence frames.
- For schema v3, record scene, camera, and framing from the cited pixels, then set `visual_action_type` from the pixels rather than the spoken verb. Use `physical_change` only when the picture shows a real state change such as product contacting skin, rinsing, wiping, opening, or pouring. Every `physical_change` must cite three distinct real beat frames under `action_evidence`: before, peak contact/motion, and visible after-state.
- When a beat literally speaks an old product/brand name, record each exact occurrence under `spoken_product_names`; leave it empty otherwise. This field is evidence for replacing only the product-name slot, not permission to rewrite the surrounding line. The independent visual reviewer must confirm from the cited frames that each declared name is actually a product or brand entity; an author-declared substring alone is not evidence.
- Do not treat the 12 evenly sampled storyboard panels as the rhythm truth. They are image/prompt navigation only.
- Run:

```bash
python3 tools/source_rhythm_qc.py \
  --source-rhythm output/<job-id>/剧情分析/source_rhythm.json \
  --json-out output/<job-id>/checks/source_rhythm_qc.json \
  --md-out output/<job-id>/checks/source_rhythm_qc.md
```

Only after that check passes, lock the current `source_rhythm.json` SHA-256 and use `tools/source_composition_fanout.py` to build one `source_blueprint` Stage Execution plan. The coordinator may dispatch bounded agent packets for `story_view`, `timeline_view`, `shot_view`, and `role_product_seam_audit`, plus command packets for independent Part storyboard rebuilds. Every packet reads the same locked rhythm/ASR/frame/cut evidence and writes only its isolated `output/<job-id>/source-composition/<cache-key>/tasks/<task-id>/` root. Do not start another Qwen ASR, edit the rhythm from a packet, or let any packet write canonical storyboards, shared prose, gate files, or loop state.

Write the job-local plan input as `output/<job-id>/source-composition/source_composition_spec.json`. It must contain `job_id`, `source_rhythm_path`, the freshly computed `source_rhythm_sha256`, `source_rhythm_qc_path`, a safe `cache_key`, and the explicit `tasks` DAG. Build and run command-only packets through the real CLI:

```bash
python3 tools/source_composition_fanout.py plan \
  --root . \
  --spec output/<job-id>/source-composition/source_composition_spec.json \
  --out output/<job-id>/source-composition/source_composition_plan.json

python3 tools/source_composition_fanout.py run \
  --root . \
  --plan output/<job-id>/source-composition/source_composition_plan.json
```

The `plan` command rejects a same-path rhythm file changed after the external PASS report, then seals both the current rhythm SHA-256 and QC-report SHA-256. If the sealed plan contains agent packets, the coordinator uses the same public `run_plan(..., agent_dispatcher=...)` entry point so the approved sub-agent host can dispatch them; the command-only CLI intentionally has no implicit agent host.

`run` stops after writing the hash-bound `source_composition_bundle.json`; it explicitly records `canonical_merge=NOT_PERFORMED` and `checker_review=NOT_PERFORMED`. After that fan-in, the coordinator verifies the bundle hashes, merges the passed outputs once into the canonical paths below, and invokes the independent source checker once. The fanout module does not perform or claim either step. A failed dependency becomes `STOP`; it is not silently replaced by another rhythm author.

Write all of these before checker review:

Rebuild the Part storyboards from the checked rhythm record so every `must_keep` / `mergeable` beat is selected once and action beats use their measured peak instead of uniform sampling:

```bash
REPORT="output/<job-id>/checks/source_blueprint_report.json"
python3 tools/build_part_storyboards.py \
  --input "$(jq -r '.source_video' "$REPORT")" \
  --output "output/<job-id>/storyboard_source_refs" \
  --total-frames "$(jq -r '.parameters.total_frames' "$REPORT")" \
  --groups "$(jq -r '.parameters.groups' "$REPORT")" \
  --cols "$(jq -r '.parameters.storyboard_cols' "$REPORT")" \
  --thumb-long-edge "$(jq -r '.parameters.thumb_long_edge' "$REPORT")" \
  --source-rhythm "output/<job-id>/剧情分析/source_rhythm.json"
```

Do not submit the initial uniform-sampled cache storyboard to the gate. The final manifest must say `selection_mode=source_rhythm`, and every required beat id must appear exactly once under `selected_frames`.

- `output/<job-id>/剧情分析/剧情分析.md`: narrative skeleton, complete source lines, speaker modes, target replacement strategy, and product-profile boundary.
- `output/<job-id>/剧情分析/画面时间线.md`: source time, visual action, line/speaker, story function, and contamination risk.
- `output/<job-id>/剧情分析/字幕层整理.md`: visible subtitles/overlays and whether they are timing evidence or must be removed.
- `output/<job-id>/剧情分析/shot_table.md`: a readable downstream view that references `source_rhythm.json` beat ids; it must not replace or contradict the rhythm record.
- `output/<job-id>/分镜/分镜表与缝点审查.md`: Part assignment, seam candidates, source-order lock, role map, and product-action translations, referencing shot-table row ids.
- `output/<job-id>/分镜/分镜污染审查.md`: old product/person/text/tool contamination risks and explicit exclusions.

The approved identity applies only to the source-defined protagonist/product-host role. Preserve every source speaker mode row by row. Translate source product actions to the loaded product profile before ImageGen.

## Part Math

- `groups = ceil(target_duration_seconds / 15)`
- `total_frames = groups * 12`
- Each group must produce one `source_storyboard_partX.jpg`.

## Cache Contract

- Default cache root: `.cache/source-blueprint/`.
- Cache entry: `.cache/source-blueprint/<cache-key>/`.
- The key uses the source video SHA-256 plus every mechanical parameter that affects output.
- Cache only Seed 2.0 Mini source-understanding response/evidence, probe data, contact sheet, source ASR, source-material index, Part storyboard images, source frame folders, measured rhythm evidence, and the storyboard manifest.
- Never cache `剧情分析.md`, `画面时间线.md`, `字幕层整理.md`, `分镜表与缝点审查.md`, `分镜污染审查.md`, or other target-product interpretation.
- On a hit, restore only cached factual artifacts. Existing product-specific prose in the current job output must remain untouched.

## Outputs

- `output/<job-id>/剧情分析/video_probe.json`
- `output/<job-id>/剧情分析/contact_sheet.jpg`
- `output/<job-id>/剧情分析/asr/`
- `output/<job-id>/剧情分析/story_analysis_materials.md`
- `output/<job-id>/剧情分析/video_understanding/analysis.json`
- `output/<job-id>/剧情分析/video_understanding/analysis.md`
- `output/<job-id>/剧情分析/video_understanding/request_manifest.json`
- `output/<job-id>/剧情分析/video_understanding/raw_response.json`
- `output/<job-id>/剧情分析/video_understanding/hook_review/analysis.json`
- `output/<job-id>/剧情分析/video_understanding/hook_review/request_manifest.json`
- `output/<job-id>/剧情分析/video_understanding/hook_review/raw_response.json`
- `output/<job-id>/剧情分析/video_understanding/hook_review/aligned_timeline.json`
- `output/<job-id>/剧情分析/source_rhythm.json`
- `output/<job-id>/剧情分析/source_rhythm_evidence/frame_*.jpg`
- `output/<job-id>/storyboard_source_refs/source_storyboard_partX.jpg`
- `output/<job-id>/storyboard_source_refs/source_frames_partX/`
- `output/<job-id>/storyboard_source_refs/source_storyboard_manifest.json`
- `output/<job-id>/checks/source_blueprint_report.json`
- `output/<job-id>/checks/source_rhythm_qc.json`
- `output/<job-id>/checks/source_rhythm_qc.md`
- `output/<job-id>/source-composition/source_composition_plan.json`
- `output/<job-id>/source-composition/<cache-key>/source_composition_bundle.json`
- `output/<job-id>/checks/source_rhythm_visual_review.json` (written by the independent checker for every source beat)
- `output/<job-id>/checks/source_rhythm_visual_review_qc.json`
- `output/<job-id>/checks/source_rhythm_visual_review_qc.md`

The JSON report must include `cache_hit`, `source_sha256`, `task_timings`, `artifacts`, and `overall`.

## Gate

Run `gates/source_blueprint_gate.md` against the report, source facts, and current-job craft files. In self-audit mode, run one independent checker for this combined stage.

## Stop Conditions

- Source video is missing or unreadable.
- Any parallel task fails, including either Seed 2.0 Mini provider call.
- The rapid-hook review is missing, uses the wrong mode/FPS/segment, or its measured-cut-aligned timeline is empty.
- Video-understanding provider/model/source hash/request evidence is missing or invalid.
- ASR, contact sheet, probe data, storyboard manifest, or a required Part storyboard is missing.
- Cached product-specific analysis prose is detected.
- Source rhythm beats are empty, source words are not traceable to raw ASR spans, a correction lacks visible-text evidence, a claimed hard cut is not detected, a physical change lacks before/peak/after evidence, or `source_rhythm_qc.json` fails.
- The final storyboard manifest is still `uniform`, misses a required beat, duplicates a cross-Part beat, or does not select the action peak.
- Any required story, speaker-mode, role-map, action-translation, or storyboard audit artifact is incomplete.
