---
title: Loop 提速 v2
labels:
  - implemented
status: implemented
created: 2026-06-22
---

# Loop 提速 v2 PRD

## 实施状态

已在 2026-06-22 完成实现与验证。实现拆分记录在 `docs/issues/loop-speed-v2/`，当前交接摘要见 `docs/loop-speed-v2-handoff.md`。

## 问题说明

现在的 Viral Replica Loop 已经有很多必要的质量约束，但跑起来太慢，而且很容易把 agent 卡进没有意义的细节循环。

从最近几次任务看，真正慢的不是口播、缝点、Seedance 提示词、音频切分、请求打包这些阶段。只要图片资产锁定，这些下游阶段通常几分钟到二十分钟内就能重新通过。真正耗时集中在图片阶段：人物服装没换干净、白泥厚度或颜色争议、GPT Image 证据不完整、跨 Part 连续性失败、护肤前后状态失败，以及图片一变后下游反复重跑。

用户视角里，这个 loop 本来应该很简单：

- 原视频分镜人物完整替换成批准的模特。
- 原视频产品完整替换成批准的产品。
- 背景不用换，整体结构、镜头顺序、动作节奏保留。
- 孔凤春清洁泥膜必须是厚厚的白泥或乳白泥。
- 交付只有两种：Seedance 前素材包，或者直接跑 Seedance 后交付最终视频。

但现在的问题是：

- 小到不影响 Seedance 的视觉阈值也会卡住。
- 真实视觉失败、证据缺失、轻微警告混在一起。
- 用户已经说“跑 Seedance”，loop 还可能再次确认。
- 图片改了一点，下游 voiceover / seam / prompt / request 又被大面积重跑。
- 最终视频原本还会因为“主观效果 review”停住。
- 线程太长后，agent 容易忘记已经写过的硬规则。

## 解决方案

Loop 提速 v2 要把已经确认过的运行规则固化成可执行的 workflow 行为。

loop 只有两个用户可见交付结果：

- **Pre-Seedance Handoff**：Seedance 前素材、音频、提示词、manifest、说明全部准备好。
- **Final Video**：已经跑完 Seedance，并通过最终客观技术检查的视频。

loop 默认不再因为以下事情停下来问用户：

- 图片小样确认。
- 轻微视觉警告。
- Part1 / Part2 分别确认 Seedance。
- 最终视频主观效果评价。

视觉结果分三类：

- **Hard Failure**：必须卡住，例如错人、错产品、错服装、源视频污染、明显压扁、镜头顺序变了、没有保存输出、白泥变黄/灰/水/薄。
- **Visual Warning**：不影响核心 Seedance 输入的小问题，可以自动继续，但必须写清楚 `why_not_fail`。
- **Evidence STOP**：图片可能肉眼可用，但缺少必需证据，比如 ImageGen 输入证据、manifest 绑定、active hash 对不上。

图片批次通过后，重视觉 QC 要按 active image hash 复用。只要最终图片 hash、manifest 映射、素材角色表、prompt reference roles 没变，下游阶段只跑轻量同步检查，不重复跑几何、连续性、护肤进程、白泥、GPT Image 合同这些重检查。

Seedance 成本边界要清楚：

- 用户说“跑 Seedance / 直接出视频 / 生成最终视频”，就是当前明确 job 的 Generation Approval。
- 当前 job 的批准默认覆盖该 job 必需的所有 Part 各一次。
- 批量生成必须明确说“这批都跑 / 全部跑 / 今天这些都跑 / 指定 job 列表”。
- 失败 Part 重跑需要新的定向批准。
- 最终视频客观失败最多只允许一次定向 Seedance 重试。

最终视频 QC 只卡客观硬失败。通过后直接交付视频，主观效果由用户看。

## 用户故事

