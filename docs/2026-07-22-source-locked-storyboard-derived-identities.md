# 2026-07-22 冰喷 2 经验回写

## 结论

这次验证了一个可用的图像分支：当用户没有提供模特，且原片是多个不同人物的混剪时，可以先在原分镜上替换产品并生成新人物，分镜通过后再派生独立、写实的人物身份图。

这次也暴露了台词流程的错误：把原片台词压成“功能、句式和情绪类似”的新文案，即使剧情顺序没变，也不是用户要的复刻。从本次起，默认台词合同改为“原台词锁定，只改特定槽位”。

## 验证过的图像结论

- 原分镜+产品图在不提供模特图时，可以生成多个新人物，不必强行设置一个固定主角。
- 角色还是要保留原片性别、故事功能和重复出现关系，不能把多人全部统一成一个模特。
- 需要给 Seedance 的人物图应由 GPT-Image-2 从已批准的当前 job 分镜重新生成，不是简单裁切 panel，也不是抽原片旧人脸。
- 只为口播、近景、关键操作和跨 Part 角色生成身份图。背景人群继续由已批准分镜约束。
- 原角色明确跨 Part 时，后续 Part 改图要加入前一 Part 派生的同一身份图。只是故事功能相同，但原片是不同人时，不得强行合并。

图像证据位于：

`output/research-competitor-cases-20260722/experiments/ice-spray2-storyboard-derived-identities/`

## 台词纠错

历史对照稿曾使用下列处理：合并三轮重复反差句、把问题/成分句重写成新产品的句子、将多人短评改成另一组短评。这种做法只保留了文案功能，没有保留原台词，应判为失败。

新默认规则：

1. 原台词按证据逐句锁定，保留原用词、句序、重复、说话人、重音和停顿。
2. 产品名、不适用当前产品的事实、角色称呼、价格/活动和用户明确指定处才可替换。
3. 每处替换/删除在 `speech_group.line_edits` 中声明；目标句必须精确等于原句应用这些操作后的结果。
4. 60 秒压到 30 秒也不允许自由改写。先按原片语速压缩；仍超容量时，只删可证明的重复/填充片段，并保留原句骨架和顺序。
5. 最终 prompt 不另写台词，只机械渲染已验证的目标句。

台词事实源：`.agents/skills/video-replication/references/source-script-lock.md`。

## 标准提示词开头

固定使用：

```text
参考图角色：
@图片1定义为“分镜板”，只控制……；不传递……。
@图片2中的产品定义为“目标产品”，只锁定……；不传递……。
@图片4中的人物定义为“角色A”，只锁定……；不传递……。
```

不再根据操作人临时切换成“控制校准”、“综合参考”或其他自由格式。

## 已回写的位置

- 主方法：`.agents/skills/video-replication/SKILL.md`
- 原台词锁定：`.agents/skills/video-replication/references/source-script-lock.md`
- 无模特多人分支：`.agents/skills/video-replication/references/storyboard-derived-identities.md`
- Seedance 格式：`.agents/skills/video-replication/references/seedance-20-prompt-standard.md`
- 执行与门禁：`workers/pre_seedance_pack_worker.md`、`gates/pre_seedance_pack_gate.md`、`workers/image_batch_worker.md`、`gates/image_batch_gate.md`
- 自动合同：`tools/pre_seedance_pack.py`、`tools/source_rhythm_qc.py`、`tools/visual_asset_manifest_qc.py`

## 本轮边界

本轮更新流程与验收规则，没有重跑冰喷 2 的付费图像或 Seedance 视频生成。原有冰喷 2 分镜/人物图作为图像分支证据；其旧台词对照稿作为反例，不是新标准的 PASS 产物。
