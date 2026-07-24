import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "finish_video.py"


@unittest.skipIf(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), "ffmpeg/ffprobe not installed")
class FinishVideoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.part1 = self.root / "part1.mp4"
        self.part2 = self.root / "part2.mp4"
        self.make_video(self.part1, duration=2.0, frequency=700)
        self.make_video(self.part2, duration=2.0, frequency=900)

    def tearDown(self):
        self.tmp.cleanup()

    def run_command(self, *args, check=True):
        result = subprocess.run(
            ["python3", str(SCRIPT), *args],
            text=True,
            capture_output=True,
            check=False,
        )
        if check and result.returncode != 0:
            self.fail(f"finish_video failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        return result

    def make_video(self, path, duration, frequency):
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"testsrc2=size=160x90:rate=10:duration={duration}",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={frequency}:sample_rate=48000:duration={duration}",
                "-shortest",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(path),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            self.fail(f"fixture ffmpeg failed: {result.stderr}")

    def duration(self, path):
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            text=True,
            capture_output=True,
            check=True,
        )
        return float(result.stdout.strip())

    def write_plan(self, timeline, **extra):
        plan = {
            "version": 1,
            "inputs": [
                {"id": "part1", "path": self.part1.name},
                {"id": "part2", "path": self.part2.name},
            ],
            "timeline": timeline,
            "output": {"filename": "final_video.mp4", "audio_fade_out_seconds": 0.2},
        }
        plan.update(extra)
        path = self.root / "edit_plan.json"
        path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        return path

    def test_init_then_render_joins_complete_parts(self):
        plan = self.root / "edit_plan.json"
        self.run_command(
            "init",
            "--input",
            str(self.part1),
            "--input",
            str(self.part2),
            "--plan",
            str(plan),
        )

        created = json.loads(plan.read_text(encoding="utf-8"))
        self.assertEqual(created["executor"], "local_ffmpeg")
        self.assertEqual([item["input"] for item in created["timeline"]], ["part1", "part2"])
        self.assertEqual(created["timeline"][0]["start"], 0.0)
        self.assertAlmostEqual(created["timeline"][0]["end"], 2.0, delta=0.1)

        out_dir = self.root / "finishing"
        self.run_command("render", "--plan", str(plan), "--out-dir", str(out_dir))

        output = out_dir / "final_video.mp4"
        report = json.loads((out_dir / "finish_report.json").read_text(encoding="utf-8"))
        self.assertTrue(output.exists())
        self.assertEqual(report["overall"], "PASS")
        self.assertAlmostEqual(self.duration(output), 4.0, delta=0.25)

    def test_render_keeps_explicit_ranges_and_applies_speed(self):
        plan = self.write_plan(
            [
                {"input": "part1", "start": 0.0, "end": 1.0, "speed": 1.0},
                {"input": "part2", "start": 0.5, "end": 1.5, "speed": 2.0},
            ]
        )

        out_dir = self.root / "finishing"
        self.run_command("render", "--plan", str(plan), "--out-dir", str(out_dir))

        report = json.loads((out_dir / "finish_report.json").read_text(encoding="utf-8"))
        self.assertAlmostEqual(report["expected_duration"], 1.5, delta=0.01)
        self.assertAlmostEqual(self.duration(out_dir / "final_video.mp4"), 1.5, delta=0.25)

    def test_local_finishing_rejects_subtitles(self):
        subtitle = self.root / "captions.srt"
        subtitle.write_text(
            "1\n00:00:00,100 --> 00:00:00,900\nMVP caption\n",
            encoding="utf-8",
        )
        plan = self.write_plan(
            [{"input": "part1", "start": 0.0, "end": 1.0, "speed": 1.0}],
            subtitles={"path": subtitle.name},
        )

        out_dir = self.root / "finishing"
        result = self.run_command(
            "render", "--plan", str(plan), "--out-dir", str(out_dir), check=False
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("caption-free", result.stderr)
        self.assertIn("caption_finishing", result.stderr)
        self.assertFalse((out_dir / "final_video.mp4").exists())

    def test_report_binds_current_plan_and_output_hashes(self):
        plan = self.write_plan(
            [{"input": "part1", "start": 0.0, "end": 1.0, "speed": 1.0}]
        )
        out_dir = self.root / "finishing"

        self.run_command("render", "--plan", str(plan), "--out-dir", str(out_dir))

        output = out_dir / "final_video.mp4"
        report = json.loads((out_dir / "finish_report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["plan_sha256"], hashlib.sha256(plan.read_bytes()).hexdigest())
        self.assertEqual(report["output_sha256"], hashlib.sha256(output.read_bytes()).hexdigest())

    def test_failed_rerender_invalidates_old_pass_reports(self):
        plan = self.write_plan(
            [{"input": "part1", "start": 0.0, "end": 1.0, "speed": 1.0}]
        )
        out_dir = self.root / "finishing"
        self.run_command("render", "--plan", str(plan), "--out-dir", str(out_dir))
        self.assertTrue((out_dir / "finish_report.json").exists())

        bad_plan = json.loads(plan.read_text(encoding="utf-8"))
        bad_plan["timeline"][0]["end"] = 3.0
        plan.write_text(json.dumps(bad_plan, indent=2) + "\n", encoding="utf-8")
        result = self.run_command(
            "render", "--plan", str(plan), "--out-dir", str(out_dir), check=False
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((out_dir / "finish_report.json").exists())
        self.assertFalse((out_dir / "finish_report.md").exists())

    def test_mismatched_aspect_ratio_is_rejected_instead_of_stretched(self):
        portrait = self.root / "portrait.mp4"
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc2=size=90x160:rate=10:duration=1",
                "-f", "lavfi", "-i", "sine=frequency=500:sample_rate=48000:duration=1",
                "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", str(portrait),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            self.fail(f"fixture ffmpeg failed: {result.stderr}")
        plan = self.root / "mixed-plan.json"
        plan.write_text(
            json.dumps(
                {
                    "version": 1,
                    "inputs": [
                        {"id": "landscape", "path": self.part1.name},
                        {"id": "portrait", "path": portrait.name},
                    ],
                    "timeline": [
                        {"input": "landscape", "start": 0, "end": 1, "speed": 1},
                        {"input": "portrait", "start": 0, "end": 1, "speed": 1},
                    ],
                    "output": {"filename": "final_video.mp4"},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        result = self.run_command(
            "render", "--plan", str(plan), "--out-dir", str(self.root / "mixed"), check=False
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("aspect ratio", result.stderr)

    def test_noncanonical_output_filename_is_rejected(self):
        plan = self.write_plan(
            [{"input": "part1", "start": 0.0, "end": 1.0, "speed": 1.0}]
        )
        value = json.loads(plan.read_text(encoding="utf-8"))
        value["output"]["filename"] = "alternate.mp4"
        plan.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

        result = self.run_command(
            "render", "--plan", str(plan), "--out-dir", str(self.root / "final"), check=False
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("final_video.mp4", result.stderr)

    def test_any_subtitle_configuration_is_rejected_as_plan_error(self):
        subtitle = self.root / "captions.srt"
        subtitle.write_text(
            "1\n00:00:00,100 --> 00:00:00,900\nCaption\n",
            encoding="utf-8",
        )
        plan = self.write_plan(
            [{"input": "part1", "start": 0.0, "end": 1.0, "speed": 1.0}],
            subtitles={"path": subtitle.name, "font_size": -10},
        )

        result = self.run_command(
            "render", "--plan", str(plan), "--out-dir", str(self.root / "final"), check=False
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("caption-free", result.stderr)

    def test_invalid_segment_is_rejected_before_render(self):
        plan = self.write_plan(
            [{"input": "part1", "start": 1.5, "end": 2.5, "speed": 1.0}]
        )

        result = self.run_command(
            "render",
            "--plan",
            str(plan),
            "--out-dir",
            str(self.root / "finishing"),
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exceeds input duration", result.stderr)
        self.assertFalse((self.root / "finishing" / "final_video.mp4").exists())


if __name__ == "__main__":
    unittest.main()
