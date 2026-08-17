# 局部精修请求合同

## 路由

先读取当前 Job 的生成模型锁。局部精修必须继承模型族、provider 和 fallback policy，不得因为它是短补丁而改用另一版本。

- Seedance 2.5 锁：读取 `../../seedance-25-replica/references/api-route.md`，使用 `taskCode=2509`、`doubao-seedance-2-5-260628`、Active Pixmax 图片/视频素材、当前 Prompt 绑定的源忠实度 QC 和同一 runner。请求构建器不能表达 `reference_video` 时直接 STOP，不回退 Seedance 2.0。
- Seedance 2.0 锁：才允许使用该 Job 已验证的 2.0 局部精修路线，并记录选择证据。

真人图和含真人的场景图先上传并激活为素材库 `asset://...`；深度视频也先激活为视频素材。

## 内容顺序

无产品：

```json
[
  {"type": "text", "text": "<prompt>"},
  {
    "type": "image_url",
    "image_url": {"url": "asset://<person_asset>"},
    "role": "reference_image"
  },
  {
    "type": "image_url",
    "image_url": {"url": "asset://<scene_asset>"},
    "role": "reference_image"
  },
  {
    "type": "video_url",
    "video_url": {"url": "asset://<depth_video_asset>"},
    "role": "reference_video"
  }
]
```

有产品时，把产品放在场景图之后、深度视频之前：

```json
{
  "type": "image_url",
  "image_url": {"url": "asset://<product_asset>"},
  "role": "reference_image"
}
```

有声重做时，在深度视频之后加入：

```json
{
  "type": "audio_url",
  "audio_url": {"url": "<当前修复区间对应的 Part 声音参考 URL>"},
  "role": "reference_audio"
}
```

声音参考默认从已通过 Part 的 reference audio 按当前修复区间准确裁取，不得改用原视频音频。没有已通过 Part 的独立短实验可使用原视频同区间原声，并在证据中记录该分支。提示词逐字恢复该区间的最终口播、声音模式和音效。

`role` 必须与 `image_url` / `video_url` 同级。三张图片都使用 `reference_image`，深度视频使用 `reference_video`；本流程不使用 `first_frame`。

## 视频参数

```json
{
  "resolution": "720p",
  "ratio": "<与母版一致>",
  "duration": 4,
  "watermark": false,
  "generate_audio": "<原片区间有可听声音时为 true；响度证据确认无可听声音时才为 false>"
}
```

`duration` 使用服务允许且能覆盖动作的最短整数值。原片区间有可听声音时必须使用有声请求；只有响度证据确认无可听声音时才使用静音请求。

有声重做时，下载结果必须包含音频流，之后将新生成的音视频作为一个整体贴合并替换母版目标槽位；只修画面时才保留母版原音频。
