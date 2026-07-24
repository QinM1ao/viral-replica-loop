import json
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUEST_QC = REPO_ROOT / "tools" / "request_body_qc.py"
MODEL_CONFIG = REPO_ROOT / "rules" / "SEEDANCE_MODEL.json"
sys.path.insert(0, str(REPO_ROOT / "tools"))

from run_next_loop_round import preflight_pass_recording  # noqa: E402
from qc_risk_ledger import build_stage_ledger  # noqa: E402
from qc_input_binding import attach_input_binding  # noqa: E402


class RequestBodyQcTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.prompt = self.root / "prompt.txt"
        self.prompt.write_text(
            "参照@图片1生成15秒真实产品口播视频，保留操作声，镜头包含人物近景、产品特写和真实手部操作。",
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def write_request(
        self,
        model,
        *,
        duration=15,
        image_count=1,
        prompt_text=None,
        param_as_string=True,
        include_timeout=True,
    ):
        request = self.root / "request.json"
        param = {
            "model": model,
            "content": [
                {
                    "type": "text",
                    "text": prompt_text or self.prompt.read_text(encoding="utf-8"),
                },
                *[
                    {
                    "type": "image_url",
                    "role": "reference_image",
                    "image_url": {"url": f"https://example.com/reference-{index}.png"},
                    }
                    for index in range(1, image_count + 1)
                ],
            ],
            "generate_audio": True,
            "ratio": "9:16",
            "duration": duration,
            "resolution": "720p",
        }
        body = {
            "taskCode": 2509,
            "param": (
                json.dumps(param, ensure_ascii=False)
                if param_as_string
                else param
            ),
        }
        if include_timeout:
            body["acquireResourceTimeoutSeconds"] = 60
        payload = {
            "url": "https://higress-api.wujieai.com/wj-open/v2/open-platform/task/task_create",
            "method": "POST",
            "body": body,
        }
        request.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return request

    def run_qc(self, request):
        out_json = self.root / "request_qc.json"
        out_md = self.root / "request_qc.md"
        result = subprocess.run(
            [
                "python3",
                str(REQUEST_QC),
                "--requests",
                str(request),
                "--prompt-files",
                str(self.prompt),
                "--model-route-config",
                str(MODEL_CONFIG),
                "--allowed-task-codes",
                "2509",
                "--require-public-urls",
                "--expected-endpoint",
                "task_create",
                "--out-json",
                str(out_json),
                "--out-md",
                str(out_md),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            self.fail(f"request_body_qc failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        return json.loads(out_json.read_text(encoding="utf-8"))

    def check(self, report, name):
        return next(item for item in report["requests"][0]["checks"] if item["name"] == name)

    def test_passes_ordinary_seedance_20_model_ep_inside_param_json(self):
        report = self.run_qc(self.write_request("ep-20260521101914-nwv8j"))

        self.assertEqual(report["overall"], "PASS")
        self.assertEqual(self.check(report, "model_ep")["status"], "PASS")

    def test_fails_when_model_ep_is_not_selected_default(self):
        report = self.run_qc(self.write_request("ep-20260521101842-4q4lc"))

        self.assertEqual(report["overall"], "FAIL")
        self.assertEqual(self.check(report, "model_ep")["status"], "FAIL")

    def test_fails_when_gateway_param_is_not_a_json_string(self):
        report = self.run_qc(
            self.write_request(
                "ep-20260521101914-nwv8j",
                param_as_string=False,
            )
        )

        self.assertEqual(report["overall"], "FAIL")
        self.assertEqual(self.check(report, "param_json_string")["status"], "FAIL")

    def test_fails_when_acquire_resource_timeout_is_missing(self):
        report = self.run_qc(
            self.write_request(
                "ep-20260521101914-nwv8j",
                include_timeout=False,
            )
        )

        self.assertEqual(report["overall"], "FAIL")
        self.assertEqual(self.check(report, "acquire_resource_timeout")["status"], "FAIL")

    def test_fails_when_provider_duration_is_fractional(self):
        report = self.run_qc(
            self.write_request(
                "ep-20260521101914-nwv8j",
                duration=10.8,
            )
        )

        self.assertEqual(report["overall"], "FAIL")
        self.assertEqual(self.check(report, "integer_duration")["status"], "FAIL")

    def test_fails_when_prompt_references_a_nonexistent_image(self):
        report = self.run_qc(
            self.write_request(
                "ep-20260521101914-nwv8j",
                image_count=6,
                prompt_text="@图片1是分镜，@图片7是角色C，生成真实产品视频。",
            )
        )

        self.assertEqual(report["overall"], "FAIL")
        self.assertEqual(self.check(report, "image_reference_bounds")["status"], "FAIL")

class RequestQcRunnerPreflightTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.job = {"id": "job-001", "product_name": "generic product", "handoff_mode": "api"}
        self.decision = {"canonical_stage": "request_qc"}
        self.args = SimpleNamespace(record_gate_result="PASS", artifact="", dry_run=True)
        self.checks = self.root / "output/job-001/checks"
        self.requests = self.root / "output/job-001/seedance/requests"
        self.checks.mkdir(parents=True)
        self.requests.mkdir(parents=True)
        manifest = self.root / "output/job-001/visual-assets/approved_visual_manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps({"job_id": "job-001", "part_storyboards": {}}) + "\n",
            encoding="utf-8",
        )
        for name in [
            "request_qc_gate_review_qc.json",
            "request_qc_visual_asset_manifest_qc.json",
            "request_qc_cross_part_continuity_qc.json",
            "request_qc_storyboard_geometry_qc.json",
            "request_qc_seedance_prompt_contract_qc.json",
        ]:
            self.write_pass(self.checks / name)
        for name in [
            "request_qc_visual_asset_manifest_qc.json",
            "request_qc_cross_part_continuity_qc.json",
            "request_qc_storyboard_geometry_qc.json",
            "request_qc_seedance_prompt_contract_qc.json",
        ]:
            self.bind_report(self.checks / name, [manifest])

    def tearDown(self):
        self.tmp.cleanup()

    def write_pass(self, path):
        path.write_text(json.dumps({"overall": "PASS"}) + "\n", encoding="utf-8")

    def bind_report(self, path, inputs):
        report = json.loads(path.read_text(encoding="utf-8"))
        attach_input_binding(report, self.root, inputs)
        path.write_text(json.dumps(report) + "\n", encoding="utf-8")

    def test_runner_blocks_request_qc_pass_without_request_body_qc(self):
        with self.assertRaisesRegex(ValueError, "request body QC"):
            preflight_pass_recording(self.root, self.job, self.decision, self.args)

    def test_runner_accepts_request_qc_pass_with_request_body_qc(self):
        self.write_pass(self.requests / "request_qc.json")
        self.bind_report(
            self.requests / "request_qc.json",
            [self.root / "output/job-001/visual-assets/approved_visual_manifest.json"],
        )
        plan = build_stage_ledger(self.root, self.job, "request_qc", write=False)
        bindings = {
            item["name"]: item["fingerprint_hash"]
            for item in plan["semantic_review_request"]["families"]
        }
        (self.checks / "request_qc_gate_review_qc.json").write_text(
            json.dumps(
                {
                    "overall": "PASS",
                    "qc_risk_review": {"family_fingerprints": bindings},
                }
            )
            + "\n",
            encoding="utf-8",
        )

        preflight_pass_recording(self.root, self.job, self.decision, self.args)


if __name__ == "__main__":
    unittest.main()
