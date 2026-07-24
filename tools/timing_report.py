#!/usr/bin/env python3
import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


IMAGE_STAGES = {"image_sample", "image_sample_review", "image_batch_qc"}
DOWNSTREAM_STAGES = {"voiceover", "seam", "seedance_prompt", "audio_boundary_qc", "request_qc"}
NON_IMAGE_PRE_SEEDANCE_STAGES = {
    "source_blueprint",
    "story_analysis",
    "storyboard",
    "voiceover",
    "seam",
    "seedance_prompt",
    "audio_boundary_qc",
    "request_qc",
    "pre_seedance_pack",
}


def parse_time(value):
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def format_duration(seconds):
    seconds = max(0, int(round(seconds or 0)))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)


def read_event_log(path):
    events = []
    if not path.exists():
        return events
    with path.open(encoding="utf-8") as f:
        for line_number, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                event = {"type": "malformed", "raw": line}
            event["_line"] = line_number
            event["_time"] = parse_time(event.get("time"))
            events.append(event)
    return events


def short_text(value, limit=110):
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "..."


def event_stage(event):
    return event.get("stage") or event.get("next_stage") or "(none)"


def event_job(event):
    return event.get("job") or "(none)"


def event_budget_key(event):
    job = event_job(event)
    run_id = str(event.get("workflow_run_id") or "").strip()
    return f"{job}@{run_id}" if run_id and run_id != job else job


def classify_categories(event):
    stage = event_stage(event)
    gate = str(event.get("gate") or "")
    failure_type = str(event.get("failure_type") or "")
    retry_variable = str(event.get("retry_variable") or "")
    note = str(event.get("note") or "")
    reason = str(event.get("reason") or "")
    blob = " ".join([stage, gate, failure_type, retry_variable, note, reason]).lower()
    is_non_pass = (
        event.get("decision") == "stop"
        or (event.get("type") == "gate_result" and event.get("result") != "PASS")
    )
    categories = []

    if stage in IMAGE_STAGES or "repair" in blob or "改图" in blob:
        categories.append("image-stage repair")
    if stage == "generation" or "seedance_generating" in blob or "download" in blob:
        categories.append("Seedance generation")
    if is_non_pass and (
        "524" in blob
        or "timeout" in blob
        or "provider" in blob
        or "gateway" in blob
        or "public-upload-not-configured" in blob
    ):
        categories.append("provider failure")
    if is_non_pass and (
        "evidence" in blob
        or "manifest" in blob
        or "contract" in blob
        or "hash" in blob
        or "missing" in blob
        or "unavailable" in blob
        or "cannot attach" in blob
        or "no candidate" in blob
        or "no saved" in blob
        or "unsaved" in blob
    ):
        categories.append("evidence failure")
    if is_non_pass and (
        "visual" in blob
        or "wardrobe" in blob
        or "clothing" in blob
        or "identity" in blob
        or "product" in blob
        or "mud" in blob
        or "yellow" in blob
        or "gray" in blob
        or "grey" in blob
        or "skin" in blob
        or "continuity" in blob
        or "geometry" in blob
        or "storyboard" in blob
        or "squeeze" in blob
        or "color" in blob
    ):
        categories.append("visual failure")
    if is_non_pass and (
        stage == "generation_approval"
        or "cost_approval" in gate
        or "paid" in blob
        or "generation requires explicit" in blob
        or "before generation" in blob
    ):
        categories.append("cost gate stop")
    if stage in DOWNSTREAM_STAGES or "revalidated" in blob or "reused" in blob:
        categories.append("downstream reuse/revalidation")
    if "qc" in stage or "qc" in blob or "gate" in gate:
        categories.append("QC")

    if not categories:
        categories.append("other")
    return list(dict.fromkeys(categories))


def empty_stage_summary(job, stage):
    return {
        "job": job,
        "stage": stage,
        "first": None,
        "last": None,
        "events": 0,
        "decisions": 0,
        "gate_results": Counter(),
        "result_elapsed": Counter(),
        "categories": Counter(),
    }


