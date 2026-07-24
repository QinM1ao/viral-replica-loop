import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from hash_gated_visual_qc import ensure_reuse_summary, record_snapshot  # noqa: E402
from restore_storyboard_shot_labels import restore  # noqa: E402


class HashGatedVisualQcTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.job_id = "job-001"
        self.job_dir = self.root / "output" / self.job_id
        (self.job_dir / "final-images").mkdir(parents=True)
        (self.job_dir / "visual-assets").mkdir(parents=True)
        (self.job_dir / "checks").mkdir(parents=True)
        (self.job_dir / "seedance").mkdir(parents=True)
        (self.job_dir / "seedance_web_final" / "prompts").mkdir(parents=True)
        self.part1_path = self.job_dir / "final-images" / "part1_seedance_ref.png"
        self.part1_evidence = self.job_dir / "checks" / "part1_shot_label_restore.json"
        self.restore_part1(bar_color=(38, 38, 38))
        (self.job_dir / "final-images" / "part2_seedance_ref.png").write_bytes(b"part2")
        (self.job_dir / "seedance" / "seedance_素材角色表.md").write_text("roles v1\n", encoding="utf-8")
        (self.job_dir / "seedance_web_final" / "prompts" / "part1.txt").write_text(
            "prompt roles v1\n",
            encoding="utf-8",
        )
        self.write_manifest(product_group_id="product-a")
        self.write_pass_qc("image_batch_qc_storyboard_geometry_qc.json")
        self.write_pass_qc("image_batch_qc_cross_part_continuity_qc.json")
        self.write_pass_qc("image_batch_qc_skincare_progression_qc.json")

    def tearDown(self):
        self.tmp.cleanup()

    def write_json(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def write_manifest(self, product_group_id):
        self.write_json(
            self.job_dir / "visual-assets" / "approved_visual_manifest.json",
            {
                "job_id": self.job_id,
                "product_group_id": product_group_id,
                "product_group_manifest": "output/shared/product/manifest.json",
                "identity_group_id": "identity-a",
                "identity_group_manifest": "output/shared/identity/manifest.json",
                "reusable_refs": {
                    "product_front": "output/shared/product/front.png",
                    "product_open": "output/shared/product/open.png",
                    "identity_ref": "output/shared/identity/ref.png",
                    "afterwash_face": "output/shared/identity/after.png",
                },
                "part_storyboards": {
                    "part1": {
                        "path": f"output/{self.job_id}/final-images/part1_seedance_ref.png",
                        "asset_type": "AI改好分镜图",
                        "image_route": "matpool_gpt_image_2_edit",
                        "contains_source_video_pixels": False,
                        "source_reference": f"output/{self.job_id}/storyboard_source_refs/source_storyboard_part1.jpg",
                        "shot_label_metadata": {
                            "type": "shot_label_metadata_only",
                            "evidence": f"output/{self.job_id}/checks/part1_shot_label_restore.json",
                            "panel_pixels_modified": False,
                        },
                    },
                    "part2": {
                        "path": f"output/{self.job_id}/final-images/part2_seedance_ref.png",
                        "asset_type": "AI改好分镜图",
                        "image_route": "matpool_gpt_image_2_edit",
                        "contains_source_video_pixels": False,
                        "source_reference": f"output/{self.job_id}/storyboard_source_refs/source_storyboard_part2.jpg",
                    },
                },
            },
        )

    def restore_part1(self, bar_color):
        candidate = self.job_dir / "final-images" / "part1_candidate.png"
        image = Image.new("RGB", (400, 600), (90, 70, 50))
        draw = ImageDraw.Draw(image)
        for top, bottom in ((210, 225), (405, 420), (585, 600)):
            draw.rectangle((0, top, 399, bottom - 1), fill=bar_color)
            draw.text((8, top + 2), "Shot XX", fill=(0, 190, 255))
        image.save(candidate)
        restore(candidate, self.part1_path, self.part1_evidence, cols=4, rows=3)

    def write_pass_qc(self, name):
        self.write_json(self.job_dir / "checks" / name, {"overall": "PASS"})

    def test_reuses_heavy_qc_when_hashes_and_mappings_are_unchanged(self):
        record_snapshot(self.root, self.job_id, write=True)

        summary = ensure_reuse_summary(
            self.root,
            self.job_id,
            "request_qc",
            visual_qc_path=self.job_dir / "checks" / "request_qc_visual_asset_manifest_qc.json",
            checker_qc_path=self.job_dir / "checks" / "request_qc_gate_review_qc.json",
            write=True,
        )

        self.assertEqual(summary["overall"], "PASS")
        self.assertIn("storyboard_geometry", summary["reused_reports"])
        self.assertIn("cross_part_continuity", summary["reused_reports"])
        self.assertEqual(
            [check["name"] for check in summary["lightweight_checks"]],
            ["visual_asset_manifest_qc", "checker_review_qc"],
        )
        self.assertTrue((self.job_dir / "checks" / "request_qc_visual_qc_reuse_summary.json").exists())

    def test_invalidates_when_active_image_hash_changes(self):
        record_snapshot(self.root, self.job_id, write=True)
        (self.job_dir / "final-images" / "part1_seedance_ref.png").write_bytes(b"changed")

        summary = ensure_reuse_summary(self.root, self.job_id, "request_qc", write=False)

        self.assertEqual(summary["overall"], "STOP")
        self.assertIn("active_final_image_hashes_changed", summary["invalidations"])

    def test_reuses_content_qc_when_only_shot_label_metadata_changes(self):
        record_snapshot(self.root, self.job_id, write=True)
        original_hash = (
            json.loads(self.part1_evidence.read_text(encoding="utf-8"))["output_sha256"]
        )

        self.restore_part1(bar_color=(42, 42, 42))
        changed_hash = (
            json.loads(self.part1_evidence.read_text(encoding="utf-8"))["output_sha256"]
        )
        self.assertNotEqual(original_hash, changed_hash)

        summary = ensure_reuse_summary(self.root, self.job_id, "request_qc", write=False)

        self.assertEqual(summary["overall"], "PASS")
        self.assertEqual(summary["invalidations"], [])
        self.assertEqual(summary["metadata_only_changes"], ["part1"])
        self.assertIn("storyboard_geometry", summary["reused_reports"])

    def test_invalidates_when_manifest_mapping_changes(self):
        record_snapshot(self.root, self.job_id, write=True)
        self.write_manifest(product_group_id="product-b")

        summary = ensure_reuse_summary(self.root, self.job_id, "request_qc", write=False)

        self.assertEqual(summary["overall"], "STOP")
        self.assertIn("approved_visual_manifest_mapping_changed", summary["invalidations"])

    def test_invalidates_when_material_role_mapping_changes_after_baseline(self):
        record_snapshot(self.root, self.job_id, write=True)
        ensure_reuse_summary(self.root, self.job_id, "seedance_prompt", write=True)
        (self.job_dir / "seedance" / "seedance_素材角色表.md").write_text("roles v2\n", encoding="utf-8")

        summary = ensure_reuse_summary(self.root, self.job_id, "request_qc", write=False)

        self.assertEqual(summary["overall"], "STOP")
        self.assertIn("material_role_mapping_changed", summary["invalidations"])

    def test_invalidates_when_user_visible_defect_is_recorded(self):
        record_snapshot(self.root, self.job_id, write=True)
        self.write_json(
            self.job_dir / "checks" / "user_visible_defects.json",
            {"defects": [{"status": "open", "note": "visible product drift"}]},
        )

        summary = ensure_reuse_summary(self.root, self.job_id, "request_qc", write=False)

        self.assertEqual(summary["overall"], "STOP")
        self.assertIn("user_visible_defect_recorded", summary["invalidations"])


if __name__ == "__main__":
    unittest.main()
