import csv
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "tools" / "run_next_loop_round.py"


class CostPolicyEnforcementTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._write_fixture()

    def tearDown(self):
        self.tmp.cleanup()

    def run_loop(self, *args, check=True):
        result = subprocess.run(
            ["python3", str(RUNNER), "--root", str(self.root), "--job-id", "job-001", *args],
            text=True,
            capture_output=True,
            check=False,
        )
        if check and result.returncode != 0:
            self.fail(f"runner failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        return result

    def _write_fixture(self):
        for rel in [
            "rules",
            "gates",
            "workers",
            "output/job-001/seedance/requests",
            "output/job-001/generation",
            "assets/product",
            "assets/person",
        ]:
            (self.root / rel).mkdir(parents=True, exist_ok=True)

        for rel in ["STATE.md", "QC_RULES.md", "LOOP.md"]:
            (self.root / rel).write_text(f"# {rel}\n", encoding="utf-8")

        (self.root / "assets/source.mp4").write_bytes(b"")
        (self.root / "output/job-001/seedance/requests/request_qc.md").write_text("PASS\n", encoding="utf-8")
        for part in ["part1", "part2"]:
            (self.root / f"output/job-001/seedance/requests/{part}_request_prepared.json").write_text(
                "{}\n",
                encoding="utf-8",
            )

        for rel in [
            "gates/cost_approval_gate.md",
            "gates/generation_gate.md",
            "gates/final_video_gate.md",
            "workers/cost_approval_worker.md",
            "workers/generation_worker.md",
            "workers/final_qc_worker.md",
        ]:
            (self.root / rel).write_text("# contract\n", encoding="utf-8")

        stage_rules = {
            "version": 1,
            "terminal_statuses": ["done", "blocked"],
            "paid_stage_markers": ["generation_approved", "seedance_generating", "paid"],
            "rules": [
                {
                    "id": "seedance_inputs_prepared",
                    "match": {"type": "prefix", "status": "seedance_inputs_prepared"},
                    "decision": "stop",
                    "reason": "Seedance generation requires explicit client approval",
                    "canonical_stage": "generation_approval",
                    "cost_class": "expensive_generation",
                    "worker": "human approval",
                    "worker_file": "workers/cost_approval_worker.md",
                    "action": "Stop before paid generation.",
                    "next_expected": "generation_approved",
                    "gate": "gates/cost_approval_gate.md",
                },
                {
                    "id": "generation_approved",
                    "match": {"type": "exact", "status": "generation_approved"},
                    "decision": "continue",
                    "canonical_stage": "generation",
                    "cost_class": "expensive_generation",
                    "worker": "$video-replication generation",
                    "worker_file": "workers/generation_worker.md",
                    "action": "Submit approved tasks.",
                    "next_expected": "final_qc",
                    "gate": "gates/generation_gate.md",
                },
                {
                    "id": "final_qc",
                    "match": {"type": "prefix", "status": "final_qc"},
                    "decision": "continue",
                    "canonical_stage": "final_qc",
                    "cost_class": "free_check",
                    "worker": "$video-replication final qc",
                    "worker_file": "workers/final_qc_worker.md",
                    "action": "Run final technical QC.",
                    "next_expected": "done",
                    "gate": "gates/final_video_gate.md",
                },
            ],
        }
        (self.root / "rules/STAGE_RULES.json").write_text(
            json.dumps(stage_rules, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        cost_policy = {
            "version": 1,
            "cost_classes": {
                "free_check": {"auto_allowed": True},
                "cheap_quality_work": {"auto_allowed": True, "counter": "gpt_image_runs"},
                "expensive_generation": {
                    "auto_allowed": False,
                    "counter": "seedance_runs",
                    "requires_allow_paid": True,
                    "requires_approval_record": True,
                },
            },
            "budgets": {
                "gpt_image_runs_per_job": {"soft": 8, "hard": 12},
                "seedance_runs_per_approval": {"hard": 1},
                "seedance_targeted_retries_per_failed_output": {"hard": 1},
            },
            "approval": {
                "direct_generation_request_is_approval": True,
                "direct_generation_phrases": ["跑 Seedance", "直接出视频", "生成最终视频"],
                "default_approval_scope": "current_explicit_job",
                "current_job_approval_covers_required_parts_once": True,
                "failed_part_retry_requires_new_approval": True,
                "batch_requires_explicit_batch_scope": True,
            },
        }
        (self.root / "COST_POLICY.md").write_text(
            "# Cost Policy\n\n```json\n"
            + json.dumps(cost_policy, ensure_ascii=False, indent=2)
            + "\n```\n",
            encoding="utf-8",
        )

        with (self.root / "jobs.csv").open("w", newline="", encoding="utf-8") as f:
            fieldnames = [
                "id",
                "status",
                "video_path",
                "product_name",
                "product_assets",
                "person_assets",
                "audio_assets",
                "target_duration",
                "notes",
                "output_dir",
                "last_artifact",
                "next_stage",
                "needs_user_confirmation",
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow(
                {
                    "id": "job-001",
                    "status": "seedance_inputs_prepared",
                    "video_path": str(self.root / "assets/source.mp4"),
                    "product_name": "孔凤春清洁泥膜",
                    "product_assets": str(self.root / "assets/product"),
                    "person_assets": str(self.root / "assets/person"),
                    "audio_assets": "extract_from_original",
                    "target_duration": "30s",
                    "notes": "client_profile=kongfengchun",
                    "output_dir": "output/job-001",
                    "last_artifact": "output/job-001/seedance/requests/request_qc.md",
                    "next_stage": "generation_approved",
                    "needs_user_confirmation": "true",
                }
            )

        (self.root / "RUNNER_STATE.json").write_text(
            json.dumps({"version": 1, "retry_limit": 2, "updated_at": None, "jobs": {}}, indent=2) + "\n",
            encoding="utf-8",
        )

    def test_direct_current_job_approval_covers_required_parts_once(self):
        result = self.run_loop(
            "--allow-paid",
            "--approval-source-message",
            "请直接跑 Seedance 给我视频",
            "--dry-run",
        )
        self.assertIn("Decision: **continue**", result.stdout)
        self.assertIn("Approval scope: `current_job`", result.stdout)
        self.assertIn("Approved task count: `2`", result.stdout)
        self.assertIn("Planned task count: `2`", result.stdout)

    def test_current_job_approval_does_not_approve_batch(self):
        result = self.run_loop(
            "--allow-paid",
            "--approval-source-message",
            "请直接跑 Seedance 给我视频",
            "--generation-intent",
            "batch",
            "--planned-task-count",
            "4",
            "--dry-run",
        )
        self.assertIn("Decision: **stop**", result.stdout)
        self.assertIn("batch generation requires explicit batch/all/named-jobs approval", result.stdout)

    def test_explicit_batch_approval_allows_batch(self):
        result = self.run_loop(
            "--allow-paid",
            "--approval-recorded",
            "--approval-scope",
            "batch",
            "--approval-task-count",
            "4",
            "--planned-task-count",
            "4",
            "--generation-intent",
            "batch",
            "--dry-run",
        )
        self.assertIn("Decision: **continue**", result.stdout)
        self.assertIn("Approval scope: `batch`", result.stdout)
        self.assertIn("Approved task count: `4`", result.stdout)

    def test_failed_part_retry_requires_targeted_approval(self):
        denied = self.run_loop(
            "--allow-paid",
            "--approval-source-message",
            "请直接跑 Seedance 给我视频",
            "--generation-intent",
            "failed_part_retry",
            "--planned-task-count",
            "1",
            "--dry-run",
        )
        self.assertIn("Decision: **stop**", denied.stdout)
        self.assertIn("failed-Part retry requires new targeted approval", denied.stdout)

        allowed = self.run_loop(
            "--allow-paid",
            "--approval-recorded",
            "--approval-scope",
            "targeted_retry",
            "--approval-task-count",
            "1",
            "--planned-task-count",
            "1",
            "--generation-intent",
            "failed_part_retry",
            "--dry-run",
        )
        self.assertIn("Decision: **continue**", allowed.stdout)
        self.assertIn("Approval scope: `targeted_retry`", allowed.stdout)

    def test_second_final_video_retry_is_blocked(self):
        state = json.loads((self.root / "RUNNER_STATE.json").read_text(encoding="utf-8"))
        state["jobs"]["job-001"] = {
            "spent": {
                "gpt_image_runs": 0,
                "seedance_runs": 2,
                "seedance_targeted_retries": 1,
                "final_video_seedance_retries": 1,
            }
        }
        (self.root / "RUNNER_STATE.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

        result = self.run_loop(
            "--allow-paid",
            "--approval-recorded",
            "--approval-scope",
            "targeted_retry",
            "--approval-task-count",
            "1",
            "--planned-task-count",
            "1",
            "--generation-intent",
            "final_video_retry",
            "--dry-run",
        )
        self.assertIn("Decision: **stop**", result.stdout)
        self.assertIn("second paid retry blocked", result.stdout)


if __name__ == "__main__":
    unittest.main()
