#!/usr/bin/env python3
"""Deterministically restore storyboard Shot navigation labels.

This is a metadata-only postprocess. It redraws the dark label bars and never
edits panel-image pixels. It must not be used to combine, replace, or repair
storyboard visual content. When an image model omits a label bar, an optional
same-canvas label template may define that missing metadata-only region.
"""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def font_path():
    for candidate in [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]:
        if Path(candidate).exists():
            return candidate
    return None


def is_label_bar_pixel(pixel):
    red, green, blue = pixel[:3]
    return (
        28 <= red <= 48
        and 28 <= green <= 48
        and 28 <= blue <= 48
        and max(red, green, blue) - min(red, green, blue) <= 5
    )


def contiguous_runs(values, minimum_length):
    runs = []
    start = None
    for index, value in enumerate(values):
        if value and start is None:
            start = index
        if start is not None and (not value or index == len(values) - 1):
            end = index if not value else index + 1
            if end - start >= minimum_length:
                runs.append((start, end))
            start = None
    return runs


def detect_label_runs(image):
    width, height = image.size
    step = max(1, width // 440)
    row_hits = []
    for y in range(height):
        samples = [image.getpixel((x, y)) for x in range(0, width, step)]
        fraction = sum(is_label_bar_pixel(pixel) for pixel in samples) / len(samples)
        row_hits.append(fraction >= 0.45)

    return contiguous_runs(row_hits, max(3, height // 300))


def detect_label_bands(image, rows):
    _, height = image.size
    runs = detect_label_runs(image)
    if len(runs) == rows:
        return runs
    if len(runs) < rows:
        raise RuntimeError(
            f"detected {len(runs)} of {rows} Shot-label bars; "
            "use --label-template with a same-canvas approved storyboard"
        )

    selected = []
    for row in range(rows):
        segment_start = row * height / rows
        segment_end = (row + 1) * height / rows
        candidates = [
            run
            for run in runs
            if segment_start <= (run[0] + run[1]) / 2 < segment_end
        ]
        if not candidates:
            raise RuntimeError(f"could not detect Shot-label bar for row {row + 1}")
        selected.append(max(candidates, key=lambda run: (run[1] - run[0], run[1])))

    if len(set(selected)) != rows:
        raise RuntimeError("detected duplicate Shot-label bars")
    return selected


def resolve_label_bands(image, rows, label_template=None):
    candidate_runs = detect_label_runs(image)
    if len(candidate_runs) == rows:
        return candidate_runs, ["candidate"] * rows, candidate_runs, None

    if label_template is None:
        return detect_label_bands(image, rows), ["candidate"] * rows, candidate_runs, None

    if label_template.size != image.size:
        raise RuntimeError(
            "label template canvas must match input canvas: "
            f"input={image.size} template={label_template.size}"
        )

    template_bands = detect_label_bands(label_template, rows)
    resolved = [None] * rows
    sources = [None] * rows
    tolerance = max(8, round(image.height / rows / 4))

    for candidate in candidate_runs:
        candidate_center = (candidate[0] + candidate[1]) / 2
        ranked = sorted(
            (
                (abs(candidate_center - (band[0] + band[1]) / 2), index)
                for index, band in enumerate(template_bands)
                if resolved[index] is None
            ),
            key=lambda item: item[0],
        )
        if not ranked or ranked[0][0] > tolerance:
            continue
        _, index = ranked[0]
        resolved[index] = candidate
        sources[index] = "candidate"

    for index, template_band in enumerate(template_bands):
        if resolved[index] is None:
            resolved[index] = template_band
            sources[index] = "template"

    if any(band is None for band in resolved):
        raise RuntimeError("could not resolve every Shot-label bar")
    if len(set(resolved)) != rows:
        raise RuntimeError("resolved duplicate Shot-label bars")
    return resolved, sources, candidate_runs, template_bands


def dominant_bar_color(image, bands):
    pixels = []
    width, _ = image.size
    step = max(1, width // 440)
    for top, bottom in bands:
        for y in range(top, bottom):
            for x in range(0, width, step):
                pixel = image.getpixel((x, y))[:3]
                if is_label_bar_pixel(pixel):
                    pixels.append(tuple(pixel))
    if not pixels:
        return (38, 38, 38)
    most_common = Counter(pixels).most_common(1)[0][0]
    level = round(sum(most_common) / 3)
    return (level, level, level)


def count_changes(before, after, bands):
    width, height = before.size
    outside = 0
    inside = 0
    for y in range(height):
        in_band = any(top <= y < bottom for top, bottom in bands)
        for x in range(width):
            if before.getpixel((x, y)) == after.getpixel((x, y)):
                continue
            if in_band:
                inside += 1
            else:
                outside += 1
    return inside, outside


def panel_content_sha256(image, bands):
    """Hash every pixel except the deterministic Shot-label bands."""
    digest = hashlib.sha256()
    digest.update(
        json.dumps(
            {
                "mode": image.mode,
                "size": list(image.size),
                "excluded_label_bands": [[top, bottom] for top, bottom in bands],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    width, height = image.size
    for y in range(height):
        if any(top <= y < bottom for top, bottom in bands):
            continue
        digest.update(image.crop((0, y, width, y + 1)).tobytes())
    return digest.hexdigest()


def restore(
    input_path,
    output_path,
    evidence_path,
    cols,
    rows,
    label_template_path=None,
):
    before = Image.open(input_path).convert("RGB")
    label_template = (
        Image.open(label_template_path).convert("RGB")
        if label_template_path is not None
        else None
    )
    bands, band_sources, candidate_bands, template_bands = resolve_label_bands(
        before,
        rows,
        label_template=label_template,
    )
    after = before.copy()
    draw = ImageDraw.Draw(after)
    bar_color = dominant_bar_color(before, bands)
    labels = [f"Shot {index:02d}" for index in range(1, cols * rows + 1)]
    font_file = font_path()

    for row, (top, bottom) in enumerate(bands):
        bar_height = bottom - top
        font_size = max(10, round(bar_height * 0.45))
        label_font = (
            ImageFont.truetype(font_file, font_size)
            if font_file
            else ImageFont.load_default()
        )
        draw.rectangle((0, top, before.width - 1, bottom - 1), fill=bar_color)
        for col in range(cols):
            cell_left = round(col * before.width / cols)
            label = labels[row * cols + col]
            text_y = top + max(1, (bar_height - font_size) // 2 - 1)
            draw.text(
                (cell_left + max(6, round(before.width * 0.016)), text_y),
                label,
                fill=(0, 190, 255),
                font=label_font,
            )

    inside_changes, outside_changes = count_changes(before, after, bands)
    if outside_changes:
        raise RuntimeError(
            f"refusing output: {outside_changes} pixels changed outside Shot-label bars"
        )

    content_hash_before = panel_content_sha256(before, bands)
    content_hash_after = panel_content_sha256(after, bands)
    if content_hash_before != content_hash_after:
        raise RuntimeError("refusing output: panel-content fingerprint changed")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    after.save(output_path, "PNG")
    report = {
        "status": "PASS",
        "postprocess_type": "shot_label_metadata_only",
        "input": str(input_path),
        "input_sha256": sha256_file(input_path),
        "output": str(output_path),
        "output_sha256": sha256_file(output_path),
        "canvas": [before.width, before.height],
        "grid": {"cols": cols, "rows": rows},
        "labels": labels,
        "label_bands": [[top, bottom] for top, bottom in bands],
        "label_band_sources": band_sources,
        "candidate_detected_label_bands": [
            [top, bottom] for top, bottom in candidate_bands
        ],
        "label_template": str(label_template_path) if label_template_path else None,
        "label_template_sha256": (
            sha256_file(label_template_path) if label_template_path else None
        ),
        "label_template_bands": (
            [[top, bottom] for top, bottom in template_bands]
            if template_bands is not None
            else None
        ),
        "changed_pixels_in_label_bands": inside_changes,
        "outside_label_changed_pixels": outside_changes,
        "panel_pixels_modified": False,
        "panel_content_sha256_before": content_hash_before,
        "panel_content_sha256_after": content_hash_after,
        "allowed_change": "Shot navigation label bars only",
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--label-template", type=Path)
    parser.add_argument("--cols", type=int, required=True)
    parser.add_argument("--rows", type=int, required=True)
    args = parser.parse_args()

    if args.cols <= 0 or args.rows <= 0:
        raise SystemExit("--cols and --rows must be positive")
    if args.input.resolve() == args.output.resolve():
        raise SystemExit("--output must differ from --input")

    report = restore(
        args.input,
        args.output,
        args.evidence,
        args.cols,
        args.rows,
        label_template_path=args.label_template,
    )
    print(report["output"])
    print(report["output_sha256"])


if __name__ == "__main__":
    main()
