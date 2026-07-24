import copy
import hashlib
import json
import multiprocessing
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from generation_fanout import (  # noqa: E402
    FanoutError,
    build_plan,
    merge_completions,
    preflight_plan,
    reserve_plan,
    run_reserved_parts,
)
import stage_execution  # noqa: E402


def _failed_process_runner(command, cwd):
    time.sleep(0.15)
    return SimpleNamespace(returncode=4, stdout="", stderr="provider failed")


def _run_reserved_in_process(root, plan, start, results):
    start.wait()
    try:
        report = run_reserved_parts(
            root,
            plan,
            runner=_failed_process_runner,
        )
        results.put(("report", report["overall"]))
    except FanoutError as exc:
        results.put(("error", str(exc)))


class GenerationFanoutTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.job_id = "job-123"
        self.request_dir = self.root / "output" / self.job_id / "seedance" / "requests"
        self.request_dir.mkdir(parents=True)
        self.approval_path = (
            self.root
            / "output"
            / self.job_id
            / "seedance"
            / "generation_approval.md"
        )
        self.requests = []
        for number in (1, 2):
            path = self.request_dir / f"part{number}_request_prepared.json"
            path.write_text(
                json.dumps(
                    {
                        "url": "https://example.invalid/v2/task_create",
                        "body": {"param": json.dumps({"part": number})},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            self.requests.append(
                {"part_id": f"part{number}", "request_path": str(path)}
            )
        self.write_approval(
            self.approval_path,
            scope="current_job",
            requests=self.requests,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def write_approval(
        self,
        path,
        scope,
        requests,
        result="PASS",
        job_id=None,
        generation_intent=None,
    ):
        parts = [item["part_id"] for item in requests]
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if scope == "current_job":
            text = (
                "# Seedance Generation Approval\n\n"
                f"- Job: `{job_id or self.job_id}`\n"
                "- Approval scope: current job only\n"
                f"- Approved task count: {len(parts)}\n"
                f"- Expected Parts: {', '.join(parts)}, once each\n\n"
                "## Approved Request Files\n\n"
                + "".join(
                    f"- `{item['request_path']}`\n" for item in requests
                )
                + "\n## Result\n\n"
                f"`{result}`\n"
            )
        else:
            intent = generation_intent or "failed_part_retry"
            text = (
                "# Targeted Retry Approval\n\n"
                f"- Job: `{job_id or self.job_id}`\n"
                "- Scope: `targeted_retry`\n"
                f"- Generation intent: `{intent}`\n"
                f"- Approved Part: {parts[0]} only\n"
                f"- Approved task count: {len(parts)}\n"
                f"- Request file: `{requests[0]['request_path']}`\n"
                "- Retry limit for this approval: exactly one provider task\n"
                f"- Result: `{result}`\n"
            )
        path.write_text(text, encoding="utf-8")
        return path

    def make_plan(
        self,
        approval_task_count=2,
        requests=None,
        attempt=1,
        approval_record_path=None,
        generation_intent=None,
    ):
        return build_plan(
            self.root,
            self.job_id,
            requests or self.requests,
            approval_task_count=approval_task_count,
            attempt=attempt,
            approval_record_path=approval_record_path,
            generation_intent=generation_intent,
        )

    def make_single_plan(self):
        approval = self.write_approval(
            self.approval_path.with_name("generation_approval_part1.md"),
            scope="current_job",
            requests=self.requests[:1],
        )
        return self.make_plan(
            approval_task_count=1,
            requests=self.requests[:1],
            approval_record_path=approval,
        )

    def write_selected_outputs(self):
        selected_dir = (
            self.root
            / "output"
            / self.job_id
            / "generation"
            / "selected"
        )
        selected_dir.mkdir(parents=True, exist_ok=True)
        outputs = []
        for number in (1, 2):
            path = selected_dir / f"part{number}.mp4"
            path.write_bytes(f"accepted-part-{number}".encode("utf-8"))
            outputs.append(
                {
                    "part_id": f"part{number}",
                    "attempt": 1,
                    "path": str(path.resolve()),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "duration_seconds": 10.0 + number,
                }
            )
        manifest = {
            "schema_version": 1,
            "attempt": 1,
            "approval_claims": {"scope": "current_job"},
            "outputs": outputs,
        }
        path = (
            self.root
            / "output"
            / self.job_id
            / "generation"
            / "selected_outputs.json"
        )
        path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        final_path = (
            self.root
            / "output"
            / self.job_id
            / "final"
            / "final_video.mp4"
        )
        final_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.write_bytes(b"accepted-final-master")
        return path, manifest, final_path

    def make_quality_retake_plan(self):
        selected_path, selected, final_path = self.write_selected_outputs()
        request = self.request_dir / "quality_retake_part1" / "part1_request.json"
        request.parent.mkdir(parents=True, exist_ok=True)
        request.write_text(
            '{"part": 1, "quality_retake": true}\n',
            encoding="utf-8",
        )
        requests = [{"part_id": "part1", "request_path": str(request)}]
        approval = self.write_approval(
            self.approval_path.with_name("quality_retake_part1.md"),
            scope="targeted_retry",
            requests=requests,
            generation_intent="quality_retake",
        )
        plan = self.make_plan(
            approval_task_count=1,
            requests=requests,
            attempt=2,
            approval_record_path=approval,
            generation_intent="quality_retake",
        )
        return plan, selected_path, selected, final_path

    def write_passing_preflight_evidence(self, command):
        request = Path(command[command.index("--request") + 1])
        out_dir = Path(command[command.index("--out-dir") + 1])
        output = Path(command[command.index("--output") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        request_hash = hashlib.sha256(request.read_bytes()).hexdigest()
        for filename in (
            "request_contract.json",
            "reference_audio_preflight.json",
        ):
            (out_dir / filename).write_text(
                json.dumps(
                    {
                        "overall": "PASS",
                        "request_sha256": request_hash,
                    }
                ),
                encoding="utf-8",
            )
        return request, out_dir, output

    def pass_preflight(self, plan, root=None):
        def passing_runner(command, cwd):
            self.write_passing_preflight_evidence(command)
            return SimpleNamespace(returncode=0, stdout="preflight ok", stderr="")

        return preflight_plan(root or self.root, plan, runner=passing_runner)

    def test_plan_binds_prepared_requests_and_isolates_each_part_command(self):
        plan = self.make_plan()

        self.assertEqual(plan["job_id"], self.job_id)
        self.assertEqual(plan["stage"], "generation")
        self.assertEqual(plan["attempt"], 1)
        self.assertEqual(plan["approval_task_count"], 2)
        self.assertEqual(
            plan["approval_record_path"],
            str(self.approval_path.resolve()),
        )
        self.assertEqual(
            plan["approval_record_sha256"],
            hashlib.sha256(self.approval_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(plan["approval_claims"]["scope"], "current_job")
        self.assertEqual([item["part_id"] for item in plan["parts"]], ["part1", "part2"])
        self.assertEqual(
            [packet["packet_id"] for packet in plan["stage_execution"]["packets"]],
            ["part1", "part2"],
        )
        self.assertIn(
            "output/job-123/generation/selected_outputs.json",
            plan["stage_execution"]["coordinator_only_paths"],
        )

        output_paths = set()
        out_dirs = set()
        for item in plan["parts"]:
            request = Path(item["request_path"])
            self.assertEqual(
                item["request_sha256"],
                hashlib.sha256(request.read_bytes()).hexdigest(),
            )
            self.assertEqual(item["attempt"], 1)
            self.assertEqual(
                item["command"][:2],
                ["python3", "tools/seedance_taskcode_runner.py"],
            )
            self.assertNotIn("generation_fanout.py", " ".join(item["command"]))
            out_dirs.add(item["out_dir"])
            output_paths.add(item["output_path"])

        self.assertEqual(len(out_dirs), 2)
        self.assertEqual(len(output_paths), 2)

    def test_plan_rejects_outer_or_part_packet_mutation(self):
        plan = self.make_plan()
        self.assertRegex(plan["plan_sha256"], r"^[0-9a-f]{64}$")

        mutated = copy.deepcopy(plan)
        mutated["parts"][0]["command"].append("--unexpected")
        with self.assertRaisesRegex(FanoutError, "generation plan hash mismatch"):
            preflight_plan(self.root, mutated)

        detached = copy.deepcopy(plan)
        detached["parts"][0]["command"].append("--unexpected")
        unsigned = dict(detached)
        unsigned.pop("plan_sha256")
        detached["plan_sha256"] = hashlib.sha256(
            json.dumps(
                unsigned,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        with self.assertRaisesRegex(
            FanoutError,
            "preflight and paid commands are not correctly sealed",
        ):
            preflight_plan(self.root, detached)

    def test_reservation_requires_current_hash_bound_preflight(self):
        plan = self.make_plan()
        with self.assertRaisesRegex(FanoutError, "preflight report is missing"):
            reserve_plan(self.root, plan)

        self.assertEqual(self.pass_preflight(plan)["overall"], "PASS")
        changed_request = Path(plan["parts"][0]["request_path"])
        changed_request.write_text(
            json.dumps({"url": "https://example.invalid", "body": {"changed": True}}),
            encoding="utf-8",
        )
        changed_approval = self.write_approval(
            self.approval_path.with_name("changed_generation_approval.md"),
            scope="current_job",
            requests=self.requests,
        )
        changed_plan = self.make_plan(
            approval_record_path=changed_approval,
        )
        with self.assertRaisesRegex(FanoutError, "preflight.*plan"):
            reserve_plan(self.root, changed_plan)

    def test_reservation_path_is_canonical_and_cannot_bypass_spent_state(self):
        plan = self.make_single_plan()
        self.assertEqual(self.pass_preflight(plan)["overall"], "PASS")
        alternate = self.root / "alternate-reservation.json"
        with self.assertRaisesRegex(FanoutError, "canonical"):
            reserve_plan(self.root, plan, reservation_path=alternate)
        self.assertFalse(alternate.exists())

        reservation = reserve_plan(self.root, plan)
        self.assertEqual(reservation["parts"][0]["status"], "RESERVED")

        def failed_runner(command, cwd):
            return SimpleNamespace(returncode=4, stdout="", stderr="provider failed")

        self.assertEqual(
            run_reserved_parts(self.root, plan, runner=failed_runner)["overall"],
            "FAIL",
        )
        with self.assertRaisesRegex(FanoutError, "canonical"):
            run_reserved_parts(
                self.root,
                plan,
                reservation_path=alternate,
                runner=failed_runner,
            )
        self.assertFalse(alternate.exists())

    def test_targeted_retry_uses_attempt_two_and_new_canonical_reservation(self):
        plan = self.make_single_plan()
        self.assertEqual(self.pass_preflight(plan)["overall"], "PASS")
        reserve_plan(self.root, plan)

        def failed_runner(command, cwd):
            return SimpleNamespace(returncode=4, stdout="", stderr="provider failed")

        self.assertEqual(
            run_reserved_parts(self.root, plan, runner=failed_runner)["overall"],
            "FAIL",
        )

        retry_request = (
            self.request_dir
            / "retry_part1"
            / "part1_request.json"
        )
        retry_request.parent.mkdir(parents=True)
        retry_request.write_text(
            json.dumps(
                {
                    "url": "https://example.invalid/v2/task_create",
                    "body": {"param": json.dumps({"part": 1, "fixed": True})},
                }
            ),
            encoding="utf-8",
        )
        retry_requests = [
            {"part_id": "part1", "request_path": str(retry_request)}
        ]
        retry_approval = (
            self.root
            / "output"
            / self.job_id
            / "seedance"
            / "retry_approval_part1.md"
        )
        self.write_approval(
            retry_approval,
            scope="targeted_retry",
            requests=retry_requests,
        )
        retry_plan = self.make_plan(
            approval_task_count=1,
            requests=retry_requests,
            attempt=2,
            approval_record_path=retry_approval,
        )
        self.assertEqual(retry_plan["attempt"], 2)
        self.assertIn("/attempt_2/parts/part1/", retry_plan["parts"][0]["output_path"])
        self.assertEqual(retry_plan["approval_claims"]["scope"], "targeted_retry")
        self.assertEqual(self.pass_preflight(retry_plan)["overall"], "PASS")
        retry_reservation = reserve_plan(self.root, retry_plan)
        self.assertEqual(retry_reservation["attempt"], 2)
        retry_reservation_path = (
            self.root
            / "output"
            / self.job_id
            / "generation"
            / "fanout"
            / "reservation_attempt_2.json"
        )
        self.assertTrue(retry_reservation_path.is_file())
        self.assertEqual(
            run_reserved_parts(
                self.root,
                retry_plan,
                runner=failed_runner,
            )["overall"],
            "FAIL",
        )
        completion = json.loads(
            Path(retry_plan["parts"][0]["completion_path"]).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(completion["attempt"], 2)
        self.assertEqual(
            completion["approval_claims"],
            retry_plan["approval_claims"],
        )

        with self.assertRaisesRegex(FanoutError, "attempt must be 1 or 2"):
            self.make_plan(
                approval_task_count=1,
                requests=retry_requests,
                attempt=3,
                approval_record_path=retry_approval,
            )

    def test_quality_retake_plan_binds_current_selected_outputs(self):
        (
            plan,
            selected_path,
            unused_selected,
            final_path,
        ) = self.make_quality_retake_plan()

        self.assertEqual(plan["generation_intent"], "quality_retake")
        self.assertEqual(
            plan["approval_claims"]["generation_intent"],
            "quality_retake",
        )
        self.assertEqual(
            plan["baseline_selected_outputs_path"],
            str(selected_path.resolve()),
        )
        self.assertEqual(
            plan["baseline_selected_outputs_sha256"],
            hashlib.sha256(selected_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            plan["baseline_final_path"],
            str(final_path.resolve()),
        )
        self.assertEqual(
            plan["baseline_final_sha256"],
            hashlib.sha256(final_path.read_bytes()).hexdigest(),
        )

    def test_failed_quality_retake_preserves_selected_outputs(self):
        (
            plan,
            selected_path,
            unused_selected,
            final_path,
        ) = self.make_quality_retake_plan()
        original = selected_path.read_bytes()
        original_final = final_path.read_bytes()
        state_path = self.root / "STATE.md"
        runner_state_path = self.root / "RUNNER_STATE.json"
        state_path.write_text("other task current round\n", encoding="utf-8")
        runner_state_path.write_text(
            '{"active_job": "job-other"}\n',
            encoding="utf-8",
        )
        self.assertEqual(self.pass_preflight(plan)["overall"], "PASS")
        reserve_plan(self.root, plan)

        report = run_reserved_parts(
            self.root,
            plan,
            runner=_failed_process_runner,
        )

        self.assertEqual(report["overall"], "FAIL")
        self.assertEqual(selected_path.read_bytes(), original)
        self.assertEqual(final_path.read_bytes(), original_final)
        self.assertEqual(
            state_path.read_text(encoding="utf-8"),
            "other task current round\n",
        )
        self.assertEqual(
            runner_state_path.read_text(encoding="utf-8"),
            '{"active_job": "job-other"}\n',
        )
        repair_state = json.loads(
            (
                self.root
                / "output"
                / self.job_id
                / "generation"
                / "quality_retake_state.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            repair_state["status"],
            "generation_failed_baseline_active",
        )
        self.assertEqual(repair_state["next_stage"], "STOP")

    def test_quality_retake_merge_replaces_only_target_part(self):
        (
            plan,
            selected_path,
            selected,
            final_path,
        ) = self.make_quality_retake_plan()
        original_final = final_path.read_bytes()
        self.assertEqual(self.pass_preflight(plan)["overall"], "PASS")
        reserve_plan(self.root, plan)

        def passing_runner(command, cwd):
            out_dir = Path(command[command.index("--out-dir") + 1])
            output = Path(command[command.index("--output") + 1])
            out_dir.mkdir(parents=True, exist_ok=True)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"quality-retake-part-1")
            (out_dir / "summary.json").write_text(
                json.dumps(
                    {
                        "status": "succeeded",
                        "video": str(output),
                        "duration_seconds_actual": 11.0,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        self.assertEqual(
            run_reserved_parts(
                self.root,
                plan,
                runner=passing_runner,
            )["overall"],
            "PASS",
        )
        merged = merge_completions(
            self.root,
            plan,
            selected_outputs_path=selected_path,
        )

        by_part = {
            item["part_id"]: item for item in merged["outputs"]
        }
        baseline_by_part = {
            item["part_id"]: item for item in selected["outputs"]
        }
        self.assertEqual(by_part["part1"]["attempt"], 2)
        self.assertNotEqual(
            by_part["part1"]["sha256"],
            baseline_by_part["part1"]["sha256"],
        )
        self.assertEqual(
            by_part["part2"],
            baseline_by_part["part2"],
        )
        self.assertEqual(
            json.loads(selected_path.read_text(encoding="utf-8")),
            merged,
        )
        self.assertEqual(final_path.read_bytes(), original_final)
        repair_state = json.loads(
            (
                self.root
                / "output"
                / self.job_id
                / "generation"
                / "quality_retake_state.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            repair_state["status"],
            "selected_part_replaced",
        )
        self.assertEqual(repair_state["next_stage"], "finishing")

    def test_attempt_two_merge_replaces_failed_part_and_keeps_attempt_one_passes(self):
        plan = self.make_plan()

        def first_attempt_runner(command, cwd):
            out_dir = Path(command[command.index("--out-dir") + 1])
            request = Path(command[command.index("--request") + 1])
            if "--preflight-only" in command:
                out_dir.mkdir(parents=True, exist_ok=True)
                request_hash = hashlib.sha256(request.read_bytes()).hexdigest()
                for filename in (
                    "request_contract.json",
                    "reference_audio_preflight.json",
                ):
                    (out_dir / filename).write_text(
                        json.dumps(
                            {
                                "overall": "PASS",
                                "request_sha256": request_hash,
                            }
                        ),
                        encoding="utf-8",
                    )
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if "part2" in request.name:
                return SimpleNamespace(
                    returncode=4,
                    stdout="",
                    stderr="part2 failed",
                )
            output = Path(command[command.index("--output") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"attempt-1-part1")
            (out_dir / "summary.json").write_text(
                json.dumps(
                    {
                        "status": "succeeded",
                        "video": str(output),
                        "duration_seconds_actual": 12.0,
                    }
                ),
                encoding="utf-8",
            )
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        self.assertEqual(
            preflight_plan(
                self.root,
                plan,
                runner=first_attempt_runner,
            )["overall"],
            "PASS",
        )
        reserve_plan(self.root, plan)
        self.assertEqual(
            run_reserved_parts(
                self.root,
                plan,
                runner=first_attempt_runner,
            )["overall"],
            "FAIL",
        )

        retry_request = self.request_dir / "retry_part2" / "part2_request.json"
        retry_request.parent.mkdir(parents=True)
        retry_request.write_text('{"part": 2, "fixed": true}\n', encoding="utf-8")
        retry_requests = [
            {"part_id": "part2", "request_path": str(retry_request)}
        ]
        retry_approval = self.write_approval(
            self.approval_path.with_name("retry_part2.md"),
            scope="targeted_retry",
            requests=retry_requests,
        )
        retry_plan = self.make_plan(
            approval_task_count=1,
            requests=retry_requests,
            attempt=2,
            approval_record_path=retry_approval,
        )

        def retry_runner(command, cwd):
            out_dir = Path(command[command.index("--out-dir") + 1])
            request = Path(command[command.index("--request") + 1])
            if "--preflight-only" in command:
                out_dir.mkdir(parents=True, exist_ok=True)
                request_hash = hashlib.sha256(request.read_bytes()).hexdigest()
                for filename in (
                    "request_contract.json",
                    "reference_audio_preflight.json",
                ):
                    (out_dir / filename).write_text(
                        json.dumps(
                            {
                                "overall": "PASS",
                                "request_sha256": request_hash,
                            }
                        ),
                        encoding="utf-8",
                    )
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            output = Path(command[command.index("--output") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"attempt-2-part2")
            (out_dir / "summary.json").write_text(
                json.dumps(
                    {
                        "status": "succeeded",
                        "video": str(output),
                        "duration_seconds_actual": 10.5,
                    }
                ),
                encoding="utf-8",
            )
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        self.assertEqual(
            preflight_plan(
                self.root,
                retry_plan,
                runner=retry_runner,
            )["overall"],
            "PASS",
        )
        reserve_plan(self.root, retry_plan)
        self.assertEqual(
            run_reserved_parts(
                self.root,
                retry_plan,
                runner=retry_runner,
            )["overall"],
            "PASS",
        )

        selected = merge_completions(self.root, retry_plan)
        self.assertEqual(
            [item["part_id"] for item in selected["outputs"]],
            ["part1", "part2"],
        )
        self.assertEqual(
            [item["attempt"] for item in selected["outputs"]],
            [1, 2],
        )
        self.assertIn(
            "/fanout/parts/part1/",
            selected["outputs"][0]["path"],
        )
        self.assertIn(
            "/fanout/attempt_2/parts/part2/",
            selected["outputs"][1]["path"],
        )

        Path(selected["outputs"][0]["path"]).write_bytes(b"tampered")
        with self.assertRaisesRegex(FanoutError, "output hash changed"):
            merge_completions(self.root, retry_plan)

    def test_targeted_retry_requires_new_exact_approval_and_failed_attempt_one(self):
        plan = self.make_single_plan()
        self.assertEqual(self.pass_preflight(plan)["overall"], "PASS")
        reserve_plan(self.root, plan)

        retry_request = self.request_dir / "part1_request_retry.json"
        retry_request.write_text('{"fixed": true}\n', encoding="utf-8")
        retry_requests = [
            {"part_id": "part1", "request_path": str(retry_request)}
        ]
        retry_approval = self.write_approval(
            self.approval_path.with_name("retry_part1.md"),
            scope="targeted_retry",
            requests=retry_requests,
        )

        with self.assertRaisesRegex(FanoutError, "previous attempt.*FAIL"):
            self.make_plan(
                approval_task_count=1,
                requests=retry_requests,
                attempt=2,
                approval_record_path=retry_approval,
            )

        def failed_runner(command, cwd):
            return SimpleNamespace(returncode=4, stdout="", stderr="provider failed")

        self.assertEqual(
            run_reserved_parts(
                self.root,
                plan,
                runner=failed_runner,
            )["overall"],
            "FAIL",
        )
        with self.assertRaisesRegex(FanoutError, "targeted_retry"):
            self.make_plan(
                approval_task_count=1,
                requests=retry_requests,
                attempt=2,
                approval_record_path=plan["approval_record_path"],
            )
        self.write_approval(
            plan["approval_record_path"],
            scope="targeted_retry",
            requests=retry_requests,
        )
        with self.assertRaisesRegex(
            FanoutError,
            "new approval record path and hash",
        ):
            self.make_plan(
                approval_task_count=1,
                requests=retry_requests,
                attempt=2,
                approval_record_path=plan["approval_record_path"],
            )

    def test_approval_claims_reject_forged_or_expanded_scope(self):
        forged = self.approval_path.with_name("forged_approval.md")
        valid = self.approval_path.read_text(encoding="utf-8")
        cases = [
            ("Result", valid.replace("`PASS`", "`FAIL`"), "Result must be PASS"),
            (
                "count",
                valid.replace("Approved task count: 2", "Approved task count: 3"),
                "task count",
            ),
            (
                "parts",
                valid.replace("part1, part2", "part1, part3"),
                "approved Parts",
            ),
            (
                "requests",
                valid.replace(
                    self.requests[1]["request_path"],
                    self.requests[0]["request_path"],
                ),
                "request paths",
            ),
            (
                "scope",
                valid.replace("current job only", "targeted_retry"),
                "scope",
            ),
        ]
        for label, text, error in cases:
            with self.subTest(label=label):
                forged.write_text(text, encoding="utf-8")
                with self.assertRaisesRegex(FanoutError, error):
                    self.make_plan(approval_record_path=forged)

    def test_structured_json_approval_claims_are_supported(self):
        approval = self.approval_path.with_suffix(".json")
        approval.write_text(
            json.dumps(
                {
                    "job_id": self.job_id,
                    "scope": "current_job",
                    "approved_task_count": 2,
                    "approved_parts": ["part1", "part2"],
                    "request_paths": [
                        item["request_path"] for item in self.requests
                    ],
                    "result": "PASS",
                }
            ),
            encoding="utf-8",
        )
        plan = self.make_plan(approval_record_path=approval)
        self.assertEqual(plan["approval_claims"]["result"], "PASS")
        self.assertEqual(
            plan["approval_claims"]["approved_parts"],
            ["part1", "part2"],
        )

    def test_cost_policy_canonical_approval_template_is_supported(self):
        approval = self.approval_path.with_name("cost_policy_approval.md")
        approval.write_text(
            (
                "Approved action: approved to submit the exact requests below\n"
                f"Job: {self.job_id}\n"
                "Stage: generation\n"
                "Request files:\n"
                f"- `{self.requests[0]['request_path']}`\n"
                f"- `{self.requests[1]['request_path']}`\n"
                "Number of Seedance tasks: 2\n"
                "Expected Parts: part1, part2\n"
                "Approval scope: current_job\n"
                "Approval source: user explicitly requested generation\n"
                "Timestamp: 2026-07-23T12:00:00+08:00\n"
            ),
            encoding="utf-8",
        )
        plan = self.make_plan(approval_record_path=approval)
        self.assertEqual(plan["approval_claims"]["result"], "PASS")

        approval.write_text(
            approval.read_text(encoding="utf-8").replace(
                "approved to submit",
                "request summary reviewed for",
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(FanoutError, "Result must be PASS"):
            self.make_plan(approval_record_path=approval)

        approval.write_text(
            approval.read_text(encoding="utf-8").replace(
                "request summary reviewed for",
                "not approved to submit",
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(FanoutError, "Result must be PASS"):
            self.make_plan(approval_record_path=approval)

    def test_job014_current_and_fixed_audio_retry_markdown_are_compatible(self):
        compat_root = self.root / "compat"
        compat_job = "job-014"
        requests = []
        request_dir = (
            compat_root
            / "output"
            / compat_job
            / "seedance"
            / "requests"
        )
        request_dir.mkdir(parents=True)
        for number in range(1, 6):
            request = request_dir / f"part{number}_request_prepared.json"
            request.write_text(
                json.dumps({"part": number}),
                encoding="utf-8",
            )
            requests.append((f"part{number}", request))
        approval_dir = request_dir.parent
        approval = approval_dir / "generation_approval.md"
        approval.write_text(
            """# Seedance Generation Approval

- Job: `job-014`
- Stage: `generation_approval`
- Generation type: current-job final-video generation
- Approval scope: current job only
- Approved task count: 5
- Planned task count: 5
- Expected Parts: `part1`, `part2`, `part3`, `part4`, `part5`, once each
- Paid generation: yes
- Batch/all-jobs approval: no
- Failed-Part retry approval: no

## Approved Request Files

- `output/job-014/seedance/requests/part1_request_prepared.json`
- `output/job-014/seedance/requests/part2_request_prepared.json`
- `output/job-014/seedance/requests/part3_request_prepared.json`
- `output/job-014/seedance/requests/part4_request_prepared.json`
- `output/job-014/seedance/requests/part5_request_prepared.json`

## Result

`PASS`
""",
            encoding="utf-8",
        )

        plan = build_plan(
            compat_root,
            compat_job,
            requests,
            approval_task_count=5,
        )
        self.assertEqual(plan["approval_claims"]["scope"], "current_job")
        self.assertEqual(self.pass_preflight(plan, root=compat_root)["overall"], "PASS")
        reserve_plan(compat_root, plan)

        def failed_runner(command, cwd):
            return SimpleNamespace(returncode=4, stdout="", stderr="provider failed")

        self.assertEqual(
            run_reserved_parts(
                compat_root,
                plan,
                runner=failed_runner,
            )["overall"],
            "FAIL",
        )

        retry_request = (
            request_dir
            / "retry_part2_fixed_audio"
            / "part2_request.json"
        )
        retry_request.parent.mkdir(parents=True)
        retry_request.write_text('{"part": 2, "fixed_audio": true}\n', encoding="utf-8")
        retry_approval = (
            approval_dir
            / "generation_retry_part2_fixed_audio_approval.md"
        )
        retry_approval.write_text(
            """# Part2 Fixed-Audio Targeted Retry Approval

- Job: `job-014`
- Scope: `targeted_retry`
- Generation intent: `failed_part_retry`
- Approved Part: Part2 only
- Approved task count: `1`
- Request file: `output/job-014/seedance/requests/retry_part2_fixed_audio/part2_request.json`
- Retry limit for this approval: exactly one provider task
- Result: `PASS`
""",
            encoding="utf-8",
        )
        retry_plan = build_plan(
            compat_root,
            compat_job,
            [("part2", retry_request)],
            approval_task_count=1,
            approval_record_path=retry_approval,
            attempt=2,
        )
        self.assertEqual(
            retry_plan["approval_claims"]["approved_parts"],
            ["part2"],
        )
        self.assertEqual(
            retry_plan["approval_claims"]["request_paths"],
            [str(retry_request.resolve())],
        )

    def test_approval_record_must_exist_and_stay_job_local_and_hash_bound(self):
        self.approval_path.unlink()
        with self.assertRaisesRegex(FanoutError, "approval record not found"):
            self.make_plan()

        outside = self.root / "outside-approval.md"
        outside.write_text("Result: PASS\n", encoding="utf-8")
        with self.assertRaisesRegex(FanoutError, "job-local"):
            build_plan(
                self.root,
                self.job_id,
                self.requests,
                approval_task_count=2,
                approval_record_path=outside,
            )

        self.write_approval(
            self.approval_path,
            scope="current_job",
            requests=self.requests,
        )
        plan = self.make_plan()
        with self.approval_path.open("a", encoding="utf-8") as approval:
            approval.write("\n")
        with self.assertRaisesRegex(FanoutError, "approval record hash changed"):
            preflight_plan(self.root, plan)

    def test_reservation_is_durable_idempotent_and_rejects_changed_or_excess_work(self):
        reservation_path = (
            self.root / "output" / self.job_id / "generation" / "fanout" / "reservation.json"
        )
        plan = self.make_plan()
        self.assertEqual(self.pass_preflight(plan)["overall"], "PASS")
        first = reserve_plan(self.root, plan, reservation_path=reservation_path)
        second = reserve_plan(self.root, plan, reservation_path=reservation_path)

        self.assertEqual(first, second)
        self.assertEqual(json.loads(reservation_path.read_text(encoding="utf-8")), first)
        self.assertEqual(first["approval_task_count"], 2)
        self.assertEqual(
            {item["request_sha256"] for item in first["parts"]},
            {item["request_sha256"] for item in plan["parts"]},
        )
        self.assertTrue(all(item["attempt"] == 1 for item in first["parts"]))

        self.requests[0]["request_path"] = str(
            self.request_dir / "part1_changed_request_prepared.json"
        )
        Path(self.requests[0]["request_path"]).write_text(
            json.dumps({"url": "https://example.invalid", "body": {"changed": True}}),
            encoding="utf-8",
        )
        changed_approval = self.write_approval(
            self.approval_path.with_name("changed_generation_approval.md"),
            scope="current_job",
            requests=self.requests,
        )
        changed_plan = self.make_plan(
            approval_record_path=changed_approval,
        )
        self.assertEqual(self.pass_preflight(changed_plan)["overall"], "PASS")
        with self.assertRaisesRegex(FanoutError, "different generation plan"):
            reserve_plan(self.root, changed_plan, reservation_path=reservation_path)

        with self.assertRaisesRegex(FanoutError, "must equal Part count"):
            self.make_plan(
                approval_task_count=1,
            )

    def test_concurrent_runs_allow_only_one_submission_entry(self):
        plan = self.make_single_plan()
        self.assertEqual(self.pass_preflight(plan)["overall"], "PASS")
        reserve_plan(self.root, plan)
        context = multiprocessing.get_context("fork")
        start = context.Event()
        result_queue = context.Queue()
        processes = [
            context.Process(
                target=_run_reserved_in_process,
                args=(self.root, plan, start, result_queue),
            )
            for unused in range(2)
        ]
        for process in processes:
            process.start()
        start.set()
        for process in processes:
            process.join(timeout=5)
            self.assertEqual(process.exitcode, 0)

        results = [result_queue.get(timeout=2) for unused in range(2)]
        self.assertEqual(
            sum(kind == "report" for kind, value in results),
            1,
        )
        self.assertEqual(
            sum(kind == "error" for kind, value in results),
            1,
        )
        self.assertTrue(
            any(
                kind == "error" and "already spent" in value
                for kind, value in results
            )
        )

    def test_paid_dispatch_uses_sealed_stage_execution_argv(self):
        plan = self.make_single_plan()
        packet = plan["stage_execution"]["packets"][0]
        self.assertEqual(packet["command"], plan["parts"][0]["command"])
        self.assertIn("--require-existing-preflight", packet["command"])
        self.assertNotIn("--preflight-only", packet["command"])
        self.assertIn(
            "--preflight-only",
            plan["parts"][0]["preflight_command"],
        )
        self.assertEqual(self.pass_preflight(plan)["overall"], "PASS")
        reserve_plan(self.root, plan)
        paid_calls = []

        def failed_runner(command, cwd):
            paid_calls.append(list(command))
            return SimpleNamespace(returncode=4, stdout="", stderr="provider failed")

        with mock.patch.object(
            stage_execution,
            "execute_plan",
            wraps=stage_execution.execute_plan,
        ) as execute_plan:
            report = run_reserved_parts(
                self.root,
                plan,
                runner=failed_runner,
            )

        self.assertEqual(report["overall"], "FAIL")
        self.assertEqual(len(paid_calls), 1)
        self.assertEqual(
            paid_calls[0][paid_calls[0].index("--request") + 1],
            plan["parts"][0]["request_path"],
        )
        normalized_call = list(paid_calls[0])
        for flag in ("--out-dir", "--output"):
            normalized_call[
                normalized_call.index(flag) + 1
            ] = packet["command"][packet["command"].index(flag) + 1]
        self.assertEqual(normalized_call, packet["command"])
        execute_plan.assert_called_once()

    def test_preflight_dispatch_uses_sealed_stage_execution_staging(self):
        plan = self.make_plan()
        canonical_requests = {
            item["request_path"] for item in plan["parts"]
        }
        canonical_out_dirs = {
            item["out_dir"] for item in plan["parts"]
        }
        calls = []

        def passing_runner(command, cwd):
            request, out_dir, output = (
                self.write_passing_preflight_evidence(command)
            )
            calls.append(
                {
                    "request": str(request),
                    "out_dir": str(out_dir),
                    "output": str(output),
                }
            )
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with (
            mock.patch.object(
                stage_execution,
                "seal_plan",
                wraps=stage_execution.seal_plan,
            ) as seal_plan,
            mock.patch.object(
                stage_execution,
                "execute_plan",
                wraps=stage_execution.execute_plan,
            ) as execute_plan,
        ):
            report = preflight_plan(
                self.root,
                plan,
                runner=passing_runner,
                max_workers=2,
            )

        self.assertEqual(report["overall"], "PASS")
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            {item["request"] for item in calls},
            canonical_requests,
        )
        self.assertTrue(
            all(item["out_dir"] not in canonical_out_dirs for item in calls)
        )
        self.assertTrue(
            all(
                ".stage-execution-" in item["out_dir"]
                and ".stage-execution-" in item["output"]
                for item in calls
            )
        )
        seal_plan.assert_called_once()
        execute_plan.assert_called_once()
        for part in plan["parts"]:
            self.assertTrue(
                (Path(part["out_dir"]) / "request_contract.json").is_file()
            )
            self.assertTrue(
                (
                    Path(part["out_dir"])
                    / "reference_audio_preflight.json"
                ).is_file()
            )

    def test_preflight_blocks_sibling_staging_pollution(self):
        plan = self.make_plan()
        sibling_poison = (
            Path(plan["parts"][1]["out_dir"]) / "sibling-poison.txt"
        )

        def polluting_runner(command, cwd):
            request, unused_out_dir, unused_output = (
                self.write_passing_preflight_evidence(command)
            )
            if "part1" in request.name:
                sibling_roots = list(
                    Path(cwd).resolve().parent.glob(
                        ".stage-execution-part2-*"
                    )
                )
                target = (
                    sibling_roots[0] / "sibling-poison.txt"
                    if sibling_roots
                    else sibling_poison
                )
                target.write_text("poison\n", encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        report = preflight_plan(
            self.root,
            plan,
            runner=polluting_runner,
            max_workers=2,
        )

        self.assertEqual(report["overall"], "FAIL")
        self.assertEqual(
            [item["status"] for item in report["results"]],
            ["FAIL", "FAIL"],
        )
        self.assertFalse(sibling_poison.exists())
        self.assertTrue(
            all(
                not (
                    Path(part["out_dir"])
                    / "request_contract.json"
                ).exists()
                for part in plan["parts"]
            )
        )

    def test_preflight_blocks_and_restores_out_of_bounds_write(self):
        plan = self.make_single_plan()
        protected = self.root / "jobs.csv"
        protected.write_text("original\n", encoding="utf-8")

        def violating_runner(command, cwd):
            self.write_passing_preflight_evidence(command)
            protected.write_text("mutated\n", encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        report = preflight_plan(
            self.root,
            plan,
            runner=violating_runner,
        )

        self.assertEqual(report["overall"], "FAIL")
        self.assertEqual(
            protected.read_text(encoding="utf-8"),
            "original\n",
        )
        self.assertFalse(
            (
                Path(plan["parts"][0]["out_dir"])
                / "request_contract.json"
            ).exists()
        )
        reservation = (
            self.root
            / "output"
            / self.job_id
            / "generation"
            / "fanout"
            / "reservation.json"
        )
        self.assertFalse(reservation.exists())
        with self.assertRaisesRegex(FanoutError, "preflight.*not PASS"):
            reserve_plan(self.root, plan)
        self.assertFalse(reservation.exists())

    def test_preflight_honors_max_workers(self):
        plan = self.make_plan()
        lock = threading.Lock()
        active = 0
        peak_active = 0

        def passing_runner(command, cwd):
            nonlocal active, peak_active
            with lock:
                active += 1
                peak_active = max(peak_active, active)
            try:
                time.sleep(0.05)
                self.write_passing_preflight_evidence(command)
                return SimpleNamespace(
                    returncode=0,
                    stdout="",
                    stderr="",
                )
            finally:
                with lock:
                    active -= 1

        report = preflight_plan(
            self.root,
            plan,
            runner=passing_runner,
            max_workers=2,
        )

        self.assertEqual(report["overall"], "PASS")
        self.assertEqual(peak_active, 2)

    def test_plan_rejects_request_inside_the_part_write_root(self):
        request = (
            self.root
            / "output"
            / self.job_id
            / "generation"
            / "fanout"
            / "parts"
            / "part1"
            / "prepared_request.json"
        )
        request.parent.mkdir(parents=True, exist_ok=True)
        request.write_text('{"part":1}\n', encoding="utf-8")
        requests = [
            {"part_id": "part1", "request_path": str(request)}
        ]
        approval = self.write_approval(
            self.approval_path.with_name("nested_request_approval.md"),
            scope="current_job",
            requests=requests,
        )

        with self.assertRaisesRegex(
            FanoutError,
            "request cannot be inside.*write root",
        ):
            self.make_plan(
                approval_task_count=1,
                requests=requests,
                approval_record_path=approval,
            )

    def test_plan_rejects_request_inside_another_parts_write_root(self):
        request = (
            self.root
            / "output"
            / self.job_id
            / "generation"
            / "fanout"
            / "parts"
            / "part2"
            / "part1_prepared_request.json"
        )
        request.parent.mkdir(parents=True, exist_ok=True)
        request.write_text('{"part":1}\n', encoding="utf-8")
        requests = [
            {"part_id": "part1", "request_path": str(request)},
            self.requests[1],
        ]
        approval = self.write_approval(
            self.approval_path.with_name("cross_part_request_approval.md"),
            scope="current_job",
            requests=requests,
        )

        with self.assertRaisesRegex(
            FanoutError,
            "request cannot be inside.*write root",
        ):
            self.make_plan(
                requests=requests,
                approval_record_path=approval,
            )

    def test_paid_dispatch_write_set_violation_fails_and_is_removed(self):
        plan = self.make_single_plan()
        self.assertEqual(self.pass_preflight(plan)["overall"], "PASS")
        reserve_plan(self.root, plan)
        forbidden = (
            self.root
            / "output"
            / self.job_id
            / "generation"
            / "outside_packet.txt"
        )

        def violating_runner(command, cwd):
            output = Path(command[command.index("--output") + 1])
            out_dir = Path(command[command.index("--out-dir") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            out_dir.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"video")
            (out_dir / "summary.json").write_text(
                json.dumps(
                    {
                        "status": "succeeded",
                        "video": str(output),
                        "duration_seconds_actual": 1.0,
                    }
                ),
                encoding="utf-8",
            )
            forbidden.write_text("violation\n", encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        report = run_reserved_parts(
            self.root,
            plan,
            runner=violating_runner,
        )

        self.assertEqual(report["overall"], "FAIL")
        self.assertIn("write set", report["results"][0]["error"])
        self.assertFalse(forbidden.exists())

    def test_run_uses_injected_runner_and_spends_each_reservation_once(self):
        plan = self.make_plan()
        reservation_path = (
            self.root / "output" / self.job_id / "generation" / "fanout" / "reservation.json"
        )
        calls = []

        def fake_runner(command, cwd):
            calls.append((list(command), Path(cwd)))
            out_dir = Path(command[command.index("--out-dir") + 1])
            if "--preflight-only" in command:
                out_dir.mkdir(parents=True, exist_ok=True)
                request_path = Path(command[command.index("--request") + 1])
                request_hash = hashlib.sha256(request_path.read_bytes()).hexdigest()
                (out_dir / "request_contract.json").write_text(
                    json.dumps(
                        {
                            "overall": "PASS",
                            "request_sha256": request_hash,
                        }
                    ),
                    encoding="utf-8",
                )
                (out_dir / "reference_audio_preflight.json").write_text(
                    json.dumps(
                        {
                            "overall": "PASS",
                            "request_sha256": request_hash,
                        }
                    ),
                    encoding="utf-8",
                )
                return SimpleNamespace(returncode=0, stdout="preflight ok", stderr="")
            output = Path(command[command.index("--output") + 1])
            out_dir.mkdir(parents=True, exist_ok=True)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"generated-video-" + output.name.encode("utf-8"))
            (out_dir / "summary.json").write_text(
                json.dumps(
                    {
                        "status": "succeeded",
                        "video": str(output),
                        "duration_seconds_actual": 12.5,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")

        preflight = preflight_plan(
            self.root,
            plan,
            runner=fake_runner,
            max_workers=2,
        )
        self.assertEqual(preflight["overall"], "PASS")
        self.assertEqual(preflight["attempt"], 1)
        self.assertEqual(
            preflight["approval_claims"],
            plan["approval_claims"],
        )
        reserve_plan(self.root, plan, reservation_path=reservation_path)
        report = run_reserved_parts(
            self.root,
            plan,
            reservation_path=reservation_path,
            runner=fake_runner,
            max_workers=2,
        )

        self.assertEqual(report["overall"], "PASS")
        self.assertEqual(report["attempt"], 1)
        self.assertEqual(report["approval_claims"], plan["approval_claims"])
        self.assertEqual(len(calls), 4)
        self.assertTrue(
            all(call[0][:2] == ["python3", "tools/seedance_taskcode_runner.py"] for call in calls)
        )
        self.assertEqual(
            sum("--preflight-only" in call[0] for call in calls),
            2,
        )
        self.assertEqual(
            sum("--require-existing-preflight" in call[0] for call in calls),
            2,
        )
        reservation = json.loads(reservation_path.read_text(encoding="utf-8"))
        self.assertEqual(reservation["attempt"], 1)
        self.assertEqual(
            reservation["approval_claims"],
            plan["approval_claims"],
        )
        self.assertTrue(all(item["spent"] is True for item in reservation["parts"]))
        self.assertTrue(all(item["status"] == "PASS" for item in reservation["parts"]))

        with self.assertRaisesRegex(FanoutError, "already spent"):
            run_reserved_parts(
                self.root,
                plan,
                reservation_path=reservation_path,
                runner=fake_runner,
            )
        self.assertEqual(len(calls), 4)

    def test_preflight_failure_leaves_every_reservation_unspent(self):
        plan = self.make_plan()
        reservation_path = (
            self.root / "output" / self.job_id / "generation" / "fanout" / "reservation.json"
        )
        calls = []

        def failed_preflight(command, cwd):
            calls.append(list(command))
            return SimpleNamespace(
                returncode=2,
                stdout="",
                stderr="request contract failed",
            )

        preflight = preflight_plan(
            self.root,
            plan,
            runner=failed_preflight,
            max_workers=2,
        )

        self.assertEqual(preflight["overall"], "FAIL")
        self.assertFalse(reservation_path.exists())
        self.assertEqual(len(calls), 2)
        self.assertTrue(all("--preflight-only" in command for command in calls))

    def test_failed_execution_stays_spent_and_cannot_retry(self):
        plan = self.make_single_plan()
        reservation_path = (
            self.root / "output" / self.job_id / "generation" / "fanout" / "reservation.json"
        )
        def failed_runner(command, cwd):
            out_dir = Path(command[command.index("--out-dir") + 1])
            if "--preflight-only" in command:
                out_dir.mkdir(parents=True, exist_ok=True)
                request_path = Path(command[command.index("--request") + 1])
                request_hash = hashlib.sha256(request_path.read_bytes()).hexdigest()
                (out_dir / "request_contract.json").write_text(
                    json.dumps(
                        {
                            "overall": "PASS",
                            "request_sha256": request_hash,
                        }
                    ),
                    encoding="utf-8",
                )
                (out_dir / "reference_audio_preflight.json").write_text(
                    json.dumps(
                        {
                            "overall": "PASS",
                            "request_sha256": request_hash,
                        }
                    ),
                    encoding="utf-8",
                )
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            return SimpleNamespace(returncode=4, stdout="", stderr="provider failed")

        self.assertEqual(
            preflight_plan(self.root, plan, runner=failed_runner)["overall"],
            "PASS",
        )
        reserve_plan(self.root, plan, reservation_path=reservation_path)
        report = run_reserved_parts(
            self.root,
            plan,
            reservation_path=reservation_path,
            runner=failed_runner,
        )
        self.assertEqual(report["overall"], "FAIL")
        reservation = json.loads(reservation_path.read_text(encoding="utf-8"))
        self.assertTrue(reservation["parts"][0]["spent"])
        self.assertEqual(reservation["parts"][0]["status"], "FAIL")

        with self.assertRaisesRegex(FanoutError, "already spent"):
            run_reserved_parts(
                self.root,
                plan,
                reservation_path=reservation_path,
                runner=failed_runner,
            )

    def test_merge_returns_selected_outputs_without_writing_shared_manifest(self):
        plan = self.make_plan()
        reservation_path = (
            self.root / "output" / self.job_id / "generation" / "fanout" / "reservation.json"
        )
        def fake_runner(command, cwd):
            out_dir = Path(command[command.index("--out-dir") + 1])
            if "--preflight-only" in command:
                out_dir.mkdir(parents=True, exist_ok=True)
                request_path = Path(command[command.index("--request") + 1])
                request_hash = hashlib.sha256(request_path.read_bytes()).hexdigest()
                (out_dir / "request_contract.json").write_text(
                    json.dumps(
                        {
                            "overall": "PASS",
                            "request_sha256": request_hash,
                        }
                    ),
                    encoding="utf-8",
                )
                (out_dir / "reference_audio_preflight.json").write_text(
                    json.dumps(
                        {
                            "overall": "PASS",
                            "request_sha256": request_hash,
                        }
                    ),
                    encoding="utf-8",
                )
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            output = Path(command[command.index("--output") + 1])
            out_dir.mkdir(parents=True, exist_ok=True)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"video-" + output.name.encode("utf-8"))
            (out_dir / "summary.json").write_text(
                json.dumps(
                    {
                        "status": "succeeded",
                        "video": str(output),
                        "duration_seconds_actual": 14.9,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        self.assertEqual(
            preflight_plan(self.root, plan, runner=fake_runner)["overall"],
            "PASS",
        )
        reserve_plan(self.root, plan, reservation_path=reservation_path)
        run_reserved_parts(
            self.root,
            plan,
            reservation_path=reservation_path,
            runner=fake_runner,
        )
        selected = merge_completions(self.root, plan)

        self.assertEqual(selected["schema_version"], 1)
        self.assertEqual(
            [item["part_id"] for item in selected["outputs"]],
            ["part1", "part2"],
        )
        for item in selected["outputs"]:
            self.assertTrue(Path(item["path"]).is_absolute())
            self.assertEqual(
                item["sha256"],
                hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest(),
            )
            self.assertEqual(item["duration_seconds"], 14.9)
        self.assertFalse(
            (
                self.root
                / "output"
                / self.job_id
                / "generation"
                / "selected_outputs.json"
            ).exists()
        )

        first_summary = Path(plan["parts"][0]["summary_path"])
        summary = json.loads(first_summary.read_text(encoding="utf-8"))
        summary["status"] = "failed"
        first_summary.write_text(json.dumps(summary), encoding="utf-8")
        with self.assertRaisesRegex(FanoutError, "summary is not PASS"):
            merge_completions(self.root, plan)

    def test_generation_stage_contract_uses_reservation_and_part_fanout(self):
        rules = json.loads(
            (REPO_ROOT / "rules/STAGE_RULES.json").read_text(encoding="utf-8")
        )
        rule = next(item for item in rules["rules"] if item["id"] == "generation_approved")

        self.assertIn("tools/generation_fanout.py", rule["action"])
        self.assertIn("durable reservation", rule["action"])
        self.assertIn("no automatic retry", rule["action"])
        worker = (REPO_ROOT / rule["worker_file"]).read_text(encoding="utf-8")
        self.assertLess(
            worker.index("tools/generation_fanout.py preflight"),
            worker.index("tools/generation_fanout.py reserve"),
        )
        self.assertIn("tools/generation_fanout.py reserve", worker)
        self.assertIn("Only the coordinator may write", worker)


if __name__ == "__main__":
    unittest.main()
