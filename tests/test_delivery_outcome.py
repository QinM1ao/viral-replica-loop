import hashlib
import json
import tempfile
import unittest
from pathlib import Path


from tools.delivery_outcome import build_delivery_manifest


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DeliveryOutcomeTest(unittest.TestCase):
    def test_paid_retake_report_is_not_a_local_repair_lifecycle_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = root / "output" / "job-paid"
            final = job / "final"
            retake = job / "quality_retake" / "paid"
            final.mkdir(parents=True)
            retake.mkdir(parents=True)
            video = final / "final_video.mp4"
            video.write_bytes(b"paid retake")
            digest = sha256(video)
            (retake / "retake_report.json").write_text(
                json.dumps(
                    {
                        "overall": "PASS",
                        "paid_tasks_submitted": 1,
                        "candidate": {"sha256": digest},
                    }
                ),
                encoding="utf-8",
            )
            (final / "finish_report.json").write_text(
                json.dumps(
                    {
                        "overall": "PASS",
                        "output": str(video),
                        "output_sha256": digest,
                    }
                ),
                encoding="utf-8",
            )

            result = build_delivery_manifest(root, "job-paid")

            self.assertEqual(
                result["stages"]["local_repair"]["status"],
                "NOT_APPLICABLE",
            )

    def test_existing_retime_report_shape_requires_registration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = root / "output" / "job-retime"
            final = job / "final"
            retime = job / "quality_retake" / "rolling" / "retime_v2"
            final.mkdir(parents=True)
            retime.mkdir(parents=True)
            video = final / "final_video.mp4"
            video.write_bytes(b"retimed")
            digest = sha256(video)
            (retime / "retime_report.json").write_text(
                json.dumps(
                    {
                        "overall": "PASS",
                        "output": {"final_video_sha256": digest},
                    }
                ),
                encoding="utf-8",
            )
            (final / "finish_report.json").write_text(
                json.dumps(
                    {
                        "overall": "PASS",
                        "output": str(video),
                        "output_sha256": digest,
                    }
                ),
                encoding="utf-8",
            )

            result = build_delivery_manifest(root, "job-retime")

            self.assertEqual(result["overall"], "FAIL")
            self.assertEqual(result["stages"]["local_repair"]["status"], "FAIL")

    def test_old_repair_manifest_does_not_block_a_new_unrepaired_master(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = root / "output" / "job-new-master"
            final = job / "final"
            final.mkdir(parents=True)
            video = final / "final_video.mp4"
            video.write_bytes(b"new normal finish")
            digest = sha256(video)
            (final / "finish_report.json").write_text(
                json.dumps(
                    {
                        "overall": "PASS",
                        "output": str(video),
                        "output_sha256": digest,
                    }
                ),
                encoding="utf-8",
            )
            manifest = (
                root
                / "output"
                / ".history"
                / "job-new-master"
                / "manifests"
                / "local_repair_promotion_latest.json"
            )
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "job_id": "job-new-master",
                        "policy": "current_plus_one_rollback",
                        "current": {
                            "path": "final/final_video.mp4",
                            "sha256": "0" * 64,
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = build_delivery_manifest(root, "job-new-master")

            self.assertEqual(
                result["stages"]["local_repair"]["status"],
                "NOT_APPLICABLE",
            )

    def test_matching_repair_evidence_requires_a_current_lifecycle_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = root / "output" / "job-repair"
            final = job / "final"
            subtitle = job / "subtitle_removal"
            repair = job / "local_repair"
            final.mkdir(parents=True)
            subtitle.mkdir()
            repair.mkdir()
            video = final / "final_video.mp4"
            video.write_bytes(b"repaired")
            digest = sha256(video)
            report = repair / "repair_report.json"
            report.write_text(
                json.dumps(
                    {
                        "overall": "PASS",
                        "candidate": {
                            "path": str(repair / "candidate.mp4"),
                            "sha256": digest,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (final / "finish_report.json").write_text(
                json.dumps(
                    {
                        "overall": "PASS",
                        "output": str(video),
                        "output_sha256": digest,
                    }
                ),
                encoding="utf-8",
            )
            (subtitle / "subtitle_removal_report.json").write_text(
                json.dumps(
                    {
                        "overall": "PASS",
                        "source_video": str(video),
                        "source_sha256": digest,
                        "output_video": str(video),
                        "output_sha256": digest,
                    }
                ),
                encoding="utf-8",
            )
            (final / "final_qc.json").write_text(
                json.dumps(
                    {
                        "overall": "PASS",
                        "videos": [{"path": str(video), "sha256": digest}],
                    }
                ),
                encoding="utf-8",
            )

            unregistered = build_delivery_manifest(root, "job-repair")

            self.assertEqual(unregistered["overall"], "FAIL")
            self.assertEqual(
                unregistered["stages"]["local_repair"]["status"],
                "FAIL",
            )

            rollback = (
                root
                / "output"
                / ".history"
                / "job-repair"
                / "rollback"
                / "local_repair"
                / "final"
                / "final_video.mp4"
            )
            rollback.parent.mkdir(parents=True)
            rollback.write_bytes(b"original")
            manifest_path = (
                root
                / "output"
                / ".history"
                / "job-repair"
                / "manifests"
                / "local_repair_promotion_latest.json"
            )
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "job_id": "job-repair",
                        "policy": "current_plus_one_rollback",
                        "current": {
                            "path": "final/final_video.mp4",
                            "sha256": digest,
                        },
                        "rollback": {
                            "path": (
                                ".history/job-repair/rollback/local_repair/"
                                "final/final_video.mp4"
                            ),
                            "sha256": sha256(rollback),
                        },
                        "review_report": {
                            "path": "local_repair/repair_report.json",
                            "sha256": sha256(report),
                        },
                    }
                ),
                encoding="utf-8",
            )

            registered = build_delivery_manifest(root, "job-repair")

            self.assertEqual(registered["overall"], "PASS")
            self.assertEqual(
                registered["stages"]["local_repair"]["status"],
                "PASS",
            )

    def test_clean_delivery_has_one_final_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = root / "output" / "job-001"
            final = job / "final"
            subtitle = job / "subtitle_removal"
            final.mkdir(parents=True)
            subtitle.mkdir()
            video = final / "final_video.mp4"
            video.write_bytes(b"video")
            digest = sha256(video)
            (final / "finish_report.json").write_text(
                json.dumps(
                    {
                        "overall": "PASS",
                        "output": str(video),
                        "output_sha256": digest,
                    }
                ),
                encoding="utf-8",
            )
            (subtitle / "subtitle_removal_report.json").write_text(
                json.dumps(
                    {
                        "overall": "PASS",
                        "action": "skipped_clean",
                        "paid_tasks_submitted": 0,
                        "source_video": str(video),
                        "source_sha256": digest,
                        "output_video": str(video),
                        "output_sha256": digest,
                    }
                ),
                encoding="utf-8",
            )
            (final / "final_qc.json").write_text(
                json.dumps(
                    {
                        "overall": "PASS",
                        "videos": [
                            {"path": str(video), "sha256": digest}
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = build_delivery_manifest(root, "job-001")

            self.assertEqual(result["overall"], "PASS")
            self.assertEqual(result["next_action"], "done")
            self.assertEqual(result["delivery_path"], str(video.resolve()))
            self.assertEqual(
                result["stages"]["subtitle_removal"]["paid_tasks_submitted"],
                0,
            )

    def test_replaced_active_output_fails_without_changing_the_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            final = root / "output" / "job-002" / "final"
            final.mkdir(parents=True)
            video = final / "final_video.mp4"
            video.write_bytes(b"current")
            (final / "finish_report.json").write_text(
                json.dumps(
                    {
                        "overall": "PASS",
                        "output": str(video),
                        "output_sha256": "0" * 64,
                    }
                ),
                encoding="utf-8",
            )

            result = build_delivery_manifest(root, "job-002")

            self.assertEqual(result["overall"], "FAIL")
            self.assertEqual(video.read_bytes(), b"current")

    def test_subtitle_report_cannot_bind_a_different_source_path_by_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = root / "output" / "job-003"
            final = job / "final"
            subtitle = job / "subtitle_removal"
            final.mkdir(parents=True)
            subtitle.mkdir()
            video = final / "final_video.mp4"
            other = final / "copy.mp4"
            video.write_bytes(b"same bytes")
            other.write_bytes(b"same bytes")
            digest = sha256(video)
            (final / "finish_report.json").write_text(
                json.dumps(
                    {
                        "overall": "PASS",
                        "output": str(video),
                        "output_sha256": digest,
                    }
                ),
                encoding="utf-8",
            )
            (subtitle / "subtitle_removal_report.json").write_text(
                json.dumps(
                    {
                        "overall": "PASS",
                        "source_video": str(other),
                        "source_sha256": digest,
                        "output_video": str(video),
                        "output_sha256": digest,
                    }
                ),
                encoding="utf-8",
            )

            result = build_delivery_manifest(root, "job-003")

            self.assertEqual(
                result["stages"]["subtitle_removal"]["status"],
                "FAIL",
            )

    def test_legacy_subtitle_chain_can_deliver_without_a_finishing_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = root / "output" / "job-004"
            final = job / "final"
            subtitle = job / "subtitle_removal"
            final.mkdir(parents=True)
            subtitle.mkdir()
            source = final / "source.mp4"
            output = final / "clean.mp4"
            source.write_bytes(b"source")
            output.write_bytes(b"clean")
            (subtitle / "subtitle_removal_report.json").write_text(
                json.dumps(
                    {
                        "overall": "PASS",
                        "source_video": str(source),
                        "source_sha256": sha256(source),
                        "output_video": str(output),
                        "output_sha256": sha256(output),
                    }
                ),
                encoding="utf-8",
            )
            (final / "final_qc.json").write_text(
                json.dumps(
                    {
                        "overall": "PASS",
                        "videos": [
                            {
                                "path": str(output),
                                "sha256": sha256(output),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = build_delivery_manifest(root, "job-004")

            self.assertEqual(result["overall"], "PASS")
            self.assertEqual(
                result["compatibility_mode"],
                "legacy_subtitle_chain",
            )


if __name__ == "__main__":
    unittest.main()
