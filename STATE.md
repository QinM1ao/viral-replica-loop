# Loop State

## Goal

Reusable Kongfengchun viral-replica workspace.

This repository is ready for the next Kongfengchun source video task. The queue is intentionally empty so a fresh job can be created from client-local source video, product asset, person/model asset, and audio settings.

## Acceptance

- Kongfengchun product/profile experience stays available under `client-profiles/kongfengchun/`.
- Product rules stay available under `rules/product-profiles/`.
- New tasks are created with `scripts/new-task.py` or by giving Codex the simple intake paths.
- Every round selects one current job.
- Every stage writes artifacts under `output/<job-id>/`.
- Every stage runs its linked gate before advancing.
- Pre-Seedance web handoff stops before paid generation unless explicitly approved.

## Current Round

- Date:
- Current task: none
- Current stage: ready for intake
- This round did: prepared the workspace for Kongfengchun reuse
- Artifacts: none
- Verification: run `./install.sh`, then create a new job
- Next: create a new task from the next Kongfengchun source video
- Needs user confirmation: no

## Attempts

- No active attempts in this handoff workspace.
- Reference-only Kongfengchun artifacts live under `examples/kongfengchun-reference-job-008/` when included.

## Stop Rules

- Stop when there are no runnable jobs.
- Stop when source video, product assets, or person assets are missing.
- Stop before paid or batch Seedance generation unless explicitly approved.
- Stop after repeated failure or no effective progress.
