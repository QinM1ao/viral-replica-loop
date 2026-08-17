import copy
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "product-fixtures" / "v1"
if not FIXTURE_ROOT.is_dir():
    FIXTURE_ROOT = ROOT.parent / "assets" / "fixtures" / "v1"
sys.path.insert(0, str(ROOT / "tools"))

from product_fixture_suite import (  # noqa: E402
    FixtureValidationError,
    validate_audible_av_pair,
    validate_fixture_suite,
    validate_pcm_u8,
    validate_y4m,
)
from provider_fixture_recorder import (  # noqa: E402
    RecorderStop,
    ZeroSubmissionRecorder,
    canonical_json_bytes,
    sha256_bytes,
)


class ProductFixtureSuiteTest(unittest.TestCase):
    def test_y4m_validation_rejects_probeable_media_with_trailing_frame_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            malformed = Path(tmp) / "trailing-frame-bytes.y4m"
            malformed.write_bytes(
                b"YUV4MPEG2 W2 H2 F2:1 Ip A1:1 Cmono\n"
                b"FRAME\nABCD\n"
                b"FRAME\nBCDE\n"
            )
            with self.assertRaisesRegex(
                FixtureValidationError, "does not fully decode"
            ):
                validate_y4m(
                    malformed,
                    expected_frames=2,
                    expected_duration=1.0,
                )

    def test_all_y4m_media_fully_decodes_with_exact_stream_duration_and_frames(self):
        expectations = {
            "core/source.y4m": {"frames": 2, "duration": 1.0},
            "finalization/part-01.y4m": {"frames": 2, "duration": 1.0},
            "finalization/part-02.y4m": {"frames": 2, "duration": 1.0},
            "finalization/final-master.y4m": {"frames": 4, "duration": 2.0},
        }
        for relative, expected in expectations.items():
            path = FIXTURE_ROOT / relative
            with self.subTest(path=relative):
                decoded = subprocess.run(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-xerror",
                        "-i",
                        str(path),
                        "-map",
                        "0:v:0",
                        "-f",
                        "null",
                        "-",
                    ],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(decoded.returncode, 0, decoded.stderr)

                probed = subprocess.run(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-count_frames",
                        "-show_entries",
                        (
                            "stream=codec_type,codec_name,pix_fmt,width,height,"
                            "r_frame_rate,nb_read_frames,duration"
                        ),
                        "-of",
                        "json",
                        str(path),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                streams = json.loads(probed.stdout)["streams"]
                self.assertEqual(len(streams), 1)
                self.assertEqual(
                    streams[0],
                    {
                        "codec_type": "video",
                        "codec_name": "rawvideo",
                        "pix_fmt": "gray",
                        "width": 2,
                        "height": 2,
                        "r_frame_rate": "2/1",
                        "duration": f"{expected['duration']:.6f}",
                        "nb_read_frames": str(expected["frames"]),
                    },
                )

    def test_audible_pcm_fully_decodes_and_matches_source_duration(self):
        path = FIXTURE_ROOT / "core" / "source_audio.pcm_u8"
        binding = json.loads(
            (FIXTURE_ROOT / "core" / "input_binding.json").read_text(
                encoding="utf-8"
            )
        )
        facts = binding["audio_facts"]

        report = validate_pcm_u8(
            path,
            sample_rate_hz=8000,
            channels=1,
            expected_samples=8000,
            expected_duration=1.0,
        )
        validate_audible_av_pair(
            FIXTURE_ROOT / "core" / "source_4s.mkv",
            FIXTURE_ROOT / "core" / "source_audio_4s.wav",
            expected_duration=facts["duration_seconds"],
            expected_samples=facts["sample_count"],
        )

        self.assertEqual(report["sample_count"], 8000)
        self.assertEqual(report["duration_seconds"], 1.0)
        self.assertGreater(report["rms_from_silence"], 8.0)
        self.assertGreater(report["peak_from_silence"], 16)

        with tempfile.TemporaryDirectory() as tmp:
            silent = Path(tmp) / "silent.pcm_u8"
            silent.write_bytes(bytes([128]) * 8000)
            with self.assertRaisesRegex(
                FixtureValidationError,
                "silent or lacks audible energy",
            ):
                validate_pcm_u8(
                    silent,
                    sample_rate_hz=8000,
                    channels=1,
                    expected_samples=8000,
                    expected_duration=1.0,
                )

    def test_suite_covers_all_families_with_complete_non_client_provenance(self):
        report = validate_fixture_suite(FIXTURE_ROOT)

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(
            report["fixture_families"],
            [
                "PF-01 core-audible-source-locked",
                "PF-02 branch-table",
                "PF-03 failure-mutations",
                "PF-04 local-finalization",
                "PF-05 sealed-independent-checker-verdicts",
            ],
        )
        origin = json.loads(
            (FIXTURE_ROOT / "fixture_origin.json").read_text(encoding="utf-8")
        )
        for fixture in origin["fixtures"]:
            self.assertTrue(fixture["non_client"])
            self.assertTrue(fixture["source"])
            self.assertTrue(fixture["license_or_authorization"])
            self.assertTrue(fixture["content_summary"])
            self.assertTrue(fixture["expected_logical_roles"])
            self.assertNotIn("customer", fixture["source"].lower())
            self.assertNotIn("workspace-dev", fixture["source"].lower())

        self.assertTrue(report["media"]["audible_source"])
        self.assertTrue(report["media"]["local_finishing"])
        self.assertTrue(report["media"]["final_technical_qc"])

    def test_layouts_reuse_exact_shared_contract_and_two_runs_are_stable(self):
        with mock.patch.object(
            socket.socket,
            "connect",
            side_effect=AssertionError("fixture validation attempted network access"),
        ):
            report = validate_fixture_suite(FIXTURE_ROOT)

        self.assertEqual(
            report["layout_bindings"]["LegacyLayout"],
            report["layout_bindings"]["CanonicalLayout"],
        )
        self.assertEqual(
            report["layout_runs"]["LegacyLayout"],
            report["layout_runs"]["CanonicalLayout"],
        )
        self.assertEqual(len(report["layout_runs"]["LegacyLayout"]), 2)
        self.assertEqual(
            report["layout_runs"]["LegacyLayout"][0],
            report["layout_runs"]["LegacyLayout"][1],
        )
        self.assertEqual(report["external_effects"], [])
        self.assertEqual(report["paid_task_count"], 0)
        self.assertEqual(report["media_generation_task_count"], 0)

    def test_recorder_replays_only_exact_bound_request_and_never_opens_network(self):
        request = json.loads(
            (FIXTURE_ROOT / "provider" / "request.json").read_text(encoding="utf-8")
        )
        recorder = ZeroSubmissionRecorder(
            FIXTURE_ROOT / "provider" / "recording.json",
            now="2026-07-30T12:00:00Z",
        )

        with mock.patch.object(
            socket.socket,
            "connect",
            side_effect=AssertionError("network access attempted"),
        ):
            response = recorder.replay(request)

        self.assertFalse(response["receipt"]["real_submit"])
        self.assertFalse(response["receipt"]["task_created"])
        self.assertEqual(response["receipt"]["paid_task_count"], 0)
        self.assertEqual(response["receipt"]["external_effects"], [])
        self.assertEqual(
            recorder.metrics(),
            {
                "matched_replay_count": 1,
                "unmatched_request_count": 0,
                "fallback_count": 0,
            },
        )

        mutations = json.loads(
            (FIXTURE_ROOT / "failures" / "single_variable_mutations.json").read_text(
                encoding="utf-8"
            )
        )
        for mutation in mutations["mutations"]:
            changed = copy.deepcopy(request)
            target = changed
            path = mutation["json_path"].split(".")
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = mutation["value"]
            with self.subTest(mutation=mutation["mutation_id"]):
                with self.assertRaises(RecorderStop) as raised:
                    recorder.replay(changed)
                self.assertEqual(raised.exception.code, mutation["expected_stop_code"])
        self.assertGreaterEqual(
            recorder.metrics()["unmatched_request_count"],
            1,
        )
        self.assertEqual(recorder.metrics()["fallback_count"], 0)

    def test_recording_summary_must_match_canonical_frozen_request_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp) / "v1"
            shutil.copytree(FIXTURE_ROOT, copied)
            request = json.loads(
                (copied / "provider" / "request.json").read_text(encoding="utf-8")
            )
            changed_request = copy.deepcopy(request)
            changed_request["provider"]["model"] = "unbound-model"

            recording_path = copied / "provider" / "recording.json"
            recording = json.loads(recording_path.read_text(encoding="utf-8"))
            recording["request_summary_sha256"] = sha256_bytes(
                canonical_json_bytes(changed_request)
            )
            recording["seal_sha256"] = sha256_bytes(
                canonical_json_bytes(
                    {
                        "kind": recording["kind"],
                        "request_summary_sha256": recording[
                            "request_summary_sha256"
                        ],
                        "response_summary_sha256": recording[
                            "response_summary_sha256"
                        ],
                        "valid_until": recording["valid_until"],
                    }
                )
            )
            recording_path.write_text(
                json.dumps(recording, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(RecorderStop) as raised:
                ZeroSubmissionRecorder(
                    recording_path,
                    now="2026-07-30T12:00:00Z",
                )
            self.assertEqual(raised.exception.code, "recording_invalid")
            self.assertIn("request summary", raised.exception.detail)

    def test_invalid_or_client_derived_fixture_metadata_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp) / "v1"
            shutil.copytree(FIXTURE_ROOT, copied)
            manifest_path = copied / "fixture_origin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["fixtures"][0]["non_client"] = False
            manifest["fixtures"][0]["source"] = "historical customer Job"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(FixtureValidationError):
                validate_fixture_suite(copied)


if __name__ == "__main__":
    unittest.main()
