# Kongfengchun Reference Job 008

This is a reference-only snapshot of a passed Kongfengchun cleaning mud-mask Pre-Seedance handoff.

It is intentionally not queued in root `jobs.csv`. New client runs should create a fresh job with `scripts/new-task.py` and write new artifacts under `output/<new-job-id>/`.

Use this example to inspect the expected handoff shape:

- `output/job-008/seedance_web_final/` - active web-side upload package
- `output/job-008/final-images/` - approved storyboard reference images
- `output/job-008/visual-assets/approved_visual_manifest.json` - visual binding manifest
- `output/job-008/checks/pre_seedance_pack_*.md` - final Pre-Seedance gate and QC evidence
- `output/job-008/prompt_validation_source_speaker_20260706/` - strict prompt evidence proving source speaker modes are preserved

The active Kongfengchun rules still live in:

- `client-profiles/kongfengchun/`
- `rules/product-profiles/`
- `docs/kongfengchun-validated-workflow.md`
- `docs/seedance-20-prompt-standard.md`
