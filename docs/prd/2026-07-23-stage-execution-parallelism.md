# Stage Execution and Safe Parallelism

## Outcome

Reduce wall-clock time inside one job and one canonical stage without weakening source-faithful replication, paid-action controls, or semantic QC.

The default replication contract remains `source_locked + necessary_only`: preserve source wording, line order, repetitions, speaker mode, shot order, timing, scene, framing, action, roles, and product-proof placement. Parallel execution changes only who performs independent work and where evidence is written. It does not authorize creative adaptation.

## Shared execution contract

Every parallelizable unit is a sealed Stage Execution packet with:

- one `job_id` and one canonical `stage`;
- an immutable plan hash;
- a command or an explicit agent task;
- declared dependencies;
- isolated allowed write roots;
- one job-local completion artifact;
- hash-bound output evidence.

The Stage Execution module dispatches dependency-ready packets, fans their results in, and invokes one coordinator commit. Packets and sub-agents cannot write `jobs.csv`, `RUNNER_STATE.json`, `STATE.md`, shared manifests, gate state, cost state, retry state, paid approval, or semantic conclusions.

## Parallel execution boundaries

### Image Batch

- Build executable per-Part packets from `part_execution_specs.json`.
- Parts with ready prompts and references may run in parallel.
- `storyboard_derived` identity work uses an explicit ready-set DAG.
- Each Part writes only its own candidate, Matpool invocation, contract, logs, and completion.
- Shot-label normalization and Part evidence stay inside that Part lane.
- The coordinator merges the shared image contract and runs one QC ledger.

### Seedance generation

- Run request-contract, serialized-parameter, reference-audio, and credential preflight before a paid reservation exists.
- After all preflights pass, reserve the exact approved Part set, request hashes, attempt number, and task count.
- Mark all reserved attempts spent before parallel `task_create` calls.
- A Part lane may submit, poll, and download only its reserved request.
- A failed or ambiguous attempt remains spent. No lane may retry.
- The coordinator writes `selected_outputs.json`, generation spend, and loop state once.

### QC

- Changed deterministic evidence families may execute concurrently in isolated stage evidence directories.
- One ledger coordinator combines deterministic evidence, fingerprint reuse, and semantic families.
- Unchanged PASS families are reused by current hash.
- At most one batched semantic checker request may be emitted for a stage.
- Semantic families never run in the deterministic fan-out.

### Source Blueprint

- Existing source fact preparation remains bounded: one Qwen ASR process, measured cuts/frames, and configured Seed 2.0 Mini understanding.
- One canonical maker authors the whole-film `source_rhythm.json`.
- `source_rhythm_qc.json` must PASS and the rhythm hash must lock before any composition fan-out.
- Only then may story view, timeline view, shot table, role/product/seam audit, and independent Part storyboard rebuilds run as isolated packets.
- Packets cannot rerun ASR, edit source rhythm, or write canonical merged files.
- The coordinator merges once and invokes one source checker.

### Pre-Seedance

- Director-plan authorship, validation, route choice, manifest freeze, archive/replace, and shared voice/seam semantics remain serial.
- After the plan freezes, deterministic per-Part prompt, audio, and selected web-or-API output adapters may use isolated staging and bounded parallelism when Part count or audio work justifies it.
- The coordinator promotes staged outputs once in stable Part order.
- No LLM sub-agent may independently rewrite a Part script, shot order, dialogue, seam, or source-beat mapping.

## Serial by design

- paid approval, reservation changes, and retry authorization;
- director plan and whole-film dialogue/shot/seam semantics;
- source-rhythm authorship;
- shared state and shared-manifest commits;
- the batched semantic checker and final semantic conclusion;
- the dependent delivery chain from finishing through subtitle handling to final QC.

## Acceptance criteria

1. A mutated sealed packet is rejected before dispatch.
2. Packet write roots cannot overlap or contain coordinator-only paths.
3. Dependency-ready packets run concurrently and blocked dependents become `STOP`.
4. Exactly one coordinator commit receives the ordered fan-in report.
5. Image Part commands are real Matpool project commands with isolated contracts and no retry.
6. Invalid Seedance request/audio input creates no paid reservation and performs no `task_create`.
7. Once generation is marked spent, failure cannot be retried without new targeted approval.
8. Deterministic QC produces one evidence bundle and one ledger; semantic review remains at most once.
9. Source composition rejects a missing, changed, or non-PASS rhythm/QC binding.
10. Pre-Seedance parallel work cannot write shared output directories before coordinator promotion.
