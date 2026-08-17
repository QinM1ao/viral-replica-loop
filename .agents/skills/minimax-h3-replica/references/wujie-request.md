# Wujie MiniMax H3 Request Contract

Read this only when building, submitting, querying, or recovering a MiniMax H3 request through Wujie.

## Endpoints

```text
POST https://higress-api.wujieai.com/wj-open/v2/open-platform/task/task_create
GET  https://higress-api.wujieai.com/wj-open/v2/open-platform/task/v2/task_info?taskKey=<TASK_KEY>
```

Use `Authorization: Bearer <key>` and `Content-Type: application/json`. Read the configured Wujie credential from the process or the Workspace credential configuration; never write it into Job artifacts.

## Create Body

`param` is a JSON-encoded string inside the outer JSON object:

```json
{
  "taskCode": 2513,
  "acquireResourceTimeoutSeconds": 600,
  "param": "{\"model\":\"MiniMax-H3\",\"content\":[...],\"resolution\":\"2K\",\"duration\":13,\"ratio\":\"9:16\"}"
}
```

Use this `content` order:

```json
[
  {"type":"text","text":"<six-section Ref2VA prompt>"},
  {"type":"video_url","video_url":{"url":"https://.../source-unit.mp4"},"role":"reference_video"},
  {"type":"image_url","image_url":{"url":"https://.../person.png"},"role":"reference_image"},
  {"type":"image_url","image_url":{"url":"https://.../product.png"},"role":"reference_image"},
  {"type":"audio_url","audio_url":{"url":"https://.../approved-master.wav"},"role":"reference_audio"}
]
```

Add only assets used by the prompt. Preserve their order when assigning `<Video N>`, `<Picture N>`, and `<Audio N>`. Keep `role` outside the nested URL object.

## Free Preflight

Before `task_create`:

1. Parse the outer request JSON.
2. Parse `param` as JSON and verify `model=MiniMax-H3`, duration, ratio, resolution, and content order.
3. Confirm every local source exists and has the recorded hash used to create its URL.
4. GET every public URL, require HTTP 200, and decode the returned media.
5. Probe the reference video and audio durations against the unit.
6. Save the exact submitted request body in the unit directory.

A preflight failure creates zero paid tasks.

## Create and Query Semantics

A successful outer response and `task_status=QUEUEING` prove only that Wujie accepted task creation. Save its Task Key immediately.

The query response may wrap the MiniMax result as a JSON string in `data.result`. Parse that string and inspect `task.model` and `task.status`:

- `queued`: keep polling the same key.
- `running`: keep polling the same key.
- `succeeded`: require `task.content.url`, then download immediately while the URL is valid.
- `failed`: preserve the response and stop.
- non-JSON gateway text: preserve it as a gateway result, keep querying the same key for a bounded period, and do not infer another provider from the wording.

Do not describe a task as failed merely because the query layer returned a generic error. Do not create a second paid task while the first key can still be queried, unless the user explicitly authorizes one targeted retry after the first outcome is known.

## Unit Artifacts

Store each attempt independently:

```text
unit-01/
  prompt.txt
  request.json
  preflight.json
  create_response.json
  task_key.txt
  latest_task_info.json
  raw.mp4
  ffprobe.json
  contact_sheet.jpg
  qc.json
```

Never overwrite a prior Task Key or raw output. A retry uses a new sibling attempt directory.

## Cost Boundary

Direct user language such as “使用 MiniMax H3 生成视频” approves every required unit of the current explicit Job once. Prompt writing, packaging, URL checks, and query polling are not paid-generation approval. A failed unit receives no automatic retry; report its Task Key and request one targeted decision.
