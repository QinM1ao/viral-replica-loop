# Visual Analysis

Use this for GPT Image sample, image repair, and image QC stages.

## Checks

- Storyboard layout and shot order remain unchanged.
- One task uses one approved identity anchor unless the brief says otherwise.
- Person looks like the approved model, not the source host.
- Product shape, label, material, and usage follow client assets.
- No invented packaging, blank jars, unrelated boxes, old subtitles, or old props.
- Skincare/clay-mask products must not inherit old gray mud, tube applicators, watery paste, or wrong usage action.
- Cross-part skin tone, exposure, wardrobe, and scene must not jump unless the source video does.

## Retry Rule

Change one variable only:

- identity reference
- product reference
- scene prompt
- local panel repair

Keep approved layout and shot order locked.

## PASS Shape

Only promote images into `output/<job-id>/final-images/` after hard checks pass.
