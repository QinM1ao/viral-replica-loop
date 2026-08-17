# ShotLoom Loop Context

This context names the domain language for the viral video replication loop. It keeps workflow terms separate from implementation files, gates, and scripts.

## Language

**ShotLoom Plugin**:
The versioned, distributable product that supplies the replication method, operating policy, and workspace initialization for any Client Workspace. It owns no client references, live Jobs, run state, or generated artifacts.
_Avoid_: Client Workspace, live repository, customer data folder

**Plugin Installation**:
A locally materialized, versioned ShotLoom Plugin managed as one replaceable package. Its files may be inspectable on the host, but the installation is not a client customization surface; product development changes are released as a new plugin version.
_Avoid_: plugin source tree, Client Workspace profile, editable runtime configuration

**Plugin Release Identity**:
The immutable identity of one Private Plugin Release, formed by its semantic version and the content digest of its signed release manifest. Reusing one semantic version for different content is invalid; a Codex cachebuster is development metadata and never a customer release identity.
_Avoid_: mutable version, filename label, cachebuster release, latest

**Plugin Activation**:
The recoverable transition that makes one validated Managed Plugin Copy the Codex-discovered Plugin Installation for future tasks. Activation never mutates a Client Workspace, changes a running Job, or hot-swaps the current Codex task.
_Avoid_: file copy alone, Workspace migration, current-task reload

**Plugin Rollback**:
An explicit activation of a retained Last-Known-Good Plugin Release after compatibility with the current Workspace Schema, Job Provenance, and Runtime Contracts has been proven. It never performs a best-effort Workspace downgrade.
_Avoid_: automatic downgrade, Schema rollback, arbitrary old folder

**Plugin Uninstall**:
Removal of the Codex registration, personal marketplace entry, Managed Plugin Copy, and plugin-owned release staging while preserving every Client Workspace and, by default, its Keychain-backed Service Authorization. Credential revocation is a separate confirmed action.
_Avoid_: Workspace deletion, implicit credential revocation, factory reset

**Plugin Package**:
The self-contained folder delivered and installed as the ShotLoom Plugin. Its canonical root folder is `shotloom/`, exactly matching the normalized plugin name in `.codex-plugin/plugin.json`. It contains every Skill, workflow rule, executable component, Built-in Profile, workspace template, test, and operating document required by the product, but contains no live client Job or generated work output.
_Avoid_: Client Workspace, partial installer, live checkout export

**Canonical Plugin Layout**:
The internal filesystem contract of the `shotloom/` Plugin Package: `.codex-plugin/plugin.json`; one root `install.command`; six bounded customer-facing entries under `skills/`; private workflow implementation under `engine/`; reusable rules under `profiles/builtin/`; workspace initialization material under `workspace-template/`; lifecycle utilities under `scripts/`; non-client proof material under `assets/fixtures/`; plus `tests/` and `docs/`. Only `skills/` is declared as the customer Skill discovery surface; `engine/` preserves the complete craft, tools, workflows, workers, and rules without exposing implementation layers as entry choices.
_Avoid_: flat plugin repository, every internal Skill exposed, client media in assets, workspace state in engine

**Plugin Source Repository**:
The Git repository rooted at the maintainable source of one Plugin Package. Client Workspaces, including the Development Workspace, live outside its filesystem boundary so client data cannot enter plugin history through normal source-control operations.
_Avoid_: product root containing workspaces, monorepo with client media, gitignored customer data

**Private Plugin Release**:
A versioned, validated Plugin Package distributed directly to authorized clients rather than listed in the public Plugin Directory. Private distribution narrows availability but does not relax Codex Plugin Conformance, security, installation, or release-proof requirements.
_Avoid_: internal prototype, unvalidated zip, public marketplace listing

**Private Folder Installation**:
The first-release installation experience where an authorized client receives exactly one versioned `shotloom/` Plugin Package and runs one bundled local installation command. The installer places the managed plugin copy in the supported local location, creates or updates the client's personal marketplace registration, validates discovery, and instructs the user to start a new Codex task. It requires neither Plugin Creator, Git, a vendor backend, nor delivery of `workspace-dev/`.
_Avoid_: manual file placement, public marketplace publication, bundled Development Workspace, Plugin Creator as a client dependency

