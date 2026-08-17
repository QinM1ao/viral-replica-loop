# 表情提示预算

目标是让人物不呆板，不是逐帧复刻每次眨眼。数值唯一来源为 `rules/EXPRESSION_PROMPT_POLICY.json`。

## 开头只理解一次

`source_blueprint` 的完整 Seed 2.0 Mini 视频理解在现有 `timeline` 内同时产出：

- `people_mode`
- `visible_roles`
- `expression_and_gaze`

ASR、接触表、完整视频理解、0–3 秒快速钩子复核、分镜准备、节奏检测和本地脸部检测按现有 sealed plan 并发。表情不触发新的语义模型调用。结果按源视频 hash 缓存为：

```text
output/<job-id>/剧情分析/expression_prompt_profile.json
```

后续分镜、导演计划、提示词和局部精修只读取该 profile；源视频 hash 未变时不重新理解。

## 两条分支

| 分支 | 表情来源 | 眨眼处理 |
|---|---|---|
| `single_person_budgeted` | 同一次视频理解的常规表情 + 并发生成的原生帧眼睑证据 | 只在能纠正呆板或错误首态时选一个动作相关节点 |
| `multi_person_semantic` | 同一次视频理解的 `expression_and_gaze` | 不新增眨眼提示，不读取逐帧眨眼结果 |

`no_person` 省略表情提示；`uncertain` 使用多人分支的保守预算。

## 写入导演计划

每个源片证据 beat 只有一个可选 `expression_cue`。cue 的数量由源片中实际含脸节拍和证据决定，不设“每 15 秒最多几条”或“最多眨眼几次”的固定上限。渲染时 cue 并入 `画面：`，不得生成独立 `表情：` 字段。

选择顺序：

1. 当前生成结果确实错误的首帧眼睛状态；
2. 一个有动机的注视或表情变化；
3. 与喷雾、转头、停顿或说话节点绑定的自然眨眼。

`expression_cue_source` 必须绑定 `video_understanding:`、`face_expression:`、`natural_blink_fallback:` 或明确的 `user_request:` 证据。原片同一 Shot 内连续眨眼时，用“快速连续眨眼”等一句自然语言概括，不逐次列出，也不把实际次数改写成固定规则。未入选的检测事件保留为证据，不进入提示词；不得为了覆盖全部检测节点拉长提示词。

### 单人原片无眨眼

本地检测在人脸覆盖率达到配置阈值且没有可靠 `blink` 事件时，“无眨眼”本身构成兜底证据。仅当视频理解没有表明人物在刻意持续凝视时，才在自然动作节点加入短促眨眼：

1. 优先动作释放或皮肤回弹；
2. 其次手部掠过面部后的视线回落；
3. 再次为转头稳定或自然话语停顿。

不按视频秒数分配眨眼。每个连续的无眨眼人脸表演区间只选择必要的自然节点，cue 绑定当前 beat 的 `natural_blink_fallback:<beat_id>`；硬切边缘、首帧、眼睛被遮挡最重处和刻意凝视段不选。多人分支不启用此兜底。

## 完成条件

- `expression_prompt_profile.json` 与当前源视频 hash 一致；
- 单人/多人分支与 `people_mode` 一致；
- 每个 `expression_cue` 的长度、分句数和证据来源通过 `pre_seedance_pack.py` 的预算校验；
- 多人 cue 不含眨眼、闭眼、睁眼或眼睑指令；
- 最终提示词没有独立 `表情：` 字段；
- 后续没有新增视频理解调用。
