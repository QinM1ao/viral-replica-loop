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

For a Canonical Plugin Job, read the absolute `contract_root` and `state_root` from the bound execution context and the current row's absolute `output_dir` from its bound `jobs.csv`. Bind them as `ENGINE_ROOT`, `STATE_ROOT`, and `JOB_OUTPUT`; do not derive any of them from cwd and do not create compatibility symlinks. Legacy repository Jobs may bind `ENGINE_ROOT` and `STATE_ROOT` to the repository root and `JOB_OUTPUT` to `output/<job-id>`.

```bash
ENGINE_ROOT="<execution-context contract_root>"
STATE_ROOT="<execution-context state_root>"
JOB_OUTPUT="<jobs.csv output_dir>"

python3 "$ENGINE_ROOT/tools/prepare_source_blueprint.py" \
  --video "<source-video-path>" \
  --output-dir "$JOB_OUTPUT" \
  --target-duration "<jobs.csv target_duration>"
```

This command is the preparation checkpoint, not the Stage Run completion. Do not return a
user-facing completion, ask for confirmation, or wait for another runner decision after it
returns `PASS`. Continue the same `source_blueprint` run through the work below and record
completion only through the existing Source Blueprint Gate. Do not call image generation,
`image_batch_fanout.py`, Seedance, or any other video-generation route during this stage.

The command runs story analysis, Part storyboard preparation, source rhythm, and local face evidence concurrently on a cache miss. Inside story analysis, the full-video 2fps call, opening 0–3s 5fps rapid-hook call, ElevenLabs Scribe v1, and contact sheet also run concurrently. ASR emits raw text, word timestamps, speaker turns, sentence segments, and tagged audio events. The full call emits `people_mode`, `visible_roles`, and `expression_and_gaze`; no later expression step may start another semantic-model call.

Read `expression_prompt_profile.json` as the sole downstream expression route. Single-person work may select a small number of native-frame eye-state cues under `$ENGINE_ROOT/rules/EXPRESSION_PROMPT_POLICY.json`; multi-person work uses the existing `expression_and_gaze` values and omits blink instructions.

Read `video_understanding/analysis.json`, `video_understanding/hook_review/analysis.json`, `video_understanding/hook_review/aligned_timeline.json`, and `asr/asr_timeline.json` before authoring beats. Use the full analysis for whole-video semantic coverage. For the opening rapid hook, use the hook review for action order/type and the aligned timeline for measured boundaries and candidate frames. Do not copy the model's coarse timestamps or spoken content into source facts. Raw ElevenLabs ASR controls the auditable evidence text; speaker turns and word timestamps provide audio boundaries. Visible subtitles may correct named words. A high-confidence `semantic_review` may correct an obvious context error when it records `reason` and `confidence>=0.9`, while preserving the raw evidence. Measured cuts and cited pixels control visual timing, action peaks, and physical state changes.

## One-Round Craft Work

Before writing prose, complete `$JOB_OUTPUT/剧情分析/source_rhythm.json`:

- Keep `source_evidence.asr_text` unchanged. Each spoken beat points to an exact `asr_span`; punctuation may change, words may not.
- Any ASR correction must name `from` and `to`. Prefer `evidence_type=visible_text`, where the corrected words appear in a timestamped 5fps subtitle observation with an evidence-frame path. An obvious lexical/context error may use `evidence_type=semantic_review` only with a written reason and `confidence>=0.9`; ambiguous alternatives remain unresolved. Never overwrite `source_evidence.asr_text`.
- Split beats at real hard cuts and meaningful action/speech boundaries. Record exact source time, speaker mode, emphasis words, pause after the beat, action-peak times, visual action, emotion function, rhythm class, replication priority, transition type, and evidence frames. Prefer frames marked `safe_for_beat_evidence=true`; never use a frame on a measured cut as the semantic proof for the shot that ends there.
- For schema v3, record scene, camera, and framing from the cited pixels, then set `visual_action_type` from the pixels rather than the spoken verb. Use `physical_change` only when the picture shows a real state change such as product contacting skin, rinsing, wiping, opening, or pouring. Every `physical_change` must cite three distinct real beat frames under `action_evidence`: before, peak contact/motion, and visible after-state.
- When a beat literally speaks an old product/brand name, record each exact occurrence under `spoken_product_names`; leave it empty otherwise. This field is evidence for replacing only the product-name slot, not permission to rewrite the surrounding line. The independent visual reviewer must confirm from the cited frames that each declared name is actually a product or brand entity; an author-declared substring alone is not evidence.
- Do not treat the 12 evenly sampled storyboard panels as the rhythm truth. They are image/prompt navigation only.
- Run:

