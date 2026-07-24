---
name: video-replication
description: |
  爆款视频复刻全流程 skill：拆分镜 → 图像生成/改图（换人换产品去字幕；GPT Image 只走 Matpool GPT-Image-2 项目路线）→ 写口播 → 缝点设计 → 生成 Seedance 提示词 → 通过 Seedance 真人过审/素材库直接出片、拼接、打包。
  已包含护肤/美妆/清洁泥膜类复刻经验：前后对比、洗后效果、无字幕 Seedance 写法、产品名口播时长、音频分段边界质检、上半身人物身份图、紧裁产品图。
  当用户提到以下场景时务必使用此 skill：
  - 复刻视频、翻拍视频、模仿爆款视频、视频二创
  - 用 Seedance/可灵/Sora 重新生成视频
  - 替换视频中的人物/产品/元素，保留镜头节奏
  - 把参考视频变成自己的视频
  - 护肤品、泥膜、洁面、面膜、美妆类电商视频复刻
  - "像这个视频一样做一个"、"换成我的产品"
  即使没说"复刻"，只要意图是"拿别人的视频改内容重新做"，就应触发此 skill。
  如果用户请求的是 viral-replica-loop 的 jobs.csv、runner、worker、gate、STATE.md、Seedance 前停、批量自检、成本审批或发布治理，请改用 $viral-replica 作为外层 loop adapter。
---

# 爆款视频复刻 Skill

## 工作流总览

```
参考视频 → ⓪视频剧情分析 → ①拆分镜/压缩分段 → ②全 Part 批量改图/快修 → ③改图审核 → ④写口播 → ⑤缝点设计 → ⑥Seedance 路由/提示词 → ⑦Seedance 生成 → ⑧拼接/静音保险版/打包
```

步骤⓪是复刻核心（先理解原片剧情和话术），步骤②/③是视觉替换核心（换人换产品并审核），步骤⑤是连续性核心（让多段15秒不割裂）。

## Loop Boundary

在 `viral-replica-loop` 仓库里，本 skill 只负责复刻 craft：剧情、分镜、改图、口播、缝点、Seedance 提示词、生成和 final QC 方法。队列选择、`jobs.csv`、`STATE.md` 写回、checker 记录、cost approval、批量自检和发布治理由 `$viral-replica` 负责。

Governance evidence lives outside the initial load:

- `manifest.json`
- `agents/interface.yaml`
- `evals/trigger_cases.json`
- `evals/output_cases.json`
- `reports/trust_report.md`
- `reports/output_quality_scorecard.md`

> **GPT Image 路线硬规则：步骤②/③/快修只使用项目 Matpool GPT-Image-2 路线：`.agents/skills/video-replication/scripts/generate.py`。必须通过 `MATPOOL_API_KEY` 鉴权，实际提交源分镜、product profile 声明的产品/材质参考、人物等本地图片作为 multipart `image` 输入，才算有效 direct edit。不要尝试任何废弃 GPT Image 路线或网关探测。调用前读取 `references/codex-imagegen-direct.md`。**

> **产品 profile 硬规则：所有产品先读 `output/<job-id>/product_profile.json`。通用规则永远加载；品类、品牌、SKU 规则只能由 product profile 显式加载，不能只凭 `孔凤春` 等品牌词触发。`开盖白泥`、`手指取泥`、`洗后脸`、泥膜白度/厚度、单男模等泥膜经验只在 profile 加载 `category:clay_mask` 或 `sku:kongfengchun_clean_mud_mask` 时执行。`category:toner`、`category:unknown` 和其他新产品默认只执行通用产品一致性、源节奏、去旧产品/旧人物/字幕污染规则。**

> **产品文字和角色映射硬规则：当 product profile 声明 `visible_text_patterns`，产品近景必须保留真实可读瓶身/包装文字；空白瓶、抹平标签、伪文字或只有标志没有文字都不能通过。多人源片必须先写角色映射：批准身份只替换源片定义的主角/产品主持人，配角保留故事功能和性别，可泛化或去识别，但不能被替换成主角身份。**

> **Matpool GPT-Image-2 改图硬规则：Matpool 必须按 GPT Image API edit/reference 经验执行，不是纯文生图。必须实际提交源 Part 分镜图、product profile 声明的产品参考图、人物身份图（以及 profile 需要时的材质/洗后脸图），并在 `codex_imagegen_contract.json` 里写清各图角色和 hash。源分镜传构图、镜头顺序、景别、动作节奏和场景关系，不传旧产品、旧涂抹工具、旧主播脸、旧人物衣服、旧材质颜色或字幕；默认完整换人，人物图传目标脸、发型、身体和服装，除非用户明确说只换脸或保留原衣服。泥膜类如果原片有管状/棒状/刷头/手臂试色，且当前 profile 加载 clay-mask 规则，必须先翻译成“手指从罐内取白泥、指腹上脸”，不要把旧工具词写进生成提示词里当负面锚点；非泥膜产品要翻译成该 product profile 的真实使用动作。**

> **简单替换改图硬规则：默认图像任务不是重新设计画面，而是直接编辑源 Part 分镜：人物换成批准人物，产品/工具/材质换成 product profile 声明的当前产品、当前材质和当前使用动作，字幕/旧信息卡清掉；原场景、镜头裁切、手部动作位置、源分镜面板网格、镜头顺序和动作节奏都保持。竖屏源片默认 4 列 x 3 行，横屏源片默认 3 列 x 4 行，不能把横屏做成过长的 4x3 宽条。不要额外加连续性参考、风格重塑、浴室新场景、海报构图或尺寸归一化，除非用户明确要求。**

> **API 效果几何硬规则：参考 `job-002` 的正确效果。Matpool 生成的 `AI改好分镜图` 必须像 API edit 一样保留源 Part 分镜的整张 12 格画布、每格大小、位置和镜头顺序；只替换人、产品、泥膜和文字污染。不能重新生成一个新的 12 格模板，不能改变格子大小/边框/标签体系，不能让人物被横向或纵向挤压。若画布尺寸只出现极小 API 输出漂移可接受；若明显换尺寸、换排版或看起来像重排的 storyboard collage，必须 `FAIL`。在 loop kit 里用 `tools/storyboard_geometry_qc.py` 检查。**

> **Matpool 效果保护硬规则：Matpool GPT-Image-2 是唯一已验证 GPT Image 基线。不要为了省事改提示词风格、参考图顺序、`--quality`、`--size` 或 `-i/--image` 语义。失败时修 Matpool 输入、提示词或素材；不要切到废弃 API。**

> **快修硬规则：局部问题不要重跑全链路。若只是 profile-required 材质偏色、单个产品镜头缺产品、标签被擦掉、洗后脸参考不合格，优先只修目标图/目标面板，修好后立刻同步到 final-images、Seedance refs、最终网页端输出区，再跑一次硬检和视觉检查。但如果候选图已经换场景、重排分镜、压扁人物或改变镜头顺序，不准继续快修，必须丢弃候选图并从源 Part 分镜重做。**

> **视觉资产硬规则：步骤②/③的产物只能是当前 job 的 `AI改好分镜图`，也就是保存到磁盘、可直接给 Seedance 使用的 AI 生成/改图分镜。Python/PIL 拼图、source rhythm board、contact sheet、裁剪源帧、validated anchor 拼图、旧 job 分镜、未保存的“生成方向”都不能作为小样、批量改图、final image 或 Seedance ref。每个 job 必须写 `output/<job-id>/visual-assets/approved_visual_manifest.json` 并通过 `tools/visual_asset_manifest_qc.py` 后，才能进入 Seedance 提示词/请求阶段。**

> **硬规则：不要只看分镜图就写口播/Seedance。必须先做视频剧情分析，复刻原片的冲突、反转、卖点、福利收口，再替换成用户的人物和产品。**

> **硬规则：用户提供的产品图和产品名优先于视觉分析工具的粗分类。视觉分析把鸭脖、鸡脖、肉干等识别成“肉块”时，不要沿用“肉块”写法；必须回看产品图，写出可见形态特征（例如骨孔、骨节、截面、纤维、调料颗粒）。**

