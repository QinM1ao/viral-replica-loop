# Seedance taskCode Request Contract

Use this branch whenever a Part is prepared for API submission through the Wujie `taskCode` route.

The executable single source of truth is `tools/seedance_request_contract.py`. Builders, request QC, and the real submission runner must import it instead of recreating the wire shape.

## Steps

1. Build the request with `build_taskcode_request(...)`. Completion: `inspect_taskcode_request(...)` returns `PASS`, with JSON-string `body.param`, `acquireResourceTimeoutSeconds=60`, an integer 4–15 second provider duration, matching task codes, and in-range image/audio references.
2. Keep prepared and submitted states distinct. A prepared pack may use `asset://UPLOAD_...` placeholders only while both `prepared_only=true` and `do_not_submit=true`; the submitted copy has both flags false or absent. Every submitted image and reference video must be an `asset://asset-...` Pixmax asset already polled to `Status=Active`; direct HTTPS visual URLs are forbidden. Preserve the Active asset manifest and require its exact visual ref set to match the request.
3. Export the approved reference-audio master to MP3 without changing its content or timing, upload that MP3 to a public HTTP(S) URL, and submit it as `reference_audio`. WAV and `asset://` audio refs are forbidden. Completion: `inspect_taskcode_request(..., for_submission=True, require_active_visual_assets=True)` returns `PASS`.
4. Put the binding manifest beside the request as `partX_asset_binding.json`, unless an explicit `--active-asset-manifest` is supplied. Submit only through `tools/seedance_taskcode_runner.py`. It writes `request_contract.json` and `active_visual_asset_preflight.json` before any provider call, then downloads and decodes every reference audio into `reference_audio_preflight.json`. Completion: all three reports are `PASS` before `task_create` is called.

Image and audio references have independent namespaces. Five images plus `@音频1` means `@图片1`–`@图片5` and `@音频1`; audio does not consume an image index. The contract accepts the actual number of image items instead of requiring an arbitrary fixed count.

If the wire contract or audio preflight fails, correct the local request or upload and rerun the free preflight. No provider task was created, so no paid retry was consumed and no new retry approval is required.
