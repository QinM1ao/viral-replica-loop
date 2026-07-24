# Worker Contracts

This folder defines how each loop stage should be executed.

A worker is a repeatable action checklist. It is not the gate. The worker produces artifacts; the gate decides `PASS`, `FAIL`, or `STOP`.

## Worker Output Format

Every worker must leave a review/update artifact with this shape:

```text
Current task:
Current stage:
Worker:
Inputs used:
Video-replication skill check:
This round did:
Artifacts:
Gate to run:
Verification:
Next status if PASS:
Retry variable if FAIL:
Needs user confirmation:
```

## Rules

- Work on one job only.
- Advance one stage only.
- Before stage work, read `.agents/skills/video-replication/SKILL.md`; this is the actual craft method.
- Use `.agents/skills/viral-replica/SKILL.md` only as the loop adapter.
- Do not skip the linked gate.
- Do not spend money or submit batch generation unless the cost gate has passed.
- The sole post-generation exception is the conditional subtitle-removal stage: current hash-bound `burned_in` evidence authorizes one MediaKit Pro task through the project skill; clean videos submit nothing and retries require new approval.
- If inputs are missing, stop and record `STOP`; do not invent replacements.
- If the worker output fails, change only one retry variable on the next attempt.

## Relationship To Other Files

- `rules/STAGE_RULES.json` points to the worker file and gate file.
- `gates/*.md` defines how to judge the worker output.
- `RUNNER_STATE.json` records gate results and retry counts.
- `STATE.md` remains the human-readable run log.

## Scripted Workers

These parts now have scripts:

| Worker area | Script | What it automates |
|---|---|---|
| Video understanding | `tools/video_understanding.py` | Required Wujie Higress Seed 2.0 Mini semantic analysis with redacted evidence. |
| Story analysis prep | `tools/prepare_story_analysis.py` | Seed 2.0 Mini understanding, ffprobe, contact sheet, optional ASR. |
| Image hard gate | `tools/image_hard_gate_qc.py` | layout, refs, mud color, product marker, skin color. |
| GPT Image contract | `tools/codex_imagegen_contract_qc.py` | edit/reference evidence, source-transfer boundaries, product/action/identity review checklist. |
| Request QC | `tools/request_body_qc.py` | request JSON, taskCode, URLs, asset refs, prompt embedding. |
| Final technical QC | `tools/final_video_qc.py` | ffprobe, freeze detect, black detect, audio/video stream, contact sheet. |

These are still intentionally manual or Codex-led:

- Seedance prompt writing
- Image generation. Use the Matpool GPT-Image-2 project route only; deprecated GPT Image routes and gateway probes are not valid. Multi-Part image batch must first write complete `image-batch/part_execution_specs.json`, then use the sealed `tools/image_batch_fanout.py plan`, isolated `contracts/partX_contract.json`, and one `tools/image_batch_fanout.py merge`; image sample and image batch must pass `tools/codex_imagegen_contract_qc.py` before PASS.
- Pre-Seedance pack assembly. After image batch PASS, the default worker is `workers/pre_seedance_pack_worker.md`, which combines voiceover, seam, Seedance prompts, audio boundary evidence, and request/web handoff QC into one stage. The separate voiceover/seam/prompt/audio/request workers remain legacy fallback or focused-repair workers.
- Seedance paid submit
- subjective final effect judgment after delivery; it is not a blocking loop gate

## Self-Audit Mode

When the user asks to run the loop through intermediate stages, the main agent may repeat loop iterations for one pinned job. Each iteration still has exactly one maker worker and one linked gate.

Use this flow:

1. Run `./run-loop.sh --self-audit --job-id <job-id>`.
2. The maker executes the selected worker contract.
3. Build and seal one `tools/qc_evidence_fanout.py` plan, run its immutable deterministic task packets in isolated directories, then call its single coordinator once to write the stage QC Risk Ledger and any one batched semantic request. Reuse unchanged families without rerunning them.
4. Only when the ledger emits a semantic review request, run one separate checker using `workers/checker_worker.md` and bind it with `tools/checker_review_qc.py --risk-request ...`.
5. Record the ledger-backed result with `./run-loop.sh --record-gate-result ...`.
6. Repeat for the same pinned job until a hard stop, explicit stop point, Pre-Seedance Handoff, or Final Video delivery.

Self-audit mode can replace intermediate client taste review only when the linked gate allows it. It cannot approve paid generation. Final video subjective effect review is not a blocking gate; objective final technical QC passes or fails the loop.
