# Seed 2.0 Mini 视频理解 / Seedance 2.0 Mini 视频生成辨析与无界 Higress 实测

日期：2026-07-17
范围：只使用火山方舟 / 火山引擎官方文档与官方 API 规格；无界网关部分来自本轮实际 HTTP 路由测试。本轮未提交任何视频生成任务。

## 结论

1. 截图中的 `doubao-seed-2-0-mini-260215` 是 **Doubao Seed 2.0 Mini 多模态理解 / 对话模型**，不是视频生成模型。官方模型列表将它列为支持深度思考、文本生成、多模态理解、工具调用和结构化输出的通用模型。[火山方舟：模型列表](https://www.volcengine.com/docs/82379/1330310)
2. 真正的视频模型名为 **Doubao Seedance 2.0 Mini**，当前官方教程列出的 Model ID 是 `doubao-seedance-2-0-mini-260615`（注意多了 `ance`，版本号也不同）。[火山方舟：Doubao Seedance 2.0 系列教程](https://www.volcengine.com/docs/82379/2291680)
3. 无界 Higress 的实测结果与上述区分一致：`GET /v1/models` 可见 `doubao-seed-2-0-mini-260215`，`POST /v1/chat/completions` 的文本和本地 MP4 视频理解请求均返回 HTTP 200；但 `POST /v1/contents/generations/tasks` 返回 HTTP 404。因此当前项目把它用于 **Seed 2.0 Mini 视频理解**，而不是 Seedance 视频生成。
4. 火山官方的视频理解输入格式是 Chat content 中的 `video_url`；本地文件可用 `data:video/mp4;base64,...`，并可设置 `fps`。本地文件上限 50 MB、请求体上限 64 MB；项目实现见 `tools/video_understanding.py` 与 `docs/video-understanding.md`。[火山方舟：视频理解](https://docs.volcengine.com/docs/82379/1895586?lang=zh)

## 无界网关：已验证的调用方式

截图标明网关 Base URL 为 `https://higress-api.wujieai.com/v1`，提供方协议为 `openai-completions`。本轮实测通过的路径是 OpenAI Chat Completions：

```bash
curl 'https://higress-api.wujieai.com/v1/chat/completions' \
  -H 'Authorization: Bearer <WUJIE_API_KEY>' \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "doubao-seed-2-0-mini-260215",
    "messages": [
      {"role": "user", "content": "只回复 OK"}
    ],
    "stream": false
  }'
```

对应 OpenAI SDK：

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://higress-api.wujieai.com/v1",
    api_key="<WUJIE_API_KEY>",
)

result = client.chat.completions.create(
    model="doubao-seed-2-0-mini-260215",
    messages=[{"role": "user", "content": "只回复 OK"}],
)
print(result.choices[0].message.content)
```

火山方舟原生同时提供 Chat API `POST https://ark.cn-beijing.volces.com/api/v3/chat/completions` 和 Responses API `POST https://ark.cn-beijing.volces.com/api/v3/responses`。官方说明 2025-06-15 及之后的大语言模型默认支持 Responses API，因此 `doubao-seed-2-0-mini-260215` 可按 Responses 协议直连火山方舟。[火山方舟：Responses API 文本生成](https://www.volcengine.com/docs/82379/1958520)、[创建模型响应 API](https://www.volcengine.com/docs/82379/1569618)、[ChatCompletions API](https://api.volcengine.com/api-docs/view?action=ChatCompletions&serviceCode=ark&version=2024-01-01)

> 不要把火山方舟原生的 `/api/v3/contents/generations/tasks` 机械地改成无界的 `/v1/contents/generations/tasks`。该网关实测对后一路径返回 404，说明没有对外暴露这条映射。

## 如果要调真正的 Seedance 2.0 Mini

### 协议与端点

官方视频生成不走 Chat Completions 或 Responses，而是异步 **Video Generation Task API**：

```text
POST https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks
GET  https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks/{task_id}
```

创建成功先返回 `id`；之后轮询查询端点，状态为 `queued` / `running` / `succeeded` / `failed`。成功后在 `content.video_url` 取 MP4 地址。也可传 `callback_url` 接收同样结构的 Webhook。[火山方舟：视频生成教程](https://www.volcengine.com/docs/82379/2298881)、[创建视频生成任务 API](https://api.volcengine.com/api-docs/view?action=CreateContentsGenerationsTasks&serviceCode=ark&version=2024-01-01)、[查询视频生成任务 API](https://api.volcengine.com/api-docs/view?action=GetContentsGenerationsTask&serviceCode=ark&version=2024-01-01)

### 官方当前列出的 Mini 参数

| 字段 | Seedance 2.0 Mini |
|---|---|
| `model` | `doubao-seedance-2-0-mini-260615` |
| `content[].type` | `text`, `image_url`, `video_url`, `audio_url` |
| 参考素材 role | `first_frame`, `last_frame`, `reference_image`, `reference_video`, `reference_audio`（按场景使用） |
| 多模态参考数量 | 图片 0–9，视频 0–3，音频 0–3；不支持“纯音频”或“文本+音频” |
| `generate_audio` | `true` 生成有声视频；官方能力表列出 Mini 支持 |
| `resolution` | `480p` / `720p` |
| `ratio` | `21:9`, `16:9`, `4:3`, `1:1`, `3:4`, `9:16`；通用示例也使用 `adaptive` |
| `duration` | 4–15 秒 |
| 输出 | MP4 |
| 其他通用字段 | `watermark`, `return_last_frame`, `callback_url`；具体可用性以当前模型卡 / API Explorer 为准 |

上述 Mini 规格和多模态能力均来自官方 Seedance 2.0 系列能力表及教程。[火山方舟：Doubao Seedance 2.0 系列教程](https://www.volcengine.com/docs/82379/2291680)、[火山方舟：视频生成教程](https://www.volcengine.com/docs/82379/2298881)

最小化的官方直连请求外形如下（**未在本轮执行**）：

```bash
curl 'https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks' \
  -H 'Authorization: Bearer <ARK_API_KEY>' \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "doubao-seedance-2-0-mini-260615",
    "content": [
      {"type": "text", "text": "清晨的海边，镜头缓慢向前推进，海浪自然起伏"}
    ],
    "generate_audio": true,
    "resolution": "720p",
    "ratio": "16:9",
    "duration": 5,
    "watermark": false
  }'
```

### 官方文档的当前不确定性

官方 Seedance 2.0 系列页已列出 Mini 的 Model ID、能力和 API 参数；但通用《视频生成教程》顶部仍保留一条“Mini 当前仅支持控制台体验，预计 6 月 25 日支持 API”的发布期提示。当前日期已过 6 月 25 日，但这条文字未被清理。因此，公开文档可以确认调用协议和请求结构，但 **Mini 在特定账号 / 渠道是否已放开 API 权限** 仍应以火山控制台模型开通状态或 API Explorer 的当场预检为准。[火山方舟：视频生成教程](https://www.volcengine.com/docs/82379/2298881)

## 对当前项目的直接判断

- 截图里的模型已经成为当前项目默认视频理解器：无界 `POST /v1/chat/completions` + `doubao-seed-2-0-mini-260215`，本地 MP4 实测返回 HTTP 200。
- 新 `source_blueprint` / legacy `story_analysis` 都必须产出 `剧情分析/video_understanding/analysis.json`；理解调用失败不能用接触表或人工概述假通过。
- 要生视频：模型必须是 `doubao-seedance-2-0-mini-260615`，协议必须是异步视频任务 API；当前无界 `/v1` 网关路由未暴露它。
- 如果无界后续宣布支持 Seedance Mini，需要它明确给出视频任务的路由映射，仅在 `/v1/models` 看到 `doubao-seed-2-0-mini-260215` 不等于支持 Seedance 视频生成。
