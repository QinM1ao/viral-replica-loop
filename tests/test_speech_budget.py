import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from speech_budget import assess_speech_groups, spoken_units


class SpeechBudgetTest(unittest.TestCase):
    def test_percent_claim_counts_as_spoken_words(self):
        self.assertEqual(spoken_units("52%"), 5)

    def test_three_short_groups_with_silence_pass(self):
        result = assess_speech_groups(
            [
                {
                    "id": "speech1",
                    "target_start": 0.0,
                    "target_end": 5.0,
                    "speaker_kind": "narration",
                    "line": "相亲遇到小学同学，我真没想到。",
                },
                {
                    "id": "speech2",
                    "target_start": 5.0,
                    "target_end": 11.0,
                    "speaker_kind": "narration",
                    "line": "赶紧拿出孔凤春发酵水，倒在掌心轻拍吸收。",
                },
                {
                    "id": "speech3",
                    "target_start": 12.0,
                    "target_end": 14.5,
                    "speaker_kind": "sync",
                    "line": "状态一下醒了。",
                },
            ]
        )

        self.assertEqual(result["overall"], "PASS")
        self.assertEqual(result["metrics"]["speech_group_count"], 3)
        self.assertGreaterEqual(result["metrics"]["silence_seconds"], 0.5)

    def test_fast_source_can_raise_total_cap_to_ninety_with_warning(self):
        result = assess_speech_groups(
            [
                {
                    "id": "speech1",
                    "target_start": 0.0,
                    "target_end": 5.0,
                    "speaker_kind": "narration",
                    "line": "一" * 30,
                },
                {
                    "id": "speech2",
                    "target_start": 5.0,
                    "target_end": 10.0,
                    "speaker_kind": "narration",
                    "line": "二" * 30,
                },
                {
                    "id": "speech3",
                    "target_start": 10.0,
                    "target_end": 14.5,
                    "speaker_kind": "narration",
                    "line": "三" * 27,
                },
            ],
            source_units_per_second=6.27,
        )

        self.assertEqual(result["overall"], "PASS")
        self.assertEqual(result["limits"]["max_total_spoken_units"], 90)
        self.assertIn("source_matched_high_density", result["warnings"])

    def test_source_locked_localized_expansion_raises_only_the_bound_delta(self):
        groups = [
            {
                "id": f"speech{index}",
                "target_start": (index - 1) * (29 / 6.2),
                "target_end": index * (29 / 6.2),
                "speaker_kind": "narration",
                "line": character * 29,
            }
            for index, character in enumerate(("一", "二", "三"), start=1)
        ]

        without_bound_expansion = assess_speech_groups(
            groups,
            source_units_per_second=85 / 14.5,
            source_total_spoken_units=85,
        )
        with_bound_expansion = assess_speech_groups(
            groups,
            source_units_per_second=85 / 14.5,
            source_total_spoken_units=85,
            allowed_localized_expansion_units=2,
        )

        self.assertEqual(without_bound_expansion["overall"], "FAIL")
        self.assertEqual(with_bound_expansion["overall"], "PASS")
        self.assertEqual(with_bound_expansion["limits"]["max_total_spoken_units"], 87)

    def test_more_than_eighty_five_without_source_evidence_fails(self):
        result = assess_speech_groups(
            [
                {
                    "id": "speech1",
                    "target_start": 0.0,
                    "target_end": 5.0,
                    "speaker_kind": "narration",
                    "line": "一" * 30,
                },
                {
                    "id": "speech2",
                    "target_start": 5.0,
                    "target_end": 10.0,
                    "speaker_kind": "narration",
                    "line": "二" * 30,
                },
                {
                    "id": "speech3",
                    "target_start": 10.0,
                    "target_end": 14.5,
                    "speaker_kind": "narration",
                    "line": "三" * 27,
                },
            ]
        )

        self.assertEqual(result["overall"], "FAIL")
        self.assertIn("total_spoken_units", result["failed_rules"])

    def test_more_than_three_groups_fails(self):
        groups = [
            {
                "id": f"speech{index}",
                "target_start": float(index - 1) * 3,
                "target_end": float(index) * 3,
                "speaker_kind": "narration",
                "line": "这是一句短旁白。",
            }
            for index in range(1, 5)
        ]

        result = assess_speech_groups(groups)

        self.assertEqual(result["overall"], "FAIL")
        self.assertIn("speech_group_count", result["failed_rules"])

    def test_source_spoken_beats_allow_six_short_groups(self):
        groups = [
            {
                "id": f"speech{index}",
                "target_start": float(index - 1) * 2.4,
                "target_end": float(index) * 2.4,
                "speaker_kind": "sync" if index in {1, 3, 5} else "narration",
                "line": "短句。",
            }
            for index in range(1, 7)
        ]

        result = assess_speech_groups(
            groups,
            source_speech_group_count=4,
            source_spoken_beat_count=6,
        )

        self.assertEqual(result["overall"], "PASS")
        self.assertEqual(result["limits"]["max_speech_groups"], 6)
        self.assertIn("source_matched_extra_speech_group", result["warnings"])

    def test_rushed_group_fails_even_when_total_copy_is_short(self):
        result = assess_speech_groups(
            [
                {
                    "id": "speech1",
                    "target_start": 0.0,
                    "target_end": 2.0,
                    "speaker_kind": "narration",
                    "line": "相亲遇到小学同学这件事情我真的完全没有想到。",
                }
            ]
        )

        self.assertEqual(result["overall"], "FAIL")
        self.assertIn("max_group_chars_per_second", result["failed_rules"])

    def test_exact_rate_boundary_is_not_rejected_by_float_noise(self):
        result = assess_speech_groups(
            [
                {
                    "id": "speech1",
                    "target_start": 8.9,
                    "target_end": 8.9 + 11 / 6.2,
                    "speaker_kind": "sync",
                    "line": "甲乙丙丁戊己庚辛壬癸子",
                }
            ]
        )

        self.assertEqual(result["overall"], "PASS")

    def test_source_locked_group_may_keep_measured_fast_source_pace(self):
        result = assess_speech_groups(
            [
                {
                    "id": "speech1",
                    "target_start": 0.0,
                    "target_end": 2.25,
                    "speaker_kind": "sync",
                    "line": "一" * 21,
                    "source_spoken_units": 21,
                    "source_duration_seconds": 2.25,
                    "allowed_localized_expansion_units": 0,
                }
            ],
            part_duration=2.57,
            source_pause_seconds=0.32,
        )

        self.assertEqual(result["overall"], "PASS")
        self.assertEqual(
            result["limits"]["max_group_chars_per_second"],
            9.333,
        )
        self.assertEqual(result["limits"]["min_silence_seconds"], 0.32)

    def test_source_locked_group_rejects_unbound_copy_beyond_source_capacity(self):
        result = assess_speech_groups(
            [
                {
                    "id": "speech1",
                    "target_start": 0.0,
                    "target_end": 2.25,
                    "speaker_kind": "sync",
                    "line": "一" * 23,
                    "source_spoken_units": 21,
                    "source_duration_seconds": 2.25,
                    "allowed_localized_expansion_units": 1,
                }
            ],
            part_duration=2.57,
            source_pause_seconds=0.32,
        )

        self.assertEqual(result["overall"], "FAIL")
        self.assertIn("max_group_chars_per_second", result["failed_rules"])

    def test_source_locked_sync_group_keeps_measured_source_sentence_length(self):
        result = assess_speech_groups(
            [
                {
                    "id": "speech1",
                    "target_start": 0.0,
                    "target_end": 3.0,
                    "speaker_kind": "sync",
                    "line": "一" * 23,
                    "source_spoken_units": 26,
                    "source_duration_seconds": 3.0,
                    "source_max_sync_units": 26,
                    "allowed_localized_expansion_units": 0,
                }
            ],
            part_duration=3.5,
        )

        self.assertEqual(result["overall"], "PASS")
        self.assertEqual(result["limits"]["max_sync_line_units"], 26)

    def test_source_locked_sync_group_rejects_unbound_longer_sentence(self):
        result = assess_speech_groups(
            [
                {
                    "id": "speech1",
                    "target_start": 0.0,
                    "target_end": 4.5,
                    "speaker_kind": "sync",
                    "line": "一" * 27,
                    "source_spoken_units": 26,
                    "source_duration_seconds": 4.5,
                    "source_max_sync_units": 26,
                    "allowed_localized_expansion_units": 0,
                }
            ],
            part_duration=5.0,
        )

        self.assertEqual(result["overall"], "FAIL")
        self.assertIn("sync_line_units", result["failed_rules"])

    def test_long_sync_line_fails(self):
        result = assess_speech_groups(
            [
                {
                    "id": "speech1",
                    "target_start": 0.0,
                    "target_end": 6.0,
                    "speaker_kind": "sync",
                    "line": "轻拍上脸以后整个皮肤状态立刻醒过来而且一点都不黏腻。",
                }
            ]
        )

        self.assertEqual(result["overall"], "FAIL")
        self.assertIn("sync_line_units", result["failed_rules"])

    def test_sync_group_allows_multiple_short_sentences(self):
        result = assess_speech_groups(
            [
                {
                    "id": "speech1",
                    "target_start": 0.0,
                    "target_end": 6.0,
                    "speaker_kind": "sync",
                    "line": "管它黑头还是油光。孔凤春清洁泥膜，建议油皮看好了。四种果酸松动毛孔油脂。",
                }
            ]
        )

        self.assertEqual(result["overall"], "PASS")
        self.assertLessEqual(result["metrics"]["max_sync_line_units"], 22)

    def test_groups_must_leave_silence_and_must_not_overlap(self):
        no_silence = assess_speech_groups(
            [
                {
                    "id": "speech1",
                    "target_start": 0.0,
                    "target_end": 8.0,
                    "speaker_kind": "narration",
                    "line": "第一段。",
                },
                {
                    "id": "speech2",
                    "target_start": 8.0,
                    "target_end": 15.0,
                    "speaker_kind": "narration",
                    "line": "第二段。",
                },
            ]
        )
        overlap = assess_speech_groups(
            [
                {
                    "id": "speech1",
                    "target_start": 0.0,
                    "target_end": 8.0,
                    "speaker_kind": "narration",
                    "line": "第一段。",
                },
                {
                    "id": "speech2",
                    "target_start": 7.0,
                    "target_end": 12.0,
                    "speaker_kind": "narration",
                    "line": "第二段。",
                },
            ]
        )

        self.assertIn("silence_seconds", no_silence["failed_rules"])
        self.assertIn("speech_group_overlap", overlap["failed_rules"])


if __name__ == "__main__":
    unittest.main()
