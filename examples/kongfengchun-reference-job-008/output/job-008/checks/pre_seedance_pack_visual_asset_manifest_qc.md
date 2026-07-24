# Visual Asset Manifest QC

- Overall: **PASS**
- Job: `job-008`
- Stage: `pre_seedance_pack`
- Manifest: `output/job-008/visual-assets/approved_visual_manifest.json`

## Checks

- PASS: `job_exists` - job-008
- PASS: `product_profile_exists` - output/job-008/product_profile.json
- PASS: `product_profile_job_id` - profile=job-008 expected=job-008
- PASS: `product_profile_loads_generic_rule` - {"profile_job_id": "job-008", "brand_id": "kongfengchun", "category_id": "clay_mask", "sku_id": "kongfengchun_clean_mud_mask", "loaded_rules": ["generic:generic_product", "category:clay_mask", "brand:kongfengchun", "sku:kongfengchun_clean_mud_mask"], "skipped_rules": []}
- PASS: `approved_visual_manifest_exists` - output/job-008/visual-assets/approved_visual_manifest.json
- PASS: `visual_manifest_job_id` - manifest=job-008 expected=job-008
- PASS: `product_group_manifest_exists` - output/shared/kongfengchun/products/kongfengchun_clean_mud_mask/manifest.json
- PASS: `identity_group_manifest_exists` - output/shared/kongfengchun/identities/kongfengchun_male_content4/manifest.json
- PASS: `product_group_type` - product_group
- PASS: `product_group_id` - manifest=kongfengchun_clean_mud_mask visual=kongfengchun_clean_mud_mask
- PASS: `product_name_binding` - job=孔凤春清洁泥膜 group=孔凤春清洁泥膜
- PASS: `product_source_assets_binding` - group=<kongfengchun-assets>/泥膜 job=<kongfengchun-assets>/泥膜
- PASS: `product_front_ref_exists` - output/shared/kongfengchun/products/kongfengchun_clean_mud_mask/product_front_tight.png
- PASS: `product_open_mud_ref_exists` - output/shared/kongfengchun/products/kongfengchun_clean_mud_mask/product_open_white_mud_tight.png
- PASS: `identity_group_type` - identity_group
- PASS: `identity_group_id` - manifest=kongfengchun_male_content4 visual=kongfengchun_male_content4
- PASS: `identity_person_asset_binding` - allowed=<kongfengchun-assets>/模特/男/content 4.png job_person_assets=<kongfengchun-assets>/模特
- PASS: `identity_ref_exists` - output/shared/kongfengchun/identities/kongfengchun_male_content4/identity_ref.png
- PASS: `afterwash_face_ref_exists` - output/shared/kongfengchun/identities/kongfengchun_male_content4/afterwash_face_closeup.png
- PASS: `reusable_ref_product_front` - actual=output/shared/kongfengchun/products/kongfengchun_clean_mud_mask/product_front_tight.png expected=output/shared/kongfengchun/products/kongfengchun_clean_mud_mask/product_front_tight.png
- PASS: `reusable_ref_product_open` - actual=output/shared/kongfengchun/products/kongfengchun_clean_mud_mask/product_open_white_mud_tight.png expected=output/shared/kongfengchun/products/kongfengchun_clean_mud_mask/product_open_white_mud_tight.png
- PASS: `reusable_ref_identity_ref` - actual=output/shared/kongfengchun/identities/kongfengchun_male_content4/identity_ref.png expected=output/shared/kongfengchun/identities/kongfengchun_male_content4/identity_ref.png
- PASS: `reusable_ref_afterwash_face` - actual=output/shared/kongfengchun/identities/kongfengchun_male_content4/afterwash_face_closeup.png expected=output/shared/kongfengchun/identities/kongfengchun_male_content4/afterwash_face_closeup.png
- PASS: `part_storyboard_part1_asset_type` - AI改好分镜图
- PASS: `part_storyboard_part1_route` - matpool_gpt_image_2_edit
- PASS: `part_storyboard_part1_no_source_pixels_flag` - False
- PASS: `part_storyboard_part1_path_exists` - output/job-008/final-images/part1_seedance_ref.png
- PASS: `part_storyboard_part1_under_active_job` - output/job-008/final-images/part1_seedance_ref.png
- PASS: `part_storyboard_part1_filename_not_forbidden` - part1_seedance_ref.png
- PASS: `part_storyboard_part2_asset_type` - AI改好分镜图
- PASS: `part_storyboard_part2_route` - matpool_gpt_image_2_edit
- PASS: `part_storyboard_part2_no_source_pixels_flag` - False
- PASS: `part_storyboard_part2_path_exists` - output/job-008/final-images/part2_seedance_ref.png
- PASS: `part_storyboard_part2_under_active_job` - output/job-008/final-images/part2_seedance_ref.png
- PASS: `part_storyboard_part2_filename_not_forbidden` - part2_seedance_ref.png
- PASS: `active_dirs_no_forbidden_visual_names` - []
- PASS: `final_upload_dir_exists` - output/job-008/seedance_web_final
- PASS: `final_upload_no_deprecated_drafts` - []
- PASS: `final_part1_dir_exists` - output/job-008/seedance_web_final/Part1_上传素材
- PASS: `final_part1_01_single_image` - ["01_图片1_Part1分镜节奏.png"]
- PASS: `final_part1_01_matches_manifest` - actual=output/job-008/seedance_web_final/Part1_上传素材/01_图片1_Part1分镜节奏.png expected=output/job-008/final-images/part1_seedance_ref.png
- PASS: `final_part1_02_single_image` - ["02_图片2_孔凤春清洁泥膜正面.png"]
- PASS: `final_part1_02_matches_manifest` - actual=output/job-008/seedance_web_final/Part1_上传素材/02_图片2_孔凤春清洁泥膜正面.png expected=output/shared/kongfengchun/products/kongfengchun_clean_mud_mask/product_front_tight.png
- PASS: `final_part1_04_single_image` - ["04_图片4_男模身份content4.png"]
- PASS: `final_part1_04_matches_manifest` - actual=output/job-008/seedance_web_final/Part1_上传素材/04_图片4_男模身份content4.png expected=output/shared/kongfengchun/identities/kongfengchun_male_content4/identity_ref.png
- PASS: `final_part1_03_single_image` - ["03_图片3_开盖白泥.png"]
- PASS: `final_part1_03_matches_manifest` - actual=output/job-008/seedance_web_final/Part1_上传素材/03_图片3_开盖白泥.png expected=output/shared/kongfengchun/products/kongfengchun_clean_mud_mask/product_open_white_mud_tight.png
- PASS: `final_part1_05_single_image` - ["05_图片5_洗后脸部特写.png"]
- PASS: `final_part1_05_matches_manifest` - actual=output/job-008/seedance_web_final/Part1_上传素材/05_图片5_洗后脸部特写.png expected=output/shared/kongfengchun/identities/kongfengchun_male_content4/afterwash_face_closeup.png
- PASS: `final_part1_06_audio_present` - ["06_音频1_Part1原爆款声音参考.mp3"]
- PASS: `final_part2_dir_exists` - output/job-008/seedance_web_final/Part2_上传素材
- PASS: `final_part2_01_single_image` - ["01_图片1_Part2分镜节奏.png"]
- PASS: `final_part2_01_matches_manifest` - actual=output/job-008/seedance_web_final/Part2_上传素材/01_图片1_Part2分镜节奏.png expected=output/job-008/final-images/part2_seedance_ref.png
- PASS: `final_part2_02_single_image` - ["02_图片2_孔凤春清洁泥膜正面.png"]
- PASS: `final_part2_02_matches_manifest` - actual=output/job-008/seedance_web_final/Part2_上传素材/02_图片2_孔凤春清洁泥膜正面.png expected=output/shared/kongfengchun/products/kongfengchun_clean_mud_mask/product_front_tight.png
- PASS: `final_part2_04_single_image` - ["04_图片4_男模身份content4.png"]
- PASS: `final_part2_04_matches_manifest` - actual=output/job-008/seedance_web_final/Part2_上传素材/04_图片4_男模身份content4.png expected=output/shared/kongfengchun/identities/kongfengchun_male_content4/identity_ref.png
- PASS: `final_part2_03_single_image` - ["03_图片3_开盖白泥.png"]
- PASS: `final_part2_03_matches_manifest` - actual=output/job-008/seedance_web_final/Part2_上传素材/03_图片3_开盖白泥.png expected=output/shared/kongfengchun/products/kongfengchun_clean_mud_mask/product_open_white_mud_tight.png
- PASS: `final_part2_05_single_image` - ["05_图片5_洗后脸部特写.png"]
- PASS: `final_part2_05_matches_manifest` - actual=output/job-008/seedance_web_final/Part2_上传素材/05_图片5_洗后脸部特写.png expected=output/shared/kongfengchun/identities/kongfengchun_male_content4/afterwash_face_closeup.png
- PASS: `final_part2_06_audio_present` - ["06_音频1_Part2原爆款声音参考.mp3"]

