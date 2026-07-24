import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "source_rhythm_qc.py"
PREPARE_SCRIPT = REPO_ROOT / "tools" / "prepare_source_rhythm.py"
sys.path.insert(0, str(REPO_ROOT / "tools"))

from source_rhythm_qc import check_director_plan


class SourceRhythmQCTest(unittest.TestCase):
    def run_qc(self, root, payload, *extra_args):
        rhythm_path = root / "source_rhythm.json"
        report_path = root / "source_rhythm_qc.json"
        rhythm_path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--source-rhythm",
                str(rhythm_path),
                "--json-out",
                str(report_path),
                *extra_args,
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        return result, json.loads(report_path.read_text(encoding="utf-8"))

    def test_report_binds_the_exact_source_rhythm_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = {"schema_version": 1, "beats": []}
            unused_result, report = self.run_qc(root, payload)
            rhythm_path = root / "source_rhythm.json"

            self.assertEqual(
                report["source_rhythm_sha256"],
                hashlib.sha256(rhythm_path.read_bytes()).hexdigest(),
            )

    def test_rejects_confirmed_line_that_changes_evidence_backed_hook_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rhythm_path = root / "source_rhythm.json"
            report_path = root / "source_rhythm_qc.json"
            rhythm_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "beats": [
                            {
                                "id": "beat-001",
                                "source_start": 0.0,
                                "source_end": 1.7,
                                "evidence": {
                                    "asr_text": "黑头闭口涂油皮粉丝涂",
                                    "visible_text": ["黑头闭口", "涂", "油皮粉刺", "涂"],
                                },
                                "corrections": [
                                    {
                                        "from": "粉丝",
                                        "to": "粉刺",
                                        "evidence_type": "visible_text",
                                    }
                                ],
                                "confirmed_source_line": "黑头闭口脸，油皮粉刺脸！",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--source-rhythm",
                    str(rhythm_path),
                    "--json-out",
                    str(report_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["overall"], "FAIL")
            self.assertEqual(report["issues"][0]["code"], "confirmed_line_mismatch")
            self.assertEqual(report["issues"][0]["expected"], "黑头闭口涂油皮粉刺涂")
            self.assertEqual(report["issues"][0]["actual"], "黑头闭口脸油皮粉刺脸")

    def test_rejects_mechanical_rhythm_file_before_beats_are_authored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result, report = self.run_qc(
                root,
                {
                    "schema_version": 1,
                    "duration": 3.0,
                    "actual_cut_points": [],
                    "source_evidence": {
                        "asr_text": "看好了",
                        "subtitle_observations": [],
                    },
                    "beats": [],
                },
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("missing_source_beats", [issue["code"] for issue in report["issues"]])

    def test_rejects_action_command_without_physical_state_change_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result, report = self.run_qc(
                root,
                {
                    "schema_version": 2,
                    "duration": 1.0,
                    "actual_cut_points": [],
                    "source_evidence": {
                        "asr_text": "涂",
                        "subtitle_observations": [],
                    },
                    "beats": [
                        {
                            "id": "sr002",
                            "source_start": 0.0,
                            "source_end": 1.0,
                            "asr_span": {"start": 0, "end": 1},
                            "confirmed_source_line": "涂！",
                            "speaker_mode": "voiceover",
                            "emphasis_tokens": ["涂"],
                            "pause_after_seconds": 0.0,
                            "action_peak_times": [0.5],
                            "visual_action": "动态大字‘涂’闪现并切换问题部位",
                            "visual_action_type": "physical_change",
                            "emotion_function": "命令式单字重音",
                            "rhythm_class": "rapid_hook",
                            "replication_priority": "must_keep",
                            "evidence_frame_refs": [
                                "frame_before.jpg",
                                "frame_peak.jpg",
                                "frame_after.jpg",
                            ],
                            "entry_transition": "source_start",
                            "exit_transition": "source_end",
                        }
                    ],
                },
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn(
                "missing_physical_action_evidence",
                [issue["code"] for issue in report["issues"]],
            )

    def test_rejects_silent_physical_change_without_state_change_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result, report = self.run_qc(
                root,
                {
                    "schema_version": 2,
                    "duration": 1.0,
                    "actual_cut_points": [],
                    "source_evidence": {"asr_text": "", "subtitle_observations": []},
                    "beats": [
                        {
                            "id": "sr001",
                            "source_start": 0.0,
                            "source_end": 1.0,
                            "confirmed_source_line": "",
                            "speaker_mode": "silent",
                            "emphasis_tokens": [],
                            "pause_after_seconds": 0.0,
                            "action_peak_times": [0.5],
                            "visual_action": "泥膜棒滑过鼻翼并把泥膜留在皮肤上",
                            "visual_action_type": "physical_change",
                            "emotion_function": "快速动作证明",
                            "rhythm_class": "rapid_hook",
                            "replication_priority": "must_keep",
                            "evidence_frame_refs": [
                                "frame_before.jpg",
                                "frame_peak.jpg",
                                "frame_after.jpg",
                            ],
                            "entry_transition": "source_start",
                            "exit_transition": "source_end",
                        }
                    ],
                },
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn(
                "missing_physical_action_evidence",
                [issue["code"] for issue in report["issues"]],
            )

    def test_mergeable_physical_change_still_requires_state_change_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result, report = self.run_qc(
                root,
                {
                    "schema_version": 2,
                    "duration": 1.0,
                    "actual_cut_points": [],
                    "source_evidence": {"asr_text": "", "subtitle_observations": []},
                    "beats": [
                        {
                            "id": "sr001",
                            "source_start": 0.0,
                            "source_end": 1.0,
                            "confirmed_source_line": "",
                            "speaker_mode": "silent",
                            "emphasis_tokens": [],
                            "pause_after_seconds": 0.0,
                            "action_peak_times": [0.5],
                            "visual_action": "拉开拉链并露出包内产品",
                            "visual_action_type": "physical_change",
                            "emotion_function": "过渡动作",
                            "rhythm_class": "transition",
                            "replication_priority": "mergeable",
                            "evidence_frame_refs": ["before.jpg", "peak.jpg", "after.jpg"],
                            "entry_transition": "source_start",
                            "exit_transition": "source_end",
                        }
                    ],
                },
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn(
                "missing_physical_action_evidence",
                [issue["code"] for issue in report["issues"]],
            )

    def test_rejects_incomplete_physical_state_change_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result, report = self.run_qc(
                root,
                {
                    "schema_version": 2,
                    "duration": 1.0,
                    "actual_cut_points": [],
                    "source_evidence": {
                        "asr_text": "涂",
                        "subtitle_observations": [],
                    },
                    "beats": [
                        {
                            "id": "sr002",
                            "source_start": 0.0,
                            "source_end": 1.0,
                            "asr_span": {"start": 0, "end": 1},
                            "confirmed_source_line": "涂！",
                            "speaker_mode": "voiceover",
                            "emphasis_tokens": ["涂"],
                            "pause_after_seconds": 0.0,
                            "action_peak_times": [0.5],
                            "visual_action": "泥膜快速涂过鼻翼",
                            "visual_action_type": "physical_change",
                            "emotion_function": "命令式单字重音",
                            "rhythm_class": "rapid_hook",
                            "replication_priority": "must_keep",
                            "evidence_frame_refs": [
                                "frame_before.jpg",
                                "frame_peak.jpg",
                                "frame_after.jpg",
                            ],
                            "action_evidence": {
                                "kind": "physical_change"
                            },
                            "entry_transition": "source_start",
                            "exit_transition": "source_end",
                        }
                    ],
                },
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn(
                "incomplete_physical_action_evidence",
                [issue["code"] for issue in report["issues"]],
            )

    def test_rejects_physical_action_evidence_without_three_real_beat_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            before = root / "frame_before.jpg"
            peak = root / "frame_peak.jpg"
            after = root / "frame_after.jpg"
            result, report = self.run_qc(
                root,
                {
                    "schema_version": 2,
                    "duration": 1.0,
                    "actual_cut_points": [],
                    "source_evidence": {
                        "asr_text": "涂",
                        "subtitle_observations": [],
                    },
                    "beats": [
                        {
                            "id": "sr002",
                            "source_start": 0.0,
                            "source_end": 1.0,
                            "asr_span": {"start": 0, "end": 1},
                            "confirmed_source_line": "涂！",
                            "speaker_mode": "voiceover",
                            "emphasis_tokens": ["涂"],
                            "pause_after_seconds": 0.0,
                            "action_peak_times": [0.5],
                            "visual_action": "泥膜快速涂过鼻翼并留在皮肤上",
                            "visual_action_type": "physical_change",
                            "emotion_function": "命令式单字重音",
                            "rhythm_class": "rapid_hook",
                            "replication_priority": "must_keep",
                            "evidence_frame_refs": [str(before), str(peak), str(after)],
                            "action_evidence": {
                                "kind": "physical_change",
                                "before_frame_ref": str(before),
                                "peak_frame_ref": str(peak),
                                "after_frame_ref": str(after),
                                "motion": "泥膜从鼻翼上方快速向下滑过",
                                "state_before": "鼻翼没有泥膜",
                                "state_after": "鼻翼留下泥膜",
                                "visible_result": "泥膜真实转移到皮肤",
                            },
                            "entry_transition": "source_start",
                            "exit_transition": "source_end",
                        }
                    ],
                },
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn(
                "unverified_physical_action_evidence",
                [issue["code"] for issue in report["issues"]],
            )

    def test_accepts_physical_action_with_before_peak_after_state_change_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            before = root / "frame_before.jpg"
            peak = root / "frame_peak.jpg"
            after = root / "frame_after.jpg"
            for frame in (before, peak, after):
                frame.write_bytes(b"frame")
            result, report = self.run_qc(
                root,
                {
                    "schema_version": 2,
                    "duration": 1.0,
                    "actual_cut_points": [],
                    "source_evidence": {
                        "asr_text": "涂",
                        "subtitle_observations": [],
                    },
                    "beats": [
                        {
                            "id": "sr002",
                            "source_start": 0.0,
                            "source_end": 1.0,
                            "asr_span": {"start": 0, "end": 1},
                            "confirmed_source_line": "涂！",
                            "speaker_mode": "voiceover",
                            "emphasis_tokens": ["涂"],
                            "pause_after_seconds": 0.0,
                            "action_peak_times": [0.5],
                            "visual_action": "泥膜快速涂过鼻翼并留在皮肤上",
                            "visual_action_type": "physical_change",
                            "emotion_function": "命令式单字重音",
                            "rhythm_class": "rapid_hook",
                            "replication_priority": "must_keep",
                            "evidence_frame_refs": [str(before), str(peak), str(after)],
                            "action_evidence": {
                                "kind": "physical_change",
                                "before_frame_ref": str(before),
                                "peak_frame_ref": str(peak),
                                "after_frame_ref": str(after),
                                "motion": "泥膜从鼻翼上方快速向下滑过",
                                "state_before": "鼻翼没有泥膜",
                                "state_after": "鼻翼留下泥膜",
                                "visible_result": "泥膜真实转移到皮肤",
                            },
                            "entry_transition": "source_start",
                            "exit_transition": "source_end",
                        }
                    ],
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(report["overall"], "PASS")

    def test_rejects_changed_raw_asr_file_after_rhythm_authorship(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asr_path = root / "asr.md"
            asr_path.write_text("## Full Text\n\n看好了\n", encoding="utf-8")
            payload = {
                "schema_version": 1,
                "duration": 1.0,
                "actual_cut_points": [],
                "source_evidence": {
                    "asr_text": "看好了",
                    "asr_source": str(asr_path),
                    "asr_text_sha256": "0" * 64,
                    "subtitle_observations": [],
                },
                "beats": [
                    {
                        "id": "beat-001",
                        "source_start": 0.0,
                        "source_end": 1.0,
                        "asr_span": {"start": 0, "end": 3},
                        "confirmed_source_line": "看好了",
                        "speaker_mode": "sync",
                        "emphasis_tokens": ["看好了"],
                        "pause_after_seconds": 0.0,
                        "action_peak_times": [0.5],
                        "visual_action": "主播指向镜头",
                        "emotion_function": "提醒",
                        "rhythm_class": "normal",
                        "replication_priority": "must_keep",
                        "evidence_frame_refs": ["frame.jpg"],
                        "entry_transition": "source_start",
                        "exit_transition": "source_end",
                    }
                ],
            }

            result, report = self.run_qc(root, payload)

            self.assertEqual(result.returncode, 1)
            self.assertIn("asr_source_hash_mismatch", [issue["code"] for issue in report["issues"]])

    def test_accepts_explicit_raw_text_character_spans_with_punctuation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = {
                "schema_version": 1,
                "duration": 1.0,
                "actual_cut_points": [],
                "source_evidence": {
                    "asr_text": "前，壬二酸",
                    "asr_span_basis": "raw_text",
                    "subtitle_observations": [],
                },
                "beats": [
                    {
                        "id": "beat-001",
                        "source_start": 0.0,
                        "source_end": 1.0,
                        "asr_span": {"start": 2, "end": 5},
                        "confirmed_source_line": "壬二酸",
                        "speaker_mode": "sync",
                        "emphasis_tokens": ["壬二酸"],
                        "pause_after_seconds": 0.0,
                        "action_peak_times": [0.5],
                        "visual_action": "主播展示成分",
                        "emotion_function": "解释成分",
                        "rhythm_class": "normal",
                        "replication_priority": "must_keep",
                        "evidence_frame_refs": ["frame.jpg"],
                        "entry_transition": "source_start",
                        "exit_transition": "source_end",
                    }
                ],
            }

            result, report = self.run_qc(root, payload)

            self.assertEqual(result.returncode, 0, report)
            self.assertEqual(report["overall"], "PASS")

    def test_rejects_unexplained_gap_between_source_beats(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            common = {
                "speaker_mode": "sync",
                "emphasis_tokens": [],
                "pause_after_seconds": 0.0,
                "visual_action": "主播连续说话",
                "emotion_function": "信息推进",
                "rhythm_class": "normal",
                "replication_priority": "must_keep",
                "evidence_frame_refs": ["frame.jpg"],
            }
            payload = {
                "schema_version": 1,
                "duration": 2.0,
                "actual_cut_points": [],
                "source_evidence": {"asr_text": "看好了开始", "subtitle_observations": []},
                "beats": [
                    {
                        **common,
                        "id": "beat-001",
                        "source_start": 0.0,
                        "source_end": 1.0,
                        "asr_span": {"start": 0, "end": 3},
                        "confirmed_source_line": "看好了",
                        "action_peak_times": [0.5],
                        "entry_transition": "source_start",
                        "exit_transition": "continuous",
                    },
                    {
                        **common,
                        "id": "beat-002",
                        "source_start": 1.5,
                        "source_end": 2.0,
                        "asr_span": {"start": 3, "end": 5},
                        "confirmed_source_line": "开始",
                        "action_peak_times": [1.7],
                        "entry_transition": "continuous",
                        "exit_transition": "source_end",
                    },
                ],
            }

            result, report = self.run_qc(root, payload)

            self.assertEqual(result.returncode, 1)
            self.assertIn("source_beat_timeline_gap", [issue["code"] for issue in report["issues"]])

    def test_accepts_line_derived_from_raw_transcript_span_with_visible_correction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = {
                "schema_version": 1,
                "duration": 2.0,
                "actual_cut_points": [{"time": 1.7, "score": 0.4}],
                "source_evidence": {
                    "asr_text": "黑头闭口涂油皮粉丝涂管它黑头还是油光",
                    "subtitle_observations": [
                        {"time": 0.2, "text": "黑头闭口，涂！"},
                        {"time": 0.9, "text": "油皮粉刺，涂！"},
                    ],
                },
                "beats": [
                    {
                        "id": "beat-001",
                        "source_start": 0.0,
                        "source_end": 1.7,
                        "asr_span": {"start": 0, "end": 10},
                        "corrections": [
                            {
                                "from": "粉丝",
                                "to": "粉刺",
                                "evidence_type": "visible_text",
                            }
                        ],
                        "confirmed_source_line": "黑头闭口，涂！油皮粉刺，涂！",
                        "speaker_mode": "voiceover",
                        "emphasis_tokens": ["涂", "涂"],
                        "pause_after_seconds": 0.1,
                        "action_peak_times": [0.2, 0.9],
                        "visual_action": "两组问题肌极近景，手指分别点出问题位置",
                        "emotion_function": "快速问题钩子",
                        "rhythm_class": "rapid_hook",
                        "replication_priority": "must_keep",
                        "evidence_frame_refs": ["hook_0.2.jpg", "hook_0.9.jpg"],
                        "entry_transition": "source_start",
                        "exit_transition": "hard_cut",
                    }
                ],
            }

            result, report = self.run_qc(root, payload)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(report["overall"], "PASS")

    def test_rejects_correction_backed_only_by_subtitle_from_another_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = {
                "schema_version": 1,
                "duration": 6.0,
                "actual_cut_points": [],
                "source_evidence": {
                    "asr_text": "油皮粉丝",
                    "subtitle_observations": [{"time": 5.0, "text": "油皮粉刺"}],
                },
                "beats": [
                    {
                        "id": "beat-001",
                        "source_start": 0.0,
                        "source_end": 1.0,
                        "asr_span": {"start": 0, "end": 4},
                        "corrections": [
                            {"from": "粉丝", "to": "粉刺", "evidence_type": "visible_text"}
                        ],
                        "confirmed_source_line": "油皮粉刺",
                        "speaker_mode": "voiceover",
                        "emphasis_tokens": ["粉刺"],
                        "pause_after_seconds": 0.0,
                        "action_peak_times": [0.5],
                        "visual_action": "油皮问题近景",
                        "emotion_function": "问题钩子",
                        "rhythm_class": "rapid_hook",
                        "replication_priority": "must_keep",
                        "evidence_frame_refs": ["frame.jpg"],
                        "entry_transition": "source_start",
                        "exit_transition": "continuous",
                    }
                ],
            }

            result, report = self.run_qc(root, payload)

            self.assertEqual(result.returncode, 1)
            self.assertIn("unsupported_correction", [issue["code"] for issue in report["issues"]])

    def test_rejects_beat_without_required_emotion_rhythm_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = {
                "schema_version": 1,
                "source_evidence": {"asr_text": "看好了", "subtitle_observations": []},
                "beats": [
                    {
                        "id": "beat-001",
                        "source_start": 0.0,
                        "source_end": 0.8,
                        "asr_span": {"start": 0, "end": 3},
                        "confirmed_source_line": "看好了",
                        "speaker_mode": "sync",
                        "emphasis_tokens": ["看好了"],
                        "pause_after_seconds": 0.0,
                        "action_peak_times": [0.5],
                        "visual_action": "主播指向镜头",
                        "evidence_frame_refs": ["frame_0.5.jpg"],
                    }
                ],
            }

            result, report = self.run_qc(root, payload)

            self.assertEqual(result.returncode, 1)
            self.assertIn(
                "missing_rhythm_field",
                [issue["code"] for issue in report["issues"]],
            )

    def test_rejects_action_peak_outside_its_source_beat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = {
                "schema_version": 1,
                "duration": 3.0,
                "actual_cut_points": [],
                "source_evidence": {"asr_text": "看好了", "subtitle_observations": []},
                "beats": [
                    {
                        "id": "beat-001",
                        "source_start": 0.0,
                        "source_end": 1.0,
                        "asr_span": {"start": 0, "end": 3},
                        "confirmed_source_line": "看好了",
                        "speaker_mode": "sync",
                        "emphasis_tokens": ["看好了"],
                        "pause_after_seconds": 0.0,
                        "action_peak_times": [2.0],
                        "visual_action": "主播指向镜头",
                        "emotion_function": "提醒",
                        "rhythm_class": "normal",
                        "replication_priority": "must_keep",
                        "evidence_frame_refs": ["frame.jpg"],
                        "entry_transition": "source_start",
                        "exit_transition": "continuous",
                    }
                ],
            }

            result, report = self.run_qc(root, payload)

            self.assertEqual(result.returncode, 1)
            self.assertIn("action_peak_outside_beat", [issue["code"] for issue in report["issues"]])

    def test_rejects_claimed_hard_cut_that_is_not_backed_by_detected_cut(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = {
                "schema_version": 1,
                "duration": 2.0,
                "actual_cut_points": [{"time": 0.8, "score": 0.4}],
                "source_evidence": {"asr_text": "看好了", "subtitle_observations": []},
                "beats": [
                    {
                        "id": "beat-001",
                        "source_start": 1.1,
                        "source_end": 2.0,
                        "asr_span": {"start": 0, "end": 3},
                        "confirmed_source_line": "看好了",
                        "speaker_mode": "sync",
                        "emphasis_tokens": ["看好了"],
                        "pause_after_seconds": 0.0,
                        "action_peak_times": [1.3],
                        "visual_action": "主播指向镜头",
                        "emotion_function": "提醒",
                        "evidence_frame_refs": ["frame_1.3.jpg"],
                        "entry_transition": "hard_cut",
                        "exit_transition": "source_end",
                    }
                ],
            }

            result, report = self.run_qc(root, payload)

            self.assertEqual(result.returncode, 1)
            self.assertIn(
                "unverified_hard_cut",
                [issue["code"] for issue in report["issues"]],
            )

    def test_rejects_target_plan_that_overstretches_a_rapid_source_hook(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_line = "黑头闭口涂油皮粉刺涂管它黑头还是油光"
            payload = {
                "schema_version": 1,
                "duration": 25.6,
                "actual_cut_points": [],
                "source_evidence": {"asr_text": source_line, "subtitle_observations": []},
                "beats": [
                    {
                        "id": "beat-hook",
                        "source_start": 0.0,
                        "source_end": 2.13,
                        "asr_span": {"start": 0, "end": len(source_line)},
                        "confirmed_source_line": source_line,
                        "speaker_mode": "voiceover",
                        "emphasis_tokens": ["涂", "涂"],
                        "pause_after_seconds": 0.0,
                        "action_peak_times": [0.3, 1.0],
                        "visual_action": "两组问题肌快速硬切",
                        "emotion_function": "快速问题钩子",
                        "rhythm_class": "rapid_hook",
                        "replication_priority": "must_keep",
                        "evidence_frame_refs": ["hook.jpg"],
                        "entry_transition": "source_start",
                        "exit_transition": "continuous",
                    }
                ],
            }
            plan_path = root / "director_plan.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "job": {"target_duration": "30s"},
                        "parts": [
                            {
                                "id": "part1",
                                "beats": [
                                    {
                                        "id": "p1b1",
                                        "target_start": 0.0,
                                        "target_end": 3.5,
                                        "source_beat_ids": ["beat-hook"],
                                    }
                                ],
                                "speech_groups": [
                                    {
                                        "id": "p1s1",
                                        "beat_ids": ["p1b1"],
                                        "target_start": 0.0,
                                        "target_end": 3.4,
                                        "line": source_line,
                                    }
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result, report = self.run_qc(
                root,
                payload,
                "--director-plan",
                str(plan_path),
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn(
                "rapid_hook_overstretched",
                [issue["code"] for issue in report["issues"]],
            )

    def test_rejects_long_speech_block_with_too_few_units_for_source_pace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_line = "脏东西连根拔起现在这个皮肤女朋友凑再近都不怕了"
            payload = {
                "schema_version": 1,
                "duration": 30.0,
                "actual_cut_points": [],
                "source_evidence": {"asr_text": source_line, "subtitle_observations": []},
                "beats": [
                    {
                        "id": "beat-proof",
                        "source_start": 10.0,
                        "source_end": 14.0,
                        "asr_span": {"start": 0, "end": len(source_line)},
                        "confirmed_source_line": source_line,
                        "speaker_mode": "voiceover",
                        "emphasis_tokens": ["连根拔起"],
                        "pause_after_seconds": 0.1,
                        "action_peak_times": [11.0, 13.2],
                        "visual_action": "水洗后切近景展示",
                        "emotion_function": "效果证明",
                        "rhythm_class": "proof",
                        "replication_priority": "must_keep",
                        "evidence_frame_refs": ["proof.jpg"],
                        "entry_transition": "continuous",
                        "exit_transition": "continuous",
                    }
                ],
            }
            plan_path = root / "director_plan.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "job": {"target_duration": "30s"},
                        "parts": [
                            {
                                "id": "part2",
                                "beats": [
                                    {
                                        "id": "p2b1",
                                        "target_start": 0.0,
                                        "target_end": 9.4,
                                        "source_beat_ids": ["beat-proof"],
                                    }
                                ],
                                "speech_groups": [
                                    {
                                        "id": "p2s1",
                                        "beat_ids": ["p2b1"],
                                        "target_start": 0.0,
                                        "target_end": 9.4,
                                        "line": "洗完以后皮肤真干净",
                                    }
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result, report = self.run_qc(
                root,
                payload,
                "--director-plan",
                str(plan_path),
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn(
                "speech_too_sparse_for_source_pace",
                [issue["code"] for issue in report["issues"]],
            )

    def test_source_pace_floor_is_capped_by_the_speech_capacity_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_line = "甲乙丙丁戊己庚辛"
            target_line = "甲乙丙丁戊己"
            payload = {
                "schema_version": 1,
                "duration": 1.0,
                "actual_cut_points": [],
                "source_evidence": {"asr_text": source_line, "subtitle_observations": []},
                "beats": [
                    {
                        "id": "beat-fast",
                        "source_start": 0.0,
                        "source_end": 1.0,
                        "asr_span": {"start": 0, "end": len(source_line)},
                        "confirmed_source_line": source_line,
                        "speaker_mode": "sync",
                        "emphasis_tokens": [],
                        "pause_after_seconds": 0.0,
                        "action_peak_times": [0.5],
                        "visual_action": "主播快速口播",
                        "emotion_function": "快速推进",
                        "rhythm_class": "normal",
                        "replication_priority": "must_keep",
                        "evidence_frame_refs": ["fast.jpg"],
                        "entry_transition": "source_start",
                        "exit_transition": "source_end",
                    }
                ],
            }
            plan_path = root / "director_plan.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "job": {"target_duration": "1s"},
                        "parts": [
                            {
                                "id": "part1",
                                "beats": [
                                    {
                                        "id": "p1b1",
                                        "target_start": 0.0,
                                        "target_end": 1.0,
                                        "source_beat_ids": ["beat-fast"],
                                    }
                                ],
                                "speech_groups": [
                                    {
                                        "id": "p1s1",
                                        "beat_ids": ["p1b1"],
                                        "target_start": 0.0,
                                        "target_end": 6 / 6.2,
                                        "line": target_line,
                                    }
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result, report = self.run_qc(
                root,
                payload,
                "--director-plan",
                str(plan_path),
            )

            self.assertEqual(result.returncode, 0, report)
            self.assertEqual(report["overall"], "PASS")

    def test_v5_director_plan_rejects_a_rewritten_source_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = {
                "schema_version": 1,
                "duration": 1.0,
                "actual_cut_points": [],
                "source_evidence": {"asr_text": "看好了", "subtitle_observations": []},
                "beats": [
                    {
                        "id": "beat-001",
                        "source_start": 0.0,
                        "source_end": 1.0,
                        "asr_span": {"start": 0, "end": 3},
                        "confirmed_source_line": "看好了",
                        "speaker_mode": "sync",
                        "emphasis_tokens": ["看好了"],
                        "pause_after_seconds": 0.0,
                        "action_peak_times": [0.5],
                        "visual_action": "主播指向镜头",
                        "emotion_function": "提醒",
                        "rhythm_class": "normal",
                        "replication_priority": "must_keep",
                        "evidence_frame_refs": ["frame.jpg"],
                        "entry_transition": "source_start",
                        "exit_transition": "source_end",
                    }
                ],
            }
            rhythm_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            import hashlib

            plan_path = root / "director_plan.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "version": 5,
                        "source_rhythm": {
                            "path": str(root / "source_rhythm.json"),
                            "analysis_sha256": hashlib.sha256(rhythm_bytes).hexdigest(),
                            "source_video_sha256": "",
                        },
                        "job": {"target_duration": "1s"},
                        "parts": [
                            {
                                "id": "part1",
                                "beats": [
                                    {
                                        "id": "p1b1",
                                        "target_start": 0.0,
                                        "target_end": 1.0,
                                        "source_beat_ids": ["beat-001"],
                                        "source_line": "我来介绍",
                                    }
                                ],
                                "speech_groups": [
                                    {
                                        "id": "p1s1",
                                        "beat_ids": ["p1b1"],
                                        "target_start": 0.0,
                                        "target_end": 1.0,
                                        "line": "我来介绍",
                                    }
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result, report = self.run_qc(
                root,
                payload,
                "--director-plan",
                str(plan_path),
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn(
                "director_plan_source_line_not_verbatim",
                [issue["code"] for issue in report["issues"]],
            )

    def test_v6_source_length_requires_every_source_beat_exactly_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = {
                "schema_version": 1,
                "duration": 2.0,
                "actual_cut_points": [1.0],
                "source_evidence": {"asr_text": "保留这句", "subtitle_observations": []},
                "beats": [
                    {
                        "id": "beat-keep",
                        "source_start": 0.0,
                        "source_end": 1.0,
                        "asr_span": {"start": 0, "end": 4},
                        "confirmed_source_line": "保留这句",
                        "speaker_mode": "sync",
                        "emphasis_tokens": ["保留"],
                        "pause_after_seconds": 0.0,
                        "action_peak_times": [0.5],
                        "visual_action": "主播正面说话",
                        "emotion_function": "钩子",
                        "rhythm_class": "normal",
                        "replication_priority": "must_keep",
                        "evidence_frame_refs": ["keep.jpg"],
                        "entry_transition": "source_start",
                        "exit_transition": "hard_cut",
                    },
                    {
                        "id": "beat-removable",
                        "source_start": 1.0,
                        "source_end": 2.0,
                        "asr_span": {"start": 4, "end": 4},
                        "confirmed_source_line": "",
                        "speaker_mode": "silent",
                        "emphasis_tokens": [],
                        "pause_after_seconds": 0.0,
                        "action_peak_times": [1.5],
                        "visual_action": "产品近景轻晃",
                        "emotion_function": "产品证明",
                        "rhythm_class": "normal",
                        "replication_priority": "removable",
                        "evidence_frame_refs": ["product.jpg"],
                        "entry_transition": "hard_cut",
                        "exit_transition": "source_end",
                    },
                ],
            }
            rhythm_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            import hashlib

            plan_path = root / "director_plan.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "version": 6,
                        "replication_fidelity": {
                            "mode": "source_locked",
                            "change_policy": "necessary_only",
                            "duration_mode": "source_length",
                        },
                        "source_rhythm": {
                            "path": str(root / "source_rhythm.json"),
                            "analysis_sha256": hashlib.sha256(rhythm_bytes).hexdigest(),
                            "source_video_sha256": "",
                        },
                        "job": {"target_duration": "2s"},
                        "parts": [
                            {
                                "id": "part1",
                                "beats": [
                                    {
                                        "id": "p1b1",
                                        "target_start": 0.0,
                                        "target_end": 2.0,
                                        "source_beat_ids": ["beat-keep"],
                                        "source_line": "保留这句",
                                        "source_visual_action": "主播正面说话",
                                    }
                                ],
                                "speech_groups": [
                                    {
                                        "id": "p1s1",
                                        "beat_ids": ["p1b1"],
                                        "target_start": 0.0,
                                        "target_end": 2.0,
                                        "line": "保留这句",
                                    }
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result, report = self.run_qc(
                root,
                payload,
                "--director-plan",
                str(plan_path),
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn(
                "uncovered_source_beat",
                [issue["code"] for issue in report["issues"]],
            )

    def test_v6_source_length_does_not_require_explicitly_excluded_source_beat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = {
                "schema_version": 3,
                "duration": 2.0,
                "actual_cut_points": [1.0],
                "source_evidence": {"asr_text": "保留这句", "subtitle_observations": []},
                "beats": [
                    {
                        "id": "beat-keep",
                        "source_start": 0.0,
                        "source_end": 1.0,
                        "asr_span": {"start": 0, "end": 4},
                        "confirmed_source_line": "保留这句",
                        "speaker_mode": "sync",
                        "emphasis_tokens": ["保留"],
                        "pause_after_seconds": 0.0,
                        "action_peak_times": [0.5],
                        "visual_action": "主播正面说话",
                        "emotion_function": "钩子",
                        "rhythm_class": "normal",
                        "replication_priority": "must_keep",
                        "evidence_frame_refs": ["keep.jpg"],
                        "entry_transition": "source_start",
                        "exit_transition": "hard_cut",
                    },
                    {
                        "id": "beat-editing-anomaly",
                        "source_start": 1.0,
                        "source_end": 2.0,
                        "asr_span": {"start": 4, "end": 4},
                        "confirmed_source_line": "",
                        "speaker_mode": "silent",
                        "emphasis_tokens": [],
                        "pause_after_seconds": 0.0,
                        "action_peak_times": [1.5],
                        "visual_action": "误插入的一帧无关人物",
                        "emotion_function": "源片剪辑异常",
                        "rhythm_class": "source_editing_anomaly",
                        "replication_priority": "exclude",
                        "evidence_frame_refs": ["anomaly.jpg"],
                        "entry_transition": "hard_cut",
                        "exit_transition": "source_end",
                    },
                ],
            }
            rhythm_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            import hashlib

            plan_path = root / "director_plan.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "version": 6,
                        "replication_fidelity": {
                            "mode": "source_locked",
                            "change_policy": "necessary_only",
                            "duration_mode": "source_length",
                        },
                        "source_rhythm": {
                            "path": str(root / "source_rhythm.json"),
                            "analysis_sha256": hashlib.sha256(rhythm_bytes).hexdigest(),
                            "source_video_sha256": "",
                        },
                        "job": {"target_duration": "2s"},
                        "parts": [
                            {
                                "id": "part1",
                                "beats": [
                                    {
                                        "id": "p1b1",
                                        "target_start": 0.0,
                                        "target_end": 2.0,
                                        "source_beat_ids": ["beat-keep"],
                                        "source_line": "保留这句",
                                        "source_visual_action": "主播正面说话",
                                    }
                                ],
                                "speech_groups": [
                                    {
                                        "id": "p1s1",
                                        "beat_ids": ["p1b1"],
                                        "target_start": 0.0,
                                        "target_end": 2.0,
                                        "line": "保留这句",
                                    }
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result, report = self.run_qc(
                root,
                payload,
                "--director-plan",
                str(plan_path),
            )

            self.assertNotIn(
                "uncovered_source_beat",
                [issue["code"] for issue in report["issues"]],
            )

            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["parts"][0]["beats"][0]["source_beat_ids"] = [
                "beat-editing-anomaly"
            ]
            plan["parts"][0]["beats"][0]["source_line"] = ""
            plan["parts"][0]["beats"][0]["source_visual_action"] = (
                "误插入的一帧无关人物"
            )
            plan_path.write_text(
                json.dumps(plan, ensure_ascii=False),
                encoding="utf-8",
            )

            _mapped_result, mapped_report = self.run_qc(
                root,
                payload,
                "--director-plan",
                str(plan_path),
            )

            self.assertIn(
                "excluded_source_beat_mapped",
                [issue["code"] for issue in mapped_report["issues"]],
            )

    def test_v6_rejects_duplicate_source_beat_mapping(self):
        source = {
            "duration": 2.0,
            "beats": [
                {
                    "id": "beat-001",
                    "source_start": 0.0,
                    "source_end": 2.0,
                    "confirmed_source_line": "",
                    "speaker_mode": "silent",
                    "rhythm_class": "normal",
                    "replication_priority": "must_keep",
                    "visual_action": "产品近景轻晃",
                }
            ],
        }
        plan = {
            "version": 6,
            "replication_fidelity": {
                "mode": "source_locked",
                "change_policy": "necessary_only",
                "duration_mode": "source_length",
            },
            "job": {"target_duration": "2s"},
            "parts": [
                {
                    "id": "part1",
                    "beats": [
                        {
                            "id": "p1b1",
                            "target_start": 0.0,
                            "target_end": 1.0,
                            "source_beat_ids": ["beat-001"],
                            "source_visual_action": "产品近景轻晃",
                        },
                        {
                            "id": "p1b2",
                            "target_start": 1.0,
                            "target_end": 2.0,
                            "source_beat_ids": ["beat-001"],
                            "source_visual_action": "产品近景轻晃",
                        },
                    ],
                    "speech_groups": [],
                }
            ],
        }

        issues = check_director_plan(source, plan)

        self.assertIn("duplicate_source_beat_mapping", [issue["code"] for issue in issues])

    def test_v6_rejects_source_visual_action_that_is_not_bound_verbatim(self):
        source = {
            "duration": 2.0,
            "beats": [
                {
                    "id": "beat-001",
                    "source_start": 0.0,
                    "source_end": 2.0,
                    "confirmed_source_line": "",
                    "speaker_mode": "silent",
                    "rhythm_class": "normal",
                    "replication_priority": "must_keep",
                    "visual_action": "画面从产品特写硬切到主播正脸",
                }
            ],
        }
        plan = {
            "version": 6,
            "replication_fidelity": {
                "mode": "source_locked",
                "change_policy": "necessary_only",
                "duration_mode": "source_length",
            },
            "job": {"target_duration": "2s"},
            "parts": [
                {
                    "id": "part1",
                    "beats": [
                        {
                            "id": "p1b1",
                            "target_start": 0.0,
                            "target_end": 2.0,
                            "source_beat_ids": ["beat-001"],
                            "source_visual_action": "主播拿起产品后连续推近",
                        }
                    ],
                    "speech_groups": [],
                }
            ],
        }

        issues = check_director_plan(source, plan)

        self.assertIn(
            "director_plan_source_visual_action_not_verbatim",
            [issue["code"] for issue in issues],
        )

    def test_v6_source_length_rejects_merging_source_beats_in_target_beat(self):
        source = {
            "duration": 2.0,
            "beats": [
                {
                    "id": "beat-001",
                    "source_start": 0.0,
                    "source_end": 1.0,
                    "confirmed_source_line": "第一句",
                    "speaker_mode": "voiceover",
                    "rhythm_class": "normal",
                    "replication_priority": "must_keep",
                    "visual_action": "第一镜",
                },
                {
                    "id": "beat-002",
                    "source_start": 1.0,
                    "source_end": 2.0,
                    "confirmed_source_line": "第二句",
                    "speaker_mode": "voiceover",
                    "rhythm_class": "normal",
                    "replication_priority": "must_keep",
                    "visual_action": "第二镜",
                },
            ],
        }
        plan = {
            "version": 6,
            "replication_fidelity": {
                "mode": "source_locked",
                "change_policy": "necessary_only",
                "duration_mode": "source_length",
            },
            "job": {"target_duration": "2s"},
            "parts": [
                {
                    "id": "part1",
                    "beats": [
                        {
                            "id": "p1b1",
                            "target_start": 0.0,
                            "target_end": 2.0,
                            "source_beat_ids": ["beat-001", "beat-002"],
                            "source_visual_action": "第一镜 → 第二镜",
                            "source_line": "第一句第二句",
                            "source_speaker_mode": "voiceover",
                        }
                    ],
                    "speech_groups": [],
                }
            ],
        }

        issues = check_director_plan(source, plan)

        self.assertIn(
            "source_length_target_beat_must_bind_one_source_beat",
            [issue["code"] for issue in issues],
        )

    def test_v6_rejects_source_lines_moved_between_beats(self):
        source = {
            "duration": 2.0,
            "beats": [
                {
                    "id": "beat-001",
                    "source_start": 0.0,
                    "source_end": 1.0,
                    "confirmed_source_line": "第一句",
                    "speaker_mode": "voiceover",
                    "rhythm_class": "normal",
                    "replication_priority": "must_keep",
                    "visual_action": "第一镜",
                },
                {
                    "id": "beat-002",
                    "source_start": 1.0,
                    "source_end": 2.0,
                    "confirmed_source_line": "第二句",
                    "speaker_mode": "voiceover",
                    "rhythm_class": "normal",
                    "replication_priority": "must_keep",
                    "visual_action": "第二镜",
                },
            ],
        }
        plan = {
            "version": 6,
            "replication_fidelity": {
                "mode": "source_locked",
                "change_policy": "necessary_only",
                "duration_mode": "source_length",
            },
            "job": {"target_duration": "2s"},
            "parts": [
                {
                    "id": "part1",
                    "beats": [
                        {
                            "id": "p1b1",
                            "target_start": 0.0,
                            "target_end": 1.0,
                            "source_beat_ids": ["beat-001"],
                            "source_visual_action": "第一镜",
                            "source_line": "第二句",
                            "source_speaker_mode": "voiceover",
                        },
                        {
                            "id": "p1b2",
                            "target_start": 1.0,
                            "target_end": 2.0,
                            "source_beat_ids": ["beat-002"],
                            "source_visual_action": "第二镜",
                            "source_line": "第一句",
                            "source_speaker_mode": "voiceover",
                        },
                    ],
                    "speech_groups": [],
                }
            ],
        }

        issues = check_director_plan(source, plan)

        self.assertIn(
            "director_plan_beat_source_line_not_verbatim",
            [issue["code"] for issue in issues],
        )

    def test_v6_rejects_source_speaker_mode_changed_per_beat(self):
        source = {
            "duration": 1.0,
            "beats": [
                {
                    "id": "beat-001",
                    "source_start": 0.0,
                    "source_end": 1.0,
                    "confirmed_source_line": "看好了",
                    "speaker_mode": "voiceover",
                    "rhythm_class": "normal",
                    "replication_priority": "must_keep",
                    "visual_action": "主播展示产品",
                }
            ],
        }
        plan = {
            "version": 6,
            "replication_fidelity": {
                "mode": "source_locked",
                "change_policy": "necessary_only",
                "duration_mode": "source_length",
            },
            "job": {"target_duration": "1s"},
            "parts": [
                {
                    "id": "part1",
                    "beats": [
                        {
                            "id": "p1b1",
                            "target_start": 0.0,
                            "target_end": 1.0,
                            "source_beat_ids": ["beat-001"],
                            "source_visual_action": "主播展示产品",
                            "source_line": "看好了",
                            "source_speaker_mode": "sync",
                        }
                    ],
                    "speech_groups": [],
                }
            ],
        }

        issues = check_director_plan(source, plan)

        self.assertIn(
            "director_plan_beat_source_speaker_mode_changed",
            [issue["code"] for issue in issues],
        )

    def test_v6_rejects_source_transition_claim_that_conflicts_with_rhythm(self):
        source = {
            "schema_version": 3,
            "duration": 1.0,
            "beats": [
                {
                    "id": "beat-001",
                    "source_start": 0.0,
                    "source_end": 1.0,
                    "confirmed_source_line": "",
                    "speaker_mode": "silent",
                    "rhythm_class": "normal",
                    "replication_priority": "must_keep",
                    "visual_action": "产品静物特写",
                    "visual_action_type": "static_hold",
                    "scene": "浴室台面",
                    "camera": "固定机位",
                    "framing": "产品特写",
                    "action_peak_times": [0.5],
                    "entry_transition": "hard_cut",
                    "exit_transition": "source_end",
                }
            ],
        }
        plan = {
            "version": 6,
            "replication_fidelity": {
                "mode": "source_locked",
                "change_policy": "necessary_only",
                "duration_mode": "source_length",
            },
            "job": {"target_duration": "1s"},
            "parts": [
                {
                    "id": "part1",
                    "beats": [
                        {
                            "id": "p1b1",
                            "target_start": 0.0,
                            "target_end": 1.0,
                            "source_beat_ids": ["beat-001"],
                            "source_visual_action": "产品静物特写",
                            "source_line": "",
                            "source_speaker_mode": "silent",
                            "visual_fidelity": {
                                "source_scene": "另一个场景",
                                "source_camera": "固定机位",
                                "source_framing": "产品特写",
                                "source_transition": "continuous",
                                "source_action_stage": "static_hold",
                                "source_action_timing": "peak_fractions=0.500",
                                "source_hard_cuts": "entry=hard_cut;exit=source_end",
                            },
                        }
                    ],
                    "speech_groups": [],
                }
            ],
        }

        issues = check_director_plan(source, plan)

        self.assertIn(
            "director_plan_source_transition_not_verbatim",
            [issue["code"] for issue in issues],
        )
        self.assertIn(
            "director_plan_source_scene_not_verbatim",
            [issue["code"] for issue in issues],
        )

    def test_v6_rejects_source_rhythm_schema_downgrade(self):
        source = {"schema_version": 2, "duration": 1.0, "beats": []}
        plan = {
            "version": 6,
            "replication_fidelity": {
                "mode": "source_locked",
                "change_policy": "necessary_only",
                "duration_mode": "source_length",
            },
            "job": {"target_duration": "1s"},
            "parts": [],
        }

        issues = check_director_plan(source, plan)

        self.assertIn(
            "director_plan_v6_requires_source_rhythm_v3",
            [issue["code"] for issue in issues],
        )

    def test_v6_source_length_rejects_redistributed_beat_timing(self):
        source = {
            "duration": 2.0,
            "beats": [
                {
                    "id": "beat-001",
                    "source_start": 0.0,
                    "source_end": 1.0,
                    "confirmed_source_line": "",
                    "speaker_mode": "silent",
                    "rhythm_class": "normal",
                    "replication_priority": "must_keep",
                    "visual_action": "第一镜",
                },
                {
                    "id": "beat-002",
                    "source_start": 1.0,
                    "source_end": 2.0,
                    "confirmed_source_line": "",
                    "speaker_mode": "silent",
                    "rhythm_class": "normal",
                    "replication_priority": "must_keep",
                    "visual_action": "第二镜",
                },
            ],
        }
        plan = {
            "version": 6,
            "replication_fidelity": {
                "mode": "source_locked",
                "change_policy": "necessary_only",
                "duration_mode": "source_length",
            },
            "job": {"target_duration": "2s"},
            "parts": [
                {
                    "id": "part1",
                    "beats": [
                        {
                            "id": "p1b1",
                            "target_start": 0.0,
                            "target_end": 0.2,
                            "source_beat_ids": ["beat-001"],
                            "source_visual_action": "第一镜",
                            "source_line": "",
                            "source_speaker_mode": "silent",
                        },
                        {
                            "id": "p1b2",
                            "target_start": 0.2,
                            "target_end": 2.0,
                            "source_beat_ids": ["beat-002"],
                            "source_visual_action": "第二镜",
                            "source_line": "",
                            "source_speaker_mode": "silent",
                        },
                    ],
                    "speech_groups": [],
                }
            ],
        }

        issues = check_director_plan(source, plan)

        self.assertIn(
            "source_length_beat_timing_changed",
            [issue["code"] for issue in issues],
        )

    def test_rejects_director_beat_without_source_rhythm_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = {
                "schema_version": 1,
                "duration": 15.0,
                "actual_cut_points": [],
                "source_evidence": {"asr_text": "看好了", "subtitle_observations": []},
                "beats": [
                    {
                        "id": "beat-001",
                        "source_start": 0.0,
                        "source_end": 1.0,
                        "asr_span": {"start": 0, "end": 3},
                        "confirmed_source_line": "看好了",
                        "speaker_mode": "sync",
                        "emphasis_tokens": ["看好了"],
                        "pause_after_seconds": 0.0,
                        "action_peak_times": [0.5],
                        "visual_action": "主播指向镜头",
                        "emotion_function": "提醒",
                        "rhythm_class": "normal",
                        "replication_priority": "must_keep",
                        "evidence_frame_refs": ["frame.jpg"],
                        "entry_transition": "source_start",
                        "exit_transition": "continuous",
                    }
                ],
            }
            plan_path = root / "director_plan.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "job": {"target_duration": "15s"},
                        "parts": [
                            {
                                "id": "part1",
                                "beats": [
                                    {"id": "p1b1", "target_start": 0.0, "target_end": 1.2}
                                ],
                                "speech_groups": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result, report = self.run_qc(
                root,
                payload,
                "--director-plan",
                str(plan_path),
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn(
                "missing_source_beat_mapping",
                [issue["code"] for issue in report["issues"]],
            )

    def test_v4_director_plan_requires_exact_source_rhythm_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = {
                "schema_version": 1,
                "duration": 1.0,
                "actual_cut_points": [],
                "source_evidence": {"asr_text": "看好了", "subtitle_observations": []},
                "beats": [
                    {
                        "id": "beat-001",
                        "source_start": 0.0,
                        "source_end": 1.0,
                        "asr_span": {"start": 0, "end": 3},
                        "confirmed_source_line": "看好了",
                        "speaker_mode": "sync",
                        "emphasis_tokens": ["看好了"],
                        "pause_after_seconds": 0.0,
                        "action_peak_times": [0.5],
                        "visual_action": "主播指向镜头",
                        "emotion_function": "提醒",
                        "rhythm_class": "normal",
                        "replication_priority": "must_keep",
                        "evidence_frame_refs": ["frame.jpg"],
                        "entry_transition": "source_start",
                        "exit_transition": "source_end",
                    }
                ],
            }
            plan_path = root / "director_plan.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "version": 4,
                        "job": {"target_duration": "1s"},
                        "parts": [
                            {
                                "id": "part1",
                                "beats": [
                                    {
                                        "id": "p1b1",
                                        "target_start": 0.0,
                                        "target_end": 1.0,
                                        "source_beat_ids": ["beat-001"],
                                    }
                                ],
                                "speech_groups": [
                                    {
                                        "id": "p1s1",
                                        "beat_ids": ["p1b1"],
                                        "target_start": 0.0,
                                        "target_end": 1.0,
                                        "line": "看好了",
                                    }
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result, report = self.run_qc(
                root,
                payload,
                "--director-plan",
                str(plan_path),
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn(
                "missing_source_rhythm_binding",
                [issue["code"] for issue in report["issues"]],
            )

    def test_v4_director_plan_rejects_stale_source_rhythm_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = {
                "schema_version": 1,
                "duration": 1.0,
                "actual_cut_points": [],
                "source_evidence": {"asr_text": "看好了", "subtitle_observations": []},
                "beats": [
                    {
                        "id": "beat-001",
                        "source_start": 0.0,
                        "source_end": 1.0,
                        "asr_span": {"start": 0, "end": 3},
                        "confirmed_source_line": "看好了",
                        "speaker_mode": "sync",
                        "emphasis_tokens": ["看好了"],
                        "pause_after_seconds": 0.0,
                        "action_peak_times": [0.5],
                        "visual_action": "主播指向镜头",
                        "emotion_function": "提醒",
                        "rhythm_class": "normal",
                        "replication_priority": "must_keep",
                        "evidence_frame_refs": ["frame.jpg"],
                        "entry_transition": "source_start",
                        "exit_transition": "source_end",
                    }
                ],
            }
            plan_path = root / "director_plan.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "version": 4,
                        "source_rhythm": {
                            "path": "source_rhythm.json",
                            "analysis_sha256": "0" * 64,
                            "source_video_sha256": "",
                        },
                        "job": {"target_duration": "1s"},
                        "parts": [
                            {
                                "id": "part1",
                                "beats": [
                                    {
                                        "id": "p1b1",
                                        "target_start": 0.0,
                                        "target_end": 1.0,
                                        "source_beat_ids": ["beat-001"],
                                    }
                                ],
                                "speech_groups": [
                                    {
                                        "id": "p1s1",
                                        "beat_ids": ["p1b1"],
                                        "target_start": 0.0,
                                        "target_end": 1.0,
                                        "line": "看好了",
                                    }
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result, report = self.run_qc(
                root,
                payload,
                "--director-plan",
                str(plan_path),
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn(
                "stale_source_rhythm_binding",
                [issue["code"] for issue in report["issues"]],
            )

    @unittest.skipIf(not shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_prepare_detects_real_hard_cuts_instead_of_uniform_intervals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video_path = root / "three-scenes.mp4"
            rhythm_path = root / "source_rhythm.json"
            make_video = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=red:s=160x90:r=30:d=0.8",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=blue:s=160x90:r=30:d=0.8",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=green:s=160x90:r=30:d=0.8",
                    "-filter_complex",
                    "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
                    "-map",
                    "[v]",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(video_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(make_video.returncode, 0, make_video.stderr)

            result = subprocess.run(
                [
                    sys.executable,
                    str(PREPARE_SCRIPT),
                    "--video",
                    str(video_path),
                    "--output",
                    str(rhythm_path),
                    "--scene-threshold",
                    "0.18",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            rhythm = json.loads(rhythm_path.read_text(encoding="utf-8"))
            self.assertEqual(rhythm["cut_detection"]["method"], "ffmpeg_scene_score")
            self.assertEqual(len(rhythm["actual_cut_points"]), 2)
            self.assertAlmostEqual(rhythm["actual_cut_points"][0]["time"], 0.8, delta=0.05)
            self.assertAlmostEqual(rhythm["actual_cut_points"][1]["time"], 1.6, delta=0.05)

    @unittest.skipIf(not shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_prepare_records_audio_energy_peak_for_emphasis_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video_path = root / "energy.mp4"
            rhythm_path = root / "source_rhythm.json"
            make_video = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=160x90:r=25:d=3",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=1000:sample_rate=16000:duration=3",
                    "-filter:a",
                    "volume='if(between(t,1,2),1,0)':eval=frame",
                    "-c:v",
                    "libx264",
                    "-c:a",
                    "aac",
                    "-shortest",
                    str(video_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(make_video.returncode, 0, make_video.stderr)

            result = subprocess.run(
                [
                    sys.executable,
                    str(PREPARE_SCRIPT),
                    "--video",
                    str(video_path),
                    "--output",
                    str(rhythm_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            rhythm = json.loads(rhythm_path.read_text(encoding="utf-8"))
            self.assertEqual(rhythm["audio_energy"]["method"], "pcm_rms")
            samples = rhythm["audio_energy"]["samples"]
            peak = max(samples, key=lambda sample: sample["normalized_rms"])
            self.assertGreaterEqual(peak["start"], 1.0)
            self.assertLess(peak["start"], 2.0)
            self.assertLess(samples[0]["normalized_rms"], 0.05)

    @unittest.skipIf(not shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_prepare_extracts_five_fps_evidence_for_transient_subtitles_and_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video_path = root / "one-second.mp4"
            rhythm_path = root / "source_rhythm.json"
            make_video = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=160x90:r=25:d=1",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(video_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(make_video.returncode, 0, make_video.stderr)

            result = subprocess.run(
                [
                    sys.executable,
                    str(PREPARE_SCRIPT),
                    "--video",
                    str(video_path),
                    "--output",
                    str(rhythm_path),
                    "--evidence-fps",
                    "5",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            rhythm = json.loads(rhythm_path.read_text(encoding="utf-8"))
            self.assertEqual(rhythm["schema_version"], 3)
            frames = rhythm["evidence_frames"]
            self.assertEqual(len(frames), 5)
            self.assertEqual([frame["time"] for frame in frames], [0.0, 0.2, 0.4, 0.6, 0.8])
            self.assertTrue(all(Path(frame["path"]).is_file() for frame in frames))


if __name__ == "__main__":
    unittest.main()
