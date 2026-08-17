import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "seedance25_output_dialogue_qc.py"


class Seedance25OutputDialogueQCTest(unittest.TestCase):
    def run_case(self, actual: str):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        fidelity = root / "fidelity.json"
        video = root / "video.mp4"
        manifest = root / "request_manifest.json"
        timeline = root / "timeline.json"
        output = root / "output.json"
        fidelity.write_text(
            json.dumps({"expected_transcript": "第一句最后一句必须说完"}, ensure_ascii=False),
            encoding="utf-8",
        )
        video.write_bytes(b"generated-video")
        import hashlib
        manifest.write_text(
            json.dumps({"source_sha256": hashlib.sha256(video.read_bytes()).hexdigest()}),
            encoding="utf-8",
        )
        timeline.write_text(
            json.dumps(
                {"words": [{"type": "word", "text": char} for char in actual]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                "python3",
                str(SCRIPT),
                "--source-fidelity-qc",
                str(fidelity),
                "--video",
                str(video),
                "--asr-request-manifest",
                str(manifest),
                "--asr-timeline",
                str(timeline),
                "--output",
                str(output),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        report = json.loads(output.read_text(encoding="utf-8"))
        temp.cleanup()
        return result.returncode, report

    def test_passes_exact_generated_dialogue(self):
        code, report = self.run_case("第一句最后一句必须说完")
        self.assertEqual(code, 0)
        self.assertEqual(report["overall"], "PASS")

    def test_rejects_truncated_ending(self):
        code, report = self.run_case("第一句最后一句")
        self.assertEqual(code, 2)
        self.assertEqual(report["overall"], "FAIL")
        self.assertEqual(report["checks"][2]["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