## Inputs

```json
{
  "job": {
    "id": "job-008",
    "status": "image_qc_passed",
    "video_path": "<kongfengchun-assets>/泥膜对标/白云山泥膜棒 (20).mp4",
    "product_name": "孔凤春清洁泥膜",
    "client_profile": "kongfengchun",
    "product_assets": "<kongfengchun-assets>/泥膜",
    "person_assets": "<kongfengchun-assets>/模特",
    "audio_assets": "extract_from_original",
    "target_duration": "30s",
    "notes": "继续测试当前 loop；源视频为白云山泥膜棒 (20).mp4；任务产品是孔凤春清洁泥膜；模特随机取一个但需按源片主角/产品主持人性别匹配；基本全复刻，保留源片剧情节奏、镜头顺序、字幕/ASR节奏、产品证明、洗净/洗后证明和收口；产品替换为孔凤春清洁泥膜，白色方圆罐、白盖、绿色标识、开盖乳白厚泥、手指取泥、指腹上脸；产品和泥膜近景必须真实可读且保持厚白泥，不得空白罐、伪包装、灰黄米色稀泥、管棒刷头或手臂试色；声音参考从原视频提取并按句子边界切成两段；Seedance 模型使用 mini ep-20260625155850-zpss5；最后在生成视频前停，只交付网页端/请求侧 Pre-Seedance 包，不提交付费 Seedance 生成；多段默认无 BGM；self_audit_until=seedance_inputs_prepared; client_profile=kongfengchun; read client-profiles/kongfengchun/README.md",
    "output_dir": "output/job-008",
    "last_artifact": "output/job-008/checks/image_batch_qc_gate_review.md",
    "next_stage": "seedance_inputs_prepared",
    "needs_user_confirmation": "false"
  },
  "product_profile": {
    "version": 1,
    "job_id": "job-008",
    "product_name": "孔凤春清洁泥膜",
    "brand_id": "kongfengchun",
    "category_id": "clay_mask",
    "sku_id": "kongfengchun_clean_mud_mask",
    "classification": {
      "category_confidence": 0.95,
      "category_reason": "matched_clay_mask_terms",
      "brand_source": "client_profile_or_product_name"
    },
    "loaded_rules": [
      "generic:generic_product",
      "category:clay_mask",
      "brand:kongfengchun",
      "sku:kongfengchun_clean_mud_mask"
    ],
    "forbidden_rules": [],
    "skipped_rules": [],
    "reference_roles": {
      "required": [
        "source_storyboard",
        "product_front",
        "identity_ref",
        "product_open_mud"
      ],
      "optional": [
        "afterwash_face"
      ],
      "order_prefix": [
        "source_storyboard",
        "product_front",
        "product_open_mud",
        "identity_ref"
      ]
    },
    "review_flags": {
      "required": [
        "layout_matches_source",
        "source_aspect_preserved",
        "source_scene_preserved",
        "no_identity_reference_background",
        "no_product_reference_background",
        "same_identity_as_reference",
        "primary_identity_consistent",
        "primary_identity_only_on_target_role",
        "secondary_characters_keep_source_role_gender",
        "no_source_host_identity",
        "target_product_packaging",
        "target_product_label",
        "no_old_product",
        "no_subtitles_or_text",
        "white_milky_thick_mud",
        "finger_or_fingertip_application",
        "no_tube_stick_brush_cotton_swatch",
        "no_arm_swatch"
      ]
    },
    "checks": {
      "requires_product_consistency": true,
      "requires_afterwash_ref": true,
      "requires_mud_checks": true,
      "requires_skincare_progression": true,
      "requires_finger_jar_application": true,
      "requires_brand_label_consistency": true
    },
    "prompt_required_groups": [
      {
        "name": "target_product",
        "patterns": [
          "孔凤春",
          "清洁泥膜",
          "泥膜",
          "Kongfengchun",
          "clay mask",
          "孔凤春清洁泥膜"
        ]
      },
      {
        "name": "finger_application",
        "patterns": [
          "手指",
          "指腹",
          "\\bfinger\\b",
          "\\bfingertip\\b",
          "\\bfingertips\\b"
        ]
      },
      {
        "name": "open_jar",
        "patterns": [
          "罐",
          "\\bjar\\b"
        ]
      },
      {
        "name": "white_thick_mud",
        "patterns": [
          "乳白",
          "奶白",
          "白色厚泥",
          "白泥",
          "milky[- ]white",
          "white thick"
        ]
      }
    ],
    "visible_text_patterns": [],
    "character_policy": {
      "primary_identity_scope": "approved identity applies only to the source-defined product host or protagonist role",
      "secondary_character_rule": "preserve each secondary character's story role and gender; replace or de-identify them as generic context identities, and never turn them into the primary approved identity"
    },
    "tool_risk_translation_groups": [
      {
        "name": "finger_application",
        "patterns": [
          "手指",
          "指腹",
          "\\bfinger\\b",
          "\\bfingertip\\b"
        ]
      },
      {
        "name": "open_jar",
        "patterns": [
          "罐",
          "\\bjar\\b"
        ]
      }
    ],
    "source_storyboard_controls": [
      "layout",
      "shot_order",
      "framing",
      "action_rhythm",
      "scene_family"
    ],
    "source_storyboard_must_not_control": [
      "old_product",
      "old_tool",
      "old_host_identity",
      "old_mud_color",
      "subtitles"
    ],
    "usage_action": "show the Kongfengchun cleansing mud mask jar, open milky-white thick paste, finger pickup, and fingertip face application"
  },
  "visual_manifest": {
    "schema_version": 1,
    "job_id": "job-008",
    "stage": "image_batch_qc",
    "product_group_id": "kongfengchun_clean_mud_mask",
    "product_group_manifest": "output/shared/kongfengchun/products/kongfengchun_clean_mud_mask/manifest.json",
    "identity_group_id": "kongfengchun_male_content4",
    "identity_group_manifest": "output/shared/kongfengchun/identities/kongfengchun_male_content4/manifest.json",
    "reusable_refs": {
      "product_front": "output/shared/kongfengchun/products/kongfengchun_clean_mud_mask/product_front_tight.png",
      "product_open": "output/shared/kongfengchun/products/kongfengchun_clean_mud_mask/product_open_white_mud_tight.png",
      "identity_ref": "output/shared/kongfengchun/identities/kongfengchun_male_content4/identity_ref.png",
      "afterwash_face": "output/shared/kongfengchun/identities/kongfengchun_male_content4/afterwash_face_closeup.png"
    },
    "part_storyboards": {
      "part1": {
        "path": "output/job-008/final-images/part1_seedance_ref.png",
        "asset_type": "AI改好分镜图",
        "image_route": "matpool_gpt_image_2_edit",
        "contains_source_video_pixels": false,
        "source_reference": "output/job-008/storyboard_source_refs/source_storyboard_part1.jpg",
        "prompt": "output/job-008/image-batch/prompts/part1_rolemap_prompt_v3_product_mud_hardgate.md",
        "candidate_sha256": "e76c63fdd0747681fec0da965a392983e8f9933ac4061151f902050df2bb3fb1",
        "synced_from_candidate": "output/job-008/image-batch/candidates/part1_matpool_v3.png",
        "hard_gate": "output/job-008/checks/part1_image_hard_gate_qc.json"
      },
      "part2": {
        "path": "output/job-008/final-images/part2_seedance_ref.png",
        "asset_type": "AI改好分镜图",
        "image_route": "matpool_gpt_image_2_edit",
        "contains_source_video_pixels": false,
        "source_reference": "output/job-008/storyboard_source_refs/source_storyboard_part2.jpg",
        "prompt": "output/job-008/image-batch/prompts/part2_rolemap_prompt_v2_source_scene_strict.md",
        "candidate_sha256": "a35ddd3c408db07bdf43ad3cfdd5bff4de3911fb9c2aab76ba23ca8bb70ba7e7",
        "synced_from_candidate": "output/job-008/image-batch/candidates/part2_matpool_v2.png",
        "hard_gate": "output/job-008/checks/part2_image_hard_gate_qc.json"
      }
    },
    "promotion_note": "Promoted Part1 V3 plus Part2 V2 after manual visual inspection: source room cues retained, same male identity, readable KOPHENIX/Kongfengchun jar, thick milky-white mud, no source subtitles."
  },
  "product_manifest": {
    "asset_group_type": "product_group",
    "product_id": "kongfengchun_clean_mud_mask",
    "product_name": "孔凤春清洁泥膜",
    "source_assets": "<kongfengchun-assets>/泥膜",
    "front_ref": "product_front_tight.png",
    "open_mud_ref": "product_open_white_mud_tight.png",
    "binding_rule": "front_ref and open_mud_ref can only be reused when product_id and source_assets match the active job"
  },
  "identity_manifest": {
    "asset_group_type": "identity_group",
    "identity_id": "kongfengchun_male_content4",
    "identity_ref": "identity_ref.png",
    "afterwash_face_ref": "afterwash_face_closeup.png",
    "allowed_when": {
      "person_asset": "<kongfengchun-assets>/模特/男/content 4.png"
    },
    "binding_rule": "afterwash_face_ref can only be used when identity_ref is the active model identity"
  }
}
```