> **硬规则：改图后必须审核，再写口播和 Seedance。产品形态、人物一致性、字幕清理、Part 是否串片，任何一项不合格都要重跑或修提示词，不能把错误继续带到口播/视频提示词。**

> **硬规则：用户要“缩成30秒/做一个30秒小剧情”时，不要复刻全长。把原片剧情压成2个15秒 Part：Part1 继承开场冲突和卖点引入，Part2 继承证明点、解决方案和收口。**

> **硬规则：30秒双段或多段拼接视频默认禁止BGM。Seedance 提示词必须写“禁止BGM、禁止配乐、禁止音乐铺底、禁止鼓点”，只保留对白、环境声和真实操作音。否则两段拼接时音乐断点会露馅。只有用户明确要单条氛围片/带音乐版，才允许生成BGM。**

> **硬规则：产品名和品牌名以用户最新明确说法为准。参考视频标题、字幕或视觉识别里的旧品牌名不能沿用；例如用户说“产品名称是新空白，产品是全屋智能”，提示词、口播、文件名都必须锁定为“新空白全屋智能”。**

> **硬规则：用户提供“指定主播/厂家人物视频/指定声音”时，人物和声音都必须作为变量输入，不能再让 Seedance 随机生成人物。先抽/确认一张自然表情的主身份图，再用这张图做图像改图和 Seedance 参考图；声音参考按每个15秒 Part 切成独立音频传入。默认走 Apifox 文档里的 `/wj-open/v2/open-platform/task/task_create` 任务接口，真人脸项目优先 `taskCode=2509`。详细流程读取 `references/identity-audio-seedance.md`。**

> **硬规则：带声音多段视频生成前必须做音频边界质检。每个 Part 的参考音频必须按原片转写的完整句子边界切分，不能机械切 15.00s。Seedance/网页端上传的每条音频必须 `<=15.00s`，建议输出 `14.90s` 留编码和网页容差；15.01s、15.15s 都算失败。如果一句话在 14.56s 结束，可以切到 14.56s；不要补到超过 15.00s。下一 Part 才从新句开始。禁止让上一段参考音频带入下一段开头台词，也禁止让下一段参考音频带入上一段尾句。生成前用 ASR 转写每段 reference audio，并用 ffprobe 确认时长；不通过就不能提交 Seedance。**

> **硬规则：Seedance 提示词必须是可直接提交的干净提示词，不能写内部计划、纠错说明或污染词。不要写“不是泥膜棒”“不是孤立商品图”“不要裁头”“不拆衣服”“后续继承同一个人”“同Part1完全一致”等给人看的说明。用正向事实描述 product profile 规定的实际画面：当前产品包装/标签/材质、目标模特服装、连续手部动作；只有 clay-mask profile 才写白色圆罐、开盖乳白泥膏和指腹上脸。**

> **硬规则：产品还原要求高时，产品图必须同时进入图像改图和 Seedance 生成。不要只在提示词里写产品名；也不要把带旧产品的原片分镜直接喂给 Seedance，否则容易把旧产品污染进成片。**

> **硬规则：Seedance 生成前必须先做素材角色绑定。每张图、每段视频、每条音频只能先指定一个主角色：身份、产品、分镜/动作、环境、首帧、尾帧、声音节奏。必须同时写清“传递什么”和“不传递什么”。不要写“参考所有图片风格”这种含糊说法。**

> **硬规则：Seedance 2.0 网页端或 R2V 交付提示词必须是模型可读的 3-shot production brief。先写参考图角色、主目标/次目标/主动简化，再用 `Shot 1/2/3` 承载 15 秒内的关键镜头组。不要把 `Part1最终分镜图`、`AI改好分镜图`、`current-job`、`source rhythm board` 等内部工作流词写进最终提示词；这些只能出现在 manifest 和 QC 文档里。详细标准读取 `references/seedance-20-prompt-standard.md`。**

> **硬规则：最终 Seedance 提示词必须从剧情分析推导，不得从分镜图直接发挥。写提示词前必须先有 `source time -> source visual action -> source line/speaker -> target visual action -> target line/speaker -> reference binding` 映射；每个原片关键落点都要进入对应 `Shot`，并区分“画外音旁白”和“画面内同期口播”。产品、手部、掌心、手机、瓶身、台面证明镜头里人物不张口；只有稳定看镜头的人脸短句才写同期口播。**

> **硬规则：产品参考图只校准包装身份、标签文字、瓶身比例或材质，不控制镜头构图。产品镜头的构图、手部动作、瓶身位置和出现节奏必须绑定到 source-aligned `@图片1`。不要写“女主持瓶或产品在台面”“掌心或手背”“屏障修护或敏肌适用”这类二选一，原片是什么落点就写什么落点；关键产品动作要用确定动作和正向运动描述，避免 Seedance 选成静止 packshot。**

> **硬规则：护肤/美妆/清洁泥膜类电商视频必须做明确前后对比。使用前可以有轻微暗沉、油光、毛孔、闭口或粗糙；使用后必须同一人同一场景明显更亮、更干净、更细腻，闭口和粗糙感减少。若洗后肤色、皮肤质感与使用前无明显差异，或洗后仍显闭口/暗沉/粗糙，就不符合电商视频目标，必须重跑或修提示词。护肤/美妆/泥膜/洁面/面膜项目必须读取 `references/skincare-beauty-replication.md`。**

## 依赖

- **ffmpeg + Python 3 + Pillow**（分镜拆解）
- **Matpool GPT-Image-2**（改图；项目唯一 GPT Image 路线）
- **Seedance 2.0**（生成视频）
- **MCP 视觉/视频分析工具**（优先用于分析原视频画面、音频、口播和时间线）

安装：
```bash
brew install ffmpeg
pip3 install Pillow
```

## 本地环境变量

GPT Image 出图只读取 Matpool：

```bash
export MATPOOL_API_KEY="sk-..."
export MATPOOL_BASE_URL="https://token.matpool.com/v1" # 可省略，默认就是这个
```

不要把 key 写进提示词、日志、仓库配置或最终回复。只检查变量是否存在：

```bash
printenv MATPOOL_API_KEY >/dev/null && echo OK
```

Seedance 视频生成仍使用无界/网关配置，和 GPT Image 出图路线分开：

```bash
~/.config/wujieai/env
```

这个文件会导出：

```bash
WUJIEAI_API_KEY
HIGRESS_API_KEY
GATEWAY_API_KEY
```

如果在非交互 shell、脚本或 GUI 工具里生成 Seedance 视频时找不到这些变量，先显式加载：

```bash
source "$HOME/.config/wujieai/env"
```

## 步骤 ⓪：视频剧情分析（必做，MCP 优先）

先看原视频，不要直接写“普通种草口播”。复刻的目标是保留原片剧情骨架，而不是只保留镜头构图。

### 0a. 用 MCP 直接分析原视频（首选）

> **绝对不能跳过这一步。口播文案必须从原视频提取/改写，不能凭分镜自己编。**

如果可用，优先调用视频分析 MCP（例如 `mcp_zai-vision_analyze_video`）逐秒分析原视频：画面动作、音频逐句、起止时间、字幕/花字、声音来源、复刻功能。

MCP 输出必须整理成：
- 原视频完整口播逐句文案（带时间戳）
- 每一句的说话人/声音来源：女主同期声、同事同期声、群体反应、画外音旁白、混合；多人视频不能合并成一条不区分角色的“总口播”
- 说话方式判断（画外音旁白 / 画面内同期声）
- 画面动作时间线
- 原片剧情骨架：冲突、反转、卖点、价格/福利、收口
- 需要删除/替换/弱化的人物关系（例如多女主、抢戏同事）

这些数据是后续写口播、写 Seedance 提示词、判断缝点的主要依据。MCP 能直接分析音频和画面时，比只抽帧更优先。

### 0b. 抽帧看完整剧情（MCP 不可用时 fallback）

如果没有可用 MCP，或 MCP 音频识别不稳定，再用 ffmpeg 抽帧做接触表辅助分析：

```bash
mkdir -p "<输出目录>/视频分析/frames_2fps"
ffmpeg -y -i "<视频路径>" \
  -vf "fps=2,scale=288:512" \
  -q:v 2 \
  "<输出目录>/视频分析/frames_2fps/f_%03d.jpg"
```