1. 作为 loop 使用者，我希望一个任务只在 Seedance 前素材包或最终视频这两个结果处交付，这样中间过程不会反复打断我。
2. 作为 loop 使用者，我希望图片小样默认只是内部方向检查，这样不用我每次确认小样才能继续。
3. 作为 loop 使用者，我希望轻微视觉警告自动继续，这样 0.11 这种非核心差异不会浪费几个小时。
4. 作为 loop 使用者，我希望每个视觉警告都写清楚为什么不是失败，这样后续 agent 不会把真失败糊弄过去。
5. 作为 loop 使用者，我希望真正的错人、错产品、错服装、源污染仍然硬卡，这样速度提升不会牺牲核心质量。
6. 作为 loop 使用者，我希望证据问题和视觉问题分开，这样缺证据时修证据，不要重新争论图片本身。
7. 作为 loop 使用者，我希望 active image hash 没变时复用重视觉 QC，这样下游不会无意义重审。
8. 作为 loop 使用者，我希望 prompt/request 阶段只在必要时跑重视觉 QC，这样后半段能快起来。
9. 作为 loop 使用者，我希望图片 hash 变了就重新跑重视觉 QC，这样真正改图仍然可靠。
10. 作为 loop 使用者，我希望 manifest 或 reference role 变了也重新跑重视觉 QC，这样旧 PASS 不会被滥用。
11. 作为 loop 使用者，我希望我指出的可见缺陷能强制重审，这样人工发现的问题不会被缓存规则盖掉。
12. 作为 loop 使用者，我希望默认完整替换人物，包括脸、头发、身体和衣服，这样不会保留原视频人物服装。
13. 作为 loop 使用者，我希望只有我明确说保留源视频服装时才保留，这样复刻不是照抄。
14. 作为 loop 使用者，我希望孔凤春泥膜必须是厚白泥或乳白泥，这样产品质感不会跑偏。
15. 作为 loop 使用者，我希望核心人物、产品、结构、白泥都对时，不再纠结非常小的画布或颜色指标差异。
16. 作为 loop 使用者，我希望局部失败只修局部图片、局部 panel 或单个变量，这样不会重启整个任务。
17. 作为 loop 使用者，我希望被压扁、重构、换场景的候选图直接废弃，这样不会在坏图上继续修。
18. 作为 loop 使用者，我希望失败的 Part 不能当作另一个 Part 的连续性参考，这样一个错误不会污染整个视频。
19. 作为 loop 使用者，我希望“跑 Seedance”本身就是批准，这样 agent 不会重复确认。
20. 作为 loop 使用者，我希望当前 job 的 Seedance 批准覆盖所有必需 Part 各一次，这样 Part1/Part2 不需要分别确认。
21. 作为 loop 使用者，我希望批量批准必须明确，这样不会因为当前 job 批准误跑整批队列。
22. 作为 loop 使用者，我希望失败 Part 重跑要单独批准，这样 Seedance 成本受控。
23. 作为 loop 使用者，我希望最终视频失败最多只允许一次定向重跑，这样不会为了主观效果反复烧钱。
24. 作为 loop 使用者，我希望最终视频 QC 只检查客观硬失败，这样技术上没问题的视频能直接交付。
25. 作为 loop 使用者，我希望最终视频检查包括打不开、无视频流、无音频流、时长错、冻结、黑屏、漏话、重复话、缝点断、明显错人错产品等问题。
26. 作为 loop 使用者，我希望主观视频效果由我在交付后判断，而不是让 loop 卡住。
27. 作为 loop 使用者，我希望每次停止或完成都给我具体路径，这样我能直接看图、prompt、音频、QC 报告或视频。
28. 作为 loop 使用者，我希望 loop 自动报告每个 stage 花了多久，这样我知道到底慢在哪里。
29. 作为 loop 使用者，我希望耗时报告能区分图片生成、QC、下游复用和 Seedance 生成，这样优化有依据。
30. 作为 loop 使用者，我希望 loop 明确说明当前是视觉失败、证据失败、供应商失败还是成本门卡住，这样下一步很清楚。
31. 作为 loop 使用者，我希望下游 voiceover/seam/prompt/request 在图片没变时按 hash 复用，这样不会重复劳动。
32. 作为 loop 使用者，我希望最终 handoff 目录只保留 active 上传素材，这样不会混进废稿。
33. 作为 loop 使用者，我希望 runner 真正执行成本策略，而不是只在文档里写。
34. 作为 loop 使用者，我希望 self-audit 自动跑时只固定一个 job，不让多个 worker 抢共享状态。
35. 作为 loop 使用者，我希望 PRD 后能拆成小 issue，每个 issue 用新上下文实现，这样 agent 不会因为长线程变笨。
36. 作为后续 agent，我希望 Pre-Seedance Handoff、Generation Approval、Visual Warning、Visual Override、Hash-Gated Visual QC、Final Technical QC 这些术语有明确含义，这样不会中途重新解释。
37. 作为后续 agent，我希望 ADR 说明为什么跳过主观确认、为什么按 hash 复用 QC，这样不会把提速规则又改回慢流程。
38. 作为后续 agent，我希望测试集中在 runner/stage-rule/gate-record 这一层，这样能验证真实 workflow 行为。
39. 作为后续 agent，我希望只有 runner 看不到的地方才补脚本级测试，这样测试不会太碎。
40. 作为后续 agent，我希望事件日志能生成耗时摘要，这样每次长跑都能留下可分析的性能证据。

## 实现决策

