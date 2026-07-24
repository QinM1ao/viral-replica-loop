import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from seedance_request_contract import (  # noqa: E402
    build_taskcode_request,
    inspect_taskcode_request,
    reference_audio_urls,
    require_taskcode_request,
)


MODEL = "ep-20260521101914-nwv8j"
RUNNER = REPO_ROOT / "tools" / "seedance_taskcode_runner.py"


def provider_param(*, image_count=5, duration=11, prompt=None, with_audio=True):
    content = [
        {
            "type": "text",
            "text": prompt or "使用@图片1到@图片5，并参考@音频1生成视频。",
        }
    ]
    content.extend(
        {
            "type": "image_url",
            "image_url": {"url": f"https://example.com/image-{index}.png"},
            "role": "reference_image",
        }
        for index in range(1, image_count + 1)
    )
    if with_audio:
        content.append(
            {
                "type": "audio_url",
                "audio_url": {"url": "https://example.com/reference.mp3"},
                "role": "reference_audio",
            }
        )
    return {
        "model": MODEL,
        "content": content,
        "generate_audio": True,
        "ratio": "9:16",
        "duration": duration,
        "resolution": "720p",
        "watermark": False,
    }


class SeedanceTaskcodeRequestContractTest(unittest.TestCase):
    def test_builder_emits_the_provider_validated_wire_shape(self):
        request = build_taskcode_request(provider_param(), task_code=2509)

        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["body"]["taskCode"], 2509)
        self.assertEqual(request["body"]["acquireResourceTimeoutSeconds"], 60)
        self.assertIsInstance(request["body"]["param"], str)
        self.assertEqual(json.loads(request["body"]["param"])["duration"], 11)
        require_taskcode_request(request)

    def test_five_images_and_one_audio_use_independent_reference_namespaces(self):
        request = build_taskcode_request(provider_param(image_count=5), task_code=2509)

        report = inspect_taskcode_request(request)

        self.assertEqual(report["overall"], "PASS")
        self.assertEqual(report["metrics"]["image_count"], 5)
        self.assertEqual(report["metrics"]["audio_count"], 1)
        self.assertEqual(
            reference_audio_urls(request),
            ["https://example.com/reference.mp3"],
        )

    def test_prepared_audio_placeholder_passes_pack_qc_but_cannot_be_submitted(self):
        param = provider_param()
        param["content"][-1]["audio_url"]["url"] = (
            "asset://UPLOAD_PART2_01_REFERENCE_AUDIO"
        )
        request = build_taskcode_request(
            param,
            task_code=2509,
            metadata={"prepared_only": True, "do_not_submit": True},
        )

        self.assertEqual(inspect_taskcode_request(request)["overall"], "PASS")
        self.assertEqual(
            inspect_taskcode_request(request, for_submission=True)["overall"],
            "FAIL",
        )

    def test_prepared_flags_must_change_state_together(self):
        with self.assertRaisesRegex(ValueError, "submission_state"):
            build_taskcode_request(
                provider_param(),
                task_code=2509,
                metadata={"prepared_only": True},
            )

    def test_prepared_flags_must_be_booleans(self):
        request = build_taskcode_request(provider_param(), task_code=2509)
        request["prepared_only"] = "false"

        report = inspect_taskcode_request(request, for_submission=True)

        self.assertEqual(report["overall"], "FAIL")
        self.assertEqual(
            next(
                check
                for check in report["checks"]
                if check["name"] == "submission_state"
            )["status"],
            "FAIL",
        )

    def test_rejects_a_different_task_create_host(self):
        request = build_taskcode_request(provider_param(), task_code=2509)
        request["url"] = "https://example.com/task_create"

        report = inspect_taskcode_request(request)

        self.assertEqual(report["overall"], "FAIL")
        self.assertEqual(
            next(
                check
                for check in report["checks"]
                if check["name"] == "task_create_url"
            )["status"],
            "FAIL",
        )

    def test_rejects_a_dict_param_before_provider_submission(self):
        request = build_taskcode_request(provider_param(), task_code=2509)
        request["body"]["param"] = provider_param()

        report = inspect_taskcode_request(request)

        self.assertEqual(report["overall"], "FAIL")
        self.assertEqual(
            next(check for check in report["checks"] if check["name"] == "param_json_string")["status"],
            "FAIL",
        )

    def test_rejects_fractional_duration_before_provider_submission(self):
        request = build_taskcode_request(provider_param(), task_code=2509)
        param = json.loads(request["body"]["param"])
        param["duration"] = 10.8
        request["body"]["param"] = json.dumps(param)

        report = inspect_taskcode_request(request)

        self.assertEqual(report["overall"], "FAIL")
        self.assertEqual(
            next(check for check in report["checks"] if check["name"] == "integer_duration")["status"],
            "FAIL",
        )

    def test_rejects_prompt_image_index_above_the_actual_image_count(self):
        request = build_taskcode_request(provider_param(image_count=6), task_code=2509)
        param = json.loads(request["body"]["param"])
        param["content"][0]["text"] = "使用@图片1和@图片7生成视频。"
        request["body"]["param"] = json.dumps(param)

        report = inspect_taskcode_request(request)

        self.assertEqual(report["overall"], "FAIL")
        self.assertEqual(
            next(
                check
                for check in report["checks"]
                if check["name"] == "image_reference_bounds"
            )["status"],
            "FAIL",
        )

    def test_submission_runner_stops_locally_before_provider_on_contract_failure(self):
        request = build_taskcode_request(provider_param(), task_code=2509)
        request["body"]["param"] = provider_param()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_path = root / "request.json"
            out_dir = root / "evidence"
            request_path.write_text(json.dumps(request), encoding="utf-8")

            result = subprocess.run(
                [
                    "python3",
                    str(RUNNER),
                    "--request",
                    str(request_path),
                    "--out-dir",
                    str(out_dir),
                    "--output",
                    str(root / "part.mp4"),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 2)
            report = json.loads(
                (out_dir / "request_contract.json").read_text(encoding="utf-8")
            )
            self.assertEqual(report["overall"], "FAIL")
            self.assertEqual(
                report["request_sha256"],
                hashlib.sha256(request_path.read_bytes()).hexdigest(),
            )
            self.assertFalse((out_dir / "create_response.json").exists())


if __name__ == "__main__":
    unittest.main()