把 2fps 帧做成 contact sheet，逐段记录：
- 开场钩子：冲突/问题/反差是什么
- 中段卖点：价格、成分、质感、场景、证明点是什么
- 后段转化：福利、行动号召、直播间/链接/限时话术是什么
- 画面关系：谁是主角、谁是同事/路人、哪些人物必须删除或弱化
- 屏幕文字：原片字幕/花字里承载了哪些剧情信息

### 0c. 输出剧情分析

写入 `<视频名>_复刻/视频分析/原视频剧情分析.md`，至少包含：MCP 原视频分析、逐段剧情、原始口播、说话方式、字幕/花字、复刻策略、产品身份确认、产品可见形态特征、禁止误生成、新产品卖点如何套入原片话术。护肤/美妆类还必须写明使用前问题、使用中动作、使用后改善点和前后对比镜头，并按 `references/skincare-beauty-replication.md` 记录擦掉/洗净动作、同期声/旁白判断和口播时长风险。

**常见错误：**
- 只写“你看这个产品很好吃/很好用”，丢掉原片的冲突和反转。
- 只看分镜不看字幕，导致口播和剧情错位。
- 有 MCP 可用时不用 MCP，导致漏掉原始口播和语气。
- 把原片剧情改成普通带货脚本。
- 把产品图粗看成“肉块/零食”，导致后续改图、口播、Seedance 全部偏离真实产品。

## 步骤 ①：拆解分镜

### 10. 先决定复刻长度

不要默认按原视频全长生成。先按用户目标决定：

| 用户目标 | 分段策略 |
|---|---|
| 直接完整复刻 | `groups = ceil(原视频时长 / 15)` |
| 用户要求“不缩减，原视频多少秒做多少秒” | 原片 `>40s` 默认放弃或先请用户确认；`≤40s` 按 15s 切分，尾段按剩余口播长度生成 |
| “缩到30秒 / 做30秒小剧情” | 固定2组，每组15秒；从原片均匀抽24帧，压缩剧情骨架 |
| “做15秒短版” | 固定1组；保留钩子、核心卖点、转化收口 |
| 纯氛围空间展示≤15秒 | 固定1组，可保留BGM |

30秒压缩不是机械截取前30秒，而是复刻原片整体节奏和内容：开场钩子、核心冲突、证明/卖点、行动收口都要出现。

完整复刻时也不要机械压尾段。例如原片 37.7s，可做 `15s + 15s + 7.7s`；如果尾段台词容易没说完，可以把最后一段放到 8s 左右，给 0.3-1.0s 容错，但不要改剧情顺序。

### 1a. 先取完整镜头流

视频 ≤15 秒时，直接取 12 帧、分 1 组，跳到步骤②。

视频 >15 秒时，**先取完整镜头流，不要直接分组**：

```bash
# 先取完整帧（不分组），用于找安全缝点。
# 在 loop kit 里优先用 tools/build_part_storyboards.py，确保横屏源视频不会被挤成竖屏。
python3 tools/build_part_storyboards.py \
  --input "<视频路径>" \
  --output "<输出目录>/storyboard_source_refs" \
  --total-frames 24 \
  --groups 1
```

这一步输出 24 帧的完整网格图和单独帧，用于下一步审查。

### 1b. 安全缝点审查（>15秒视频必做）

> **核心原则：不允许机械地按时间一刀切。必须先看完整镜头流，再在 13.5s–16.5s 区间找最适合衔接的安全缝点。**

看完整网格图，找 15 秒附近（第11-14帧，对应约 13.5s-16.5s）的内容：

**安全缝点优先级（从高到低）：**
```
产品特写 > 手部动作 > 桌面平铺 > 包装开合 >
食物夹取 > 杯面按压 > 肩带拉伸 > 后扣展示 >
衣领整理 > 外搭B-roll > 人物侧脸半身
```

**禁止把缝点放在：**
- 人物正脸口播（嘴型明显在说话中间）
- 总结推荐句（"赶紧下单"类收尾）
- 重新开场句（"今天给大家推荐"类开头）
- 场景切换过大的镜头

**审查四个问题：**
1. Part1 最后一镜是不是人物正脸口播？→ 不合格
2. Part2 第一镜是不是重新开场？→ 不合格
3. Part1 最后一镜和 Part2 第一镜是不是同一产品/同一动作/同一场景？→ 必须是
4. 15s 边界附近有没有产品特写/手部动作/B-roll 可以藏缝？→ 必须有

**合格标准：** Part1 最后一格和 Part2 第一格，看起来像同一个产品、同一个场景、同一个动作的连续两帧。如果看起来像"一个视频结束了，另一个视频重新开始了"，就是不合格。

### 1c. 微调镜头归属

如果 15 秒正好切在不合格位置，**不改原视频镜头顺序，只改镜头归属**。把安全缝点帧复制到两边：前一 Part 以它收尾，后一 Part 从它开始。

### 1d. 按安全缝点重新分组

确定好缝点位置后，重新跑脚本分组：

```bash
python3 tools/build_part_storyboards.py \
  --input "<视频路径>" \
  --output "<输出目录>/storyboard_source_refs" \
  --total-frames 24 \
  --groups 2
```

**画幅硬规则：** 分镜参考图必须保留源视频画幅。横屏源视频的每个 panel 必须仍是横屏，不能为了套用竖屏模板强行变成 9:16、3:4 或竖向小格。只有用户明确要求“横转竖/竖屏投放”时，才在后续单独制定竖屏适配方案；复刻阶段默认按源片画幅走。

> 如果脚本不支持自定义分割点，就手动把单独帧分到 `Part1_单独帧/` 和 `Part2_单独帧/` 目录。
> 缝点帧复制到两个目录里：Part1 最后一帧 = Part2 第一帧（或高度相似的连续帧）。

**分组数规则：**
- Seedance 单段最长 15 秒，默认 `groups = ceil(视频时长 / 15)`。
- 最后一段不必强行 15 秒；按剩余剧情和口播长度设置 `duration`，可加 0.3-1.0s 余量让台词说完。
- 每组默认 12 帧，因此 `total_frames = groups * 12`。
- 例如 57.7 秒视频应拆 4 组、48 帧，而不是固定 3 组 36 帧。
- 用户明确要求更多/更少帧时，再按用户要求调整。

**输出：**
- `PartX_单独帧/` — 单帧图，喂给图像生成/改图步骤
- `分镜_PartX.jpg` — 网格总览图，看整体节奏

## 步骤 ②：全 Part 批量改图（默认）

> **GPT Image 默认路线：只用 Matpool GPT-Image-2。** 调用 `.agents/skills/video-replication/scripts/generate.py`，通过 `MATPOOL_API_KEY` 鉴权，参考图用本地文件 multipart `image` 字段提交。不要尝试任何废弃 GPT Image 路线或网关探测。

这是整个流程的视觉核心。默认**不要先跑小样**；storyboard 通过后，按目标时长一次性改完全部 Part 分镜。30 秒通常直接改 Part1/Part2，45 秒通常直接改 Part1/Part2/Part3。小样只在用户明确要求“先看小样/做到小样停/只试一张”或新产品形态风险极高时作为可选路线。图像参考角色必须来自 `output/<job-id>/product_profile.json`，不要把旧泥膜 SKU 的参考顺序套到新产品上。

### 2a. 参考图顺序

调用 GPT Image 前，先读取 `references/codex-imagegen-direct.md`。该文件名为历史兼容名，内容是 Matpool GPT-Image-2 direct edit 操作页。

Matpool 路线：把分镜图、product profile 声明的产品图/材质图、人物图作为真实本地图片输入，提示词里明确每张图的职责。输出后保存到当前 stage 的 `output/<job-id>/...` 目录，并记录 `image_route=matpool_gpt_image_2_edit`。只有保存后的当前 job 目标分镜图才能登记为 `AI改好分镜图`。

