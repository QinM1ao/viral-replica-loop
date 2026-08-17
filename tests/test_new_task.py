import importlib.util
import csv
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("new_task", ROOT / "scripts" / "new-task.py")
NEW_TASK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NEW_TASK)


def prepare_rules(root):
    shutil.copytree(
        ROOT / "rules" / "product-profiles",
        root / "rules" / "product-profiles",
    )
    shutil.copy2(
        ROOT / "rules" / "STAGE_RULES.json",
        root / "rules" / "STAGE_RULES.json",
    )


class NewTaskTest(unittest.TestCase):
    def test_stop_before_generation_defaults_to_web_handoff(self):
        self.assertEqual(
            NEW_TASK.infer_handoff_mode("auto", "不需要最终视频，到 Seedance 生成视频前停"),
            "web",
        )

    def test_direct_generation_defaults_to_api_handoff(self):
        self.assertEqual(NEW_TASK.infer_handoff_mode("auto", "直接出视频，跑 Seedance"), "api")

    def test_explicit_mode_wins(self):
        self.assertEqual(NEW_TASK.infer_handoff_mode("both", "生成视频前停"), "both")

    def test_ambiguous_handoff_builds_only_the_web_surface(self):
        self.assertEqual(NEW_TASK.infer_handoff_mode("auto", ""), "web")

    def test_cli_defaults_missing_person_assets_to_storyboard_derived(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_rules(root)
            video = root / "source.mp4"
            video.write_bytes(b"video")
            product = root / "product"
            product.mkdir()

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "new-task.py"),
                    "--root",
                    str(root),
                    "--video",
                    str(video),
                    "--product-name",
                    "Test Product",
                    "--product-assets",
                    str(product),
                    "--target-duration",
                    "1s",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            with (root / "jobs.csv").open(newline="", encoding="utf-8") as file:
                job = next(csv.DictReader(file))
            self.assertEqual(job["person_assets"], "storyboard_derived")
            self.assertIn("Person asset mode: storyboard_derived", (root / "BRIEF.md").read_text(encoding="utf-8"))

    def test_cli_defaults_target_duration_to_each_source_video_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_rules(root)
            video = root / "source.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=64x64:d=2.4",
                    "-an",
                    str(video),
                ],
                check=True,
                capture_output=True,
            )
            product = root / "product"
            product.mkdir()

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "new-task.py"),
                    "--root",
                    str(root),
                    "--video",
                    str(video),
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
            with (root / "jobs.csv").open(newline="", encoding="utf-8") as file:
                job = next(csv.DictReader(file))
            self.assertAlmostEqual(float(job["target_duration"].removesuffix("s")), 2.4, places=1)
            intake = json.loads(
                (root / "output" / job["id"] / "intake.json").read_text(encoding="utf-8")
            )
            self.assertFalse(intake["target_duration"]["explicitly_requested"])
            self.assertEqual(intake["target_duration"]["request_evidence"], None)

    def test_explicit_target_duration_is_bound_in_intake_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_rules(root)
            video = root / "source.mp4"
            video.write_bytes(b"video")
            product = root / "product"
            product.mkdir()

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "new-task.py"),
                    "--root",
                    str(root),
                    "--video",
                    str(video),
                    "--product-name",
                    "Test Product",
                    "--product-assets",
                    str(product),
                    "--target-duration",
                    "12s",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            intake_path = root / "output" / "job-001" / "intake.json"
            intake = json.loads(intake_path.read_text(encoding="utf-8"))
            self.assertTrue(intake["target_duration"]["explicitly_requested"])
            self.assertEqual(
                intake["target_duration"]["request_evidence"]["quote"],
                "--target-duration 12s",
            )

    def test_appending_a_job_preserves_the_active_brief_and_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prepare_rules(root)
            product = root / "product"
            product.mkdir()
            first_video = root / "first.mp4"
            second_video = root / "second.mp4"
            first_video.write_bytes(b"first")
            second_video.write_bytes(b"second")
            common = [
                sys.executable,
                str(ROOT / "scripts" / "new-task.py"),
                "--root",
                str(root),
                "--product-name",
                "Test Product",
                "--product-assets",
                str(product),
                "--target-duration",
                "1s",
            ]

            first = subprocess.run(
                [*common, "--video", str(first_video)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            (root / "BRIEF.md").write_text(
                "active brief must survive",
                encoding="utf-8",
            )
            (root / "STATE.md").write_text(
                "active state must survive",
                encoding="utf-8",
            )

            second = subprocess.run(
                [*common, "--video", str(second_video), "--append"],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(second.returncode, 0, second.stderr)
            with (root / "jobs.csv").open(newline="", encoding="utf-8") as file:
                self.assertEqual(
                    [row["id"] for row in csv.DictReader(file)],
                    ["job-001", "job-002"],
                )
            self.assertEqual(
                (root / "BRIEF.md").read_text(encoding="utf-8"),
                "active brief must survive",
            )
            self.assertEqual(
                (root / "STATE.md").read_text(encoding="utf-8"),
                "active state must survive",
            )


if __name__ == "__main__":
    unittest.main()