def summarize_events(events, selected_jobs=None):
    selected = set(selected_jobs or [])
    filtered = [e for e in events if not selected or event_job(e) in selected]
    filtered = sorted(filtered, key=lambda e: (e.get("_time") or datetime.min, e.get("_line", 0)))
    timed = [e for e in filtered if e.get("_time")]
    counts = Counter(e.get("type", "event") for e in filtered)
    first = timed[0]["_time"] if timed else None
    last = timed[-1]["_time"] if timed else None

    stage_summaries = {}
    last_decision_at = {}
    last_event_at = {}
    non_pass = []
    slow_areas = defaultdict(lambda: {"events": 0, "elapsed": 0, "examples": []})
    timeline_by_job = defaultdict(list)
    non_image_pre_seedance = Counter()

    for event in filtered:
        job = event_job(event)
        stage = event_stage(event)
        key = (job, stage)
        summary = stage_summaries.setdefault(key, empty_stage_summary(job, stage))
        event_time = event.get("_time")
        if event_time:
            summary["first"] = summary["first"] or event_time
            summary["last"] = event_time
        summary["events"] += 1

        previous_job_event = timeline_by_job[job][-1] if timeline_by_job[job] else None
        if event_time and previous_job_event and previous_job_event.get("_time"):
            event["_job_elapsed"] = (event_time - previous_job_event["_time"]).total_seconds()
        else:
            event["_job_elapsed"] = 0
        timeline_by_job[job].append(event)

        event_type = event.get("type")
        if event_type == "decision":
            summary["decisions"] += 1
            if event_time and event.get("decision") == "continue":
                last_decision_at[key] = event_time
            if event.get("decision") == "stop":
                categories = classify_categories(event)
                non_pass.append({"event": event, "result": "STOP_DECISION", "categories": categories})
                for category in categories:
                    add_slow_area(slow_areas, category, event, 0)
        elif event_type == "gate_result":
            result = event.get("result") or "(none)"
            summary["gate_results"][result] += 1
            explicit_duration = event.get("duration_seconds")
            elapsed = max(0, float(explicit_duration)) if explicit_duration is not None else 0
            if explicit_duration is None and event_time:
                start = last_decision_at.pop(key, None) or last_event_at.get(key)
                if start:
                    elapsed = max(0, (event_time - start).total_seconds())
            event["_gate_elapsed"] = elapsed
            summary["result_elapsed"][result] += elapsed
            categories = classify_categories(event)
            for category in categories:
                summary["categories"][category] += 1
                add_slow_area(slow_areas, category, event, elapsed)
            if stage in NON_IMAGE_PRE_SEEDANCE_STAGES:
                non_image_pre_seedance[event_budget_key(event)] += elapsed
            if result != "PASS":
                non_pass.append({"event": event, "result": result, "categories": categories})

        if event_time:
            last_event_at[key] = event_time

    return {
        "events": filtered,
        "first": first,
        "last": last,
        "span": (last - first).total_seconds() if first and last else 0,
        "counts": counts,
        "stage_summaries": sorted(stage_summaries.values(), key=stage_sort_key),
        "non_pass": non_pass,
        "slow_areas": slow_areas,
        "timeline_by_job": timeline_by_job,
        "non_image_pre_seedance": non_image_pre_seedance,
    }


def stage_sort_key(summary):
    return (summary["job"], summary["first"] or datetime.min, summary["stage"])


def add_slow_area(slow_areas, category, event, elapsed):
    area = slow_areas[category]
    area["events"] += 1
    area["elapsed"] += elapsed
    if len(area["examples"]) < 3:
        area["examples"].append(event)


def count_text(counter):
    if not counter:
        return "-"
    return ", ".join(f"{key}:{counter[key]}" for key in sorted(counter))


