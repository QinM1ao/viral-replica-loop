# Cost Policy

## Purpose

This policy prevents the loop from spending money or wasting expensive generation attempts.

Core principle:

```text
Spend careful effort on image generation.
Be strict before Seedance.
Never use Seedance to discover problems that should have been caught in images, prompts, or request QC.
```

Image generation strongly decides final video quality, but the loop should not burn time on deprecated provider retries. GPT Image work uses the Matpool GPT-Image-2 project route only. Deprecated GPT Image routes and gateway probes are not valid in this project.

Seedance is expensive, so the loop must only submit when references, prompts, audio boundaries, and request bodies have already passed.

## Machine Policy

The runner reads this JSON block.

```json
{
  "version": 1,
  "cost_classes": {
    "free_check": {
      "auto_allowed": true
    },
    "cheap_quality_work": {
      "auto_allowed": true,
      "counter": "gpt_image_runs"
    },
    "conditional_paid_repair": {
      "auto_allowed": true,
      "requires_detection_evidence": true,
      "max_tasks_per_job": 1,
      "requires_new_approval_for_retry": true
    },
    "expensive_generation": {
      "auto_allowed": false,
      "counter": "seedance_runs",
      "requires_allow_paid": true,
      "requires_approval_record": true
    }
  },
  "budgets": {
    "gpt_image_runs_per_job": {
      "soft": 8,
      "hard": 12
    },
    "seedance_runs_without_approval": {
      "hard": 0
    },
    "seedance_runs_per_approval": {
      "hard": 1
    },
    "seedance_targeted_retries_per_failed_output": {
      "hard": 1
    },
    "same_failure_type": {
      "hard": 2
    }
  },
  "approval": {
    "allow_paid_alone_is_not_enough": true,
    "approval_record_required": true,
    "direct_generation_request_is_approval": true,
    "direct_generation_phrases": [
      "跑 Seedance",
      "直接跑 Seedance",
      "直接出视频",
      "给我视频",
      "生成最终视频"
    ],
    "default_approval_scope": "current_explicit_job",
    "current_job_approval_covers_required_parts_once": true,
    "failed_part_retry_requires_new_approval": true,
    "quality_retake_requires_new_approval": true,
    "batch_requires_explicit_batch_scope": true,
    "ambiguous_words_are_not_approval": [
      "继续",
      "下一步",
      "试试",
      "都行"
    ]
  },
  "routes": {
    "cost_stop_worker": "workers/cost_approval_worker.md",
    "cost_stop_gate": "gates/cost_approval_gate.md"
  }
}
```

## Cost Classes

| Class | Examples | Default behavior |
|---|---|---|
| `free_check` | reading files, ASR, ffmpeg, ffprobe, prompt writing, QC markdown | Allowed automatically. |
| `cheap_quality_work` | Matpool GPT-Image-2 sample/edit, local panel repair | Allowed within budget, but must pass strict gates. |
| `conditional_paid_repair` | One MediaKit Pro subtitle-removal task after current finished-master evidence confirms `burned_in` pixels | Allowed once by the project's standing approval; clean videos submit nothing and every retry needs new approval. |
| `expensive_generation` | Seedance task submit, Seedance retry, batch video generation | Must stop for explicit user approval. |

## Global Default

No paid or batch generation without explicit user approval.

`--allow-paid` is not enough by itself. The loop also needs a clear approval record in `STATE.md` or the current user message.

A direct user request to run Seedance, directly generate the final video, or "直接出视频" is explicit approval for the current explicit job/generation round by default. It covers each required Part for that job once. Do not ask for a second confirmation, and do not ask again for Part2 when Part2 is required to complete the same job. Record the current user message as the approval source.

Batch approval is never implied by default. Only treat generation as batch-approved when the user explicitly names a batch scope, such as "这批都跑", "全部跑", "今天这些都跑", or a concrete list of jobs.

Failed-Part retry approval is separate. If Part1 or Part2 fails and needs a new Seedance submit, get a new approval for that targeted retry.

The generated-subtitle cleanup standing approval is narrower than Seedance approval. It applies only after `subtitle_removal/subtitle_detection.json` passes and classifies the exact current `final/final_video.mp4` master as `burned_in`; it authorizes one MediaKit Pro subtitle-removal task on that master. It does not authorize a retry, another MediaKit tool, a clean-video probe, or a different job.

Before the first MediaKit call, persist `output/<job-id>/subtitle_removal/paid_attempt.json`. The runner also records `spent.mediakit_subtitle_removal_runs`; any existing attempt marker or a count of 1 blocks another automatic task. A failed attempt is still spent. A later user-approved retry must use the same command with `--allow-paid --approval-recorded --approval-scope targeted_retry --approve-mediakit-subtitle-retry`, write a new append-only `paid_attempt_<n>.json`, and never overwrite an earlier attempt record. Without all four flags, the retry remains blocked.

