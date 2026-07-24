# GPT Image 2 改图提示词模板

本文件只提供局部改写示例。正式参考图角色、Shot 导航栏规则、调用步骤和完成条件以 `codex-imagegen-direct.md` 为唯一事实源；每次生产改图先读该文件，再按当前 product profile 填充。

## 核心原则

改图的目标是**只换内容，不换镜头**：
- 保持构图、角度、景别、动作完全一致
- 替换人物、产品、品牌元素
- 去除 panel 画面里的口播字幕、旧说明文字、贴纸和水印
- 12 格 storyboard 必须保留原有 `Shot 01-12` 编号、编号位置和对应关系

## 基础模板

```
Based on this image, generate a new picture with the exact same composition,
camera angle, framing, and character pose. Make these changes:

1. PERSON: [描述目标人物]
2. PRODUCT: [描述目标产品]
3. Remove dialogue subtitles, old promotional text, stickers, watermarks, and content overlays inside the panels
4. PRESERVE: every black Shot-label bar and the cyan labels Shot 01 through Shot 12 in their original positions and exact panel correspondence; do not delete, rewrite, renumber, reorder, translate, restyle, or move them
5. KEEP: background environment, lighting, mood, and overall visual style
```

## 中文模板

```
请基于这张图片生成一张新图片，保持完全相同的构图、角度、镜头和人物动作。
做以下替换：

1. 人物：[目标人物描述]
2. 产品：[目标产品描述]
3. 去掉每格画面里的口播字幕、旧宣传说明、贴纸、水印和旧内容覆盖层
4. 保留原 storyboard 的每条黑色 Shot 编号栏，以及青色 Shot 01-12 编号、编号位置和每个编号对应的画面；不得删除、改写、重新编号、调换顺序、翻译、改样式或移动
5. 保留：背景环境、光线、氛围、整体视觉风格
```

## 人物描述模板

根据目标风格选择合适的描述：

### 中国网红美女
```
一位中国年轻女性，长发，妆容精致，穿着时尚，皮肤白皙，表情自然亲和。
保持与原图完全相同的姿势和动作。
```

### 男性口播达人
```
一位中国年轻男性，干净利落的发型，穿着休闲得体，表情自信有感染力。
保持与原图完全相同的姿势和动作。
```

### 产品特写（无人物）
```
去掉人物，只保留产品。产品放在与原图相同的背景环境中，
保持相同的光线和构图风格。
```

### 通用人物替换
```
[性别] [年龄段] [风格特征] [穿着描述]。
保持与原图人物完全相同的姿势、动作和表情。
```

## 产品描述模板

### 食品类
```
[产品名称]，[包装描述]，放在画面中与原产品相同的位置。
包装上显示品牌名"[品牌名]"。保持食物的新鲜感和食欲感。
```

### 美妆护肤类
```
[产品名称]，[包装材质/颜色]，[容量]。
放在画面中与原产品相同的位置。产品标签清晰可读。
```

### 日用品类
```
[产品名称]，[外观描述]。
放在画面中与原产品相同的位置，保持与原图一致的产品大小比例。
```

## 批量改图一致性指南

同一视频的所有帧需要保持视觉一致性：

1. **人物描述固定** — 所有帧使用完全相同的人物描述文案
2. **产品描述固定** — 所有帧使用完全相同的产品描述文案
3. **风格词统一** — 在每帧的提示词末尾加上统一的风格约束

### 统一风格后缀（可选）

```
Maintain a clean, professional commercial photography style.
Consistent warm lighting. High quality, sharp details.
```

## 常见场景示例

### 示例1：口播带货（热干面 → 螺蛳粉）

原帧：一位女性在展示热干面产品

```
Based on this image, generate a new picture with the exact same composition,
camera angle, framing, and character pose. Make these changes:

1. PERSON: A young Chinese woman with long hair, light makeup, wearing a
   casual home outfit. Keep the exact same pose and gesture as the original.
2. PRODUCT: Replace the food product with a pack of 螺蛳粉 (Luosifen/snail
   noodles). The package should be colorful with brand name "XX牌" visible.
   Place it in the same position as the original product.
3. Remove dialogue subtitles, old promotional text, watermarks, and overlays inside the panels.
4. Preserve the storyboard Shot labels when the input is a storyboard grid.
5. KEEP: The kitchen/home background, warm lighting, cozy atmosphere.
```

### 示例2：场景代入（换人物 + 换产品）

原帧：一位达人拿着护肤品在讲解

```
Based on this image, generate a new picture with the exact same composition,
camera angle, framing, and hand position. Make these changes:

1. PERSON: A young Chinese woman, age 25-30, elegant style, wearing a white
   blouse. Keep the exact same pose, hand position, and speaking expression.
2. PRODUCT: Replace with a glass bottle of facial serum, 30ml, with a
   minimalist label showing "XX精华". Hold it in the same hand position.
3. Remove dialogue subtitles, old promotional text, watermarks, and overlays inside the panels.
4. Preserve the storyboard Shot labels when the input is a storyboard grid.
5. KEEP: The clean modern background, soft studio lighting, beauty commercial
   style.
```

### 示例3：纯产品展示（无人物）

原帧：热干面在桌面上的摆盘

```
Based on this image, generate a new picture with the exact same composition,
camera angle, and plating arrangement. Make these changes:

1. Replace the food product with 螺蛳粉 (Luosifen) in a nice bowl,
   garnished with toppings. Same serving style and portion size.
2. Remove dialogue subtitles, old promotional text, watermarks, and overlays inside the panels.
3. Preserve the storyboard Shot labels when the input is a storyboard grid.
4. KEEP: The wooden table background, overhead angle, food photography
   lighting, warm color palette.
```

## 注意事项

- GPT Image 2 对文字渲染能力强，品牌名可以明确写出来
- 如果原图有复杂的手部动作，描述时要强调"保持相同的手部姿势"
- 背景如果很复杂，可以用"保持完全相同的背景"简化
- 每次生成后检查一致性，如果不满意可以追加约束重新生成