def elapsed_text(counter):
    if not counter:
        return "-"
    return ", ".join(f"{key}:{format_duration(counter[key])}" for key in sorted(counter))


def render_report(summary, log_path, selected_jobs=None, timeline_limit=12, non_image_budget_seconds=1200):
    selected_jobs = selected_jobs or []
    first = summary["first"].isoformat() if summary["first"] else "n/a"
    last = summary["last"].isoformat() if summary["last"] else "n/a"
    lines = [
        "# Loop Timing Report",
        "",
        f"Generated from `{log_path}`.",
        "",
        "## Event Window",
        "",
        f"- First event: `{first}`",
        f"- Last event: `{last}`",
        f"- Total elapsed span: **{format_duration(summary['span'])}**",
        f"- Event counts: {count_text(summary['counts'])}",
        "",
        "## Gate Results By Job And Stage",
        "",
        "| Job | Stage | First | Last | Span | Events | Decisions | Gate results | Result elapsed | Slow labels |",
        "|---|---|---|---|---:|---:|---:|---|---|---|",
    ]

    if summary["stage_summaries"]:
        for item in summary["stage_summaries"]:
            first_text = item["first"].isoformat(timespec="seconds") if item["first"] else "n/a"
            last_text = item["last"].isoformat(timespec="seconds") if item["last"] else "n/a"
            span = (item["last"] - item["first"]).total_seconds() if item["first"] and item["last"] else 0
            labels = ", ".join(category for category, _ in item["categories"].most_common(4)) or "-"
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"`{item['job']}`",
                        f"`{item['stage']}`",
                        f"`{first_text}`",
                        f"`{last_text}`",
                        format_duration(span),
                        str(item["events"]),
                        str(item["decisions"]),
                        count_text(item["gate_results"]),
                        elapsed_text(item["result_elapsed"]),
                        labels,
                    ]
                )
                + " |"
            )
    else:
        lines.append("| - | - | - | - | 0s | 0 | 0 | - | - | - |")

    lines.extend(["", "## Non-PASS Events", ""])
    if summary["non_pass"]:
        lines.extend(
            [
                "| Time | Job | Stage | Result | Failure type | Retry variable | Area | Note |",
                "|---|---|---|---|---|---|---|---|",
            ]
        )
        for item in summary["non_pass"]:
            event = item["event"]
            time_text = event["_time"].isoformat(timespec="seconds") if event.get("_time") else "n/a"
            note = event.get("note") or event.get("reason") or ""
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"`{time_text}`",
                        f"`{event_job(event)}`",
                        f"`{event_stage(event)}`",
                        f"**{item['result']}**",
                        f"`{event.get('failure_type') or '-'}`",
                        f"`{event.get('retry_variable') or '-'}`",
                        ", ".join(item["categories"]),
                        short_text(note),
                    ]
                )
                + " |"
            )
    else:
        lines.append("- No non-PASS gate results or stop decisions in this event window.")

    lines.extend(["", "## Likely Slow Areas", ""])
    slow_rows = sorted(
        summary["slow_areas"].items(),
        key=lambda item: (item[1]["elapsed"], item[1]["events"]),
        reverse=True,
    )
    if slow_rows:
        lines.extend(["| Area | Events | Attributed elapsed | Recent evidence |", "|---|---:|---:|---|"])
        for category, data in slow_rows:
            examples = "; ".join(example_text(event) for event in data["examples"])
            lines.append(f"| {category} | {data['events']} | {format_duration(data['elapsed'])} | {examples} |")
    else:
        lines.append("- No slow-area signals found.")

    lines.extend(["", "## Non-Image Pre-Seedance Budget", ""])
    budget_rows = summary.get("non_image_pre_seedance", {})
    if budget_rows:
        lines.extend(["| Job | Measured time | Budget | Result |", "|---|---:|---:|---|"])
        for job, elapsed in sorted(budget_rows.items()):
            result = "PASS" if elapsed <= non_image_budget_seconds else "OVER"
            lines.append(
                f"| `{job}` | {format_duration(elapsed)} | {format_duration(non_image_budget_seconds)} | **{result}** |"
            )
    else:
        lines.append("- No measured non-image pre-Seedance gate time.")

    lines.extend(["", "## Focused Timelines", ""])
    if selected_jobs:
        for job in selected_jobs:
            lines.extend([f"### `{job}`", ""])
            events = summary["timeline_by_job"].get(job, [])[-timeline_limit:]
            if events:
                for event in events:
                    time_text = event["_time"].isoformat(timespec="seconds") if event.get("_time") else "n/a"
                    elapsed = format_duration(event.get("_job_elapsed", 0))
                    status = event.get("result") or event.get("decision") or event.get("type", "event")
                    detail = event.get("note") or event.get("reason") or event.get("artifact") or ""
                    lines.append(
                        f"- `{time_text}` (+{elapsed}) `{event_stage(event)}` {event.get('type', 'event')} **{status}**"
                        + (f" - {short_text(detail)}" if detail else "")
                    )
            else:
                lines.append("- No events for this job in the selected event window.")
            lines.append("")
    else:
        lines.append("Pass `--job <job-id>` to include recent per-job timelines.")

    return "\n".join(lines).rstrip() + "\n"


