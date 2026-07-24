import json
import unittest

from tests import test_runner_enforcement as runner_fixture


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


if __name__ == "__main__":
    unittest.main()
