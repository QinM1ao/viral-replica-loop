#!/usr/bin/env python3
import argparse
import json
import math
from pathlib import Path

from PIL import Image


def load_rgb(path):
    return Image.open(path).convert("RGB")


def panel_crops(img, cols=4, rows=3):
    w, h = img.size
    crops = []
    for r in range(rows):
        for c in range(cols):
            x0 = round(c * w / cols)
            x1 = round((c + 1) * w / cols)
            y0 = round(r * h / rows)
            y1 = round((r + 1) * h / rows)
            crop = img.crop((x0, y0, x1, y1))
            cw, ch = crop.size
            # Remove gutters, borders, and blue Shot labels from the coarse metric.
            crops.append(crop.crop((int(cw * 0.08), int(ch * 0.08), int(cw * 0.92), int(ch * 0.86))))
    return crops


def iter_pixels(img, step=4):
    pix = img.load()
    w, h = img.size
    for y in range(0, h, step):
        for x in range(0, w, step):
            yield pix[x, y]


def mean_rgb_for_mask(panels, indices, mask_fn):
    total = [0.0, 0.0, 0.0]
    count = 0
    for idx in indices:
        if idx >= len(panels):
            continue
        for r, g, b in iter_pixels(panels[idx]):
            if mask_fn(r, g, b):
                total[0] += r
                total[1] += g
                total[2] += b
                count += 1
    if count == 0:
        return None, 0
    return [v / count for v in total], count


def skin_mask(r, g, b):
    return (
        r > 70
        and g > 45
        and b > 30
        and r > g
        and g >= b * 0.82
        and (r - b) > 18
        and max(r, g, b) - min(r, g, b) > 18
    )


def color_distance(a, b):
    if not a or not b:
        return None
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def ratio_for_mask(panels, indices, mask_fn):
    hit = 0
    total = 0
    for idx in indices:
        if idx >= len(panels):
            continue
        for r, g, b in iter_pixels(panels[idx]):
            total += 1
            if mask_fn(r, g, b):
                hit += 1
    return 0.0 if total == 0 else hit / total


def mud_region(panel):
    w, h = panel.size
    return panel.crop((int(w * 0.16), int(h * 0.08), int(w * 0.84), int(h * 0.58)))


def white_mud_mask(r, g, b):
    chroma = max(r, g, b) - min(r, g, b)
    return r > 178 and g > 172 and b > 160 and chroma < 42


def gray_mud_mask(r, g, b):
    chroma = max(r, g, b) - min(r, g, b)
    avg = (r + g + b) / 3
    return 75 < avg < 172 and chroma < 30


def product_green_mask(r, g, b):
    return g > 85 and g > r * 1.16 and g > b * 1.16


