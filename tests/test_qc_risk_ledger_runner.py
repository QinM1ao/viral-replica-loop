import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from tests import test_runner_enforcement as runner_fixture
from tools.checker_review_qc import bind_risk_request, review_report


class QcRiskLedgerRunnerTest(unittest.TestCase):
    def setUp(self):
        self.fixture = runner_fixture.RunnerEnforcementTest(methodName="runTest")
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_unchanged_stage_passes_without_a_new_checker_review(self):
        self.fixture.write_job(
            "image_qc_passed",
            "seedance_inputs_prepared",
            False,
            "output/job-001/checks/pre_seedance_pack_gate_review.md",
        )
        first = self.fixture.run_loop(
            "--record-gate-result",
            "PASS",
            "--artifact",
            "output/job-001/checks/pre_seedance_pack_gate_review.md",
        )
        self.assertEqual(first.returncode, 0)

        checker_qc = (
            self.fixture.root
            / "output/job-001/checks/pre_seedance_pack_gate_review_qc.json"
        )
        archived_checker = checker_qc.with_name("prior_stage_gate_review_qc.json")
        checker_qc.rename(archived_checker)
        state_path = (
            self.fixture.root
            / "output/job-001/checks/qc_risk_ledger_state.json"
        )
        state = json.loads(state_path.read_text(encoding="utf-8"))
        for family in state["families"].values():
            for evidence in family.get("evidence", []):
                if evidence.get("name") == "batched_checker_review":
                    evidence["path"] = "output/job-001/checks/prior_stage_gate_review_qc.json"
        state_path.write_text(json.dumps(state) + "\n", encoding="utf-8")

        second = self.fixture.run_loop(
            "--record-gate-result",
            "PASS",
            "--artifact",
            "output/job-001/checks/pre_seedance_pack_gate_review.md",
            check=False,
        )

        self.assertEqual(second.returncode, 0, second.stderr)

    def test_runner_binds_one_checker_review_and_records_the_gate(self):
        artifact = "output/job-001/checks/pre_seedance_pack_gate_review.md"
        self.fixture.write_job(
            "image_qc_passed",
            "seedance_inputs_prepared",
            False,
            artifact,
        )
        checker_qc = (
            self.fixture.root
            / "output/job-001/checks/pre_seedance_pack_gate_review_qc.json"
        )
        checker_qc.unlink()

        first = self.fixture.run_loop(
            "--record-gate-result",
            "PASS",
            "--artifact",
            artifact,
            check=False,
        )
        self.assertNotEqual(first.returncode, 0)
        request_path = (
            self.fixture.root
            / "output/job-001/checks/pre_seedance_pack_semantic_review_request.json"
        )
        request = json.loads(request_path.read_text(encoding="utf-8"))
        family_results = {
            item["name"]: "PASS" for item in request["families"]
        }
        line_edit_results = {}
        for family in request["families"]:
            for edit in (family.get("scope") or {}).get("line_edit_audit") or []:
                line_edit_results[edit["id"]] = {
                    "result": "PASS",
                    "necessary": True,
                    "minimal": True,
                    "evidence_checked": True,
                    "note": "verified against the current source evidence",
                }
        review_lines = [
            "Gate: gates/pre_seedance_pack_gate.md",
            "Job: job-001",
            "Stage: pre_seedance_pack",
            f"Risk request id: {request['request_id']}",
            (
                "Risk request sha256: "
                + hashlib.sha256(request_path.read_bytes()).hexdigest()
            ),
            "Input artifacts: output/job-001/seedance/director_plan.json",
            "Checks: all requested semantic families",
            "Result: PASS",
            f"Family results: {json.dumps(family_results, separators=(',', ':'))}",
            "Outcome type: PASS",
            "Why not fail:",
            "Reason: all requested families passed",
            "Failed item: none",
            "Failure type: none",
            "Retry variable: none",
            "Locked variables: current source and approved assets",
            "Next status: seedance_inputs_prepared",
            "Needs user confirmation: false",
        ]
        if line_edit_results:
            review_lines.append(
                "Line edit results: "
                + json.dumps(line_edit_results, separators=(",", ":"))
            )
        (
            self.fixture.root
            / artifact
        ).write_text("\n".join(review_lines) + "\n", encoding="utf-8")

        second = self.fixture.run_loop(
            "--record-gate-result",
            "PASS",
            "--artifact",
            artifact,
            check=False,
        )

        self.assertEqual(second.returncode, 0, second.stderr)
        bound = json.loads(checker_qc.read_text(encoding="utf-8"))
        self.assertEqual(bound["overall"], "PASS")
        self.assertEqual(
            bound["qc_risk_review"]["request_id"],
            request["request_id"],
        )

    def test_runner_rejects_review_declared_for_an_older_request(self):
        artifact = "output/job-001/checks/pre_seedance_pack_gate_review.md"
        self.fixture.write_job(
            "image_qc_passed",
            "seedance_inputs_prepared",
            False,
            artifact,
        )
        checker_qc = (
            self.fixture.root
            / "output/job-001/checks/pre_seedance_pack_gate_review_qc.json"
        )
        checker_qc.unlink()

        first = self.fixture.run_loop(
            "--record-gate-result",
            "PASS",
            "--artifact",
            artifact,
            check=False,
        )
        self.assertNotEqual(first.returncode, 0)
        request_path = (
            self.fixture.root
            / "output/job-001/checks/pre_seedance_pack_semantic_review_request.json"
        )
        request = json.loads(request_path.read_text(encoding="utf-8"))
        review = (self.fixture.root / artifact).read_text(encoding="utf-8")
        review += (
            "\nRisk request id: old-request\n"
            + f"Risk request sha256: {'0' * 64}\n"
        )
        (self.fixture.root / artifact).write_text(review, encoding="utf-8")

        state_before = (self.fixture.root / "RUNNER_STATE.json").read_bytes()
        jobs_before = (self.fixture.root / "jobs.csv").read_bytes()
        second = self.fixture.run_loop(
            "--record-gate-result",
            "PASS",
            "--artifact",
            artifact,
            check=False,
        )

        self.assertNotEqual(second.returncode, 0)
        self.assertEqual(
            (self.fixture.root / "RUNNER_STATE.json").read_bytes(),
            state_before,
        )
        self.assertEqual(
            (self.fixture.root / "jobs.csv").read_bytes(),
            jobs_before,
        )
        bound = json.loads(checker_qc.read_text(encoding="utf-8"))
        check = next(
            item
            for item in bound["checks"]
            if item["name"] == "qc_risk_review_declared_request"
        )
        self.assertEqual(check["status"], "STOP")
        self.assertNotEqual(request["request_id"], "old-request")

    def test_checker_wait_uses_stable_request_creation_time_not_rewrite_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request_path = root / "request.json"
            request = {
                "job_id": "job-001",
                "stage": "pre_seedance_pack",
                "created_at": "2000-01-01T00:00:00",
                "required": True,
                "invocation_count": 1,
                "request_id": "stable-request",
                "families": [
                    {
                        "name": "visual_integrity",
                        "fingerprint_hash": "a" * 64,
                    }
                ],
            }
            request_path.write_text(
                json.dumps(request) + "\n",
                encoding="utf-8",
            )
            request_sha = hashlib.sha256(request_path.read_bytes()).hexdigest()
            review_path = root / "review.md"
            review_path.write_text(
                "\n".join(
                    [
                        "Gate: gates/pre_seedance_pack_gate.md",
                        "Job: job-001",
                        "Stage: pre_seedance_pack",
                        "Risk request id: stable-request",
                        f"Risk request sha256: {request_sha}",
                        "Input artifacts: current inputs",
                        "Checks: visual integrity",
                        "Result: PASS",
                        "Outcome type: PASS",
                        "Reason: current evidence passed",
                        "Failed item: none",
                        "Failure type: none",
                        "Retry variable: none",
                        "Locked variables: current inputs",
                        "Next status: seedance_inputs_prepared",
                        "Needs user confirmation: false",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            report = bind_risk_request(
                review_report(review_path),
                request_path,
                root,
                require_declared_request=True,
            )

            self.assertEqual(report["overall"], "PASS")
            self.assertGreater(
                report["qc_risk_review"]["wait_seconds"],
                60,
            )


if __name__ == "__main__":
    unittest.main()
