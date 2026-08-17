# Seedance 2.5 已验证调用链

固定模型与任务路由：

- `model=doubao-seedance-2-5-260628`
- `taskCode=2509`
- 视觉素材使用 Active Pixmax `asset://asset-...`
- 可选音色参考使用公网 `.mp3`
- content 顺序为提示词、全部图片、可选深度视频、可选音频
- 一份批准请求只允许一次 `task_create`

## 请求分支

### `generated_voiceover`

- `generate_audio=true`
- 可选上传一个干净音色 MP3；Prompt 中每个语义口播块只出现一次
- 生成后运行 ASR，逐字核对完整目标口播与结尾

### `original_master_postmix`

- `generate_audio=false`
- provider 请求不包含原口播音频，也不包含任何音频引用
- 视觉验收后保留 raw output，用批准的原音频母版替换音轨并验证母版绑定

## 可选深度

`depth_reference.enabled=false` 是默认值，请求只包含图片。启用时只增加一个 Active Pixmax Video，并保持图片在前、视频在后；该视频职责只限镜头。

## 构建请求

```bash
python3 tools/seedance25_request_builder.py \
  --prompt "<unit>/00_Seedance2.5_提示词.txt" \
  --pixmax-assets "<unit>/pixmax_assets.json" \
  --source-fidelity-qc "<unit>/source_fidelity_qc.json" \
  --audio-mode "<generated_voiceover|original_master_postmix>" \
  --duration "<4到30的整数秒>" \
  --ratio 9:16 \
  --resolution 720p \
  --out-request "<unit>/request.json" \
  --out-manifest "<unit>/active_asset_manifest.json" \
  --out-qc "<unit>/request_qc.json"
```

`generated_voiceover` 使用干净音色样本时追加 `--audio-url "<public.mp3>"`。`original_master_postmix` 不传该参数。

## 无扣费预检

```bash
python3 tools/seedance_taskcode_runner.py \
  --request "<unit>/request.json" \
  --active-asset-manifest "<unit>/active_asset_manifest.json" \
  --source-fidelity-qc "<unit>/source_fidelity_qc.json" \
  --out-dir "<unit>/preflight" \
  --output "<unit>/raw_output.mp4" \
  --preflight-only
```

完成条件：source fidelity、请求格式、Active 素材与可选音色 MP3 全部 `PASS`，并且没有调用 `task_create`。

## 原音频直贴

仅用于 `original_master_postmix`，且在视觉验收后执行：

```bash
ffmpeg -i "<raw_output.mp4>" -i "<approved_original_audio>" \
  -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -movflags +faststart \
  "<final_with_original_audio.mp4>"
```

执行前确认 raw video 时长足以容纳完整母版；执行后用 `ffprobe` 验证视频和音频流，并把母版 SHA-256、交付音频解码 SHA-256 与输出路径写入 finishing QC。原母版完整结尾缺失时收尾失败，不截短母版交付。

## 付费生成

只有当前 Job 已有明确费用批准与预约时，才通过 `generation_fanout.py` 调用同一个 runner。保留请求、Task Key、轮询历史、raw output、finishing 产物和全部 QC；失败或结果不明时不自动重提。
