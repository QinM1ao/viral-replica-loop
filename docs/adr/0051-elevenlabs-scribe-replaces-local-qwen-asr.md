# ADR 0051: ElevenLabs Scribe replaces local Qwen ASR

ShotLoom uses ElevenLabs `scribe_v1` through the production Wujie Higress `/elevenlabs/v1/speech-to-text` route as its sole default ASR provider. Requests enable diarization, audio-event tagging, and word timestamps. The raw provider response remains immutable evidence; ShotLoom additionally derives speaker turns and sentence segments and binds ASR character spans to word times during source-rhythm QC.

This removes the Qwen MLX package, Python 3.14 ASR environment, model download, warm-up, offline cache validation, and Qwen-specific concurrency class from the active workflow. Workspace setup checks the existing Higress credential configuration instead of preparing a local ASR model; the first real source transcription remains the definitive endpoint/authentication check.

Speaker IDs and word timestamps replace manual source-audio sentence-boundary discovery and speaker-change estimation. They do not replace measured visual cuts, pixel evidence, visible-text/OCR review, semantic video understanding, or the visual decision between voiceover and in-frame synchronized speech. Final target audio is still transcribed when boundary verification is required because rewritten or regenerated audio does not inherit source timestamps.

ASR mistakes are corrected in a separate review layer. Visible text is preferred evidence. An obvious lexical or contextual error may be recorded as `semantic_review` only with a written reason and confidence of at least 0.9. Ambiguous alternatives remain unresolved, and the raw ElevenLabs transcript is never overwritten.
