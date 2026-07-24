import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

from tools import video_understanding


class VideoUnderstandingTest(unittest.TestCase):
    def test_rapid_hook_review_saves_auditable_physical_change_evidence(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg is required for focused video review")

        model_output = {
            "summary": "开头依次展示问题、鼻部上脸涂、第二个问题、下巴上脸涂。",
            "timeline": [
                {
                    "start_seconds": 0.6,
                    "end_seconds": 1.133,
                    "visual_action": "泥膜棒接触鼻部并划过，鼻部留下可见泥膜。",
                    "visual_action_type": "physical_change",
                    "physical_change_evidence": {
                        "contact_visible": True,
                        "motion_visible": True,
                        "state_before": "鼻部未涂泥膜",
                        "state_after": "鼻部出现泥膜",
                        "visible_result": "鼻部留有连续泥膜痕迹",
                    },
                    "confidence": 0.97,
                }
            ],
            "uncertainties": [],
        }

        def handler(request):
            payload = json.loads(request.content)
            video_item, prompt_item = payload["messages"][0]["content"]
            self.assertEqual(video_item["video_url"]["fps"], 5)
            self.assertIn("接触", prompt_item["text"])
            self.assertIn("动作过程", prompt_item["text"])
            self.assertIn("动作后状态", prompt_item["text"])
            return httpx.Response(
                200,
                json={
                    "id": "rapid-hook-response",
                    "choices": [{"message": {"content": json.dumps(model_output)}}],
                    "usage": {"total_tokens": 456},
                },
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "source.mp4"
            out_dir = root / "hook-review"
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=white:s=160x284:d=4",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(video),
                ],
                check=True,
            )
            client = httpx.Client(transport=httpx.MockTransport(handler))
            with mock.patch.dict(
                os.environ,
                {"HIGRESS_API_KEY": "test-key", "PATH": os.environ.get("PATH", "")},
                clear=True,
            ):
                result = video_understanding.understand_video(
                    video,
                    out_dir,
                    client=client,
                    mode="rapid_hook",
                    fps=5,
                    start_seconds=0,
                    duration_seconds=3,
                )
            client.close()

            manifest = json.loads(
                (out_dir / "request_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(result["analysis_mode"], "rapid_hook")
            self.assertEqual(result["sampling_fps"], 5)
            self.assertEqual(
                result["source_segment"],
                {"start_seconds": 0.0, "end_seconds": 3.0, "timebase": "source_absolute"},
            )
            self.assertTrue(result["submitted_video"]["used_segment"])
            self.assertNotEqual(result["source_sha256"], result["submitted_video"]["sha256"])
            self.assertEqual(manifest["http_status"], 200)
            self.assertGreaterEqual(manifest["gateway_duration_seconds"], 0)
            self.assertGreaterEqual(manifest["total_duration_seconds"], 0)

    def test_env_file_is_parsed_without_executing_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "env"
            env_file.write_text(
                "export HIGRESS_API_KEY='test-key'\nIGNORED=$(touch /tmp/nope)\n",
                encoding="utf-8",
            )
            key, source = video_understanding.resolve_api_key(env={}, env_file=env_file)
        self.assertEqual(key, "test-key")
        self.assertEqual(source, "HIGRESS_API_KEY")

    def test_payload_uses_official_video_url_content_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "source.mp4"
            video.write_bytes(b"video-bytes")
            config = video_understanding.load_config()
            payload = video_understanding.build_payload(video, config)

        self.assertEqual(payload["model"], "doubao-seed-2-0-mini-260215")
        content = payload["messages"][0]["content"]
        self.assertEqual(content[0]["type"], "video_url")
        self.assertEqual(content[0]["video_url"]["fps"], 2)
        self.assertTrue(content[0]["video_url"]["url"].startswith("data:video/mp4;base64,"))
        self.assertEqual(content[1]["type"], "text")

    def test_understand_video_saves_evidence_without_secret_or_base64(self):
        model_output = {
            "summary": "A presenter demonstrates a product.",
            "story_structure": ["hook", "demo"],
            "timeline": [],
            "uncertainties": [],
        }

        def handler(request):
            payload = json.loads(request.content)
            self.assertEqual(payload["model"], "doubao-seed-2-0-mini-260215")
            self.assertIn("data:video/mp4;base64,", payload["messages"][0]["content"][0]["video_url"]["url"])
            return httpx.Response(
                200,
                json={
                    "id": "response-1",
                    "choices": [{"message": {"content": json.dumps(model_output)}}],
                    "usage": {"total_tokens": 123},
                },
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "source.mp4"
            out_dir = root / "understanding"
            video.write_bytes(b"small-video")
            client = httpx.Client(transport=httpx.MockTransport(handler))
            with mock.patch.dict(os.environ, {"HIGRESS_API_KEY": "super-secret"}, clear=True):
                result = video_understanding.understand_video(video, out_dir, client=client)
            client.close()

            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["analysis"]["summary"], model_output["summary"])
            manifest_text = (out_dir / "request_manifest.json").read_text(encoding="utf-8")
            self.assertNotIn("super-secret", manifest_text)
            self.assertNotIn("data:video", manifest_text)
            self.assertTrue((out_dir / "analysis.md").is_file())
            self.assertTrue((out_dir / "raw_response.json").is_file())

    def test_parse_json_content_accepts_fenced_json(self):
        parsed = video_understanding.parse_json_content("```json\n{\"summary\": \"ok\"}\n```")
        self.assertEqual(parsed, {"summary": "ok"})

    def test_transport_failure_is_retried_once(self):
        calls = []

        def handler(request):
            calls.append(request)
            if len(calls) == 1:
                raise httpx.ConnectError("temporary", request=request)
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "{\"summary\":\"ok\",\"timeline\":[]}"}}]},
            )

        config = video_understanding.load_config()
        client = httpx.Client(transport=httpx.MockTransport(handler))
        with mock.patch.object(video_understanding.time, "sleep"):
            response, status, _ = video_understanding.call_gateway(
                {"model": config["model"]}, config, "test-key", client=client
            )
        client.close()
        self.assertEqual(status, 200)
        self.assertEqual(len(calls), 2)
        self.assertIn("choices", response)


if __name__ == "__main__":
    unittest.main()