**Matpool direct edit 原则：** 同一份源 Part 分镜、同一批 profile-declared 产品/材质/人物/洗后脸参考、同一份最终改图 prompt、同一张源分镜比例、同一档质量目标。Matpool 必须按 edit/reference 合同执行，不得重新发挥成 text-to-image。

同时必须写 `codex_imagegen_contract.json`。这个文件要记录：
- `api_effect_baseline.source=matpool_gpt_image_2_edit`，并写明 `preserve_api_route=true`
- `matpool_uses_real_image_inputs=true`
- Matpool 本轮实际使用的 prompt path；该 prompt 应复用或等价于 API 改图 prompt，不能写成只给人看的说明
- Matpool 本轮实际使用的 `quality`、`size`；应与源 Part 分镜比例匹配
- 实际提交的图片角色：源 Part 分镜、product profile 要求的产品/材质参考、身份图、洗后脸图（如用）
- 源分镜只传递：layout / shot_order / framing / action_rhythm / scene_family
- 源分镜不传递：old_product / old_tool / old_host_identity / old_mud_color / subtitles
- 每个 Part 的 prompt、candidate、source_risks、required_translations、checker_visual_review
- 对 clay-mask profile：旧管/棒/刷/手臂试色只允许转译成手指取罐内白泥、指腹上脸；其他 profile 必须转译成当前产品的真实动作

Matpool 出图前必须显式执行这个输入映射：

| Matpool 输入 | 作用 |
|---|---|
| `-i "<原始分镜故事板>"` | 源 Part storyboard；只传 layout / shot_order / framing / action_rhythm |
| `-i "<产品参考图>"` | product profile 声明的产品/材质图；锁当前包装、标签、形态、材质和真实使用动作 |
| `-i "<人物参考图>"` | 身份/模特图；默认锁同一人物脸、发型、年龄感、身份一致性、身体外观和服装 |
| `--quality medium --size "<源Part分镜图画布比例或像素尺寸>"` | 按源分镜画布比例执行 |
| `matpool_gpt_image_2_edit` | 必须当作 edit/reference 任务，不得当成纯文生图或风格海报 |

如果 Matpool 做不到上述映射，结论是 `FAIL` 或 `STOP`，不是切到废弃 API，也不是降低现有成品标准。

在 loop kit 里，image batch PASS 前还要运行；如果用户显式走 image sample，sample 也要运行同类检查：

```bash
python3 tools/codex_imagegen_contract_qc.py --root . --job-id <job-id> --stage image_sample
python3 tools/codex_imagegen_contract_qc.py --root . --job-id <job-id> --stage image_batch_qc
```

常用顺序：

```bash
# A/B/C 复刻网格整图，用于每个 Part 的完整 storyboard 改图
-i "<原始分镜故事板>" \
-i "<产品参考图>" \
-i "<女主自拍参考图>"
```

如果女主身份不稳定，改用身份优先验证：

```bash
-i "<女主脸部身份参考>" \
-i "<原始分镜故事板>" \
-i "<产品参考图>"
```

**经验：** 女主图放第一张不总是更好。若目标是保留 12 格故事板结构，A=原分镜、B=产品、C=女主，再用提示词明确 A/B/C 角色，常比“女主第一”更稳。若小脸不像，再裁前 6 格做身份验证。

**指定主播经验：** 如果用户提供厂家视频或指定主播截图，先从中选/确认一张自然表情、正脸清晰、发型服装符合目标的主身份图。不要擅自用夸张表情、眨眼、低头、嘴型奇怪或带强字幕遮挡的帧做主身份图。若用户指出“这张表情怪”，立刻停掉当前改图任务，换用户指定图重跑。

当产品图多于一张、人物图也要传时，优先把产品图合成一张产品参考，形成 3-ref 批量改图输入：

```bash
-i "<原始分镜或干净分镜>" \
-i "<产品合成参考图>" \
-i "<指定主播主身份图>"
```

### 2b. 默认直接跑全部 Part

默认按 storyboard manifest 里的 Part 列表直接跑完整批量：
- 15 秒：直接跑 Part1。
- 30 秒：直接跑 Part1、Part2。
- 45 秒：直接跑 Part1、Part2、Part3。
- 更长视频：按 `ceil(目标时长 / 15)` 直接跑所有 Part。

每个 Part 都是完整 12 格 storyboard 改图。不要为了确认方向先只改前 6 格；如果某个 Part 失败，只修失败 Part 或失败面板，已通过 Part 锁定不重跑。

推荐参数：

```bash
--quality medium --size "<源Part分镜图画布比例或像素尺寸>"
```

`job-001`/`job-002` 这类竖屏源片可以继续用 4 列 x 3 行、接近 `3:4` 的 12 格 storyboard 画布；横屏源片默认使用 3 列 x 4 行的横向 panel storyboard，不得强行套 `3:4`，也不要做成过长的 4 列 x 3 行宽条。

**常见错误排查：**

- Matpool 返回资源或尺寸错误 → 先按源分镜比例换成明确像素尺寸，例如 `1024x1536`，再按 `medium → low` 质量降级；只有明确质量不足时才升到 `high`。
- 图片文件被上游拒绝或疑似元数据问题 → 用 Pillow 重新编码图片去掉元数据后仍走 Matpool 本地 `image` 字段：
  ```python
  from PIL import Image
  img = Image.open('分镜_Part1.jpg')
  img.save('/tmp/part1_clean.jpg', 'JPEG', quality=90)
  # 然后 -i /tmp/part1_clean.jpg
  ```
  不要改成任何废弃 GPT Image 路线或网关探测。

### 2c. 身份/多女主检查

看图后必须检查：
- 如果用户指定了女主参考、要求“唯一女主”，或原片多女主会干扰主角，才检查是否只有一个清晰女主。
- 如果用户没有指定女主，只是要求人物全部替换/洗图，不要强行写“只保留一个女主；其他前景女性删除/替换成男同事/背景虚化”。这会改变原片人物关系。默认应全面替换原片人物身份，同时保留原片多人关系和镜头节奏。
- 检查原片人物是否都被新人物替换，是否还残留原人物脸。
- 产品包装是否一致。
- 字幕/花字是否清掉，但 Shot 标签是否保留。

如果用户提供了指定女主而前几格不像：不要继续批量跑。调整提示词，明确女主在各镜头中的位置；只有在需要唯一女主时，才写“其他前景女性删除/替换成男同事/背景虚化”。

批量候选通过基础视觉检查时，必须更新 `output/<job-id>/visual-assets/approved_visual_manifest.json`，并运行：

```bash
python3 tools/visual_asset_manifest_qc.py --job-id <job-id> --stage image_batch_qc
```

没有通过 visual asset manifest QC 时，不要记录 image batch 的 `PASS`。

读取 `references/replication-lessons.md` 获取本轮验证过的 ABC 提示词和排错策略。

## 步骤 ③：快修 / 局部重试

初次全 Part 批量改图后，只对失败 Part 或失败面板做 Matpool GPT-Image-2 快修。不要因为一个局部失败重跑全部 Part。每次快修仍然是源 storyboard edit/reference 任务，一次完成：
- 替换人物（指定女主/主角）
- 替换产品（指定包装/食物/道具）
- 去除字幕（干净画面，只保留构图和动作）

> **⚠️ 默认先改网格图，不改单帧。** 但如果人物身份在远景格一直不稳，允许裁前半段/后半段小网格，或改关键单帧做局部修复。

> **快修优先：** 已经通过的 Part 不要因为局部问题重跑。一个或两个面板失败、泥膜颜色偏差、产品标签弱、洗后脸参考不合格时，只修该图/该面板/该材质变量。快修最多先跑 1 次，仍失败再做 1 次针对性重试；不要盲目第三次。

### 改图提示词模板

读取 `references/rewrite-prompts.md` 获取完整的提示词模板和示例；读取 `references/replication-lessons.md` 获取身份一致性和多女主排错模板。

分镜网格改图提示词必须写清：图1只保留构图/顺序/动作/排版，图2锁产品，图3锁人物；保留镜头节奏；替换人物和产品；清除字幕花字；保留 Shot 编号。食品要写可见形态和禁止误生成项。

