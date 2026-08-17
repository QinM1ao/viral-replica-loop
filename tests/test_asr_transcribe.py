import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import asr_transcribe


FIXTURE_RESULT = {
    "language_code": "zho",
    "language_probability": 1.0,
    "text": "你好。欢迎来。",
    "words": [
        {
            "text": "你",
            "start": 0.1,
            "end": 0.2,
            "type": "word",
            "speaker_id": "speaker_0",
            "logprob": -0.01,
        },
        {
            "text": "好",
            "start": 0.2,
            "end": 0.3,
            "type": "word",
            "speaker_id": "speaker_0",
            "logprob": -0.02,
        },
        {
            "text": "。",
            "start": 0.3,
            "end": 0.3,
            "type": "word",
            "speaker_id": "speaker_0",
            "logprob": -0.01,
        },
        {
            "text": "欢迎",
            "start": 0.8,
            "end": 1.0,
            "type": "word",
            "speaker_id": "speaker_1",
            "logprob": -0.03,
        },
        {
            "text": "来",
            "start": 1.0,
            "end": 1.1,
            "type": "word",
            "speaker_id": "speaker_1",
            "logprob": -0.01,
        },
        {
            "text": "。",
            "start": 1.1,
            "end": 1.1,
            "type": "word",
            "speaker_id": "speaker_1",
            "logprob": -0.01,
        },
        {
            "text": "(笑声)",
            "start": 1.2,
            "end": 1.4,
            "type": "audio_event",
            "speaker_id": None,
            "logprob": -0.1,
        },
    ],
    "transcription_id": "fixture-transcript",
    "audio_duration_secs": 1.4,
}


class FakeResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return FIXTURE_RESULT


class EmptyResponse(FakeResponse):
    def json(self):
        raise ValueError("empty response")


class FakeClient:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        file_tuple = kwargs["files"]["file"]
        self.calls.append(
            {
                "url": url,
                "headers": kwargs["headers"],
                "data": dict(kwargs["data"]),
                "filename": file_tuple[0],
                "file_bytes": file_tuple[1].read(),
                "content_type": file_tuple[2],
            }
        )
        return FakeResponse()


class EmptyThenReadyClient(FakeClient):
    def post(self, url, **kwargs):
        response = super().post(url, **kwargs)
        if len(self.calls) == 1:
            return EmptyResponse()
        return response


class AsrTranscribeTest(unittest.TestCase):
    def test_provider_check_stays_available_without_http_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "env"
            env_file.write_text("HIGRESS_API_KEY=fixture-key\n", encoding="utf-8")
            with mock.patch.object(asr_transcribe, "httpx", None):
                result = asr_transcribe.check_asr_provider(env_file=env_file)

        self.assertEqual(result, "elevenlabs:scribe_v1 via HIGRESS_API_KEY")

    def test_default_route_uses_production_higress_elevenlabs(self):
        config = asr_transcribe.load_config()

        self.assertEqual(config["model"], "scribe_v1")
        self.assertEqual(
            config["endpoint"],
            "https://higress-api.wujieai.com/elevenlabs/v1/speech-to-text",
        )
        self.assertTrue(config["diarize"])
        self.assertTrue(config["tag_audio_events"])
        self.assertEqual(config["timestamps_granularity"], "word")

    def test_request_writes_raw_result_timeline_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.wav"
            source.write_bytes(b"fixture-wave")
            out_dir = root / "asr"
            client = FakeClient()

            json_path = asr_transcribe.transcribe_elevenlabs(
                source,
                out_dir,
                api_key="fixture-key",
                client=client,
                num_speakers=2,
            )

            self.assertEqual(json.loads(json_path.read_text()), FIXTURE_RESULT)
            timeline = json.loads((out_dir / "asr_timeline.json").read_text())
            self.assertEqual(
                [turn["speaker_id"] for turn in timeline["speaker_turns"]],
                ["speaker_0", "speaker_1"],
            )
            self.assertEqual(
                [segment["text"] for segment in timeline["sentence_segments"]],
                ["你好。", "欢迎来。"],
            )
            self.assertEqual(timeline["audio_events"][0]["text"], "(笑声)")

            manifest = json.loads((out_dir / "request_manifest.json").read_text())
            self.assertEqual(manifest["http_status"], 200)
            self.assertEqual(manifest["model"], "scribe_v1")
            self.assertEqual(
                manifest["raw_response_sha256"],
                asr_transcribe.sha256_file(json_path),
            )
            self.assertEqual(
                manifest["timeline_sha256"],
                asr_transcribe.sha256_file(out_dir / "asr_timeline.json"),
            )
            self.assertNotIn("fixture-key", json.dumps(manifest))

            call = client.calls[0]
            self.assertEqual(
                call["url"],
                "https://higress-api.wujieai.com/elevenlabs/v1/speech-to-text",
            )
            self.assertEqual(call["headers"]["Authorization"], "Bearer fixture-key")
            self.assertEqual(
                call["data"],
                {
                    "model_id": "scribe_v1",
                    "language_code": "zh",
                    "diarize": "true",
                    "tag_audio_events": "true",
                    "timestamps_granularity": "word",
                    "num_speakers": "2",
                },
            )
            self.assertEqual(call["file_bytes"], b"fixture-wave")

    def test_empty_response_is_retried_once_in_the_same_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.wav"
            source.write_bytes(b"fixture-wave")
            client = EmptyThenReadyClient()

            with mock.patch.object(asr_transcribe.time, "sleep"):
                json_path = asr_transcribe.transcribe_elevenlabs(
                    source,
                    root / "asr",
                    api_key="fixture-key",
                    client=client,
                )

            self.assertEqual(len(client.calls), 2)
            self.assertEqual(json.loads(json_path.read_text()), FIXTURE_RESULT)

    def test_markdown_exposes_speakers_sentence_boundaries_and_raw_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            json_path = root / "elevenlabs_scribe_v1.json"
            json_path.write_text(json.dumps(FIXTURE_RESULT), encoding="utf-8")
            (root / "asr_timeline.json").write_text(
                json.dumps(asr_transcribe.build_timeline(FIXTURE_RESULT)),
                encoding="utf-8",
            )
            markdown_path = root / "原口播ASR_elevenlabs.md"

            asr_transcribe.write_markdown(json_path, markdown_path)

            markdown = markdown_path.read_text(encoding="utf-8")
            self.assertIn("## Full Text\n\n你好。欢迎来。", markdown)
            self.assertIn("speaker_0", markdown)
            self.assertIn("speaker_1", markdown)
            self.assertIn("0.10-0.30", markdown)
            self.assertIn("0.80-1.10", markdown)

    def test_spacing_tokens_do_not_split_speaker_turns(self):
        result = {
            "text": "hello world",
            "words": [
                {
                    "text": "hello",
                    "start": 0.0,
                    "end": 0.4,
                    "type": "word",
                    "speaker_id": "speaker_0",
                },
                {
                    "text": " ",
                    "start": 0.4,
                    "end": 0.4,
                    "type": "spacing",
                    "speaker_id": None,
                },
                {
                    "text": "world",
                    "start": 0.5,
                    "end": 0.9,
                    "type": "word",
                    "speaker_id": "speaker_0",
                },
            ],
        }

        timeline = asr_transcribe.build_timeline(result)

        self.assertEqual(len(timeline["speaker_turns"]), 1)
        self.assertEqual(timeline["speaker_turns"][0]["text"], "hello world")


if __name__ == "__main__":
    unittest.main()