**Codex Plugin Conformance**:
The product constraint that the Plugin Package uses Codex's supported plugin manifest, packaged Skills, optional app dependencies, installation lifecycle, and permission model rather than inventing a parallel plugin format. Plugin implementation begins only after the official Plugin Creator and validation guidance are available and have been read.
_Avoid_: custom plugin loader, repository-only installation, Codex-like folder without validation

**Customer Skill Surface**:
The intentionally small set of plugin Skills a client may invoke directly: one primary full-replication entry and bounded specialist entries for shot refinement and hard-subtitle removal. Craft, provider, checker, bootstrap, and maintainer capabilities remain internal.
_Avoid_: every bundled Skill is customer-facing, bypassing the loop, maintainer tools in the customer menu

**Local Plugin Execution**:
The operating mode where the Plugin Installation performs orchestration, media processing, state management, and QC on the client's machine and calls approved external model providers directly through client-owned Service Authorization. No vendor-operated workflow backend or credential proxy participates.
_Avoid_: hosted execution service, hidden API relay, vendor job queue

**Supported Host**:
An Apple Silicon macOS machine running a compatible Codex Desktop release and satisfying the plugin's verified local runtime contract. Other operating systems and Intel Macs are outside the first release until they independently achieve Behavioral Parity.
_Avoid_: any computer, best-effort cross-platform support, unverified host

**Plugin Permission Boundary**:
The least-authority operating scope for Local Plugin Execution: read user-selected source locations for import, write only the active Client Workspace and rebuildable managed runtime area, execute declared local media tools, and reach declared provider endpoints. Paid generation remains governed by Generation Approval.
_Avoid_: whole-machine access, unrelated repository writes, implicit paid submission

**Product Fixture**:
A minimal, non-client test asset or expected deterministic artifact owned by the Plugin Package and used to prove product behavior without a Client Workspace. It is synthetic, licensed, or anonymized and never represents a live or historical client Job.
_Avoid_: customer media, Development Workspace output, showcase disguised as a test

**Built-in Profile**:
A versioned, inspectable replication specialization distributed with the Viral Replica Plugin because its rules and acceptance behavior are reusable across eligible Client Workspaces. It may contain explicitly authorized, sanitized customer-derived rules, but owns no customer media, Job evidence, mutable lessons, or secrets.
_Avoid_: hard-coded client behavior, private customer profile, global default for every product

**Workspace Profile**:
A versioned client-specific product rule or preference owned by one Client Workspace and private to that workspace. It may specialize declared extension points but cannot modify the Viral Replica Plugin or weaken core approval, safety, or QC invariants.
_Avoid_: Built-in Profile, plugin patch, shared customer configuration

**Effective Profile**:
The immutable Job-bound result of resolving the Generic Core, selected Built-in Profiles, the active Workspace Profile, and explicit Job facts in that order. Its ordered component identities and versions form part of Job Provenance.
_Avoid_: current defaults, mutable profile lookup, all available profiles

**Profile Promotion**:
The release act that turns an explicitly authorized, sanitized, reusable Workspace Profile rule into a new Built-in Profile version after non-client proof. It never promotes customer media, historical Jobs, raw lessons, secrets, or provider evidence.
_Avoid_: copying a client folder, automatic sharing, in-place profile mutation

**Client Workspace**:
A persistent boundary owned by exactly one client or brand organization. It may contain multiple product, person, video, and audio reference collections plus multiple Jobs, run state, generated artifacts, and Delivery Outcomes; it is operated by a Viral Replica Plugin but survives plugin installation, replacement, and upgrade.
_Avoid_: plugin directory, source checkout, output folder, shared multi-client workspace, one-video workspace

**Job Archive**:
The complete persistent record of one Job, including its bound inputs, intermediate work, QC evidence, and active Delivery Outcome. It keeps technical detail available without making that detail the workspace's primary customer-facing surface.
_Avoid_: output folder, final delivery only, shared cross-Job artifacts

**Delivery Library**:
The customer-facing collection of current Delivery Outcomes across a Client Workspace. It exposes only active deliverables and never becomes a second source of truth for intermediate work, failed candidates, or run state.
_Avoid_: output tree, archive of every attempt, system status folder

