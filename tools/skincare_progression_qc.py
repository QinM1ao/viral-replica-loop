#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path

from qc_input_binding import attach_input_binding

from PIL import Image, ImageDraw, ImageOps


REQUIRED_REVIEW_FLAGS = [
    "pre_wash_has_visible_problem",
    "pre_wash_not_afterwash_bright",
    "afterwash_only_after_cleaning",
    "post_wash_visibly_improved",
    "improvement_not_lighting_only",
    "real_skin_texture_preserved",
    "effect_progression_reads_correctly",
]


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def discover_part_images(root, job_id, explicit_manifest=None):
    manifest_path = resolve_path(root, explicit_manifest) if explicit_manifest else root / "output" / job_id / "visual-assets" / "approved_visual_manifest.json"
    parts = []
    afterwash_ref = None
    if manifest_path.exists():
        manifest = load_json(manifest_path)
        reusable_refs = manifest.get("reusable_refs") or {}
        if reusable_refs.get("afterwash_face"):
            afterwash_ref = resolve_path(root, reusable_refs["afterwash_face"])
        storyboards = manifest.get("part_storyboards") or {}
        for key, item in sorted(storyboards.items(), key=lambda kv: part_number(kv[0])):
            raw = item.get("path") if isinstance(item, dict) else None
            if raw:
                parts.append({"part": key, "path": resolve_path(root, raw), "source": manifest_path})

    if not parts:
        final_dir = root / "output" / job_id / "final-images"
        for path in sorted(final_dir.glob("part*_seedance_ref.*")):
            parts.append({"part": path.stem.split("_", 1)[0], "path": path, "source": final_dir})

    return parts, afterwash_ref


def fit_image(img, box):
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail(box, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", box, "white")
    x = (box[0] - img.width) // 2
    y = (box[1] - img.height) // 2
    canvas.paste(img, (x, y))
    return canvas


def make_compare_sheet(root, parts, afterwash_ref, output_path):
    max_panel_w = 620
    max_panel_h = 680
    label_h = 44
    gutter = 18
    margin = 18
    items = [(item["part"], item["path"]) for item in parts]
    if afterwash_ref and afterwash_ref.exists():
        items.append(("afterwash_ref", afterwash_ref))

    images = []
    for label, path in items:
        img = Image.open(path)
        images.append((label, path, fit_image(img, (max_panel_w, max_panel_h))))

    width = margin * 2 + len(images) * max_panel_w + max(0, len(images) - 1) * gutter
    height = margin * 2 + label_h + max_panel_h
    sheet = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(sheet)

    x = margin
    for label, path, img in images:
        draw.rectangle([x, margin, x + max_panel_w, margin + label_h - 8], fill=(245, 245, 245))
        draw.text((x + 10, margin + 12), f"{label} | {rel_or_abs(root, path)}", fill=(20, 20, 20))
        sheet.paste(img, (x, margin + label_h))
        draw.rectangle([x, margin + label_h, x + max_panel_w, margin + label_h + max_panel_h], outline=(210, 210, 210))
        x += max_panel_w + gutter

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, "JPEG", quality=92)


