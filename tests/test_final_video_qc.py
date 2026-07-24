import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FINAL_VIDEO_QC = REPO_ROOT / "tools" / "final_video_qc.py"


@unittest.skipIf(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), "ffmpeg/ffprobe not installed")
class FinalVideoQcTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def ffmpeg(self, *args):
        result = subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            self.fail(f"ffmpeg failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")

    def make_normal_video(self, path, duration=2.0, audio=True):
        args = [
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size=160x90:rate=10:duration={duration}",
        ]
        if audio:
            args.extend([
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=1000:sample_rate=44100:duration={duration}",
                "-shortest",
                "-c:a",
                "aac",
            ])
        args.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)])
        self.ffmpeg(*args)

    def make_static_video(self, path, color):
        self.ffmpeg(
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:size=160x90:rate=10:duration=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:sample_rate=44100:duration=2",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        )

    def make_audio_only(self, path):
        self.ffmpeg(
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:sample_rate=44100:duration=2",
            "-c:a",
            "aac",
            str(path),
        )

    def run_qc(self, video, *extra_args, asr_text="孔凤春清洁泥膜"):
        out_dir = self.root / f"qc-{len(list(self.root.glob('qc-*')))}"
        asr = self.root / "asr.md"
        asr.write_text(asr_text, encoding="utf-8")
        result = subprocess.run(
            [
                "python3",
                str(FINAL_VIDEO_QC),
                "--videos",
                str(video),
                "--target-duration",
                "2",
                "--duration-tolerance",
                "0.35",
                "--brand-term",
                "孔凤春",
                "--asr-md",
                str(asr),
                "--out-dir",
                str(out_dir),
                *extra_args,
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            self.fail(f"final_video_qc failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        report = json.loads((out_dir / "final_qc.json").read_text(encoding="utf-8"))
        return report, out_dir

    def check(self, report, name):
        return next(item for item in report["checks"] if item["name"] == name)

    def test_pass_reports_streams_duration_and_contact_sheet(self):
        video = self.root / "normal.mp4"
        self.make_normal_video(video)

        report, out_dir = self.run_qc(video)

        self.assertEqual(report["overall"], "PASS")
        self.assertEqual(self.check(report, "video_files_exist")["status"], "PASS")
        self.assertEqual(self.check(report, "video_files_readable")["status"], "PASS")
        self.assertEqual(self.check(report, "video_stream_present")["status"], "PASS")
        self.assertEqual(self.check(report, "audio_stream_present")["status"], "PASS")
        self.assertEqual(self.check(report, "duration")["status"], "PASS")
        self.assertEqual(self.check(report, "contact_sheet")["status"], "PASS")
        self.assertEqual(
            report["videos"][0]["sha256"],
            hashlib.sha256(video.read_bytes()).hexdigest(),
        )
        self.assertTrue((out_dir / "contact_sheet.jpg").exists())

    def test_missing_file_stops(self):
        report, _ = self.run_qc(self.root / "missing.mp4")

        self.assertEqual(report["overall"], "STOP")
        self.assertEqual(self.check(report, "video_files_exist")["status"], "STOP")
        self.assertEqual(self.check(report, "video_files_readable")["status"], "PASS")

    def test_unreadable_file_stops(self):
        video = self.root / "not_video.mp4"
        video.write_text("not a media file", encoding="utf-8")

        report, _ = self.run_qc(video)

        self.assertEqual(report["overall"], "STOP")
        self.assertEqual(self.check(report, "video_files_readable")["status"], "STOP")

    def test_missing_video_stream_fails(self):
        video = self.root / "audio_only.mp4"
        self.make_audio_only(video)

        report, _ = self.run_qc(video)

        self.assertEqual(report["overall"], "FAIL")
        self.assertEqual(self.check(report, "video_stream_present")["status"], "FAIL")

    def test_missing_audio_stream_fails(self):
        video = self.root / "video_only.mp4"
        self.make_normal_video(video, audio=False)

        report, _ = self.run_qc(video)

        self.assertEqual(report["overall"], "FAIL")
        self.assertEqual(self.check(report, "audio_stream_present")["status"], "FAIL")

    def test_duration_failure(self):
        video = self.root / "normal.mp4"
        self.make_normal_video(video)

        report, _ = self.run_qc(video, "--target-duration", "5", "--duration-tolerance", "0.1")

        self.assertEqual(report["overall"], "FAIL")
        self.assertEqual(self.check(report, "duration")["status"], "FAIL")

    def test_freeze_event_fails(self):
        video = self.root / "static_blue.mp4"
        self.make_static_video(video, "blue")

        report, _ = self.run_qc(video)

        self.assertEqual(self.check(report, "freeze_detect")["status"], "FAIL")

    def test_source_comparison_fails_when_generated_video_adds_low_motion_holds(self):
        source = self.root / "source.mp4"
        generated = self.root / "generated.mp4"
        self.make_normal_video(source)
        self.make_static_video(generated, "blue")

        report, _ = self.run_qc(generated, "--source-video", str(source))

        check = self.check(report, "source_rhythm_low_motion")
        self.assertEqual(check["status"], "FAIL")
        self.assertIn("source=0", check["detail"])
        self.assertRegex(check["detail"], r"generated=[1-9]")

    def test_black_event_fails(self):
        video = self.root / "black.mp4"
        self.make_static_video(video, "black")

        report, _ = self.run_qc(video)

        self.assertEqual(self.check(report, "black_detect")["status"], "FAIL")

    def test_missing_asr_brand_term_fails(self):
        video = self.root / "normal.mp4"
        self.make_normal_video(video)

        report, _ = self.run_qc(video, asr_text="没有品牌词")

        self.assertEqual(report["overall"], "FAIL")
        self.assertEqual(self.check(report, "asr_contains:孔凤春")["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
