import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "source_rhythm_visual_review_qc.py"


class SourceRhythmVisualReviewQcTest(unittest.TestCase):
    def write_source_rhythm(self, root):
        frames = []
        for index in range(1, 4):
            path = root / f"frame_{index:04d}.jpg"
            path.write_bytes(b"evidence")
            frames.append(str(path))
        rhythm_path = root / "source_rhythm.json"
        rhythm_path.write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "beats": [
                        {
                            "id": "sr001",
                            "replication_priority": "must_keep",
                            "confirmed_source_line": "黑头闭口，涂！",
                            "evidence_frame_refs": frames,
                            "action_evidence": {
                                "kind": "physical_change",
                                "before_frame_ref": frames[0],
                                "peak_frame_ref": frames[1],
                                "after_frame_ref": frames[2],
                                "motion": "泥膜棒接触脸部并滑动",
                                "state_before": "皮肤未覆盖泥膜",
                                "state_after": "皮肤已覆盖泥膜",
                                "visible_result": "泥膜留在脸上",
                            },
                        },
                        {
                            "id": "sr002",
                            "replication_priority": "mergeable",
                            "confirmed_source_line": "这支泥膜棒",
                            "spoken_product_names": ["泥膜棒"],
                            "evidence_frame_refs": [frames[2]],
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return rhythm_path, frames

    def run_qc(self, root, rhythm_path, review):
        review_path = root / "review.json"
        out_json = root / "qc.json"
        review_path.write_text(
            json.dumps(review, ensure_ascii=False),
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--root",
                str(root),
                "--source-rhythm",
                str(rhythm_path),
                "--review",
                str(review_path),
                "--out-json",
                str(out_json),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        report = json.loads(out_json.read_text(encoding="utf-8")) if out_json.exists() else {}
        return result, report

    def test_summary_only_review_cannot_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rhythm_path, _ = self.write_source_rhythm(root)

            result, report = self.run_qc(
                root,
                rhythm_path,
                {"reviewer": "checker", "summary": "节奏看起来没问题"},
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(report["overall"], "STOP")
            self.assertEqual(report["missing_beat_ids"], ["sr001", "sr002"])

    def test_each_required_beat_must_cite_and_match_real_evidence_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rhythm_path, frames = self.write_source_rhythm(root)

            result, report = self.run_qc(
                root,
                rhythm_path,
                {
                    "reviewer": "checker",
                    "beats": [
                        {
                            "beat_id": "sr001",
                            "reviewed_frame_refs": frames,
                            "description_matches_evidence": True,
                            "action_type_matches_evidence": True,
                            "physical_action_matches": True,
                            "notes": "看到涂抹前、接触滑动、涂抹后留膜",
                        },
                        {
                            "beat_id": "sr002",
                            "reviewed_frame_refs": [frames[2]],
                            "description_matches_evidence": True,
                            "action_type_matches_evidence": True,
                            "confirmed_spoken_product_names": ["泥膜棒"],
                            "spoken_product_names_are_product_entities": True,
                            "notes": "看到产品展示",
                        },
                    ],
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(report["overall"], "PASS")
            self.assertEqual(report["reviewed_beat_ids"], ["sr001", "sr002"])

    def test_checker_must_confirm_action_type_against_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rhythm_path, frames = self.write_source_rhythm(root)

            result, report = self.run_qc(
                root,
                rhythm_path,
                {
                    "reviewer": "checker",
                    "beats": [
                        {
                            "beat_id": "sr001",
                            "reviewed_frame_refs": frames,
                            "description_matches_evidence": True,
                            "physical_action_matches": True,
                            "notes": "已看三帧",
                        },
                        {
                            "beat_id": "sr002",
                            "reviewed_frame_refs": [frames[2]],
                            "description_matches_evidence": True,
                            "action_type_matches_evidence": True,
                            "confirmed_spoken_product_names": ["泥膜棒"],
                            "spoken_product_names_are_product_entities": True,
                            "notes": "已看产品展示",
                        },
                    ],
                },
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(report["overall"], "FAIL")
            sr001 = next(item for item in report["checks"] if item["beat_id"] == "sr001")
            self.assertIn("action_type_does_not_match_evidence", sr001["fail_reasons"])

    def test_declared_product_name_requires_semantic_entity_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rhythm_path, frames = self.write_source_rhythm(root)

            result, report = self.run_qc(
                root,
                rhythm_path,
                {
                    "reviewer": "checker",
                    "beats": [
                        {
                            "beat_id": "sr001",
                            "reviewed_frame_refs": frames,
                            "description_matches_evidence": True,
                            "action_type_matches_evidence": True,
                            "physical_action_matches": True,
                            "notes": "已看三帧",
                        },
                        {
                            "beat_id": "sr002",
                            "reviewed_frame_refs": [frames[2]],
                            "description_matches_evidence": True,
                            "action_type_matches_evidence": True,
                            "confirmed_spoken_product_names": ["泥膜棒"],
                            "spoken_product_names_are_product_entities": False,
                            "notes": "像普通工具词，不能确认是产品实体",
                        },
                    ],
                },
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(report["overall"], "FAIL")
            sr002 = next(item for item in report["checks"] if item["beat_id"] == "sr002")
            self.assertIn(
                "spoken_product_names_not_confirmed_as_product_entities",
                sr002["fail_reasons"],
            )

    def test_schema_two_review_cannot_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rhythm_path, frames = self.write_source_rhythm(root)
            rhythm = json.loads(rhythm_path.read_text(encoding="utf-8"))
            rhythm["schema_version"] = 2
            rhythm_path.write_text(json.dumps(rhythm), encoding="utf-8")

            result, report = self.run_qc(
                root,
                rhythm_path,
                {
                    "reviewer": "checker",
                    "beats": [
                        {
                            "beat_id": "sr001",
                            "reviewed_frame_refs": frames,
                            "description_matches_evidence": True,
                            "action_type_matches_evidence": True,
                            "physical_action_matches": True,
                            "notes": "已看三帧",
                        },
                        {
                            "beat_id": "sr002",
                            "reviewed_frame_refs": [frames[2]],
                            "description_matches_evidence": True,
                            "action_type_matches_evidence": True,
                            "confirmed_spoken_product_names": ["泥膜棒"],
                            "spoken_product_names_are_product_entities": True,
                            "notes": "已看产品展示",
                        },
                    ],
                },
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(report["overall"], "STOP")

    def test_removable_beat_still_requires_visual_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rhythm_path, frames = self.write_source_rhythm(root)
            rhythm = json.loads(rhythm_path.read_text(encoding="utf-8"))
            rhythm["beats"].append(
                {
                    "id": "sr003",
                    "replication_priority": "removable",
                    "confirmed_source_line": "Old Product",
                    "spoken_product_names": ["Old Product"],
                    "evidence_frame_refs": [frames[0]],
                }
            )
            rhythm_path.write_text(json.dumps(rhythm), encoding="utf-8")

            result, report = self.run_qc(
                root,
                rhythm_path,
                {
                    "reviewer": "checker",
                    "beats": [
                        {
                            "beat_id": "sr001",
                            "reviewed_frame_refs": frames,
                            "description_matches_evidence": True,
                            "action_type_matches_evidence": True,
                            "physical_action_matches": True,
                            "notes": "已看三帧",
                        },
                        {
                            "beat_id": "sr002",
                            "reviewed_frame_refs": [frames[2]],
                            "description_matches_evidence": True,
                            "action_type_matches_evidence": True,
                            "confirmed_spoken_product_names": ["泥膜棒"],
                            "spoken_product_names_are_product_entities": True,
                            "notes": "已看产品展示",
                        },
                    ],
                },
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(report["overall"], "STOP")
            self.assertIn("sr003", report["missing_beat_ids"])


if __name__ == "__main__":
    unittest.main()
