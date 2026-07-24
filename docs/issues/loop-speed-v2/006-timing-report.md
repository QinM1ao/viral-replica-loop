---
title: Timing report
labels:
  - implemented
status: done
parent: docs/prd/2026-06-22-loop-speed-v2.md
---

# Timing report

## Parent

`docs/prd/2026-06-22-loop-speed-v2.md`

## What to build

Build a timing report that summarizes where loop time is actually going.

The report should read event logs and group elapsed time by job, stage, and gate result. It should highlight non-PASS events and distinguish image-stage repair, QC, downstream reuse, Seedance generation, provider failure, evidence failure, visual failure, and cost gate stops when that data is available.

The output should be understandable to the user without reading raw JSON logs.

## Acceptance criteria

- [x] A command can generate a timing report from the loop event log.
- [x] The report lists first event, last event, total elapsed span, and event counts.
- [x] The report groups gate results by job and stage.
- [x] The report highlights non-PASS events with failure type, retry variable, and short note.
- [x] The report shows recent focused timelines for selected jobs.
- [x] The report identifies likely slow areas such as image-stage repair, provider retry, repeated downstream revalidation, and cost stops.
- [x] The report has a Markdown output suitable for handoff or final assistant responses.
- [x] Tests use a small fixture event log and verify grouping, elapsed-time formatting, non-PASS highlighting, and selected-job timeline output.

## Implementation

Command:

```bash
python3 tools/timing_report.py --root . --out output/timing-report.md --job job-003 --job job-005 --job job-006
```

Verification:

```bash
python3 -m unittest tests/test_timing_report.py
./scripts/verify.sh
```

## User stories covered

28, 29, 30, 35, 40

## Blocked by

None - can start immediately.
