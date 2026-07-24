# Viral Replica Loop Context

This context names the domain language for the viral video replication loop. It keeps workflow terms separate from implementation files, gates, and scripts.

## Language

**Pre-Seedance Handoff**:
The local completion point where upload-ready images, audio, prompts, manifests, and notes are prepared for the user before any Seedance generation. It does not require user confirmation; the user reviews the handoff artifacts themselves.
_Avoid_: intermediate approval, client review gate, manual checkpoint

**Generation Approval**:
Explicit user approval to submit paid/API/batch Seedance generation. A direct user instruction to run Seedance, generate the final video, or directly produce the video is the approval record for the current explicit job/generation round by default; it covers each required Part for that job once, so do not ask for per-Part confirmation. Batch approval exists only when the user explicitly says to run a batch, all jobs, or a named group. Failed-Part retries need new approval. This is the confirmation boundary; it is not part of local handoff preparation.
_Avoid_: handoff, request QC, Seedance input preparation

**Delivery Outcome**:
One of the two user-facing loop exits: a Pre-Seedance Handoff, or a completed generated video. Image samples, internal QC, and repair decisions are not delivery outcomes.
_Avoid_: sample review, intermediate checkpoint, stage approval

**Seedance Generated Output**:
A completed Seedance video contains flattened video and optional audio. It never contains a separate subtitle track. Accidental visible captions can only be burned into the video pixels, so the loop distinguishes only `clean` and `burned_in`; separate-track handling belongs outside this workflow.
_Avoid_: separate_track, remux branch, subtitle-stream fallback

**Finishing Master**:
The single caption-free video produced by local finishing from the selected Seedance Generated Outputs. Hard-subtitle inspection and any conditional repair run against this exact video, so discarded Part intervals never trigger repair work.
_Avoid_: raw-Part subtitle decision, pre-finishing repair, multiple active final inputs

**Client Tutorial Case**:
A client-readable tutorial built from one real completed replication job. It shows the required inputs, the action taken at each step, the actual prompts used, the resulting artifact, and the acceptance check in direct instructional language. It does not use service-pitch language, personal narration, repository identifiers, or hypothetical phrases such as "if you do this manually".
_Avoid_: client showcase, service introduction, internal runbook, operator diary

**Final Technical QC**:
The objective final-video check after Seedance generation. It blocks missing/unreadable outputs, missing streams, wrong duration, freeze/black/blank frames, duplicated or missing speech, broken seams, or obvious wrong person/product/wardrobe/mud/scene. It does not judge subjective effect; if it passes, deliver the final video.
_Avoid_: subjective final review, taste approval, endless final polish

**Final Captions**:
Optional captions added only after Final Technical QC when the user explicitly requests them. Their text and timing come from the actual final audio, while their visual grammar comes from the source video. Seedance generation and local finishing remain caption-free.
_Avoid_: Seedance-generated captions, finishing SRT, pre-QC caption render

**Visual Override**:
A recorded decision to continue when the artifact satisfies the core visual intent and only a non-material metric or threshold is disputed. It applies to small visual-tolerance issues, not to source contamination, missing evidence, wrong product, wrong person, wrong wardrobe, visible squeeze, or unsaved outputs.
_Avoid_: ignoring QC, taste review, forced PASS

**Visual Warning**:
A non-blocking visual QC result for a small metric or local visual concern that does not break the core Seedance input. It continues automatically, but the review must record why the concern is not a failure.
_Avoid_: soft fail, client review, hidden failure

**Hash-Gated Visual QC**:
A speed rule where heavy visual checks are reused by active image hash. If the final Part image hashes and manifest mapping have not changed, downstream stages cite the previous visual PASS evidence instead of re-running geometry, continuity, skincare progression, mud review, or Codex ImageGen contract QC.
_Avoid_: rechecking by habit, stale PASS, visual debate loop

**QC Risk Family**:
The smallest unit of QC reuse. It groups quality failures that are invalidated by the same relevant inputs, such as visual integrity, source fidelity, generation-pack consistency, or final-video integrity. An unchanged QC Risk Family reuses its current PASS evidence; the checker reviews only QC Risk Families whose relevant inputs changed or whose prior evidence is missing, failing, or stale.
_Avoid_: whole-stage recheck, one-file-one-check, checker rereads everything

**QC Risk Fingerprint**:
The internal fingerprint of only the inputs relevant to one QC Risk Family. It decides whether that family is unchanged and may reuse current PASS evidence. Unrelated changes must not invalidate the family: for example, prompt text does not invalidate visual integrity, and Shot-label metadata does not invalidate storyboard panel content when the metadata-only proof passes.
_Avoid_: stage-name invalidation, hash everything together, unrelated change forces recheck

