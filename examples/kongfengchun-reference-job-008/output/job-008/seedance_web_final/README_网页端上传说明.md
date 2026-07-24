# job-008 Seedance 网页端上传说明

目标：在 Seedance 网页端手动生成两段 15 秒视频，最终拼成约 30 秒；本 loop 到生成前停止，不提交付费/API 生成。

## 推荐生成设置

- Route：真人脸素材库 / 参考图生视频，优先 face-safe 路线。
- Model：SD 2.0 mini (`ep-20260625155850-zpss5`)。
- taskCode：`2509`。
- Ratio：`9:16`。
- Duration：每段 `15s`。
- Audio：开启声音生成，并上传对应 Part 的 `06` 音频。
- BGM：不要开启配乐；提示词已写禁止 BGM。

## Part1 上传顺序

目录：`output/job-008/seedance_web_final/Part1_上传素材/`

1. `01_图片1_Part1分镜节奏.png`
2. `02_图片2_孔凤春清洁泥膜正面.png`
3. `03_图片3_开盖白泥.png`
4. `04_图片4_男模身份content4.png`
5. `05_图片5_洗后脸部特写.png`
6. `06_音频1_Part1原爆款声音参考.mp3`

提示词：`output/job-008/seedance_web_final/prompts/Part1_Seedance提示词.txt`

## Part2 上传顺序

目录：`output/job-008/seedance_web_final/Part2_上传素材/`

1. `01_图片1_Part2分镜节奏.png`
2. `02_图片2_孔凤春清洁泥膜正面.png`
3. `03_图片3_开盖白泥.png`
4. `04_图片4_男模身份content4.png`
5. `05_图片5_洗后脸部特写.png`
6. `06_音频1_Part2原爆款声音参考.mp3`

提示词：`output/job-008/seedance_web_final/prompts/Part2_Seedance提示词.txt`

## 关键提醒

- 两段分开生成，每段只用对应 Part 目录里的素材和对应提示词。
- 上传图不要混用中间候选目录，只用 `seedance_web_final` 里的 active 文件。
- 参考音频只用于声音质感、语速、停顿和直播感；提示词里的中文才是目标口播。
- Part2 的 `05` 洗后脸参考只在水洗和毛巾擦干之后使用。
