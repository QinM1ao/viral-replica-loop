# Seedance 2.5 源忠实度契约

每个生成单元保存 schema-v5 `internal_traceability.json`。视觉事件、语义口播组、音频模式和可选深度分别建模：

```json
{
  "schema_version": 5,
  "fidelity_mode": "source_locked",
  "audio_mode": "generated_voiceover",
  "depth_reference": {"enabled": false},
  "source_rhythm_sha256": "<source_rhythm.json sha256>",
  "events": [
    {
      "stage": "阶段一",
      "source_beat_id": "sr001",
      "target_visual_action": "<源动作应用 visual_edits 后的完整结果>",
      "visual_edits": []
    }
  ],
  "speech_groups": [
    {
      "id": "sg001",
      "semantic_unit": "complete_sentence",
      "stage_span": ["阶段一", "阶段二", "阶段三"],
      "source_parts": [
        {"source_beat_id": "sr001", "text": "我真的"},
        {"source_beat_id": "sr002", "text": "恨不得把它"},
        {"source_beat_id": "sr003", "text": "焊在脸上"}
      ],
      "source_line": "我真的恨不得把它焊在脸上",
      "target_line": "我真的恨不得把它焊在脸上",
      "line_edits": [],
      "delivery": "single_continuous_block",
      "protected_terms": ["焊在脸上"]
    }
  ]
}
```

## 字段规则

- `audio_mode` 只能是 `generated_voiceover` 或 `original_master_postmix`。
- `depth_reference.enabled` 默认为 `false`。启用时补充 `qc_path` 与 `output_sha256`，并要求深度 QC 绑定相同源视频；关闭时 Prompt 与请求均不得出现视频参考。
- events 中每个源 beat 按顺序 exact-once。多个 beat 可以共享同一自然阶段，但每个事件的完整目标动作仍须出现在该阶段。
- `speech_groups.source_parts` 按源 beat 顺序 exact-once 覆盖全部 `confirmed_source_line`；同组 parts 拼接后还原 `source_line`。
- `semantic_unit` 只能是 `complete_sentence`、`complete_clause` 或 `standalone_utterance`。它描述可自然独立说出的语义块，不是 ASR 标点标签。
- `stage_span` 是连续、非空、按 events 顺序排列的自然阶段。不同 speech group 的 span 按顺序排列，可以相邻，不可交叉。
- `target_line` 只通过声明的 `line_edits` 从 `source_line` 得到。用户提供全新口播时，以审核后的新口播块作为目标证据，并记录对应用户原话。
- `generated_voiceover`：每组完整 `target_line` 只在 span 的首个阶段出现一组 `{}`，且该阶段明确写出覆盖范围。Prompt 全部花括号按顺序等于 speech groups。
- `original_master_postmix`：speech groups 只承担内部对齐；Prompt 的花括号和音频引用数量必须为零。
- 喷洒事件的目标动作必须包含可观察雾化过程：按压喷头、离开喷口立即分散、均匀细密的雾化微滴、短暂悬浮、落肤形成极细小水珠。
- Prompt 的 `【保持一致】`不超过 120 字，只承担跨阶段身份、数量、归属、状态和说话关系。

## 运行

```bash
python3 tools/seedance25_source_fidelity_qc.py \
  --source-rhythm "<job>/剧情分析/source_rhythm.json" \
  --traceability "<unit>/internal_traceability.json" \
  --prompt "<unit>/00_Seedance2.5_提示词.txt" \
  --user-directives "<job>/user_directives.txt" \
  --output "<unit>/source_fidelity_qc.json"
```

仅在 `depth_reference.enabled=true` 时追加：

```text
--depth-qc "<unit>/depth_reference_qc.json"
```

完成条件：schema、音频模式、可选深度、事件覆盖、语义口播组、逐字台词、内部标签、喷雾物理和 Prompt 放置全部通过，`overall=PASS`。
