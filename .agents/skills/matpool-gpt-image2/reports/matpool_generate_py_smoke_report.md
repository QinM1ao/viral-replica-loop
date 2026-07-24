# Matpool Generate.py Smoke Report

## Result

PASS.

## Route

- Script: `.agents/skills/video-replication/scripts/generate.py`
- Provider: Matpool
- Model: `GPT-Image-2`
- Endpoint behavior: local multi-reference edit through `/images/edits`
- Reference transport: repeated multipart field `image`
- Deprecated GPT Image routes: not used

## Test

Prompt:

```text
output/job-001/gpt_image2_gateway_smoke/wrapper_three_ref_simple_prompt.txt
```

References:

```text
output/job-001/storyboard_source_refs/source_storyboard_part1.jpg
output/job-001/改图小样/refs_optimized/product_front_open_sheet.jpg
output/job-001/改图小样/refs_optimized/female_identity_ref.jpg
```

Output:

```text
output/job-001/gpt_image2_gateway_smoke/matpool_generate_py_retest_20260702/matpool_gpt_image2_three_ref.png
```

File check:

```text
PNG image data, 1024 x 1536, 8-bit/color RGB, non-interlaced
```

## Notes

The API key was supplied only through the process environment during the smoke test and was not written to project files.
