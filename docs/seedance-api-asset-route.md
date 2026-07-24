# Seedance API Asset Route

Use this when a job should run through Seedance `taskCode=2509` instead of manual web upload.

## Rule

Do not submit the web-side placeholder refs, such as:

```text
asset://Part1_上传素材/01_图片1_Part1分镜节奏.png
```

For API generation, image refs must be public `http(s)` URLs or activated Pixmax material-library refs:

```text
asset://asset-20260703105311-8bkqr
```

For real people and mixed multi-image jobs, the stable route is:

```text
local image -> public https URL -> Pixmax Active asset -> asset://asset-... -> taskCode=2509
```

Audio stays a public `https://...mp3` URL and must be `<=15.00s`.

## Create Pixmax Assets

First upload each image to a public URL using the client's own storage/CDN. Then create Active Pixmax assets:

```bash
export GATEWAY_API_KEY="..."

python3 tools/pixmax_asset_library.py \
  --urls \
    "https://cdn.example.com/part1_storyboard.png" \
    "https://cdn.example.com/product_front.png" \
    "https://cdn.example.com/product_open.png" \
    "https://cdn.example.com/identity_ref.png" \
    "https://cdn.example.com/afterwash_face.png" \
  --roles \
    part1_storyboard \
    product_front \
    product_open_mud \
    identity_ref \
    afterwash_face \
  --source-files \
    "output/<job-id>/AI改好分镜图/Part1最终分镜图.png" \
    "output/<job-id>/generation/upload_transport/product_front.jpg" \
    "output/<job-id>/generation/upload_transport/product_open.jpg" \
    "output/<job-id>/visual-assets/identity_ref.png" \
    "output/<job-id>/visual-assets/afterwash_face.png" \
  --out-json output/<job-id>/seedance/requests/part1_pixmax_assets.json
```

The output JSON contains the usable `asset_ref` values. Use those values in the request body as separate image content objects:

```json
{"type":"image_url","image_url":{"url":"asset://asset-..."},"role":"reference_image"}
```

Keep `role` outside `image_url`.

`--source-files` is the upload-time geometry gate and must point to the exact local files behind the URLs. It runs before `CreateAssetGroup`/`CreateAsset`. Unreadable files and uncommon narrow/tall canvases fail locally, so a provider 400 is not used as an aspect-ratio probe. If the original is an extreme product strip, prepare a non-distorted standard-ratio transport crop that keeps the required package, label, or opening detail, then upload and pass that transport file here. URL-only use requires the explicit `--allow-unverified-remote-geometry` escape hatch and is reserved for assets whose local originals are genuinely unavailable.

## Submit TaskCode Request

After replacing all image URLs with Active `asset://asset-...` refs and keeping audio as public `https://...mp3`, run:

```bash
python3 tools/request_body_qc.py \
  --requests output/<job-id>/seedance/requests/part1_request_prepared.json \
  --prompt-files output/<job-id>/seedance/seedance_part1_prompt.txt \
  --model-route-config rules/SEEDANCE_MODEL.json \
  --allow-asset-refs \
  --out-json output/<job-id>/seedance/requests/request_qc.json \
  --out-md output/<job-id>/seedance/requests/request_qc.md

python3 tools/seedance_taskcode_runner.py \
  --request output/<job-id>/seedance/requests/part1_request_prepared.json \
  --out-dir output/<job-id>/generation/part1 \
  --output output/<job-id>/generation/videos/part1.mp4 \
  --poll-interval 10 \
  --max-wait 5400
```

If `task_create` returns a task key but `task_info` later says `同步调用三方API失败: 接入HTTP请求异常`, check the image refs first. In previous successful runs, all images were Active `asset://asset-...` refs and audio was a public URL.