```bash
python3 "$ENGINE_ROOT/tools/source_rhythm_qc.py" \
  --source-rhythm "$JOB_OUTPUT/剧情分析/source_rhythm.json" \
  --json-out "$JOB_OUTPUT/checks/source_rhythm_qc.json" \
  --md-out "$JOB_OUTPUT/checks/source_rhythm_qc.md"
```

After rhythm QC passes, submit one batched independent visual review containing every beat and run
`source_rhythm_visual_review_qc.py`. Do not split the initial review into separate contacts,
actions, or story passes. When the report identifies failed beat IDs, preserve ASR, cuts, cached
source evidence, and every passing beat; edit only those failed beat records, request only the
targeted recheck needed for those IDs, merge the replacement review items into the original review
file, and rerun the two rhythm QC commands. Never restart preparation or re-review the whole video
for a local beat failure. This review remains on the critical path because it is the final check
allowed to find a missing key shot. Then rebuild the final canonical Part storyboards immediately
from the checked rhythm record:

```bash
REPORT="$JOB_OUTPUT/checks/source_blueprint_report.json"
python3 "$ENGINE_ROOT/tools/build_part_storyboards.py" \
  --input "$(jq -r '.source_video' "$REPORT")" \
  --output "$JOB_OUTPUT/storyboard_source_refs" \
  --total-frames "$(jq -r '.parameters.total_frames' "$REPORT")" \
  --groups "$(jq -r '.parameters.groups' "$REPORT")" \
  --cols "$(jq -r '.parameters.storyboard_cols' "$REPORT")" \
  --thumb-long-edge "$(jq -r '.parameters.thumb_long_edge' "$REPORT")" \
  --source-rhythm "$JOB_OUTPUT/剧情分析/source_rhythm.json"
```

Do not use the initial uniform storyboard. The final manifest must say `selection_mode=source_rhythm`, contain exactly 12 frames per Part, and cover every required beat exactly once. Once the source-detail work and gate pass, the next `image_batch_qc` stage may prepare image prompts, seal its own storyboard lock, and start image edits. Until then, no task may modify `source_rhythm.json`, its QC/review evidence, or `storyboard_source_refs/`, and no image work may overlap this stage.

Use `$ENGINE_ROOT/tools/source_composition_fanout.py` only for source-detail packets. Every packet reads the same locked rhythm/ASR/frame/cut evidence and writes only its isolated `$JOB_OUTPUT/source-composition/<cache-key>/tasks/<task-id>/` root. Part storyboard rebuilding is not a background task. Do not start another ASR request, edit the rhythm from a packet, or let any packet write canonical storyboards, shared prose, gate files, or loop state.

Write the job-local plan input as `$JOB_OUTPUT/source-composition/source_composition_spec.json`. It must contain `job_id`, absolute `job_output_root=$JOB_OUTPUT`, absolute `output_root`, `source_rhythm_path`, the freshly computed `source_rhythm_sha256`, `source_rhythm_qc_path`, a safe `cache_key`, and the explicit `tasks` DAG. Build and run command-only packets through the real CLI:

```bash
python3 "$ENGINE_ROOT/tools/source_composition_fanout.py" plan \
  --root "$STATE_ROOT" \
  --spec "$JOB_OUTPUT/source-composition/source_composition_spec.json" \
  --out "$JOB_OUTPUT/source-composition/source_composition_plan.json"

python3 "$ENGINE_ROOT/tools/source_composition_fanout.py" run \
  --root "$STATE_ROOT" \
  --plan "$JOB_OUTPUT/source-composition/source_composition_plan.json"
```

The `plan` command rejects a same-path rhythm file changed after the external PASS report, then seals both the current rhythm SHA-256 and QC-report SHA-256. If the sealed plan contains agent packets, the coordinator uses the same public `run_plan(..., agent_dispatcher=...)` entry point so the approved sub-agent host can dispatch them; the command-only CLI intentionally has no implicit agent host.