护肤泥膜类的 ImageGen 提示词必须是正向目标画面，不要把旧片的“泥膜棒、棒状涂抹头、刷头、棉签、手臂试色、管状挤出”等词写进提示词。应写成：白色方圆罐在手边或近景可见，手指从开盖罐内挑起乳白厚泥，用指腹涂到脸部对应位置，源分镜里的旧工具动作只保留镜头功能和节奏。

### Matpool GPT-Image-2 改图命令

> **⚠️ VS Code / 非交互终端**：终端不读 `.zshrc`，`MATPOOL_API_KEY` 不会自动加载。每次运行改图命令前确认变量存在：
> ```bash
> printenv MATPOOL_API_KEY >/dev/null && echo OK
> ```

> **⚠️ 变量名**：不要用 `PROMPT` 作为存放提示词的变量名——在 zsh 里 `PROMPT` 是保留的 shell 提示符变量，赋值多行字符串会污染终端显示。改用 `EDIT_PROMPT` 或 `IMG_PROMPT`。

统一使用：

```bash
python3 .agents/skills/video-replication/scripts/generate.py \
  --prompt-file "<提示词.txt>" \
  -i "<分镜>" \
  -i "<产品>" \
  -i "<人物>" \
  --quality medium \
  --size "<源Part分镜图画布比例或像素尺寸>" \
  --file "<输出目录>/part1_matpool.png"
```

**说明：**
- `--size`：必须匹配源 Part 分镜图画布比例或明确像素尺寸；`3:4` 只适用于竖屏源片的 12 格分镜网格
- `--file`：指定最终保存文件
- 多张参考图重复 `-i`，顺序保持源分镜、产品、人物、洗后脸
- 不允许切到任何废弃 GPT Image 路线或网关探测

**关键原则：**
- 改网格图，不改单帧
- 不改镜头语言（构图、角度、景别）
- 只换内容（人、产品、文字）
- 保持与原分镜的视觉节奏一致
- 批量阶段最终 promoted Part 图必须登记为当前 job `AI改好分镜图`；不能用 Python/PIL 拼图、源视频节奏板、contact sheet、裁剪源帧、旧 job 分镜或 validated anchor 拼图代替。

## 步骤 ③b：改图审核（必做）

每张 Part 改图后先审核，不合格就修提示词重跑，不要继续写口播或 Seedance。

审核结果写入 `<视频名>_复刻/改图审核.md`，至少检查：

- **产品身份**：是否是用户产品，而不是视觉工具误称的泛化类别。食品类要写清形态证据，例如鸭脖/鸡脖的骨节、骨孔、截面、纤维、调料颗粒。
- **产品一致性**：所有镜头里的产品是否同一类，不能 Part2/Part3 被污染成 Part1 或其他产品。
- **人物一致性**：主角是否同一张脸、同一发型、同一妆容；原人物脸和原人物衣服是否残留。默认完整换人，衣服必须跟模特图；只有用户明确说 face-only 或保留原衣服时才不锁衣服。
- **跨 Part 连续性**：Part1 和 Part2 是同一条视频的连续切片，不是两张独立海报。相邻 Part 必须同一身份、同一目标服装体系、同一场景体系、肤色光线接近、产品和泥膜质感一致；衣领、袖型、外套、发型或场景明显变化时不能通过，除非原片剧情明确换装/换场景并在 Seedance 提示词里承接。
- **分镜结构**：是否保留原镜头顺序、每格构图、动作关系和 Part 节奏。
- **文字清理**：中文字幕、口播字幕、花字、水印是否清掉；只保留需要的 Shot 编号。
- **手部动作**：开袋、拿产品、试吃、指向、陈列是否自然。
- **护肤前后对比**：护肤/美妆/泥膜类必须检查使用前和使用后是否形成电商对比。使用后皮肤要比使用前更亮、更均匀、更细腻、更干净，闭口、粗糙、暗沉、油光要减少；不能只是脸被水打湿或灯光变亮，也不能塑料磨皮到失真。
- **洗后参考时序**：洗后亮肤参考只能影响清洗/擦净之后的证明镜头。洗前或正在涂抹阶段不能已经像洗后一样白净、发亮、细腻；否则就是 after-wash reference contamination，必须回图像阶段修。

产品不稳时的修法：

1. 不要只加“更真实/更好吃”；改写为结构性形态约束。
2. 为产品做近景 crop，作为额外参考图，锁住骨节/孔洞/截面/纤维等特征。
3. 明确禁止误生成列表，例如“不要普通肉块、圆墩肉、方块肉、牛肉干、排骨、肉丸、鸭翅、鸡翅、辣条”。
4. 只重跑失败的 Part，已合格 Part 不要一起重跑，避免新污染。
5. 最终把合格四张图复制到一个 `最终改图/` 或 `最终改图四张/` 文件夹，方便后续 Seedance 使用。
6. 如果已经存在 `final-images/`、`seedance/seedance_refs/` 或 `seedance_web_final/`，快修通过后必须同步替换这些最终位置，旧图移入 `deprecated_*`，避免用户拿错图。
7. 更新 `output/<job-id>/visual-assets/approved_visual_manifest.json`，登记 Part 图、产品组、身份组和 after-wash 组绑定，然后运行：
   ```bash
   python3 tools/visual_asset_manifest_qc.py --job-id <job-id> --stage image_batch_qc
   ```
   QC 不通过时，不能继续写口播、Seedance 提示词或请求。

指定主播/指定产品项目的额外审核：

- 主播是否像用户指定截图，而不是“相似网红脸”或随机 AI 美女。
- 主播表情是否自然；不要把怪表情参考图继续带到 Seedance。
- 产品色号/包装是否以用户最新素材为准；例如用户从豆沙粉棕改成亚麻灰棕后，所有口播、改图、Seedance 都必须同步改成亚麻灰棕。
- 旧产品是否完全清除。若原片是面膜，不能残留面膜袋、面膜布、护肤品证明板；需要改成染发膏调配、刷发束、发色展示等对应动作。
- 护肤效果参考图是否准备好。若产品卖点依赖“洗后变好”，必须做一张同一模特的洗后更好皮肤参考图，供图像改图 / Seedance 在洗后镜头使用。

## 步骤 ④：写口播文案

基于步骤⓪的视频剧情分析、原片字幕/话术、改图后的分镜节奏，写一段 30 秒口播文案。

### 口播结构

```
前3秒：复刻原片钩子（冲突/问题/反差）
Part1（约12-15秒）：复刻原片场景推进和卖点引入
Part2（约12-15秒）：复刻原片证明/福利/行动号召
```

### 写作要求

- 按原片剧情和分镜动作节奏写，每句话对应一个镜头
- 多人场景必须标清每句话是谁说的：女主、同事A、同事B、群体反应、画外音；不要只写一条没有角色归属的口播
- 如果原片是“同期声制造冲突 + 画外音讲卖点”的混合结构，复刻文案也必须保留这种声音分工
- 口语化，不要书面语
- 前3秒必须继承原片钩子，不要另写无关开场
- 总字数控制在 150-200 字（30秒语速）
- 标注每句话对应的镜头编号
- 保留原片的叙事功能：冲突、反转、卖点、价格/福利、收口；只替换产品和人物

读取 `references/voiceover-templates.md` 获取更多口播模板和示例。

护肤/美妆/泥膜类还要读取 `references/skincare-beauty-replication.md`，检查替换后的品牌/产品名是否超出原句时长；品牌名说不清时，优先缩短产品名，不要硬塞全称。

## 步骤 ⑤：缝点设计

> **核心原则（来自分镜焚决）：每个15秒Beat都不是独立短视频，而是长片中的一个连续切片。每个Beat必须默认继承上一Beat最后一帧的空间状态。**

只有一组分镜（≤15秒视频）时跳过此步。有2组以上时必做。多于2组时，对每个相邻边界都写：Part1→Part2、Part2→Part3、Part3→Part4……

### 4a. 看缝点帧

看每个相邻边界的前一 Part **最后2帧**和后一 Part **前2帧**，判断缝点内容。建议生成一张 `缝点审查图.png`，把每个边界的 4 帧放在一起看。

