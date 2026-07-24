# 原台词锁定合同

这是视频复刻中台词与发声节奏的唯一事实源。默认模式是 `source_locked`，不是“保留原意后改写”。

## 默认规则

- 从 `source_rhythm.json` 中取经 ASR、字幕和画面证据确认的原台词。
- 保留原句的用词、句序、重复、语气词、说话人、旁白/同期声层级、重音和停顿位置。
- 不得为了“更顺”、“更像广告”、“更适合新产品”而改写整句。保留功能不等于保留原台词。
- 目标台词必须等于“原台词 + 已声明的局部编辑”；没有声明的字词变化都是失败。
- 吸引力、广告顺滑度、措辞偏好和“语义更清楚”都不是修改理由。事实没有变化的钩子必须逐字保留；例如“这个它很贵，但改善暗沉很牛”不能润色成“虽然价格高但提亮效果很好”。
- 本文件只负责台词层；镜头、动作、硬切和时长的默认锁定同时服从 `source-replication-contract.md`。

## 允许改的特定部分

只允许以下理由，且每一处都要在对应 `speech_group.line_edits` 中登记：

| `reason` | 何时可用 |
|---|---|
| `product_name` | 把旧品牌/产品名替换为当前 job 的完整产品名 |
| `product_fact` | 旧成分、形态、使用方式或功效与当前 product profile 冲突 |
| `person_or_role` | 用户指定要更换的人名、称呼或角色关系 |
| `price_or_offer` | 价格、赠品、活动或购买条件已不成立 |
| `duration_compression` | 目标时长确实放不下，只删除重复/填充片段 |
| `user_requested` | 用户明确指定的局部台词变更 |

每条编辑必须包含：

```json
{
  "kind": "replace",
  "from": "原句中唯一的精确片段",
  "to": "目标片段",
  "reason": "product_name",
  "reason_detail": "用当前 job 产品名替换旧产品名"
}
```

`kind` 只能是 `replace` 或 `delete`。`from` 默认必须在当前原句中唯一出现；同一旧产品名重复出现时，每次编辑必须用 1-based `occurrence` 精确指定当前句中的那一次，不能因为重复就合并或删掉。`delete` 的 `to` 必须为空。`product_name` 的 `to` 必须等于 job 的 `product_name`。

`product_name` 也只能替换产品名槽位。每一次局部或整句 `product_name` 编辑都必须写 `source_slot_evidence`，绑定当前 director plan 同一份 schema-v3 `source_rhythm.json` 的真实 path/hash、beat id、`spoken_product_names` 和精确文字；独立视觉复核还必须确认该词确属产品或品牌实体。若同一文字出现多次，`occurrence` 命中的字符区间必须实际落在该证据 beat 内，不能拿后一个产品实体为前一个普通词背书。

`product_fact` 和 `price_or_offer` 必须写 `fact_evidence`，绑定当前 job 的 `product_profile.json` 真实 path/hash、当前编辑的精确 `source_slot` / `target_slot`、冲突类型、目标处理策略和至少一个真实 JSON Pointer 引用。`product_fact` 只接受产品形态、功效、成分、频率、替代性宣称或使用动作冲突；`price_or_offer` 只接受已失效活动或无当前证据支持的优惠。资料未提及某项事实不等于与原片冲突：尤其不能因为 profile 没有频次字段，就把“一天喷一次/两次”改成“按需”。频次只有在当前 profile 明确写出不同频次，且 `contradicted_frequency` 的引用直接包含目标频次时才允许修改。`person_or_role` 必须像 `user_requested` 一样绑定 BRIEF 或当前 job intake 的结构化 `request_evidence`，不能用于删口头语、改语气或润色句子。`duration_compression` 只能在 `replication_fidelity.duration_mode=user_compressed` 且 intake 证据有效时执行 `delete`，不能用 `replace` 重写。

Pre-Seedance 独立 checker 必须逐条返回 `Line edit results`：每个编辑 ID 都要说明是否必要、是否已经缩到最小槽位、是否核对过证据以及结论。少一条、只写整体 PASS，或任一编辑没有核对证据，都不能 PASS。

## 压缩时长的顺序

1. 先按原片测得语速分配台词，不因为目标时长较短就自动改句。
2. 容量确实不足时，先删除原片中可证明的重复或填充片段，使用 `duration_compression` 登记。
3. 保留原句骨架、句序、快慢交替和收口方式；不新建一套“冲突—卖点—下单”文案。
4. 如果删除仍无法通过发声容量门禁，返回 `FAIL/STOP`，不允许自由改写蒙混过关。

## 最终 Seedance 提示词

- 开头固定为 `参考图角色：`，然后每张图按“定义为什么 → 只控制/锁定什么 → 不传递什么”写。
- 不使用“控制校准”这类模糊开头，不在最终 prompt 中写纠错过程。
- 每个 `时间｜Shot` 执行块中的 `声音：` 必须机械继承已验证的 `speech_group.line`，不得在 prompt 阶段再次润色。
- `delivery_note` 只控制语速、情绪、重音、停顿和口型归属，不得携带新台词。

## 产物与完成条件

新流程必须生成：

- `output/<job-id>/seedance/director_plan.json`，`version >= 6`、`script_fidelity.mode=source_locked` 且 `replication_fidelity.change_policy=necessary_only`。
- `output/<job-id>/voiceover/source_script_fidelity.md`，逐句列出原台词、登记编辑和目标台词。
- `voiceover.md`、`shot_line_map.md` 和每个 Part 的最终 prompt，台词与 `director_plan.json` 完全同步。

以下任一情况为 `FAIL`：

- 新流程缺少 `line_edits`，或存在未声明改写。
- 原台词只剩“语义相似”，用词、句序、重复和节奏被改掉。
- `voiceover.md`、`shot_line_map.md`、prompt 中的台词与计划不同。
- 用对原片的形容词代替可执行台词，或让模型“自然改写”。

## 本轮经验

冰喷 2 测试中，把原片台词重写成一组功能相似的通用电商句，虽然结构看似正确，但原句的重复、短促反应和说话节奏已丢失。这不属于复刻。纠正后的默认原则是：先锁原句，再只替换用户或产品事实要求改的槽位。