**REUSED_PASS**:
A current QC Risk Family result inherited without checker content review because its QC Risk Fingerprint is unchanged, its prior PASS evidence still exists with matching hashes, and no new user-visible defect applies to it. REUSED_PASS has the same blocking value as PASS but records reuse provenance instead of pretending a new review occurred.
_Avoid_: checker confirmation pass, silent stale reuse, copy old PASS without fingerprint proof

**Deterministic QC**:
A quality judgment fully decided by reproducible machine facts, such as file existence, Artifact Hash equality, audio duration, prompt/request equality, or selected model route. A changed deterministic QC Risk Family passes from its program evidence alone and is not sent to the independent checker.
_Avoid_: checker rereads machine facts, prose confirmation of exact equality

**Semantic QC**:
A quality judgment that requires interpreting meaning or visible intent, such as source rhythm fidelity, speaker mode, person/product correctness, physical action quality, or whether a prompt preserves the source video's character. A changed semantic QC Risk Family requires independent checker review.
_Avoid_: regex decides creative fidelity, maker self-approval, checker validates file length

**QC Defect Scope**:
The smallest QC Risk Family and artifact region invalidated by a user-visible defect, normally narrowed to a Part, Shot, role, action, line, or seam. Unnamed and unchanged risks retain REUSED_PASS. The scope expands to a whole semantic family only when the user reports a whole-output failure or the defect cannot be localized from current evidence.
_Avoid_: one local complaint invalidates the whole stage, rerun every Part, vague defect reopens everything

**QC Risk Ledger**:
The single stage-level decision artifact consumed by the runner. It lists every required QC Risk Family with its status (`PASS`, `REUSED_PASS`, `FAIL`, or `STOP`), current QC Risk Fingerprint, evidence provenance, reuse or recheck reason, and any QC Defect Scope. A stage passes only when every required family is `PASS` or `REUSED_PASS`; individual QC reports remain internal evidence and the runner does not discover or interpret their file paths.
_Avoid_: runner knows individual QC internals, scattered path guessing, missing one report silently passes

**Targeted QC Repair**:
The failure path that reruns only the smallest producer and artifact region named by each QC Defect Scope. One evaluation reports all currently observable defects together; repair may combine defects owned by the same producer, while unaffected `PASS` and `REUSED_PASS` families remain valid. After repair, only risk families whose fingerprints changed are evaluated again.
_Avoid_: whole-stage rollback, one-defect-at-a-time loops, invalidating unrelated PASS evidence

**QC Evidence Freshness**:
Evidence is current only when it belongs to the active QC Risk Fingerprint and its cited artifacts still exist with matching hashes. A first run, changed fingerprint, expired evidence, or missing prior report triggers normal re-evaluation rather than failure. `FAIL` means an evaluation found a defect; `STOP` is reserved for missing required inputs or evidence that makes evaluation impossible.
_Avoid_: missing cache becomes STOP, stale PASS reuse, treating normal recheck as failure

**QC Reuse Boundary**:
QC reuse applies only inside the risk family whose fingerprint is unchanged. Paid-generation approval remains a separate policy gate and is never inherited from unrelated work. Final-video integrity binds to the exact generated video hash, so every new output is evaluated; changing a prompt invalidates generation-pack risks but not unchanged storyboard visual risks.
_Avoid_: cached approval, new video reuses old final QC, prompt edit reopens image review

**QC Ledger Adapter**:
A compatibility boundary that converts existing individual QC reports into QC Risk Ledger entries without exposing their paths or formats to the runner. New-flow stages consume the ledger first; legacy stages may keep their current QC scripts behind adapters until equivalent behavior is proven and duplicate implementations can be retired safely.
_Avoid_: rewrite all QC at once, runner legacy branches, permanent dual sources of truth

**QC Decision Trace**:
The lightweight execution record stored inside the QC Risk Ledger for each family: why it ran or reused evidence, active and wait time, final status, evidence provenance, and next repair scope. JSON is the default record; Markdown, compare sheets, and other visual reports are produced only for failures or explicit inspection requests.
_Avoid_: report generation on every PASS, hidden checker wait, JSON/Markdown duplication by default

**Batched Semantic Review**:
At most one independent checker invocation per stage. Deterministic checks run first and may run concurrently; every changed Semantic QC family is then packaged into one minimal review request, and the checker returns all observable semantic defects together. If no Semantic QC fingerprint changed, the checker is not invoked.
_Avoid_: checker per Part, checker per report, serialized semantic reviews, checker call when nothing changed

**Artifact Hash**:
An internal fingerprint of existing file contents, normally SHA-256. It is used to detect a changed asset, prevent stale QC from attaching to a new version, reuse checks for unchanged inputs, and map a request to its prompt and output. It is not a generation Seed, cannot reproduce a Seedance result, and is not a routine user-facing workflow step.
_Avoid_: random seed, quality score, user version name, reproduction key
