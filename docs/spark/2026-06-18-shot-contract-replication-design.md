# Shot-Contract Replication Design

Date: 2026-06-18
Project: `viral-replica-loop`
Scope: internal workflow and gate design for close video replication, especially `孔凤春清洁泥膜` jobs.

## Problem

The current loop can preserve broad story beats and product/person replacement, but it can still fail at true replication because the original video's visible shot rhythm is not contractually bound to the target Seedance input image and prompt.

The observed failure in `job-002` was:

- The rewritten voiceover became close enough to the original ASR/subtitle rhythm.
- The final Seedance prompts still did not guarantee that original key shots appeared at the right moments.
- A visible original shot, such as the host showing a phone to the viewer while speaking, was missing or weak in the target final storyboard image.
- Because the final `01_图片1` storyboard did not explicitly contain every required key shot, Seedance had no reliable visual carrier for those shots and produced a static-feeling result.

The fix is not to add more generic prompt language. The workflow needs an internal shot contract that binds:

```text
original source shot -> target storyboard cell -> target spoken line -> Seedance prompt time block
```

## Goals

- Preserve original video shot rhythm, not just the selling points.
- Ensure every visually important source shot has a target counterpart before Seedance prompt handoff.
- Prevent missing key shots from being "patched" with prompt text when the final Seedance storyboard image does not contain them.
- Keep the final user handoff directory simple: only uploadable assets, prompts, and minimal upload instructions.

## Non-Goals

- Do not put internal contracts, QC reports, or process notes into the final `seedance_web_final/` handoff.
- Do not require exact 51-second replication when the target is 30 seconds.
- Do not force every repeated or low-information source frame to survive compression.
- Do not change the product/person/white-mud gates defined by the Kongfengchun profile.

## Key Requirement

For 30-second compressed replication, repeated or secondary shots may be merged, but must-keep functional shots cannot be omitted.

Examples of must-keep shots for `job-002` style videos:

- Product extreme close-up at the opening.
- Face application / local mud action.
- Face-to-camera testimonial shots.
- Problem/old-state proof shot.
- Phone shown to the viewer while speaking.
- Product usage/proof shot, such as "this jar is nearly used up."
- Product/open-mud texture shot.
- Cleaning logic proof shot.
- Value/price packaging comparison beat.
- Clear usage step after washing.
- Rinse / sink wash action.
- Towel wipe action.
- After-wash close face proof.
- Product close beside clean face for CTA.

## Internal Artifacts

Add a `shot-contract/` folder under each job output:

```text
output/<job-id>/shot-contract/
├── source_shot_contract.md
├── target_shot_contract.md
└── seedance_shot_prompt_map.md
```

These are internal QC artifacts. They do not go into `seedance_web_final/`.

## Source Shot Contract

Created during `story_analysis`.

Purpose: capture the original source video's key visual shots and bind each one to subtitle/ASR.

Minimum columns:

| Column | Meaning |
|---|---|
| `source_id` | Stable shot id, e.g. `S01`. |
| `source_time` | Original time range or frame timestamp. |
| `source_visual` | What is visible in the source shot. |
| `source_subtitle_asr` | Subtitle/ASR spoken during this shot. |
| `shot_function` | What this shot does in the story or sale. |
| `must_keep` | `yes` for shots that must survive compression. |
| `replacement_rule` | How the source content maps to target product/person. |
| `forbidden_carryover` | Old product/person/mud/text/tools that cannot be inherited. |

Important: this contract must include visually obvious proof shots even if they are not the most important spoken line. The phone-showing shot is a must-keep shot because it changes the viewer's perception of proof and rhythm.

## Target Shot Contract

Created during `storyboard`.

Purpose: map each must-keep source shot into the 30-second target structure and the final target storyboard image.

Minimum columns:

| Column | Meaning |
|---|---|
| `source_id` | Links to `source_shot_contract.md`. |
| `target_part` | `Part1` or `Part2`. |
| `target_cell` | The intended cell number in final `01_图片1`. |
| `target_time` | Approximate time range in the 15-second Seedance part. |
| `target_visual` | Exact target image content. |
| `target_spoken_line` | The line that should be spoken in this shot. |
| `required_refs` | Product, open-mud, identity, after-wash refs needed. |
| `status` | `mapped`, `merged`, or `missing`. |

Rules:

- Every `must_keep=yes` source shot must map to a target cell.
- If a must-keep shot is merged, the target cell must still visibly carry its function.
- If a must-keep shot is missing, storyboard/image generation cannot pass.

## Image Batch Gate

The image batch gate must check final `01_图片1` storyboards against `target_shot_contract.md`.

Pass only if:

- Every must-keep contract row has a visible target cell in the final current-job AI-edited storyboard.
- The cell carries the correct visual function, not just a vaguely related product/person image.
- Product/person/mud constraints still pass.
- The final storyboard image is a current-job `AI改好分镜图`.

