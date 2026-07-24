# Viral Replica Brief

## Client

- Client name: 孔凤春
- Project name: reusable viral-replica loop workspace
- Date:

## Source Videos

- Source video folder: fill with the client's local path for the next task
- Number of videos:
- Target duration: 30s by default
- Replication level: close

## Product

- Product name: 孔凤春清洁泥膜 or another Kongfengchun product
- Product asset folder: fill with the client's local product image folder
- Product constraints: see `PRODUCT_CONSTRAINTS.md`
- Product profile: generated per job under `output/<job-id>/product_profile.json`

## Person / Host

- Person asset folder: fill with the client's local model/person image folder
- Identity rule: infer source host gender during story analysis, then choose one matching model identity from the person assets unless the user specifies otherwise

## Voice / Audio

- Voice source: extract_from_original by default
- Keep original subtitles as timing reference: yes
- Generate audio in Seedance: yes unless the job is explicitly silent
- BGM: no by default for multi-part videos

## Notes

- For Kongfengchun cleaning mud-mask jobs, keep the current validated rules: white/milky-white thick mud, open jar, fingertip pickup, fingertip face application, readable current-product label, no old tube/stick/brush/arm-swatch action, no yellow/gray/watery mud, no source subtitles or old product contamination.
- For Kongfengchun toner or other products, load only the product profile declared by `output/<job-id>/product_profile.json`; do not apply mud-mask rules to toner or unknown products.
- Default stop point for web-side handoff: stop at `seedance_inputs_prepared` before paid Seedance generation.
