import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import local_repair_lifecycle


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "local_repair_lifecycle.py"
ARTIFACT_SCRIPT = REPO_ROOT / "tools" / "artifact_lifecycle.py"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class LocalRepairLifecycleTest(unittest.TestCase):
    def _write_report(self, path, master, candidate):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "overall": "PASS",
                    "paid_tasks_submitted": 0,
                    "baseline": {
                        "path": str(master),
                        "sha256": sha256(master),
                    },
                    "candidate": {
                        "path": str(candidate),
                        "sha256": sha256(candidate),
                    },
                }
            ),
            encoding="utf-8",
        )

    def _promote(self, job_dir, candidate, report):
        return subprocess.run(
            [
                "python3",
                str(SCRIPT),
                "promote",
                "--job-dir",
                str(job_dir),
                "--candidate",
                str(candidate),
                "--report",
                str(report),
                "--confirm-job-id",
                job_dir.name,
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_promote_keeps_current_master_and_exactly_one_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "output" / "job-001"
            master = job_dir / "final" / "final_video.mp4"
            candidate1 = job_dir / "local_repair" / "candidate1.mp4"
            candidate2 = job_dir / "local_repair" / "candidate2.mp4"
            master.parent.mkdir(parents=True)
            candidate1.parent.mkdir(parents=True)
            master.write_bytes(b"original")
            candidate1.write_bytes(b"first repair")
            report1 = job_dir / "local_repair" / "report1.json"
            self._write_report(report1, master, candidate1)

            first = self._promote(job_dir, candidate1, report1)

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(master.read_bytes(), b"first repair")
            self.assertFalse(candidate1.exists())
            manifest1 = json.loads(first.stdout)
            rollback = (
                job_dir.parent
                / ".history"
                / job_dir.name
                / "rollback"
                / "local_repair"
                / "final"
                / "final_video.mp4"
            )
            self.assertEqual(rollback.read_bytes(), b"original")
            self.assertEqual(manifest1["current"]["sha256"], sha256(master))
            self.assertEqual(manifest1["rollback"]["sha256"], sha256(rollback))

            candidate2.write_bytes(b"second repair")
            unused = job_dir / "local_repair" / "unused_intermediate.mp4"
            unused.write_bytes(b"old local intermediate")
            report2 = job_dir / "local_repair" / "report2.json"
            self._write_report(report2, master, candidate2)
            second = self._promote(job_dir, candidate2, report2)

            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(master.read_bytes(), b"second repair")
            self.assertFalse(candidate2.exists())
            self.assertEqual(rollback.read_bytes(), b"first repair")
            history_videos = list(
                (job_dir.parent / ".history" / job_dir.name).rglob("*.mp4")
            )
            self.assertEqual(history_videos, [rollback])

            preview = subprocess.run(
                [
                    "python3",
                    str(ARTIFACT_SCRIPT),
                    "preview",
                    "--job-dir",
                    str(job_dir),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(preview.returncode, 0, preview.stderr)
            family = json.loads(preview.stdout)["managed_families"][
                "local_repair_media"
            ]
            self.assertEqual(
                [item["path"] for item in family["candidates"]],
                ["local_repair/unused_intermediate.mp4"],
            )
            self.assertIn("current_plus_one_rollback", family["reason"])
            preview_path = job_dir / "checks" / "cleanup_preview.json"
            preview_path.parent.mkdir(parents=True)
            preview_path.write_text(preview.stdout, encoding="utf-8")
            cleaned = subprocess.run(
                [
                    "python3",
                    str(ARTIFACT_SCRIPT),
                    "cleanup",
                    "--job-dir",
                    str(job_dir),
                    "--preview",
                    str(preview_path),
                    "--confirm-job-id",
                    job_dir.name,
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(cleaned.returncode, 0, cleaned.stderr)
            self.assertFalse(candidate1.exists())
            self.assertFalse(candidate2.exists())
            self.assertFalse(unused.exists())
            self.assertTrue(master.exists())
            self.assertTrue(rollback.exists())

    def test_repo_root_relative_paths_match_the_documented_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "output" / "job-relative"
            master = job_dir / "final" / "final_video.mp4"
            candidate = job_dir / "local_repair" / "candidate.mp4"
            report = job_dir / "local_repair" / "report.json"
            master.parent.mkdir(parents=True)
            candidate.parent.mkdir(parents=True)
            master.write_bytes(b"original")
            candidate.write_bytes(b"candidate")
            report.write_text(
                json.dumps(
                    {
                        "overall": "PASS",
                        "paid_tasks_submitted": 0,
                        "baseline": {
                            "path": "output/job-relative/final/final_video.mp4",
                            "sha256": sha256(master),
                        },
                        "candidate": {
                            "path": (
                                "output/job-relative/local_repair/candidate.mp4"
                            ),
                            "sha256": sha256(candidate),
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = self._promote(
                job_dir,
                Path("output/job-relative/local_repair/candidate.mp4"),
                Path("output/job-relative/local_repair/report.json"),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(master.read_bytes(), b"candidate")

    def test_symlinked_history_root_is_rejected_before_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job_dir = root / "output" / "job-symlink"
            master = job_dir / "final" / "final_video.mp4"
            candidate = job_dir / "local_repair" / "candidate.mp4"
            report = job_dir / "local_repair" / "report.json"
            master.parent.mkdir(parents=True)
            candidate.parent.mkdir(parents=True)
            master.write_bytes(b"original")
            candidate.write_bytes(b"candidate")
            self._write_report(report, master, candidate)
            outside = root / "outside"
            outside.mkdir()
            (job_dir.parent / ".history").symlink_to(outside, target_is_directory=True)

            result = self._promote(job_dir, candidate, report)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symlink", result.stderr)
            self.assertEqual(master.read_bytes(), b"original")
            self.assertEqual(list(outside.rglob("*")), [])

    def test_manifest_publish_failure_restores_master_and_previous_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "output" / "job-transaction"
            master = job_dir / "final" / "final_video.mp4"
            candidate = job_dir / "local_repair" / "candidate.mp4"
            report = job_dir / "local_repair" / "report.json"
            rollback = (
                job_dir.parent
                / ".history"
                / job_dir.name
                / "rollback"
                / "local_repair"
                / "final"
                / "final_video.mp4"
            )
            master.parent.mkdir(parents=True)
            candidate.parent.mkdir(parents=True)
            rollback.parent.mkdir(parents=True)
            master.write_bytes(b"current")
            candidate.write_bytes(b"candidate")
            rollback.write_bytes(b"older rollback")
            self._write_report(report, master, candidate)

            with mock.patch.object(
                local_repair_lifecycle,
                "publish_manifest",
                side_effect=OSError("disk full"),
            ):
                with self.assertRaises(OSError):
                    local_repair_lifecycle.promote(
                        job_dir,
                        candidate,
                        report,
                        job_dir.name,
                    )

            self.assertEqual(master.read_bytes(), b"current")
            self.assertEqual(rollback.read_bytes(), b"older rollback")
            self.assertEqual(candidate.read_bytes(), b"candidate")

    def test_stale_report_cannot_replace_the_master(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "output" / "job-002"
            master = job_dir / "final" / "final_video.mp4"
            candidate = job_dir / "local_repair" / "candidate.mp4"
            master.parent.mkdir(parents=True)
            candidate.parent.mkdir(parents=True)
            master.write_bytes(b"original")
            candidate.write_bytes(b"candidate")
            report = job_dir / "local_repair" / "report.json"
            self._write_report(report, master, candidate)
            candidate.write_bytes(b"changed after review")

            result = self._promote(job_dir, candidate, report)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("candidate", result.stderr)
            self.assertEqual(master.read_bytes(), b"original")
            self.assertFalse(
                (job_dir.parent / ".history" / job_dir.name / "rollback").exists()
            )


if __name__ == "__main__":
    unittest.main()
