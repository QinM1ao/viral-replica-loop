# Auto-Repair Product Reference Still Inserts

## Decision

Local finishing must scan the rendered master against the approved `product_*`
reference images before publishing `final_video.mp4`.

A failure requires several consecutive frames with all three signals:

- a strong geometric feature match to the approved reference;
- a high inlier ratio;
- matched reference features covering a large part of the video frame.

This distinguishes a reference image pasted or enlarged into the video from a
normal product shot that merely preserves the correct label.

When a failure is found, finishing may automatically replace only that visual
interval with a clean moving product interval from the same rendered video.
The original audio stream is copied unchanged, total duration is preserved, and
the detector must pass on the repaired result. If no safe same-video interval
exists, finishing stops.

## Rationale

The defect is generated-video pixel content, so it is cheaper and more stable
to repair locally than to request another paid generation. Limiting replacement
sources to the same approved video avoids introducing a new person, product, or
scene. Binding the report to the current product references and output prevents
stale detection evidence from passing the finishing gate.
