# Fast Default Pipeline Validation

Date: 2026-07-03

Skill: `video-replication`

## Decision

Replace the old default post-image path with a compact `pre_seedance_pack` stage.

Old default:

```text
image_qc_passed -> voiceover -> seam -> seedance_prompt -> audio_boundary_qc -> request_qc -> seedance_inputs_prepared
```

New default:

```text
image_qc_passed -> pre_seedance_pack -> seedance_inputs_prepared
```

The old stages remain as legacy/focused-repair fallbacks.

## Feasibility Evidence

- Runner rule now maps `image_qc_passed` to `canonical_stage=pre_seedance_pack`.
- `workers/pre_seedance_pack_worker.md` defines the combined artifact contract.
- `gates/pre_seedance_pack_gate.md` defines PASS/FAIL/STOP rules without weakening cost approval.
- `tools/run_next_loop_round.py` treats `pre_seedance_pack` as a visual/request stage, requiring checker review QC, visual asset manifest QC, heavy visual QC or valid hash-gated reuse, request QC, and audio duration QC when audio exists.
- `tests/test_runner_enforcement.py` includes a regression test proving `pre_seedance_pack` PASS transitions directly to `seedance_inputs_prepared`.

Verification command:

```bash
python3 -m unittest tests/test_runner_enforcement.py
```

Result:

```text
Ran 9 tests in 0.510s
OK
```

## Speed Evidence

Timing source:

```text
output/fast-pipeline-timing-report-20260703.md
```

For `job-001`, the old post-image downstream path recorded these latest PASS elapsed times:

| Stage | PASS elapsed |
|---|---:|
| voiceover | 1m 31s |
| seam | 41s |
| seedance_prompt | 8m 39s |
| audio_boundary_qc | 2m 15s |
| request_qc | 5m 20s |

Observed downstream reuse/revalidation subtotal: about `18m 26s`, plus multiple runner/checker/gate cycles.

The new default does not make prompt writing or request checks disappear. It removes the default five-stage runner ladder and turns them into one worker/gate package. Expected speed gain comes from:

- one runner decision and one gate record instead of five
- one checker review contract instead of five separate stage reviews
- hash-gated reuse of image-batch heavy visual QC
- no default final generated-video ASR
- no default image sample stop

## Preserved Safety

- Story analysis still precedes prompts and voiceover.
- Image batch still must PASS before the Pre-Seedance pack.
- Cost approval is unchanged; `pre_seedance_pack` stops at `seedance_inputs_prepared`.
- Audio boundary ASR still applies to reference audio for sound-enabled multi-Part jobs.
- Final generated-video ASR is optional only for user-requested script/audio verification or targeted audio defects.
- Old per-stage workers/gates remain available for legacy statuses or focused repairs.

## Archive

Previous default skill and runner contracts were archived before replacement:

```text
.agents/skills/video-replication/archive/20260703-pre-fast-default/
```

Archived files:

- `SKILL.md`
- `interface.yaml`
- `manifest.json`
- `output_cases.json`
- `STAGE_RULES.json`
- `LOOP.md`

## Remaining Evidence Gaps

- No new paid Seedance generation was run for this SkillOps change.
- No provider-backed model eval or blind A/B review was run.
- Speed evidence is based on local runner tests plus historical timing logs, not a fresh full end-to-end video job.
