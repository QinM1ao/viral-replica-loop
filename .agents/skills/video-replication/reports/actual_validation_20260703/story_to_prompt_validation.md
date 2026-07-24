# Story-To-Prompt Actual Validation

Date: 2026-07-03

## Conclusion

Overall: **PASS**

This is a same-case live regeneration validation. It proves that the updated `video-replication` skill standard can guide Codex to regenerate prompts at the same structural and key-beat level for the known `job-001` case.

It is not a blind holdout and not a provider-backed model eval. It does not yet prove generalization to a new unseen video.

## Inputs

- `.agents/skills/video-replication/SKILL.md`
- `.agents/skills/video-replication/references/seedance-20-prompt-standard.md`
- `output/job-001/剧情分析/剧情分析.md`
- `output/job-001/分镜/分镜表与缝点审查.md`
- `output/job-001/voiceover/voiceover.md`
- `output/job-001/seam/seam_design.md`
- `output/job-001/product_profile.json`
- `output/job-001/visual-assets/approved_visual_manifest.json`

## Generated Outputs

- `.agents/skills/video-replication/reports/actual_validation_20260703/regenerated_part1_prompt.txt`
- `.agents/skills/video-replication/reports/actual_validation_20260703/regenerated_part2_prompt.txt`

## Golden References

- `output/job-001/seedance_v3_1_ordinary_2_0_20260703/prompts/part1_seedance_prompt_v3_1_ordinary_2_0_tiny_ref_fix.txt`
- `output/job-001/seedance_v3_1_ordinary_2_0_20260703/prompts/part2_seedance_prompt_v3_1_ordinary_2_0.txt`

## Results

| Check family | Part1 | Part2 |
|---|---:|---:|
| Reference roles | PASS | PASS |
| Core shape | PASS | PASS |
| 3-shot structure | PASS | PASS |
| Speaker layering | PASS | PASS |
| Product reference binding | PASS | PASS |
| Motion constraint | PASS | PASS |
| No BGM / no on-screen dialogue text | PASS | PASS |
| No banned workflow or ambiguous alternative terms | PASS | PASS |
| Required story beats | PASS | PASS |
| Product shots do not mouth narration | PASS | PASS |
| Similarity to final successful prompt | 0.902 | 0.923 |

## Boundary

This validation is strong enough to update the skill scorecard from "no actual output validation" to "same-case prompt regeneration PASS".

It is not enough to mark the governed package release-ready. A future validation should use a different source video as a blind or semi-blind holdout.