**Workspace System Area**:
The plugin-owned internal area of a Client Workspace containing queue state, checkpoints, caches, and runtime metadata. It is preserved for safe resume and diagnostics but is not part of normal customer content navigation.
_Avoid_: Reference Library, Job Archive, Delivery Library

**Managed Runtime**:
A plugin-declared, Workspace-local, rebuildable collection of interpreters, packages, media binaries, models, and caches prepared from version locks, approved sources, integrity hashes, and license metadata. Bootstrap builds it transactionally under `.viral-replica/runtime/`; normal Job execution never installs or mutates dependencies, and no Managed Runtime may depend on global packages, user caches, sibling checkouts, elevated privileges, or undeclared machine state.
_Avoid_: system Python environment, dynamic pip during a Job, bundled client data, irreplaceable local setup

**Runtime Contract**:
The immutable versioned declaration of the Managed Runtime families a Plugin version may use, including artifact identities, dependency locks, integrity checks, host constraints, and compatibility. Runtime versions are built side by side and activated only after validation; a Job binds one compatible Runtime Contract for its run and never observes an in-place dependency mutation.
_Avoid_: mutable virtual environment, latest-compatible package, plugin version alone, live Job runtime switch

**Development Workspace**:
The non-delivered Client Workspace used by the product maintainer for active and historical development Jobs, references, generated media, evidence, and deliveries. The Plugin Package has no runtime dependency on its presence or contents.
_Avoid_: Plugin Package, built-in test fixture, customer installation

**Legacy Archive**:
The read-only Development Workspace collection of historical runs, experiments, research, and deliveries that are retained with an origin manifest but not rewritten as current Job Archives. A specific item is normalized only when it becomes active or is selected as a maintained proof case.
_Avoid_: current Job Archive, discarded history, fabricated migration evidence

**Legacy Job Adoption**:
The explicit, recoverable act of creating a new canonical Job from one retained legacy item because a user has chosen to continue it. Adoption preserves the legacy item unchanged, imports only verified inputs and evidence, records unknown provenance honestly, starts a new approval boundary, and resumes only from a compatibility-proven checkpoint.
_Avoid_: automatic normalization, rewriting history in place, inherited generation approval, treating every incomplete row as active

**Workspace Independence**:
The guarantee that deleting or replacing one Client Workspace does not impair the Plugin Package, Workspace Bootstrap, or future Jobs in another workspace. It does not recover references, Job Archives, evidence, or Delivery Outcomes that were deleted with that workspace.
_Avoid_: automatic backup, recoverable deletion, plugin depends on historical runs

**Workspace Schema**:
The versioned structural contract a Viral Replica Plugin uses to interpret one Client Workspace. A schema transition is explicit and recoverable, preserves historical Job Archives and Reference Bindings, and prevents an incompatible plugin from writing the workspace.
_Avoid_: plugin version, silent folder rewrite, best-effort downgrade

**Canonical Workspace Layout**:
The shared filesystem layout used by every Client Workspace and by `workspace-dev/`: `workspace.yaml`; reusable `references/products/`, `references/people/`, `references/videos/`, and `references/audio/`; complete `jobs/<job-id>/input/`, `work/`, `qc/`, and `delivery/` archives; a customer-facing `deliveries/` projection; and a hidden `.viral-replica/` system area for state, rebuildable cache, and runtime. Stable English directory names form the machine contract, while Chinese READMEs and plugin-facing labels explain each area to users.
_Avoid_: flat output directory, translated machine paths, plugin files inside the workspace, client media inside the plugin

**Reference Library**:
The client-owned, versioned collection of reusable product, person, video, and audio references inside one Client Workspace. Updating its current selections affects future Jobs only.
_Avoid_: Job inputs, generated artifacts, unversioned asset folder

**Reference Import**:
The authorized copy of user-selected external media into a versioned Reference Library collection. The external source is read-only, and every Job uses the imported workspace-owned version rather than a mutable outside path.
_Avoid_: linked external file, writing source folders, untracked absolute path

**Reference Binding**:
The immutable record of the exact Reference Library versions selected when a Job is created. A Job keeps those versions unless the user explicitly creates a new binding for that Job.
_Avoid_: current reference pointer, mutable asset path, latest files

