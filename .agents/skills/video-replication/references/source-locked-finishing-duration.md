# Source-Locked Finishing Duration

Use this branch when the job preserves source wording and cadence instead of compressing to a shorter target.

1. Initialize finishing with every selected Part kept in full at `speed=1.0`. Completion: every approved Part and complete spoken line is present in order.
2. Evaluate duration with the same target and tolerance passed to Final Technical QC. Exact equality with the source is not a repair goal. Completion: an overrun inside the configured tolerance is accepted when it comes from complete `source_locked` speech.
3. Change the timeline only for an objective defect such as a bad interval, duplicate boundary, broken speech, or failed technical check. Completion: every cut or speed change names the defect it fixes and still passes story-integrity review.

This keeps full speech ahead of cosmetic timestamp matching while retaining a measurable technical boundary.