Fail if:

- A required source function is missing from final `01_图片1`.
- A target cell exists only in the written contract but not in the final image.
- The workflow tries to rely on Seedance prompt text to invent a missing key shot.
- A source rhythm board, contact sheet, cropped source frame, or deprecated image is used as final upload material.

Required retry:

- Missing key shot -> return to image batch and regenerate or locally repair the target storyboard image.
- Prompt wording alone is not an allowed repair.

## Seedance Shot Prompt Map

Created during `seedance_prompt`.

Purpose: bind each prompt time block to the target storyboard cell and spoken line.

Minimum columns:

| Column | Meaning |
|---|---|
| `target_part` | `Part1` or `Part2`. |
| `target_cell` | Final storyboard cell number. |
| `time_range` | Seedance prompt time range. |
| `visual_action` | What happens in this short shot. |
| `spoken_line` | Exact spoken line for this shot. |
| `material_refs` | Which upload images affect this shot. |
| `motion_note` | Camera/action continuity note. |

Seedance prompt rules:

- Prompts must be written from this map.
- Each time block must say which target cell it corresponds to.
- The prompt cannot introduce a new key shot that is absent from the final storyboard image.
- Face-to-camera shots should be interrupted by the same proof/action/product rhythm found in the target contract.

## Request Handoff Gate

The request handoff gate remains focused on final usability.

It should verify:

- `Part1_上传素材/01-06` exists.
- `Part2_上传素材/01-06` exists.
- `01` images match approved visual manifest storyboards.
- `02/03` match the active product group.
- `04/05` match the active identity group.
- `06` audio files are `<=15.00s`, target `14.90s`.
- Prompt files are the prompt-gate-passed versions.
- Final directory contains no drafts, deprecated files, internal contracts, contact sheets, or QC reports.

Final handoff structure:

```text
seedance_web_final/
├── Part1_上传素材/
│   ├── 01_图片1_Part1最终分镜.png
│   ├── 02_图片2_产品正面.png
│   ├── 03_图片3_开盖白泥.png
│   ├── 04_图片4_男模身份content4.png
│   ├── 05_图片5_生成洗后脸部特写.png
│   └── 06_音频1_Part1原爆款声音参考.mp3
├── Part2_上传素材/
│   ├── 01_图片1_Part2最终分镜.png
│   ├── 02_图片2_产品正面.png
│   ├── 03_图片3_开盖白泥.png
│   ├── 04_图片4_男模身份content4.png
│   ├── 05_图片5_生成洗后脸部特写.png
│   └── 06_音频1_Part2原爆款声音参考.mp3
└── prompts/
    ├── Part1_Seedance提示词.txt
    └── Part2_Seedance提示词.txt
```

Optional: include one minimal upload instruction file if needed, but do not include internal contracts.

## Failure Routing

| Failure | Route |
|---|---|
| Missing key source shot in target contract | Return to storyboard. |
| Key shot mapped in contract but absent from final `01_图片1` | Return to image batch. |
| Correct cell exists but spoken line is wrong | Return to voiceover or Seedance prompt, depending on whether the script or binding is wrong. |
| Product/person/white mud wrong | Return to image batch or fast repair. |
| Prompt invents a missing shot | Fail prompt gate, return to image batch if final storyboard lacks the shot. |
| Final handoff contains internal files or drafts | Fail request gate, clean final directory. |

## Example: Phone-Shown-To-Viewer Shot

Source contract row:

| Field | Value |
|---|---|
| `source_id` | `S09` |
| `source_time` | Around original product/proof section |
| `source_visual` | Host holds phone toward viewer while speaking. |
| `source_subtitle_asr` | Source proof/checking/cleaning-routine line. |
| `shot_function` | Proof of research, routine, or product credibility. |
| `must_keep` | `yes` |
| `replacement_rule` | Target male holds phone to viewer; screen may be non-readable; no old product screen text. |

Target contract row:

| Field | Value |
|---|---|
| `target_part` | `Part1` |
| `target_cell` | concrete cell number in final storyboard |
| `target_visual` | Same male holds phone toward camera while speaking; phone functions as proof, not decoration. |
| `target_spoken_line` | The corresponding compressed proof line. |
| `status` | `mapped` only if visible in final `01_图片1`. |

If this target cell is absent from final `01_图片1`, the image batch gate fails. The Seedance prompt may not add a phone-shot instruction to compensate.

## Success Criteria

A job may proceed to Seedance handoff only when:

- Every must-keep source shot is present in the target shot contract.
- Every must-keep target shot is visible in final `01_图片1`.
- Every prompt time block is bound to a target storyboard cell.
- Final upload folder contains only upload assets, prompt files, and optional minimal upload instructions.
- No paid/API Seedance generation has been submitted unless explicitly approved.
