# GPT Image Shot 编号保留实测

这是一份验证证据，不是操作规则。GPT Image 改图的唯一操作事实源是：

```text
.agents/skills/video-replication/references/codex-imagegen-direct.md
```

## 验证结论

2026-07-14 使用项目 Matpool GPT-Image-2 真实 edit 接口，对 `job-001` Part 1 做了单变量测试：源分镜、产品图、人物图、模型、质量和尺寸保持不变，只强化 Shot 导航栏约束。

| 对照 | 结果 | Shot 编号 |
|---|---|---|
| 旧正式成品 | FAIL | 0/12 |
| 新实测候选 | PASS | 12/12 |

新候选同时完成了人物替换、产品替换和 panel 内字幕清理。真实调用耗时 `78.075s`，输出 SHA-256：

```text
a4b4a903ddd2ac929dd98bd611772c9db7c124cc91a3f7dfccff062315ba01d0
```

## 固定测试输入

- 源分镜：`output/job-001/storyboard_source_refs/source_storyboard_part1.jpg`
- 产品正面：`output/shared/kongfengchun/products/kongfengchun_fermented_toner/product_front.png`
- 产品开盖：`output/shared/kongfengchun/products/kongfengchun_fermented_toner/product_open_or_cap.png`
- 人物身份：`output/shared/kongfengchun/identities/kongfengchun_female_generated/identity_ref.png`
- 模型：`GPT-Image-2`
- 质量：`medium`
- 尺寸：`864x1248`

## 实测证据

- 候选图：`output/job-001/experiments/shot-label-retention/part1_preserve_shot_labels_candidate.png`
- 生产提示词：`output/job-001/experiments/shot-label-retention/part1_preserve_shot_labels_prompt.md`
- Matpool 调用记录：`output/job-001/experiments/shot-label-retention/matpool_invocation.json`
- RED 结果：`output/job-001/experiments/shot-label-retention/red_existing_output.json`
- GREEN 结果：`output/job-001/experiments/shot-label-retention/green_generated_output.json`
- 项目 geometry QC：`output/job-001/experiments/shot-label-retention/storyboard_geometry_qc.json`，结果 `PASS`

自动测试检查 12 个 Shot 导航栏在源图相对位置附近是否仍有青色标签；人工检查逐项读了 `Shot 01-12`，确认顺序和 panel 对应关系正确。自动检测只做辅助，最终 PASS 仍以逐项视觉检查为准。

## 写回项目的决定

- 通用 product profile 把 `shot_labels` 列为源分镜必须传递的结构。
- GPT Image contract 缺少 `shot_labels` 时不能 PASS。
- `storyboard_geometry_review.json` 必须包含 `shot_labels_preserved=true`。
- `SKILL.md` 的步骤②/③以 canonical direct-edit reference 的 completion criterion 为完成条件。
- Seedance 可以使用带 Shot 导航栏的已批准分镜图做镜头寻址，但最终视频画面仍不显示网格、边框或编号。

一次真实 PASS 证明这条路径可行，但不代表随机生成永远稳定，因此每个 Part 都必须单独验收，不能把本案例当成永久豁免。

## 2026-07-20 流程接入回归

`job-012` 的两张当前 Matpool 分镜都经过确定性 Shot-label metadata-only 处理，再以原字节 hash 同步到 final images。验证证据：

- `output/job-012/checks/part1_shot_label_restore.json`
- `output/job-012/checks/part2_shot_label_restore.json`
- `output/job-012/checks/image_batch_qc_visual_asset_manifest_qc.json`

两个 Part 均记录 `outside_label_changed_pixels=0` 和 `panel_pixels_modified=false`，证据输出 hash 与 promoted image hash 一致。完整单元测试 190 项通过，`job-012` 从零验收测试通过，runner 的 `image_batch_qc` PASS preflight 也接受该 schema-v2 证据。操作规则仍只在本文开头指向的唯一事实源中维护。
