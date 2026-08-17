---
name: video-shot-refinement
description: 镜头精修：Use when a generated replica is broadly acceptable but one or a few bounded shots have weak action or hand/contact fidelity, stiff gaze or facial expression, skin-texture or lighting drift, or timing drift and should be regenerated as a short patch, then cut back into the existing master. Also use when video-replication needs a local post-generation repair without rerunning the full workflow.
---

# 镜头精修

这是 `$video-replication` 的生成后局部修复分支。主流程、已通过的 Part、口播、总时长和原音频保持锁定；本 skill 只重做明确失败的连续镜头。

## 依赖

- FFmpeg / ffprobe
- Python 3、OpenCV、NumPy、PyTorch、Pillow、Transformers
- 项目 Matpool GPT-Image-2 路线
- 支持 `reference_video` 的当前 Job 锁定 Seedance 请求路线

## 1. 锁定修复区间

从原片、当前成片和已有 `source_rhythm.json` 中确认：

- 当前成片需要替换的准确起止时间；
- 原片对应的连续镜头和硬切；
- 失败项是动作、手脸接触、手势、眼神表情、皮肤质感、节奏还是场景光影；
- 该区间是否含产品。
- 当前已通过 Part 在该区间的声音模式、最终口播、音效和声音参考时间段。

区间含多个连续镜头、极短过渡镜头，或用户报告“动作参考变弱 / 不按视频走”时，必须读取 [动作蓝图门禁](references/motion-blueprint.md)。用切镜候选加原生帧确认真实 Shot 数量、硬切时间、每镜首态、完整轨迹、动作峰值和终态；不得从旧提示词的 Shot 数量反推原片。

先用 `ffprobe` 和响度检测判定原区间是否存在可听声音。存在可听人声、环境声、音乐或动作声即进入有声分支；音频流存在但实际静音时记录响度证据。只有当前区间被证明确实无可听声音，最终提示词和请求才可使用静音格式。

将原片对应区间裁成最短动作参考。默认使用 Seedance 可接受的最短 4–5 秒任务；修复区间更短时仍只描述该区间的动作，生成后再整体匀速贴合原槽位。

区间内出现可见人脸时，读取 [references/face-expression-evidence.md](references/face-expression-evidence.md) 和主流程的 [表情提示预算](../video-replication/references/expression-prompt-budget.md)。先复用同源 `expression_prompt_profile.json`。

只有单人镜头、当前缺少同源缓存且失败项确为眼神表情时，才运行本地逐帧检测：

```bash
python3 tools/run_face_expression_detector.py \
  --video "<原片对应区间.mp4>" \
  --out-dir "<输出>/auto_face_expression"
```

该入口固定使用项目本地 `.venv-face-expression`，首次缺失时只在项目内初始化一次，不向系统 Python 安装依赖。依赖初始化或检测失败时直接停止并保留错误，不得用人工逐帧描述冒充检测产物。多人镜头不运行新的眨眼分析，直接复用开头视频理解的常规表情。单人检测用于选择能纠正呆板或错误首态的短 cue；原片没有可靠眨眼时，按表情提示预算的“无眨眼兜底”绑定一个自然动作节点，不按时长机械分配眨眼。

完成条件：一个连续修复区间、一个原片动作片段和一个可观察的失败项全部明确；多镜头区间已有逐 Shot 动作蓝图且每个硬切由原生帧确认；表情分支已选定，且没有新增视频理解调用。

## 2. 生成纯灰度深度动作参考

运行：

```bash
python3 .agents/skills/video-shot-refinement/scripts/render_depth_reference.py \
  "<原片对应区间.mp4>" \
  "<输出>/depth_reference_intermediate.mp4"

ffmpeg -y -i "<输出>/depth_reference_intermediate.mp4" \
  -c:v libx264 -pix_fmt yuv420p -an \
  "<输出>/depth_reference.mp4"
```

保持原片画幅、人物坐标、动作顺序、硬切、帧率和时长。默认使用纯深度，不叠加骨骼；当前实测中骨骼叠加没有提高动作还原，反而增加重新编排动作的概率。

完成条件：深度视频可解码、无音频、画幅比例与原片一致，并与动作蓝图具有相同 Shot 数量、顺序、硬切、完整轨迹、动作峰值和终态。

## 3. 制作单张场景光影参考

从原片修复区间抽取一张能看清场景、光线和核心动作的代表帧。调用项目 Matpool GPT-Image-2 direct edit：

- 图1：原片代表帧，保留场景、机位、构图、曝光、光线方向、皮肤受光、手部落点和动作阶段；
- 图2：一张批准人物图，完整替换人物脸、头发、身体和服装；
- 图3：仅在修复镜头确实出现产品时加入，用于替换并锁定当前产品；
- 清除字幕、花字和旧覆盖信息。

输出仍是一张与原片同画幅的正常分镜帧。它不是空场景图，而是“目标人物已经处于原场景和原动作阶段”的场景光影参考。

完成条件：只有一张批准人物图和一张场景光影参考进入视频请求；场景图已换成目标人物、字幕已清除、构图与画幅没有变化。含产品镜头还要确认产品已替换正确。

## 4. 写局部精修提示词

读取 [references/prompt-template.md](references/prompt-template.md)；多镜头动作同时读取 [动作蓝图门禁](references/motion-blueprint.md)。沿用现有提示词结构：

