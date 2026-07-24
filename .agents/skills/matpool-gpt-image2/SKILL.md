---
name: matpool-gpt-image2
description: Use when a viral-replica-loop task needs GPT Image 2 image generation or image editing from local reference images. This is the only supported GPT Image route in this project: Matpool GPT-Image-2 via `.agents/skills/video-replication/scripts/generate.py`.
---

# Matpool GPT-Image-2

## Purpose

Run GPT Image 2 through this repository's validated Matpool route while keeping the existing video-replication craft, prompts, QC, and stage gates.

This skill is only about the GPT Image invocation method.

## Hard Rule

Use only:

```bash
python3 .agents/skills/video-replication/scripts/generate.py
```

Do not try any deprecated GPT Image route or gateway probe. Those routes are removed for this project and should not be retried as fallbacks.

## Configuration

Credentials are read in this order:

- `MATPOOL_API_KEY`
- optional `MATPOOL_BASE_URL`, default `https://token.matpool.com/v1`
- optional `MATPOOL_IMAGE_MODEL`, default `GPT-Image-2`
- `.agents/skills/video-replication/config/default.json` only for non-secret defaults

Do not write API keys to repo files, prompts, reports, logs, or final responses.

## Multi-Reference Edit

Use local reference images directly. Repeat `-i` in role order; the script submits every file as multipart field name `image`.

```bash
python3 .agents/skills/video-replication/scripts/generate.py \
  --prompt-file "<prompt.txt>" \
  -i "<source-storyboard.jpg>" \
  -i "<product-front-or-sheet.jpg>" \
  -i "<identity-ref.jpg>" \
  --quality medium \
  --size "1024x1536" \
  --file "<out>/matpool_gpt_image2_edit.png"
```

For viral-replica storyboard edits, the default reference order is:

1. source storyboard
2. product front / product sheet / open product material
3. identity or model reference
4. after-wash face reference, only when needed

## Contract

Every promoted image stage still needs this project's existing evidence files and QC:

- `codex_imagegen_contract.json`
- `tools/codex_imagegen_contract_qc.py`
- `tools/visual_asset_manifest_qc.py`
- stage-specific geometry, continuity, and skincare checks when required

Use these route fields:

```json
{
  "image_route": "matpool_gpt_image_2_edit",
  "api_effect_baseline": {
    "source": "matpool_gpt_image_2_edit",
    "preserve_api_route": true
  },
  "matpool_uses_real_image_inputs": true
}
```

## Failure Handling

If Matpool fails:

- verify `MATPOOL_API_KEY`
- verify every `-i` path exists and is a real image
- reduce refs by combining product images into one sheet
- re-encode suspicious images to JPEG/PNG without metadata
- retry quality `medium -> low`; use `high` only when a specific image quality problem justifies the extra time
- use an explicit pixel size such as `1024x1536`

Do not switch to any deprecated GPT Image provider.
