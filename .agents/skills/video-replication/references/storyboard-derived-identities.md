# 无模特多人原片的分镜派生身份流程

本分支仅在用户没有提供模特/人物图，且原片出现多个不同人物时启用。内部 intake 值为 `person_assets=storyboard_derived`。

这仍是标准视频复刻流程的一个图像分支，不是另起一套流程。剧情分析、原台词锁定、分镜顺序、产品替换、图像审核、Pre-Seedance pack 和各阶段 Gate 保持不变。

## 角色表先于改图

在第一次 ImageGen 前建立稳定角色 ID，至少记录：

- `id`：例如 `role_A`、`role_D`。
- `gender`：保留原片角色性别。
- `source_role`：主持人、顾客、同事、路人、群体等故事功能。
- `parts`：角色实际出现的 Part。
- `identity_required`：只有口播、近景、关键操作或跨 Part 复现的角色设为 `true`。

背景人群、短暂路人和不需要跨镜一致的人物保持泛化/去识别，不为每一张脸生成身份图。

## 标准顺序

1. **用原 Part 分镜做直接编辑。** 实际提交原分镜和产品图给 Matpool GPT-Image-2，不提供人物参考。提示词要求每个旧人物替换为新的、写实的同性别角色，同时保留角色关系、场景、景别、手位、动作和 Shot 顺序；产品换成当前产品，去掉 panel 内旧字幕/花字。
2. **先审核分镜。** 新人物的真实感、性别、角色映射、产品和分镜几何同时通过后，该 Part 才能成为身份来源。
3. **从已批准分镜派生专用人物图。** 对 `identity_required=true` 的角色，使用当前 job 已批准分镜作为身份来源，通过 Matpool 生成真实感强、正脸清楚的单人上半身图。不得直接裁切原视频人脸，不得用来源分镜中的旧人物，不带产品、字幕、其他人或复杂背景。
4. **跨 Part 先传身份。** 如果 `role_A` 在 Part1 和 Part2 都出现，Part1 批准后立即生成 `role_A` 身份图；改 Part2 时将该图作为约束输入。未通过的 Part 不能作为身份来源。
5. **后出现的新角色后派生。** 只在 Part2 首次出现的角色，先在 Part2 的直接编辑中产生；Part2 通过后再派生其身份图，供 Part2 Seedance 或更后续 Part 使用。
6. **Seedance 只传当前 Part 需要的人物。** 每个 Part 使用自己的 `01` 分镜、产品图和该 Part 实际出现的身份图。不把 Part1 独有人物传给 Part2，也不把一个主角身份套到所有人上。

## 图像提示词边界

无人物参考的第一次分镜编辑中：

- 图1是唯一场景/构图/动作事实源。
- 图2/3只锁定目标产品。
- 人物可重新生成，但必须按 role map 一对一保留原角色性别和故事功能。
- 不用“更好看的模特”、“统一主角”等指令改掉多人关系。

已有分镜派生身份图的后续 Part 编辑中：

- 原 Part 分镜仍是编辑对象。
- 目标产品图仍只锁产品。
- 每张人物图只锁定对应 role 的脸、发型、身体和服装，不传递其背景、构图或其他人。

## Seedance 参考图开头

最终 prompt 使用标准定义句：

```text
参考图角色：
@图片1定义为“分镜板”，只控制镜头顺序、景别、动作节奏和场景关系；不传递分镜网格、边框、文字、旧产品及旧人物身份。
@图片2中的产品定义为“目标产品”，只锁定包装、标签、结构和材质；不传递白底或棚拍背景，不控制镜头构图、场景、手部位置或动作节奏。
@图片4中的人物定义为“角色A”，只锁定脸、发型、身体、服装和身份一致性；不传递参考图背景、构图、无关人物或其他角色身份。
@图片5中的人物定义为“角色D”，只锁定脸、发型、身体、服装和身份一致性；不传递参考图背景、构图、无关人物或其他角色身份。
```

当前 Part 只有一个需要锁定的角色时只写一条。人物过多时，保留口播/近景/跨 Part 角色的身份图，其余由已批准分镜约束。

## Manifest 合同

ImageGen 生成证据不得伪造一张不存在的 `identity_ref`。无人物图的首次分镜编辑在 Part contract 中声明：

```json
{
  "person_asset_mode": "storyboard_derived",
  "identity_strategy": "generate_from_source_roles_then_derive",
  "role_map": "output/<job-id>/visual-assets/role_map.json",
  "role_map_loaded_to_context": true
}
```

该次 `refs_loaded` 只列真实提交的原分镜和产品图。当后续 Part 已有派生身份图时，使用 `identity_strategy=reuse_storyboard_derived_roles`，并在 `refs_loaded` 和 `reference_order` 中如实列出 `identity_role_A`、`identity_role_D` 等实际输入。

`approved_visual_manifest.json` 必须包含：

```json
{
  "person_asset_mode": "storyboard_derived",
  "role_map": "output/<job-id>/visual-assets/role_map.json",
  "identity_role_manifests": {
    "role_A": "output/<job-id>/visual-assets/identities/role_A_manifest.json"
  },
  "part_identity_roles": {
    "part1": ["role_A"],
    "part2": ["role_A", "role_F"]
  },
  "part_reusable_refs": {
    "part1": {"identity_role_A": "output/<job-id>/visual-assets/identities/role_A.png"},
    "part2": {
      "identity_role_A": "output/<job-id>/visual-assets/identities/role_A.png",
      "identity_role_F": "output/<job-id>/visual-assets/identities/role_F.png"
    }
  }
}
```

每个身份 manifest 记录 `asset_group_type=identity_group`、`identity_id`、`role_id`、`presenter_gender`、`origin=storyboard_derived`、`source_job_id`、`source_part`、`source_storyboard` 和 `identity_ref`。`source_storyboard` 必须是当前 job 中已批准的对应 Part 分镜。

## 完成条件

该分支只有在以下条件全部成立时才完成：

1. 无人物图的 intake 被记为 `storyboard_derived`，不因缺少模特图阻塞。
2. role map 在 ImageGen 前存在，且每个多人角色的性别/故事功能未被改掉。
3. 每个身份图来自当前 job 已批准的分镜，其来源 manifest 完整。
4. 跨 Part 角色在后续 Part 改图和 Seedance 中使用同一张已批准身份图。
5. 每个 Part 的上传包只包含该 Part 实际需要的人物图，且角色绑定与 prompt 一致。
6. `tools/visual_asset_manifest_qc.py` 和统一分镜视觉验收都为 `PASS`。
