# 复刻视频实战经验

## 先分析视频，再写口播

不要只看分镜就写口播。优先用 MCP 视频分析工具直接分析原片画面、音频、口播和字幕；如果 MCP 不可用，再用 2fps 抽帧 + 原片字幕复原剧情。

输出原视频剧情分析时，记录：

- 原始口播：逐句文案、时间戳、画外音/同期声判断。
- 开场钩子：原片靠什么抓人，是冲突、尴尬、问题，还是反差。
- 剧情推进：谁在做什么，谁被吸引，哪里发生转折。
- 卖点话术：价格、品质、分量、成分、口感、效果、福利。
- 收口方式：直播间、限时福利、点击链接、囤货。
- 要删除/替换的人：多女主、无关同事、抢戏人物。

口播要复刻“叙事功能”，不是逐字照搬。比如原片是“办公室不让吃 → 真香反转 → 产品 next level → 买送福利”，新口播也必须保留这个骨架，只替换成新产品。

## 多人视频要标清谁在说话

多人短剧带货不能把所有声音写成一条“总口播”。必须先判断每句话的声音来源：

- 女主同期声：用于递产品、试吃、真实感评价。
- 同事/主管同期声：用于制造冲突、质疑、被真香反转。
- 群体反应：用于“真香”“好香”等情绪反馈。
- 画外音旁白：用于卖点、品牌、价格、福利和直播间收口。

如果原片是“同期声短剧 + 画外音卖点”的混合结构，复刻口播和 Seedance 提示词也必须保持这种分工。Seedance 每个时间段都要写明谁开口，否则模型容易生成成一个人从头念到底。

## 跨品类替换要防原产品形态污染

当原片是牛肉片/肉脯/片状食物，目标产品是鸭脖、鸭货、杯面等形态差异大的产品时，模型会强烈继承原片食物轮廓。提示词里不能只写“替换成鸭脖”，要逐格或全局强调：

- 原片平片肉类只保留镜头角度和手部姿势，不保留食物形状。
- 目标必须是“骨节/圆柱/块状鸭脖段”，禁止“flat beef slices / steak sheets / jerky sheets”。
- 产品包装可以先通过整网格小样验证，食物形态不稳时再切关键特写单帧修复。

## 产品识别以用户素材为准，不要沿用误分类

视觉分析工具可能把鸭脖、鸡脖、鸭货、风干肉类粗略说成“肉块”。如果用户明确说产品是鸭脖/鸡脖/某个具体品类，或产品图可见该品类特征，后续所有文档、改图提示词、口播和 Seedance 都必须使用具体品类名，不要继续写“肉块/卤味肉块”。

正确做法：

- 先回看产品图，提取可见形态证据。
- 对鸭脖/鸡脖类，写“一节一节短段、长段骨节、骨孔、骨头截面、脊骨纹理、肉丝纤维、红棕卤色、辣椒粉/椒盐粉/香辛料颗粒”。
- 禁止项要针对误生成：普通肉块、圆墩肉块、方块肉、肉丸、牛肉干、排骨、鸭翅、鸡翅、辣条、扁平片状零食。
- 如果某个 Part 变成圆墩肉块，单独重跑该 Part；不要重跑已合格 Part。
- 必要时从产品图裁一个近景参考图，作为额外参考图锁住形态。

错误链路：产品图被描述成“肉块” → 改图变成肉块 → 口播写成肉块口感 → Seedance 提示词继续偏。发现源头错时，要从改图提示词、口播、Seedance 全部回滚修正。

## GPT Image 2 多参考图经验

项目只使用 Matpool GPT-Image-2。多参考图用本地 multipart `image` 字段，顺序就是角色顺序：

```bash
python3 .agents/skills/video-replication/scripts/generate.py \
  --prompt-file "<prompt.txt>" \
  -i "<A 原始分镜>" \
  -i "<B 产品参考>" \
  -i "<C 女主参考>" \
  --quality medium \
  --size "<源Part分镜图画布比例或像素尺寸>" \
  --file "<输出目录>/part1_matpool.png"
```

不要尝试任何废弃 GPT Image 路线或网关探测。Matpool 失败时只修输入图片、提示词、质量或尺寸，不切废弃路线。

## 产品文字生成目标与尺度化审核

2026-07-02 的 `孔凤春发酵水` 修复证明：只写“product label clear”或“包装像目标产品”不够，GPT Image 容易把瓶身小字抹成空白瓶。正确做法是把真实可见文字沉进 product profile、prompt 和合同 QC：

