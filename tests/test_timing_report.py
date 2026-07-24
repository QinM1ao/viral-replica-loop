import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import timing_report


class TimingReportTest(unittest.TestCase):
    def test_duration_formatting(self):
        self.assertEqual(timing_report.format_duration(0), "0s")
        self.assertEqual(timing_report.format_duration(125), "2m 5s")
        self.assertEqual(timing_report.format_duration(4530), "1h 15m 30s")

    def test_markdown_report_groups_and_highlights_events(self):
        log_path = ROOT / "tests" / "fixtures" / "timing_events.jsonl"
        events = timing_report.read_event_log(log_path)
        summary = timing_report.summarize_events(events)
        report = timing_report.render_report(summary, log_path, selected_jobs=["job-101"], timeline_limit=10)

        self.assertIn("- First event: `2026-06-22T10:00:00`", report)
        self.assertIn("- Last event: `2026-06-22T11:15:00`", report)
        self.assertIn("- Total elapsed span: **1h 15m**", report)
        self.assertIn("| `job-101` | `image_batch_qc` |", report)
        self.assertIn("STOP:1", report)
        self.assertIn("STOP:45m 30s", report)
        self.assertIn("provider_524", report)
        self.assertIn("source_storyboard_edit_route", report)
        self.assertIn("provider failure", report)
        self.assertIn("cost gate stop", report)
        self.assertIn("missing_manifest_evidence", report)
        self.assertIn("approved_visual_manifest", report)
        self.assertIn("## Non-Image Pre-Seedance Budget", report)
        self.assertIn("### `job-101`", report)
        self.assertIn("`request_qc` gate_result **FAIL**", report)
        self.assertNotIn("### `job-102`", report)

    def test_selected_jobs_filter_summary(self):
        log_path = ROOT / "tests" / "fixtures" / "timing_events.jsonl"
        events = timing_report.read_event_log(log_path)
        summary = timing_report.summarize_events(events, selected_jobs=["job-102"])
        report = timing_report.render_report(summary, log_path, selected_jobs=["job-102"])

        self.assertIn("`job-102`", report)
        self.assertIn("generation_approval", report)
        self.assertNotIn("`job-101` | `image_batch_qc`", report)

    def test_explicit_duration_is_used_for_budget_and_stage_elapsed(self):
        events = [
            {
                "type": "gate_result",
                "time": "2026-07-10T10:00:00",
                "job": "job-fast",
                "stage": "pre_seedance_pack",
                "result": "PASS",
                "duration_seconds": 601,
                "_line": 1,
                "_time": timing_report.parse_time("2026-07-10T10:00:00"),
            }
        ]
        summary = timing_report.summarize_events(events)
        report = timing_report.render_report(summary, Path("events.jsonl"), non_image_budget_seconds=1200)

        self.assertEqual(summary["non_image_pre_seedance"]["job-fast"], 601)
        self.assertIn("PASS:10m 1s", report)
        self.assertIn("| `job-fast` | 10m 1s | 20m | **PASS** |", report)

    def test_budget_separates_reused_job_ids_by_workflow_run(self):
        events = []
        for index, (run_id, duration) in enumerate((("run-a", 400), ("run-b", 500)), start=1):
            events.append(
                {
                    "type": "gate_result",
                    "time": f"2026-07-10T10:0{index}:00",
                    "job": "job-001",
                    "workflow_run_id": run_id,
                    "stage": "pre_seedance_pack",
                    "result": "PASS",
                    "duration_seconds": duration,
                    "_line": index,
                    "_time": timing_report.parse_time(f"2026-07-10T10:0{index}:00"),
                }
            )
        summary = timing_report.summarize_events(events)

        self.assertEqual(summary["non_image_pre_seedance"]["job-001@run-a"], 400)
        self.assertEqual(summary["non_image_pre_seedance"]["job-001@run-b"], 500)

    def test_fail_on_budget_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "events.jsonl"
            log.write_text(
                json.dumps(
                    {
                        "type": "gate_result",
                        "time": "2026-07-10T10:00:00",
                        "job": "job-001",
                        "workflow_run_id": "run-over",
                        "stage": "pre_seedance_pack",
                        "result": "PASS",
                        "duration_seconds": 1201,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    "python3",
                    str(ROOT / "tools" / "timing_report.py"),
                    "--root",
                    str(root),
                    "--log",
                    str(log),
                    "--fail-on-budget",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("**OVER**", result.stdout)


if __name__ == "__main__":
    unittest.main()
