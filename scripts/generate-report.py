#!/usr/bin/env python3
import argparse
import csv
import json
from pathlib import Path


def read_text(path):
    return path.read_text(encoding="utf-8") if path.exists() else ""


def read_jobs(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_events(path, limit=20):
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            events.append({"raw": line})
    return events[-limit:]


def main():
    parser = argparse.ArgumentParser(description="Generate a simple loop report.")
    parser.add_argument("--root", default=".", help="Loop kit root.")
    parser.add_argument("--out", default="", help="Output markdown path.")
    parser.add_argument("--last-decision", default="", help="Optional runner decision markdown to include instead of RUNNER_LAST_DECISION.md.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out = Path(args.out).resolve() if args.out else root / "output" / "loop-report.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    jobs = read_jobs(root / "jobs.csv")
    events = read_events(root / "logs" / "loop_events.jsonl")

    lines = [
        "# Viral Replica Loop Report",
        "",
        "## Jobs",
        "",
    ]
    if jobs:
        for job in jobs:
            lines.append(f"- `{job.get('id', '')}`: status `{job.get('status', '')}`, next `{job.get('next_stage', '')}`")
    else:
        lines.append("- No jobs in `jobs.csv`.")

    lines.extend(["", "## Last Decision", ""])
    last_decision_path = Path(args.last_decision).resolve() if args.last_decision else root / "RUNNER_LAST_DECISION.md"
    last_decision = read_text(last_decision_path).strip()
    lines.append(last_decision if last_decision else "No runner decision yet.")

    lines.extend(["", "## Recent Events", ""])
    if events:
        for event in events:
            lines.append(f"- `{event.get('time', '')}` {event.get('type', 'event')}: {event.get('job', '')} {event.get('decision', event.get('result', ''))} {event.get('reason', '')}")
    else:
        lines.append("- No events yet.")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
