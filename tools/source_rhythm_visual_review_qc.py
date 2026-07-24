#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_path(root, raw):
    path = Path(str(raw or "")).expanduser()
    return path if path.is_absolute() else root / path


def rel_or_abs(root, path):
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def review_report(root, source_rhythm_path, review_path):
    rhythm = load_json(source_rhythm_path)
    review = load_json(review_path)
    required_beats = [
        beat for beat in rhythm.get("beats") or [] if str(beat.get("id") or "")
    ]
    required_by_id = {
        str(beat.get("id") or ""): beat
        for beat in required_beats
        if str(beat.get("id") or "")
    }
    review_items = review.get("beats") if isinstance(review.get("beats"), list) else []
    review_by_id = {}
    duplicate_beat_ids = []
    for item in review_items:
        beat_id = str(item.get("beat_id") or "") if isinstance(item, dict) else ""
        if not beat_id:
            continue
        if beat_id in review_by_id:
            duplicate_beat_ids.append(beat_id)
        review_by_id[beat_id] = item

    missing_beat_ids = [beat_id for beat_id in required_by_id if beat_id not in review_by_id]
    unknown_beat_ids = [beat_id for beat_id in review_by_id if beat_id not in required_by_id]
    checks = []
    schema_version = int(rhythm.get("schema_version") or 0)
    has_stop = bool(
        schema_version < 3
        or missing_beat_ids
        or duplicate_beat_ids
        or unknown_beat_ids
    )
    has_fail = False

    for beat_id, beat in required_by_id.items():
        item = review_by_id.get(beat_id)
        if not item:
            continue
        evidence_refs = {str(value) for value in beat.get("evidence_frame_refs") or []}
        reviewed_refs = [str(value) for value in item.get("reviewed_frame_refs") or []]
        missing_files = [
            value for value in reviewed_refs if not resolve_path(root, value).is_file()
        ]
        outside_beat_refs = [value for value in reviewed_refs if value not in evidence_refs]
        item_stop_reasons = []
        item_fail_reasons = []
        if not reviewed_refs:
            item_stop_reasons.append("missing_reviewed_frame_refs")
        if missing_files:
            item_stop_reasons.append("reviewed_frame_missing")
        if outside_beat_refs:
            item_stop_reasons.append("reviewed_frame_not_cited_by_beat")
        if not str(item.get("notes") or "").strip():
            item_stop_reasons.append("missing_notes")
        if item.get("description_matches_evidence") is not True:
            item_fail_reasons.append("description_does_not_match_evidence")
        if item.get("action_type_matches_evidence") is not True:
            item_fail_reasons.append("action_type_does_not_match_evidence")
        declared_product_names = beat.get("spoken_product_names") or []
        confirmed_product_names = item.get("confirmed_spoken_product_names")
        if declared_product_names:
            if item.get("spoken_product_names_are_product_entities") is not True:
                item_fail_reasons.append(
                    "spoken_product_names_not_confirmed_as_product_entities"
                )
            if not isinstance(confirmed_product_names, list) or {
                str(value).strip().casefold() for value in confirmed_product_names
            } != {
                str(value).strip().casefold() for value in declared_product_names
            }:
                item_fail_reasons.append(
                    "confirmed_spoken_product_names_do_not_match_source_rhythm"
                )

        action_evidence = beat.get("action_evidence")
        if isinstance(action_evidence, dict):
            action_refs = {
                str(action_evidence.get(field) or "")
                for field in (
                    "before_frame_ref",
                    "peak_frame_ref",
                    "after_frame_ref",
                )
            }
            action_refs.discard("")
            missing_action_refs = sorted(action_refs.difference(reviewed_refs))
            if missing_action_refs:
                item_stop_reasons.append("physical_action_frames_not_reviewed")
            if item.get("physical_action_matches") is not True:
                item_fail_reasons.append("physical_action_does_not_match")

        has_stop = has_stop or bool(item_stop_reasons)
        has_fail = has_fail or bool(item_fail_reasons)
        checks.append(
            {
                "beat_id": beat_id,
                "status": "STOP" if item_stop_reasons else "FAIL" if item_fail_reasons else "PASS",
                "reviewed_frame_refs": reviewed_refs,
                "missing_files": missing_files,
                "outside_beat_refs": outside_beat_refs,
                "declared_spoken_product_names": declared_product_names,
                "confirmed_spoken_product_names": confirmed_product_names,
                "spoken_product_names_are_product_entities": item.get(
                    "spoken_product_names_are_product_entities"
                ),
                "stop_reasons": item_stop_reasons,
                "fail_reasons": item_fail_reasons,
            }
        )

    overall = "STOP" if has_stop else "FAIL" if has_fail else "PASS"
    return {
        "overall": overall,
        "schema_version": schema_version,
        "source_rhythm": rel_or_abs(root, source_rhythm_path),
        "source_rhythm_sha256": file_sha256(source_rhythm_path),
        "review_file": rel_or_abs(root, review_path),
        "required_beat_ids": list(required_by_id),
        "reviewed_beat_ids": [beat_id for beat_id in required_by_id if beat_id in review_by_id],
        "missing_beat_ids": missing_beat_ids,
        "duplicate_beat_ids": sorted(set(duplicate_beat_ids)),
        "unknown_beat_ids": unknown_beat_ids,
        "checks": checks,
    }


def write_markdown(path, report):
    lines = [
        "# Source Rhythm Visual Review QC",
        "",
        f"- Overall: `{report['overall']}`",
        f"- Source rhythm: `{report['source_rhythm']}`",
        f"- Review: `{report['review_file']}`",
        f"- Missing beats: `{', '.join(report['missing_beat_ids'])}`",
        "",
        "## Per-beat checks",
        "",
    ]
    for check in report["checks"]:
        reasons = check["stop_reasons"] + check["fail_reasons"]
        lines.append(
            f"- {check['status']}: `{check['beat_id']}`"
            + (f" - {', '.join(reasons)}" if reasons else "")
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(
        description="Require the source-blueprint checker to visually review every required source beat."
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--source-rhythm", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    source_rhythm_path = resolve_path(root, args.source_rhythm)
    review_path = resolve_path(root, args.review)
    out_json = resolve_path(root, args.out_json)
    out_md = resolve_path(root, args.out_md) if args.out_md else None
    report = review_report(root, source_rhythm_path, review_path)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if out_md:
        write_markdown(out_md, report)
    print(report["overall"])
    raise SystemExit(0 if report["overall"] == "PASS" else 1)


if __name__ == "__main__":
    main()
