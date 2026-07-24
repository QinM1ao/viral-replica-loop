#!/usr/bin/env python3
"""Collect loop evidence and draft a SkillOps improvement proposal."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path


SIGNAL_RULES = [
    ("cross_part_continuity", "gate_gap", ["cross-Part", "cross_part", "衣服不连续", "continuity"]),
    ("skincare_progression", "gate_gap", ["skincare", "progression", "洗后", "after-wash", "太白", "too white"]),
    ("storyboard_geometry", "gate_gap", ["storyboard geometry", "geometry", "squeez", "压扁", "重排"]),
    ("codex_imagegen_contract", "checker_contract", ["codex_imagegen_contract", "API-equivalence", "reference order", "wrong refs", "旧工具"]),
    ("prompt_pollution", "prompt_quality", ["workflow context", "AI改好分镜图", "current-job", "工程化", "Part1最终"]),
    ("handoff_clutter", "handoff_governance", ["deprecated", "废稿", "clutter", "final upload"]),
    ("approval_scope", "approval_safety", ["approval", "paid", "generation_approved", "batch", "retry"]),
    ("automation_drift", "automation_drift", ["parallel", "lane", "cron", "heartbeat", "no runnable"]),
]


def read_text(path: Path, limit: int = 200_000) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[:limit]


def read_jobs(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def read_jsonl_tail(path: Path, limit: int) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    events = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def collect_text_blobs(root: Path, event_limit: int) -> list[tuple[str, str]]:
    blobs: list[tuple[str, str]] = []
    for rel in [
        "STATE.md",
        "RUNNER_STATE.json",
        "logs/review_feedback.jsonl",
        "client-profiles/kongfengchun/lesson-registry.jsonl",
    ]:
        path = root / rel
        text = read_text(path)
        if text:
            blobs.append((rel, text))

    events = read_jsonl_tail(root / "logs" / "loop_events.jsonl", event_limit)
    if events:
        rendered = "\n".join(json.dumps(event, ensure_ascii=False) for event in events)
        blobs.append(("logs/loop_events.jsonl", rendered))
    return blobs


def read_review_feedback_tail(root: Path, limit: int) -> list[dict]:
    return read_jsonl_tail(root / "logs" / "review_feedback.jsonl", limit)


def classify_signals(blobs: list[tuple[str, str]]) -> list[dict[str, object]]:
    signals: list[dict[str, object]] = []
    for rel, text in blobs:
        lowered = text.lower()
        for signal, category, needles in SIGNAL_RULES:
            hits = [needle for needle in needles if needle.lower() in lowered]
            if hits:
                signals.append(
                    {
                        "signal": signal,
                        "classification": category,
                        "evidence_path": rel,
                        "matched_terms": hits[:5],
                    }
                )
    return signals


def signals_from_review_feedback(entries: list[dict]) -> list[dict[str, object]]:
    signals: list[dict[str, object]] = []
    for entry in entries:
        classification = entry.get("classification")
        if not classification:
            continue
        signals.append(
            {
                "signal": f"review_feedback:{entry.get('review_outcome', 'unknown')}",
                "classification": classification,
                "evidence_path": "logs/review_feedback.jsonl",
                "matched_terms": [
                    str(entry.get("job_id", "")),
                    str(entry.get("stage", "")),
                    str(entry.get("suggested_surface", "")),
                ],
            }
        )
    return signals


def summarize_jobs(jobs: list[dict[str, str]]) -> tuple[str, Counter]:
    status_counts = Counter(job.get("status", "") for job in jobs)
    lines = []
    for job in jobs:
        lines.append(
            f"- {job.get('id')}: {job.get('status')} -> {job.get('next_stage')}; confirmation={job.get('needs_user_confirmation')}"
        )
    return "\n".join(lines) if lines else "- No jobs.csv rows found.", status_counts


def recommended_action(classifications: Counter) -> tuple[str, str, str]:
    if not classifications:
        return (
            "report_only",
            "No recurring failure pattern crossed the evidence threshold. Keep observing and do not patch source files.",
            "No new eval case yet.",
        )
    top, _ = classifications.most_common(1)[0]
    if top == "prompt_quality":
        return (
            "eval_or_reference_patch",
            "Add or update an output eval plus the relevant prompt/reference guidance.",
            "Add a case that rejects workflow labels and requires model-facing Seedance wording.",
        )
    if top == "gate_gap":
        return (
            "gate_or_eval_patch",
            "Add an eval case first; patch the gate only if current gate text cannot catch the evidence.",
            "Add a case that reproduces the missed QC pattern and names the expected blocker.",
        )
    if top == "checker_contract":
        return (
            "checker_or_script_patch",
            "Patch checker requirements or deterministic QC only after confirming the current evidence target.",
            "Add a case that verifies the checker inspects the actual artifact, not only maker summaries.",
        )
    if top == "handoff_governance":
        return (
            "worker_or_gate_patch",
            "Tighten final handoff packaging rules and add an eval for deprecated/internal clutter.",
            "Add a case that fails when seedance_web_final contains deprecated drafts or internal QC clutter.",
        )
    if top == "approval_safety":
        return (
            "approval_boundary_patch",
            "Patch approval wording only if the direct/current-job/batch boundary is ambiguous in current docs.",
            "Add a case that distinguishes current-job approval from batch approval.",
        )
    if top == "automation_drift":
        return (
            "automation_report",
            "Keep this as an operations report unless the scheduler or lane selector is demonstrably stale.",
            "Add a case that treats no runnable lanes at seedance_inputs_prepared as a success state.",
        )
    return (
        "proposal_review",
        "Prepare a reviewed patch against the smallest durable surface.",
        "Add a focused regression case for the repeated signal.",
    )


def summarize_review_feedback(entries: list[dict]) -> tuple[str, Counter, Counter]:
    if not entries:
        return "- No review feedback ledger entries found.", Counter(), Counter()

    outcome_counts = Counter(str(entry.get("review_outcome", "")) for entry in entries)
    surface_counts = Counter(str(entry.get("suggested_surface", "")) for entry in entries)
    lines = []
    for entry in entries[-8:]:
        evidence = entry.get("evidence_paths") or []
        if isinstance(evidence, list):
            evidence_text = ", ".join(str(item) for item in evidence[:3])
        else:
            evidence_text = str(evidence)
        lines.append(
            "- {id}: {job_id}/{stage} `{outcome}` -> {meaning} (surface: `{surface}`; evidence: {evidence})".format(
                id=entry.get("id", "<no-id>"),
                job_id=entry.get("job_id", "<no-job>"),
                stage=entry.get("stage", "<no-stage>"),
                outcome=entry.get("review_outcome", "<no-outcome>"),
                meaning=entry.get("meaning", "<no-meaning>"),
                surface=entry.get("suggested_surface", "<none>"),
                evidence=evidence_text or "none",
            )
        )
    return "\n".join(lines), outcome_counts, surface_counts


def build_proposal(
    root: Path,
    signals: list[dict[str, object]],
    jobs_summary: str,
    status_counts: Counter,
    review_entries: list[dict],
) -> str:
    classifications = Counter(str(signal["classification"]) for signal in signals)
    action_key, action, eval_case = recommended_action(classifications)
    evidence_paths = sorted({str(signal["evidence_path"]) for signal in signals})
    if not evidence_paths:
        evidence_paths = ["STATE.md", "jobs.csv"]
    if review_entries and "logs/review_feedback.jsonl" not in evidence_paths:
        evidence_paths.append("logs/review_feedback.jsonl")

    signal_lines = []
    for signal in signals[:12]:
        terms = ", ".join(str(term) for term in signal["matched_terms"])
        signal_lines.append(
            f"- `{signal['signal']}` as `{signal['classification']}` from `{signal['evidence_path']}`; matched: {terms}"
        )
    if not signal_lines:
        signal_lines.append("- No repeated failure signal detected in the bounded evidence scan.")

    status_line = ", ".join(f"{status or '<blank>'}: {count}" for status, count in status_counts.items())
    status_line = status_line or "No job status counts available."
    review_summary, outcome_counts, surface_counts = summarize_review_feedback(review_entries)
    outcome_line = ", ".join(f"{key or '<blank>'}: {value}" for key, value in outcome_counts.items())
    outcome_line = outcome_line or "No review outcomes available."
    surface_line = ", ".join(f"{key or '<blank>'}: {value}" for key, value in surface_counts.items())
    surface_line = surface_line or "No suggested surfaces available."

    return f"""# Skill Improvement Proposal