- SKU/profile 里声明 `visible_text_patterns`，例如 `PORTULACA OLERACEA FERMENTED ESSENCE TONER`、`马齿苋发酵精华水`、`52%马齿苋`、`屏障修护`、`敏肌适用`。
- 改图 prompt 仍以真实标签为生成目标；指定英雄近景必须保留主要品牌、产品名和真实标签设计，不能抹成空白玻璃、绿色标志-only 或无字瓶。远景、斜拍、多瓶和分镜尺度的小字只审核整体颜色、行结构和品牌观感，不要求逐字一致；仅小字差异记为 `VISUAL_WARNING`，不能单独触发硬失败。
- `codex_imagegen_contract.json` 的 review 必须有 `product_visible_text=true` 和 `no_blank_label=true`。
- 如果候选已经变空白瓶，同时还改变了场景/人物关系/分镜结构，不要拿失败候选继续修；从源 Part 分镜重做。

可复用正向片段：

```text
The designated hero product close-up must preserve the major brand and product-name anchors from Image B:
"PORTULACA OLERACEA FERMENTED ESSENCE TONER", "马齿苋发酵精华水",
"52%马齿苋发酵精华", "屏障修护", "敏肌适用".
For distant, oblique, multi-bottle, or storyboard-scale views, preserve the
overall label color, line layout, and brand impression; exact microtext is not required.
Do not erase the label, smooth it into blank glass, use an old-source label,
use only a green mark, or make a wordless bottle.
```

## 多人物源片先写角色映射

2026-07-02 的 `相亲相到小学同学` 源片有女主和男配。错误做法是沿用“一个任务只用同一个身份”或“single identity”，这会把男配也替换成女主，破坏剧情功能。

正确做法：

- 先从剧情分析写 role map，而不是直接套唯一身份。
- 批准身份只应用到源片定义的主角/产品主持人。
- 配角保留故事功能和性别，可换成泛化/去识别人物。
- 合同 review 使用 `primary_identity_consistent=true`、`primary_identity_only_on_target_role=true`、`secondary_characters_keep_source_role_gender=true`，不要再用容易误导的 `single_identity`。

可复用正向片段：

```text
Hard role map:
- Replace the source female lead/product host completely with Image D.
- Do not apply Image D to the male date counterpart.
- The opening blind-date counterpart must remain a male supporting character.
  Replace or de-identify him as any generic adult male, but keep him male
  and keep his story function.
```

## 场景锁定不能只靠“保留原分镜”一句话

`job-003-v2` 证明：如果 GPT Image prompt 只写“参考源分镜”和“使用模特图”，模型可能把模特图里的房间、自拍角度、灯光或背景当成新场景，导致剧情和原分镜场景对不上。

正确做法是把场景锁定写进出图 prompt 的生成入口，而不是等出图后靠 QC 返工：

- 先打开成功 rolemap prompt：`output/job-001/image-batch/prompts/part1_label_rolemap_repair_prompt.md`。
- 只复制结构：`Reference roles`、`Hard role map`、`Hard source-scene rule`、`Task`、`Do not`。
- 当前任务必须重新填当前产品、当前人物、当前源场景；不要复制发酵水产品内容。
- `Hard source-scene rule` 必须点名当前源分镜的场景家族和具体背景线索。
- 身份图只传脸、发型、年龄感、身体印象、服装；不能传背景、房间、灯光、自拍构图。
- 产品图只传包装、标签、材质和使用动作；不能传棚拍背景、白底、裁切边缘、packshot 构图。
- 如果候选已经换了场景、重排分镜或把产品/模特参考背景搬进画面，丢弃候选，从源 Part 分镜重做。

## 推荐 ABC 提示词结构

当目标是整张 12 格故事板，一般先用：

- Image A = 原始 12 格分镜故事板
- Image B = 产品包装/产品参考图
- Image C = 女主自拍/人物身份参考图

提示词核心：

```text
Edit Image A, using Image B as the exact product reference and Image C as the exact female protagonist identity reference.

Goal: regenerate the full 12-panel storyboard in one coherent pass.

Critical requirements:
1. There must be ONLY ONE clear female protagonist across the entire 12-shot storyboard.
2. The only female protagonist must clearly look like the woman in Image C.
3. Do NOT create multiple similar-looking women.
4. Any other women originally visible in the storyboard must be removed, replaced with male coworkers, or reduced to distant blurred background office extras that do NOT resemble the protagonist.
5. Absolutely no second female lead, no duplicate heroine, and no extra foreground woman.

Product requirements:
6. Replace all product appearances with the product from Image B.

Storyboard structure requirements:
9. Preserve the 12-panel contact-sheet storyboard structure from Image A.
11. Remove all subtitles, dialogue captions, floating Chinese text, sticker text, and other overlaid text inside the image panels.
12. Keep the storyboard frame UI and blue Shot labels.
```