**Job Provenance**:
The immutable record of the plugin version, workflow contract, Runtime Contract, Built-in Profile versions, Workspace Profile versions, and Reference Binding under which a Job was created. Only a plugin and Runtime Contract pair that declares compatibility with that provenance may resume the Job without an explicit migration.
_Avoid_: current plugin defaults, copied plugin source, best-effort resume

**Workspace Bootstrap**:
The one-time, plugin-led preparation started on the first `shotloom:viral-replica` use after installation. The customer sees only Workspace selection, native protected prompts for any required Service Authorization, clear preparation progress, and a ready or actionable stop result. Internally it records the selected location outside the replaceable plugin package, prepares compatible Managed Runtime families, performs No-Spend Capability Probes, and establishes layered readiness. Completion means the user does not need to understand or edit code, repositories, Keychain records, Runtime Contracts, provider probes, or terminal commands before normal use.
_Avoid_: Job Intake, manual installation guide, workspace migration

**Workspace Readiness**:
The state in which a Client Workspace has a valid compatible Schema, writable customer boundary, and verified local managed runtime, so it can be selected and accept Jobs independently of optional external provider configuration. Workspace Readiness does not imply that every Provider Capability is ready.
_Avoid_: every provider configured, paid generation approved, all stages runnable

**Provider Capability Readiness**:
The independent readiness state of one provider-backed capability such as source understanding, image generation, asset transport, video generation, or subtitle removal. A missing or invalid capability blocks only the stage that requires it and gives a specific configuration path; it does not invalidate Workspace Readiness or unrelated stages.
_Avoid_: one global authenticated flag, domain-wide provider permission, workspace failure

**No-Spend Capability Probe**:
A provider-specific authorization and capability check that cannot create a generation task or consume paid media quota. It prefers read-only account, project, permission, and reachability calls; a storage capability may use a synthetic disposable object to prove write, read, deletion, and post-deletion absence. A capability without a safe probe remains Configured but Unverified until its first separately authorized real operation succeeds.
_Avoid_: test generation, placeholder paid task, key-format-only readiness, secret-bearing diagnostic

**Compatibility Migration**:
A staged transition that lets the existing repository layout and the new plugin/workspace layout use the same behavior before the new layout becomes the default. Historical Jobs remain readable and resumable without rewriting their evidence or replaying completed external work.
_Avoid_: big-bang folder move, history rewrite, unverified default switch

**Parallel Product Build**:
The migration workspace where the new `shotloom/` Plugin Package and sibling `workspace-dev/` Development Workspace are assembled and validated beside the untouched legacy checkout. It becomes the product default only after Behavioral Parity passes.
_Avoid_: in-place restructure, destructive cleanup, rename before validation

**Canonical Default Cutover**:
The atomic, recoverable change that makes CanonicalLayout the creation path for future Jobs after migration integrity, Behavioral Parity, clean installation, Workspace recovery, and a fresh Release Proof Job have all passed. It does not rewrite retained history, switch a running Job, inherit old approvals, or delete LegacyLayout.
_Avoid_: folder rename, plugin activation alone, historical migration, cleanup of the legacy checkout

**Migration Retention**:
The classification of every existing repository asset as Plugin Package content, Development Workspace content, or rebuildable material that need not migrate. Mixed directories are classified item by item so real run history is preserved without shipping caches, private media, or temporary probes.
_Avoid_: copy the whole checkout, discard all scratch work, package generated media

**Behavioral Parity**:
The release condition for structural migration: deterministic rules, bindings, plans, prompts, requests, stage decisions, approvals, QC conclusions, and delivery contents are exactly equivalent, while stochastic generation uses equivalent model routes, inputs, settings, and acceptance outcomes. Existing accepted artifacts and evidence remain intact.
_Avoid_: pixel-identical generation, tests pass somewhere, visual similarity without input parity

**Release Proof Job**:
A newly created Job run through the installed Plugin Package on a Supported Host from Workspace Bootstrap to a final Delivery Outcome using explicit Service Authorization and Generation Approval. A full PASS is required before claiming end-to-end customer readiness.
_Avoid_: migrated historical Job, fixture-only validation, Pre-Seedance-only proof

**Service Authorization**:
Client-owned permission and billing authority for external understanding, image, audio, and video generation services used by the Viral Replica Plugin. It is configured through a protected runtime boundary and never belongs to the plugin package, Client Workspace, or Job evidence.
_Avoid_: bundled API key, plugin credential, shared vendor account