## Image Generation Budget

Image generation can be tried more than Seedance, but bad images must not pass downstream.

| Action | Soft limit | Hard stop | Notes |
|---|---:|---:|---|
| First sample for one storyboard stage | 2 attempts | 3 attempts | Failed hard-gate samples should be discarded internally. |
| Full Part storyboard image candidate | 2 attempts per Part | 3 attempts per Part | Only hard-pass candidates should be shown for taste review. |
| Fast local repair | 1 targeted retry | 2 attempts total | Repair only the failed image/panel/material variable; do not rerun the whole Part. |
| Same failure type | 2 consecutive attempts | 2 consecutive attempts | After this, stop or change strategy; do not blindly retry. |
| Total image work before next user checkpoint | 8 runs per job | 12 runs per job | Stop with a failure summary after hard stop. |

## Image Strict Gate

Before any Seedance prompt or request build, image artifacts must pass strict review.

For skincare and clay-mask jobs, the image gate must reject:

- wrong person or weak identity match
- multiple identity references when the task has one model
- obvious skin-tone or lighting mismatch across Parts
- unknown packaging box, blank jar, wrong jar, or invented label
- old product texture contamination
- yellow/beige/tan/cream-yellow mud, gray mud, watery mud, thin mud, tube applicator, or tool-to-face action
- wrong scene copied from the person reference
- wrong wardrobe copied from an unrelated reference
- changed storyboard grid, shot order, or shot count

Product-specific hard gates should be written in `PRODUCT_CONSTRAINTS.md` before image generation begins.

Examples:

- single-model jobs must use one approved identity anchor
- products cannot become invented blank packages
- texture must match the client product assets
- cross-part skin tone and exposure must stay close
- product front and open-texture references should be split when they serve different roles

If any of these fail, do more image repair work instead of moving to Seedance.

## Seedance Budget

Seedance is expensive. Default policy is conservative.

| Action | Allowed without explicit approval | Limit after approval |
|---|---:|---:|
| Build prompt text | yes | unlimited free checks |
| Build request JSON | yes | unlimited free checks |
| Upload or prepare public URLs | yes, if no paid action | as needed |
| Submit one Seedance test for one Part | no | 1 run per approved Part |
| Retry failed Seedance Part | no | 1 targeted retry after new approval |
| Batch submit multiple jobs or multiple variants | no | only if user explicitly approves batch |
| Auto-submit after prompt/request pass | no | never by default |

Final video QC may trigger at most one targeted Seedance retry for an objective hard failure. After one targeted retry, a repeated technical failure or any second paid retry stops the loop and reports the failed QC evidence.

## Seedance Must Stop If

The loop must stop before Seedance submit when:

- request body has not passed `gates/request_gate.md`
- prompt has not passed `gates/seedance_prompt_gate.md`
- image references have unresolved quality issues
- audio boundaries are not checked for sound-enabled videos
- task count is unclear
- generation would be batch or paid
- user has not explicitly approved the submit

## Approval Record

A valid approval should record:

```text
Approved action:
Job:
Stage:
Request files:
Number of Seedance tasks:
Expected Parts:
Approval scope:
Approval source:
Timestamp:
```

Examples of valid approval:

- user says "直接跑 Seedance"
- user says "跑 Seedance 给我视频"
- user says "直接出视频"
- user says "提交生成" after seeing the exact request summary
- user says "同意跑这两个 Part"
- user says "允许这次 Seedance 重跑 Part2"
- user says "这批都跑" after the batch/job list is clear

Ambiguous messages are not approval:

- "继续"
- "下一步"
- "试试"
- "都行"

Those can advance free checks, but not paid Seedance submit.

## Runner Behavior

The runner reads the machine policy block in this file.

It should:

1. compare `RUNNER_STATE.json` spent counts with this policy
2. allow image generation work within the soft budget
3. stop and summarize after hard budget
4. stop before Seedance unless `--allow-paid` and `--approval-recorded` are both present
5. route cost stops to:
   - worker: `workers/cost_approval_worker.md`
   - gate: `gates/cost_approval_gate.md`

## State Fields

Track spending in `RUNNER_STATE.json`:

```json
{
  "spent": {
    "gpt_image_runs": 0,
    "seedance_runs": 0,
    "mediakit_subtitle_removal_runs": 0
  }
}
```

The `gpt_image_runs` counter name is kept for runner compatibility, but it counts all image-generation samples, edits, and repairs.

Seedance count should include every submitted video generation task.

MediaKit subtitle-removal count includes every submitted Pro task, successful or failed. Record it with `--spent-mediakit-subtitle-removal-runs 1` in the same gate round; never overwrite or omit a failed attempt to regain automatic permission.
