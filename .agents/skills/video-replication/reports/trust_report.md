# Trust Report

Skill: `video-replication`

Status: governed package draft. This report scopes craft risks and does not claim full release readiness.

## Permission Surface

- Reads source videos, extracted frames, product assets, person assets, audio assets, and job artifacts.
- May call image-generation or video-generation providers when used outside the loop.
- Inside `viral-replica-loop`, queue selection, state writeback, and paid-generation approval belong to `viral-replica`.

## Script Surface

- Local helper: `.agents/skills/video-replication/scripts/generate.py`.
- Runtime QC scripts live at the repo root under `tools/` and are invoked by the loop wrapper.

## Secrets

- Provider key names and local env loading instructions exist in `SKILL.md`.
- Secret values must never be printed, copied into prompts, or saved in generated reports.
- Secret scan is `missing evidence`.

## Network And Cost

- Image and Seedance generation can have provider cost.
- Inside this loop, generation is blocked by the cost gate until explicit approval.
- The `pre_seedance_pack` replacement stops at `seedance_inputs_prepared`; it does not submit paid Seedance generation.
- Final generated-video ASR is no longer a routine delivery action; reference-audio ASR remains required when debugging or validating sound-enabled multi-Part audio boundaries.

## Release Gaps

- Runtime permission probes are `missing evidence`.
- One provider-backed output case now exists at `reports/actual_validation_20260716_kongfengchun_part2.md`; broader provider-backed trigger/category coverage is still `missing evidence`.
- The deterministic Shot-label fast path has real `job-012` artifact evidence and a 193-test regression run at `reports/shot_label_fast_path_validation_20260720.md`.
- Blind output review decisions are `missing evidence`.
