import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FINAL_VIDEO_QC = REPO_ROOT / "tools" / "final_video_qc.py"


@unittest.skipIf(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    "ffmpeg/ffprobe not installed",
)
class SourceLockedDurationToleranceTest(unittest.TestCase):
    def test_complete_source_locked_speech_may_finish_slightly_over_source_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "final.mp4"
            out_dir = root / "qc"
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
                    "testsrc2=size=160x90:rate=10:duration=3.2",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=1000:sample_rate=44100:duration=3.2",
                    "-shortest",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    str(video),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            result = subprocess.run(
                [
                    "python3",
                    str(FINAL_VIDEO_QC),
                    "--videos",
                    str(video),
                    "--target-duration",
                    "2",
                    "--duration-tolerance",
                    "3",
                    "--out-dir",
                    str(out_dir),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            report = json.loads((out_dir / "final_qc.json").read_text(encoding="utf-8"))
            duration_check = next(
                check for check in report["checks"] if check["name"] == "duration"
            )

            self.assertEqual(duration_check["status"], "PASS")
            self.assertGreater(report["videos"][0]["duration"], 3.0)
            self.assertEqual(
                report["videos"][0]["sha256"],
                hashlib.sha256(video.read_bytes()).hexdigest(),
            )


if __name__ == "__main__":
    unittest.main()
