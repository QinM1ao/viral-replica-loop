import tempfile
import unittest
from pathlib import Path
import sys
import json
import subprocess
import hashlib


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from job_run import (
    CheckResult,
    StageArtifact,
    StageRequest,
    StageResult,
    _command_executor,
    _initial_stage_from_existing_state,
    run_job,
    run_stage,
)
from run_next_loop_round import advisory_semantic_failures_only


class JobRunTest(unittest.TestCase):
    def test_job_run_continues_across_passing_stages_until_delivery(self):
        calls = []
        next_stages = {
            "source_blueprint": "image_batch",
            "image_batch": "pre_seedance_pack",
            "pre_seedance_pack": "done",
        }

        def execute(request):
            calls.append((request.stage, request.attempt))
            return StageResult.pass_(
                artifact=f"output/job-001/{request.stage}.json",
                next_stage=next_stages[request.stage],
            )

        with tempfile.TemporaryDirectory() as tmp:
            report = run_job(
                root=Path(tmp),
                job_id="job-001",
                initial_stage="source_blueprint",
                execute_stage=execute,
            )

        self.assertEqual(report.status, "DELIVERED", report)
        self.assertEqual(
            calls,
            [
                ("source_blueprint", 1),
                ("image_batch", 1),
                ("pre_seedance_pack", 1),
            ],
        )
        self.assertEqual(report.completed_stages, tuple(next_stages))

    def test_image_semantic_failure_retries_once_then_uses_best_usable_artifact(self):
        calls = []

        def execute(request):
            calls.append((request.stage, request.attempt))
            if request.stage == "image_batch":
                return StageResult(
                    status="FAIL",
                    artifact=f"output/job-001/image-attempt-{request.attempt}.png",
                    next_stage="pre_seedance_pack",
                    usable=True,
                    outcome_type="SEMANTIC_QC",
                    reason="人物神态不够像",
                    retry_scopes=("part1",),
                )
            return StageResult.pass_(
                artifact="output/job-001/pre-seedance-pack.json",
                next_stage="done",
            )

        with tempfile.TemporaryDirectory() as tmp:
            report = run_job(
                root=Path(tmp),
                job_id="job-001",
                initial_stage="image_batch",
                execute_stage=execute,
            )

        self.assertEqual(report.status, "DELIVERED")
        self.assertEqual(
            calls,
            [
                ("image_batch", 1),
                ("image_batch", 2),
                ("pre_seedance_pack", 1),
            ],
        )
        self.assertEqual(report.completed_stages, ("image_batch", "pre_seedance_pack"))
        self.assertEqual(len(report.warnings), 1)
        self.assertIn("人物神态不够像", report.warnings[0])

    def test_video_visual_failure_is_delivered_as_warning_without_retry(self):
        calls = []

        def execute(request):
            calls.append((request.stage, request.attempt))
            if request.stage == "generation":
                return StageResult(
                    status="FAIL",
                    artifact="output/job-001/generation/selected.mp4",
                    next_stage="final_qc",
                    usable=True,
                    outcome_type="VISUAL_DEFECT",
                    reason="表情不够自然，但视频可播放且内容完整",
                )
            return StageResult.pass_(
                artifact="output/job-001/final/final_video.mp4",
                next_stage="done",
            )

        with tempfile.TemporaryDirectory() as tmp:
            report = run_job(
                root=Path(tmp),
                job_id="job-001",
                initial_stage="generation",
                execute_stage=execute,
                approved_paid_stages=("generation",),
            )

        self.assertEqual(report.status, "DELIVERED")
        self.assertEqual(calls, [("generation", 1), ("final_qc", 1)])
        self.assertEqual(len(report.warnings), 1)
        self.assertIn("表情不够自然", report.warnings[0])

    def test_job_run_resumes_from_checkpoint_without_repeating_completed_stage(self):
        calls = []

        def execute(request):
            calls.append((request.stage, request.attempt))
            return StageResult.pass_(
                artifact="output/job-001/image.png",
                next_stage="done",
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint = (
                root
                / "output"
                / "job-001"
                / "checks"
                / "job_run_checkpoint.json"
            )
            checkpoint.parent.mkdir(parents=True)
            source_artifact = root / "output" / "job-001" / "source.json"
            source_artifact.parent.mkdir(parents=True, exist_ok=True)
            source_artifact.write_text("{}", encoding="utf-8")
            checkpoint.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "job_id": "job-001",
                        "current_stage": "image_batch",
                        "completed_stages": ["source_blueprint"],
                        "warnings": [],
                        "artifacts": {
                            "source_blueprint": {
                                "path": "output/job-001/source.json",
                                "sha256": hashlib.sha256(b"{}").hexdigest(),
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = run_job(
                root=root,
                job_id="job-001",
                initial_stage="source_blueprint",
                execute_stage=execute,
            )

        self.assertEqual(report.status, "DELIVERED")
        self.assertEqual(calls, [("image_batch", 1)])
        self.assertEqual(
            report.completed_stages,
            ("source_blueprint", "image_batch"),
        )

    def test_ambiguous_external_submission_stops_without_submitting_again(self):
        calls = []

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint = (
                root
                / "output"
                / "job-001"
                / "checks"
                / "job_run_checkpoint.json"
            )
            checkpoint.parent.mkdir(parents=True)
            checkpoint.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "job_id": "job-001",
                        "current_stage": "generation",
                        "completed_stages": ["pre_seedance_pack"],
                        "warnings": [],
                        "in_flight": {
                            "stage": "generation",
                            "attempt": 1,
                            "idempotency_key": "job-001:generation:1",
                            "external_submission": True,
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = run_job(
                root=root,
                job_id="job-001",
                initial_stage="source_blueprint",
                execute_stage=lambda request: calls.append(request),
            )

        self.assertEqual(report.status, "STOPPED")
        self.assertEqual(report.current_stage, "generation")
        self.assertIn("external submission", report.reason)
        self.assertEqual(calls, [])

    def test_video_generation_waits_for_explicit_paid_approval(self):
        calls = []

        with tempfile.TemporaryDirectory() as tmp:
            report = run_job(
                root=Path(tmp),
                job_id="job-001",
                initial_stage="generation",
                execute_stage=lambda request: calls.append(request),
            )

        self.assertEqual(report.status, "STOPPED")
        self.assertEqual(report.current_stage, "generation")
        self.assertIn("paid approval", report.reason)
        self.assertEqual(calls, [])

    def test_blocked_job_is_terminal_and_never_dispatched_as_a_stage(self):
        calls = []

        with tempfile.TemporaryDirectory() as tmp:
            report = run_job(
                root=Path(tmp),
                job_id="job-001",
                initial_stage="blocked",
                execute_stage=lambda request: calls.append(request),
            )

        self.assertEqual(report.status, "STOPPED")
        self.assertEqual(report.current_stage, "blocked")
        self.assertEqual(calls, [])

    def test_formal_job_authorizes_image_work_and_one_targeted_retry(self):
        authorizations = []

        def execute(request):
            authorizations.append((request.attempt, request.authorization))
            return StageResult(
                status="FAIL",
                artifact=f"output/job-001/image-{request.attempt}.png",
                next_stage="done",
                usable=True,
                outcome_type="SEMANTIC_QC",
                reason="局部细节偏差",
                retry_scopes=("part1",),
            )

        with tempfile.TemporaryDirectory() as tmp:
            report = run_job(
                root=Path(tmp),
                job_id="job-001",
                initial_stage="image_batch",
                execute_stage=execute,
            )

        self.assertEqual(report.status, "DELIVERED")
        self.assertEqual(
            authorizations,
            [(1, "job_image_scope"), (2, "job_image_targeted_retry")],
        )

    def test_stale_or_wrong_job_artifact_is_a_hard_stop_even_if_readable(self):
        def execute(_request):
            return StageResult(
                status="FAIL",
                artifact="output/job-000/image.png",
                next_stage="pre_seedance_pack",
                usable=True,
                outcome_type="BINDING_FAILURE",
                blocker="stale_or_wrong_job_binding",
                reason="artifact belongs to job-000",
            )

        with tempfile.TemporaryDirectory() as tmp:
            report = run_job(
                root=Path(tmp),
                job_id="job-001",
                initial_stage="image_batch",
                execute_stage=execute,
            )

        self.assertEqual(report.status, "STOPPED")
        self.assertEqual(report.current_stage, "image_batch")
        self.assertIn("job-000", report.reason)
        self.assertEqual(report.completed_stages, ())

    def test_run_loop_job_run_cli_drives_the_stage_executor_continuously(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executor = root / "fixture_executor.py"
            executor.write_text(
                "\n".join(
                    [
                        "import json, sys",
                        "from pathlib import Path",
                        "request = json.load(sys.stdin)",
                        "if request['operation'] == 'maker':",
                        "  artifact = 'output/job-001/' + request['stage'] + '.json'",
                        "  path = Path(request['root']) / artifact",
                        "  path.parent.mkdir(parents=True, exist_ok=True)",
                        "  path.write_text('{}')",
                        "  next_stage = {",
                        "    'source_blueprint': 'image_batch',",
                        "    'image_batch': 'done',",
                        "  }[request['stage']]",
                        "  result = {'artifact': artifact, 'next_stage': next_stage, 'usable': True}",
                        "elif request['operation'] == 'deterministic_qc':",
                        "  result = {'passed': True}",
                        "elif request['operation'] == 'risk_ledger':",
                        "  result = {'semantic_review_required': False}",
                        "else:",
                        "  raise AssertionError(request['operation'])",
                        "json.dump(result, sys.stdout)",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            report = run_job(
                root=root,
                job_id="job-001",
                initial_stage="source_blueprint",
                execute_stage=_command_executor(
                    root,
                    f"{sys.executable} {executor}",
                ),
            )

        self.assertEqual(report.status, "DELIVERED", report)
        self.assertEqual(
            report.completed_stages,
            ("source_blueprint", "image_batch"),
        )

    def test_stage_run_skips_semantic_checker_when_risk_ledger_reuses_evidence(self):
        checker_calls = []
        writebacks = []
        request = StageRequest(
            job_id="job-001",
            stage="pre_seedance_pack",
            attempt=1,
            idempotency_key="job-001:pre_seedance_pack:1",
            authorization="free_stage",
        )

        result = run_stage(
            request=request,
            make=lambda _request: StageArtifact(
                artifact="output/job-001/seedance_web_final/manifest.json",
                next_stage="generation",
            ),
            deterministic_check=lambda _artifact: CheckResult.pass_(),
            build_risk_ledger=lambda _artifact: False,
            semantic_check=lambda _artifact: checker_calls.append("called"),
            writeback=writebacks.append,
        )

        self.assertEqual(result.status, "PASS")
        self.assertEqual(checker_calls, [])
        self.assertEqual(writebacks, [result])

    def test_job_run_cli_reconstructs_legacy_start_from_jobs_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prior = root / "output" / "job-001" / "image-qc.json"
            prior.parent.mkdir(parents=True)
            prior.write_text("{}", encoding="utf-8")
            (root / "jobs.csv").write_text(
                "id,status,next_stage,last_artifact\n"
                "job-001,image_qc_passed,pre_seedance_pack,"
                "output/job-001/image-qc.json\n",
                encoding="utf-8",
            )
            rules = root / "rules" / "STAGE_RULES.json"
            rules.parent.mkdir()
            rules.write_text(
                json.dumps(
                    {
                        "terminal_statuses": ["done", "blocked"],
                        "rules": [
                            {
                                "match": {
                                    "type": "exact",
                                    "status": "image_qc_passed",
                                },
                                "canonical_stage": "pre_seedance_pack",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            stage = _initial_stage_from_existing_state(root, "job-001")

        self.assertEqual(stage, "pre_seedance_pack")

    def test_unusable_artifact_records_resumable_hard_stop_not_ambiguous_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = run_job(
                root=root,
                job_id="job-001",
                initial_stage="image_batch",
                execute_stage=lambda _request: StageResult(
                    status="FAIL",
                    artifact="",
                    next_stage="image_batch",
                    usable=False,
                    outcome_type="HARD_FAILURE",
                    reason="image file is unreadable",
                ),
            )
            checkpoint = json.loads(
                report.checkpoint_path.read_text(encoding="utf-8")
            )

        self.assertEqual(report.status, "STOPPED")
        self.assertEqual(report.reason, "image file is unreadable")
        self.assertNotIn("in_flight", checkpoint)
        self.assertEqual(
            checkpoint["last_result"]["blocker"],
            "unusable_artifact",
        )

    def test_stage_run_calls_requested_semantic_checker_once_and_keeps_artifact_usable(self):
        checker_calls = []
        request = StageRequest(
            job_id="job-001",
            stage="image_batch",
            attempt=1,
            idempotency_key="job-001:image_batch:1",
            authorization="job_image_scope",
        )

        def semantic_check(_artifact):
            checker_calls.append("called")
            return CheckResult(passed=False, reason="光线略有偏差")

        result = run_stage(
            request=request,
            make=lambda _request: StageArtifact(
                artifact="output/job-001/image.png",
                next_stage="pre_seedance_pack",
            ),
            deterministic_check=lambda _artifact: CheckResult.pass_(),
            build_risk_ledger=lambda _artifact: True,
            semantic_check=semantic_check,
            writeback=lambda _result: None,
        )

        self.assertEqual(checker_calls, ["called"])
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.outcome_type, "SEMANTIC_QC")
        self.assertTrue(result.usable)

    def test_each_failed_image_part_gets_one_scoped_retry(self):
        calls = []
        writebacks = []

        def execute(request):
            calls.append(
                (
                    request.attempt,
                    request.scope,
                    request.authorization,
                    request.idempotency_key,
                )
            )
            if request.attempt == 1:
                return StageResult(
                    status="FAIL",
                    artifact="output/job-001/image-manifest.json",
                    next_stage="done",
                    usable=True,
                    outcome_type="SEMANTIC_QC",
                    reason="Part1 and Part3 need repair",
                    retry_scopes=("part1", "part3"),
                )
            return StageResult.pass_(
                artifact="output/job-001/image-manifest.json",
                next_stage="done",
            )

        with tempfile.TemporaryDirectory() as tmp:
            report = run_job(
                root=Path(tmp),
                job_id="job-001",
                initial_stage="image_batch",
                execute_stage=execute,
                writeback_stage=lambda request, result: (
                    writebacks.append(
                        (request.stage, request.scope, result.status)
                    )
                    or result.next_stage
                ),
            )

        self.assertEqual(report.status, "DELIVERED")
        self.assertEqual(
            calls,
            [
                (1, "stage", "job_image_scope", "job-001:image_batch:1:stage"),
                (
                    2,
                    "part1",
                    "job_image_targeted_retry",
                    "job-001:image_batch:2:part1",
                ),
                (
                    2,
                    "part3",
                    "job_image_targeted_retry",
                    "job-001:image_batch:2:part3",
                ),
            ],
        )
        self.assertEqual(
            writebacks,
            [("image_batch", "part3", "PASS")],
        )

    def test_completed_legacy_job_is_left_untouched_even_with_initial_stage_argument(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "jobs.csv").write_text(
                "id,status,next_stage,last_artifact\n"
                "job-001,done,done,output/job-001/final.mp4\n",
                encoding="utf-8",
            )
            rules = root / "rules" / "STAGE_RULES.json"
            rules.parent.mkdir()
            rules.write_text(
                json.dumps(
                    {
                        "terminal_statuses": ["done", "blocked"],
                        "rules": [],
                    }
                ),
                encoding="utf-8",
            )
            executor = root / "must_not_run.py"
            executor.write_text(
                "raise SystemExit('executor must not run')\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    "bash",
                    str(REPO_ROOT / "run-loop.sh"),
                    "--job-run",
                    "--root",
                    str(root),
                    "--job-id",
                    "job-001",
                    "--initial-stage",
                    "image_batch",
                    "--executor-command",
                    f"{sys.executable} {executor}",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            checkpoint_exists = (
                root
                / "output"
                / "job-001"
                / "checks"
                / "job_run_checkpoint.json"
            ).exists()

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["status"], "DELIVERED")
        self.assertFalse(checkpoint_exists)

    def test_advisory_override_never_bypasses_deterministic_failure(self):
        semantic_only = {
            "families": {
                "appearance": {
                    "kind": "semantic",
                    "status": "FAIL",
                }
            }
        }
        deterministic_failure = {
            "families": {
                "artifact_binding": {
                    "kind": "deterministic",
                    "status": "FAIL",
                }
            }
        }

        self.assertTrue(advisory_semantic_failures_only(semantic_only))
        self.assertFalse(
            advisory_semantic_failures_only(deterministic_failure)
        )

    def test_job_run_cli_rejects_missing_executor_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executor = root / "missing_artifact.py"
            executor.write_text(
                "\n".join(
                    [
                        "import json, sys",
                        "request = json.load(sys.stdin)",
                        "assert request['operation'] == 'maker'",
                        "json.dump({'artifact': '', 'next_stage': 'done', 'usable': True}, sys.stdout)",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            report = run_job(
                root=root,
                job_id="job-001",
                initial_stage="image_batch",
                execute_stage=_command_executor(
                    root,
                    f"{sys.executable} {executor}",
                ),
            )
            checkpoint = json.loads(
                report.checkpoint_path.read_text(encoding="utf-8")
            )

        self.assertEqual(report.status, "STOPPED")
        self.assertIn("no artifact", report.reason)
        self.assertEqual(
            checkpoint["in_flight"]["idempotency_key"],
            "job-001:image_batch:1:stage",
        )

    def test_unusable_targeted_retry_keeps_original_usable_image(self):
        def execute(request):
            if request.stage == "image_batch" and request.attempt == 1:
                return StageResult(
                    status="FAIL",
                    artifact="output/job-001/original.png",
                    next_stage="pre_seedance_pack",
                    usable=True,
                    outcome_type="SEMANTIC_QC",
                    reason="Part1 expression warning",
                    retry_scopes=("part1",),
                )
            if request.stage == "image_batch":
                return StageResult(
                    status="FAIL",
                    artifact="",
                    next_stage="pre_seedance_pack",
                    usable=False,
                    outcome_type="HARD_FAILURE",
                    reason="retry download failed",
                )
            return StageResult.pass_(
                artifact="output/job-001/pack.json",
                next_stage="done",
            )

        with tempfile.TemporaryDirectory() as tmp:
            report = run_job(
                root=Path(tmp),
                job_id="job-001",
                initial_stage="image_batch",
                execute_stage=execute,
            )

        self.assertEqual(report.status, "DELIVERED")
        self.assertIn("kept the original usable candidate", report.warnings[0])
        self.assertEqual(
            report.completed_stages,
            ("image_batch", "pre_seedance_pack"),
        )

    def test_ambiguous_targeted_retry_stops_with_in_flight_submission_preserved(self):
        def execute(request):
            if request.attempt == 1:
                return StageResult(
                    status="FAIL",
                    artifact="output/job-001/original.png",
                    next_stage="done",
                    usable=True,
                    outcome_type="SEMANTIC_QC",
                    retry_scopes=("part1",),
                )
            return StageResult(
                status="STOP",
                artifact="",
                next_stage="image_batch",
                usable=False,
                outcome_type="HARD_FAILURE",
                blocker="state_conflict",
                reason="provider submission outcome is unknown",
            )

        with tempfile.TemporaryDirectory() as tmp:
            report = run_job(
                root=Path(tmp),
                job_id="job-001",
                initial_stage="image_batch",
                execute_stage=execute,
            )
            checkpoint = json.loads(
                report.checkpoint_path.read_text(encoding="utf-8")
            )

        self.assertEqual(report.status, "STOPPED")
        self.assertEqual(checkpoint["in_flight"]["scope"], "part1")

    def test_definitive_video_failure_consumes_single_attempt_across_resume(self):
        calls = []

        def execute(request):
            calls.append(request)
            return StageResult(
                status="FAIL",
                artifact="",
                next_stage="generation",
                usable=False,
                outcome_type="HARD_FAILURE",
                reason="generated video is unreadable",
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = run_job(
                root=root,
                job_id="job-001",
                initial_stage="generation",
                execute_stage=execute,
                approved_paid_stages=("generation",),
            )
            second = run_job(
                root=root,
                job_id="job-001",
                initial_stage="generation",
                execute_stage=execute,
                approved_paid_stages=("generation",),
            )
            checkpoint = json.loads(
                first.checkpoint_path.read_text(encoding="utf-8")
            )

        self.assertEqual(first.status, "STOPPED")
        self.assertEqual(second.status, "STOPPED")
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            checkpoint["single_attempt_consumed"],
            ["generation"],
        )
        self.assertIn("explicit retake decision", second.reason)

    def test_ambiguous_video_submission_is_consumed_after_reconciliation(self):
        calls = []

        def execute(request):
            calls.append(request)
            return StageResult(
                status="STOP",
                artifact="",
                next_stage="generation",
                usable=False,
                outcome_type="HARD_FAILURE",
                blocker="state_conflict",
                reason="provider submission outcome is unknown",
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = run_job(
                root=root,
                job_id="job-001",
                initial_stage="generation",
                execute_stage=execute,
                approved_paid_stages=("generation",),
            )
            checkpoint = json.loads(
                first.checkpoint_path.read_text(encoding="utf-8")
            )
            self.assertEqual(checkpoint["in_flight"]["stage"], "generation")
            self.assertEqual(
                checkpoint["single_attempt_consumed"],
                ["generation"],
            )
            checkpoint.pop("in_flight")
            first.checkpoint_path.write_text(
                json.dumps(checkpoint),
                encoding="utf-8",
            )
            second = run_job(
                root=root,
                job_id="job-001",
                initial_stage="generation",
                execute_stage=execute,
                approved_paid_stages=("generation",),
            )

        self.assertEqual(first.status, "STOPPED")
        self.assertEqual(second.status, "STOPPED")
        self.assertEqual(len(calls), 1)
        self.assertIn("explicit retake decision", second.reason)

    def test_unbound_image_retry_scope_keeps_usable_candidate_and_continues(self):
        calls = []

        def execute(request):
            calls.append((request.stage, request.attempt))
            if request.stage == "image_batch":
                return StageResult(
                    status="FAIL",
                    artifact="output/job-001/original.png",
                    next_stage="pre_seedance_pack",
                    usable=True,
                    outcome_type="SEMANTIC_QC",
                    reason="局部观感可再优化",
                )
            return StageResult.pass_(
                artifact="output/job-001/pack.json",
                next_stage="done",
            )

        with tempfile.TemporaryDirectory() as tmp:
            report = run_job(
                root=Path(tmp),
                job_id="job-001",
                initial_stage="image_batch",
                execute_stage=execute,
            )

        self.assertEqual(report.status, "DELIVERED")
        self.assertEqual(
            calls,
            [("image_batch", 1), ("pre_seedance_pack", 1)],
        )
        self.assertTrue(
            any(
                "targeted retry was skipped" in warning
                for warning in report.warnings
            )
        )


if __name__ == "__main__":
    unittest.main()
