import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import sys


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from checker_review_qc import review_report
from qc_outcomes import (
    OUTCOME_EVIDENCE_STOP,
    OUTCOME_HARD_FAILURE,
    OUTCOME_VISUAL_WARNING,
)
from run_next_loop_round import default_runner_state, record_gate_result


BASE_REVIEW = """Gate: gates/image_batch_gate.md
Job: job-test
Stage: image_batch_qc
Input artifacts: output/job-test/image-batch/改图审核.md
Checks: checked actual images and QC evidence
Result: {result}
Outcome type: {outcome}
Why not fail: {why_not_fail}
Reason: {reason}
Failed item: {failed_item}
Failure type: {failure_type}
Retry variable: {retry_variable}
Locked variables: approved source storyboard layout
Next status: {next_status}
Needs user confirmation: {needs_confirmation}
"""


def write_review(path, **overrides):
    values = {
        "result": "PASS",
        "outcome": "PASS",
        "why_not_fail": "",
        "reason": "all required checks passed",
        "failed_item": "none",
        "failure_type": "none",
        "retry_variable": "none",
        "next_status": "image_qc_passed",
        "needs_confirmation": "false",
    }
    values.update(overrides)
    path.write_text(BASE_REVIEW.format(**values), encoding="utf-8")


class QcOutcomeTests(unittest.TestCase):
    def test_hard_failure_is_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            review = Path(tmp) / "review.md"
            write_review(
                review,
                result="FAIL",
                outcome="HARD_FAILURE",
                reason="wrong product appears in product close-up",
                failed_item="Part1 panel 10",
                failure_type="wrong_product",
                retry_variable="product_reference",
            )

            report = review_report(review)

        self.assertEqual(report["overall"], "FAIL")
        self.assertEqual(report["outcome_type"], OUTCOME_HARD_FAILURE)
        self.assertEqual(report["blocker_category"], "visual_failure")

    def test_visual_warning_with_why_not_fail_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            review = Path(tmp) / "review.md"
            write_review(
                review,
                outcome="VISUAL_WARNING",
            why_not_fail="Tiny uniform API-size drift; no subject squeeze, same shot order, active hashes match.",
                reason="usable Seedance input with a non-material metric warning",
            )

            report = review_report(review)

        self.assertEqual(report["overall"], "PASS")
        self.assertEqual(report["outcome_type"], OUTCOME_VISUAL_WARNING)
        self.assertEqual(report["blocker_category"], "visual_warning")

    def test_visual_warning_without_why_not_fail_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            review = Path(tmp) / "review.md"
            write_review(
                review,
                outcome="VISUAL_WARNING",
                why_not_fail="",
                reason="tiny local concern",
            )

            report = review_report(review)

        self.assertEqual(report["overall"], "STOP")
        self.assertEqual(report["outcome_type"], OUTCOME_VISUAL_WARNING)
        failing = {check["name"] for check in report["checks"] if check["status"] == "FAIL"}
        self.assertIn("visual_warning_has_why_not_fail", failing)

    def test_visual_warning_cannot_cover_hard_failure_terms(self):
        with tempfile.TemporaryDirectory() as tmp:
            review = Path(tmp) / "review.md"
            write_review(
                review,
                outcome="VISUAL_WARNING",
                why_not_fail="Looks close enough.",
                reason="wrong person in Part2 but otherwise usable",
            )

            report = review_report(review)

        self.assertEqual(report["overall"], "STOP")
        failing = {check["name"] for check in report["checks"] if check["status"] == "FAIL"}
        self.assertIn("visual_warning_no_hard_failure_red_flags", failing)

    def test_visual_warning_cannot_cover_hard_product_label_failures(self):
        for reason in (
            "blank label in the designated hero close-up",
            "blank bottle in the designated hero close-up",
            "smoothed label in the designated hero close-up",
            "wrong label design in the designated hero close-up",
            "old-source label remains on the product",
            "major product-name anchor missing in the hero close-up",
            "missing major brand anchor in the hero close-up",
            "The designated hero label is blank.",
            "The hero close-up has an incorrect label design.",
            "The bottle still uses the old source's label.",
            "The major brand anchor is absent.",
            "wrong bottle shape in the designated hero close-up",
            "an invented spray nozzle appears on the toner bottle",
            "目标产品瓶型错误，出现了不应有的喷头",
        ):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as tmp:
                review = Path(tmp) / "review.md"
                write_review(
                    review,
                    outcome="VISUAL_WARNING",
                    failure_type="product_label_microtext_only",
                    why_not_fail="The storyboard is otherwise usable.",
                    reason=reason,
                )

                report = review_report(review)

            self.assertEqual(report["overall"], "STOP", reason)
            failing = {
                check["name"]
                for check in report["checks"]
                if check["status"] == "FAIL"
            }
            self.assertTrue(
                {
                    "visual_warning_no_hard_failure_red_flags",
                    "visual_warning_label_finding_code",
                }
                & failing
            )

    def test_storyboard_scale_microtext_can_remain_visual_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            review = Path(tmp) / "review.md"
            write_review(
                review,
                outcome="VISUAL_WARNING",
                failure_type="product_label_microtext_only",
                why_not_fail=(
                    "The distant label keeps the same color, line layout, "
                    "brand impression, and product identity."
                ),
                reason=(
                    "Storyboard-scale microtext is not character-for-character "
                    "but the hero brand and product-name anchors are correct."
                ),
            )

            report = review_report(review)

        self.assertEqual(report["overall"], "PASS")
        self.assertEqual(report["outcome_type"], OUTCOME_VISUAL_WARNING)

    def test_non_label_package_tool_warning_does_not_require_label_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            review = Path(tmp) / "review.md"
            write_review(
                review,
                outcome="VISUAL_WARNING",
                failure_type="tool_shape_visual_warning",
                why_not_fail=(
                    "The package is visibly cut open and the product is removed "
                    "through the slit; only the knife silhouette is slightly soft."
                ),
                reason=(
                    "The bottle and outer package remain correct. The local tool "
                    "shape does not affect the product label or action chain."
                ),
            )

            report = review_report(review)

        self.assertEqual(report["overall"], "PASS")
        failing = {
            check["name"]
            for check in report["checks"]
            if check["status"] == "FAIL"
        }
        self.assertNotIn("visual_warning_label_finding_code", failing)

    def test_evidence_stop_is_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            review = Path(tmp) / "review.md"
            write_review(
                review,
                result="STOP",
                outcome="EVIDENCE_STOP",
                reason="missing ImageGen input proof for the saved candidate",
                failed_item="codex_imagegen_contract.json",
                failure_type="missing_imagegen_input_proof",
                retry_variable="codex_imagegen_contract",
                next_status="image_sample_approved",
                needs_confirmation="yes",
            )

            report = review_report(review)

        self.assertEqual(report["overall"], "STOP")
        self.assertEqual(report["outcome_type"], OUTCOME_EVIDENCE_STOP)
        self.assertEqual(report["blocker_category"], "evidence_failure")

    def test_gate_record_preserves_visual_warning(self):
        state = default_runner_state()
        job = {"id": "job-test", "status": "image_sample_approved", "last_artifact": ""}
        decision = {"canonical_stage": "image_batch_qc", "gate": "gates/image_batch_gate.md"}
        args = SimpleNamespace(
            record_gate_result="PASS",
            failure_type="",
            retry_variable="",
            artifact="",
            note="tiny metric warning",
            outcome_type="VISUAL_WARNING",
            why_not_fail="Visible image is source-faithful; metric drift is non-material.",
            spent_gpt_image_runs=0,
            spent_seedance_runs=0,
            generation_intent="current_job",
        )

        job_state, event = record_gate_result(state, job, decision, args, ROOT, {})

        self.assertEqual(event["outcome_type"], OUTCOME_VISUAL_WARNING)
        self.assertEqual(event["blocker_category"], "visual_warning")
        self.assertEqual(job_state["last_outcome_type"], OUTCOME_VISUAL_WARNING)


if __name__ == "__main__":
    unittest.main()
