import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from tools import prepare_story_analysis


class PrepareStoryAnalysisTest(unittest.TestCase):
    def test_cli_prepares_full_and_rapid_hook_reviews_in_parallel(self):
        worker_barrier = threading.Barrier(4)

        def fake_subprocess_run(command, **kwargs):
            if command[0] == "ffprobe":
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps({"format": {"duration": "4.0"}, "streams": []}),
                    stderr="",
                )

            worker_barrier.wait(timeout=2)
            joined = " ".join(str(part) for part in command)
            if command[0] == "ffmpeg":
                Path(command[-1]).write_bytes(b"contact-sheet")
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            out_dir = Path(command[command.index("--out-dir") + 1])
            out_dir.mkdir(parents=True, exist_ok=True)
            if "asr_transcribe.py" in joined:
                transcript = out_dir / "transcript.md"
                transcript.write_text("# ASR\n\n## Full Text\n\n黑头闭口涂。\n", encoding="utf-8")
                return subprocess.CompletedProcess(
                    command, 0, stdout=f"{transcript}\n", stderr=""
                )

            mode = command[command.index("--mode") + 1]
            analysis = out_dir / "analysis.json"
            analysis.write_text(
                json.dumps({"status": "PASS", "analysis_mode": mode}),
                encoding="utf-8",
            )
            for name in ["analysis.md", "request_manifest.json", "raw_response.json"]:
                (out_dir / name).write_text("{}\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout=f"{analysis}\n", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "source.mp4"
            story_dir = root / "story"
            video.write_bytes(b"video")
            argv = [
                "prepare_story_analysis.py",
                "--video",
                str(video),
                "--out-dir",
                str(story_dir),
                "--run-asr",
                "--rapid-hook-seconds",
                "3",
                "--rapid-hook-fps",
                "5",
            ]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                prepare_story_analysis.subprocess,
                "run",
                side_effect=fake_subprocess_run,
            ):
                prepare_story_analysis.main()

            self.assertTrue((story_dir / "asr" / "transcript.md").is_file())
            full = json.loads(
                (story_dir / "video_understanding" / "analysis.json").read_text(
                    encoding="utf-8"
                )
            )
            hook = json.loads(
                (
                    story_dir
                    / "video_understanding"
                    / "hook_review"
                    / "analysis.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(full["analysis_mode"], "full")
            self.assertEqual(hook["analysis_mode"], "rapid_hook")
            materials = (story_dir / "story_analysis_materials.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("hook_review/analysis.json", materials)


if __name__ == "__main__":
    unittest.main()
