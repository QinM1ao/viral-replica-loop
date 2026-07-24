# Trust Report

Skill: `viral-replica`

Status: production package. This report scopes the loop adapter and does not replace provider or organization-level security review.

## Permission Surface

- Reads local loop control files: `BRIEF.md`, `STATE.md`, `jobs.csv`, `LOOP.md`, `rules/STAGE_RULES.json`.
- Writes loop state only through existing runner and gate-recording commands.
- Reads and writes job artifacts under `output/<job-id>/`.
- Does not own provider credentials.
- Does not submit paid Seedance generation unless the cost gate and explicit approval scope are satisfied.

## Script Surface

- Primary runner: `tools/run_next_loop_round.py`.
- Checker validation: `tools/checker_review_qc.py`.
- Visual and request gates: `tools/visual_asset_manifest_qc.py`, `tools/codex_imagegen_contract_qc.py`, `tools/storyboard_geometry_qc.py`, `tools/cross_part_continuity_qc.py`, `tools/skincare_progression_qc.py`, `tools/audio_duration_qc.py`, `tools/request_body_qc.py`.

## Secrets

- No secret values should be printed, copied into prompts, or stored in final handoff directories.
- Secret scanning is `missing evidence`.

## Network And Cost

- The skill wrapper may reach provider-backed generation only through explicit generation approval.
- Web-side handoff stops before paid/API generation by default.

## Production Scope

- Production readiness here means routeable, reusable, file-backed, and structurally checked inside this repository.
- Governed release evidence such as runtime permission probes, package checksum, install ledger, and blind human review can be added later if this skill is promoted beyond local production use.