```
Part1 最后2帧的内容：
├── 有产品在手上 → 产品对位切（推荐度最高）
├── 正脸在说话   → B-roll藏缝（把口播尾音压到产品细节上）
├── 手在操作产品 → 动作桥（延续同一动作方向）
└── 都不是       → 默认用产品对位切
```

### 4b. 确定继承状态

从 Part1 最后一帧提取并记录：
- 人物朝向（面左/面右/正面）
- 产品位置（手上/桌面/画面哪个区域）
- 手的姿态（举着/捏着/放下中）
- 构图（中景/近景/特写，产品占画面比例）
- 光线方向
- 边界动作（收手、合盖、转身、水声、擦脸、拿起产品等连续动作）

### 4c. 口播断句检查

- 缝点前 200ms 口播必须已收句，不要把嘴型拖到最后一帧
- 缝点后 300ms 才开新句
- 每15秒只放 2-3 句，不要每镜一句
- 如果缝点帧是正脸说话，把口播尾句压到 B-roll 上（L-cut）
- 带参考音频时，以 ASR 时间戳为准切分音频：上一段最后一句结束后可留静音/环境声，但最终文件必须 `<=15.00s`，推荐 `14.90s`；下一段从新句开始。提示词最后半秒也要写成收手、合盖、环境声或动作声，不要写“继续说话”。

### 4d. 输出缝点方案

记录到口播文案同一文件里；复杂项目也单独写 `<视频名>_复刻/缝点设计.md`。每个边界都用这个格式：

```
## 缝点设计

### PartX → PartY

缝合方式：[产品对位切 / B-roll藏缝 / 动作桥]

PartX 结尾状态：
- 画面：[具体描述最后一帧]
- 产品位置：[手上/桌面/画面位置]
- 手的姿态：[举着/捏着/放下中/正在操作]
- 构图：[中景/近景/特写，产品占比]
- 光线方向：
- 口播：[最后一句在哪个时间点收住]

PartY 起始要求：
- 画面：[继承什么，用哪个连续动作接上，什么时候开始新动作]
- 口播：[新句从什么时间点开始]
```

**常见错误：** 只写“产品对位切/动作桥”一句话，不写结尾状态、起始继承、口播收句时间。这不算完成缝点设计。

## 步骤 ⑥：生成 Seedance 提示词

把视频剧情分析 + approved visual manifest 里的改好分镜图 + 口播文案 + 缝点方案，整理成 Seedance 2.0 可直接用的提示词。

### Seedance 约束条件

- **比例：** 默认匹配源视频/用户 brief 的目标画幅；只有用户明确要求竖屏投放时才写 9:16 竖屏
- **时长：** 每段 15 秒
- **画面：** 无字幕、无水印、无分镜黑底排版
- **一致性：** 同一段内同一人物/产品/场景
- **输入：** 只使用 approved visual manifest 里的素材：`01` 当前 job `AI改好分镜图`，`02/03` 同一产品组，`04/05` 同一身份组；不能只靠文字描述产品/人物
- **剧情映射：** 最终提示词必须从剧情分析、ASR/字幕、画面时间线、分镜表和口播文案推导；先写 shot-line map，再写 `Shot 1/2/3`。不能只看 approved storyboard 或产品图直接编一个通用广告。
- **护肤效果：** 护肤/美妆/泥膜类必须输入洗后皮肤更好参考图，并在提示词中写清“只在洗净/擦净后的镜头使用”。使用后要比使用前明显更亮、更干净、更细腻，闭口和粗糙感减少。
- **声音归属：** 多人视频必须在每个时间段写清楚由谁开口（女主/同事/画外音/群体反应），不能把所有台词写成同一个人的连续口播
- **说话人层级：** 每句台词都必须标注为画外音旁白、画面内同期口播、配角同期声或群体反应。产品/手部/手机证明镜头默认人物不张口，台词走旁白；同期口播只放在稳定人脸镜头。
- **产品引用：** 产品参考图只锁产品身份和可读标签，不锁构图或背景。产品特写段必须写成真实手持、倒掌心、轻推、轻拍、台面触地等源节奏动作，不能让白底产品图或棚拍 packshot 变成镜头。
- **交付形式：** 必须给出每个 Part 可直接复制到 Seedance 的独立提示词块，不要只写说明文档或摘要。

### 6a. 从剧情分析推导最终提示词

读取 `references/seedance-20-prompt-standard.md`，按其中的 `剧情分析 -> 最终提示词` 标准执行。最小可交付中间产物是一个 shot-line map：

```text
Part / target time
source time
source visual action
source line and speaker mode
target visual action
target line and speaker mode
reference binding
must-keep reason
```

写 prompt 时逐行消化这个 map：开场冲突、场景转换、第一人称操作、产品名/标签证明、质地/使用动作、脸部状态证明、手机/社交证明、福利收口等源片落点，必须各自进入对应 `Shot`。如果某个源落点不适合当前产品，要在 target visual action 中翻译成 product profile 的真实使用动作，而不是删掉。

### 6b. Seedance 生成前路由

写提示词前，先在 `seedance_素材角色表.md` 里完成三件事：

1. **选择生成模式：** 纯文生视频、参考图生视频、真人素材库、参考音频、首尾帧、视频参考动作、纯文字避污染。每个 Part 只能选一个主模式，其他素材只做辅助。
2. **素材角色绑定：** 给每个素材一个主角色，并写清排除项。基础顺序来自 product profile：`图片1=当前 job AI改好分镜图，只传递镜头顺序、构图、动作和场景关系；图片2=产品主参考，锁包装/标签/形态；图片3=profile 要求时的产品材质/开盖参考；图片4=身份/模特图，锁同一模特脸/发型/身份/身体/服装；图片5=profile 要求时的同身份组洗后脸，只在洗净/擦净后的证明镜头使用；音频1=声音节奏，只传递语速、停顿和直播感，不照搬旧台词。`
3. **单段预算分配：** 每个 Part 先决定主保什么：产品还原 / 人物身份 / 动作节奏 / 场景氛围 / 口播声音。只能选一个主目标、一个次目标，其余主动简化。不要让同一段同时追求完美人脸、大幅动作、复杂场景、细小产品细节和长口播。

常用决策：

| 场景 | 主目标 | 次目标 | 简化项 |
|---|---|---|---|
| 电商产品特写 | 产品还原 | 手部动作 | 背景、多人互动 |
| 指定主播口播 | 人物身份 | 声音节奏 | 大幅肢体动作、复杂场景 |
| 前后对比护肤 | 效果对比 | 人物一致 | 背景变化、道具数量 |
| 氛围空间展示 | 场景氛围 | 镜头运动 | 人脸细节、长口播 |

### 6c. Seedance 参考图处理

- Seedance 参考图必须来自 approved visual manifest，不直接喂带旧产品、旧人物、字幕、水印、黑底排版的原片分镜。
- 进入 Seedance 前，只能整理/复制已批准的 `AI改好分镜图`、产品组图、身份组图到 `seedance_refs/` 或 `seedance_web_final/`。不要裁剪源视频帧、源分镜 panel 或旧 job 图片来充当新素材；洗后脸必须是同身份组专门生成的脸部特写。
- 产品要求高时，产品图必须作为独立素材传入；产品特写、开盖、涂抹、试吃、包装靠近镜头的时间段，要在提示词里再次绑定产品图。
- 真人脸、自拍、指定主播、含真人脸的最终改图分镜，默认走 Apifox 文档 taskCode 接口的人脸检测版本；所有参考素材必须先变成公网 `http(s)` URL。非真人分镜/产品/场景图也用公网 URL 作为 `reference_image`。
- 参考图含医疗、旧品牌、敏感场景或强污染元素时，不要硬传图，改成纯文字或先做图像清洁图。

### 缝点写进提示词的方法

**每个前一 Part 的边界时间段，必须追加：**
- 结尾用缝点文档记录的手部/产品/水声/擦脸/合盖等连续动作收住
- 口播提前收住，末尾只留真实动作声或环境声过渡

**每个后一 Part 的开头时间段，必须追加：**
- 开头继承上一段结尾位置、光线和人物朝向
- 先用连续动作接上，再自然开口，避免第一帧直接变重新开场或停住不动

### 提示词结构