## 多女主排错

问题：前几格不像用户给的女主，最后两格才像。

原因通常不是“没有传女主图”，而是：

- 原分镜里有多个前景女性，模型不知道谁是女主。
- 前几格女主脸小，原图人物身份权重强。
- 最后两格是近景自拍式构图，更容易套上参考脸。

修法：

1. 在提示词中写“ONLY ONE clear female protagonist”。
2. 明确其他前景女性必须删除、替换成男同事，或变成远处模糊背景。
3. 写 Shot guidance，逐格指定女主出现位置。
4. 如果仍不稳，裁出前 6 格单独跑身份验证。
5. 如果前 6 格还不稳，再考虑局部遮脸/单帧修复，不要继续完整 Part 批量烧图。

## 未指定女主时不要强行唯一女主

如果用户没有给女主参考图，也没有明确要求“只保留一个女主”，任务通常只是“洗图/全面替换人物和产品”。这时不要写：

```text
只保留一个女主；其他前景女性必须删除、替换成男同事，或变成远处模糊背景人物，不能像女主。
```

这会把原片的人物关系改坏，尤其是办公室多人围观、多人试吃、闺蜜同框、导购互动这类爆款结构。默认做法应该是：

- 全面替换原片人物身份，不保留原人物脸。
- 保留原片人物数量、站位、互动关系和镜头节奏。
- 只在用户指定女主参考、明确要求唯一女主，或原片多女主明显抢戏时，才加“唯一女主/其他女性弱化”的约束。

## 小样确认标准

批量改图前，先让用户确认一张小样：

- 女主：是否是指定人物，而不是“相似网红脸”。
- 唯一性：是否只有一个清晰女主。
- 产品：包装颜色、文字风格、食物形态是否统一。
- 字幕：画面内字幕/花字是否清掉。
- 结构：12 格/Shot 标签/镜头顺序是否保留。

推荐先用 `--quality medium --size <源Part分镜图画布比例或像素尺寸>`。竖屏源片的 12 格 storyboard 可接近 `3:4`；横屏源片必须保持横向画布。若资源或尺寸报错，先改成明确像素尺寸并按 `medium → low` 降级，不切废弃 API；只有明确质量不足时才升到 `high`。

## 改图后必须审核

改完图不要直接进入口播和 Seedance。每个 Part 都要写审核结论，至少检查：

- 产品是不是用户指定品类，是否有形态证据。
- 产品有没有被前后 Part 污染，例如 Part2 生成成 Part1 的开袋逻辑。
- 人物是否同一人，同发型、服装、妆容是否稳定。
- 原字幕、花字、水印是否清掉，只保留需要的 Shot 标签。
- 手部、试吃、开袋、展示动作是否自然。

审核不过就重跑。不要把“部分合格”的图当成最终图，因为后续口播和视频提示词会围绕错误图继续放大问题。

## Seedance 提示词

Seedance 提示词必须继承原片剧情分析。不要只写“展示产品、试吃、收口”。每段都要能直接复制到 Seedance 使用，不能只交付说明文档。

按关键动作写可变时间轴：

- 画面：对应原片剧情动作。
- 口播：对应原片话术功能。
- 禁止项：无字幕、无水印、不要保留分镜黑底排版。

多段拼接时，每个相邻边界都要写缝点：

- 前一段边界时间段：用收手、合盖、转身、擦脸、水声、手部操作等连续动作收住，最后 0.3-0.6 秒不放新台词。
- 后一段开头时间段：按本 Part 的原片镜头独立开始，并在本段内重新绑定人物、产品、场景和声音；不继承上一段最后一帧的构图、位置或未完成动作。

交付格式建议：

````markdown
## Part 1
使用参考图：`.../part1_seedance_ref.png`

```text
根据我提供的第1张分镜图，生成一条15秒、9:16竖屏的真实短视频……
...
0.0s - 3.0s：
画面：...
口播："..."
```
````

不要把四段混成一个长说明，也不要只给“通用约束 + 时间线摘要”。
