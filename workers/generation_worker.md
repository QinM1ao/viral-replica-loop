# Generation Worker

## Canonical Stage

`generation`

## Purpose

Submit only the explicitly approved paid generation tasks and download the outputs.

## Inputs

- Explicit approval record.
- Passed request QC artifact.
- Request JSON files.
- Cost approval gate result.
- `gates/generation_gate.md`.

## Actions

1. Confirm approval scope: job, parts, request files, and task count.
2. Read `.agents/skills/video-replication/references/seedance-taskcode-request-contract.md`.
   Before any Pixmax asset creation, pass every public image URL together with its exact local upload source through `tools/pixmax_asset_library.py --source-files ...`. The helper must reject unreadable or non-standard image geometry before its first network asset call. For an unusually narrow/tall source, first create a non-distorted 9:16, 2:3, 3:4, 4:5, or 1:1 transport crop/canvas that keeps the reference's required product/identity evidence; record the original and transport paths. Do not discover image-ratio problems from a provider 400 response.
3. Build an explicit per-Part plan with `tools/generation_fanout.py plan --attempt 1 --approval-record <job-local-record>`, binding the approval record hash and its parsed `PASS` claims: exact job, `current_job` scope, task count, Parts, and request paths. The approved task count must equal the Part count. The approval parser accepts the `COST_POLICY.md` fields `Request files` and `Number of Seedance tasks`; when `Result` is absent, only an explicit `approved`/`allowed` status may derive `PASS`.
4. Before creating a paid reservation, run `tools/generation_fanout.py preflight`. It runs every Part with `tools/seedance_taskcode_runner.py --preflight-only` in parallel and requires request-bound `request_contract.json=PASS` plus `reference_audio_preflight.json=PASS`. If any free preflight fails, create no reservation and do not call `task_create`; fix the prepared request and rebuild the plan.
5. After every preflight passes, persist the canonical `generation/fanout/reservation.json` with `tools/generation_fanout.py reserve --attempt 1`. The reservation binds job, Part, request SHA-256, attempt, and parsed approval claims before any provider call; a caller-selected reservation path is forbidden.
6. Run the reserved Parts with `tools/generation_fanout.py run`. It revalidates the hash-bound PASS preflight, atomically marks every reserved attempt spent, then dispatches the sealed Stage Execution packets. The exact paid argv already contains `--require-existing-preflight` before sealing; it is never appended at runtime. Stage Execution enforces each Part's declared write root and fails/restores out-of-set writes. Once marked spent, the attempt remains spent even if the provider fails, violates its write set, or the coordinator crashes.
7. Never retry automatically from the fanout runner. One failed Part may receive the sole targeted retry only through a new job-local `targeted_retry` approval record, a new request path and hash, and `tools/generation_fanout.py plan --attempt 2 --generation-intent failed_part_retry`. This lane binds exactly one Part whose Attempt 1 reservation is already `spent=true` and `status=FAIL`.
8. If the user explicitly approves re-drawing one already successful Part for quality, use a new job-local `targeted_retry` approval record and `tools/generation_fanout.py plan --attempt 2 --generation-intent quality_retake`. This lane binds exactly one current `generation/selected_outputs.json` Part, the complete selected-manifest hash, and the current `final/final_video.mp4` hash. It records terminal-job repair progress only in `generation/quality_retake_state.json` and must not edit global `STATE.md` or `RUNNER_STATE.json`. The old selected Part and existing final remain active if preflight or generation fails. Replace only the target after the new completion is `PASS`; 旧的已选 Part 在成功合并前不得删除、覆盖或失效。
9. Both Attempt 2 lanes use isolated `generation/fanout/attempt_2/` artifacts and canonical `generation/fanout/reservation_attempt_2.json`. No Attempt 3 or second targeted retry exists.
10. After every current-job Part has a PASS completion, run `tools/generation_fanout.py merge` once. Failed-Part retry rebuilds the set from Attempt 1 PASS completions. Quality retake rebuilds it from the hash-bound current selected manifest. Both replace only the targeted Part and revalidate current paths, hashes, and durations. Only the coordinator may write `generation/selected_outputs.json`, `generation_log.md`, cost state, gate state, or loop state.
11. Write `generation/selected_outputs.json` with schema version 1 and exactly one `part_id`, absolute path, current SHA-256, and measured `duration_seconds` entry for every selected downloaded Part.
12. Record task keys, output paths, failures, and spent generation count.

Do not branch on subtitle tracks here. Seedance returns flattened video pixels with optional audio, never a separate subtitle track. Accidental visible captions are checked once on the single locally finished master in the next conditional stage.

## Outputs

Write under `output/<job-id>/generation/`:

- submitted request copies
- provider responses
- task keys
- downloaded part videos
- `generation_log.md`
- `selected_outputs.json`
- per-Part `request_contract.json`
- per-Part `reference_audio_preflight.json`
- `generation/fanout/preflight_report.json`
- `generation/fanout/reservation.json`
- optional single-Part failed retry or quality-retake evidence under `generation/fanout/attempt_2/`
- optional `generation/fanout/reservation_attempt_2.json`
- optional terminal-job `generation/quality_retake_state.json`

## Gate

Run:

`gates/generation_gate.md`

## PASS Next Status

`finishing`

## FAIL Retry Variables

Choose exactly one:

- `provider_retry`
- `request_body`
- `reference_url`
- `audio_input`

## Stop Conditions

- Another paid retry beyond the one explicit targeted Attempt 2 would be required.
- Provider failure reason is unclear after one exact retry.