def write_md(path, data):
    lines = [
        "# Storyboard Loop QC",
        "",
        f"- Candidate: `{data['candidate']}`",
        f"- Part1 anchor: `{data['part1_anchor']}`",
        f"- Overall: **{data['overall']}**",
        "",
        "## Checks",
        "",
    ]
    for check in data["checks"]:
        status = "PASS" if check["pass"] else "FAIL"
        lines.append(f"- {status}: {check['name']} - {check['detail']}")
    lines.extend(["", "## Metrics", "", "```json", json.dumps(data["metrics"], ensure_ascii=False, indent=2), "```", ""])
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--part1-anchor", required=True)
    parser.add_argument("--refs", nargs="*", default=[])
    parser.add_argument("--expected-ratio", type=float, default=None)
    parser.add_argument("--expected-ratio-from-image")
    parser.add_argument("--ratio-tolerance", type=float, default=0.04)
    parser.add_argument("--required-ref-name", default="", help="Require exactly one reference with this file name.")
    parser.add_argument("--banned-ref-name", action="append", default=[], help="Reject references with this file name. Can be repeated.")
    parser.add_argument("--check-white-mud", action="store_true", help="Enable clay-mask white/gray mud tripwire on panels 6 and 10.")
    parser.add_argument("--require-green-marker", action="store_true", help="Enable coarse green product-marker tripwire.")
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-md", required=True)
    args = parser.parse_args()

    cand = load_rgb(args.candidate)
    part1 = load_rgb(args.part1_anchor)
    cand_panels = panel_crops(cand)
    part1_panels = panel_crops(part1)

    candidate_ratio = cand.size[0] / cand.size[1]
    expected_ratio = args.expected_ratio if args.expected_ratio is not None else 3 / 4
    expected_ratio_source = "default_0.75"
    if args.expected_ratio_from_image:
        expected_img = load_rgb(args.expected_ratio_from_image)
        expected_ratio = expected_img.size[0] / expected_img.size[1]
        expected_ratio_source = args.expected_ratio_from_image
    min_long_edge = 900
    min_short_edge = 500
    size_ok = max(cand.size) >= min_long_edge and min(cand.size) >= min_short_edge
    layout_ok = abs(candidate_ratio - expected_ratio) < args.ratio_tolerance and size_ok

    banned_names = set(args.banned_ref_name)
    banned_refs = [p for p in args.refs if Path(p).name in banned_names]
    required_refs = [p for p in args.refs if args.required_ref_name and Path(p).name == args.required_ref_name]
    ref_ok = not banned_refs
    if args.required_ref_name:
        ref_ok = ref_ok and len(required_refs) == 1

    face_indices = [0, 1, 2, 3, 4, 8, 10, 11]
    part1_skin, part1_skin_count = mean_rgb_for_mask(part1_panels, face_indices, skin_mask)
    cand_skin, cand_skin_count = mean_rgb_for_mask(cand_panels, face_indices, skin_mask)
    skin_dist = color_distance(part1_skin, cand_skin)
    # This is a coarse tripwire, not a face identity score.
    color_ok = skin_dist is not None and skin_dist <= 34 and cand_skin_count > 250

    white_ratio = None
    gray_ratio = None
    mud_ok = True
    if args.check_white_mud:
        mud_indices = [5, 9]  # Shot 06 and Shot 10 in a 12-panel board.
        mud_panels = [mud_region(cand_panels[i]) for i in mud_indices]
        white_ratio = ratio_for_mask(mud_panels, [0, 1], white_mud_mask)
        gray_ratio = ratio_for_mask(mud_panels, [0, 1], gray_mud_mask)
        mud_ok = white_ratio >= 0.18 and gray_ratio <= 0.30

    green_ratio = None
    product_ok = True
    if args.require_green_marker:
        product_indices = [5, 9, 10, 11]
        green_ratio = ratio_for_mask(cand_panels, product_indices, product_green_mask)
        product_ok = green_ratio >= 0.002

    checks = [
        {
            "name": "reference manifest",
            "pass": ref_ok,
            "detail": f"required_ref={args.required_ref_name or 'none'}, required_count={len(required_refs)}, banned_refs={banned_refs}",
        },
        {
            "name": "storyboard canvas ratio",
            "pass": layout_ok,
            "detail": f"size={cand.size}, ratio={candidate_ratio:.3f}, expected_ratio={expected_ratio:.3f}, tolerance={args.ratio_tolerance:.3f}, source={expected_ratio_source}",
        },
        {
            "name": "cross-part skin/color consistency",
            "pass": color_ok,
            "detail": f"skin_rgb_distance={skin_dist}, candidate_skin_pixels={cand_skin_count}",
        },
        {
            "name": "white thick mud, not gray old mud",
            "pass": mud_ok,
            "detail": "skipped" if not args.check_white_mud else f"white_ratio={white_ratio:.3f}, gray_ratio={gray_ratio:.3f}",
        },
        {
            "name": "target product green visual marker",
            "pass": product_ok,
            "detail": "skipped" if not args.require_green_marker else f"green_ratio={green_ratio:.4f}",
        },
    ]
    overall = "PASS" if all(c["pass"] for c in checks) else "FAIL"
    data = {
        "candidate": str(Path(args.candidate)),
        "part1_anchor": str(Path(args.part1_anchor)),
        "refs": args.refs,
        "overall": overall,
        "checks": checks,
        "metrics": {
            "candidate_size": cand.size,
            "candidate_ratio": candidate_ratio,
            "expected_ratio": expected_ratio,
            "expected_ratio_source": expected_ratio_source,
            "part1_skin_rgb": part1_skin,
            "candidate_skin_rgb": cand_skin,
            "skin_rgb_distance": skin_dist,
            "white_mud_ratio": white_ratio,
            "gray_mud_ratio": gray_ratio,
            "product_green_ratio": green_ratio,
        },
    }

    Path(args.out_json).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    write_md(args.out_md, data)
    print(overall)
    for check in checks:
        print(("PASS" if check["pass"] else "FAIL") + ":", check["name"], "-", check["detail"])


if __name__ == "__main__":
    main()
