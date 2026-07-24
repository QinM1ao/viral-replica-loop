import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
QC_SCRIPT = REPO_ROOT / "tools" / "storyboard_geometry_qc.py"


class StoryboardGeometryQCTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        source = self.root / "output/job-001/storyboard_source_refs/source_storyboard_part1.jpg"
        candidate = self.root / "output/job-001/final-images/part1.png"
        source.parent.mkdir(parents=True)
        candidate.parent.mkdir(parents=True)
        Image.new("RGB", (856, 1246), "white").save(source)
        Image.new("RGB", (864, 1248), "white").save(candidate)

        manifest = {
            "part_storyboards": {
                "part1": {
                    "path": "output/job-001/final-images/part1.png",
                    "source_reference": "output/job-001/storyboard_source_refs/source_storyboard_part1.jpg",
                }
            }
        }
        manifest_path = self.root / "output/job-001/visual-assets/approved_visual_manifest.json"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

        self.review_path = self.root / "output/job-001/checks/storyboard_geometry_review.json"
        self.review_path.parent.mkdir(parents=True)
        self.review = {
            "job_id": "job-001",
            "reviewer": "checker",
            "same_12_panel_template": True,
            "panel_sizes_match_source": True,
            "shot_order_matches_source": True,
            "no_recomposed_storyboard": True,
            "no_squashed_subjects": True,
            "api_edit_effect_matches_job002": True,
        }

    def tearDown(self):
        self.tmp.cleanup()

    def run_qc(self):
        self.review_path.write_text(json.dumps(self.review) + "\n", encoding="utf-8")
        result = subprocess.run(
            [
                "python3",
                str(QC_SCRIPT),
                "--root",
                str(self.root),
                "--job-id",
                "job-001",
                "--stage",
                "image_batch_qc",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report_path = self.root / "output/job-001/checks/image_batch_qc_storyboard_geometry_qc.json"
        return json.loads(report_path.read_text(encoding="utf-8"))

    def test_missing_shot_label_review_stops_geometry_qc(self):
        report = self.run_qc()

        self.assertEqual(report["overall"], "STOP")
        self.assertIn("shot_labels_preserved", report["missing_flags"])

    def test_true_shot_label_review_passes_geometry_qc(self):
        self.review["shot_labels_preserved"] = True

        report = self.run_qc()

        self.assertEqual(report["overall"], "PASS")
        self.assertEqual(report["review"]["shot_labels_preserved"], True)


if __name__ == "__main__":
    unittest.main()
