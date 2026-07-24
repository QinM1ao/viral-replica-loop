# 源片高还原复刻合同

这是新任务的默认复刻标准。复刻不是“参考后再创作”，也不是只保留剧情功能；默认执行 `source_locked + necessary_only`：能不改的必须不改，只开放确实必须变化的最小槽位。

## 默认锁定

以下内容默认继承原片，不需要用户逐项重申：

- 台词原用词、句序、重复、语气词、钩子句式、说话人和旁白/同期声层级。
- 重音、停顿、快慢变化和开口位置。
- 镜头顺序、场景、机位、景别、构图、动作阶段、动作落点和硬切关系。
- 角色数量、性别、人物关系和每个角色的故事功能。
- 产品出现次数、出现位置、证明镜头和收口方式。
- 完整复刻时的全部源 beat，包括被分析阶段标为 `removable` 的停顿、反应或产品镜头。

“更顺”“更像广告”“表达更高级”“语义差不多”“模型更容易生成”都不是修改理由。原句已经能用于当前产品时必须原样保留。例如“这个它很贵，但改善暗沉很牛”属于钩子，若产品事实没有冲突，就不能润色成另一句话。

## 只允许的最小变化

仅在以下情况开放局部变化：

- 用当前产品名替换旧产品名。
- 旧成分、包装、材质、功效或使用动作与当前 `product_profile.json` 明确冲突。
- 用批准人物替换旧人物身份，但保留原角色、场景、镜头和动作功能。
- 用户明确点名要求修改的文字或画面。
- 安全、审核或法律要求造成的最小必要变化。
- 用户明确要求缩短成片时，删除有证据标记的重复或填充内容。

台词变化写入 `speech_group.line_edits`；画面变化写入对应 beat 的 `visual_edits`。每项都必须包含精确 `from`、精确 `to`、允许的 `reason`、具体 `reason_detail`；`user_requested` 还必须绑定真实 `request_evidence`。不得用一个宽泛理由替换整句或重做整个镜头。

`request_evidence` 不是自由填写的备注字符串，必须绑定 `BRIEF.md` 或当前任务唯一的 `output/<current-job-id>/intake.json` 路径、SHA-256 和原请求摘录；另一个 job 的真实 intake 也无效。产品事实类画面变化还必须绑定 `product_profile.json` 证据。

## 导演计划合同

新计划使用 `version >= 6`，并必须包含：

```json
{
  "script_fidelity": {"mode": "source_locked"},
  "replication_fidelity": {
    "mode": "source_locked",
    "change_policy": "necessary_only",
    "duration_mode": "source_length",
    "user_request_evidence": null,
    "locked_visual_dimensions": [
      "shot_order",
      "scene",
      "camera",
      "framing",
      "action_stage",
      "action_timing",
      "hard_cuts"
    ]
  }
}
```

schema-v3 `source_rhythm.json` 是必需输入，不是可选参考；每个源 beat 必须有 scene、camera、framing、动作类型/峰值和进出转场事实。完整复刻的每个源 beat 必须按原顺序且恰好映射一次，而且每个 target beat 只能绑定一个 source beat；不得遗漏、重复、倒序、把多个源 beat 折成一个目标 beat，或把源硬切改成一个连续动作。只有 `execution_blocks` 可以把相邻 target beat 放进同一 Prompt 块，不能改变源 beat 的镜头边界和动作关系。

每个 target beat 的 `source_visual_action`、`source_line` 和 `source_speaker_mode` 必须逐 beat 机械继承所绑定 source beat，不能只在全片拼接后“总字数相同”。每个 beat 还必须包含 `visual_fidelity`，逐项列出 source/target 的 scene、camera、framing、action_stage 和 transition；source transition 与 action stage 要和 `source_rhythm.json` 一致，target 值必须保持相同。`target_visual_action` 有差异时必须登记一项 `visual_edits`。

`spoken_product_anchor` 不是必填广告句。原片没有念产品名时使用 `{"enabled": false}`，不得新增产品名口播；原片念了几次、在什么位置念，就按原次数和位置只替换产品名槽位。每次 `product_name` 编辑都必须绑定当前计划同一份 schema-v3 `source_rhythm.json` 的真实 path/hash、具体 beat 和精确 occurrence 字符区间，并由 hash-bound 独立视觉复核确认该词确属产品或品牌实体；作者自填 `spoken_product_names` 不足以放行。

## 时长

- intake 未提供目标时长时，`scripts/new-task.py` 用 `ffprobe` 把每个源视频的真实时长写入 job，不再默认 30 秒。
- 默认 `duration_mode=source_length`：不因略长而删完整台词、压缩镜头、重分配节拍或变速。
- 只有用户明确提供更短目标时长，且 `intake.json` 有结构化证据，才使用 `user_compressed`。
- `duration_compression` 只能删除，不能替换或改写；删除仍不能满足容量时返回 `FAIL/STOP`。

## 完成条件

生成前必须同时产生并检查：

- `voiceover/source_script_fidelity.md`：逐句原台词、必要局部编辑和目标台词。
- `voiceover/source_replication_fidelity.md`：逐 beat 原动作、必要画面编辑、目标动作和锁定维度。
- `source_rhythm_qc`：完整复刻时全部源 beat exact-once、顺序不变、源动作文本绑定。
- `source_rhythm_visual_review_qc`：独立检查全部 source beat，包括 `removable`，并绑定 schema v3 与当前 source-rhythm hash。
- `source_to_generation_fidelity` 独立检查：核对每项声明变化确实必要，且没有未登记的台词或镜头发挥。

只做到“叙事功能覆盖”不能 PASS；功能覆盖只是附加检查，不是高还原复刻的充分条件。
