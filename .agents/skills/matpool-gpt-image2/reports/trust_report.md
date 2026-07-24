# Matpool GPT-Image-2 Trust Report

## Status

PASS for route consolidation.

## Contract

- Only Matpool GPT-Image-2 is allowed for project GPT Image work.
- Local references are submitted as repeated multipart `image` fields.
- Deprecated routes are removed from the project executable path and skill docs.
- API keys are read from environment/private local config and must not be committed.

## Required Smoke

Run a real edit with at least three local references:

```bash
MATPOOL_API_KEY=... python3 .agents/skills/video-replication/scripts/generate.py \
  --prompt-file output/job-001/gpt_image2_gateway_smoke/wrapper_three_ref_simple_prompt.txt \
  -i output/job-001/storyboard_source_refs/source_storyboard_part1.jpg \
  -i output/job-001/改图小样/refs_optimized/product_front_open_sheet.jpg \
  -i output/job-001/改图小样/refs_optimized/female_identity_ref.jpg \
  --quality low \
  --size 1024x1536 \
  --file output/job-001/gpt_image2_gateway_smoke/matpool_generate_py_retest/matpool.png
```
