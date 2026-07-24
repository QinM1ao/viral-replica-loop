# Output Quality Scorecard

Skill: `video-replication`

Evidence mode: `file-backed fixtures plus provider-backed Part and complete-pair validations`.

## Summary

| Area | Current status | Notes |
|---|---|---|
| Trigger cases | present | `evals/trigger_cases.json` separates craft work from loop operation. |
| Output cases | present | `evals/output_cases.json` records story, story-to-Seedance prompt, image-edit, skincare, product-label, role-map, and the complete Kongfengchun 26-second pair assertions. |
| Same-case output validation | pass | `reports/actual_validation_20260703/story_to_prompt_validation.md` records live Codex regeneration of Part1/Part2 prompts against the final successful `job-001` standard. |
| Fast default pipeline validation | pass | `reports/fast_pipeline_validation_20260703.md` records the `pre_seedance_pack` replacement, runner regression test, timing evidence, and archive path. |
| Provider-backed output validation | pass for current case | `reports/actual_validation_20260717_kongfengchun_final_26s.md` records the accepted opening-only Part1 repair, accepted Part2 repair, exact-Part concatenation, and passing final technical QC. |
| Blind A/B review | missing evidence | No reviewer decisions are recorded yet. |
| Release readiness | not release ready | Structural assets exist, but governed release evidence is incomplete. |

## Current Quality Claims

- Story analysis comes before voiceover and Seedance prompt writing.
- Final Seedance prompts are derived through a shot-line map from story analysis, ASR/subtitles, visual timeline, product profile, voiceover, seam notes, and approved references.
- Final Seedance prompts distinguish narration from in-frame synchronous speech and bind product refs to identity/material only, preventing white-background packshot leakage.
- Execution blocks cannot cross narration/in-frame-sync boundaries. Scene or visual-function changes also require a new block, and short still-life B-roll is standalone.
- Identity references lock the approved person and clothing without transferring their background or overriding Shot-specific skin state.
- The current Kongfengchun standard is the complete accepted 26-second pair: Part1 uses physical contact-motion-result wording and locked-block repair; Part2 matches product-close framing around a B-roll hard cut and uses profile-specific flawless post-wash wording.
- Local prompt repair changes only the declared failing time-and-Shot block. Accepted prompt blocks, assets, model settings, and Parts stay locked.
- Artifact hashes are internal fingerprints for stale-evidence detection, QC reuse, and provenance. They are not generation seeds and are not presented as a user workflow step.
- Same-case validation regenerated Part1 and Part2 prompts with 0.902 / 0.923 similarity to the final successful prompts while passing structure, story-beat, speaker-layering, product-binding, and banned-term checks.
- After image batch PASS, the default path uses one compact Pre-Seedance pack instead of serial voiceover, seam, Seedance prompt, audio boundary, and request QC stages.
- Final delivery QC is a fast technical check; final generated-video ASR is not a routine delivery gate.
- Image-stage outputs must be saved AI-edited storyboard assets, not source frames or composites.
- Image-stage Matpool prompts must use a validated rolemap structure and include a hard source-scene rule, so product/model reference backgrounds cannot replace the original source scene.
- Product profiles with visible text require major brand/product-name anchors and the real label design in designated hero close-ups. Distant, oblique, multi-bottle, and storyboard-scale microtext is visual-match-only; microtext-only mismatch is a warning, while wrong product/brand, blank/smoothed/old-source labels, and wrong label design remain hard failures.
- Multi-person source stories require a role map so the approved identity is applied only to the protagonist/product-host role.
- Skincare and beauty jobs require visible before/after progression; white thick mud applies only when the product profile loads `category:clay_mask`.

## Required Before Release

- Run provider-backed trigger eval.
- Run output eval with a new unseen holdout video, including baseline and with-skill outputs.
- Record blind review decisions.
- Reduce `SKILL.md` load by moving more long-form policy into references.
- Run one fresh end-to-end job through the new `pre_seedance_pack` default and compare timing against the historical five-stage path.
