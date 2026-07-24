# Subtitle-removal visual QC

Apply these checks to the current project's artifact after either branch. For MediaKit output, all checks are required.

## Technical integrity

1. Run `ffprobe` on source and result. Match duration, dimensions, frame rate, and required audio streams.
2. Run `ffmpeg -v error -i <result> -f null -`. Any decode error is `FAIL`.
3. Preserve the original file and keep the repaired output at a distinct path.

## Coverage

Create source and result contact sheets that cover every subtitle-bearing interval. One frame per second is a useful first pass for short videos; add denser samples for captions shorter than one second.

Inspect every former subtitle interval for:

- remaining glyphs, outlines, shadows, or halos
- a fixed blur band or smeared patch
- damaged faces, hands, hair, clothing, phones, or product edges
- erased or softened product labels, signs, UI text, and other valid scene text

## Temporal repair

Choose at least two high-risk windows: one where subtitles overlap a moving subject and one around a caption or shot transition. Extract at least 8 frames per second across each window and inspect them in order.

Stable reconstructed texture with no blinking text, crawling smear, or repaired-area flicker is `PASS`. Record the exact time range for every defect.

## Acceptance

The result passes only when:

- all intended subtitles are absent
- valid scene text remains usable
- foreground subjects have no obvious repair damage
- high-risk windows are temporally stable
- the file decodes and retains the required audio

Any unmet item is `FAIL`. Report the evidence before considering another paid attempt.