def example_text(event):
    time_text = event["_time"].isoformat(timespec="seconds") if event.get("_time") else "n/a"
    result = event.get("result") or event.get("decision") or event.get("type", "event")
    note = short_text(event.get("note") or event.get("reason") or "", 70)
    return f"`{time_text}` `{event_job(event)}` `{event_stage(event)}` {result}" + (f" ({note})" if note else "")


def parse_jobs(values):
    jobs = []
    for value in values or []:
        jobs.extend(part.strip() for part in value.split(",") if part.strip())
    return list(dict.fromkeys(jobs))


def load_non_image_budget(root, explicit_seconds=0):
    if explicit_seconds:
        return explicit_seconds
    path = root / "rules" / "PERFORMANCE_BUDGET.json"
    if path.exists():
        try:
            value = int(json.loads(path.read_text(encoding="utf-8")).get("non_image_pre_seedance_seconds", 1200))
            if value > 0:
                return value
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    return 1200


def main():
    parser = argparse.ArgumentParser(description="Generate a Markdown timing report from loop event logs.")
    parser.add_argument("--root", default=".", help="Loop kit root.")
    parser.add_argument("--log", default="", help="Event log path. Defaults to <root>/logs/loop_events.jsonl.")
    parser.add_argument("--out", default="", help="Write Markdown to this path. Defaults to stdout.")
    parser.add_argument("--job", action="append", default=[], help="Focused job timeline. Can be repeated or comma-separated.")
    parser.add_argument("--timeline-limit", type=int, default=12, help="Recent events per focused job.")
    parser.add_argument("--non-image-budget-seconds", type=int, default=0, help="Override the configured budget for non-image work through the Pre-Seedance handoff.")
    parser.add_argument("--fail-on-budget", action="store_true", help="Exit non-zero when any selected workflow run exceeds the non-image budget.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    log_path = Path(args.log).resolve() if args.log else root / "logs" / "loop_events.jsonl"
    selected_jobs = parse_jobs(args.job)
    non_image_budget_seconds = load_non_image_budget(root, args.non_image_budget_seconds)
    events = read_event_log(log_path)
    summary = summarize_events(events, selected_jobs=selected_jobs or None)
    report = render_report(
        summary,
        log_path,
        selected_jobs=selected_jobs,
        timeline_limit=args.timeline_limit,
        non_image_budget_seconds=non_image_budget_seconds,
    )

    if args.out:
        out = Path(args.out).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        print(out)
    else:
        print(report, end="")
    if args.fail_on_budget and any(
        elapsed > non_image_budget_seconds
        for elapsed in summary.get("non_image_pre_seedance", {}).values()
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
