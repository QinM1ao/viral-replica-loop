# job-012 One-pass 分镜视觉验收回放证据

## 结论

原先 3 套 compare/review 已收敛为 1 张 canonical compare + 1 次批量 checker。 输入不变时复用 4 组语义 PASS，不重生 compare，不发起 checker。

| 场景 | Compare | Semantic request | Checker | Requested families | Reused families | Active time | Wait time |
|---|---:|---:|---:|---:|---:|---:|---:|
| 改造前 job-012 证据 | 3 | 3 | 4 | 4 | 0 | 未记录 | 未记录 |
| Changed | 1 | 1 | 1 | 4 | 0 | 0.351130s | 0.000000s |
| Unchanged | 0 | 0 | 0 | 0 | 4 | 0.099039s | 0.000000s |

## 保留的硬保护

- Multi-Part 清洁泥膜仍检查 4 组 family：`geometry_appearance, identity_product_material_integrity, cross_part_continuity, skincare_progression`。
- Mixed fixture 中局部 FAIL 后，仍保留 3 组无关 PASS；修复只重开 `identity_product_material_integrity`。
- 确定性 preflight 失败时 checker 调用数为 0。
- GPT Image 合同在隔离副本中重新执行 `recomputed_real_contract`，共 63 项确定性检查。
- 回放只在临时隔离副本中运行；GPT Image 与 Seedance 调用数均为 0。

## 交付保护

- 现有 prompts、Seedance requests、已验证 26 秒视频与共享状态哈希不变：`True`。
- 执行基线 commit：`d94e372a0071081d7f155bb81596f796c45a44d5`；当时工作区 dirty=`True`，所以 JSON 同时固定了 6 个关键工具/规则哈希。
- 旧链路未记录 active/wait time，因此不伪造改造前时间对比；表中只报告实际可测数据。
