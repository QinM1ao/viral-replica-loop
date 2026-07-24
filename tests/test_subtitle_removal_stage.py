import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import run_next_loop_round
import subtitle_workflow_qc
from qc_risk_ledger import build_stage_ledger


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SubtitleRemovalStageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("ffmpeg"):
            raise unittest.SkipTest("ffmpeg is required for subtitle workflow media checks")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "fixture.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=16x16:d=0.5",
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=r=8000:cl=mono",
                    "-t",
                    "0.5",
                    "-c:v",
                    "mpeg4",
                    "-c:a",
                    "aac",
                    "-shortest",
                    str(path),
                ],
                check=True,
            )
            cls.video_bytes = path.read_bytes()
            frame = Path(temporary) / "frame.jpg"
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-loglevel",
                    "error",
                    "-ss",
                    "0",
                    "-i",
                    str(path),
                    "-frames:v",
                    "1",
                    str(frame),
                ],
                check=True,
            )
            cls.frame_bytes = frame.read_bytes()

    def setUp(self):
        rules = json.loads((REPO_ROOT / "rules" / "STAGE_RULES.json").read_text(encoding="utf-8"))
        self.rules = {item["id"]: item for item in rules["rules"]}

    def write_detection(self, root, classification):
        output = root / "output" / "job-001"
        final_dir = output / "final"
        repair_dir = output / "subtitle_removal"
        evidence_dir = repair_dir / "subtitle_detection_evidence"
        evidence_dir.mkdir(parents=True)
        final_dir.mkdir(parents=True)
        video = final_dir / "final_video.mp4"
        frame_start = evidence_dir / "master_0000.jpg"
        frame_end = evidence_dir / "master_0005.jpg"
        video.write_bytes(self.video_bytes)
        frame_start.write_bytes(self.frame_bytes)
        frame_end.write_bytes(self.frame_bytes)
        intervals = [{"start": 0.1, "end": 0.4}] if classification == "burned_in" else []
        report = {
            "schema_version": 2,
            "overall": "PASS",
            "finishing_master": str(video.resolve()),
            "finishing_master_sha256": sha256(video),
            "duration_seconds": 0.5,
            "classification": classification,
            "subtitle_intervals": intervals,
            "evidence_frames": [
                {
                    "path": str(frame_start.resolve()),
                    "sha256": sha256(frame_start),
                    "timestamp_seconds": 0.0,
                },
                {
                    "path": str(frame_end.resolve()),
                    "sha256": sha256(frame_end),
                    "timestamp_seconds": 0.4,
                },
            ],
        }
        report_path = repair_dir / "subtitle_detection.json"
        report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
        return report_path

    def write_removal_report(
        self, root, detection_path, *, action, paid_tasks, attempt_number=1
    ):
        output = root / "output" / "job-001"
        final_dir = output / "final"
        repair_dir = output / "subtitle_removal"
        final_dir.mkdir(parents=True, exist_ok=True)
        repair_dir.mkdir(parents=True, exist_ok=True)
        source = final_dir / "final_video.mp4"
        if not source.is_file():
            source.write_bytes(self.video_bytes)
        if action == "skipped_clean":
            result = source
            qc_path = None
        else:
            result = final_dir / "final_video_no_subtitles.mp4"
            result.write_bytes(self.video_bytes)
            evidence_dir = repair_dir / "visual_qc_evidence"
            evidence_dir.mkdir()
            high_risk_windows = []
            for window_index, (start, end) in enumerate(
                ((0.1, 0.2), (0.3, 0.4)),
                start=1,
            ):
                frame_evidence = []
                for frame_index, timestamp in enumerate((start, end), start=1):
                    frame = evidence_dir / f"window{window_index}_{frame_index}.jpg"
                    frame.write_bytes(self.frame_bytes)
                    frame_evidence.append(
                        {
                            "path": str(frame.resolve()),
                            "sha256": sha256(frame),
                            "timestamp_seconds": timestamp,
                        }
                    )
                high_risk_windows.append(
                    {
                        "start": start,
                        "end": end,
                        "frame_evidence": frame_evidence,
                    }
                )
            qc = {
                "overall": "PASS",
                "source_sha256": sha256(source),
                "output_sha256": sha256(result),
                "decode_passed": True,
                "required_audio_preserved": True,
                "subtitles_absent": True,
                "valid_scene_text_preserved": True,
                "foreground_subjects_undamaged": True,
                "temporally_stable": True,
                "subtitle_intervals_reviewed": [{"start": 0.1, "end": 0.4}],
                "high_risk_windows": high_risk_windows,
            }
            qc_path = repair_dir / "visual_qc.json"
            qc_path.write_text(json.dumps(qc) + "\n", encoding="utf-8")
        report = {
            "schema_version": 1,
            "overall": "PASS",
            "detection_report": str(detection_path.resolve()),
            "detection_sha256": sha256(detection_path),
            "source_video": str(source.resolve()),
            "source_sha256": sha256(source),
            "action": action,
            "paid_tasks_submitted": paid_tasks,
            "task_id": "amk-tool-123" if paid_tasks else None,
            "output_video": str(result.resolve()),
            "output_sha256": sha256(result),
            "visual_qc_report": str(qc_path.resolve()) if qc_path else None,
            "standing_approval": (
                "workflow_generated_hard_subtitle_v1" if paid_tasks else None
            ),
            "automatic_retry_allowed": False,
            "final_subtitle_streams": 0,
            "attempt_number": attempt_number if paid_tasks else None,
            "retry_approval": (
                "explicit_user_targeted_retry"
                if paid_tasks and attempt_number > 1
                else None
            ),
        }
        if paid_tasks:
            attempt = {
                "schema_version": 1,
                "attempt_number": 1,
                "standing_approval": "workflow_generated_hard_subtitle_v1",
                "source_video": str(source.resolve()),
                "source_sha256": sha256(source),
                "task_id": "amk-tool-123",
                "status": "completed",
            }
            attempt_path = repair_dir / (
                "paid_attempt.json"
                if attempt_number == 1
                else f"paid_attempt_{attempt_number}.json"
            )
            attempt["attempt_number"] = attempt_number
            attempt_path.write_text(json.dumps(attempt) + "\n", encoding="utf-8")
            report["paid_attempt_record"] = str(attempt_path.resolve())
            report["paid_attempt_sha256"] = sha256(attempt_path)
        report_path = repair_dir / "subtitle_removal_report.json"
        report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
        return report_path

    def write_bound_checker(self, root, stage, request):
        checks = root / "output" / "job-001" / "checks"
        request_path = checks / f"{stage}_semantic_review_request.json"
        checker_qc = checks / f"{stage}_gate_review_qc.json"
        family_fingerprints = {
            family["name"]: family["fingerprint_hash"]
            for family in request["families"]
        }
        checker_qc.write_text(
            json.dumps(
                {
                    "overall": "PASS",
                    "fields": {"Job": "job-001", "Stage": stage},
                    "checks": [
                        {"name": "qc_risk_request_binding", "status": "PASS"}
                    ],
                    "qc_risk_review": {
                        "request_id": request["request_id"],
                        "request_path": str(request_path.resolve()),
                        "request_sha256": sha256(request_path),
                        "family_fingerprints": family_fingerprints,
                        "family_results": {
                            name: "PASS" for name in family_fingerprints
                        },
                        "invocation_count": 1,
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return checker_qc

    def test_finishing_advances_through_conditional_subtitle_stage(self):
        self.assertEqual(self.rules["finishing"]["next_expected"], "subtitle_removal")
        stage = self.rules["subtitle_removal"]
        self.assertEqual(stage["canonical_stage"], "subtitle_removal")
        self.assertEqual(stage["cost_class"], "conditional_paid_repair")
        self.assertEqual(stage["next_expected"], "final_qc")
        self.assertTrue((REPO_ROOT / stage["worker_file"]).is_file())
        self.assertTrue((REPO_ROOT / stage["gate"]).is_file())
        cost_policy = (REPO_ROOT / "COST_POLICY.md").read_text(encoding="utf-8")
        self.assertIn('"conditional_paid_repair"', cost_policy)
        self.assertIn('"requires_detection_evidence": true', cost_policy)

    def test_subtitle_stage_stays_inside_user_visible_delivery_stage(self):
        stage = run_next_loop_round.user_visible_stage(
            "subtitle_removal", "subtitle_removal", "final_qc"
        )
        self.assertEqual(stage["index"], 5)
        self.assertEqual(stage["label"], "质检交付")

    def test_second_automatic_mediakit_attempt_is_blocked_by_runner_state(self):
        policy = {
            "cost_classes": {
                "conditional_paid_repair": {
                    "max_tasks_per_job": 1,
                }
            },
            "budgets": {},
        }
        reason, state = run_next_loop_round.cost_stop_reason(
            "subtitle_removal",
            "final_qc",
            {"cost_class": "conditional_paid_repair"},
            {"spent": {"mediakit_subtitle_removal_runs": 1}},
            policy,
            [],
            False,
            {},
        )
        self.assertIn("automatic MediaKit subtitle-removal limit reached", reason)
        self.assertEqual(state["mediakit_subtitle_removal_runs"], 1)

        approved_reason, _ = run_next_loop_round.cost_stop_reason(
            "subtitle_removal",
            "final_qc",
            {"cost_class": "conditional_paid_repair"},
            {"spent": {"mediakit_subtitle_removal_runs": 1}},
            policy,
            [],
            True,
            {
                "approval_recorded": True,
                "approval_scope": "targeted_retry",
                "mediakit_subtitle_retry_approved": True,
            },
        )
        self.assertIsNone(approved_reason)

    def test_paid_attempt_marker_blocks_reentry_without_passing_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repair_dir = root / "output" / "job-001" / "subtitle_removal"
            repair_dir.mkdir(parents=True)
            (repair_dir / "paid_attempt.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "attempt_number": 1,
                        "status": "failed",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            reason = run_next_loop_round.existing_mediakit_attempt_reason(
                root, {"id": "job-001"}
            )
            self.assertIn("automatic retry is blocked", reason)
            self.assertIsNone(
                run_next_loop_round.existing_mediakit_attempt_reason(
                    root,
                    {"id": "job-001"},
                    retry_approved=True,
                )
            )

    def test_explicit_targeted_approval_allows_recording_one_retry_spend(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = run_next_loop_round.default_cost_policy()
            job = {"id": "job-001"}
            state = {"spent": {"mediakit_subtitle_removal_runs": 1}}
            decision = {"canonical_stage": "subtitle_removal", "gate": "gates/subtitle_removal_gate.md"}
            args = Namespace(
                approval_recorded=True,
                approval_scope="targeted_retry",
                allow_paid=True,
                approve_mediakit_subtitle_retry=True,
                record_gate_result="FAIL",
                spent_mediakit_subtitle_removal_runs=1,
                spent_seedance_runs=0,
            )

            run_next_loop_round.preflight_cost_policy_recording(
                root, job, decision, args, policy, state
            )

            args.approve_mediakit_subtitle_retry = False
            with self.assertRaisesRegex(ValueError, "second automatic MediaKit"):
                run_next_loop_round.preflight_cost_policy_recording(
                    root, job, decision, args, policy, state
                )

    def test_completed_paid_attempt_also_blocks_a_second_submission(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            detection = self.write_detection(root, "burned_in")
            self.write_removal_report(
                root, detection, action="mediakit_pro", paid_tasks=1
            )
            reason = run_next_loop_round.existing_mediakit_attempt_reason(
                root, {"id": "job-001"}
            )
            self.assertIn("another submission is blocked", reason)

    def test_detection_report_accepts_clean_and_burned_in_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            clean = self.write_detection(root, "clean")
            self.assertEqual(subtitle_workflow_qc.detection_issues(clean), [])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            burned = self.write_detection(root, "burned_in")
            self.assertEqual(subtitle_workflow_qc.detection_issues(burned), [])

    def test_detection_rejects_legacy_separate_track_classification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            detection = self.write_detection(root, "separate_track")
            issues = subtitle_workflow_qc.detection_issues(detection)
            self.assertTrue(
                any("clean" in issue and "burned_in" in issue for issue in issues)
            )

    def test_detection_report_rejects_stale_video_and_missing_burned_in_interval(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report_path = self.write_detection(root, "burned_in")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["subtitle_intervals"] = []
            report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
            issues = subtitle_workflow_qc.detection_issues(report_path)
            self.assertTrue(any("subtitle interval" in issue for issue in issues))

            Path(report["finishing_master"]).write_bytes(b"replaced")
            issues = subtitle_workflow_qc.detection_issues(report_path)
            self.assertTrue(any("finishing master hash" in issue for issue in issues))

    def test_detection_rejects_non_image_or_unbound_frame_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report_path = self.write_detection(root, "clean")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            frame = Path(report["evidence_frames"][0]["path"])
            frame.write_bytes(b"not-an-image")
            report["evidence_frames"][0]["sha256"] = sha256(frame)
            report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")

            issues = subtitle_workflow_qc.detection_issues(report_path)

            self.assertTrue(
                any("corresponding finishing-master frame" in issue for issue in issues)
            )

    def test_detection_must_bind_the_exact_finished_master(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report_path = self.write_detection(root, "clean")
            raw_part = root / "output" / "job-001" / "generation" / "part1.mp4"
            raw_part.parent.mkdir(parents=True)
            raw_part.write_bytes(self.video_bytes)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["finishing_master"] = str(raw_part.resolve())
            report["finishing_master_sha256"] = sha256(raw_part)
            report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
            issues = subtitle_workflow_qc.detection_issues(report_path)
            self.assertTrue(any("exact finished video" in issue for issue in issues))

    def test_detection_and_removal_evidence_must_belong_to_current_job(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report_path = self.write_detection(root, "clean")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            foreign_video = root / "output" / "job-old" / "final" / "final_video.mp4"
            foreign_video.parent.mkdir(parents=True)
            foreign_video.write_bytes(b"old-video")
            report["finishing_master"] = str(foreign_video.resolve())
            report["finishing_master_sha256"] = sha256(foreign_video)
            report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
            issues = subtitle_workflow_qc.detection_issues(report_path)
            self.assertTrue(any("exact finished video" in issue for issue in issues))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current_detection = self.write_detection(root, "clean")
            foreign_detection = root / "output" / "job-old" / "subtitle_removal" / "subtitle_detection.json"
            foreign_detection.parent.mkdir(parents=True)
            foreign_detection.write_bytes(current_detection.read_bytes())
            removal = self.write_removal_report(
                root, foreign_detection, action="skipped_clean", paid_tasks=0
            )
            issues = subtitle_workflow_qc.removal_issues(removal)
            self.assertTrue(any("current job detection report" in issue for issue in issues))

    def test_clean_detection_skips_without_paid_task(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            detection = self.write_detection(root, "clean")
            report = self.write_removal_report(
                root, detection, action="skipped_clean", paid_tasks=0
            )
            self.assertEqual(subtitle_workflow_qc.removal_issues(report), [])

    def test_burned_in_detection_requires_one_mediakit_task_and_visual_qc(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            detection = self.write_detection(root, "burned_in")
            report = self.write_removal_report(
                root, detection, action="mediakit_pro", paid_tasks=1
            )
            self.assertEqual(subtitle_workflow_qc.removal_issues(report), [])
            paths = run_next_loop_round.inspection_paths(
                root,
                {"id": "job-001"},
                {"canonical_stage": "final_qc"},
            )
            active = next(item for item in paths if item["label"] == "Final video")
            self.assertTrue(active["path"].endswith("final_video_no_subtitles.mp4"))

            payload = json.loads(report.read_text(encoding="utf-8"))
            payload["paid_tasks_submitted"] = 0
            report.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            issues = subtitle_workflow_qc.removal_issues(report)
            self.assertTrue(any("exactly one paid task" in issue for issue in issues))

    def test_explicit_retry_uses_a_distinct_append_only_attempt_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            detection = self.write_detection(root, "burned_in")
            report = self.write_removal_report(
                root,
                detection,
                action="mediakit_pro",
                paid_tasks=1,
                attempt_number=2,
            )

            self.assertEqual(subtitle_workflow_qc.removal_issues(report), [])
            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertTrue(payload["paid_attempt_record"].endswith("paid_attempt_2.json"))

    def test_mediakit_branch_requires_independent_semantic_checker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            detection = self.write_detection(root, "burned_in")
            self.write_removal_report(
                root, detection, action="mediakit_pro", paid_tasks=1
            )
            ledger = build_stage_ledger(
                root,
                {"id": "job-001"},
                "subtitle_removal",
            )
            self.assertEqual(ledger["overall"], "STOP")
            request = ledger["semantic_review_request"]
            self.assertTrue(request["required"])
            self.assertEqual(
                {family["name"] for family in request["families"]},
                {"subtitle_presence_classification", "subtitle_repair_quality"},
            )
            self.assertEqual(
                next(
                    family
                    for family in request["families"]
                    if family["name"] == "subtitle_repair_quality"
                )["scope"]["subtitle_intervals"],
                [{"start": 0.1, "end": 0.4}],
            )
            checker_qc = self.write_bound_checker(
                root, "subtitle_removal", request
            )
            passed = build_stage_ledger(
                root,
                {"id": "job-001"},
                "subtitle_removal",
            )
            self.assertEqual(passed["overall"], "PASS")
            repeated = build_stage_ledger(
                root,
                {"id": "job-001"},
                "subtitle_removal",
            )
            self.assertEqual(repeated["overall"], "PASS")
            self.assertTrue(
                (
                    root
                    / "output"
                    / "job-001"
                    / "checks"
                    / "subtitle_removal_semantic_review_request.json"
                ).is_file()
            )

            valid_checker = json.loads(checker_qc.read_text(encoding="utf-8"))
            foreign = json.loads(json.dumps(valid_checker))
            foreign["fields"]["Job"] = "job-old"
            checker_qc.write_text(json.dumps(foreign) + "\n", encoding="utf-8")
            cross_job = build_stage_ledger(
                root,
                {"id": "job-001"},
                "subtitle_removal",
            )
            self.assertEqual(cross_job["overall"], "STOP")

            invalid = valid_checker
            invalid["qc_risk_review"]["request_sha256"] = "request-hash"
            checker_qc.write_text(json.dumps(invalid) + "\n", encoding="utf-8")
            rejected = build_stage_ledger(
                root,
                {"id": "job-001"},
                "subtitle_removal",
            )
            self.assertEqual(rejected["overall"], "STOP")

    def test_clean_branch_requires_one_bound_subtitle_presence_checker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            detection = self.write_detection(root, "clean")
            self.write_removal_report(
                root, detection, action="skipped_clean", paid_tasks=0
            )
            ledger = build_stage_ledger(
                root,
                {"id": "job-001"},
                "subtitle_removal",
            )
            self.assertEqual(ledger["overall"], "STOP")
            request = ledger["semantic_review_request"]
            self.assertTrue(request["required"])
            self.assertEqual(
                [family["name"] for family in request["families"]],
                ["subtitle_presence_classification"],
            )

    def test_burned_in_detection_cannot_be_marked_skipped(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            detection = self.write_detection(root, "burned_in")
            report = self.write_removal_report(
                root, detection, action="skipped_clean", paid_tasks=0
            )
            issues = subtitle_workflow_qc.removal_issues(report)
            self.assertTrue(any("mediakit_pro" in issue for issue in issues))

    def test_mediakit_visual_qc_requires_bound_temporal_frame_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            detection = self.write_detection(root, "burned_in")
            report_path = self.write_removal_report(
                root, detection, action="mediakit_pro", paid_tasks=1
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            qc_path = Path(report["visual_qc_report"])
            qc = json.loads(qc_path.read_text(encoding="utf-8"))
            qc["high_risk_windows"][0]["frame_evidence"] = []
            qc_path.write_text(json.dumps(qc) + "\n", encoding="utf-8")
            issues = subtitle_workflow_qc.removal_issues(report_path)
            self.assertTrue(any("8fps frame evidence" in issue for issue in issues))

    def test_mediakit_visual_qc_rejects_duplicate_frames_as_8fps_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            detection = self.write_detection(root, "burned_in")
            report_path = self.write_removal_report(
                root, detection, action="mediakit_pro", paid_tasks=1
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            qc_path = Path(report["visual_qc_report"])
            qc = json.loads(qc_path.read_text(encoding="utf-8"))
            first_frame = qc["high_risk_windows"][0]["frame_evidence"][0]
            qc["high_risk_windows"][0]["end"] = 0.4
            qc["high_risk_windows"][0]["frame_evidence"] = [first_frame] * 3
            qc_path.write_text(json.dumps(qc) + "\n", encoding="utf-8")

            issues = subtitle_workflow_qc.removal_issues(report_path)

            self.assertTrue(any("repeats a frame path" in issue for issue in issues))
            self.assertTrue(
                any("repeats a frame timestamp" in issue for issue in issues)
            )
            self.assertTrue(
                any("gap greater than 0.125s" in issue for issue in issues)
            )

    def test_mediakit_visual_qc_rejects_frame_not_from_repair_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            detection = self.write_detection(root, "burned_in")
            report_path = self.write_removal_report(
                root, detection, action="mediakit_pro", paid_tasks=1
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            qc_path = Path(report["visual_qc_report"])
            qc = json.loads(qc_path.read_text(encoding="utf-8"))
            frame_record = qc["high_risk_windows"][0]["frame_evidence"][0]
            frame = Path(frame_record["path"])
            frame.write_bytes(b"not-an-image")
            frame_record["sha256"] = sha256(frame)
            qc_path.write_text(json.dumps(qc) + "\n", encoding="utf-8")

            issues = subtitle_workflow_qc.removal_issues(report_path)

            self.assertTrue(
                any("corresponding repair-output frame" in issue for issue in issues)
            )

    def test_runner_preflight_requires_detection_only_at_subtitle_removal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job = {"id": "job-001"}
            args = Namespace(
                record_gate_result="PASS",
                artifact="",
                dry_run=False,
            )

            with self.assertRaisesRegex(ValueError, "selected generation outputs"):
                run_next_loop_round.preflight_pass_recording(
                    root, job, {"canonical_stage": "generation"}, args
                )

            generation = root / "output" / "job-001" / "generation"
            generation.mkdir(parents=True)
            part = generation / "part1.mp4"
            part.write_bytes(self.video_bytes)
            (generation / "selected_outputs.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "outputs": [
                            {
                                "part_id": "part1",
                                "path": str(part.resolve()),
                                "sha256": sha256(part),
                                "duration_seconds": 0.5,
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            run_next_loop_round.preflight_pass_recording(
                root, job, {"canonical_stage": "generation"}, args
            )

            detection = self.write_detection(root, "clean")
            with self.assertRaisesRegex(ValueError, "subtitle removal evidence"):
                run_next_loop_round.preflight_pass_recording(
                    root, job, {"canonical_stage": "subtitle_removal"}, args
                )

            self.write_removal_report(
                root, detection, action="skipped_clean", paid_tasks=0
            )
            ledger = build_stage_ledger(
                root, {"id": "job-001"}, "subtitle_removal"
            )
            self.write_bound_checker(
                root,
                "subtitle_removal",
                ledger["semantic_review_request"],
            )
            run_next_loop_round.preflight_pass_recording(
                root, job, {"canonical_stage": "subtitle_removal"}, args
            )

    def test_final_qc_must_be_bound_to_active_repaired_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            detection = self.write_detection(root, "burned_in")
            removal_path = self.write_removal_report(
                root, detection, action="mediakit_pro", paid_tasks=1
            )
            removal = json.loads(removal_path.read_text(encoding="utf-8"))
            final_dir = root / "output" / "job-001" / "final"
            final_qc_md = final_dir / "final_qc.md"
            final_qc_json = final_dir / "final_qc.json"
            final_qc_md.write_text("PASS\n", encoding="utf-8")
            wrong_video = Path(removal["source_video"])
            final_qc_json.write_text(
                json.dumps(
                    {
                        "overall": "PASS",
                        "videos": [
                            {"path": str(wrong_video), "sha256": sha256(wrong_video)}
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            args = Namespace(
                record_gate_result="PASS",
                artifact=str(final_qc_md),
                dry_run=False,
            )
            with self.assertRaisesRegex(ValueError, "active subtitle-removal output"):
                run_next_loop_round.preflight_pass_recording(
                    root,
                    {"id": "job-001"},
                    {"canonical_stage": "final_qc"},
                    args,
                )

            active_video = Path(removal["output_video"])
            final_qc_json.write_text(
                json.dumps(
                    {
                        "overall": "PASS",
                        "videos": [
                            {"path": str(active_video), "sha256": sha256(active_video)}
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            run_next_loop_round.preflight_pass_recording(
                root,
                {"id": "job-001"},
                {"canonical_stage": "final_qc"},
                args,
            )


if __name__ == "__main__":
    unittest.main()