读取 `references/seedance-prompts.md` 获取完整的 Seedance 提示词模板和已验证案例。生成前还要读取 `references/seedance-qc-gates.md` 做提示词洁净、参考图、音频边界和成片质检。护肤/美妆/泥膜类还要读取 `references/skincare-beauty-replication.md`，按里面的参考图顺序、无字幕格式、上半身身份图、紧裁产品图和洗后脸图规则写提示词。

15秒 Seedance 2.0 / ordinary 2.0 / mini 的最终 prompt 标准以 `references/seedance-20-prompt-standard.md` 为准；该标准包含 2026-07-03 `孔凤春发酵水` 成功样本经验：剧情分析映射、说话人层级、产品参考图身份绑定、无二选一镜头落点、正向运动约束、以及局部失败时只改一个变量的微调策略。

写 Seedance 提示词或请求前必须运行对应阶段的 visual asset manifest QC：

```bash
python3 tools/visual_asset_manifest_qc.py --job-id <job-id> --stage seedance_prompt
python3 tools/visual_asset_manifest_qc.py --job-id <job-id> --stage request_qc --check-final-dir
```

Seedance 交付必须包含：

- Part1/Part2/Part3... 每段一个独立 fenced `text` 块。
- 每段都是独立任务，必须在本段内完整写人物、产品、场景和 @图片绑定；不能依赖上一段上下文。
- 人物设定、产品设定、场景设定、视频要求。
- 按关键动作写可变时间轴，例如 `0.0-2.4秒`、`2.4-5.7秒`；每个分镜里的关键动作必须在对应时间段出现，不要求机械每 1 秒或每 3 秒一段。
- 禁止项写清：无字幕、无标题条、无说明文字、无贴纸、水印、logo、分镜边框、黑底排版、Shot编号。
- 多段衔接要求写进相邻段的结尾/开头，而不是只写在单独缝点文档里。

### 30秒压缩提示词规则

30秒视频必须写成两个独立15秒提示词：

- Part1：开头0.3秒可以直接进入，不要做完整片头；最后0.5秒收句并保留自然环境声。
- Part2：开头严格继承Part1最后的空间、人物、产品和光线，用同一动作自然接上，再开新动作。
- 护肤/美妆/泥膜类的 Part2 通常承接洗脸/擦脸/效果展示，必须把洗后更好皮肤参考图写进 6s 之后的脸部展示镜头：肤色更亮，脸颊和鼻翼更干净，闭口和粗糙感减少，但保留真实皮肤纹理。
- 两段都写“禁止BGM、禁止配乐、禁止音乐铺底、禁止鼓点”。
- “卡点”改写为动作卡点、灯光卡点、台词停顿点、操作音卡点，不写音乐卡点。
- 如果用户提供厂家声音参考，提示词必须写“参考音频只用于模仿声音质感、语速、直播感和停顿，不照搬旧台词”，并按每段 15 秒传对应音频。
- 如果用户后期要统一配音/配乐，额外导出静音保险版。

## 步骤 ⑦：Seedance 直接生成

当用户要“最终得到一个视频”时，不要只交付提示词。优先直接调用 Seedance 生成、下载、验证。

### 默认模型路由

viral-replica-loop 的默认视频生成模型只改 EP，不改流程：

```json
{
  "model_name": "SD 2.0 mini",
  "model": "ep-20260625155850-zpss5"
}
```

在 loop kit 里以 `rules/SEEDANCE_MODEL.json` 为准。所有 taskCode/API request draft 的 `model` 字段必须是 `ep-20260625155850-zpss5`，并用 `tools/request_body_qc.py --model-route-config rules/SEEDANCE_MODEL.json` 校验。不要因为切换到 SD 2.0 mini 而改故事分析、分镜、改图、口播、缝点、提示词结构、音频边界、成本审批或 final QC。

### 真人脸 / 人物身份参考图（默认走文档 taskCode 接口）

只要 Seedance 最终生成里要引用真人脸、自拍、人像身份图、换人主角图，默认使用 Apifox 文档里的无界任务接口：

```
真人图本地文件 → 上传到 https://api.qinmiao.space/uploads/... → task_create(taskCode=2509) → task_info 查询结果
```

使用文档接口 helper：

```bash
source "$HOME/.config/wujieai/env"
python3 ~/.codex/skills/seedance/scripts/seedance.py \
  --prompt-file "<Part提示词.txt>" \
  --images "https://api.qinmiao.space/uploads/.../person.png" \
  --image-role reference_image \
  --task-code 2509 \
  --model ep-20260625155850-zpss5 \
  --output "<输出Part.mp4>" \
  --ratio 9:16 \
  --duration 15 \
  --resolution 720p \
  --generate-audio \
  --poll-interval 10 \
  --max-wait 5400
```

如果项目明确使用小厂人脸检测渠道，可改为：

```bash
--task-code 2508
```

多人真人参考时，提示词和图片顺序必须一一对应：

```text
人物A对应图片1，人物B对应图片2。
人物A面部：参照图片1，五官、脸型、发型、年龄感百分百还原，杜绝美化。
人物B面部：参照图片2，五官、脸型、发型、年龄感百分百还原，杜绝美化。
```

命令中也保持同样顺序：

```bash
--images "https://.../person_a.png" "https://.../person_b.png" --image-role reference_image --task-code 2509
```

注意：
- Seedance 不能直接吃本地真人图路径，必须先变成公网 URL。
- 真人脸必须先走素材库：本地真人图先上传公网 URL，再创建并确认 Pixmax material-library asset 为 `Active`，最终 taskCode=2509 请求使用 `asset://asset_id` 且 `role: reference_image`。
- 当参考图多且公网 URL/混合引用导致上游失败时，允许把分镜图、产品图、身份图全部转成 Active Pixmax `asset://...`，仍通过 taskCode=2509、`role: reference_image`、mini EP 提交。这是 Magic Mirror 已验证路线；Fast 与 mini 只替换 `model` EP，不改变素材库打法。
- `/seedance/ai_router` 只作为用户明确指定或 taskCode 路线确认不可用时的 fallback。

### 指定主播 + 产品 + 声音参考（稳妥版）

当用户要求“用厂家指定的人物和声音”“产品也要还原”时，使用稳妥版，不要直接纯文字 Seedance：

1. 从厂家视频抽帧，挑/确认一张主身份图；用户给截图时，以用户截图为准。
2. 抽厂家声音参考，但不要用整段长音频；每个 15 秒 Part 单独切一条音频。切音频时按转写句子边界，不按机械 15.00s。句子提前结束时补静音/环境声到目标时长，避免相邻 Part 台词重叠。
3. 用图像改图先把原片分镜改成“指定主播 + 新产品 + 去字幕”的干净分镜；项目默认使用 Matpool GPT-Image-2 路线。
4. Seedance 输入顺序建议固定：
   - `图片1`：对应 Part 的最终改图分镜
   - `图片2`：产品参考图或产品合成参考图
   - `图片3`：指定主播主身份图
   - `音频1`：对应 Part 的 15 秒声音参考
5. 带真人的分镜/主播图必须使用 taskCode=2509 或按项目指定用 `2508`。真人身份图必须先变成 Active Pixmax `asset://...` 再以 `reference_image` 传入；产品图/分镜图可用公网 URL，若混合路线失败或需要与 Magic Mirror 保持一致，则也转成 Active `asset://...` 再提交。

生成前必须保存并检查：

- `reference_audio_partX.mp3`：每段实际传给 Seedance 的音频。
- `reference_audio_partX_asr.txt/json`：每段音频的 ASR 结果。
- `音频边界质检.md`：写明每个 Part 的起止句、实际切点、是否补静音、相邻段是否无重复。

命令和音频限制见 `references/identity-audio-seedance.md`。

### 非真人参考图 / 分镜图 / 产品图

只有当参考图不是真人脸，例如分镜图、产品图、场景图、干净改图网格，才使用 Magic Mirror Seedance runner。它会把本地图上传到 `https://api.qinmiao.space/uploads/...`，再作为 `reference_image` 传给 Seedance：

