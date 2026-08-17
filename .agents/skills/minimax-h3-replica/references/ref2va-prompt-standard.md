# MiniMax H3 Ref2VA Prompt Standard

This is the prompt source of truth for `minimax-h3-replica`. It adapts the official `h3-prompt-writing` full-reference rules to source-faithful ShotLoom replication.

## Required Structure

Write these six sections in this exact order:

```text
subject_definitions:
...

summary:
...

retention_analysis:
...

detailed_description:
...

overall_soundscape:
...

non_diegetic_music:
...
```

Write the sections in English. Preserve dialogue, lyrics, and intended visible text in their original language.

## Labels

- `<Subject N>` identifies reusable visible content: target people, products, environments, clothing, props, actions, or styles.
- `<Picture N>` identifies a supplied image only when the image itself anchors a frame, keyframe, composition, or storyboard. When an image only defines a subject, cite it inside that `<Subject N>` definition.
- `<Video N>` identifies a whole-video relationship: direct editing, continuation, camera motion, cut rhythm, or temporal structure.
- `<Audio N>` identifies a standalone signal used for copying or reference.

Assign each asset one stable label meaning and reuse that meaning in all six sections. Do not create a label that never appears after `subject_definitions`.

## Summary Prefix

For direct source-video replication with replacement references and a reused master soundtrack, begin with:

```text
[video editing + reference generation + audio reuse] The target video is an edited version of <Video 1>.
```

Use `audio reference` instead of `audio reuse` when the signal supplies only wording, timbre, rhythm, or style and is not intended to be copied.

## Retention Markers

Use only these visible-content markers:

- `fully_preserved`
- `partially_preserved`
- `attribute_transfer`
- `weak_reference`

Use only these audio markers:

- `fully_copy`: the complete source audio is the target video's complete final soundtrack.
- `partially_copy`: only part of the timeline or selected layers are copied, or another layer is added, removed, or replaced.
- `reference`: the signal guides content, timbre, rhythm, style, or texture without signal copying.
- `weak_reference`: only broad audio similarity is requested.

Never label a master `fully_copy` while also requesting generated ambience, effects, music, speech, ducking, mixing, time-stretching, or source-video audio.

## Time Axis and Shots

Represent the source edit as a complete time axis plus Shots:

```text
[Shot 1] ...
[Shot 2] At 00:01.067, a hard cut ...
[Shot 3] At 00:01.833, a hard cut ...
```

- Use one Shot for every measured source interval, including rapid product inserts and brief action-result shots.
- Keep Shot numbers continuous through the unit; do not collapse repeated-looking intervals when their actions or edit functions differ.
- Describe composition, subjects, environment, lighting, actions and state changes, camera behavior, current sound, and active references for each Shot.
- Keep every timestamp inside the requested unit duration and remap split units to `00:00.000`.
- Use `<scenetrans>` when a reused spoken phrase crosses a hard cut and `<cutoff>` only when the target deliberately ends mid-utterance.

Completion requires exact coverage: every measured source interval appears once and every prompt Shot maps back to one interval.

## Fully Copied Master Pattern

Define the audio as the final signal, not as a voice to perform:

```text
<Audio 1> is the complete 13.000-second final soundtrack; reuse the entire signal unchanged, including its exact words, voice identity, delivery, pauses, timing, silence, waveform, and duration.
```

Use:

```text
<Audio 1>: fully_copy - <Audio 1> is reused 1:1 as the complete final audio track, with no regeneration, reperformance, rewriting, omission, insertion, mixing, time-stretching, ducking, replacement, or additional layer.
```

In `detailed_description`, treat phrases as synchronization cues:

```text
When the directly reused <Audio 1> reaches <d>[Chinese] ...</d>, the visible action reaches its corresponding peak; no voice is generated or re-performed.
```

Use:

```text
overall_soundscape:
<Audio 1> is directly reused unchanged as the complete and only final soundtrack. Generate no additional audio layer and do not use <Video 1>'s original audio.

non_diegetic_music:
N/A
```

This wording improves reuse compliance but does not make H3 a guaranteed waveform-passthrough service. Preserve the approved master for postmix.

## Complete-Person Replacement Contract

When the user asks to replace a person, treat that person's image as the source for the complete target person and clothing, never as an identity-only reference.

In `subject_definitions`, define every replaced person with all visible attributes supplied by the intended picture: face, hair and hairline, body proportions, skin tone, arms and hands, clothing, and visible accessories. Use this binding pattern:

```text
<Subject N> is the complete [role] defined by <Picture N>, including [face, hair, body, skin tone, hands, clothing, and visible accessories]. Transfer the complete person and clothing only. <Picture N> is not a background, environment, lighting, composition, framing, pose, action, or camera reference; those elements come only from <Video 1>.
```

In `retention_analysis`:

- mark `<Video 1>` as `partially_preserved` whenever a person, clothing, product, or overlay changes;
- give each replaced person `attribute_transfer` for the complete person and clothing in exactly one assigned source-video role;
- keep the source-video background, environment, lighting, composition, framing, pose, action path, and camera behavior; do not transfer those attributes from the person picture;
- give each replacement product `attribute_transfer` for its complete visible construction and graphics.

In every Shot where a replaced role is visible, replace the entire source person and source clothing with the complete target `<Subject N>`. Bind the target face, hair, body, skin, arms, hands, clothing, and accessories to that subject; bind the shot's environment, lighting, composition, framing, pose, action, timing, and camera behavior to `<Video 1>`. Bind every old-product appearance in the same Shot to the intended replacement-product subject. Repeat these bindings after every hard cut instead of relying on the summary.

For multiple people, define and bind each role separately. Keep their identities, bodies, hands, clothing, accessories, and shot assignments separate throughout the unit.

## Source-Faithful Edit Rules

Define `<Video 1>` as the direct edit source. State exactly which dimensions remain: cut timing, shot order, framing, action path, camera behavior, scene, and product-handling rhythm. State exactly which dimensions change: target person, target product, incompatible product state, obsolete overlays, or user-requested text.

Describe replacement subjects positively and concretely. Apply the Complete-Person Replacement Contract to every replaced-person role. For products, include construction, cap/nozzle/opening, label anchors, colors, native graphics, and physical material behavior visible in the current Shot.

End the final Shot with a trim-safe hold when the provider duration exceeds the effective source action. Request no new shot, object, speech, sound, or transition in that tail.

## Prompt QC

Reject the prompt when any condition is true:

- the six sections are missing or reordered;
- a label changes meaning or remains unresolved;
- the Shot list omits, duplicates, merges, or reorders a measured source interval;
- dialogue text differs from the approved master;
- a timestamp exceeds the unit duration;
- `fully_copy` competes with another requested audio layer;
- the description asks H3 to generate the voice instead of reusing the signal;
- the target person or product is not bound at each relevant appearance;
- a requested person replacement is described as identity-only, preserves the source person's clothing, or omits the target face, hair, body, hands, or clothing;
- a person picture supplies or changes the background, environment, lighting, composition, framing, pose, action, or camera behavior;
- a replaced role is not bound as the complete target person and clothing again after a hard cut;
- an old-product appearance is not bound to the intended replacement product;
- the last interval invites a new invented shot.
