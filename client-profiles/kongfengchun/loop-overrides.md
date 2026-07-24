# Loop Overrides For 孔凤春

这些规则覆盖通用 loop，但不取消通用 loop 的硬规则。

## Intake

当 `output/<job-id>/product_profile.json` 加载 `category:clay_mask` 或 `sku:kongfengchun_clean_mud_mask`：

- 自动加载本 profile。
- `BRIEF.md` 必须写入 `Client profile: kongfengchun`。
- `jobs.csv notes` 必须包含 `client_profile=kongfengchun`。
- `STATE.md` 必须提醒下一轮先读本 profile。

只出现 `孔凤春` 品牌词不触发本 profile。`孔凤春发酵水` 等非泥膜产品只能使用通用产品一致性、品牌标签一致性和对应 category/SKU 规则。

## Story Analysis

- 必须同时拆字幕、ASR、画面。
- 如果原视频有字幕，字幕是镜头节奏主锚。
- ASR 只补充真实口播、停顿、无字幕段。
- 先标出旧片灰泥、旧产品、旧主播脸、旧涂抹工具、包装风险。

## Storyboard

- 先写污染审查，再写改图提示词。
- 原片灰泥、手臂试色、管状/棒状动作，只保留镜头作用，不保留材质和工具。
- Part1 / Part2 分镜必须一起比较肤色、光线、泥膜质感。
- 人物只允许一个身份参考。
- 非浴室原片镜头禁止改成浴室。

## Image Generation

- GPT Image 出图只使用项目 Matpool GPT-Image-2 路线：`.agents/skills/video-replication/scripts/generate.py`，并通过 `MATPOOL_API_KEY` 鉴权。
- Matpool GPT-Image-2 必须按真实 edit/reference 方式执行：实际提交源 Part 分镜、产品正面、开盖白泥、单一身份图作为 multipart `image` 文件，不能只在文字里写路径或产品名。
- 不尝试任何废弃 GPT Image 路线或网关探测。
- 每次小样/批量改图都必须写 `codex_imagegen_contract.json`，并跑 `tools/codex_imagegen_contract_qc.py`。没有 PASS，不能记录 image sample 或 image batch PASS。
- 合同里必须写清：源分镜只传构图、顺序、景别、动作节奏；不传旧产品、旧主播、旧泥膜颜色、字幕、管状/棒状/刷头/手臂试色。
- 旧片里的管状/棒状/刷头/手臂试色动作必须在生成提示词前改写成：手指从开盖白罐里取乳白厚泥，用指腹上脸。不要把“泥膜棒/刷头/手臂试色”等旧词写进 ImageGen 提示词里当负面词。
- 图像生成不再“多试”。优先快修：只修失败图/失败面板/失败材质变量。
- 小样、整 Part、局部快修都先做最多一次针对性重试；同一失败再出现就停下来换策略，不继续盲跑。
- 但是每一版都必须保存：
  - prompt
  - refs manifest
  - QC 结果
  - pass/fail 原因
- 小样过硬规则后才给用户看。
- 以下情况不需要问用户，直接内部废稿：
  - 双男模
  - 陌生包装盒
  - 普通白罐替身
  - 黄泥/米色泥/暖奶油色泥/灰泥/稀泥
  - 管状/棒状涂抹
  - 手臂试色
  - 居家镜头变浴室
  - Part1 / Part2 明显色差
- 上脸泥和开盖泥必须对齐产品开盖参考的白色厚泥；如果分镜里泥膜偏黄、偏米、偏肤色，必须继续在图像快修阶段修，不允许进入 Seedance。
- 已经存在 `final-images/`、`seedance/seedance_refs/`、`seedance_web_final/` 时，快修通过后必须同步替换最终位置，旧稿移入 `deprecated_*`。

## After-Wash Reference

- 当前默认不生成、不上传独立洗后参考图；以 Shot 文案控制前后差异，保持 `requires_afterwash_ref=false`。
- 洗后结果必须正向写清，不能用“保留真实毛孔/皮肤纹理”削弱当前 profile 的商业效果。
- 只有用户明确要求或规则显式改为 `requires_afterwash_ref=true` 时，才从 approved 单男模身份图重新生成；不得裁切已有分镜里的洗后画面。

## Seedance Prompt

- 先有逐镜头表，再写 Seedance 提示词。
- 必须按两段写，不默认拆三段。
- 提示词里不写已经在图像阶段解决的废话型负面词。
- 不把“浴室、拉链、灰泥”等旧失败词带进干净提示词，除非当前镜头真的需要说明。
- 口播必须打中文引号。
- 产品名 `孔凤春清洁泥膜` 整条成片只在产品特写镜头上说一次，必须独立成句；其他 Part 改用“这罐泥膜”。
- `director_plan.json` 必须分开 `speech_groups` 和 `execution_blocks`；单执行块最多 5 格，不得用一个长口播组把洗后证明、手机打卡、空罐和结论压成一块。
- 执行块不能跨声音模式、场景或画面功能边界；画面内同期口播与画外旁白必须拆开，短促静物 B-roll 必须独立成块。
- `主播产品近景 → B-roll → 主播产品近景` 的原片硬切，B-roll 前后使用匹配的原片场景、景别和产品位置；不重新起手推近，不擅自加溶解。
- 产品参考尽量分开引用：
  - 产品正面图控制罐身。
  - 开盖图控制白色厚泥。
- 身份图只锁人物，不传递其背景，也不覆盖各 Shot 的洗前/洗后皮肤状态。
- Part2 开头必须有动作，不允许静止头像停住。

## Seedance Generation

- 提交前必须通过 request gate 和 cost gate。
- Seedance 贵，不能靠它试错图像阶段的问题。
- 如果分镜图已经有产品/泥膜/人物/色差问题，必须回图像快修阶段修，不许直接提交生成。
- 如果交付方式是网页端手动跑 Seedance，停止前必须把最终上传素材、提示词、manifest、音频和说明放进一个 `seedance_web_final` 类输出区。