**Service Authorization Profile**:
The non-secret Workspace-scoped record that names one external provider capability, its customer account or project identity, current authorization state, and latest verification time. Its Credential Material is stored separately in macOS Keychain under the immutable Workspace identity and provider; the profile never contains a credential value.
_Avoid_: API key file, global shell environment, shared cross-client credential, provider request evidence

**Credential Material**:
A secret token, key, or credential pair owned by the client and persisted only in macOS Keychain for the first supported release. The plugin retrieves it just in time, injects it only into the exact provider subprocess that needs it, and never writes it to the Plugin Package, Client Workspace, logs, Job evidence, shell configuration, or fallback plaintext storage.
_Avoid_: environment file, workspace secret, installer input, logged authorization header

**Pre-Seedance Handoff**:
The local completion point where upload-ready images, audio, prompts, manifests, and notes are prepared for the user before any Seedance generation. It does not require user confirmation; the user reviews the handoff artifacts themselves.
_Avoid_: intermediate approval, client review gate, manual checkpoint

**Generation Approval**:
Explicit user approval to submit paid/API/batch Seedance generation. A direct user instruction to run Seedance, generate the final video, or directly produce the video is the approval record for the current explicit job/generation round by default; it covers each required Part for that job once, so do not ask for per-Part confirmation. Batch approval exists only when the user explicitly says to run a batch, all jobs, or a named group. Failed-Part retries need new approval. This is the confirmation boundary; it is not part of local handoff preparation.
_Avoid_: handoff, request QC, Seedance input preparation

**Image Work Authorization**:
Authorization created with a formal Job to produce every required storyboard image and make one targeted image retry for each failed Part. It does not authorize video generation, MediaKit work, batch Jobs, or unlimited image retries.
_Avoid_: Generation Approval, batch approval, unlimited image repair

**Delivery Outcome**:
One of the two user-facing loop exits: a Pre-Seedance Handoff, or a completed generated video. Image samples, internal QC, and repair decisions are not delivery outcomes.
_Avoid_: sample review, intermediate checkpoint, stage approval

**Stage Run**:
A complete attempt to carry one Job through its current stage and either advance it or produce a truthful stop outcome. It includes creation, required quality judgment, and state transition, and pauses only for missing required inputs, new paid authorization, or an unrepairable hard failure.
_Avoid_: runner decision, manual loop round, suggested next step

**Job Run**:
A sequence of Stage Runs pinned to one Job that advances automatically across free stages until a Delivery Outcome or a truthful stop condition. Passing an intermediate stage does not pause the Job Run.
_Avoid_: self-audit auto-run, repeated rounds, keep-going mode

**Job Progress**:
The five-stage user view of an active Job Run: 看懂原片, 改好分镜, 写视频脚本, 生成视频, 质检交付. Updates are non-blocking and hide internal stage names, hashes, Ledgers, and checker transcripts unless a truthful stop requires inspection.
_Avoid_: internal status stream, gate transcript, hash report

**Job Intake**:
The single creation path that turns simple user paths into formal Jobs. It validates all source and product inputs, allocates collision-free Job IDs, preserves source duration unless the user explicitly overrides it, chooses only the needed handoff surface, and writes each Job's intake and product-profile evidence. Explicit-task and inbox commands are adapters to this same path.
_Avoid_: rebuilding jobs.csv, adapter-specific defaults, manual queue shaping

**Lifecycle Registry**:
The single interpretation of Job lifecycle rules. It owns initial state, terminal states, ordered status matching, canonical execution stages, and the five-stage Job Progress view while preserving a read-only legacy compatibility path. Artifact schemas and paid authorization remain separate policies.
_Avoid_: runner-local stage maps, adapter-local initial status, duplicated progress labels

**Run Checkpoint**:
A current-Job record that binds completed Stage Run effects to their canonical artifacts and allows a Job Run to resume without repeating completed work or external submissions. Prose status and handoff documents are not Run Checkpoints.
_Avoid_: STATE summary, handoff note, retry from scratch

