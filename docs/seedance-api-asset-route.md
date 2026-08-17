# Seedance 2.0 API verified asset route

Use this route for ShotLoom Seedance 2.0 jobs submitted through Wujie `taskCode=2509`.
This document covers transport reliability only; output quality is a separate concern.

## Non-negotiable input contract

- Every reference image and every reference video must first become a Pixmax asset, must be polled
  until `Status=Active`, and must be submitted as `asset://asset-...`.
- Never submit a direct HTTPS image or video URL. HTTPS is only the temporary source URL used to
  create the Pixmax asset.
- Reference audio is the exception: export MP3 from the exact approved narration master without
  changing content or timing, upload it to a public HTTP(S) URL, and submit that `.mp3` URL.
  Do not submit WAV or `asset://` audio.
- Keep an asset manifest that records every submitted visual ref and `Status=Active`. The request's
  complete image/video ref set must exactly match that manifest.
- If any of these checks fails, stop in free preflight. Do not call `task_create`.

The verified conversion path is:

```text
local image/video -> public staging URL -> Pixmax asset -> poll Status=Active
                  -> asset://asset-... -> Seedance content[]

approved audio master -> MP3 export -> public https://...mp3 -> Seedance content[]
```

Web handoff placeholders such as `asset://Part1_上传素材/...` and prepared placeholders such as
`asset://UPLOAD_...` are not provider-ready assets.

## Create and verify Pixmax assets

Upload every local visual input to a public staging URL, then run the asset-library helper for both
images and videos. Keep its output JSON as provider evidence.

```bash
python3 tools/pixmax_asset_library.py \
  --urls \
    "https://cdn.example.com/person.png" \
    "https://cdn.example.com/product.png" \
    "https://cdn.example.com/reference.mp4" \
  --roles identity product reference_video \
  --source-files \
    "jobs/<job-id>/inputs/person.png" \
    "jobs/<job-id>/inputs/product.png" \
    "jobs/<job-id>/inputs/reference.mp4" \
  --asset-types Image Image Video \
  --out-json jobs/<job-id>/work/seedance/assets/part1_all_reference_assets.json
```

Do not continue until the manifest reports `overall=PASS` and every item reports
`status=Active`. Copy only each item's `asset_ref` into the request.

## Provider content shape

`role` is a sibling of the URL object, not a field inside it:

```json
[
  {"type":"text","text":"..."},
  {"type":"image_url","image_url":{"url":"asset://asset-image-1"},"role":"reference_image"},
  {"type":"video_url","video_url":{"url":"asset://asset-video-1"},"role":"reference_video"},
  {"type":"audio_url","audio_url":{"url":"https://cdn.example.com/reference.mp3"},"role":"reference_audio"}
]
```

The API binds media by `content[]` order, modality, and role. `@图片1`, `图片1`, `Image 1`, and
similar wording are prompt text, not wire-level asset binding. Do not make `@` syntax a transport
precondition.

## Free preflight gate

Before reservation or paid submission, require all of the following:

| Check | Required result |
|---|---|
| Request URL | Wujie `task_create` URL |
| `taskCode` | `2509` |
| Model | ordinary 2.0 endpoint from current engine rules |
| `body.param` | JSON string, not nested object |
| Timeout | `acquireResourceTimeoutSeconds=60` |
| Duration | integer, 4–15 seconds |
| All image/video URLs | `asset://asset-...` only |
| Visual asset manifest | exact ref-set match; every status `Active` |
| Reference audio | public HTTP(S) URL whose path ends in `.mp3` |
| Downloaded audio probe | decodable audio, duration `<=15.00s` |
| Roles | `reference_image`, `reference_video`, `reference_audio` beside URL object |

The plugin-owned submission path is:

```text
generation_fanout.py -> seedance_taskcode_runner.py -> task_create -> task_info polling
```

Do not invoke the provider runner directly. The runner must persist the request contract and audio
preflight before any paid call.

## Task lifecycle

After `task_create`, immediately persist `create_response.json` and `task_key.txt`. Poll that exact
task key and preserve polling history. A local timeout or lost terminal output is not permission to
create a second paid task. Re-submit only after the old task is conclusively failed and the retry is
properly approved.

On success, download the video and run `ffprobe`. This confirms delivery only; visual and creative
quality review is intentionally outside this API fast-path contract.

## Known failure pattern

The failed request mixed one Active asset with direct HTTPS product images, included a reference
video on the same mixed route, and sent WAV audio. `task_create` returned a task key, but later
provider queries failed. The verified successful request used Active Pixmax `asset://asset-...`
refs for every image and the reference video, plus a public MP3 exported from the same narration
master. Treat that exact transport combination as the default until a different route is separately
verified.