```bash
source "$HOME/.config/wujieai/env"
python3 ~/.codex/skills/seedance-magic-mirror-video-prompt/scripts/run_seedance_magic_mirror.py \
  --prompt-file "<Part提示词.txt>" \
  --image-file "<分镜或参考图.jpg>" \
  --output "<输出Part.mp4>" \
  --model ep-20260625155850-zpss5 \
  --ratio 9:16 \
  --duration 15 \
  --resolution 720p \
  --generate-audio \
  --image-role reference_image \
  --poll-interval 10 \
  --max-wait 5400
```

### 纯文字生成

当参考图包含会污染生成的内容（医疗、老人输液、旧品牌、敏感元素等），不要继续喂参考图。改用纯文字 Seedance：

```bash
source "$HOME/.config/wujieai/env"
env -i PATH="$PATH" HOME="$HOME" GATEWAY_API_KEY="$GATEWAY_API_KEY" \
python3 ~/.codex/skills/seedance/scripts/seedance.py \
  --prompt-file "<Part提示词.txt>" \
  --output "<输出Part.mp4>" \
  --model ep-20260625155850-zpss5 \
  --ratio 9:16 \
  --duration 15 \
  --resolution 720p \
  --generate-audio \
  --poll-interval 10 \
  --max-wait 5400
```

如果普通 `seedance.py` 报 `httpx.InvalidURL: Invalid port ':1'`，说明本机代理环境污染；用上面的 `env -i ...` 干净环境重跑。

### 失败处理

- 每个 Part 生成前先定尝试预算：默认同一 Part 最多 5 次标准生成。生成后记录 `Seedance_take_log.md`：`Take N · 改了什么 · seed/素材是否变化 · 结论[保留/后期修/编辑/重抽/重写] · 证据一句话`。
- 一次只改一个变量：只换 seed、只改一句提示词、只换一张参考图、只换模式，不能同时改很多项。
- 如果主目标已经达成，次要瑕疵能后期修，就锁定，不要为了细枝末节继续烧次数。
- 同一问题连续出现两次，说明不是运气差，要回到素材角色表或预算分配重写：例如产品细节不稳，就减少人物动作和背景复杂度；人物不像，就减少大动作和远景；口播重复，就重切参考音频。
- `同步调用三方API失败: 接入HTTP请求异常`：先按上游/网关失败处理，原样重试一次；不要立刻改提示词。
- taskCode 真人脸任务失败：先检查公网 URL 是否可访问，再确认 `taskCode=2509/2508` 是否与当前渠道匹配。不要直接切回 ai_router，除非用户明确同意。
- 真人脸视频创建后失败：如果 task 已创建但查询失败，先用返回的 `task_key` 继续查 `task_info`，不要换接口重提。
- `InvalidParameter ... audio duration ...` 或网页端上传失败：音频参考太长。把音频按 Part 切成 `<=15.00s`，推荐 `14.90s`，不要依赖 15.2s 这类 API 宽限，也不要传 30 秒音频给单个 15 秒任务。
- `audio format ... not valid`：音频格式不被当前模型接受。优先转成 mp3，15 秒一段，再作为 `reference_audio` 传入。
- `OutputVideoSensitiveContentDetected.PolicyViolation`：这是成片输出审核失败。先原样重试一次；连续失败再只软化版权/敏感视觉词，不要大改原片剧情和台词。
- 同一参考图反复失败：检查参考图是否含医疗、旧品牌、敏感或不相关元素；必要时改纯文字生成。
- 音频版失败：原样重试一次；仍失败再生成静音版或去掉 `--generate-audio`。
- 成片有BGM但多段需要拼接：优先重跑无BGM提示词；时间紧时导出静音保险版。

## 步骤 ⑧：拼接、验证、打包

生成多个15秒 Part 后，用 ffmpeg 拼接：

```bash
ffmpeg -y -f concat -safe 0 -i <(printf "file '%s'\nfile '%s'\n" \
  "<Part1.mp4>" "<Part2.mp4>") \
  -c copy "<最终30秒.mp4>"
```

导出静音保险版：

```bash
ffmpeg -y -i "<最终30秒.mp4>" -c:v copy -an "<最终30秒_静音保险版.mp4>"
```

验证：

```bash
python3 tools/final_video_qc.py \
  --videos "<最终视频.mp4>" \
  --target-duration "<目标秒数>" \
  --duration-tolerance 3 \
  --out-dir "<输出目录>/final_qc"
```

最终交付阶段默认不跑 ASR，不反复听完整音频。只确认视频可读、有所需音视频流、时长接近、无 freeze/black/static shots、无明显错人错产品错场景或缝点断裂，就直接给用户可点击视频或绝对路径。只有用户要求核对台词/声音，或问题明确指向音频、漏话、重复话、口播边界时，才额外跑 final ASR。

护肤/美妆/泥膜类还要抽帧核对前后对比：前半段保留轻微问题，后半段洗后皮肤必须更亮、更细、更干净，闭口/粗糙/暗沉减少；如果只是湿润反光、换灯光、磨皮失真或无差异，不合格。

打包交付：

```bash
zip -j -9 "<交付包.zip>" "<最终视频1.mp4>" "<最终视频2.mp4>" "<预览图.jpg>"
```

## 执行顺序

当用户说"帮我复刻这个视频"时：

1. 先确认：视频路径、要替换的产品/人物描述
2. 跑步骤⓪视频剧情分析，输出原片剧情骨架
3. 跑步骤①拆分镜
4. 跑步骤②全 Part 批量改图：按目标时长直接改完 Part1/Part2/Part3...，不默认停小样
5. 跑步骤③改图审核；不合格 Part 只做局部快修或针对性重跑
6. 小样只在用户明确要求 sample stop 时执行，不是主链路
7. 基于原片剧情 + 合格改图分镜跑步骤④写口播
8. 跑步骤⑤缝点设计（≥2组分镜时必做）
9. 跑 Seedance 生成前路由：写 `seedance_素材角色表.md`，确定每个 Part 的生成模式、素材角色、主目标和简化项
10. 跑步骤⑥生成可直接复制的 Seedance 提示词（缝点写入边界时间段）
11. 带参考音频时，先跑音频边界质检：逐段 ASR，确认 PartX 结尾和 PartX+1 开头无重复台词；提示词的音频脚本与参考音频一致
12. 跑提示词洁净和素材引用质检：确认提示词无污染词，request JSON 里实际传了分镜/产品/人物/音频，产品特写段再次 @ 产品图
13. 如果用户要最终视频，跑步骤⑦生成每个 Part，并记录 `Seedance_take_log.md`
14. 跑步骤⑧拼接和快速最终 QC；确认无静止/黑场/明显 bug 后直接交付可点击视频或绝对路径。final ASR 只在音频问题或用户要求时运行。

## 输出目录结构

```
<视频名>_复刻/
├── 视频分析/
│   ├── frames_2fps/
│   ├── contact_1.jpg
│   └── 原视频剧情分析.md
├── 分镜/                    # 步骤①输出
│   ├── Part1_单独帧/
│   ├── Part2_单独帧/
│   ├── 分镜_Part1.jpg
│   └── 分镜_Part2.jpg
├── 改图/                    # 步骤②全 Part 批量改图 + 步骤③快修输出
│   ├── Part1_改图/
│   └── Part2_改图/
├── 最终改图四张/             # 或最终改图/，集中放合格 Part 图
├── 改图审核.md               # 步骤③b输出
├── 口播文案.md               # 步骤④+⑤输出（含缝点设计）
├── 缝点设计.md               # 多段项目推荐单独输出
├── seedance_素材角色表.md     # Seedance 生成前路由：素材角色、模式、主目标、简化项
├── 音频边界质检.md           # 带声音多段项目必备
├── 提示词洁净质检.md         # Seedance 生成前必备
├── seedance_refs/            # 去掉 Shot 黑栏的 Seedance 参考图
├── seedance_提示词.md        # 步骤⑥输出
├── Seedance_take_log.md       # 每次生成/重试记录
└── 输出/
    ├── Part1.mp4
    ├── Part2.mp4
    ├── 最终30秒.mp4
    ├── 最终30秒_静音保险版.mp4
    └── 交付包.zip
```
