import csv
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from job_intake import (
    JobIntakeRequest,
    STORYBOARD_DERIVED_PERSON_ASSETS,
    create_jobs,
)


def prepare_root(path):
    shutil.copytree(
        ROOT / "rules" / "product-profiles",
        path / "rules" / "product-profiles",
    )
    shutil.copy2(
        ROOT / "rules" / "STAGE_RULES.json",
        path / "rules" / "STAGE_RULES.json",
    )


def read_jobs(root):
    with (root / "jobs.csv").open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class JobIntakeTest(unittest.TestCase):
    def test_new_intake_never_overwrites_an_existing_job_or_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_root(root)
            product = root / "product"
            product.mkdir()
            first_video = root / "first.mp4"
            second_video = root / "second.mp4"
            first_video.write_bytes(b"first")
            second_video.write_bytes(b"second")
            request = JobIntakeRequest(
                product_name="Test Product",
                product_assets=str(product),
                target_duration="1s",
                notes="不需要最终视频",
            )

            first = create_jobs(root, [first_video], request)
            marker = root / "output" / "job-001" / "keep-me.txt"
            marker.write_text("owned by the first job", encoding="utf-8")
            second = create_jobs(root, [second_video], request)

            self.assertEqual(first.created_jobs[0]["id"], "job-001")
            self.assertEqual(second.created_jobs[0]["id"], "job-002")
            self.assertEqual([row["id"] for row in read_jobs(root)], [
                "job-001",
                "job-002",
            ])
            self.assertEqual(marker.read_text(encoding="utf-8"), "owned by the first job")

    def test_two_cli_adapters_create_the_same_formal_job_contract(self):
        with tempfile.TemporaryDirectory() as first_tmp, tempfile.TemporaryDirectory() as second_tmp:
            new_root = Path(first_tmp)
            inbox_root = Path(second_tmp)
            prepare_root(new_root)
            prepare_root(inbox_root)
            new_product = new_root / "product"
            inbox_product = inbox_root / "product"
            new_product.mkdir()
            inbox_product.mkdir()
            new_video = new_root / "source.mp4"
            inbox_dir = inbox_root / "inbox"
            inbox_dir.mkdir()
            inbox_video = inbox_dir / "source.mp4"
            new_video.write_bytes(b"same-video")
            inbox_video.write_bytes(b"same-video")

            new_result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "new-task.py"),
                    "--root",
                    str(new_root),
                    "--video",
                    str(new_video),
                    "--product-name",
                    "Test Product",
                    "--product-assets",
                    str(new_product),
                    "--target-duration",
                    "1s",
                    "--notes",
                    "不需要最终视频",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            inbox_result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "sync-inbox-to-jobs.py"),
                    "--root",
                    str(inbox_root),
                    "--video-dir",
                    str(inbox_dir),
                    "--product-name",
                    "Test Product",
                    "--product-assets",
                    str(inbox_product),
                    "--target-duration",
                    "1s",
                    "--notes",
                    "不需要最终视频",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(new_result.returncode, 0, new_result.stderr)
            self.assertEqual(inbox_result.returncode, 0, inbox_result.stderr)
            new_job = read_jobs(new_root)[0]
            inbox_job = read_jobs(inbox_root)[0]
            for field in (
                "status",
                "next_stage",
                "person_assets",
                "audio_assets",
                "target_duration",
                "handoff_mode",
                "needs_user_confirmation",
            ):
                self.assertEqual(new_job[field], inbox_job[field], field)
            self.assertEqual(
                new_job["person_assets"],
                STORYBOARD_DERIVED_PERSON_ASSETS,
            )
            self.assertEqual(new_job["handoff_mode"], "web")
            for root in (new_root, inbox_root):
                self.assertTrue(
                    (root / "output" / "job-001" / "intake.json").is_file()
                )
                self.assertTrue(
                    (
                        root
                        / "output"
                        / "job-001"
                        / "product_profile.json"
                    ).is_file()
                )

    def test_inbox_uses_real_source_duration_when_user_omits_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_root(root)
            product = root / "product"
            product.mkdir()
            inbox = root / "inbox"
            inbox.mkdir()
            video = inbox / "source.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=64x64:d=1.4",
                    "-an",
                    str(video),
                ],
                check=True,
                capture_output=True,
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "sync-inbox-to-jobs.py"),
                    "--root",
                    str(root),
                    "--video-dir",
                    str(inbox),
                    "--product-name",
                    "Test Product",
                    "--product-assets",
                    str(product),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            job = read_jobs(root)[0]
            self.assertAlmostEqual(
                float(job["target_duration"].removesuffix("s")),
                1.4,
                places=1,
            )
            intake = json.loads(
                (
                    root
                    / "output"
                    / "job-001"
                    / "intake.json"
                ).read_text(encoding="utf-8")
            )
            self.assertFalse(
                intake["target_duration"]["explicitly_requested"]
            )

    def test_repeated_inbox_sync_skips_duration_probe_for_existing_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_root(root)
            product = root / "product"
            product.mkdir()
            video = root / "source.mp4"
            video.write_bytes(b"video")
            create_jobs(
                root,
                [video],
                JobIntakeRequest(
                    product_name="Test Product",
                    product_assets=str(product),
                    target_duration="1s",
                ),
            )
            probe_calls = []

            result = create_jobs(
                root,
                [video],
                JobIntakeRequest(
                    product_name="Test Product",
                    product_assets=str(product),
                    duplicate_video_policy="skip",
                ),
                duration_probe=lambda path: probe_calls.append(path) or 1.0,
            )

            self.assertEqual(result.created_jobs, ())
            self.assertEqual(probe_calls, [])

    def test_dry_run_plans_jobs_without_writing_to_the_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_root(root)
            product = root / "product"
            product.mkdir()
            video = root / "source.mp4"
            video.write_bytes(b"video")
            before = sorted(
                path.relative_to(root)
                for path in root.rglob("*")
            )

            result = create_jobs(
                root,
                [video],
                JobIntakeRequest(
                    product_name="Test Product",
                    product_assets=str(product),
                    target_duration="1s",
                ),
                dry_run=True,
            )
            after = sorted(
                path.relative_to(root)
                for path in root.rglob("*")
            )

            self.assertEqual(result.created_jobs[0]["id"], "job-001")
            self.assertEqual(after, before)

    def test_legacy_partial_rules_cannot_shape_a_new_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rules = root / "rules" / "STAGE_RULES.json"
            rules.parent.mkdir(parents=True)
            rules.write_text(
                json.dumps(
                    {
                        "terminal_statuses": ["done"],
                        "rules": [
                            {
                                "match": {
                                    "type": "exact",
                                    "status": "pending",
                                },
                                "canonical_stage": "source_blueprint",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            product = root / "product"
            product.mkdir()
            video = root / "source.mp4"
            video.write_bytes(b"video")

            with self.assertRaisesRegex(
                ValueError,
                "complete lifecycle rules",
            ):
                create_jobs(
                    root,
                    [video],
                    JobIntakeRequest(
                        product_name="Test Product",
                        product_assets=str(product),
                        target_duration="1s",
                    ),
                )


if __name__ == "__main__":
    unittest.main()
