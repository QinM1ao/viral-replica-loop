import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx


REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATOR = (
    REPO_ROOT
    / ".agents"
    / "skills"
    / "video-replication"
    / "scripts"
    / "generate.py"
)


def load_generator():
    spec = importlib.util.spec_from_file_location("matpool_generate", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MatpoolGenerateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generate = load_generator()

    def test_matpool_call_uses_configurable_long_read_timeout(self):
        response = mock.Mock(status_code=200)
        response.json.return_value = {"data": [{"b64_json": "eA=="}]}

        with mock.patch.object(self.generate.httpx, "post", return_value=response) as post:
            self.generate.matpool_call(
                {"base": "https://example.test/v1", "key": "secret", "model": "GPT-Image-2"},
                "prompt",
                "1024x1536",
                "medium",
                1,
                read_timeout_seconds=900,
            )

        timeout = post.call_args.kwargs["timeout"]
        self.assertIsInstance(timeout, httpx.Timeout)
        self.assertEqual(timeout.read, 900)

    def test_api_config_defaults_to_a_900_second_read_timeout(self):
        with (
            mock.patch.dict(
                os.environ,
                {"MATPOOL_API_KEY": "secret"},
                clear=True,
            ),
            mock.patch.object(self.generate, "load_config", return_value={}),
        ):
            config = self.generate.api_config()

        self.assertEqual(config["read_timeout_seconds"], 900)

    def test_read_timeout_is_an_unknown_provider_outcome(self):
        with mock.patch.object(
            self.generate.httpx,
            "post",
            side_effect=httpx.ReadTimeout("timed out"),
        ):
            with self.assertRaises(self.generate.MatpoolOutcomeUnknown):
                self.generate.matpool_call(
                    {"base": "https://example.test/v1", "key": "secret", "model": "GPT-Image-2"},
                    "prompt",
                    "1024x1536",
                    "medium",
                    1,
                    read_timeout_seconds=900,
                )

    def test_cli_records_timeout_as_stop_and_blocks_automatic_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "candidate.png"
            invocation = root / "invocation.json"
            argv = [
                str(GENERATOR),
                "--prompt",
                "prompt",
                "--file",
                str(output),
                "--invocation-manifest",
                str(invocation),
                "--read-timeout-seconds",
                "900",
            ]
            outcome_unknown = mock.Mock(
                side_effect=self.generate.MatpoolOutcomeUnknown(
                    "Matpool response timed out after request submission"
                )
            )
            with (
                mock.patch.dict(os.environ, {"MATPOOL_API_KEY": "secret"}, clear=False),
                mock.patch.object(self.generate.sys, "argv", argv),
                mock.patch.object(self.generate, "matpool_call", outcome_unknown),
            ):
                with self.assertRaises(SystemExit) as stopped:
                    self.generate.main()

            self.assertEqual(stopped.exception.code, 3)
            outcome_unknown.assert_called_once()
            evidence = json.loads(invocation.read_text(encoding="utf-8"))
            self.assertEqual(evidence["status"], "STOP")
            self.assertEqual(evidence["failure_kind"], "provider_result_unknown")
            self.assertEqual(evidence["provider_outcome"], "unknown")
            self.assertFalse(evidence["automatic_retry_allowed"])
            self.assertEqual(evidence["read_timeout_seconds"], 900)


if __name__ == "__main__":
    unittest.main()
