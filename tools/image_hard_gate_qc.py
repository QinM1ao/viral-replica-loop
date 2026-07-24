#!/usr/bin/env python3
import argparse
import json
import math
from pathlib import Path

from PIL import Image

from product_profile import find_job, load_product_profile, profile_requires_mud_contract


def load_rgb(path):
    return Image.open(path).convert("RGB")


def iter_pixels(img, step=5):
    pix = img.load()
    w, h = img.size
    for y in range(0, h, step):
        for x in range(0, w, step):
            yield pix[x, y]


def panel_crops(img, cols, rows):
    w, h = img.size
    out = []
    for r in range(rows):
        for c in range(cols):
            x0 = round(c * w / cols)
            x1 = round((c + 1) * w / cols)
            y0 = round(r * h / rows)
            y1 = round((r + 1) * h / rows)
            panel = img.crop((x0, y0, x1, y1))
            pw, ph = panel.size
            out.append(panel.crop((int(pw * 0.08), int(ph * 0.08), int(pw * 0.92), int(ph * 0.86))))
    return out


def mask_ratio(images, mask_fn):
    hit = 0
    total = 0
    for img in images:
        for r, g, b in iter_pixels(img):
            total += 1
            if mask_fn(r, g, b):
                hit += 1
    return 0.0 if total == 0 else hit / total


def white_mud(r, g, b):
    chroma = max(r, g, b) - min(r, g, b)
    return r > 178 and g > 172 and b > 160 and chroma < 45


def cool_white_mud(r, g, b):
    chroma = max(r, g, b) - min(r, g, b)
    return r > 205 and g > 202 and b > 195 and chroma < 32


def gray_mud(r, g, b):
    chroma = max(r, g, b) - min(r, g, b)
    avg = (r + g + b) / 3
    return 75 < avg < 172 and chroma < 32


def yellow_mud_cast(r, g, b):
    return r > 155 and g > 125 and b < 155 and (r - b) > 35 and (g - b) > 18 and (r - g) < 65


def product_green(r, g, b):
    return g > 85 and g > r * 1.16 and g > b * 1.16


def skin_mask(r, g, b):
    return r > 70 and g > 45 and b > 30 and r > g and (r - b) > 18


def mean_rgb(images, mask_fn):
    total = [0.0, 0.0, 0.0]
    count = 0
    for img in images:
        for r, g, b in iter_pixels(img):
            if mask_fn(r, g, b):
                total[0] += r
                total[1] += g
                total[2] += b
                count += 1
    if count == 0:
        return None, 0
    return [v / count for v in total], count


