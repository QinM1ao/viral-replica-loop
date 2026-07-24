import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[1]
FINISH_SCRIPT = REPO_ROOT / "tools" / "finish_video.py"
sys.path.insert(0, str(REPO_ROOT / "tools"))

import product_still_guard


@unittest.skipUnless(
    shutil.which("ffmpeg") and shutil.which("ffprobe"),
    "ffmpeg/ffprobe required",
)
class ProductStillGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.reference = self.root / "product.png"
        self.video = self.root / "buggy.mp4"
        self.make_reference()
        self.make_fixture_video()

    def tearDown(self):
        self.tmp.cleanup()

    def make_reference(self):
        image = Image.new("RGB", (240, 720), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()
        draw.rounded_rectangle((20, 12, 220, 700), radius=24, fill="#f7f7f4", outline="#222222", width=5)
        rng = np.random.default_rng(11)
        for index in range(95):
            x = int(rng.integers(28, 205))
            y = int(rng.integers(135, 640))
            radius = int(rng.integers(2, 7))
            color = tuple(int(value) for value in rng.integers(25, 225, 3))
            if index % 2:
                draw.ellipse((x, y, x + radius * 2, y + radius * 2), fill=color)
            else:
                draw.line(
                    (x, y, min(215, x + radius * 3), min(675, y + radius * 2)),
                    fill=color,
                    width=2,
                )
        draw.rounded_rectangle((42, 18, 198, 125), radius=18, fill="#d9342b")
        draw.text((39, 175), "KOPHENIX", fill="#111111", font=font)
        draw.text((38, 215), "SOOTHING REPAIR SPRAY", fill="#111111", font=font)
        for index in range(9):
            y = 275 + index * 38
            color = ("#2d9135", "#e0ad25", "#e44b3f")[index % 3]
            draw.ellipse((35 + index * 7, y, 82 + index * 7, y + 27), fill=color)
            draw.line((92, y + 12, 204, y + 12), fill="#333333", width=3)
        draw.text((82, 650), "2026", fill="#c92823", font=font)
        image.save(self.reference)

    def make_fixture_video(self):
        reference = cv2.imread(str(self.reference))
        fps = 10
        size = (360, 640)
        silent = self.root / "silent.mp4"
        writer = cv2.VideoWriter(
            str(silent),
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps,
            size,
        )
        self.assertTrue(writer.isOpened())
        rng = np.random.default_rng(7)
        texture = rng.integers(0, 35, (size[1], size[0], 3), dtype=np.uint8)
        for frame_index in range(44):
            time_seconds = frame_index / fps
            if 1.5 <= time_seconds < 2.8:
                cover_height = round(reference.shape[0] * size[0] / reference.shape[1])
                cover = cv2.resize(reference, (size[0], cover_height))
                crop_y = 60 + (frame_index % 3)
                frame = cover[crop_y : crop_y + size[1]].copy()
            else:
                frame = np.clip(texture + (frame_index % 12) * 3, 0, 255).astype(np.uint8)
                small = cv2.resize(reference, (92, 276))
                x = 42 + (frame_index * 5) % 150
                y = 290 + round(14 * np.sin(frame_index / 3))
                frame[y : y + small.shape[0], x : x + small.shape[1]] = small
            writer.write(frame)
        writer.release()
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(silent),
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=730:sample_rate=48000:duration=4.4",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-shortest",
                str(self.video),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            self.fail(f"fixture ffmpeg failed: {result.stderr}")

    def test_detects_reference_dominant_insert_without_flagging_clean_product_shots(self):
        analysis = product_still_guard.analyze_video(
            self.video,
            [self.reference],
            sample_fps=4,
        )

        intervals = analysis["suspicious_intervals"]
        self.assertEqual(len(intervals), 1)
        self.assertLessEqual(intervals[0]["start_seconds"], 1.75)
        self.assertGreaterEqual(intervals[0]["end_seconds"], 2.55)
        self.assertGreater(intervals[0]["peak_inlier_count"], 50)

    def test_auto_repair_keeps_audio_and_duration_and_clears_detection(self):
        output = self.root / "repaired.mp4"
        report_path = self.root / "product_still_guard.json"

        report = product_still_guard.guard_video(
            self.video,
            [self.reference],
            output,
            report_path=report_path,
            sample_fps=4,
        )

        self.assertEqual(report["overall"], "PASS")
        self.assertEqual(report["status"], "repaired")
        self.assertTrue(output.is_file())
        self.assertEqual(
            report["audio_packet_sha256_before"],
            report["audio_packet_sha256_after"],
        )
        self.assertAlmostEqual(
            report["input_duration_seconds"],
            report["output_duration_seconds"],
            delta=0.12,
        )
        self.assertEqual(
            product_still_guard.analyze_video(
                output,
                [self.reference],
                sample_fps=4,
            )["suspicious_intervals"],
            [],
        )
        saved = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["output_sha256"], report["output_sha256"])

    def test_finishing_render_runs_guard_before_publishing_final_report(self):
        finishing = self.root / "output" / "job-001" / "finishing"
        final = self.root / "output" / "job-001" / "final"
        finishing.mkdir(parents=True)
        plan = finishing / "edit_plan.json"
        plan.write_text(
            json.dumps(
                {
                    "version": 1,
                    "executor": "local_ffmpeg",
                    "inputs": [{"id": "part1", "path": str(self.video)}],
                    "timeline": [
                        {
                            "input": "part1",
                            "start": 0,
                            "end": 4.4,
                            "speed": 1,
                        }
                    ],
                    "product_still_guard": {
                        "mode": "auto_repair",
                        "sample_fps": 4,
                        "references": [str(self.reference)],
                    },
                    "output": {
                        "filename": "final_video.mp4",
                        "audio_fade_out_seconds": 0,
                    },
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                "python3",
                str(FINISH_SCRIPT),
                "render",
                "--plan",
                str(plan),
                "--out-dir",
                str(final),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        if result.returncode != 0:
            self.fail(f"finishing render failed\n{result.stdout}\n{result.stderr}")
        report = json.loads((final / "finish_report.json").read_text(encoding="utf-8"))
        guard_binding = report["product_still_guard"]
        self.assertEqual(guard_binding["status"], "repaired")
        self.assertTrue(guard_binding["audio_preserved"])
        guard_report = Path(guard_binding["report"])
        self.assertTrue(guard_report.is_file())
        self.assertEqual(
            json.loads(guard_report.read_text(encoding="utf-8"))["output_sha256"],
            report["output_sha256"],
        )

    def test_finishing_init_discovers_approved_product_references(self):
        job_root = self.root / "output" / "job-002"
        finishing = job_root / "finishing"
        visual_assets = job_root / "visual-assets"
        finishing.mkdir(parents=True)
        visual_assets.mkdir(parents=True)
        (visual_assets / "approved_visual_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "reusable_refs": {"product_front": str(self.reference)},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        plan = finishing / "edit_plan.json"

        result = subprocess.run(
            [
                "python3",
                str(FINISH_SCRIPT),
                "init",
                "--input",
                str(self.video),
                "--plan",
                str(plan),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        if result.returncode != 0:
            self.fail(f"finishing init failed\n{result.stdout}\n{result.stderr}")
        created = json.loads(plan.read_text(encoding="utf-8"))
        guard = created["product_still_guard"]
        self.assertEqual(guard["mode"], "auto_repair")
        resolved = (plan.parent / guard["references"][0]).resolve()
        self.assertEqual(resolved, self.reference.resolve())


if __name__ == "__main__":
    unittest.main()