**Checkpoint Reconstruction**:
A read-only recovery of Run Checkpoints for an unfinished legacy Job from its canonical artifacts and external-submission evidence. It never replays completed work, rewrites a completed Job, or guesses through conflicting state.
_Avoid_: migration replay, history rewrite, state guess

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
The deliverability check after video generation. It blocks only missing, unreadable, or unusable output, missing required streams, materially wrong duration, or decode failure; visual and creative defects are warnings and never trigger automatic video regeneration.
_Avoid_: subjective final review, automatic video retry, creative quality gate

**Final Captions**:
Optional captions added only after Final Technical QC when the user explicitly requests them. Their text and timing come from the actual final audio, while their visual grammar comes from the source video. Seedance generation and local finishing remain caption-free.
_Avoid_: Seedance-generated captions, finishing SRT, pre-QC caption render

**Visual Override**:
A recorded decision to advance with a Usable Artifact after a bounded repair or disputed quality judgment. It never bypasses missing or unusable media, wrong-Job inputs, stale evidence, or paid authorization.
_Avoid_: ignoring QC, taste review, forced PASS

**Visual Warning**:
A non-blocking visual or creative finding on an artifact that remains valid for its next consumer or delivery. It never substitutes for missing or unusable media, stale evidence, or a stage-specific hard input requirement.
_Avoid_: soft fail, client review, hidden failure

**Usable Artifact**:
A readable current-Job artifact in the required format and role that the next stage can consume. Visual or creative imperfections do not make an artifact unusable.
_Avoid_: perfect artifact, QC PASS, polished output

**Forward Progress Rule**:
A Job Run advances whenever the next stage has every required Usable Artifact, even when non-blocking semantic findings remain. Image work may retry the affected defect scope once, then continues with the best usable candidate and a Visual Warning.
_Avoid_: perfect-before-progress, whole-stage rollback, semantic fail-closed

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
A quality judgment that interprets meaning or visible intent, such as source rhythm fidelity, speaker mode, person/product correctness, physical action quality, or whether a prompt preserves the source video's character. It may request one targeted image retry or record a Visual Warning, but it cannot block a Usable Artifact from advancing.
_Avoid_: semantic hard stop, maker self-approval, checker validates file length

**QC Defect Scope**:
The smallest QC Risk Family and artifact region invalidated by a user-visible defect, normally narrowed to a Part, Shot, role, action, line, or seam. Unnamed and unchanged risks retain REUSED_PASS. The scope expands to a whole semantic family only when the user reports a whole-output failure or the defect cannot be localized from current evidence.
_Avoid_: one local complaint invalidates the whole stage, rerun every Part, vague defect reopens everything

**QC Risk Ledger**:
The single stage-level decision artifact consumed by a Stage Run. It lists every required QC Risk Family with its status (`PASS`, `REUSED_PASS`, `VISUAL_WARNING`, `FAIL`, or `STOP`), current QC Risk Fingerprint, evidence provenance, reuse or recheck reason, and any QC Defect Scope. A Stage Run advances through `PASS`, `REUSED_PASS`, and `VISUAL_WARNING`; `FAIL` and `STOP` are reserved for conditions that prevent the next consumer from receiving a Usable Artifact or required authorization.
_Avoid_: runner knows individual QC internals, scattered path guessing, missing one report silently passes

**Targeted QC Repair**:
The failure path that reruns only the smallest producer and artifact region named by each QC Defect Scope. One evaluation reports all currently observable defects together; repair may combine defects owned by the same producer, while unaffected `PASS` and `REUSED_PASS` families remain valid. After repair, only risk families whose fingerprints changed are evaluated again.
_Avoid_: whole-stage rollback, one-defect-at-a-time loops, invalidating unrelated PASS evidence

**QC Evidence Freshness**:
Evidence is current only when it belongs to the active QC Risk Fingerprint and its cited artifacts still exist with matching hashes. A first run, changed fingerprint, expired evidence, or missing prior report triggers normal re-evaluation; semantic defects become `VISUAL_WARNING`, `FAIL` means deterministic evidence proves no Usable Artifact can advance, and `STOP` is reserved for missing authorization, required inputs, or a state conflict that prevents safe writeback.
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

**Artifact Lifecycle**:
The retention rule that keeps only current Job artifacts plus one bounded rollback version. Reproducible temporary files may be discarded, older history is represented by small manifests, and cleanup begins with a read-only preview. Historical artifacts are not part of active QC discovery.
_Avoid_: unlimited deprecated packs, copying a full handoff on every rerun, scanning history during active QC
