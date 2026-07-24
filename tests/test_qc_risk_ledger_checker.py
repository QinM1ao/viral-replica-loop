import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests import test_qc_outcomes as review_fixture


ROOT = Path(__file__).resolve().parents[1]
CHECKER_QC = ROOT / "tools" / "checker_review_qc.py"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_unified_request(directory, families):
    compare = directory / "compare.jpg"
    promoted = directory / "part1.png"
    compare.write_bytes(b"compare")
    promoted.write_bytes(b"promoted")
    request = {
        "version": 1,
        "request_type": "storyboard_visual_acceptance",
        "job_id": "job-test",
        "stage": "image_batch_qc",
        "mode": "active",
        "required": True,
        "invocation_count": 1,
        "active_input_fingerprint": "active-current",
        "deterministic_input_fingerprint": "deterministic-current",
        "canonical_compare_context": {
            "role": "overview",
            "path": str(compare),
            "sha256": sha256(compare),
            "item_count": 1,
            "source_artifacts": [
                {
                    "label": "part1 promoted",
                    "path": str(promoted),
                    "sha256": sha256(promoted),
                }
            ],
        },
        "profile_expectations": {},
        "families": families,
    }
    request["request_id"] = hashlib.sha256(
        json.dumps(
            request,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    path = directory / "semantic_review_request.json"
    path.write_text(json.dumps(request) + "\n", encoding="utf-8")
    return path, compare


class QcRiskLedgerCheckerTest(unittest.TestCase):
    def run_checker(self, directory, review, request):
        out_json = directory / "review_qc.json"
        out_md = directory / "review_qc.md"
        result = subprocess.run(
            [
                "python3",
                str(CHECKER_QC),
                "--review",
                str(review),
                "--risk-request",
                str(request),
                "--out-json",
                str(out_json),
                "--out-md",
                str(out_md),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        return result, json.loads(out_json.read_text(encoding="utf-8"))

    def test_checker_qc_binds_one_review_to_all_requested_family_fingerprints(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            review = directory / "review.md"
            request = directory / "semantic_review_request.json"
            out_json = directory / "review_qc.json"
            out_md = directory / "review_qc.md"
            review_fixture.write_review(review)
            request.write_text(
                json.dumps(
                    {
                        "job_id": "job-test",
                        "stage": "image_batch_qc",
                        "required": True,
                        "invocation_count": 1,
                        "families": [
                            {"name": "visual_integrity", "fingerprint_hash": "visual-current"},
                            {
                                "name": "source_to_generation_fidelity",
                                "fingerprint_hash": "source-current",
                            },
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    str(CHECKER_QC),
                    "--review",
                    str(review),
                    "--risk-request",
                    str(request),
                    "--out-json",
                    str(out_json),
                    "--out-md",
                    str(out_md),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(report["overall"], "PASS")
            self.assertEqual(
                report["qc_risk_review"]["family_fingerprints"],
                {
                    "visual_integrity": "visual-current",
                    "source_to_generation_fidelity": "source-current",
                },
            )
            self.assertEqual(
                report["qc_risk_review"]["family_results"],
                {
                    "visual_integrity": "PASS",
                    "source_to_generation_fidelity": "PASS",
                },
            )

    def test_checker_qc_preserves_mixed_results_per_requested_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            review = directory / "review.md"
            request = directory / "semantic_review_request.json"
            out_json = directory / "review_qc.json"
            out_md = directory / "review_qc.md"
            review_fixture.write_review(
                review,
                result="FAIL",
                outcome="HARD_FAILURE",
                reason="source fidelity failed",
                failed_item="source_to_generation_fidelity",
                failure_type="wrong_action",
                retry_variable="shot_line_binding",
            )
            with review.open("a", encoding="utf-8") as handle:
                handle.write(
                    'Family results: {"visual_integrity":"PASS",'
                    '"source_to_generation_fidelity":"FAIL"}\n'
                )
            request.write_text(
                json.dumps(
                    {
                        "job_id": "job-test",
                        "stage": "image_batch_qc",
                        "required": True,
                        "invocation_count": 1,
                        "families": [
                            {"name": "visual_integrity", "fingerprint_hash": "visual-current"},
                            {
                                "name": "source_to_generation_fidelity",
                                "fingerprint_hash": "source-current",
                            },
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    str(CHECKER_QC),
                    "--review",
                    str(review),
                    "--risk-request",
                    str(request),
                    "--out-json",
                    str(out_json),
                    "--out-md",
                    str(out_md),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(report["overall"], "FAIL")
            self.assertEqual(
                report["qc_risk_review"]["family_results"],
                {
                    "visual_integrity": "PASS",
                    "source_to_generation_fidelity": "FAIL",
                },
            )

    def test_pre_seedance_checker_requires_one_result_per_line_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            review = directory / "review.md"
            request = directory / "semantic_review_request.json"
            review.write_text(
                "\n".join(
                    [
                        "Gate: gates/pre_seedance_pack_gate.md",
                        "Job: job-test",
                        "Stage: pre_seedance_pack",
                        "Input artifacts: output/job-test/seedance/director_plan.json",
                        "Checks: checked source lines and target edits",
                        "Result: PASS",
                        'Family results: {"source_to_generation_fidelity":"PASS"}',
                        "Outcome type: PASS",
                        "Why not fail:",
                        "Reason: all required checks passed",
                        "Failed item: none",
                        "Failure type: none",
                        "Retry variable: none",
                        "Locked variables: source evidence and approved images",
                        "Next status: seedance_inputs_prepared",
                        "Needs user confirmation: false",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            request.write_text(
                json.dumps(
                    {
                        "job_id": "job-test",
                        "stage": "pre_seedance_pack",
                        "required": True,
                        "invocation_count": 1,
                        "families": [
                            {
                                "name": "source_to_generation_fidelity",
                                "fingerprint_hash": "source-current",
                                "scope": {
                                    "line_edit_audit": [
                                        {
                                            "id": "part3:speech_p3_02:1",
                                            "from": "我反正老是",
                                            "to": "平时",
                                            "reason": "person_or_role",
                                        }
                                    ]
                                },
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            _, report = self.run_checker(directory, review, request)

            self.assertEqual(report["overall"], "STOP")
            failed = {
                check["name"]
                for check in report["checks"]
                if check["status"] == "STOP"
            }
            self.assertIn("line_edit_results", failed)

            with review.open("a", encoding="utf-8") as handle:
                handle.write(
                    'Line edit results: {"part3:speech_p3_02:1":'
                    '{"result":"PASS","necessary":true,"minimal":true,'
                    '"evidence_checked":true,'
                    '"note":"The current request explicitly changes this role slot only."}}\n'
                )

            _, report = self.run_checker(directory, review, request)

            self.assertEqual(report["overall"], "PASS")
            self.assertEqual(
                report["qc_risk_review"]["line_edit_results"][
                    "part3:speech_p3_02:1"
                ]["result"],
                "PASS",
            )

    def test_unified_checker_requires_exact_explicit_family_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            review = directory / "review.md"
            request, _ = write_unified_request(
                directory,
                [
                    {"name": "geometry_appearance", "fingerprint_hash": "geometry-current"},
                    {
                        "name": "identity_product_material_integrity",
                        "fingerprint_hash": "integrity-current",
                    },
                ],
            )
            review_fixture.write_review(review)
            with review.open("a", encoding="utf-8") as handle:
                handle.write('Family results: {"geometry_appearance":"PASS"}\n')

            _, report = self.run_checker(directory, review, request)

            self.assertEqual(report["overall"], "STOP")
            failed = {
                check["name"]
                for check in report["checks"]
                if check["status"] == "STOP"
            }
            self.assertIn("qc_risk_family_results", failed)

    def test_unified_checker_rejects_unrequested_family_and_wrong_top_level_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            review = directory / "review.md"
            request, _ = write_unified_request(
                directory,
                [{"name": "geometry_appearance", "fingerprint_hash": "geometry-current"}],
            )
            review_fixture.write_review(review)
            with review.open("a", encoding="utf-8") as handle:
                handle.write(
                    'Family results: {"geometry_appearance":"FAIL",'
                    '"skincare_progression":"PASS"}\n'
                )

            _, report = self.run_checker(directory, review, request)

            self.assertEqual(report["overall"], "STOP")
            failures = {
                check["name"]
                for check in report["checks"]
                if check["status"] == "STOP"
            }
            self.assertIn("qc_risk_family_results", failures)
            self.assertIn("qc_risk_top_level_result", failures)

    def test_unified_checker_rejects_changed_compare_or_original_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            review = directory / "review.md"
            request, compare = write_unified_request(
                directory,
                [{"name": "geometry_appearance", "fingerprint_hash": "geometry-current"}],
            )
            review_fixture.write_review(review)
            with review.open("a", encoding="utf-8") as handle:
                handle.write('Family results: {"geometry_appearance":"PASS"}\n')
            compare.write_bytes(b"changed compare")

            _, report = self.run_checker(directory, review, request)

            self.assertEqual(report["overall"], "STOP")
            failures = {
                check["name"]
                for check in report["checks"]
                if check["status"] == "STOP"
            }
            self.assertIn("storyboard_visual_context_binding", failures)


if __name__ == "__main__":
    unittest.main()
