# 火山引擎可调用剪辑能力调研：能否替代一部分剪映剪辑 Agent

日期：2026-07-20
范围：只引用火山引擎 / 火山方舟官方文档；未提交任何付费任务，也未对账号权限做实测。

## 结论

**有，而且有两条可调用路线。**

1. **首选接入：AI MediaKit 的 Vibe Editing。** 这是面向后端 / Agent 的自然语言剪辑 API：传视频、图片、音频、字幕素材和一句剪辑指令，异步产出成片。它最适合接在本项目 `generation -> finishing` 之后，做拼接、删段、BGM、文字 / 已有字幕、转场和特效的试验性云端收尾。[Vibe Editing 指南](https://www.volcengine.com/docs/6448/2549864?lang=zh)；[提交 API](https://www.volcengine.com/docs/6448/2563056?lang=zh)
2. **更像“剪辑 Agent”：视频点播 Aideo Agent。** 它既有控制台对话，也有 `SubmitAideoTaskAsync` / `GetAideoTaskResult` OpenAPI；官方例子表明 `Prompt` 会被 Agent 转成剪辑参数，可对多个 VOD 视频做截取、拼接和带转场的输出。代价是要接入视频点播空间、Vid 和 VOD 的 AK/SK 签名体系。[Aideo Agent 快速开始](https://www.volcengine.com/docs/4/1900367)；[获取 Aideo 任务结果 API](https://www.volcengine.com/docs/4/1963660)；[SubmitAideoTaskAsync API](https://api.volcengine.com/api-docs/view?action=SubmitAideoTaskAsync&serviceCode=vod&version=2025-03-03)
3. **不能把它直接说成剪映“一键卡点成片”的等价物。** 官方资料明确证明了 BGM、字幕、转场和多种特效可用；但本轮没有找到官方承诺“自动检测音乐节拍后选镜头卡点”“自动挑选并落位音效”“自动 ASR 后生成特定花字字幕”的单一 Agent 能力。因此这些必须作为一次真实小样的验收项，不能先写进产品承诺。[Vibe Editing 指南](https://www.volcengine.com/docs/6448/2549864?lang=zh)；[提交 API 的特效 / 转场清单](https://www.volcengine.com/docs/6448/2563056?lang=zh)

## 方案对比

| 方案 | 是否可用自然语言调用 | 已由官方资料证明的能力 | 接入与费用 | 对本项目的判断 |
| --- | --- | --- | --- | --- |
| **AI MediaKit Vibe Editing** | 是。`POST /api/v1/tools/vibe-editing`，`content` 可混排文本、视频、图片、音频、字幕 URL；异步返回 `task_id`。 | 多素材时序拼接、截取、速度、裁剪、音量 / 淡入淡出、BGM、文本或 SRT/ASS 字幕、滤镜、特效、转场、元素动画。输出可设 360p–4K、15–60 fps。 | `Authorization: Bearer <MediaKit API Key>`；首次须在控制台授权 AI MediaKit 使用 IMP 资源。自然语言意图解析本身当前不计费，底层云端合成按成功产物的时长 / 分辨率计费；产物 URL 有效期 24 小时。 | **最适合作为现有 finishing 的可选云端执行器。** 不改变当前可审查的 `edit_plan.json`；先用一条成片做付费 A/B。 |
| **VOD Aideo Agent** | 是。控制台可对话；API 有 `SubmitAideoTaskAsync` 与 `GetAideoTaskResult`。查询结果中 `Prompt` 会回显为 Agent 解析出的 `SkillParams`。 | 高光智剪、字幕擦除、视频理解、翻译、智能剪辑；智能剪辑明确包括多素材拼接、截取、合成、特效，典型场景含画中画或 BGM。 | 输入 / 输出在视频点播空间内，查询接口要求 `SpaceName`、`TaskId`；使用 VOD OpenAPI。AI 剪辑以输出时长计费，720p 及以下官方标价为 **0.018 元 / 分钟**，另有 VOD 存储和分发费用。 | **功能形态最接近剪辑 Agent，但工程接入更重。** 适合以后需要把素材、任务、成片都沉到 VOD 的产品化流程。 |
| **智能创作云“高级成片”** | 官方有 OpenAPI 页面。 | 本轮可核实其为“高级成片 OpenAPI”，但未取得能证明自然语言 Agent、自动字幕或卡点的官方参数 / 能力说明。 | 尚不能据此确定鉴权、价格、输入约束。 | **暂不选。** 先不为它做集成，等拿到产品权限或完整 API 合同再评估。 |

Vibe Editing 的接口、鉴权、输出规格、异步结果和 24 小时下载限制见[提交智能剪辑任务 API](https://www.volcengine.com/docs/6448/2563056?lang=zh)及[查询任务信息 API](https://www.volcengine.com/docs/6448/2278532?lang=zh)。其首次跨服务授权、两种使用模式和计费边界见[Vibe Editing 指南](https://www.volcengine.com/docs/6448/2549864?lang=zh)。Aideo 的 API 状态为 `Processing` / `Completed` / `Failed`，并聚合底层能力的 `ApiResponses`；它不是把剪映桌面应用远程化，而是 VOD 内的另一套 Agent / 任务体系。[GetAideoTaskResult](https://www.volcengine.com/docs/4/1963660)

## “字幕、卡点、音效”逐项判断

| 期待 | 现在能严谨地说什么 | 建议做法 |
| --- | --- | --- |
| 自动字幕 | AI MediaKit 有独立的“语音转字幕（ASR）”任务和“视频加字幕”任务；Vibe Editing 也可接收 `subtitle_url`，并支持文本 / SRT / ASS 字幕。官方没有承诺 Vibe 会从原声自动识别后生成指定花字字幕。 | 继续以本项目 ASR / 审核后的 SRT 为真源，再让 Vibe 或本地 FFmpeg 负责烧录和样式；需要验证 ASR 时单独调用其 API。 |
| BGM 与混音 | Vibe 官方示例直接支持传 `audio_url` 并以自然语言要求加 BGM、调音量和淡出；Aideo 的官方智能剪辑场景也列出 BGM。 | BGM 文件、音量、开始 / 结束点写入 `edit_plan.json`，再把同一计划转换为自然语言请求，避免让模型凭感觉改掉口播。 |
| 转场 / 视觉“卡点感” | Vibe 有可按名称指定的转场和特效，官方清单把部分效果标为适合音乐卡点或节奏场景。 | 可以明确指定“在哪两个片段之间用哪个转场”，但不要假定它会自行检测 BPM 或自动选节拍点。 |
| 自动音效 | 本轮未找到 Vibe 或 Aideo 自动生成 / 自动选配音效的官方合同。 | 先自备已授权音效并写清时间点；若未来要自动化，单独做“音效检索 / 选择”组件，不把它伪装成已验证的火山剪辑能力。 |

官方可调用的 ASR / 字幕接口分别见[语音转字幕（ASR）](https://www.volcengine.com/docs/6448/2381968)和[提交视频加字幕任务 API](https://www.volcengine.com/docs/6448/2372086)。Vibe 的转场 / 特效和 BGM / 字幕提示词示例见[提交智能剪辑任务 API](https://www.volcengine.com/docs/6448/2563056?lang=zh)。

## 建议落地顺序

1. 保持当前 `local_ffmpeg` 的 `edit_plan.json` 为默认收尾路径：免费、可复现，且不会把模型的创意决定混入必需的产品 / 人物 / 口播约束。
2. 新增一个**不默认执行**的 `vibe_editing` 试验执行器：把同一份 plan 转成带明确时间段、素材顺序、BGM 音量、字幕文件和转场名称的请求；先只用 1 条已生成的短视频做一次付费试验。
3. 试验验收只看可观察结果：镜头顺序与保留区间、口播未被 BGM 覆盖、字幕文字 / 时序 / 样式、转场点、是否产生黑帧或拉伸，以及产品标签 / 人物身份是否受损。**卡点和音效单列为待验证，不通过就不进入默认链路。**
4. 若试验显示“自然语言剪辑 + VOD 素材治理”确实优于 Vibe，再评估 Aideo；那是一次 VOD 素材入库、鉴权和产物回收的独立接入，不应和当前 Seedance 生成链路混在同一次改动里。

## 未证实项与下一步

- 尚未用本账号预检 AI MediaKit API Key、IMP 授权、VOD 空间、区域配额或实际账单；公开文档证明接口存在，不等于当前账号已开通。
- 未运行付费任务，因此没有实际效果对比，尤其没有“自动卡点 / 自动音效 / 花字字幕”质量证据。
- 智能创作云“高级成片”的官方入口已找到，但公开页面未提供足够的可验证合同，故不建议现在集成。[高级成片 OpenAPI](https://www.volcengine.com/docs/6664/1323772?lang=zh)

如果要继续，最小下一步是：拿一条已通过本项目视频 QC 的 10–15 秒 Part，带明确 BGM 与 SRT，先做 **1 次 Vibe Editing 实测**；该操作会产生云端合成费用，需先通过项目 cost gate 并得到用户明确批准。