1. `参考图角色`
2. 一段统一成片要求
3. 按顺序排列的 `时间｜Shot` 块；有声重做使用 `画面 / 声音`，有真实动作音时再加 `音效`

身份统一定义为一个角色名，后文只使用该名称。每个 Shot 的 `画面` 写当前区间的可见动作；表情按源片实际节拍加入预算内 `expression_cue`，绑定 `expression_cue_source` 后合并进动作句，不设固定时长内的 cue 或眨眼次数上限。全片皮肤光影和手指触肤按模板中的对应规则执行。有可听声音时定义 `@音频1`，每个 Shot 都写 `声音`，并为可听或明显有用的可见动作写一条短 `音效`；从已通过 Part 提示词逐字恢复对应的声音模式、最终口播和音效。没有已通过 Part 的独立短实验才使用原视频同区间声音参考。只有响度证据确认当前原片区间确实无可听声音时才省略声音字段。产品未出现在修复区间时，整个产品角色都省略。

多镜头 source-locked 修复把 `@视频1` 定义为动作、镜头顺序和节奏参考，各份素材只负责自己的明确职责。Shot 数量、顺序、硬切、主体轨迹、动作速度和终态逐项来自动作蓝图；静态图片分别传递身份、场景、光线或产品外观，最终可见动作以已经核实并写入 Prompt 的逐 Shot 事件脚本为准。压缩定义不能删除这些参考职责和控制事实。

完成条件：提示词中的素材顺序与真实上传一致，每个 Shot 唯一绑定一个动作蓝图 Shot，极短镜头没有被合并；不存在独立 `表情：` 字段；动作修复没有删除已绑定的表情 cue，表情 cue 也没有改变动作蓝图；皮肤光影只写一次；触肤强度、有声文本和音效与原动作及已通过 Part 一致。

## 5. 生成短修复片段

读取 [references/request-contract.md](references/request-contract.md)。先读取当前 Job 的模型锁；局部精修继承该锁，不自行更换模型。Seedance 2.5 Job 必须使用 `seedance-25-replica` 的 taskCode 2509 请求构建器、源忠实度 QC 与 runner，无法表达局部视频参考时 STOP，绝不回退 2.0。提交顺序固定为：

1. 提示词；
2. `@图片1` 人物身份；
3. `@图片2` 场景和光影；
4. 可选 `@图片3` 产品；
5. `@视频1` 纯灰度深度动作。
6. 有声重做时的 `@音频1`：从已通过 Part 的声音参考中按当前修复区间准确裁取。

有可听声音的区间必须带裁好的声音参考，提示词必须含对应声音与音效，且 `generate_audio=true`；不得先静音生成再把旧音轨后贴上去。已通过 Part 存在时使用 Part 声音设计；没有已通过 Part 的独立短实验使用原视频同区间原声。只有当前原片区间被证明确实无可听声音时，provider 才生成无声视觉补丁。新的 provider 提交属于定向质量重做；当前用户明确要求测试或修复这个镜头时即构成本次提交授权，否则先通过主流程成本门禁。

完成条件：保存请求、任务结果和下载后的短片；请求中的每个素材角色位于 URL 对象外层，且没有素材被误设为首帧。有声重做必须证明请求实际包含 `reference_audio`、`generate_audio=true`，输出包含音频流。

## 6. 验收并剪回母版

只检查：

- 人物、发型、服装和手部年龄是否正确；
- 按动作蓝图逐项检查实际 Shot 数量、顺序、硬切、首帧启动、产品/双手/头部轨迹、动作峰值和终态；漏镜头、漏硬切、方向错误或静止化均为 `FAIL`；
- 复用表情证据链检查视线目标、表情时机和眨眼是否与对应 Shot 的原片节点一致；
- 场景、曝光、光线方向、局部皮肤高光、真实肤理和阴影是否来自场景参考；
- 是否出现灰度浮雕、控制图或明显视觉故障。

动作合格但时长不合时，整体匀速一次贴合原槽位：

```bash
python3 .agents/skills/video-shot-refinement/scripts/replace_visual_segment.py \
  --master "<当前母版.mp4>" \
  --patch "<合格短片.mp4>" \
  --start "<母版替换起点秒>" \
  --end "<母版替换终点秒>" \
  --output "<新母版.mp4>"
```

该脚本只替换视频画面，母版原音频整轨保留。动作本身不合格时重新生成一个完整短片，不把多个失败片段内部拼接成一个动作。

有声重做生成的短片用于剪回母版时，画面和 Seedance 新生成的声音作为同一个整体区间一次贴合原槽位，并同时替换该区间的视频与音频；其余母版音视频保持不变。只修画面的无声补丁仍使用母版原音频。

完成条件：新母版或独立验收片可解码、时长与原槽位一致；动作蓝图中的每个 Shot、硬切、轨迹、峰值和终态都有可见证据；表情眼神按独立证据链通过；有声重做必须存在音频流，口播、声音模式与音效覆盖当前区间；目标音视频被完整替换，其余时间线没有改变。用户认为修复效果合格时停止继续重抽。

## 适用边界

- 整片结构、台词、产品或人物普遍错误时，返回 `$video-replication` 对应主阶段修复。
- 单纯字幕问题使用 `$video-subtitle-removal`。
- 视觉局部问题使用本 skill；音频内容问题保留在原音频/口播分支处理。
- 每次只修一个连续区间，已通过区域保持锁定。
