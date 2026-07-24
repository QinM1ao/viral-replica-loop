# GPT Image 分镜循环规则

## 适用范围

job-001 以及后续孔凤春清洁泥膜类视频复刻的 GPT Image 分镜改图阶段。

## 官方提示原则落地

参考 OpenAI 图像生成/编辑官方文档和 OpenAI Cookbook 图像提示指南，当前 loop 采用三条原则：

- 多参考图必须明确编号和角色，不让模型自行混合素材。
- 每轮只改一个主要变量，避免一次同时改身份、产品、色温和布局。
- 通过局部/小步迭代修失败点，合格项锁住不动。

## Codex ImageGen 等价路线

Codex 内置 ImageGen 的目标不是重新文生一张新图，而是复刻原 API 的 `gpt-image-2-edit` 方式：把当前 Part 的完整源分镜图、产品正面图、开盖白泥图、人物身份图作为真实图片参考输入，直接编辑成一张新的完整 12 格分镜图。

合格输出必须和 `job-001` / `job-002` 的 `01_图片1` 一样：

- 一张完整 Part storyboard，不是 9:16 单帧。
- 保持源 Part 分镜图的 panel 画幅和整体画布比例；4列x3行、约 3:4 只适用于竖屏源片 precedent。
- 横屏源视频必须保持横向 panel，并默认排成 3 列 x 4 行 storyboard；不能在分镜阶段强行压成 9:16、3:4，也不要做成过长的 4 列 x 3 行宽条。
- 原分镜只传递镜头顺序、构图、景别和动作。
- 原分镜不能传递旧产品、旧主播、字幕、灰/黄旧泥、管状/棒状/刷头/手臂试色等旧工具细节。
- 产品参考图锁定孔凤春白色方圆罐、白盖、绿色标识、标签布局和白色厚泥。
- 人物参考图只锁定目标身份。
- 旧片中的管状/棒状/刷头/手臂试色动作，必须在生成前转译成手指从开盖白罐内取乳白厚泥、用指腹上脸。不要把旧工具词写进 ImageGen 提示词里当负面锚点。
- 如果只是把本地路径写进 prompt、没有真正把图片作为参考输入，不能记为 `codex_image_gen` PASS。
- 当前 loop 必须写 `codex_imagegen_contract.json` 并通过 `tools/codex_imagegen_contract_qc.py` 后，才能记录 image sample 或 image batch PASS。

参考链接：

- `https://platform.openai.com/docs/guides/images`
- `https://cookbook.openai.com/examples/multimodal/image_generation`

## job-001 固定输入角色

### 身份

唯一男模身份图：

`<legacy-project>/孔凤春/模特/男/content 4.png`

禁止：

- `content 5.png`
- `male_identity_ref_sheet.jpg`
- `male_model_sheet.jpg`
- 任何双男模/多男模拼图

### 色彩和连续性

Part1 最终改图只作为色温、肤色、曝光、手机拍摄质感和跨 Part 连续性锚点。

### 产品

产品正面图和开盖白泥图必须拆成两张独立参考。不要只使用横向合成 sheet，也不要只靠分镜图里的小产品。

### 分镜

Part2 分镜图只传递：

- 4列x3行布局，且每格保持源视频画幅
- Shot 顺序
- 镜头构图
- 人物动作
- 场景切换

不传递：

- 原片旧产品颜色
- 灰膜/稀泥/拉丝质感
- 旧产品管状/棒状形态
- 原视频主播脸
- 小字品牌证明

## 自动硬门槛

使用：

`video-replication-loop/tools/storyboard_loop_qc.py`

必须通过：

- 单男模输入，无 banned refs。
- 按源视频画幅决定整体画布；竖屏源片默认 4 列 x 3 行，可接近 3:4；横屏源片默认 3 列 x 4 行，避免画布过长导致改图失控。
- Part1/Part2 肤色、色温不能明显跳变。
- Shot 06/10 是乳白厚泥，不是灰泥。
- 产品镜头里有绿色识别点，不能是空白/乱牌白罐。

未通过：直接写废稿说明，改一个变量重跑。

通过：写审核文档，提升为 `最终改图/Part2_final.png`，再进入 Seedance。
