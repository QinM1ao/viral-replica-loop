#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path

from qc_input_binding import attach_input_binding

from PIL import Image, ImageDraw, ImageOps


REQUIRED_REVIEW_FLAGS = [
    "same_12_panel_template",
    "panel_sizes_match_source",
    "shot_order_matches_source",
    "shot_labels_preserved",
    "no_recomposed_storyboard",
    "no_squashed_subjects",
    "api_edit_effect_matches_job002",
]


def load_json(path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def rel_or_abs(root, path):
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def resolve_path(root, raw):
    path = Path(raw)
    if path.is_absolute():
        return path
    return root / path


def part_number(key):
    digits = "".join(ch for ch in key if ch.isdigit())
    return int(digits or 0)


def discover_parts(root, job_id, explicit_manifest=None):
    manifest_path = resolve_path(root, explicit_manifest) if explicit_manifest else root / "output" / job_id / "visual-assets" / "approved_visual_manifest.json"
    parts = []
    if manifest_path.exists():
        manifest = load_json(manifest_path)
        for key, item in sorted((manifest.get("part_storyboards") or {}).items(), key=lambda kv: part_number(kv[0])):
            if not isinstance(item, dict):
                continue
            image = item.get("path")
            source = item.get("source_reference") or item.get("source_storyboard")
            if image and source:
                parts.append({
                    "part": key,
                    "path": resolve_path(root, image),
                    "source_reference": resolve_path(root, source),
                    "manifest": manifest_path,
                })
    return parts


def image_size(path):
    with Image.open(path) as img:
        return img.size


def fit_image(img, box):
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail(box, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", box, "white")
    x = (box[0] - img.width) // 2
    y = (box[1] - img.height) // 2
    canvas.paste(img, (x, y))
    return canvas


def make_compare_sheet(root, parts, output_path):
    panel_w = 520
    panel_h = 700
    label_h = 46
    gutter = 18
    margin = 18
    rows = []
    for item in parts:
        if not item["path"].exists() or not item["source_reference"].exists():
            continue
        src = fit_image(Image.open(item["source_reference"]), (panel_w, panel_h))
        cand = fit_image(Image.open(item["path"]), (panel_w, panel_h))
        rows.append((item, src, cand))

    if not rows:
        return

    width = margin * 2 + panel_w * 2 + gutter
    height = margin * 2 + len(rows) * (label_h + panel_h + gutter) - gutter
    sheet = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(sheet)

    y = margin
    for item, src, cand in rows:
        src_size = image_size(item["source_reference"])
        cand_size = image_size(item["path"])
        labels = [
            f"{item['part']} source | {rel_or_abs(root, item['source_reference'])} | {src_size[0]}x{src_size[1]}",
            f"{item['part']} candidate | {rel_or_abs(root, item['path'])} | {cand_size[0]}x{cand_size[1]}",
        ]
        for col, label in enumerate(labels):
            x = margin + col * (panel_w + gutter)
            draw.rectangle([x, y, x + panel_w, y + label_h - 8], fill=(245, 245, 245))
            draw.text((x + 10, y + 12), label, fill=(20, 20, 20))
        sheet.paste(src, (margin, y + label_h))
        sheet.paste(cand, (margin + panel_w + gutter, y + label_h))
        draw.rectangle([margin, y + label_h, margin + panel_w, y + label_h + panel_h], outline=(210, 210, 210))
        draw.rectangle([margin + panel_w + gutter, y + label_h, margin + panel_w * 2 + gutter, y + label_h + panel_h], outline=(210, 210, 210))
        y += label_h + panel_h + gutter

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, "JPEG", quality=92)


def review_template(job_id, parts, compare_path):
    return {
        "job_id": job_id,
        "reviewer": "",
        "source": str(compare_path),
        "same_12_panel_template": None,
        "panel_sizes_match_source": None,
        "shot_order_matches_source": None,
        "shot_labels_preserved": None,
        "no_recomposed_storyboard": None,
        "no_squashed_subjects": None,
        "api_edit_effect_matches_job002": None,
        "notes": "",
        "failed_item": "",
        "retry_variable": "storyboard_geometry",
        "inspected_parts": [item["part"] for item in parts],
    }


def evaluate_review(review):
    missing = []
    failed = []
    for key in REQUIRED_REVIEW_FLAGS:
        value = review.get(key)
        if value is None:
            missing.append(key)
        elif value is not True:
            failed.append(key)
    if missing:
        return "STOP", missing, failed
    if failed:
        return "FAIL", missing, failed
    return "PASS", missing, failed


def report_overall(checks, review_overall):
    order = {"PASS": 0, "FAIL": 1, "STOP": 2}
    worst = max([order.get(check["status"], 2) for check in checks] + [order.get(review_overall, 2)])
    for status, rank in order.items():
        if rank == worst:
            return status
    return "STOP"


def write_markdown(path, report):
    lines = [
        "# Storyboard Geometry QC",
        "",
        f"- Job: `{report['job_id']}`",
        f"- Stage: `{report['stage']}`",
        f"- Overall: `{report['overall']}`",
        f"- Compare image: `{report['compare_image']}`",
        f"- Review file: `{report['review_file']}`",
        "",
        "## Part Geometry",
    ]
    for item in report["parts"]:
        lines.extend([
            f"- `{item['part']}`",
            f"  - source: `{item['source_reference']}` `{item.get('source_size')}`",
            f"  - candidate: `{item['path']}` `{item.get('candidate_size')}`",
            f"  - width scale: `{item.get('width_scale')}`",
            f"  - height scale: `{item.get('height_scale')}`",
            f"  - max dimension drift: `{item.get('max_dimension_drift_ratio')}`",
            f"  - aspect ratio drift: `{item.get('aspect_ratio_drift')}`",
            f"  - squash delta: `{item.get('squash_delta')}`",
        ])
    lines.extend(["", "## Checks"])
    for check in report["checks"]:
        lines.append(f"- {check['status']}: `{check['name']}` - {check['detail']}")
    lines.extend(["", "## Review Flags"])
    review = report.get("review") or {}
    for key in REQUIRED_REVIEW_FLAGS:
        lines.append(f"- `{key}`: `{review.get(key)}`")
    if report.get("failed_flags"):
        lines.extend(["", f"Failed flags: `{', '.join(report['failed_flags'])}`"])
    if report.get("missing_flags"):
        lines.extend(["", f"Missing flags: `{', '.join(report['missing_flags'])}`"])
    notes = review.get("notes", "")
    if notes:
        lines.extend(["", "## Notes", "", notes])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def add(checks, name, status, detail):
    checks.append({"name": name, "status": status, "detail": detail})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--stage", default="image_batch_qc")
    parser.add_argument("--review")
    parser.add_argument("--manifest")
    parser.add_argument("--out-json")
    parser.add_argument("--out-md")
    parser.add_argument("--compare-out")
    parser.add_argument("--max-dimension-drift-ratio", type=float, default=0.015)
    parser.add_argument("--max-aspect-ratio-drift", type=float, default=0.015)
    parser.add_argument("--max-squash-delta", type=float, default=0.01)
    parser.add_argument("--write-review-template", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    checks_dir = root / "output" / args.job_id / "checks"
    review_path = Path(args.review) if args.review else checks_dir / "storyboard_geometry_review.json"
    out_json = Path(args.out_json) if args.out_json else checks_dir / f"{args.stage}_storyboard_geometry_qc.json"
    out_md = Path(args.out_md) if args.out_md else checks_dir / f"{args.stage}_storyboard_geometry_qc.md"
    compare_path = Path(args.compare_out) if args.compare_out else checks_dir / "storyboard_geometry_compare.jpg"
    if not review_path.is_absolute():
        review_path = root / review_path
    if not out_json.is_absolute():
        out_json = root / out_json
    if not out_md.is_absolute():
        out_md = root / out_md
    if not compare_path.is_absolute():
        compare_path = root / compare_path

    parts = discover_parts(root, args.job_id, args.manifest)
    make_compare_sheet(root, parts, compare_path)
    if args.write_review_template or not review_path.exists():
        write_json(review_path, review_template(args.job_id, parts, compare_path))

    checks = []
    report_parts = []
    if not parts:
        add(checks, "parts_discovered", "STOP", "no manifest part storyboards with source_reference")
    else:
        add(checks, "parts_discovered", "PASS", f"count={len(parts)}")

    for item in parts:
        src = item["source_reference"]
        cand = item["path"]
        part_report = {
            "part": item["part"],
            "source_reference": rel_or_abs(root, src),
            "path": rel_or_abs(root, cand),
            "source_exists": src.exists(),
            "candidate_exists": cand.exists(),
            "source_sha256": sha256_file(src) if src.exists() else None,
            "candidate_sha256": sha256_file(cand) if cand.exists() else None,
        }
        if not src.exists() or not cand.exists():
            add(checks, f"{item['part']}_files_exist", "STOP", f"source={src.exists()} candidate={cand.exists()}")
            report_parts.append(part_report)
            continue
        sw, sh = image_size(src)
        cw, ch = image_size(cand)
        width_scale = cw / sw
        height_scale = ch / sh
        source_ratio = sw / sh
        candidate_ratio = cw / ch
        max_drift = max(abs(width_scale - 1.0), abs(height_scale - 1.0))
        aspect_ratio_drift = abs(candidate_ratio - source_ratio) / source_ratio
        squash_delta = abs(width_scale - height_scale)
        part_report.update({
            "source_size": f"{sw}x{sh}",
            "candidate_size": f"{cw}x{ch}",
            "width_scale": round(width_scale, 6),
            "height_scale": round(height_scale, 6),
            "source_aspect_ratio": round(source_ratio, 6),
            "candidate_aspect_ratio": round(candidate_ratio, 6),
            "max_dimension_drift_ratio": round(max_drift, 6),
            "aspect_ratio_drift": round(aspect_ratio_drift, 6),
            "squash_delta": round(squash_delta, 6),
        })
        add(
            checks,
            f"{item['part']}_canvas_aspect_matches_source_edit_baseline",
            "PASS" if aspect_ratio_drift <= args.max_aspect_ratio_drift else "FAIL",
            f"source={sw}x{sh} candidate={cw}x{ch} aspect_drift={aspect_ratio_drift:.4f} limit={args.max_aspect_ratio_drift:.4f}",
        )
        add(
            checks,
            f"{item['part']}_uniform_output_scale_allowed",
            "PASS",
            f"source={sw}x{sh} candidate={cw}x{ch} max_dimension_drift={max_drift:.4f}; exact pixel-size matching is not required for GPT Image outputs",
        )
        add(
            checks,
            f"{item['part']}_no_anisotropic_squash",
            "PASS" if squash_delta <= args.max_squash_delta else "FAIL",
            f"width_scale={width_scale:.4f} height_scale={height_scale:.4f} delta={squash_delta:.4f} limit={args.max_squash_delta:.4f}",
        )
        report_parts.append(part_report)

    review = load_json(review_path) if review_path.exists() else {}
    review_overall, missing_flags, failed_flags = evaluate_review(review)
    overall = report_overall(checks, review_overall)
    report = {
        "job_id": args.job_id,
        "stage": args.stage,
        "overall": overall,
        "compare_image": rel_or_abs(root, compare_path),
        "review_file": rel_or_abs(root, review_path),
        "parts": report_parts,
        "checks": checks,
        "review": review,
        "missing_flags": missing_flags,
        "failed_flags": failed_flags,
    }
    attach_input_binding(
        report,
        root,
        [
            review_path,
            *[
                path
                for item in parts
                for path in (item.get("source_reference"), item.get("path"))
                if path
            ],
        ],
    )
    write_json(out_json, report)
    write_markdown(out_md, report)
    print(json.dumps({"overall": overall, "qc": rel_or_abs(root, out_json), "compare": rel_or_abs(root, compare_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