- 最高优先级的测试和实现 seam 是 runner / stage-rule / gate-record 行为层，因为它决定继续、停止、写 gate、成本控制和进入哪个交付结果。
- stage 分类保持不变：story analysis、storyboard、image sample、image batch QC、voiceover、seam、Seedance prompt、audio boundary QC、request QC、generation approval、generation、final QC。
- 用户可见交付结果只有 Pre-Seedance Handoff 和 Final Video。
- image sample 默认不再是用户确认点，除非用户明确要求先看小样。
- 视觉 QC 必须分成 Hard Failure、Visual Warning、Evidence STOP。
- Visual Warning 必须写 `why_not_fail`。
- Visual Warning 不能覆盖错人、错产品、错服装、源污染、镜头顺序改变、明显压扁、没保存输出、白泥薄/水/灰/黄。
- Hash-Gated Visual QC 在 active image hash 和映射不变时复用重 QC。
- prompt/request 阶段始终跑轻量同步检查：manifest 映射、prompt/request 同步、handoff 目录清洁度、最终音频时长、runner stop/cost gate。
- 只有 active image hash、manifest、素材角色、prompt reference role 改变，或用户报告可见缺陷时，才重跑重视觉 QC。
- 默认人物替换是完整替换，批准的模特控制脸、头发、身体、衣服。
- 源视频服装只有用户明确要求时才保留。
- 孔凤春白泥规则仍然是硬规则：必须是厚白泥或乳白泥，不能黄、灰、水、薄。
- Matpool GPT-Image-2 只有在真实提交本地图像引用时才算有效 edit/reference route；纯文本写本地路径不算。
- 失败候选图如果已经重构、压扁、换场景或源污染，直接废弃。
- 下游阶段在视觉没变时按 hash 复用已有 PASS 证据。
- 用户直接说跑 Seedance，就是当前明确 job 的 Generation Approval。
- 当前 job 的 Generation Approval 覆盖该 job 所有必需 Part 各一次。
- 批量 approval 必须明确说批量、全部或命名 job 集合。
- 失败 Part 重跑需要新的定向 approval。
- Final Technical QC 只卡客观硬失败。
- Final Technical QC 通过后直接进入 done 并交付最终视频。
- Final Technical QC 失败最多触发一次定向 Seedance 重试。
- 最终视频脚本要包含 black-screen 检测，除了 ffprobe、流检查、时长、freeze、ASR 品牌词和 contact sheet。
- loop 要能从 event log 生成按 job/stage 聚合的耗时摘要，并突出非 PASS 事件。
- 因为仓库里没有配置好的 issue tracker，本 PRD 先作为仓库文档发布；对应 issue 已拆分并完成实现。

## 测试决策

- 首选测试 seam 是 runner / stage-rule / gate-record 行为层。
- 测试应该验证外部行为：是否 continue、是否 stop、next status、成本门、retry 边界、最终交付结果。
- runner 测试要验证 Final Technical QC 通过后进入 done，而不是停在主观 review。
- runner 测试要验证当前 job 的 Generation Approval 覆盖所有必需 Part 各一次。
- runner 测试要验证当前 job approval 不会扩展成 batch approval。
- runner 测试要验证 failed-Part retry 和 final-video regeneration 是新的成本/approval 边界。
- runner 测试要验证第二次 Seedance retry 会被阻止或 STOP。
- runner 测试要验证 image sample 在 self-audit 流程里不是默认用户停点。
- runner 测试要验证 active image hash 不变时可以复用重视觉 QC。
- runner 测试要验证 image hash、manifest、reference role 或用户可见缺陷变化时必须重跑重视觉 QC。
- gate-record 测试要验证 Visual Warning 必须有 `why_not_fail`。
- gate-record 测试要验证 Visual Warning 不能放过 hard failures。
- final-video QC 脚本测试要验证缺文件、缺视频流、缺音频流、时长不对、freeze、black frame、ASR 缺品牌词、contact sheet 生成。
- cost-policy 测试要解析机器 JSON，并验证 current-job approval、batch scope、required Parts coverage、failed-Part retry approval、one targeted final retry。
- timing-summary 测试用小型 fixture event log，验证 stage 聚合、耗时输出和非 PASS 高亮。
- 测试不要真实提交 Seedance。
- 测试不要依赖内部函数名，只测 runner 决策和输出报告。

## 不在范围内

- 不优化某个当前 job 的具体视觉效果。
- 不运行付费 Seedance。
- 不改孔凤春产品、client profile 或创意策略。
- 不替换 Matpool GPT-Image-2 调用路线。
- 不做 Web UI。
- 不重写完整分布式任务系统。
- 不清理所有历史 artifacts。
- 不消灭所有人类主观判断；用户仍然在交付后判断最终效果。
- 不默认批准批量生成。
- 不允许无限 Seedance 重试。

## 补充说明

最近日志显示，图片资产一旦确认，下游 revalidation 很快。慢的阶段主要来自图片阶段不确定性、ImageGen 证据缺失或不匹配、跨 Part 连续性失败、护肤进程失败、服装错误，以及视觉变化后下游重复验证。

最重要的提速不是单纯并行，而是减少 active visual artifact 锁定后的无意义重复工作。并行 lane 有用，但必须保证共享状态由 coordinator 统一写，job lane 不能抢 `jobs.csv`、`RUNNER_STATE.json`、`STATE.md`。

本 PRD 依赖这些已确认术语和 ADR：

- Hash-Gated Visual QC：按 active image hash 复用重视觉 QC。
- Direct Seedance Request Is Approval：直接生成请求就是当前明确 job 的批准，并覆盖必需 Part 各一次。
- Final QC Is Objective Only：最终主观效果交付后由用户判断，不作为 loop 停点。

当前实现交接见 `docs/loop-speed-v2-handoff.md`，任务拆分与完成状态见 `docs/issues/loop-speed-v2/000-index.md`。