def distance(a, b):
    if not a or not b:
        return None
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def write_md(path, report):
    lines = [
        "# Image Hard Gate QC",
        "",
        f"- Overall: **{report['overall']}**",
        f"- Candidate: `{report['candidate']}`",
        "",
        "## Checks",
        "",
    ]
    for check in report["checks"]:
        lines.append(f"- {check['status']}: `{check['name']}` - {check['detail']}")
    lines.extend(["", "## Metrics", "", "```json", json.dumps(report["metrics"], ensure_ascii=False, indent=2), "```", ""])
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Run hard image checks before Seedance.")
    parser.add_argument("--root", default=".", help="Loop root directory when --job-id is used.")
    parser.add_argument("--job-id", help="When provided, mud checks are enabled only by the job product profile.")
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--part1-anchor", type=Path)
    parser.add_argument("--refs", nargs="*", type=Path, default=[])
    parser.add_argument("--required-ref-name", default="")
    parser.add_argument("--banned-ref-name", action="append", default=[])
    parser.add_argument("--cols", type=int, default=4)
    parser.add_argument("--rows", type=int, default=3)
    parser.add_argument("--expected-ratio", type=float, default=None)
    parser.add_argument("--expected-ratio-from-image", type=Path)
    parser.add_argument("--ratio-tolerance", type=float, default=0.04)
    parser.add_argument("--min-white-ratio", type=float, default=0.06)
    parser.add_argument("--min-cool-white-ratio", type=float, default=0.065)
    parser.add_argument("--max-gray-ratio", type=float, default=0.35)
    parser.add_argument("--max-yellow-ratio", type=float, default=0.22)
    parser.add_argument("--min-green-ratio", type=float, default=0.001)
    parser.add_argument("--skip-mud-checks", action="store_true")
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    args = parser.parse_args()

    if args.job_id and not args.skip_mud_checks:
        root = Path(args.root).resolve()
        job = find_job(root, args.job_id)
        if job:
            product_profile, _, _ = load_product_profile(root, job)
            args.skip_mud_checks = not profile_requires_mud_contract(product_profile)

    img = load_rgb(args.candidate)
    panels = panel_crops(img, args.cols, args.rows)
    checks = []

    expected_ratio = args.expected_ratio if args.expected_ratio is not None else 0.75
    expected_ratio_source = "default_0.75"
    if args.expected_ratio_from_image:
        ref_img = load_rgb(args.expected_ratio_from_image)
        expected_ratio = ref_img.size[0] / ref_img.size[1]
        expected_ratio_source = str(args.expected_ratio_from_image)

    ratio = img.size[0] / img.size[1]
    layout_ok = abs(ratio - expected_ratio) < args.ratio_tolerance and len(panels) == args.cols * args.rows
    checks.append({
        "name": "layout",
        "status": "PASS" if layout_ok else "FAIL",
        "detail": f"size={img.size}, ratio={ratio:.3f}, expected_ratio={expected_ratio:.3f}, tolerance={args.ratio_tolerance:.3f}, source={expected_ratio_source}, grid={args.cols}x{args.rows}",
    })

    ref_names = [p.name for p in args.refs]
    if args.required_ref_name:
        count = ref_names.count(args.required_ref_name)
        checks.append({
            "name": "required_identity_ref",
            "status": "PASS" if count == 1 else "FAIL",
            "detail": f"{args.required_ref_name} count={count}",
        })
    banned = sorted(set(ref_names).intersection(args.banned_ref_name))
    checks.append({
        "name": "banned_refs",
        "status": "PASS" if not banned else "FAIL",
        "detail": f"banned={banned}",
    })

    white_ratio = cool_white_ratio = gray_ratio = yellow_ratio = None
    if not args.skip_mud_checks:
        white_ratio = mask_ratio(panels, white_mud)
        cool_white_ratio = mask_ratio(panels, cool_white_mud)
        gray_ratio = mask_ratio(panels, gray_mud)
        yellow_ratio = mask_ratio(panels, yellow_mud_cast)
        checks.append({
            "name": "white_not_gray_mud",
            "status": "PASS" if white_ratio >= args.min_white_ratio and gray_ratio <= args.max_gray_ratio else "FAIL",
            "detail": f"white_ratio={white_ratio:.3f}, gray_ratio={gray_ratio:.3f}, min_white={args.min_white_ratio:.3f}",
        })
        checks.append({
            "name": "cool_white_mud_presence",
            "status": "PASS",
            "detail": (
                f"advisory_only: cool_white_ratio={cool_white_ratio:.3f}, "
                f"reference_min={args.min_cool_white_ratio:.3f}; whole-panel sampling includes skin/background"
            ),
        })
        checks.append({
            "name": "yellow_beige_mud_cast_guardrail",
            "status": "PASS",
            "detail": (
                f"advisory_only: yellow_ratio={yellow_ratio:.3f}, "
                f"reference_max={args.max_yellow_ratio:.3f}; whole-panel sampling includes skin/background"
            ),
        })
    else:
        checks.append({
            "name": "mud_checks_skipped",
            "status": "PASS",
            "detail": "skip-mud-checks enabled for a non-mud product",
        })

    green_ratio = mask_ratio(panels, product_green)
    checks.append({
        "name": "product_green_marker",
        "status": "PASS" if green_ratio >= args.min_green_ratio else "FAIL",
        "detail": f"green_ratio={green_ratio:.4f}, min_green={args.min_green_ratio:.4f}",
    })

    skin_dist = None
    if args.part1_anchor:
        anchor = load_rgb(args.part1_anchor)
        anchor_panels = panel_crops(anchor, args.cols, args.rows)
        cand_skin, cand_count = mean_rgb(panels, skin_mask)
        anchor_skin, anchor_count = mean_rgb(anchor_panels, skin_mask)
        skin_dist = distance(cand_skin, anchor_skin)
        checks.append({
            "name": "skin_color_consistency",
            "status": "PASS" if skin_dist is not None and skin_dist <= 36 else "FAIL",
            "detail": f"distance={skin_dist}, candidate_pixels={cand_count}, anchor_pixels={anchor_count}",
        })

    status_order = {"PASS": 0, "FAIL": 1, "STOP": 2}
    overall = max((c["status"] for c in checks), key=lambda s: status_order[s])
    report = {
        "overall": overall,
        "candidate": str(args.candidate),
        "checks": checks,
        "metrics": {
            "size": img.size,
            "ratio": ratio,
            "expected_ratio": expected_ratio,
            "expected_ratio_source": expected_ratio_source,
            "white_ratio": white_ratio,
            "cool_white_ratio": cool_white_ratio,
            "gray_ratio": gray_ratio,
            "yellow_ratio": yellow_ratio,
            "green_ratio": green_ratio,
            "skin_distance": skin_dist,
        },
    }
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_md(args.out_md, report)
    print(overall)


if __name__ == "__main__":
    main()
