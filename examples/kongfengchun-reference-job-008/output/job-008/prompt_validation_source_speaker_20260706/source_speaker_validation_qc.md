# Seedance Prompt Contract QC

- Overall: **PASS**
- Shot-line map: `output/job-008/prompt_validation_source_speaker_20260706/shot_line_map.md`

## Prompt Files

### `output/job-008/prompt_validation_source_speaker_20260706/Part1_Seedance提示词_源声音继承版.txt`

- Overall: **PASS**
- Metrics: part=1, chars=1481, map_rows=7, time_ranges=10, quoted_lines=8
- PASS: `part1_has_参考图角色` - `参考图角色` found
- PASS: `part1_has_@图片1` - `@图片1` found
- PASS: `part1_has_@图片2` - `@图片2` found
- PASS: `part1_has_主目标` - `主目标` found
- PASS: `part1_has_次目标` - `次目标` found
- PASS: `part1_has_简化` - `简化` found
- PASS: `part1_has_禁止BGM` - `禁止BGM` found
- PASS: `part1_three_shots` - shots=[1, 2, 3]
- PASS: `part1_variable_time_axis` - unique_ranges=10, required>=7
- PASS: `part1_shot1_has_internal_timing` - ranges=['0.0-5.4s', '0.0-1.8s', '1.8-3.6s', '3.6-5.4s']
- PASS: `part1_shot2_has_internal_timing` - ranges=['5.4-9.8s', '5.4-7.4s', '7.4-9.8s']
- PASS: `part1_shot3_has_internal_timing` - ranges=['9.8-15.0s', '9.8-12.2s', '12.2-15.0s']
- PASS: `part1_covers_shot_line_map_times` - all map target ranges are present
- PASS: `part1_source_speaker_modes_present` - all rows include source speaker mode
- PASS: `part1_preserves_source_speaker_modes` - target speaker modes match source speaker modes
- PASS: `part1_prompt_matches_target_speaker_modes` - prompt speaker labels match shot-line map target modes
- PASS: `part1_no_loop_only_labels` - hits=[]
- PASS: `part1_no_ambiguous_key_shot_alternatives` - hits=[]
- PASS: `part1_product_ref_identity_not_composition` - product refs use calibration wording and defer composition/action to @图片1
- PASS: `part1_global_motion_constraint` - requires visible motion / no continuous static shot wording
- PASS: `part1_quoted_lines_have_speaker_mode` - unlabeled=[]
- PASS: `part1_proof_shots_follow_source_speaker_mode` - product/hand/phone/proof shots use the source speaker mode instead of object-type defaults

### `output/job-008/prompt_validation_source_speaker_20260706/Part2_Seedance提示词_源声音继承版.txt`

- Overall: **PASS**
- Metrics: part=2, chars=1497, map_rows=7, time_ranges=10, quoted_lines=7
- PASS: `part2_has_参考图角色` - `参考图角色` found
- PASS: `part2_has_@图片1` - `@图片1` found
- PASS: `part2_has_@图片2` - `@图片2` found
- PASS: `part2_has_主目标` - `主目标` found
- PASS: `part2_has_次目标` - `次目标` found
- PASS: `part2_has_简化` - `简化` found
- PASS: `part2_has_禁止BGM` - `禁止BGM` found
- PASS: `part2_three_shots` - shots=[1, 2, 3]
- PASS: `part2_variable_time_axis` - unique_ranges=10, required>=7
- PASS: `part2_shot1_has_internal_timing` - ranges=['0.0-5.4s', '0.0-1.8s', '1.8-3.6s', '3.6-5.4s']
- PASS: `part2_shot2_has_internal_timing` - ranges=['5.4-9.8s', '5.4-7.6s', '7.6-9.8s']
- PASS: `part2_shot3_has_internal_timing` - ranges=['9.8-15.0s', '9.8-12.4s', '12.4-15.0s']
- PASS: `part2_covers_shot_line_map_times` - all map target ranges are present
- PASS: `part2_source_speaker_modes_present` - all rows include source speaker mode
- PASS: `part2_preserves_source_speaker_modes` - target speaker modes match source speaker modes
- PASS: `part2_prompt_matches_target_speaker_modes` - prompt speaker labels match shot-line map target modes
- PASS: `part2_no_loop_only_labels` - hits=[]
- PASS: `part2_no_ambiguous_key_shot_alternatives` - hits=[]
- PASS: `part2_product_ref_identity_not_composition` - product refs use calibration wording and defer composition/action to @图片1
- PASS: `part2_global_motion_constraint` - requires visible motion / no continuous static shot wording
- PASS: `part2_quoted_lines_have_speaker_mode` - unlabeled=[]
- PASS: `part2_proof_shots_follow_source_speaker_mode` - product/hand/phone/proof shots use the source speaker mode instead of object-type defaults
