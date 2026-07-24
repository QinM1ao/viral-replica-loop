import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "build_part_storyboards.py"


class BuildPartStoryboardsTest(unittest.TestCase):
    @unittest.skipIf(not shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_source_rhythm_sampling_preserves_each_must_keep_action_peak(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video_path = root / "source.mp4"
            output_dir = root / "storyboards"
            rhythm_path = root / "source_rhythm.json"
            make_video = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=160x284:r=25:d=4",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(video_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(make_video.returncode, 0, make_video.stderr)

            rhythm_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "duration": 4.0,
                        "beats": [
                            {
                                "id": f"sr00{index + 1}",
                                "source_start": float(index),
                                "source_end": float(index + 1),
                                "action_peak_times": [index + 0.2],
                                "replication_priority": "must_keep",
                            }
                            for index in range(4)
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--input",
                    str(video_path),
                    "--output",
                    str(output_dir),
                    "--total-frames",
                    "4",
                    "--groups",
                    "1",
                    "--source-rhythm",
                    str(rhythm_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(
                (output_dir / "source_storyboard_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(manifest["selection_mode"], "source_rhythm")
            selected = manifest["parts"][0]["selected_frames"]
            self.assertEqual(
                [round(frame["time"], 1) for frame in selected],
                [0.2, 1.2, 2.2, 3.2],
            )
            self.assertEqual(
                [frame["source_beat_ids"] for frame in selected],
                [["sr001"], ["sr002"], ["sr003"], ["sr004"]],
            )

    @unittest.skipIf(not shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_cross_part_beat_is_selected_once_in_the_action_peak_part(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video_path = root / "source.mp4"
            output_dir = root / "storyboards"
            rhythm_path = root / "source_rhythm.json"
            make_video = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=160x284:r=25:d=4",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(video_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(make_video.returncode, 0, make_video.stderr)
            rhythm_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "duration": 4.0,
                        "beats": [
                            {
                                "id": "sr001",
                                "source_start": 0.0,
                                "source_end": 1.0,
                                "action_peak_times": [0.5],
                                "replication_priority": "must_keep",
                            },
                            {
                                "id": "sr002",
                                "source_start": 1.8,
                                "source_end": 2.5,
                                "action_peak_times": [2.2],
                                "replication_priority": "must_keep",
                            },
                            {
                                "id": "sr003",
                                "source_start": 3.0,
                                "source_end": 4.0,
                                "action_peak_times": [3.5],
                                "replication_priority": "must_keep",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--input",
                    str(video_path),
                    "--output",
                    str(output_dir),
                    "--total-frames",
                    "4",
                    "--groups",
                    "2",
                    "--source-rhythm",
                    str(rhythm_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(
                (output_dir / "source_storyboard_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            part1, part2 = manifest["parts"]
            beat_ids = [
                beat_id
                for part in manifest["parts"]
                for frame in part["selected_frames"]
                for beat_id in frame["source_beat_ids"]
            ]
            self.assertEqual(beat_ids.count("sr002"), 1)
            self.assertTrue(all(frame["time"] < 2.0 for frame in part1["selected_frames"]))
            self.assertTrue(all(frame["time"] >= 2.0 for frame in part2["selected_frames"]))

    @unittest.skipIf(not shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_coverage_fill_frames_are_distributed_across_the_whole_part(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video_path = root / "source.mp4"
            output_dir = root / "storyboards"
            rhythm_path = root / "source_rhythm.json"
            make_video = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=160x284:r=25:d=4",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(video_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(make_video.returncode, 0, make_video.stderr)
            rhythm_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "duration": 4.0,
                        "beats": [
                            {
                                "id": "sr001",
                                "source_start": 0.0,
                                "source_end": 1.0,
                                "action_peak_times": [0.5],
                                "replication_priority": "must_keep",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--input",
                    str(video_path),
                    "--output",
                    str(output_dir),
                    "--total-frames",
                    "4",
                    "--groups",
                    "1",
                    "--source-rhythm",
                    str(rhythm_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(
                (output_dir / "source_storyboard_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            selected_times = [
                frame["time"]
                for frame in manifest["parts"][0]["selected_frames"]
            ]
            self.assertTrue(any(time < 2.0 for time in selected_times))
            self.assertTrue(any(time > 2.0 for time in selected_times))

    @unittest.skipIf(not shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_storyboard_exclusions_skip_source_editing_errors_and_keep_secondary_peaks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video_path = root / "source.mp4"
            output_dir = root / "storyboards"
            rhythm_path = root / "source_rhythm.json"
            make_video = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=160x284:r=25:d=4",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(video_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(make_video.returncode, 0, make_video.stderr)
            rhythm_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "duration": 4.0,
                        "storyboard_exclusion_ranges": [
                            {
                                "start": 3.4,
                                "end": 4.0,
                                "reason": "single_frame_source_edit_error",
                            }
                        ],
                        "beats": [
                            {
                                "id": "sr001",
                                "source_start": 0.0,
                                "source_end": 2.0,
                                "action_peak_times": [0.5, 1.5],
                                "replication_priority": "must_keep",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--input",
                    str(video_path),
                    "--output",
                    str(output_dir),
                    "--total-frames",
                    "4",
                    "--groups",
                    "1",
                    "--source-rhythm",
                    str(rhythm_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(
                (output_dir / "source_storyboard_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            selected = manifest["parts"][0]["selected_frames"]
            self.assertIn(1.5, [frame["time"] for frame in selected])
            self.assertTrue(
                any(
                    frame["time"] == 1.5
                    and frame["selection_reason"] == "secondary_action_peak"
                    for frame in selected
                )
            )
            self.assertTrue(
                all(not 3.4 <= frame["time"] <= 4.0 for frame in selected)
            )
            self.assertEqual(
                manifest["storyboard_exclusion_ranges"][0]["reason"],
                "single_frame_source_edit_error",
            )


if __name__ == "__main__":
    unittest.main()