`run` stops after writing the hash-bound `source_composition_bundle.json`; it explicitly records `canonical_merge=NOT_PERFORMED` and `checker_review=NOT_PERFORMED`. After that fan-in, the coordinator verifies the bundle hashes, merges the passed detail outputs once into the canonical paths below, and invokes only the remaining source-detail checker. It must not rerun beat selection or mutate the storyboard lock. The fanout module does not perform or claim either step. A failed dependency becomes `STOP`; it is not silently replaced by another rhythm author.

Write all of these before checker review:

The canonical Part storyboards were already rebuilt and locked before this background lane. Do not rebuild or replace them here.

- `$JOB_OUTPUT/剧情分析/剧情分析.md`: narrative skeleton, complete source lines, speaker modes, target replacement strategy, and product-profile boundary.
- `$JOB_OUTPUT/剧情分析/画面时间线.md`: source time, visual action, line/speaker, story function, and contamination risk.
- `$JOB_OUTPUT/剧情分析/字幕层整理.md`: visible subtitles/overlays and whether they are timing evidence or must be removed.
- `$JOB_OUTPUT/剧情分析/shot_table.md`: a readable downstream view that references `source_rhythm.json` beat ids; it must not replace or contradict the rhythm record.
- `$JOB_OUTPUT/分镜/分镜表与缝点审查.md`: Part assignment, seam candidates, source-order lock, role map, and product-action translations, referencing shot-table row ids.
- `$JOB_OUTPUT/分镜/分镜污染审查.md`: old product/person/text/tool contamination risks and explicit exclusions.

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

- `$JOB_OUTPUT/剧情分析/video_probe.json`
- `$JOB_OUTPUT/剧情分析/contact_sheet.jpg`
- `$JOB_OUTPUT/剧情分析/asr/`
- `$JOB_OUTPUT/剧情分析/story_analysis_materials.md`
- `$JOB_OUTPUT/剧情分析/video_understanding/analysis.json`
- `$JOB_OUTPUT/剧情分析/video_understanding/analysis.md`
- `$JOB_OUTPUT/剧情分析/video_understanding/request_manifest.json`
- `$JOB_OUTPUT/剧情分析/video_understanding/raw_response.json`
- `$JOB_OUTPUT/剧情分析/video_understanding/hook_review/analysis.json`
- `$JOB_OUTPUT/剧情分析/video_understanding/hook_review/request_manifest.json`
- `$JOB_OUTPUT/剧情分析/video_understanding/hook_review/raw_response.json`
- `$JOB_OUTPUT/剧情分析/video_understanding/hook_review/aligned_timeline.json`
- `$JOB_OUTPUT/剧情分析/source_rhythm.json`
- `$JOB_OUTPUT/剧情分析/expression_prompt_profile.json`
- `$JOB_OUTPUT/剧情分析/source_rhythm_evidence/frame_*.jpg`
- `$JOB_OUTPUT/storyboard_source_refs/source_storyboard_partX.jpg`
- `$JOB_OUTPUT/storyboard_source_refs/source_frames_partX/`
- `$JOB_OUTPUT/storyboard_source_refs/source_storyboard_manifest.json`
- `$JOB_OUTPUT/checks/source_blueprint_report.json`
- `$JOB_OUTPUT/checks/source_rhythm_qc.json`
- `$JOB_OUTPUT/checks/source_rhythm_qc.md`
- `$JOB_OUTPUT/source-composition/source_composition_plan.json`
- `$JOB_OUTPUT/source-composition/<cache-key>/source_composition_bundle.json`
- `$JOB_OUTPUT/checks/source_rhythm_visual_review.json` (written by the independent checker for every source beat)
- `$JOB_OUTPUT/checks/source_rhythm_visual_review_qc.json`
- `$JOB_OUTPUT/checks/source_rhythm_visual_review_qc.md`

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
- Source rhythm beats are empty, source words are not traceable to raw ASR spans, a correction lacks visible-text evidence or a recorded high-confidence semantic-review rationale, a claimed hard cut is not detected, a physical change lacks before/peak/after evidence, or `source_rhythm_qc.json` fails.
- The final storyboard manifest is still `uniform`, misses a required beat, duplicates a cross-Part beat, or does not select the action peak.
- Any required story, speaker-mode, role-map, action-translation, or storyboard audit artifact is incomplete.
