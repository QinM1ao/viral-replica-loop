import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from visual_asset_manifest_qc import validate_shot_label_metadata


class VisualAssetManifestShotLabelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.final_image = self.root / "output/job-001/final-images/part1.png"
        self.evidence = self.root / "output/job-001/checks/part1_shot_label_restore.json"
        self.final_image.parent.mkdir(parents=True, exist_ok=True)
        self.evidence.parent.mkdir(parents=True, exist_ok=True)
        self.final_image.write_bytes(b"AI-edited storyboard with normalized Shot labels")

    def tearDown(self):
        self.tmp.cleanup()

    def _entry(self):
        return {
            "shot_label_metadata": {
                "type": "shot_label_metadata_only",
                "evidence": str(self.evidence.relative_to(self.root)),
                "panel_pixels_modified": False,
            }
        }

    def _write_evidence(self, **overrides):
        report = {
            "status": "PASS",
            "postprocess_type": "shot_label_metadata_only",
            "output": "output/job-001/image-batch/candidates/part1_labels_restored.png",
            "output_sha256": hashlib.sha256(self.final_image.read_bytes()).hexdigest(),
            "labels": [f"Shot {index:02d}" for index in range(1, 13)],
            "outside_label_changed_pixels": 0,
            "panel_pixels_modified": False,
            "panel_content_sha256_before": "a" * 64,
            "panel_content_sha256_after": "a" * 64,
        }
        report.update(overrides)
        self.evidence.write_text(json.dumps(report), encoding="utf-8")

    def test_v2_manifest_accepts_hash_matched_metadata_only_restore(self):
        self._write_evidence()
        checks = []

        validate_shot_label_metadata(
            self.root,
            checks,
            "part1",
            self._entry(),
            self.final_image,
            required=True,
        )

        self.assertTrue(checks)
        self.assertTrue(all(check["status"] == "PASS" for check in checks), checks)

    def test_v2_manifest_rejects_missing_restore_evidence(self):
        checks = []

        validate_shot_label_metadata(
            self.root,
            checks,
            "part1",
            {},
            self.final_image,
            required=True,
        )

        self.assertIn("FAIL", {check["status"] for check in checks})

    def test_v2_manifest_rejects_panel_edits_or_output_hash_mismatch(self):
        self._write_evidence(
            output_sha256="0" * 64,
            outside_label_changed_pixels=7,
            panel_pixels_modified=True,
        )
        checks = []

        validate_shot_label_metadata(
            self.root,
            checks,
            "part1",
            self._entry(),
            self.final_image,
            required=True,
        )

        failed = {check["name"] for check in checks if check["status"] == "FAIL"}
        self.assertIn("part_storyboard_part1_shot_label_zero_panel_changes", failed)
        self.assertIn("part_storyboard_part1_shot_label_output_hash", failed)

    def test_v2_manifest_rejects_changed_panel_content_fingerprint(self):
        self._write_evidence(panel_content_sha256_after="b" * 64)
        checks = []

        validate_shot_label_metadata(
            self.root,
            checks,
            "part1",
            self._entry(),
            self.final_image,
            required=True,
        )

        failed = {check["name"] for check in checks if check["status"] == "FAIL"}
        self.assertIn("part_storyboard_part1_shot_label_panel_content_fingerprint", failed)


if __name__ == "__main__":
    unittest.main()
