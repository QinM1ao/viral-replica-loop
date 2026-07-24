import tempfile
import unittest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from run_next_loop_round import decision_markdown


class StageExecutionRunnerContractTest(unittest.TestCase):
    def test_suggested_prompt_keeps_shared_state_writes_with_the_coordinator(self):
        with tempfile.TemporaryDirectory() as tmp:
            markdown = decision_markdown(
                Path(tmp),
                {
                    "id": "job-001",
                    "status": "storyboard_passed",
                    "next_stage": "image_batch_qc",
                    "output_dir": "output/job-001",
                },
                {
                    "decision": "continue",
                    "reason": "fixture",
                    "outcome_type": "PASS",
                    "canonical_stage": "image_batch_qc",
                    "action": "Run isolated Part work packets.",
                    "worker": "image maker",
                    "worker_file": "workers/image_batch_worker.md",
                    "script_file": "tools/image_batch_fanout.py",
                    "next_expected": "image_qc_passed",
                    "rule_id": "storyboard_passed",
                    "gate": "gates/image_batch_gate.md",
                    "retry_state": {},
                    "retry_limit": 2,
                    "cost_state": {},
                    "checks": [],
                },
            )

        self.assertIn(
            "Do not write STATE.md, jobs.csv, or RUNNER_STATE.json directly.",
            markdown,
        )
        self.assertIn(
            "The coordinator records the gate through ./run-loop.sh",
            markdown,
        )
        self.assertIn(
            "Dispatch only sealed tools/stage_execution.py work packets",
            markdown,
        )
        self.assertNotIn(
            "After the stage, write STATE.md and jobs.csv.",
            markdown,
        )


if __name__ == "__main__":
    unittest.main()
