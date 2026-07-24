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


class FinishingStageTests(unittest.TestCase):
    def setUp(self):
        rules = json.loads((REPO_ROOT / "rules" / "STAGE_RULES.json").read_text(encoding="utf-8"))
        self.rules = {item["id"]: item for item in rules["rules"]}

    def test_generation_advances_to_local_finishing_before_final_qc(self):
        self.assertEqual(self.rules["generation_approved"]["next_expected"], "finishing")
        finishing = self.rules["finishing"]
        self.assertEqual(finishing["canonical_stage"], "finishing")
        self.assertEqual(finishing["cost_class"], "free_check")
        self.assertEqual(finishing["script_file"], "tools/finish_video.py")
        self.assertEqual(finishing["next_expected"], "subtitle_removal")

    def test_finishing_stays_inside_user_visible_delivery_stage(self):
        stage = run_next_loop_round.user_visible_stage("finishing", "finishing", "final_qc")
        self.assertEqual(stage["index"], 5)
        self.assertEqual(stage["label"], "质检交付")

    def test_finishing_worker_and_gate_are_present(self):
        self.assertTrue((REPO_ROOT / self.rules["finishing"]["worker_file"]).is_file())
        self.assertTrue((REPO_ROOT / self.rules["finishing"]["gate"]).is_file())

    def test_product_reference_jobs_require_a_current_product_still_guard_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job_root = root / "output" / "job-001"
            visual_assets = job_root / "visual-assets"
            final = job_root / "final"
            visual_assets.mkdir(parents=True)
            final.mkdir(parents=True)
            reference = visual_assets / "product.png"
            reference.write_bytes(b"product-reference")
            manifest = visual_assets / "approved_visual_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "reusable_refs": {"product_front": str(reference)},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            output = final / "final_video.mp4"
            output.write_bytes(b"finished-video")
            plan_path = job_root / "finishing" / "edit_plan.json"
            plan_path.parent.mkdir(parents=True)
            plan_path.write_text('{"version": 1}\n', encoding="utf-8")
            finish_report = {}
            validated_plan = {"product_still_guard": None}

            issues = run_next_loop_round.product_still_guard_evidence_issues(
                root,
                {"id": "job-001"},
                plan_path,
                validated_plan,
                finish_report,
                output,
            )

            self.assertTrue(
                any("product still guard" in issue for issue in issues),
                issues,
            )

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe required")
    def test_finishing_pass_requires_report_bound_to_current_plan_and_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            finishing = root / "output" / "job-001" / "finishing"
            generation = root / "output" / "job-001" / "generation"
            final = root / "output" / "job-001" / "final"
            finishing.mkdir(parents=True)
            generation.mkdir(parents=True)
            final.mkdir(parents=True)
            plan = finishing / "edit_plan.json"
            output = final / "final_video.mp4"
            source = generation / "part1.mp4"
            subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=black:s=16x16:d=0.5",
                    "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono",
                    "-t", "0.5", "-c:v", "mpeg4", "-c:a", "aac",
                    "-shortest", str(source),
                ],
                check=True,
            )
            output.write_bytes(source.read_bytes())
            plan.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "executor": "local_ffmpeg",
                        "inputs": [{"id": "part1", "path": str(source.resolve())}],
                        "timeline": [
                            {"input": "part1", "start": 0, "end": 0.5, "speed": 1}
                        ],
                        "output": {
                            "filename": "final_video.mp4",
                            "audio_fade_out_seconds": 0,
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (generation / "selected_outputs.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "outputs": [
                            {
                                "part_id": "part1",
                                "path": str(source.resolve()),
                                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                                "duration_seconds": 1.0,
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            report = {
                "overall": "PASS",
                "executor": "local_ffmpeg",
                "paid_tasks_submitted": 0,
                "caption_free": True,
                "plan": str(plan.resolve()),
                "plan_sha256": hashlib.sha256(plan.read_bytes()).hexdigest(),
                "output": str(output.resolve()),
                "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                "expected_duration": 0.5,
                "actual_duration": 0.5,
                "timeline": [
                    {"input": "part1", "start": 0.0, "end": 0.5, "speed": 1.0}
                ],
                "inputs": {
                    "part1": {
                        "path": str(source.resolve()),
                        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    }
                },
            }
            (final / "finish_report.json").write_text(
                json.dumps(report) + "\n", encoding="utf-8"
            )
            args = Namespace(record_gate_result="PASS")
            decision = {"canonical_stage": "finishing"}
            job = {"id": "job-001"}

            ledger = run_next_loop_round.build_stage_ledger(
                root, job, "finishing"
            )
            request = ledger["semantic_review_request"]
            family = request["families"][0]
            checks = root / "output" / "job-001" / "checks"
            request_path = checks / "finishing_semantic_review_request.json"
            (checks / "finishing_gate_review_qc.json").write_text(
                json.dumps(
                    {
                        "overall": "PASS",
                        "fields": {"Job": "job-001", "Stage": "finishing"},
                        "checks": [
                            {"name": "qc_risk_request_binding", "status": "PASS"}
                        ],
                        "qc_risk_review": {
                            "request_id": request["request_id"],
                            "request_path": str(request_path.resolve()),
                            "request_sha256": hashlib.sha256(
                                request_path.read_bytes()
                            ).hexdigest(),
                            "family_fingerprints": {
                                family["name"]: family["fingerprint_hash"]
                            },
                            "family_results": {family["name"]: "PASS"},
                            "invocation_count": 1,
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            run_next_loop_round.preflight_pass_recording(root, job, decision, args)
            self.assertTrue(request_path.is_file())
            run_next_loop_round.preflight_pass_recording(root, job, decision, args)
            self.assertTrue(request_path.is_file())

            report["caption_free"] = False
            (final / "finish_report.json").write_text(
                json.dumps(report) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "caption-free"):
                run_next_loop_round.preflight_pass_recording(root, job, decision, args)

            report["caption_free"] = True
            (final / "finish_report.json").write_text(
                json.dumps(report) + "\n", encoding="utf-8"
            )

            original_output = output.read_bytes()
            output.write_bytes(b"not-a-video")
            report["output_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
            (final / "finish_report.json").write_text(
                json.dumps(report) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "finishing evidence"):
                run_next_loop_round.preflight_pass_recording(root, job, decision, args)

            output.write_bytes(original_output)
            report["output_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
            (final / "finish_report.json").write_text(
                json.dumps(report) + "\n", encoding="utf-8"
            )

            approved_plan = plan.read_text(encoding="utf-8")
            unapproved = final / "unapproved.mp4"
            unapproved.write_bytes(source.read_bytes())
            plan_payload = json.loads(approved_plan)
            plan_payload["inputs"][0]["path"] = str(unapproved.resolve())
            plan.write_text(json.dumps(plan_payload) + "\n", encoding="utf-8")
            report["plan_sha256"] = hashlib.sha256(plan.read_bytes()).hexdigest()
            (final / "finish_report.json").write_text(
                json.dumps(report) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "finishing evidence"):
                run_next_loop_round.preflight_pass_recording(root, job, decision, args)

            plan.write_text(approved_plan, encoding="utf-8")
            report["plan_sha256"] = hashlib.sha256(plan.read_bytes()).hexdigest()
            (final / "finish_report.json").write_text(
                json.dumps(report) + "\n", encoding="utf-8"
            )

            plan.write_text('{"version": 1, "changed": true}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "finishing evidence"):
                run_next_loop_round.preflight_pass_recording(root, job, decision, args)


if __name__ == "__main__":
    unittest.main()
