# Seedance 生成质检门

用于提交 Seedance 前后做硬检查，目标是减少“生成后才发现”的返工。

## 生成前

### 1. 素材角色表

提交前必须有 `seedance_素材角色表.md`，并检查：

- 每个 Part 已写生成模式：参考图生视频、真人素材库、参考音频、首尾帧、视频动作参考或纯文字避污染。
- 每个 Part 只选一个主目标、一个次目标。
- 每个素材都有主角色：分镜/动作、产品、人物、环境、声音节奏、首帧或尾帧。
- 每个素材都写清“传递什么”和“不传递什么”。
- 最终改图分镜允许保留源 Shot 编号和对应标签栏，用于提示词中的分镜寻址；素材角色表必须声明它们不传递到最终视频。旧字幕、旧产品和旧人物仍然不得保留或传递。
- 参考音频不能传递旧台词、旧品牌名和BGM。

### 2. 提示词洁净

Seedance 提示词必须是直接给模型看的画面指令，不写内部解释、纠错说明或工作流说明。

最终批准分镜已经删除的对象只留在内部审计证据，不再写进模型提示词。检查 `scene_rule` 和每个 `画面：` 行，不得出现“前景无产品”“不陈列产品”“不出现旧产品”等对已解决对象的负面提醒；直接描述分镜中实际保留的人物、动作和场景。

常见污染词检查：

```bash
rg -n '不是孤立|商品图|不是泥膜棒|不拆|裁头|裁衣服|同Part1|同上|后续继承|方便拼接|静止余量|焦点锁|停住|不要只写|本段不使用|产品不是|Part[12]最终分镜图|AI改好分镜图|current-job|source rhythm board|contact sheet|素材角色表' "<prompt.txt>"
```

命中后改成正向事实描述，例如：

- `头肩和上半身完整入画，黑色无袖上衣、肩线和上臂可见`
- `产品是白色圆罐，开盖露出乳白色厚泥膏`
- `手部合盖、收手、水声或擦脸动作连续`

官方无字幕写法可以保留：

```text
NO CAPTIONS, NO SUBTITLES, NO BURNED-IN TEXT, NO ON-SCREEN WORDS.
画面保持纯净，无口播字幕、标题条、说明文字、贴纸、水印、分镜边框、黑底排版、Shot编号。
下面出现的中文只用于声音和嘴型，不允许显示成画面文字。
```

这里的“无分镜边框、黑底排版、Shot编号”约束最终生成视频画面，不要求从 `@图片1` 的已批准改图分镜中删除 Shot 编号。

### 3. 每段独立

每个 Part 都是独立任务。每段提示词必须自己写清：

- @图片1 是什么。
- 产品图是哪张，产品特写/开盖膏体时再次 @ 产品图。
- 人物身份图是哪张，本段人物设定里 @ 一次。
- 洗后脸图只在 product profile 明确要求时上传，并且只在洗净/擦净后的时间段 @。
- 不写“同Part1”“同一位男生继续”“后续继承”。

### 3b. Seedance 2.0 编号分镜音画绑定结构

15秒复刻段默认用 `秒数｜Shot 01–02` 执行块。检查：

- 开头有 `参考图角色`，且每张图只绑定一个主用途。
- 通常有 3–8 个执行块，并按顺序覆盖分镜图上的全部 Shot。
- 每个执行块同时有 `画面 / 声音`；只有真实动作音才增加 `音效：<...>`，不存在 `音效：无` 或独立“声音执行”区。
- 场景、画面功能或声音模式变化时必须新开执行块；同期口播与旁白不能混块，短促静物 B-roll 单独成块。
- 人物身份图不传递背景或 Shot 皮肤状态；多场景 Part 有明确 Shot 场景图。
- B-roll 前后的原片硬切用匹配的场景、景别和产品位置完成，不增加溶解或重新起手推近。
- 手机 proof、产品名特写、洗后证明、结尾产品 close-up 等源片关键 beat 必须被写进对应 Shot 执行块。
- 每句口播仍绑定到原片对应的画面功能，不把产品名移到说话脸镜头。
- 每个目标动作只来自原片/分镜或明确产品翻译；每个音效对应画面里真实可见的动作。
- 最终提示词不出现 `Part1最终分镜图`、`AI改好分镜图`、`current-job` 这类 loop 内部词。