def review_template(job_id, parts, compare_path):
    return {
        "job_id": job_id,
        "reviewer": "",
        "source": str(compare_path),
        "pre_wash_has_visible_problem": None,
        "pre_wash_not_afterwash_bright": None,
        "afterwash_only_after_cleaning": None,
        "post_wash_visibly_improved": None,
        "improvement_not_lighting_only": None,
        "real_skin_texture_preserved": None,
        "effect_progression_reads_correctly": None,
        "notes": "",
        "failed_item": "",
        "retry_variable": "skin_progression",
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


def write_markdown(path, report):
    lines = [
        "# Skincare Progression QC",
        "",
        f"- Job: `{report['job_id']}`",
        f"- Stage: `{report['stage']}`",
        f"- Overall: `{report['overall']}`",
        f"- Compare image: `{report['compare_image']}`",
        f"- Review file: `{report['review_file']}`",
        "",
        "## Parts",
    ]
    for item in report["parts"]:
        lines.append(f"- `{item['part']}`: `{item['path']}`")
    if report.get("afterwash_ref"):
        lines.append(f"- `afterwash_ref`: `{report['afterwash_ref']}`")
    lines.extend(["", "## Review Flags"])
    for key in REQUIRED_REVIEW_FLAGS:
        lines.append(f"- `{key}`: `{report['review'].get(key) if report.get('review') else None}`")
    if report.get("failed_flags"):
        lines.extend(["", f"Failed flags: `{', '.join(report['failed_flags'])}`"])
    if report.get("missing_flags"):
        lines.extend(["", f"Missing flags: `{', '.join(report['missing_flags'])}`"])
    notes = (report.get("review") or {}).get("notes", "")
    if notes:
        lines.extend(["", "## Notes", "", notes])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
    parser.add_argument("--write-review-template", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    checks_dir = root / "output" / args.job_id / "checks"
    review_path = Path(args.review) if args.review else checks_dir / "skincare_progression_review.json"
    if not review_path.is_absolute():
        review_path = root / review_path
    out_json = Path(args.out_json) if args.out_json else checks_dir / f"{args.stage}_skincare_progression_qc.json"
    out_md = Path(args.out_md) if args.out_md else checks_dir / f"{args.stage}_skincare_progression_qc.md"
    compare_path = Path(args.compare_out) if args.compare_out else checks_dir / "skincare_progression_compare.jpg"
    if not out_json.is_absolute():
        out_json = root / out_json
    if not out_md.is_absolute():
        out_md = root / out_md
    if not compare_path.is_absolute():
        compare_path = root / compare_path

    parts, afterwash_ref = discover_part_images(root, args.job_id, args.manifest)
    existing_parts = [item for item in parts if item["path"].exists()]
    report_parts = [
        {
            "part": item["part"],
            "path": rel_or_abs(root, item["path"]),
            "exists": item["path"].exists(),
            "sha256": sha256_file(item["path"]) if item["path"].exists() else None,
        }
        for item in parts
    ]

    overall = "PASS"
    missing_flags = []
    failed_flags = []
    review = None
    errors = []

    if not existing_parts:
        overall = "STOP"
        errors.append("need at least one existing Part storyboard image for skincare progression QC")
    else:
        make_compare_sheet(root, existing_parts, afterwash_ref, compare_path)

    if args.write_review_template and not review_path.exists():
        write_json(review_path, review_template(args.job_id, existing_parts, rel_or_abs(root, compare_path)))

    if not review_path.exists():
        overall = "STOP"
        errors.append("missing skincare progression review json")
    else:
        review = load_json(review_path)
        review_overall, missing_flags, failed_flags = evaluate_review(review)
        if review_overall != "PASS":
            overall = review_overall

    report = {
        "overall": overall,
        "job_id": args.job_id,
        "stage": args.stage,
        "parts": report_parts,
        "afterwash_ref": rel_or_abs(root, afterwash_ref) if afterwash_ref else None,
        "compare_image": rel_or_abs(root, compare_path),
        "review_file": rel_or_abs(root, review_path),
        "required_review_flags": REQUIRED_REVIEW_FLAGS,
        "missing_flags": missing_flags,
        "failed_flags": failed_flags,
        "errors": errors,
        "review": review,
    }
    attach_input_binding(
        report,
        root,
        [
            review_path,
            afterwash_ref,
            *[item.get("path") for item in parts if item.get("path")],
        ],
    )

    write_json(out_json, report)
    write_markdown(out_md, report)
    print(json.dumps({"overall": overall, "qc": rel_or_abs(root, out_json), "compare": rel_or_abs(root, compare_path)}, ensure_ascii=False))
    raise SystemExit(0 if overall == "PASS" else 1)


if __name__ == "__main__":
    main()
