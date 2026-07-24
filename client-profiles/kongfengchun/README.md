# 孔凤春清洁泥膜 Loop Profile

这是孔凤春清洁泥膜的专用复刻 profile。

只在 `output/<job-id>/product_profile.json` 加载 `category:clay_mask` 或 `sku:kongfengchun_clean_mud_mask` 时读取本目录。只出现 `孔凤春` 品牌词不够；`孔凤春发酵水`、toner、unknown product 或其他非泥膜产品不得加载本泥膜 profile。

## 必读顺序

1. `product-profile.md`
2. `passed-standards.md`
3. `failed-cases.md`
4. `loop-overrides.md`
5. `refs-manifest.md`
6. `prompt-rhythm-map.md`

## 这个 profile 解决什么

- 防止旧爆款里的灰泥、管状/棒状涂抹头、手臂试色污染新分镜。
- 防止图像生成乱造白罐、包装盒、礼盒、说明盒。
- 防止人物被原视频主播污染，或一次任务误用两个男模。
- 防止 Part1 / Part2 肤色、光线、泥膜质感差太大。
- 防止 Seedance 节奏只跟 ASR，不跟字幕和画面，导致产品名没卡在产品特写上。
- 防止洗后亮肤参考图从开头就绑定，造成前后肤色断层。

## 快速结论

- 身份：只用一个男模身份锚点；不能用双男模 sheet。
- 产品：只认孔凤春白色方圆罐、白盖、绿色叶子标识、开盖白泥。
- 泥膜：必须是偏乳白、厚、能被手指挑起的小峰状泥膜。
- 动作：上脸只能用手指/指腹涂抹，不能用管、棒、刷头。
- 场景：按原片镜头顺序复刻；不能把非浴室镜头改成浴室。
- 节奏：字幕 + ASR + 画面共同定镜头表；字幕存在时，字幕是节奏主锚。
- 洗后图：只在洗脸完成后的镜头引用，不能从第一秒绑定。

## 旧项目原始证据

旧项目提炼来源已经整理进本 profile：

- 已复制到本 profile 的关键图片：`assets/`
- 已复制到本 profile 的关键记录：`source-notes/`

不要直接复用旧项目废稿。旧项目只作为规则和证据来源。
