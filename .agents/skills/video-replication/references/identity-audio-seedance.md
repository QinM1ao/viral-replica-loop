# 指定主播、真人审核与音频参考

用于用户提供“厂家指定人物/声音视频”“指定主播截图”“产品必须更还原”的复刻任务。

## 核心流程

稳妥版顺序：

1. 原片剧情分析与 30 秒压缩分镜。
2. 从厂家视频抽人物帧和音频；用户给主身份截图时，以用户截图为准。
3. 做产品参考包：盒装、套装、logo/色号 crop；多张产品图可合成一张产品参考。
4. 用 GPT Image 2 先改分镜：原分镜只保留镜头节奏，人物换成指定主播，产品换成用户最新产品，清掉旧字幕旧产品。
5. 审核改图，不合格不进 Seedance。
6. Seedance 同时引用最终改图分镜、产品图、指定主播图、每段声音参考。

不要把带旧产品/旧人物的原始分镜直接喂给 Seedance。它会复刻旧道具，例如面膜袋、旧色号、旧品牌。

## 抽指定主播

从厂家视频抽 1fps 接触表：

```bash
ffmpeg -y -i "<厂家视频.mp4>" -vf "fps=1,scale=270:480" -q:v 2 "<out>/person_%03d.jpg"
ffmpeg -y -i "<厂家视频.mp4>" -vf "fps=1,scale=180:320,tile=8x10" -frames:v 1 "<out>/人物接触表.jpg"
```

选择主身份图：

- 优先正脸、自然表情、眼睛睁开、嘴型正常、发型完整、服装清楚。
- 避免夸张表情、低头检查发根、眨眼、嘴型变形、字幕挡脸的帧。
- 用户提供截图时，复制进工作区并用它作为最高优先级身份图。
- 如果截图带字幕，在 GPT/Seedance 提示词里写：只参考脸、发型、妆容、服装和气质，不复制字幕。

示例提示词：

```text
Image C is the exact female presenter identity reference.
Ignore any subtitle text in Image C. Use Image C only for the presenter's face, hairstyle, makeup, shirt, age feel, and natural expression.
Do not beautify into a generic AI influencer.
```

## 产品参考

产品还原高要求时，产品必须进 GPT Image 和 Seedance：

- GPT Image 改图：`原分镜 + 产品参考 + 主播身份图`。
- Seedance 生成：`最终改图分镜 + 产品参考 + 主播身份图`。

多张产品图过多会让 GPT Image 请求变重。把盒装和套装合成一张产品参考：

```bash
ffmpeg -y -i "<套装.jpg>" -i "<盒装.jpg>" \
  -filter_complex "[0:v]scale=512:512[p0];[1:v]scale=512:512[p1];[p0][p1]hstack=inputs=2,format=yuvj420p" \
  -q:v 2 "<out>/产品合成参考.jpg"
```

如果 Matpool 多参考图请求太重或资源报错：

1. 不要切到任何废弃 GPT Image 路线或网关探测。
2. 把分镜缩到约 768px 宽并重编码为 JPEG。
3. 把产品图合成一张，降到 3 refs：分镜、产品合成、主身份图。
4. 用 Matpool 路线重新跑小样。

## GPT Image 小样模板

推荐 3 refs：

```bash
python3 .agents/skills/video-replication/scripts/generate.py \
  --prompt-file "<改图提示词.txt>" \
  -i "<原片节奏_Part1_clean.jpg>" \
  -i "<产品合成参考.jpg>" \
  -i "<人物主身份参考.jpg>" \
  --quality medium \
  --size "<源Part分镜图画布比例或像素尺寸>" \
  --file "<out>/Part1_小样/part1_matpool.png"
```

提示词必须写：

- Image A 只保留分镜节奏、构图、手势和动作，不保留旧人物旧产品。
- Image B 锁产品包装、色号、套装结构，禁止旧产品和旧色号。
- Image C 锁指定主播身份，禁止随机 AI 网红脸。

