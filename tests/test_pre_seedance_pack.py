import csv
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "pre_seedance_pack.py"
sys.path.insert(0, str(REPO_ROOT / "tools"))

LOCKED_VISUAL_DIMENSIONS = [
    "shot_order",
    "scene",
    "camera",
    "framing",
    "action_stage",
    "action_timing",
    "hard_cuts",
]
class PreSeedancePackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.job_id = "job-001"
        self.job_dir = self.root / "output" / self.job_id
        self._write_fixture()

    def tearDown(self):
        self.tmp.cleanup()

    def run_pack(self, *args, check=True):
        result = subprocess.run(
            ["python3", str(SCRIPT), *args, "--root", str(self.root), "--job-id", self.job_id],
            text=True,
            capture_output=True,
            check=False,
        )
        if check and result.returncode != 0:
            self.fail(f"pre_seedance_pack failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        return result

    def _write_fixture(self):
        (self.root / "rules").mkdir(parents=True)
        (self.job_dir / "visual-assets").mkdir(parents=True)
        for rel, content in {
            "output/job-001/final-images/part1.png": b"part1",
            "output/job-001/final-images/part2.png": b"part2",
            "output/shared/product/front.png": b"front",
            "output/shared/product/open.png": b"open",
            "output/shared/identity/host.png": b"host",
        }.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

        with (self.root / "jobs.csv").open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=[
                    "id",
                    "status",
                    "video_path",
                    "product_name",
                    "product_assets",
                    "person_assets",
                    "audio_assets",
                    "target_duration",
                    "handoff_mode",
                    "notes",
                    "output_dir",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "id": self.job_id,
                    "status": "image_qc_passed",
                    "video_path": "source.mp4",
                    "product_name": "Test Toner",
                    "product_assets": "assets/product",
                    "person_assets": "assets/person",
                    "audio_assets": "extract_from_original",
                    "target_duration": "30s",
                    "handoff_mode": "api",
                    "notes": "Preserve the source story.",
                    "output_dir": "output/job-001",
                }
            )

        self._write_json(
            self.job_dir / "visual-assets" / "approved_visual_manifest.json",
            {
                "job_id": self.job_id,
                "source_presenter_gender": "female",
                "target_presenter_gender": "female",
                "reusable_refs": {
                    "product_front": "output/shared/product/front.png",
                    "product_open": "output/shared/product/open.png",
                    "identity_ref": "output/shared/identity/host.png",
                },
                "part_storyboards": {
                    "part1": {"path": "output/job-001/final-images/part1.png"},
                    "part2": {"path": "output/job-001/final-images/part2.png"},
                },
            },
        )
        self._write_json(
            self.root / "rules" / "SEEDANCE_MODEL.json",
            {
                "model_name": "Seedance 2.0",
                "model": "ep-test-ordinary",
                "request_field": "model",
                "task_code": 2509,
                "endpoint": "task_create",
                "ratio": "9:16",
                "duration_seconds_per_part": 15,
                "resolution": "720p",
                "generate_audio": True,
            },
        )
        self._write_json(
            self.job_dir / "剧情分析" / "source_rhythm.json",
            {
                "schema_version": 3,
                "source_sha256": "fixture-source-video",
                "duration": 30.0,
                "beats": [],
            },
        )
        self._write_json(
            self.job_dir / "intake.json",
            {
                "schema_version": 1,
                "job_id": self.job_id,
                "requests": ["Fixture explicitly requests this test-only change."],
                "target_duration": {
                    "value": "30s",
                    "explicitly_requested": False,
                    "request_evidence": None,
                },
            },
        )
        self._write_json(
            self.job_dir / "product_profile.json",
            {
                "version": 1,
                "job_id": self.job_id,
                "product_name": "Test Toner",
                "visible_text_patterns": ["Test Toner", "soothing hydration"],
                "usage_action": "press the pump to create a fine mist",
            },
        )

    def _write_json(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _request_evidence(self):
        path = self.job_dir / "intake.json"
        return {
            "source": "intake",
            "path": "output/job-001/intake.json",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "quote": "Fixture explicitly requests this test-only change.",
        }

    def _fact_evidence(
        self,
        source_slot,
        target_slot,
        conflict_kind,
        *,
        target_policy="profile_supported",
        json_pointer="/usage_action",
        quote="fine mist",
    ):
        path = self.job_dir / "product_profile.json"
        return {
            "source": "product_profile",
            "path": "output/job-001/product_profile.json",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "source_slot": source_slot,
            "target_slot": target_slot,
            "conflict_kind": conflict_kind,
            "target_policy": target_policy,
            "support_refs": [
                {
                    "json_pointer": json_pointer,
                    "quote": quote,
                }
            ],
        }

    def _bind_product_slot_evidence(self, plan, part, slots):
        rhythm_path = self.job_dir / "剧情分析" / "source_rhythm.json"
        rhythm = {
            "schema_version": 3,
            "source_sha256": "fixture-source-video",
            "duration": 30.0,
            "beats": [],
        }
        checks = []
        for target_beat, beat_id, source_line, product_name in slots:
            target_beat["source_beat_ids"] = [beat_id]
            rhythm["beats"].append(
                {
                    "id": beat_id,
                    "confirmed_source_line": source_line,
                    "spoken_product_names": [product_name],
                }
            )
            checks.append(
                {
                    "beat_id": beat_id,
                    "status": "PASS",
                    "confirmed_spoken_product_names": [product_name],
                    "spoken_product_names_are_product_entities": True,
                    "stop_reasons": [],
                    "fail_reasons": [],
                }
            )
        self._write_json(rhythm_path, rhythm)
        rhythm_sha = hashlib.sha256(rhythm_path.read_bytes()).hexdigest()
        plan["source_rhythm"]["analysis_sha256"] = rhythm_sha
        self._write_json(
            self.job_dir / "checks" / "source_rhythm_visual_review_qc.json",
            {
                "overall": "PASS",
                "source_rhythm": "output/job-001/剧情分析/source_rhythm.json",
                "source_rhythm_sha256": rhythm_sha,
                "checks": checks,
            },
        )
        return {
            beat_id: {
                "source": "source_rhythm",
                "path": "output/job-001/剧情分析/source_rhythm.json",
                "sha256": rhythm_sha,
                "beat_id": beat_id,
                "text": product_name,
            }
            for _target_beat, beat_id, _source_line, product_name in slots
        }

    def _declare_line_edits(self, plan):
        for part in plan["parts"]:
            beats = {beat["id"]: beat for beat in part["beats"]}
            for group in part["speech_groups"]:
                source_line = "".join(
                    beats[beat_id]["source_line"] for beat_id in group["beat_ids"]
                )
                if source_line == group["line"]:
                    group["line_edits"] = []
                    continue
                group["line_edits"] = [
                    {
                        "kind": "replace",
                        "from": source_line,
                        "to": group["line"],
                        "reason": "user_requested",
                        "reason_detail": "Test fixture declares its intentional target-line change.",
                        "request_evidence": self._request_evidence(),
                    }
                ]

    def _declare_visual_edits(self, plan):
        for part in plan["parts"]:
            for beat in part["beats"]:
                if beat["source_visual_action"] == beat["target_visual_action"]:
                    beat["visual_edits"] = []
                    continue
                beat["visual_edits"] = [
                    {
                        "from": beat["source_visual_action"],
                        "to": beat["target_visual_action"],
                        "reason": "user_requested",
                        "reason_detail": "Fixture explicitly requests this test-only visual replacement.",
                        "request_evidence": self._request_evidence(),
                        "preserved_dimensions": LOCKED_VISUAL_DIMENSIONS,
                    }
                ]

    def _fill_plan(self, mode="both"):
        plan_path = self.job_dir / "seedance" / "director_plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["handoff_mode"] = mode
        for part_index, part in enumerate(plan["parts"], start=1):
            part["main_goal"] = f"Part {part_index} main goal"
            part["secondary_goal"] = "Keep product and identity stable"
            part["simplify"] = "Exclude unrelated people and unrelated products"
            part["seam"]["start_state"] = f"Part {part_index} opening motion"
            part["seam"]["end_state"] = f"Part {part_index} closing motion"
            for beat_index, beat in enumerate(part["beats"], start=1):
                mode_name = "女主画面内同期口播" if beat_index in {3, 4} else "女主画外音旁白"
                beat.update(
                    {
                        "source_start": beat["target_start"],
                        "source_end": beat["target_end"],
                        "source_visual_action": f"Source action {beat_index}",
                        "source_speaker_mode": mode_name,
                        "source_line": f"Source line {beat_index}",
                        "target_visual_action": f"Target action {beat_index}",
                        "visual_fidelity": {
                            "source_scene": f"Scene {beat_index}",
                            "target_scene": f"Scene {beat_index}",
                            "source_camera": f"Camera {beat_index}",
                            "target_camera": f"Camera {beat_index}",
                            "source_framing": f"Framing {beat_index}",
                            "target_framing": f"Framing {beat_index}",
                            "source_action_stage": f"Action stage {beat_index}",
                            "target_action_stage": f"Action stage {beat_index}",
                            "source_action_timing": "peak_fractions=0.500",
                            "target_action_timing": "peak_fractions=0.500",
                            "source_transition": "hard_cut",
                            "target_transition": "hard_cut",
                            "source_hard_cuts": "entry=hard_cut;exit=hard_cut",
                            "target_hard_cuts": "entry=hard_cut;exit=hard_cut",
                        },
                        "sound_effect": f"Action sound {beat_index}",
                        "reference_binding": "@图片1/@图片2",
                        "must_keep_reason": "Source beat",
                    }
                )
            part["speech_groups"] = [
                {
                    "id": "speech1",
                    "target_start": 0.0,
                    "target_end": 5.0,
                    "speaker_mode": "女主画外音旁白",
                    "line": "Test Toner." if part_index == 2 else "First narration line.",
                    "beat_ids": ["beat1", "beat2"],
                },
                {
                    "id": "speech2",
                    "target_start": 5.0,
                    "target_end": 10.0,
                    "speaker_mode": "女主画面内同期口播",
                    "line": "Short sync line.",
                    "beat_ids": ["beat3", "beat4"],
                },
                {
                    "id": "speech3",
                    "target_start": 10.0,
                    "target_end": 14.5,
                    "speaker_mode": "女主画外音旁白",
                    "line": "Final narration line.",
                    "beat_ids": ["beat5", "beat6"],
                },
            ]
            part["execution_blocks"] = [
                {"id": "block1", "beat_ids": ["beat1", "beat2"]},
                {"id": "block2", "beat_ids": ["beat3", "beat4"]},
                {"id": "block3", "beat_ids": ["beat5", "beat6"]},
            ]
            part["source_functions"] = [
                {
                    "id": f"function{beat_index}",
                    "label": f"Source function {beat_index}",
                    "priority": "must_keep",
                    "coverage": "both",
                    "target_refs": [
                        f"beat{beat_index}",
                        "speech1" if beat_index <= 2 else "speech2" if beat_index <= 4 else "speech3",
                    ],
                }
                for beat_index in range(1, 7)
            ]
        plan["spoken_product_anchor"] = {
            "enabled": True,
            "full_name": "Test Toner",
            "brand_name": "Test",
            "part_id": "part2",
            "speech_group_id": "speech1",
        }
        self._declare_line_edits(plan)
        self._declare_visual_edits(plan)
        self._write_json(plan_path, plan)
        return plan_path

    def test_init_builds_dynamic_part_skeleton(self):
        self.run_pack("init")

        plan = json.loads((self.job_dir / "seedance" / "director_plan.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["job"]["product_name"], "Test Toner")
        self.assertEqual([part["id"] for part in plan["parts"]], ["part1", "part2"])
        self.assertEqual(plan["model_route"]["model"], "ep-test-ordinary")
        self.assertEqual(len(plan["parts"][0]["beats"]), 6)
        self.assertEqual(
            [beat["id"] for beat in plan["parts"][0]["beats"]],
            ["beat1", "beat2", "beat3", "beat4", "beat5", "beat6"],
        )
        self.assertEqual(plan["parts"][0]["speech_groups"], [])
        self.assertEqual(plan["parts"][0]["execution_blocks"], [])
        self.assertEqual(plan["parts"][0]["source_functions"], [])
        self.assertEqual(
            [(beat["panel_start"], beat["panel_end"]) for beat in plan["parts"][0]["beats"]],
            [(1, 2), (3, 4), (5, 6), (7, 8), (9, 10), (11, 12)],
        )
        self.assertTrue(
            all(beat["source_beat_ids"] == [] for beat in plan["parts"][0]["beats"])
        )
        self.assertEqual(plan["handoff_mode"], "api")
        self.assertEqual(
            plan["presenter_gender"],
            {"source": "female", "target": "female"},
        )

    def test_init_binds_current_source_rhythm_hash(self):
        rhythm_path = self.job_dir / "剧情分析" / "source_rhythm.json"
        self._write_json(
            rhythm_path,
            {
                "schema_version": 3,
                "source_sha256": "source-video-hash",
                "duration": 30.0,
                "beats": [],
            },
        )

        self.run_pack("init")

        plan = json.loads(
            (self.job_dir / "seedance" / "director_plan.json").read_text(encoding="utf-8")
        )
        self.assertEqual(plan["version"], 6)
        self.assertEqual(plan["script_fidelity"], {"mode": "source_locked"})
        self.assertEqual(
            plan["replication_fidelity"],
            {
                "mode": "source_locked",
                "change_policy": "necessary_only",
                "duration_mode": "source_length",
                "user_request_evidence": None,
                "locked_visual_dimensions": LOCKED_VISUAL_DIMENSIONS,
            },
        )
        self.assertTrue(
            all(
                beat["visual_edits"] == []
                for part in plan["parts"]
                for beat in part["beats"]
            )
        )
        self.assertEqual(plan["spoken_product_anchor"], {"enabled": False})
        self.assertEqual(
            plan["source_rhythm"],
            {
                "path": "output/job-001/剧情分析/source_rhythm.json",
                "analysis_sha256": hashlib.sha256(rhythm_path.read_bytes()).hexdigest(),
                "source_video_sha256": "source-video-hash",
            },
        )

    def test_init_requires_current_source_rhythm_for_new_flow(self):
        (self.job_dir / "剧情分析" / "source_rhythm.json").unlink()

        result = self.run_pack("init", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("source_rhythm.json is required", result.stderr)

    def test_render_rejects_execution_block_covering_more_than_five_panels(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["parts"][0]["execution_blocks"] = [
            {"id": "block1", "beat_ids": ["beat1", "beat2", "beat3"]},
            {"id": "block2", "beat_ids": ["beat4"]},
            {"id": "block3", "beat_ids": ["beat5", "beat6"]},
        ]
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("at most 5 storyboard panels", result.stderr)

    def test_render_rejects_execution_block_crossing_speaker_mode_boundary(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        part = plan["parts"][0]
        part["speech_groups"] = [
            {
                "id": "speech1",
                "target_start": 0.0,
                "target_end": 2.4,
                "speaker_mode": "女主画外音旁白",
                "line": "First narration.",
                "beat_ids": ["beat1"],
            },
            {
                "id": "speech2",
                "target_start": 2.5,
                "target_end": 4.9,
                "speaker_mode": "女主画外音旁白",
                "line": "Second narration.",
                "beat_ids": ["beat2"],
            },
            {
                "id": "speech3",
                "target_start": 5.0,
                "target_end": 7.4,
                "speaker_mode": "女主画面内同期口播",
                "line": "First sync line.",
                "beat_ids": ["beat3"],
            },
            {
                "id": "speech4",
                "target_start": 7.5,
                "target_end": 9.9,
                "speaker_mode": "女主画面内同期口播",
                "line": "Second sync line.",
                "beat_ids": ["beat4"],
            },
            {
                "id": "speech5",
                "target_start": 10.0,
                "target_end": 14.5,
                "speaker_mode": "女主画外音旁白",
                "line": "Final narration.",
                "beat_ids": ["beat5", "beat6"],
            },
        ]
        part["execution_blocks"] = [
            {"id": "block1", "beat_ids": ["beat1"]},
            {"id": "block2", "beat_ids": ["beat2", "beat3"]},
            {"id": "block3", "beat_ids": ["beat4"]},
            {"id": "block4", "beat_ids": ["beat5", "beat6"]},
        ]
        self._declare_line_edits(plan)
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("crosses speaker-mode boundaries", result.stderr)

    def test_render_preserves_repeated_product_mentions_when_source_repeats(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        first_group = plan["parts"][0]["speech_groups"][0]
        first_beats = plan["parts"][0]["beats"]
        first_beats[0]["source_line"] = "Test "
        first_beats[1]["source_line"] = "Toner."
        first_group["line"] = "Test Toner."
        first_group["line_edits"] = []
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_render_preserves_product_name_inside_the_source_sentence(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        anchor = plan["parts"][1]["speech_groups"][0]
        anchor_beats = plan["parts"][1]["beats"]
        anchor_beats[0]["source_line"] = "Try "
        anchor_beats[1]["source_line"] = "Test Toner today."
        anchor["line"] = "Try Test Toner today."
        anchor["line_edits"] = []
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_version_six_rejects_undeclared_visual_rewrite(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["parts"][0]["beats"][0]["visual_edits"] = []
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("undeclared visual rewrite", result.stderr)

    def test_version_six_rejects_whole_hook_rewrite_as_product_fact(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        part = plan["parts"][0]
        part["beats"][0]["source_line"] = "这个它很贵，"
        part["beats"][1]["source_line"] = "但改善暗沉很牛。"
        group = part["speech_groups"][0]
        group["line"] = "虽然价格高，但提亮效果很好。"
        group["line_edits"] = [
            {
                "kind": "replace",
                "from": "这个它很贵，但改善暗沉很牛。",
                "to": "虽然价格高，但提亮效果很好。",
                "reason": "product_fact",
                "reason_detail": "Rewrite the whole hook into smoother ad copy.",
            }
        ]
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must edit a local slot, not replace the whole source line", result.stderr)

    def test_version_six_rejects_person_or_role_rewrite_without_request_evidence(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        part = plan["parts"][0]
        part["beats"][0]["source_line"] = "我反正老是"
        part["beats"][1]["source_line"] = "素颜出门"
        group = part["speech_groups"][0]
        group["line"] = "平时素颜出门"
        group["line_edits"] = [
            {
                "kind": "replace",
                "from": "我反正老是",
                "to": "平时",
                "reason": "person_or_role",
                "reason_detail": "Make the source line sound smoother.",
            }
        ]
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("person_or_role requires request_evidence", result.stderr)

        plan["parts"][0]["speech_groups"][0]["line_edits"][0][
            "request_evidence"
        ] = self._request_evidence()
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_version_six_rejects_product_fact_rewrite_without_profile_evidence(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        part = plan["parts"][0]
        part["beats"][0]["source_line"] = "我自己感觉"
        part["beats"][1]["source_line"] = "很好"
        group = part["speech_groups"][0]
        group["line"] = "我自己感觉特别绝"
        group["line_edits"] = [
            {
                "kind": "replace",
                "from": "很好",
                "to": "特别绝",
                "reason": "product_fact",
                "reason_detail": "Strengthen the testimonial.",
            }
        ]
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("product_fact requires fact_evidence", result.stderr)

        plan["parts"][0]["speech_groups"][0]["line_edits"][0][
            "fact_evidence"
        ] = self._fact_evidence(
            "很好",
            "特别绝",
            "unsupported_effect",
        )
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_version_six_rejects_frequency_rewrite_when_profile_only_omits_frequency(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        part = plan["parts"][0]
        part["beats"][0]["source_line"] = "但你要是蜡黄暗沉粗糙起皮的你"
        part["beats"][1]["source_line"] = "就一天喷两次"
        group = part["speech_groups"][0]
        group["line"] = "但你要是蜡黄暗沉粗糙起皮的你就按需再喷一次"
        group["line_edits"] = [
            {
                "kind": "replace",
                "from": "一天喷两次",
                "to": "按需再喷一次",
                "reason": "product_fact",
                "reason_detail": "The profile does not specify a daily frequency.",
                "fact_evidence": self._fact_evidence(
                    "一天喷两次",
                    "按需再喷一次",
                    "unsupported_frequency",
                ),
            }
        ]
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("product_fact requires fact_evidence", result.stderr)

    def test_version_six_allows_frequency_rewrite_for_direct_profile_contradiction(self):
        profile_path = self.job_dir / "product_profile.json"
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        profile["usage_frequency"] = "每周喷一次"
        self._write_json(profile_path, profile)
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        part = plan["parts"][0]
        part["beats"][0]["source_line"] = "但你要是蜡黄暗沉粗糙起皮的你"
        part["beats"][1]["source_line"] = "就一天喷两次"
        group = part["speech_groups"][0]
        group["line"] = "但你要是蜡黄暗沉粗糙起皮的你就每周喷一次"
        group["line_edits"] = [
            {
                "kind": "replace",
                "from": "一天喷两次",
                "to": "每周喷一次",
                "reason": "product_fact",
                "reason_detail": "The profile directly specifies a different frequency.",
                "fact_evidence": self._fact_evidence(
                    "一天喷两次",
                    "每周喷一次",
                    "contradicted_frequency",
                    json_pointer="/usage_frequency",
                    quote="每周喷一次",
                ),
            }
        ]
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_version_six_keeps_unchanged_hook_verbatim(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        part = plan["parts"][0]
        part["beats"][0]["source_line"] = "这个它很贵，"
        part["beats"][1]["source_line"] = "但改善暗沉很牛。"
        group = part["speech_groups"][0]
        group["line"] = "这个它很贵，但改善暗沉很牛。"
        group["line_edits"] = []
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertEqual(result.returncode, 0, result.stderr)
        audit = (self.job_dir / "voiceover" / "source_script_fidelity.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("这个它很贵，但改善暗沉很牛。", audit)
        self.assertIn("| exact |", audit)

    def test_version_six_rejects_user_requested_rewrite_without_request_evidence(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        edit = plan["parts"][0]["speech_groups"][0]["line_edits"][0]
        edit["reason"] = "user_requested"
        edit.pop("request_evidence", None)
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("user_requested requires request_evidence", result.stderr)

    def test_version_six_rejects_forged_request_evidence(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        edit = plan["parts"][0]["speech_groups"][0]["line_edits"][0]
        edit["request_evidence"] = {
            "source": "intake",
            "path": "output/job-999/intake.json",
            "sha256": "a" * 64,
            "quote": "Fabricated request.",
        }
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must bind the current job", result.stderr)

    def test_version_six_rejects_real_request_evidence_from_another_job(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        other_intake = self.root / "output" / "job-999" / "intake.json"
        self._write_json(
            other_intake,
            {"requests": ["Fixture explicitly requests this test-only change."]},
        )
        edit = plan["parts"][0]["speech_groups"][0]["line_edits"][0]
        edit["request_evidence"] = {
            "source": "intake",
            "path": "output/job-999/intake.json",
            "sha256": hashlib.sha256(other_intake.read_bytes()).hexdigest(),
            "quote": "Fixture explicitly requests this test-only change.",
        }
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must bind the current job", result.stderr)

    def test_version_six_rejects_duration_compression_as_rewrite(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["replication_fidelity"]["duration_mode"] = "user_compressed"
        plan["replication_fidelity"]["user_request_evidence"] = self._request_evidence()
        edit = plan["parts"][0]["speech_groups"][0]["line_edits"][0]
        edit["reason"] = "duration_compression"
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duration_compression may only delete", result.stderr)

    def test_version_six_source_length_rejects_dropped_source_function(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        function = plan["parts"][0]["source_functions"][0]
        function.update(
            {
                "priority": "removable",
                "coverage": "dropped",
                "target_refs": [],
            }
        )
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("source_length replication cannot drop source functions", result.stderr)

    def test_version_six_keeps_covered_removable_source_function(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["parts"][0]["source_functions"][0]["priority"] = "removable"
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_version_six_disables_product_anchor_when_source_never_names_product(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["spoken_product_anchor"] = {"enabled": False}
        part = plan["parts"][1]
        group = part["speech_groups"][0]
        beats = {beat["id"]: beat for beat in part["beats"]}
        group["line"] = "".join(beats[beat_id]["source_line"] for beat_id in group["beat_ids"])
        group["line_edits"] = []
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_version_six_rejects_whole_hook_replacement_as_product_name(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        part = plan["parts"][0]
        part["beats"][0]["source_line"] = "这个它很贵，"
        part["beats"][1]["source_line"] = "但改善暗沉很牛。"
        group = part["speech_groups"][0]
        group["line"] = "Test Toner"
        group["line_edits"] = [
            {
                "kind": "replace",
                "from": "这个它很贵，但改善暗沉很牛。",
                "to": "Test Toner",
                "reason": "product_name",
                "reason_detail": "Incorrectly replaces the whole hook.",
                "source_slot_kind": "product_name",
                "source_slot_evidence": {
                    "source": "source_rhythm",
                    "path": "output/job-001/剧情分析/source_rhythm.json",
                    "sha256": "a" * 64,
                    "beat_id": "fake",
                    "text": "这个它很贵，但改善暗沉很牛。",
                },
            }
        ]
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("product_name edit requires current source-slot evidence", result.stderr)

    def test_version_six_can_replace_repeated_product_slots_by_occurrence(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        part = plan["parts"][1]
        part["beats"][0]["source_line"] = "Old Product，"
        part["beats"][1]["source_line"] = "Old Product。"
        evidence = self._bind_product_slot_evidence(
            plan,
            part,
            [
                (part["beats"][0], "sr-product-1", "Old Product，", "Old Product"),
                (part["beats"][1], "sr-product-2", "Old Product。", "Old Product"),
            ],
        )
        group = part["speech_groups"][0]
        group["line"] = "Test Toner，Test Toner。"
        group["line_edits"] = [
            {
                "kind": "replace",
                "from": "Old Product",
                "to": "Test Toner",
                "occurrence": 1,
                "reason": "product_name",
                "reason_detail": "Replace the first source product mention.",
                "source_slot_evidence": evidence["sr-product-1"],
            },
            {
                "kind": "replace",
                "from": "Old Product",
                "to": "Test Toner",
                "occurrence": 1,
                "reason": "product_name",
                "reason_detail": "Replace the remaining source product mention.",
                "source_slot_evidence": evidence["sr-product-2"],
            },
        ]
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_version_six_rejects_local_product_edit_without_current_slot_evidence(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        part = plan["parts"][0]
        part["beats"][0]["source_line"] = "这个它很贵，"
        part["beats"][1]["source_line"] = "但改善暗沉很牛。"
        group = part["speech_groups"][0]
        group["line"] = "Test Toner它很贵，但改善暗沉很牛。"
        group["line_edits"] = [
            {
                "kind": "replace",
                "from": "这个",
                "to": "Test Toner",
                "reason": "product_name",
                "reason_detail": "Incorrectly labels an ordinary pronoun as a product slot.",
            }
        ]
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("product_name edit requires current source-slot evidence", result.stderr)

    def test_product_slot_evidence_must_bind_the_selected_occurrence(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        part = plan["parts"][0]
        part["beats"][0]["source_line"] = "Apple tastes good，"
        part["beats"][0]["source_beat_ids"] = ["sr-food"]
        part["beats"][1]["source_line"] = "Apple Phone lasts long。"
        part["beats"][1]["source_beat_ids"] = ["sr-phone"]
        rhythm_path = self.job_dir / "剧情分析" / "source_rhythm.json"
        self._write_json(
            rhythm_path,
            {
                "schema_version": 3,
                "source_sha256": "fixture-source-video",
                "duration": 30.0,
                "beats": [
                    {
                        "id": "sr-food",
                        "confirmed_source_line": "Apple tastes good，",
                        "spoken_product_names": [],
                    },
                    {
                        "id": "sr-phone",
                        "confirmed_source_line": "Apple Phone lasts long。",
                        "spoken_product_names": ["Apple"],
                    },
                ],
            },
        )
        rhythm_sha = hashlib.sha256(rhythm_path.read_bytes()).hexdigest()
        plan["source_rhythm"]["analysis_sha256"] = rhythm_sha
        self._write_json(
            self.job_dir / "checks" / "source_rhythm_visual_review_qc.json",
            {
                "overall": "PASS",
                "source_rhythm_sha256": rhythm_sha,
                "checks": [
                    {
                        "beat_id": "sr-phone",
                        "confirmed_spoken_product_names": ["Apple"],
                        "spoken_product_names_are_product_entities": True,
                    }
                ],
            },
        )
        group = part["speech_groups"][0]
        group["line"] = "Test Toner tastes good，Apple Phone lasts long。"
        group["line_edits"] = [
            {
                "kind": "replace",
                "from": "Apple",
                "to": "Test Toner",
                "occurrence": 1,
                "reason": "product_name",
                "reason_detail": "Incorrectly targets the food occurrence.",
                "source_slot_evidence": {
                    "source": "source_rhythm",
                    "path": "output/job-001/剧情分析/source_rhythm.json",
                    "sha256": rhythm_sha,
                    "beat_id": "sr-phone",
                    "text": "Apple",
                },
            }
        ]
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("product_name edit requires current source-slot evidence", result.stderr)

    def test_product_slot_evidence_cannot_cover_a_cross_beat_occurrence(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        part = plan["parts"][0]
        part["beats"][0]["source_line"] = "AppleAp"
        part["beats"][0]["source_beat_ids"] = ["sr-one"]
        part["beats"][1]["source_line"] = "ple"
        part["beats"][1]["source_beat_ids"] = ["sr-two"]
        rhythm_path = self.job_dir / "剧情分析" / "source_rhythm.json"
        self._write_json(
            rhythm_path,
            {
                "schema_version": 3,
                "source_sha256": "fixture-source-video",
                "duration": 30.0,
                "beats": [
                    {
                        "id": "sr-one",
                        "confirmed_source_line": "AppleAp",
                        "spoken_product_names": ["Apple"],
                    },
                    {
                        "id": "sr-two",
                        "confirmed_source_line": "ple",
                        "spoken_product_names": [],
                    },
                ],
            },
        )
        rhythm_sha = hashlib.sha256(rhythm_path.read_bytes()).hexdigest()
        plan["source_rhythm"]["analysis_sha256"] = rhythm_sha
        self._write_json(
            self.job_dir / "checks" / "source_rhythm_visual_review_qc.json",
            {
                "overall": "PASS",
                "source_rhythm_sha256": rhythm_sha,
                "checks": [
                    {
                        "beat_id": "sr-one",
                        "confirmed_spoken_product_names": ["Apple"],
                        "spoken_product_names_are_product_entities": True,
                    }
                ],
            },
        )
        group = part["speech_groups"][0]
        group["line"] = "AppleTest Toner"
        group["line_edits"] = [
            {
                "kind": "replace",
                "from": "Apple",
                "to": "Test Toner",
                "occurrence": 2,
                "reason": "product_name",
                "reason_detail": "Incorrectly spans two source beats.",
                "source_slot_evidence": {
                    "source": "source_rhythm",
                    "path": "output/job-001/剧情分析/source_rhythm.json",
                    "sha256": rhythm_sha,
                    "beat_id": "sr-one",
                    "text": "Apple",
                },
            }
        ]
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("product_name edit requires current source-slot evidence", result.stderr)

    def test_render_rejects_source_rhythm_schema_downgrade(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        rhythm_path = self.job_dir / "剧情分析" / "source_rhythm.json"
        rhythm = json.loads(rhythm_path.read_text(encoding="utf-8"))
        rhythm["schema_version"] = 2
        self._write_json(rhythm_path, rhythm)
        plan["source_rhythm"]["analysis_sha256"] = hashlib.sha256(
            rhythm_path.read_bytes()
        ).hexdigest()
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("schema_version must be at least 3", result.stderr)

    def test_version_six_rejects_locked_transition_change(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["parts"][0]["beats"][0]["visual_fidelity"]["target_transition"] = "continuous"
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must preserve source_transition", result.stderr)

    def test_init_rejects_implicit_duration_compression_without_intake_evidence(self):
        rhythm_path = self.job_dir / "剧情分析" / "source_rhythm.json"
        rhythm = json.loads(rhythm_path.read_text(encoding="utf-8"))
        rhythm["duration"] = 40.0
        self._write_json(rhythm_path, rhythm)

        result = self.run_pack("init", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("explicit target-duration intake evidence", result.stderr)

    def test_init_accepts_explicit_duration_compression_from_bound_intake(self):
        rhythm_path = self.job_dir / "剧情分析" / "source_rhythm.json"
        rhythm = json.loads(rhythm_path.read_text(encoding="utf-8"))
        rhythm["duration"] = 40.0
        self._write_json(rhythm_path, rhythm)
        intake_path = self.job_dir / "intake.json"
        self._write_json(
            intake_path,
            {
                "schema_version": 1,
                "job_id": self.job_id,
                "target_duration": {
                    "value": "30s",
                    "explicitly_requested": True,
                    "request_evidence": {
                        "source": "intake",
                        "quote": "--target-duration 30s",
                    },
                },
            },
        )

        self.run_pack("init")

        plan = json.loads(
            (self.job_dir / "seedance" / "director_plan.json").read_text(encoding="utf-8")
        )
        self.assertEqual(plan["replication_fidelity"]["duration_mode"], "user_compressed")
        self.assertEqual(
            plan["replication_fidelity"]["user_request_evidence"],
            {
                "source": "intake",
                "path": "output/job-001/intake.json",
                "sha256": hashlib.sha256(intake_path.read_bytes()).hexdigest(),
                "quote": "--target-duration 30s",
            },
        )

    def test_version_five_rejects_an_undeclared_script_rewrite(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["version"] = 5
        plan["script_fidelity"] = {"mode": "source_locked"}
        for part in plan["parts"]:
            for group in part["speech_groups"]:
                group["line_edits"] = []
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("undeclared script rewrite", result.stderr)

    def test_version_five_accepts_declared_product_replacement_and_renders_audit(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["version"] = 5
        plan["script_fidelity"] = {"mode": "source_locked"}
        for part in plan["parts"]:
            beats = {beat["id"]: beat for beat in part["beats"]}
            for group in part["speech_groups"]:
                source_line = "".join(beats[beat_id]["source_line"] for beat_id in group["beat_ids"])
                group["line"] = source_line
                group["line_edits"] = []
        anchor = plan["parts"][1]["speech_groups"][0]
        source_anchor = anchor["line"]
        anchor["line"] = "Test Toner."
        anchor["line_edits"] = [
            {
                "kind": "replace",
                "from": source_anchor,
                "to": "Test Toner.",
                "reason": "product_name",
                "reason_detail": "Replace the source product with the approved job product.",
            }
        ]
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertEqual(result.returncode, 0, result.stderr)
        audit = (self.job_dir / "voiceover" / "source_script_fidelity.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("source_locked", audit)
        self.assertIn("product_name", audit)
        self.assertIn("Source line 1Source line 2", audit)
        self.assertIn("Test Toner.", audit)

    def test_render_rejects_source_target_presenter_gender_mismatch(self):
        self.run_pack("init")
        plan_path = self._fill_plan()
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["presenter_gender"] = {"source": "male", "target": "female"}
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("source and target presenter gender must match", result.stderr)

    def test_render_rejects_opposite_presenter_language(self):
        manifest_path = self.job_dir / "visual-assets" / "approved_visual_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["source_presenter_gender"] = "male"
        manifest["target_presenter_gender"] = "male"
        self._write_json(manifest_path, manifest)
        self.run_pack("init")
        self._fill_plan()

        result = self.run_pack("render", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("opposite presenter gender terms", result.stderr)

    def test_render_rejects_director_plan_image_reference_outside_part_assets(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["parts"][0]["beats"][0]["reference_binding"] = "@图片7锁角色C。"
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("references @图片7 but only 4 image assets exist", result.stderr)

    def test_render_derives_web_and_api_outputs(self):
        self.run_pack("init")
        self._fill_plan()

        self.run_pack("render")

        expected = [
            self.job_dir / "voiceover" / "voiceover.md",
            self.job_dir / "voiceover" / "source_script_fidelity.md",
            self.job_dir / "voiceover" / "source_replication_fidelity.md",
            self.job_dir / "voiceover" / "shot_line_map.md",
            self.job_dir / "voiceover" / "replication_function_coverage.md",
            self.job_dir / "seam" / "seam_design.md",
            self.job_dir / "seedance" / "seedance_素材角色表.md",
            self.job_dir / "seedance" / "seedance_part1_prompt.txt",
            self.job_dir / "seedance" / "seedance_part2_prompt.txt",
            self.job_dir / "seedance" / "handoff_mode.json",
            self.job_dir / "seedance" / "requests" / "part1_request_prepared.json",
            self.job_dir / "seedance_web_final" / "UPLOAD_ORDER.md",
        ]
        for path in expected:
            self.assertTrue(path.exists(), path)

        replication_audit = (
            self.job_dir / "voiceover" / "source_replication_fidelity.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Change policy: `necessary_only`", replication_audit)
        self.assertIn("user_requested:Source action 1→Target action 1", replication_audit)

        seam = (self.job_dir / "seam" / "seam_design.md").read_text(encoding="utf-8")
        self.assertIn("Independent hard cut", seam)
        self.assertIn("self-contained Seedance task", seam)
        self.assertIn("does not inherit", seam)
        self.assertNotIn("Preserve identity, product, scene, lighting", seam)

        prompt = (self.job_dir / "seedance" / "seedance_part1_prompt.txt").read_text(encoding="utf-8")
        self.assertIn("0.0–5.0秒｜Shot 01–04", prompt)
        self.assertIn("5.0–10.0秒｜Shot 05–08", prompt)
        self.assertIn("10.0–15.0秒｜Shot 09–12", prompt)
        self.assertIn("画面：Target action 1；Target action 2。", prompt)
        self.assertIn('声音：旁白{First narration line.}', prompt)
        self.assertIn('声音：女主画面内同期口播{Short sync line.}', prompt)
        self.assertIn("音效：<Action sound 1>；<Action sound 2>", prompt)
        self.assertNotIn("画外音旁白", prompt)
        self.assertNotIn("声音执行", prompt)
        self.assertNotIn("Shot 1（", prompt)
        self.assertNotIn("主目标：", prompt)
        self.assertNotIn("次目标：", prompt)
        self.assertNotIn("简化：", prompt)
        self.assertNotIn("@图片1（分镜参考）", prompt)

        request = json.loads(
            (self.job_dir / "seedance" / "requests" / "part1_request_prepared.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(request["prepared_only"])
        self.assertTrue(request["do_not_submit"])
        self.assertEqual(request["method"], "POST")
        self.assertEqual(
            request["url"],
            "https://higress-api.wujieai.com/wj-open/v2/open-platform/task/task_create",
        )
        self.assertEqual(request["body"]["acquireResourceTimeoutSeconds"], 60)
        self.assertIsInstance(request["body"]["param"], str)
        self.assertEqual(json.loads(request["body"]["param"])["model"], "ep-test-ordinary")
        self.assertEqual(request["body"]["taskCode"], 2509)
        handoff = json.loads((self.job_dir / "seedance" / "handoff_mode.json").read_text(encoding="utf-8"))
        self.assertEqual(handoff["handoff_mode"], "both")
        compiler_manifest = json.loads(
            (self.job_dir / "seedance" / "part_compilation_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            [part["part_id"] for part in compiler_manifest["parts"]],
            ["part1", "part2"],
        )
        self.assertEqual(
            compiler_manifest["director_plan_sha256"],
            hashlib.sha256(
                (self.job_dir / "seedance" / "director_plan.json").read_bytes()
            ).hexdigest(),
        )
        self.assertTrue(
            all(part["files"] for part in compiler_manifest["parts"])
        )
        self.assertFalse((self.job_dir / ".pre_seedance_pack_staging").exists())

        upload_files = list((self.job_dir / "seedance_web_final" / "Part1_上传素材").iterdir())
        self.assertEqual(len(upload_files), 5)
        self.assertTrue(any(path.read_bytes() == b"part1" for path in upload_files if path.suffix == ".png"))

        prompt_qc = subprocess.run(
            [
                "python3",
                str(REPO_ROOT / "tools" / "seedance_prompt_contract_qc.py"),
                "--root",
                str(self.root),
                "--job-id",
                self.job_id,
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(prompt_qc.returncode, 0, prompt_qc.stderr + prompt_qc.stdout)

        request_qc = subprocess.run(
            [
                "python3",
                str(REPO_ROOT / "tools" / "request_body_qc.py"),
                "--requests",
                str(self.job_dir / "seedance" / "requests" / "part1_request_prepared.json"),
                str(self.job_dir / "seedance" / "requests" / "part2_request_prepared.json"),
                "--prompt-files",
                str(self.job_dir / "seedance" / "seedance_part1_prompt.txt"),
                str(self.job_dir / "seedance" / "seedance_part2_prompt.txt"),
                "--model-route-config",
                str(self.root / "rules" / "SEEDANCE_MODEL.json"),
                "--allow-asset-refs",
                "--out-json",
                str(self.job_dir / "checks" / "request_qc.json"),
                "--out-md",
                str(self.job_dir / "checks" / "request_qc.md"),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(request_qc.returncode, 0, request_qc.stderr + request_qc.stdout)

    def test_render_places_delivery_note_inside_the_matching_audio_visual_block(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["parts"][0]["speech_groups"][0]["delivery_note"] = (
            "完整产品名只在切到 Shot 02 产品正面特写时说"
        )
        self._write_json(plan_path, plan)

        self.run_pack("render")

        prompt = (self.job_dir / "seedance" / "seedance_part1_prompt.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            '声音：旁白（完整产品名只在切到 Shot 02 产品正面特写时说）'
            '{First narration line.}。',
            prompt,
        )

    def test_render_places_part_scene_rule_before_execution_blocks(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["parts"][1]["scene_rule"] = (
            "Shot 01在水池前；Shot 02–10和Shot 12在暖色房间；"
            "Shot 11只使用分镜板中的虚焦静物B-roll。"
        )
        self._write_json(plan_path, plan)

        self.run_pack("render")

        part1_prompt = (self.job_dir / "seedance" / "seedance_part1_prompt.txt").read_text(
            encoding="utf-8"
        )
        part2_prompt = (self.job_dir / "seedance" / "seedance_part2_prompt.txt").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("Shot 01在水池前", part1_prompt)
        self.assertIn("Shot 01在水池前", part2_prompt)
        self.assertLess(part2_prompt.index("Shot 01在水池前"), part2_prompt.index("0.0–5.0秒"))

    def test_default_reference_preamble_uses_definition_lock_and_exclusion_format(self):
        self.run_pack("init")
        self._fill_plan(mode="api")

        self.run_pack("render")

        prompt = (self.job_dir / "seedance" / "seedance_part1_prompt.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("@图片1定义为“分镜板”，只控制", prompt)
        self.assertIn("@图片2中的产品定义为“目标产品”，只锁定", prompt)
        self.assertIn("@图片4中的人物定义为“主角”，只锁定", prompt)
        self.assertIn("不传递", prompt)
        self.assertNotIn("控制校准", prompt)

    def test_render_omits_sound_effect_line_when_block_has_no_real_effect(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        for beat in plan["parts"][0]["beats"]:
            beat["sound_effect"] = "无额外音效"
        self._write_json(plan_path, plan)

        self.run_pack("render")

        prompt = (self.job_dir / "seedance" / "seedance_part1_prompt.txt").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("音效：无", prompt)
        self.assertNotIn("音效：", prompt)

    def test_render_omits_legacy_afterwash_reference_from_every_part(self):
        afterwash = self.root / "output/shared/identity/afterwash.png"
        afterwash.write_bytes(b"afterwash")
        manifest_path = self.job_dir / "visual-assets" / "approved_visual_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["reusable_refs"]["afterwash_face"] = "output/shared/identity/afterwash.png"
        self._write_json(manifest_path, manifest)

        self.run_pack("init")
        self._fill_plan(mode="api")
        self.run_pack("render")

        prompt = (self.job_dir / "seedance" / "seedance_part1_prompt.txt").read_text(
            encoding="utf-8"
        )
        request = json.loads(
            (self.job_dir / "seedance" / "requests" / "part1_request_prepared.json").read_text(
                encoding="utf-8"
            )
        )
        param = json.loads(request["body"]["param"])
        image_items = [item for item in param["content"] if item["type"] == "image_url"]

        self.assertNotIn("@图片5", prompt)
        self.assertEqual(len(image_items), 4)
        self.assertNotIn("AFTERWASH", json.dumps(request, ensure_ascii=False))

    def test_render_uses_only_each_parts_storyboard_derived_identity_refs(self):
        manifest_path = self.job_dir / "visual-assets" / "approved_visual_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["person_asset_mode"] = "storyboard_derived"
        manifest["reusable_refs"].pop("identity_ref")
        manifest["part_reusable_refs"] = {
            "part1": {
                "identity_role_A": "output/job-001/visual-assets/derived-identities/role_A.png",
                "identity_role_D": "output/job-001/visual-assets/derived-identities/role_D.png",
                "identity_role_C": "output/job-001/visual-assets/derived-identities/role_C.png",
            },
            "part2": {
                "identity_role_F": "output/job-001/visual-assets/derived-identities/role_F.png",
                "identity_role_H": "output/job-001/visual-assets/derived-identities/role_H.png",
                "identity_role_I": "output/job-001/visual-assets/derived-identities/role_I.png",
            },
        }
        self._write_json(manifest_path, manifest)
        for role in ("A", "D", "C", "F", "H", "I"):
            path = self.job_dir / "visual-assets" / "derived-identities" / f"role_{role}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"role-{role}".encode("utf-8"))

        self.run_pack("init", "--handoff-mode", "web")
        plan_path = self._fill_plan(mode="web")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        for role in ("A", "D", "C", "F", "H", "I"):
            plan["asset_roles"][f"identity_role_{role}"] = {
                "role": f"中的女性定义为角色{role}，只锁定脸、发型、身体和服装",
                "exclusions": "不传递参考图背景或其他人物",
            }
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertEqual(result.returncode, 0, result.stderr)
        part1 = self.job_dir / "seedance_web_final" / "Part1_上传素材"
        part2 = self.job_dir / "seedance_web_final" / "Part2_上传素材"
        self.assertEqual(next(part1.glob("04_*.png")).read_bytes(), b"role-A")
        self.assertEqual(next(part1.glob("05_*.png")).read_bytes(), b"role-D")
        self.assertEqual(next(part1.glob("07_*.png")).read_bytes(), b"role-C")
        self.assertEqual(next(part2.glob("04_*.png")).read_bytes(), b"role-F")
        self.assertEqual(next(part2.glob("05_*.png")).read_bytes(), b"role-H")
        self.assertEqual(next(part2.glob("07_*.png")).read_bytes(), b"role-I")
        part1_prompt = (self.job_dir / "seedance" / "seedance_part1_prompt.txt").read_text(
            encoding="utf-8"
        )
        part2_prompt = (self.job_dir / "seedance" / "seedance_part2_prompt.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("@图片4中的女性定义为角色A", part1_prompt)
        self.assertIn("@图片5中的女性定义为角色D", part1_prompt)
        self.assertNotIn("角色F", part1_prompt)
        self.assertIn("@图片4中的女性定义为角色F", part2_prompt)
        self.assertIn("@图片5中的女性定义为角色H", part2_prompt)
        self.assertIn("@图片6中的女性定义为角色I", part2_prompt)
        self.assertNotIn("角色A", part2_prompt)

    def test_render_keeps_prompt_image_refs_within_submitted_image_count(self):
        manifest_path = self.job_dir / "visual-assets" / "approved_visual_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["person_asset_mode"] = "storyboard_derived"
        manifest["reusable_refs"].pop("identity_ref")
        manifest["part_reusable_refs"] = {}
        for part_id in ("part1", "part2"):
            manifest["part_reusable_refs"][part_id] = {
                f"identity_role_{role}": (
                    f"output/job-001/visual-assets/derived-identities/{part_id}_{role}.png"
                )
                for role in ("A", "B", "C")
            }
            for role in ("A", "B", "C"):
                path = (
                    self.job_dir
                    / "visual-assets"
                    / "derived-identities"
                    / f"{part_id}_{role}.png"
                )
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(f"{part_id}-{role}".encode("utf-8"))
        self._write_json(manifest_path, manifest)

        self.run_pack("init", "--handoff-mode", "api")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        for role in ("A", "B", "C"):
            plan["asset_roles"][f"identity_role_{role}"] = {
                "role": f"中的女性定义为角色{role}，只锁定脸、发型、身体和服装",
                "exclusions": "不传递参考图背景或其他人物",
            }
        self._write_json(plan_path, plan)

        self.run_pack("render")

        prompt = (self.job_dir / "seedance" / "seedance_part1_prompt.txt").read_text(
            encoding="utf-8"
        )
        request = json.loads(
            (self.job_dir / "seedance" / "requests" / "part1_request_prepared.json").read_text(
                encoding="utf-8"
            )
        )
        param = json.loads(request["body"]["param"])
        image_count = sum(item["type"] == "image_url" for item in param["content"])
        prompt_refs = {int(value) for value in re.findall(r"@图片(\d+)", prompt)}

        self.assertEqual(image_count, 6)
        self.assertEqual(prompt_refs, set(range(1, 7)))
        self.assertNotIn("@图片7", prompt)

    def test_render_supports_source_aligned_thirteen_second_parts(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        scale = 13.0 / 15.0
        for part in plan["parts"]:
            part["duration_seconds"] = 13
            for beat in part["beats"]:
                beat["target_start"] = round(beat["target_start"] * scale, 6)
                beat["target_end"] = round(beat["target_end"] * scale, 6)
            for group in part["speech_groups"]:
                group["target_start"] = round(group["target_start"] * scale, 6)
                group["target_end"] = round(group["target_end"] * scale, 6)
            part["speech_groups"][-1]["target_end"] = 12.4
        self._write_json(plan_path, plan)

        self.run_pack("render")

        prompt = (self.job_dir / "seedance" / "seedance_part1_prompt.txt").read_text(
            encoding="utf-8"
        )
        request = json.loads(
            (self.job_dir / "seedance" / "requests" / "part1_request_prepared.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertIn("生成约13秒", prompt)
        self.assertIn("8.7–13.0秒｜Shot 09–12", prompt)
        self.assertEqual(json.loads(request["body"]["param"])["duration"], 13)

    def test_render_rounds_fractional_provider_duration_up_without_compressing_prompt(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        scale = 10.8 / 15.0
        for part in plan["parts"]:
            part["duration_seconds"] = 10.8
            for beat in part["beats"]:
                beat["target_start"] = round(beat["target_start"] * scale, 6)
                beat["target_end"] = round(beat["target_end"] * scale, 6)
            for group in part["speech_groups"]:
                group["target_start"] = round(group["target_start"] * scale, 6)
                group["target_end"] = round(group["target_end"] * scale, 6)
            part["speech_groups"][-1]["target_end"] = 10.2
        self._write_json(plan_path, plan)

        self.run_pack("render")

        prompt = (self.job_dir / "seedance" / "seedance_part1_prompt.txt").read_text(
            encoding="utf-8"
        )
        request = json.loads(
            (self.job_dir / "seedance" / "requests" / "part1_request_prepared.json").read_text(
                encoding="utf-8"
            )
        )
        param = json.loads(request["body"]["param"])

        self.assertIn("生成约10.8秒", prompt)
        self.assertEqual(param["duration"], 11)

    def test_render_allows_four_source_aligned_beats(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        part = plan["parts"][0]
        selected = [part["beats"][0], part["beats"][2], part["beats"][4], part["beats"][5]]
        boundaries = [0.0, 3.75, 7.5, 11.25, 15.0]
        panels = [(1, 3), (4, 6), (7, 9), (10, 12)]
        shots = [1, 2, 3, 3]
        for index, beat in enumerate(selected):
            beat["target_start"] = boundaries[index]
            beat["target_end"] = boundaries[index + 1]
            beat["source_start"] = boundaries[index]
            beat["source_end"] = boundaries[index + 1]
            beat["panel_start"], beat["panel_end"] = panels[index]
            beat["shot"] = shots[index]
        part["beats"] = selected
        part["speech_groups"] = [
            {
                "id": "speech1",
                "target_start": 0.0,
                "target_end": 3.5,
                "speaker_mode": "女主画外音旁白",
                "line": selected[0]["source_line"],
                "beat_ids": [selected[0]["id"]],
                "line_edits": [],
            },
            {
                "id": "speech2",
                "target_start": 3.75,
                "target_end": 7.25,
                "speaker_mode": "女主画面内同期口播",
                "line": selected[1]["source_line"],
                "beat_ids": [selected[1]["id"]],
                "line_edits": [],
            },
            {
                "id": "speech3",
                "target_start": 7.5,
                "target_end": 11.0,
                "speaker_mode": "女主画外音旁白",
                "line": selected[2]["source_line"],
                "beat_ids": [selected[2]["id"]],
                "line_edits": [],
            },
            {
                "id": "speech4",
                "target_start": 11.25,
                "target_end": 14.5,
                "speaker_mode": "女主画外音旁白",
                "line": selected[3]["source_line"],
                "beat_ids": [selected[3]["id"]],
                "line_edits": [],
            },
        ]
        part["execution_blocks"] = [
            {"id": "block1", "beat_ids": [selected[0]["id"]]},
            {"id": "block2", "beat_ids": [selected[1]["id"]]},
            {"id": "block3", "beat_ids": [selected[2]["id"]]},
            {"id": "block4", "beat_ids": [selected[3]["id"]]},
        ]
        part["source_functions"] = [
            {
                "id": f"function{index}",
                "label": f"Source function {index}",
                "priority": "must_keep",
                "coverage": "both",
                "target_refs": [beat["id"], f"speech{index}"],
            }
            for index, beat in enumerate(selected, start=1)
        ]
        self._write_json(plan_path, plan)

        self.run_pack("render")

        prompt = (self.job_dir / "seedance" / "seedance_part1_prompt.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("Shot 01–03", prompt)
        self.assertIn("Shot 10–12", prompt)

    def test_validation_rejects_incomplete_plans(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        good = json.loads(plan_path.read_text(encoding="utf-8"))

        cases = {}
        too_few = json.loads(json.dumps(good))
        too_few["parts"][0]["beats"] = too_few["parts"][0]["beats"][:2]
        cases["at least 3 beats"] = too_few

        missing_shot = json.loads(json.dumps(good))
        for beat in missing_shot["parts"][0]["beats"]:
            if beat["shot"] == 3:
                beat["shot"] = 2
        cases["shots 1, 2, and 3"] = missing_shot

        time_gap = json.loads(json.dumps(good))
        time_gap["parts"][0]["beats"][1]["target_start"] = 3.0
        cases["continuous"] = time_gap

        speaker_mismatch = json.loads(json.dumps(good))
        speaker_mismatch["parts"][0]["speech_groups"][0]["speaker_mode"] = "女主画面内同期口播"
        cases["speaker mode"] = speaker_mismatch

        dropped_must_keep = json.loads(json.dumps(good))
        dropped_must_keep["parts"][0]["source_functions"][0]["coverage"] = "dropped"
        dropped_must_keep["parts"][0]["source_functions"][0]["target_refs"] = []
        cases["must_keep source function"] = dropped_must_keep

        missing_sound_effect = json.loads(json.dumps(good))
        missing_sound_effect["parts"][0]["beats"][0]["sound_effect"] = ""
        cases["sound_effect is required"] = missing_sound_effect

        for message, plan in cases.items():
            with self.subTest(message=message):
                self._write_json(plan_path, plan)
                result = self.run_pack("render", check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)

    def test_render_uses_source_rate_evidence_for_high_density_voiceover(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        source_line_sizes = [16, 16, 16, 16, 15, 15]
        part = plan["parts"][0]
        for beat, size in zip(part["beats"], source_line_sizes):
            beat["source_speaker_mode"] = "女主画外音旁白"
            beat["source_line"] = "源" * size
        part["speech_groups"] = [
            {
                "id": "speech1",
                "target_start": 0.0,
                "target_end": 5.0,
                "speaker_mode": "女主画外音旁白",
                "line": "一" * 30,
                "beat_ids": ["beat1", "beat2"],
            },
            {
                "id": "speech2",
                "target_start": 5.0,
                "target_end": 10.0,
                "speaker_mode": "女主画外音旁白",
                "line": "二" * 30,
                "beat_ids": ["beat3", "beat4"],
            },
            {
                "id": "speech3",
                "target_start": 10.0,
                "target_end": 14.5,
                "speaker_mode": "女主画外音旁白",
                "line": "三" * 27,
                "beat_ids": ["beat5", "beat6"],
            },
        ]
        self._declare_line_edits(plan)
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertEqual(result.returncode, 0, result.stderr)
        prompt_qc = subprocess.run(
            [
                "python3",
                str(REPO_ROOT / "tools" / "seedance_prompt_contract_qc.py"),
                "--root",
                str(self.root),
                "--job-id",
                self.job_id,
                "--prompt-files",
                str(self.job_dir / "seedance" / "seedance_part1_prompt.txt"),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(prompt_qc.returncode, 0, prompt_qc.stderr + prompt_qc.stdout)
        report = json.loads(
            (self.job_dir / "checks" / "pre_seedance_pack_seedance_prompt_contract_qc.json").read_text(
                encoding="utf-8"
            )
        )
        budget_check = next(
            check
            for check in report["prompts"][0]["checks"]
            if check["name"] == "part1_speech_budget"
        )
        self.assertIn("source_matched_high_density", budget_check["detail"])

    def test_render_preserves_four_source_speaker_runs(self):
        self.run_pack("init")
        plan_path = self._fill_plan(mode="api")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        part = plan["parts"][0]
        source_modes = [
            "女主画面内同期口播",
            "女主画外音旁白",
            "女主画外音旁白",
            "女主画面内同期口播",
            "女主画外音旁白",
            "女主画外音旁白",
        ]
        for beat, source_mode in zip(part["beats"], source_modes):
            beat["source_speaker_mode"] = source_mode
        part["speech_groups"] = [
            {
                "id": "speech1",
                "target_start": 0.0,
                "target_end": 2.5,
                "speaker_mode": "女主画面内同期口播",
                "line": "开场短句。",
                "beat_ids": ["beat1"],
            },
            {
                "id": "speech2",
                "target_start": 2.5,
                "target_end": 7.5,
                "speaker_mode": "女主画外音旁白",
                "line": "中段旁白。",
                "beat_ids": ["beat2", "beat3"],
            },
            {
                "id": "speech3",
                "target_start": 7.5,
                "target_end": 10.0,
                "speaker_mode": "女主画面内同期口播",
                "line": "产品感谢。",
                "beat_ids": ["beat4"],
            },
            {
                "id": "speech4",
                "target_start": 10.0,
                "target_end": 14.5,
                "speaker_mode": "女主画外音旁白",
                "line": "福利收口。",
                "beat_ids": ["beat5", "beat6"],
            },
        ]
        part["execution_blocks"] = [
            {"id": "block1", "beat_ids": ["beat1"]},
            {"id": "block2", "beat_ids": ["beat2", "beat3"]},
            {"id": "block3", "beat_ids": ["beat4"]},
            {"id": "block4", "beat_ids": ["beat5", "beat6"]},
        ]
        self._declare_line_edits(plan)
        self._write_json(plan_path, plan)

        result = self.run_pack("render", check=False)

        self.assertEqual(result.returncode, 0, result.stderr)
        prompt_qc = subprocess.run(
            [
                "python3",
                str(REPO_ROOT / "tools" / "seedance_prompt_contract_qc.py"),
                "--root",
                str(self.root),
                "--job-id",
                self.job_id,
                "--prompt-files",
                str(self.job_dir / "seedance" / "seedance_part1_prompt.txt"),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(prompt_qc.returncode, 0, prompt_qc.stderr + prompt_qc.stdout)

    def test_handoff_modes_select_only_requested_outputs(self):
        self.run_pack("init")
        self._fill_plan(mode="api")

        self.run_pack("render")
        self.assertTrue((self.job_dir / "seedance" / "requests").exists())
        self.assertFalse((self.job_dir / "seedance_web_final").exists())

        self.run_pack("render", "--handoff-mode", "web", "--replace")
        self.assertFalse((self.job_dir / "seedance" / "requests").exists())
        self.assertTrue((self.job_dir / "seedance_web_final" / "UPLOAD_ORDER.md").exists())

    def test_existing_final_requires_replace_and_is_archived(self):
        self.run_pack("init")
        self._fill_plan(mode="web")
        final_dir = self.job_dir / "seedance_web_final"
        final_dir.mkdir()
        (final_dir / "old.txt").write_text("old\n", encoding="utf-8")

        refused = self.run_pack("render", check=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("--replace", refused.stderr)

        self.run_pack("render", "--replace")

        archived = list((self.job_dir / "deprecated").glob("*/seedance_web_final/old.txt"))
        self.assertEqual(len(archived), 1)
        self.assertTrue((final_dir / "UPLOAD_ORDER.md").exists())

    def test_audio_cutter_caps_duration_and_accepts_injected_runner(self):
        from pre_seedance_pack import cut_audio_segment

        calls = []

        def fake_runner(command, **kwargs):
            calls.append((command, kwargs))

        output = self.root / "audio.mp3"
        cut_audio_segment(self.root / "source.mp4", output, 2.0, 30.0, runner=fake_runner)

        command, kwargs = calls[0]
        self.assertEqual(command[command.index("-t") + 1], "14.900")
        self.assertTrue(kwargs["check"])

    def test_web_handoff_reserves_06_for_audio_with_six_images(self):
        from pre_seedance_pack import write_web_part

        sources = []
        for index in range(1, 7):
            path = self.root / f"asset-{index}.png"
            path.write_bytes(f"asset-{index}".encode("utf-8"))
            sources.append(path)
        audio = self.root / "audio.mp3"
        audio.write_bytes(b"audio")
        specs = [
            ("storyboard", sources[0]),
            ("product_front", sources[1]),
            ("product_open", sources[2]),
            ("identity_role_A", sources[3]),
            ("identity_role_B", sources[4]),
            ("identity_role_C", sources[5]),
        ]

        uploads = write_web_part(
            self.job_dir / "seedance_web_final",
            {"id": "part1"},
            specs,
            "Prompt",
            audio,
        )

        names = {Path(path).name for path in uploads}
        self.assertIn("06_Part1_声音参考.mp3", names)
        self.assertTrue(any(name.startswith("07_Part1_人物身份_role_C") for name in names))
        self.assertFalse(any(name.startswith("06_Part1_人物身份_") for name in names))

    def test_audio_panel_labels_cannot_replace_missing_visual_coverage(self):
        self.run_pack("init")
        self._fill_plan(mode="api")
        self.run_pack("render")

        prompt_path = self.job_dir / "seedance" / "seedance_part1_prompt.txt"
        prompt = prompt_path.read_text(encoding="utf-8")
        prompt = prompt.replace(
            "10.0–15.0秒｜Shot 09–12",
            "10.0–15.0秒｜Shot 09–10",
        )
        prompt = prompt.replace(
            '声音：女主画外音旁白：“Final narration line.”',
            '声音：Shot 11–12 女主画外音旁白：“Final narration line.”',
        )
        prompt_path.write_text(prompt, encoding="utf-8")

        out_json = self.job_dir / "checks" / "panel_coverage_qc.json"
        result = subprocess.run(
            [
                "python3",
                str(REPO_ROOT / "tools" / "seedance_prompt_contract_qc.py"),
                "--root",
                str(self.root),
                "--job-id",
                self.job_id,
                "--prompt-files",
                str(prompt_path),
                "--out-json",
                str(out_json),
                "--out-md",
                str(self.job_dir / "checks" / "panel_coverage_qc.md"),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(out_json.read_text(encoding="utf-8"))
        failed = {
            check["name"]
            for check in report["prompts"][0]["checks"]
            if check["status"] != "PASS"
        }
        self.assertIn("part1_covers_shot_line_map_panels", failed)


if __name__ == "__main__":
    unittest.main()