Generated: {datetime.now().isoformat(timespec="seconds")}

## Observed Signals

{chr(10).join(signal_lines)}

## Evidence Paths

{chr(10).join(f"- `{path}`" for path in evidence_paths)}

## Job Snapshot

Status counts: {status_line}

{jobs_summary}

## Review Feedback

Outcome counts: {outcome_line}

Suggested surfaces: {surface_line}

{review_summary}

## Classification

{chr(10).join(f"- `{key}`: {value}" for key, value in classifications.items()) or "- `report_only`: 1"}

## Recommended Action

`{action_key}`: {action}

## Proposed Durable Surface

- Start with `evals/output_cases.json` or the relevant skill `references/*.md`.
- Patch `workers/*.md`, `gates/*.md`, or `tools/*.py` only when the proposal names concrete evidence that the current runtime contract is insufficient.
- Do not patch source files from an unattended scheduled run.

## Suggested Eval Case

{eval_case}

## Verification Command

```bash
python3 scripts/skill-release-check.py --root . --skill viral-replica-improver --strict
python3 scripts/skill-release-check.py --root . --skill viral-replica --strict
bash scripts/release-check.sh
```

## Approval Boundary

This proposal is safe to generate automatically. Applying patches to skill, worker, gate, eval, or script files requires explicit approval or an explicit implementation request.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--event-limit", type=int, default=80, help="Tail events to inspect")
    parser.add_argument("--out", help="Proposal output path")
    parser.add_argument("--dry-run", action="store_true", help="Print proposal instead of writing it")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    blobs = collect_text_blobs(root, args.event_limit)
    jobs = read_jobs(root / "jobs.csv")
    jobs_summary, status_counts = summarize_jobs(jobs)
    review_entries = read_review_feedback_tail(root, args.event_limit)
    signals = classify_signals(blobs)
    signals.extend(signals_from_review_feedback(review_entries))
    proposal = build_proposal(root, signals, jobs_summary, status_counts, review_entries)

    if args.dry_run:
        print(proposal)
        return 0

    if args.out:
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = root / out_path
    else:
        stamp = datetime.now().strftime("%Y-%m-%d")
        out_path = (
            root
            / ".agents"
            / "skills"
            / "viral-replica-improver"
            / "reports"
            / "skill-improvement-proposals"
            / f"{stamp}-outer-loop-proposal.md"
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(proposal, encoding="utf-8")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