## 声音参考

Seedance 单个 15 秒 r2v 任务的音频参考必须短于约 15.2 秒。不要给一个 15 秒任务传 30 秒音频。

优先转 mp3，但不要机械按 `0-15s / 15-30s` 切。先用 ASR 得到句子时间戳，再按完整句子边界切分；句子提前结束时补静音/环境声到目标时长。

```bash
# 例：Part1 最后一句在 14.56s 结束，补 0.44s 静音到 15s
ffmpeg -y -i "<原片音频.wav>" \
  -filter_complex "[0:a]atrim=0:14.56,asetpts=PTS-STARTPTS[a0];anullsrc=channel_layout=mono:sample_rate=16000,atrim=0:0.44,asetpts=PTS-STARTPTS[s];[a0][s]concat=n=2:v=0:a=1[a]" \
  -map "[a]" -ar 44100 -ac 2 -c:a libmp3lame -q:a 3 "<out>/voice_part1_clean.mp3"
```

如果 Part2 从 14.56s 的新句开始：

```bash
ffmpeg -y -i "<原片音频.wav>" -ss 14.56 -t 15 \
  -vn -c:a libmp3lame -b:a 128k "<out>/voice_part2_clean.mp3"
```

已踩坑：

- 30 秒音频会报：`audio duration ... must be less than or equal to 15.2`。
- m4a 可能报：`audio format ... not valid`。
- mp3 15 秒参考可用。
- 相邻 Part 音频重叠会导致同一句台词说两遍。必须生成前 ASR 转写每条 reference audio，确认上一段不含下一段开头句。

提示词里写清：

```text
参考音频1只用于模仿厂家女主播的声音质感、语速、直播感、停顿和自然口播状态，不照搬音频里的旧台词。
禁止BGM，禁止配乐，禁止音乐铺底，禁止鼓点。
```

## Seedance 命令

本地图片/音频先上传到 `https://api.qinmiao.space/uploads/...`。真人图和含真人的最终改图分镜必须走素材库。

如果图片还没有 asset：

```bash
python3 ~/.codex/skills/seedance/scripts/seedance_ai_router.py \
  --prompt-file "<Part1提示词.txt>" \
  --images "<part1_storyboard_url>" "<product_url>" "<person_url>" \
  --audios "<voice_part1_15s_mp3_url>" \
  --asset-library \
  --ratio 9:16 --duration 15 --resolution 720p \
  --generate-audio --poll-interval 10 --max-wait 5400 \
  --output "<out>/Part1.mp4"
```

如果图片已经审核成 asset：

```bash
python3 ~/.codex/skills/seedance/scripts/seedance_ai_router.py \
  --prompt-file "<Part1提示词.txt>" \
  --images "asset://asset-storyboard" "asset://asset-product" "asset://asset-person" \
  --audios "<voice_part1_15s_mp3_url>" \
  --ratio 9:16 --duration 15 --resolution 720p \
  --generate-audio --poll-interval 10 --max-wait 5400 \
  --output "<out>/Part1.mp4"
```

参考绑定要在提示词里固定：

```text
图片1：最终改图分镜，只参考镜头顺序和动作。
图片2：产品参考，锁品牌、包装、色号、套装结构。
图片3：指定主播身份，锁脸、发型、妆容、服装和年龄感。
音频1：厂家声音参考，只参考声音质感和节奏。
```

## 审核与交付

生成后必须：

1. `ffprobe` 检查每段约 15 秒、视频 h264、音频 aac。
2. 拼接成 30 秒。
3. 导出静音保险版。
4. 抽 1fps 总览图，看是否产品正确、人物不随机、旧产品无残留、画面非空。

如果 GPT 改图比直接 Seedance 更干净，以 GPT 改好的分镜为准；不要为了更像原片节奏而牺牲产品正确性。
