import sys
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from tools import pixmax_asset_library as pixmax


class PixmaxAssetLibraryTest(unittest.TestCase):
    def test_extract_id_from_supported_response_shapes(self):
        self.assertEqual(pixmax.extract_id({"Result": {"Id": "asset-1"}}), "asset-1")
        self.assertEqual(pixmax.extract_id({"data": {"Id": "asset-2"}}), "asset-2")
        self.assertEqual(pixmax.extract_id({"Id": "asset-3"}), "asset-3")

    def test_extract_status_from_supported_response_shapes(self):
        self.assertEqual(pixmax.extract_status({"Result": {"Status": "Active"}}), "Active")
        self.assertEqual(pixmax.extract_status({"data": {"status": "Failed"}}), "Failed")

    def test_validates_only_http_urls_for_asset_creation(self):
        self.assertTrue(pixmax.is_http_url("https://example.com/a.png"))
        self.assertFalse(pixmax.is_http_url("asset://asset-123"))
        self.assertFalse(pixmax.is_http_url("/tmp/a.png"))

    def test_rejects_uncommon_narrow_source_before_network_asset_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "narrow.png"
            out_json = root / "report.json"
            Image.new("RGB", (375, 1000), "white").save(source)
            argv = [
                "pixmax_asset_library.py",
                "--urls",
                "https://example.com/narrow.png",
                "--source-files",
                str(source),
                "--out-json",
                str(out_json),
            ]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                pixmax, "create_group"
            ) as create_group:
                with self.assertRaisesRegex(SystemExit, "non-standard aspect ratio"):
                    pixmax.main()
            create_group.assert_not_called()
            report = pixmax.json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(report["overall"], "FAIL")
            self.assertEqual(report["geometry_preflight"][0]["width"], 375)
            self.assertEqual(report["geometry_preflight"][0]["height"], 1000)
            self.assertEqual(report["geometry_preflight"][0]["status"], "FAIL")

    def test_accepts_standard_portrait_source_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "portrait.png"
            Image.new("RGB", (768, 1024), "white").save(source)
            result = pixmax.inspect_source_geometry([source])
            self.assertEqual(result[0]["matched_aspect"], "3:4")
            self.assertEqual(result[0]["status"], "PASS")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe required")
    def test_accepts_24fps_audio_free_depth_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "depth.mp4"
            subprocess.run(
                [
                    "ffmpeg", "-y", "-f", "lavfi", "-i", "color=black:s=180x320:r=24",
                    "-t", "0.5", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            report = pixmax.probe_source_video(video, require_no_audio=True)
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["fps"], 24.0)
            self.assertEqual(report["audio_stream_count"], 0)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe required")
    def test_rejects_20fps_depth_video_before_pixmax(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "depth20.mp4"
            subprocess.run(
                [
                    "ffmpeg", "-y", "-f", "lavfi", "-i", "color=black:s=180x320:r=20",
                    "-t", "0.5", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            report = pixmax.probe_source_video(video, require_no_audio=True)
            self.assertEqual(report["status"], "FAIL")
            self.assertIn("fps must be", report["reason"])


if __name__ == "__main__":
    unittest.main()
