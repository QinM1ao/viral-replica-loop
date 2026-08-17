import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tools" / "run_face_expression_detector.py"


class FaceExpressionRuntimeTest(unittest.TestCase):
    def test_check_uses_project_local_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp)
            runtime_python = (
                runtime_root / ".venv-face-expression" / "bin" / "python"
            )
            runtime_python.parent.mkdir(parents=True)
            runtime_python.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' "
                "'{\"mediapipe\":\"0.10.21\","
                "\"opencv\":\"4.11.0\",\"numpy\":\"1.26.4\"}'\n",
                encoding="utf-8",
            )
            runtime_python.chmod(0o755)

            result = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--runtime-root",
                    str(runtime_root),
                    "--check",
                ],
                text=True,
                capture_output=True,
                env={**os.environ, "PYTHONNOUSERSITE": "1"},
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(Path(payload["python"]), runtime_python.resolve())
        self.assertEqual(payload["mediapipe"], "0.10.21")


if __name__ == "__main__":
    unittest.main()