### 3c. 15秒口播容量

- 先读取 `voiceover-capacity-and-compression.md`；数值、自适应放宽和错误示例以该文件为唯一事实源。
- 画面时间行和 `speech_groups` 独立；不得每个分镜行新写一句。
- 默认声音组和容量不得因拆行规避；只有真实源片字速和声音模式证据才能触发源片匹配放宽。
- `replication_function_coverage.md` 必须由 checker 对照完整源片证据核验；容量 PASS 不能代替复刻功能 PASS。
- 提示词每个 Shot 块里的台词必须与 `director_plan.json` 完全一致，每句只出现一次，不得额外增句。
- 运行 `python3 tools/seedance_prompt_contract_qc.py --job-id <job-id> --stage pre_seedance_pack`；任一口播容量检查失败都不得提交 Seedance。

### 4. 音频边界

带 reference audio 时，先转写每段音频。相邻 Part 不得重复台词。

检查要求：

- PartX 最后一条 ASR 是本段最后一句。
- PartX 不包含 PartX+1 的第一句。
- PartX+1 不包含 PartX 的尾句。
- 如果一句话在 14.56s 结束，PartX 音频切到 14.56s 后补静音/环境声到 15s；PartX+1 从 14.56s 新句开始。

### 5. Request JSON

提交后保存 request JSON，并检查实际传入素材。不能只相信提示词。
Request JSON 必须使用当前选定的精确模型路由。用户未指定时，`rules/SEEDANCE_MODEL.json` 默认普通 `Seedance 2.0`：`model=ep-20260521101914-nwv8j`。用户明确说 Mini 或 Fast 时，分别使用对应 EP，不得重解释模型名。

```bash
python3 - <<'PY'
import json, sys
p=sys.argv[1]
data=json.load(open(p))
for item in data.get("content", []):
    if item.get("type")=="image_url":
        print("IMAGE", item["image_url"]["url"])
    if item.get("type")=="audio_url":
        print("AUDIO", item["audio_url"]["url"])
PY "<request.json>"
```

## 生成后

### 1. Take log

每次生成后更新 `Seedance_take_log.md`：

```text
Take 1 · changed: 首次生成 · seed: 默认 · verdict: keep/post/edit/re-roll/rewrite · evidence: 主目标是否达成
```

判断规则：

- 主目标达成、次要问题可剪辑/调色/静音处理：保留或后期修。
- 提示词正确但偶发坏帧：同提示词重抽，最多 2-3 次。
- 同一问题出现两次：重写，不再赌运气。
- 每次只改一个变量：seed、提示词一句、参考图一张、模式一个，不能同时改。

### 2. 抽帧

```bash
ffmpeg -y -i "<video.mp4>" \
  -vf "fps=1,scale=180:320,tile=8x5:padding=6:margin=6:color=white" \
  -frames:v 1 "<out>_contact_1fps.jpg"
```

护肤/泥膜视频重点看：

- 开头使用前问题是否可见，但不脏、不医疗化。
- 产品是不是目标产品形态。
- 白色泥膜是不是白色/乳白色，不是灰色泥。
- 毛巾/清水擦洗动作是否出现。
- 洗后皮肤是否更干净、更亮、更细腻。
- 最后口播是否是画面内人物开口，不是旁白。

### 3. 卡顿

```bash
ffmpeg -hide_banner -nostats -i "<video.mp4>" \
  -vf freezedetect=n=0.003:d=0.5 -an -f null - 2>&1 | rg 'freezedetect' || true
```

如果有 0.5s 以上冻结，先查提示词是否写了静止、停留、焦点锁、展示不要动等词。

### 4. 最终口播 ASR

拼接后转写最终视频，检查：

- 相邻 Part 没有重复句。
- 最后一段台词说完，没有变旁白。
- 品牌名/产品名没有被吞。

ASR 通过后再更新交付 HTML。

## 交付

客户验收默认提供：

- 原视频和生成视频并排、都可点击播放的 HTML。
- 最终视频文件。
- 1fps 抽帧图。
- 必要时保留 `音频边界质检.md`、request JSON 和提示词，方便复盘。
