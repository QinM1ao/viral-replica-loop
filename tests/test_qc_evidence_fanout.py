import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "qc_evidence_fanout.py"
sys.path.insert(0, str(REPO_ROOT / "tools"))

import qc_evidence_fanout  # noqa: E402
from qc_evidence_fanout import (  # noqa: E402
    MAX_WORKERS,
    build_plan,
    coordinate_ledger,
    run_bundle,
)
from qc_risk_ledger import evaluate_risk_families  # noqa: E402


class QCEvidenceFanoutTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.job_id = "job-001"
        self.stage = "pre_seedance_pack"

    def tearDown(self):
        self.tmp.cleanup()

    def task(self, name="prompt_contract"):
        report_path = (
            f"output/{self.job_id}/checks/evidence/{self.stage}/{name}.json"
        )
        return {
            "name": name,
            "kind": "deterministic",
            "command": [
                "python3",
                f"tools/{name}_qc.py",
                "--out",
                report_path,
            ],
            "report_path": report_path,
        }

    def test_build_plan_preserves_order_and_derives_isolated_outputs(self):
        plan = build_plan(
            self.root,
            self.job_id,
            self.stage,
            [self.task("prompt_contract"), self.task("audio_duration")],
        )

        self.assertEqual(
            [item["name"] for item in plan["tasks"]],
            ["prompt_contract", "audio_duration"],
        )
        self.assertEqual(plan["policy"], "deterministic_evidence_only")
        self.assertEqual(
            plan["bundle_path"],
            (
                f"output/{self.job_id}/checks/evidence/{self.stage}/"
                "evidence_bundle.json"
            ),
        )
        self.assertEqual(
            plan["tasks"][0]["result_path"],
            (
                f"output/{self.job_id}/checks/evidence/{self.stage}/"
                "prompt_contract.result.json"
            ),
        )
        self.assertNotIn("semantic_review_request", plan)
        self.assertEqual(
            [packet["packet_id"] for packet in plan["stage_execution"]["packets"]],
            ["prompt_contract", "audio_duration"],
        )
        self.assertTrue(plan["plan_sha256"])
        self.assertIn(
            plan["bundle_path"],
            plan["stage_execution"]["coordinator_only_paths"],
        )

    def test_build_plan_requires_a_nonempty_command_list_of_strings(self):
        invalid_commands = [
            "python3 tools/prompt_qc.py",
            [],
            ["python3", ""],
            ["python3", 7],
        ]

        for command in invalid_commands:
            with self.subTest(command=command):
                task = self.task()
                task["command"] = command
                with self.assertRaisesRegex(
                    ValueError,
                    "command must be a nonempty list of nonempty strings",
                ):
                    build_plan(self.root, self.job_id, self.stage, [task])

    def test_build_plan_rejects_semantic_families(self):
        task = self.task()
        task["kind"] = "semantic"

        with self.assertRaisesRegex(
            ValueError,
            "semantic families are not allowed",
        ):
            build_plan(self.root, self.job_id, self.stage, [task])

    def test_build_plan_limits_reports_to_the_stage_evidence_directory(self):
        invalid_paths = [
            f"output/{self.job_id}/checks/prompt_contract.json",
            f"output/{self.job_id}/checks/evidence/other-stage/prompt_contract.json",
            f"output/{self.job_id}/checks/evidence/{self.stage}/../outside.json",
            str(
                self.root
                / f"output/{self.job_id}/checks/evidence/{self.stage}/absolute.json"
            ),
        ]

        for report_path in invalid_paths:
            with self.subTest(report_path=report_path):
                task = self.task()
                task["report_path"] = report_path
                with self.assertRaisesRegex(
                    ValueError,
                    "report_path must be inside",
                ):
                    build_plan(self.root, self.job_id, self.stage, [task])

    def test_build_plan_rejects_duplicate_names_reports_and_commands(self):
        duplicate_cases = [
            [self.task("same"), self.task("same")],
            [
                self.task("first"),
                {
                    **self.task("second"),
                    "report_path": self.task("first")["report_path"],
                },
            ],
            [
                self.task("first"),
                {
                    **self.task("second"),
                    "command": list(self.task("first")["command"]),
                },
            ],
            [
                self.task("first"),
                {
                    **self.task("second"),
                    "report_path": (
                        f"output/{self.job_id}/checks/evidence/{self.stage}/"
                        "nested/../first.json"
                    ),
                },
            ],
        ]

        for tasks in duplicate_cases:
            with self.subTest(tasks=tasks):
                with self.assertRaisesRegex(ValueError, "duplicate"):
                    build_plan(self.root, self.job_id, self.stage, tasks)

    def test_build_plan_rejects_a_report_that_collides_with_another_task_result(self):
        first = self.task("first")
        second = self.task("second")
        second["report_path"] = (
            f"output/{self.job_id}/checks/evidence/{self.stage}/first.result.json"
        )

        with self.assertRaisesRegex(ValueError, "independent"):
            build_plan(self.root, self.job_id, self.stage, [first, second])

    def test_run_bundle_is_parallel_but_preserves_task_order_and_statuses(self):
        tasks = [
            self.task("slow_pass"),
            self.task("fast_fail"),
            self.task("middle_stop"),
        ]
        plan = build_plan(self.root, self.job_id, self.stage, tasks)
        barrier = threading.Barrier(3, timeout=2)
        thread_ids = set()
        lock = threading.Lock()
        statuses = {
            "slow_pass": "PASS",
            "fast_fail": "FAIL",
            "middle_stop": "STOP",
        }
        delays = {"slow_pass": 0.03, "fast_fail": 0.0, "middle_stop": 0.01}

        def fake_runner(command, **kwargs):
            name = Path(command[1]).stem.replace("_qc", "")
            with lock:
                thread_ids.add(threading.get_ident())
            barrier.wait()
            time.sleep(delays[name])
            report_path = Path(command[command.index("--out") + 1])
            if not report_path.is_absolute():
                report_path = self.root / report_path
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps({"overall": statuses[name]}) + "\n",
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(
                command,
                0 if statuses[name] == "PASS" else 1,
                stdout=f"{name} stdout\n",
                stderr=f"{name} stderr\n",
            )

        bundle = run_bundle(
            self.root,
            plan,
            max_workers=3,
            runner=fake_runner,
        )

        self.assertEqual(len(thread_ids), 3)
        self.assertEqual(bundle["overall"], "FAIL")
        self.assertEqual(
            [
                (item["name"], item["evidence"][0]["status"])
                for item in bundle["families"]
            ],
            [
                ("slow_pass", "PASS"),
                ("fast_fail", "FAIL"),
                ("middle_stop", "STOP"),
            ],
        )
        self.assertNotIn("semantic_review_request", bundle)
        self.assertNotIn("qc_risk_ledger_state", json.dumps(bundle))
        for family in bundle["families"]:
            item = family["evidence"][0]
            if item["status"] == "PASS":
                self.assertTrue((self.root / item["stdout_log"]).is_file())
                self.assertTrue((self.root / item["stderr_log"]).is_file())
                self.assertTrue((self.root / item["result_path"]).is_file())
                self.assertTrue((self.root / item["path"]).is_file())
            else:
                self.assertFalse((self.root / item["stdout_log"]).exists())
                self.assertFalse((self.root / item["stderr_log"]).exists())
                self.assertFalse((self.root / item["result_path"]).exists())
                self.assertFalse((self.root / item["path"]).exists())
            self.assertTrue(
                (
                    self.root
                    / plan["stage_execution"]["packets"][
                        [task["name"] for task in plan["tasks"]].index(
                            family["name"]
                        )
                    ]["completion_path"]
                ).is_file()
            )
            completion = json.loads(
                (
                    self.root
                    / plan["stage_execution"]["packets"][
                        [task["name"] for task in plan["tasks"]].index(
                            family["name"]
                        )
                    ]["completion_path"]
                ).read_text(encoding="utf-8")
            )
            for binding in completion["outputs"]:
                output = self.root / binding["path"]
                self.assertEqual(
                    binding["sha256"],
                    qc_evidence_fanout.sha256_file(output),
                )
        self.assertTrue((self.root / plan["bundle_path"]).is_file())

        ledger = evaluate_risk_families(
            self.job_id,
            self.stage,
            bundle["families"],
        )
        self.assertEqual(ledger["overall"], "FAIL")
        self.assertFalse(ledger["semantic_review_request"]["required"])

    def test_run_bundle_caps_the_thread_pool(self):
        tasks = [self.task(f"check_{index}") for index in range(MAX_WORKERS + 3)]
        plan = build_plan(self.root, self.job_id, self.stage, tasks)
        active = 0
        peak = 0
        lock = threading.Lock()

        def fake_runner(command, **kwargs):
            nonlocal active, peak
            name = Path(command[1]).stem.replace("_qc", "")
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with lock:
                active -= 1
            report_path = Path(command[command.index("--out") + 1])
            if not report_path.is_absolute():
                report_path = self.root / report_path
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text('{"overall":"PASS"}\n', encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        bundle = run_bundle(
            self.root,
            plan,
            max_workers=MAX_WORKERS + 100,
            runner=fake_runner,
        )

        self.assertEqual(bundle["overall"], "PASS")
        self.assertLessEqual(peak, MAX_WORKERS)
        self.assertGreater(peak, 1)
        self.assertEqual(bundle["max_workers"], MAX_WORKERS)

    def test_run_bundle_does_not_reuse_a_stale_report(self):
        task = self.task("stale")
        stale = self.root / task["report_path"]
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_text('{"overall":"PASS"}\n', encoding="utf-8")
        plan = build_plan(self.root, self.job_id, self.stage, [task])

        def no_report_runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        bundle = run_bundle(self.root, plan, runner=no_report_runner)

        evidence = bundle["families"][0]["evidence"][0]
        self.assertEqual(bundle["overall"], "STOP")
        self.assertEqual(evidence["status"], "STOP")
        self.assertTrue(stale.exists())
        self.assertIn("report unavailable", evidence["reason"])

    def test_run_bundle_rejects_outer_task_mutation(self):
        plan = build_plan(
            self.root,
            self.job_id,
            self.stage,
            [self.task("prompt_contract")],
        )
        plan["tasks"][0]["command"].append("--unexpected")

        with self.assertRaisesRegex(ValueError, "QC evidence plan hash mismatch"):
            run_bundle(self.root, plan)

    def test_run_bundle_cross_binds_outer_tasks_to_sealed_packets(self):
        plan = build_plan(
            self.root,
            self.job_id,
            self.stage,
            [self.task("prompt_contract")],
        )
        plan["tasks"][0]["command"].append("--unexpected")
        plan.pop("plan_sha256")
        plan["plan_sha256"] = (
            qc_evidence_fanout.stage_execution.stable_hash(plan)
        )

        with self.assertRaisesRegex(
            ValueError,
            "tasks do not match sealed stage_execution packets",
        ):
            run_bundle(self.root, plan)

    def test_write_set_violation_overrides_qc_family_and_ledger_status(self):
        task = self.task("prompt_contract")
        plan = build_plan(
            self.root,
            self.job_id,
            self.stage,
            [task],
        )
        rogue = self.root / "output/job-999/canonical.json"

        def violating_runner(command, **kwargs):
            report = Path(command[-1])
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text('{"overall":"PASS"}\n', encoding="utf-8")
            rogue.parent.mkdir(parents=True, exist_ok=True)
            rogue.write_text('{"forbidden":true}\n', encoding="utf-8")
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="",
                stderr="",
            )

        bundle = run_bundle(
            self.root,
            plan,
            runner=violating_runner,
        )
        ledger = coordinate_ledger(self.root, bundle)

        self.assertEqual(bundle["overall"], "FAIL")
        evidence = bundle["families"][0]["evidence"][0]
        self.assertEqual(evidence["status"], "FAIL")
        self.assertIn(
            "packet filesystem policy blocked os.mkdir",
            evidence["reason"],
        )
        self.assertIn(
            "output/job-999",
            evidence["reason"],
        )
        self.assertEqual(ledger["overall"], "FAIL")
        self.assertEqual(
            ledger["families"]["prompt_contract"]["status"],
            "FAIL",
        )
        self.assertFalse(rogue.exists())

    def test_one_coordinator_combines_evidence_and_emits_one_semantic_request(self):
        bundle = {
            "version": 1,
            "job_id": self.job_id,
            "stage": self.stage,
            "policy": "deterministic_evidence_only",
            "families": [
                {
                    "name": "prompt_contract",
                    "kind": "deterministic",
                    "fingerprint": {"prompt": "current"},
                    "evidence": [
                        {
                            "name": "prompt_contract",
                            "status": "PASS",
                            "path": "output/job-001/checks/evidence/pre_seedance_pack/prompt.json",
                        }
                    ],
                }
            ],
        }
        ledger = coordinate_ledger(
            self.root,
            bundle,
            semantic_families=[
                {
                    "name": "source_to_generation_fidelity",
                    "kind": "semantic",
                    "fingerprint": {"director_plan": "current"},
                    "reuse_evidence_valid": False,
                },
                {
                    "name": "visual_integrity",
                    "kind": "semantic",
                    "fingerprint": {"images": "current"},
                    "reuse_evidence_valid": False,
                },
            ],
            write=True,
        )

        self.assertEqual(ledger["families"]["prompt_contract"]["status"], "PASS")
        request = ledger["semantic_review_request"]
        self.assertTrue(request["required"])
        self.assertEqual(request["invocation_count"], 1)
        self.assertEqual(
            [item["name"] for item in request["families"]],
            ["source_to_generation_fidelity", "visual_integrity"],
        )
        checks = self.root / "output" / self.job_id / "checks"
        self.assertTrue((checks / f"{self.stage}_qc_risk_ledger.json").is_file())
        self.assertTrue((checks / "qc_risk_ledger_state.json").is_file())
        self.assertTrue(
            (checks / f"{self.stage}_semantic_review_request.json").is_file()
        )

    def test_dry_plan_cli_validates_without_writing_evidence(self):
        spec = {
            "job_id": self.job_id,
            "stage": self.stage,
            "tasks": [self.task("prompt_contract")],
        }
        spec_path = self.root / "fanout_spec.json"
        spec_path.write_text(json.dumps(spec), encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--root",
                str(self.root),
                "--spec",
                str(spec_path),
                "--dry-plan",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["job_id"], self.job_id)
        self.assertEqual(plan["stage"], self.stage)
        self.assertEqual(plan["tasks"][0]["kind"], "deterministic")
        self.assertFalse((self.root / plan["evidence_dir"]).exists())


if __name__ == "__main__":
    unittest.main()
