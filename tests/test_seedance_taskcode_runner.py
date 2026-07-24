import io
import json
import shutil
import sys
import tempfile
import unittest
import wave
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from seedance_taskcode_runner import (  # noqa: E402
    reference_audio_urls,
    validate_existing_preflight,
    validate_reference_audio_urls,
)


class FakeResponse:
    def __init__(self, content, status_code=200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    def __init__(self, payloads):
        self.payloads = payloads

    def get(self, url, **_kwargs):
        return FakeResponse(self.payloads[url])


def wav_bytes(duration_seconds=0.1):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(
            b"\x00\x00" * int(16000 * duration_seconds)
        )
    return output.getvalue()


class SeedanceTaskcodeRunnerAudioPreflightTest(unittest.TestCase):
    def request(self, url):
        param = {
            "content": [
                {"type": "text", "text": "test"},
                {"type": "audio_url", "audio_url": {"url": url}, "role": "reference_audio"},
            ]
        }
        return {"body": {"param": json.dumps(param)}}

    def test_extracts_reference_audio_from_serialized_param(self):
        url = "https://example.com/reference.mp3"
        self.assertEqual(reference_audio_urls(self.request(url)), [url])

    def test_rejects_http_200_empty_reference_audio_before_submission(self):
        url = "https://example.com/empty.mp3"
        with self.assertRaisesRegex(ValueError, "empty response body"):
            validate_reference_audio_urls(self.request(url), FakeClient({url: b""}))

    def test_existing_preflight_must_pass_and_match_request_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reference_audio_preflight.json"
            path.write_text(
                json.dumps(
                    {
                        "overall": "PASS",
                        "request_sha256": "expected",
                    }
                ),
                encoding="utf-8",
            )
            validate_existing_preflight(path, "expected")

            with self.assertRaisesRegex(ValueError, "request hash"):
                validate_existing_preflight(path, "changed")

            path.write_text(
                json.dumps(
                    {
                        "overall": "FAIL",
                        "request_sha256": "expected",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "not PASS"):
                validate_existing_preflight(path, "expected")

    @unittest.skipUnless(shutil.which("ffprobe"), "ffprobe is required")
    def test_accepts_decodable_reference_audio(self):
        url = "https://example.com/reference.wav"
        reports = validate_reference_audio_urls(
            self.request(url),
            FakeClient({url: wav_bytes()}),
        )

        self.assertEqual(reports[0]["byte_size"], len(wav_bytes()))
        self.assertEqual(reports[0]["codec_type"], "audio")

    @unittest.skipUnless(shutil.which("ffprobe"), "ffprobe is required")
    def test_rejects_reference_audio_over_fifteen_seconds(self):
        url = "https://example.com/too-long.wav"
        with self.assertRaisesRegex(ValueError, "15.00 seconds"):
            validate_reference_audio_urls(
                self.request(url),
                FakeClient({url: wav_bytes(15.1)}),
            )
