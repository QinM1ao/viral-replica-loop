import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from replay_storyboard_visual_acceptance import run_replay  # noqa: E402
from qc_input_binding import attach_input_binding  # noqa: E402
from tests import test_storyboard_visual_acceptance as visual_fixture  # noqa: E402


class StoryboardVisualReplayTest(unittest.TestCase):
    def setUp(self):
        self.fixture = visual_fixture.StoryboardVisualAcceptanceTest(methodName="runTest")
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_isolated_replay_proves_changed_unchanged_mixed_and_preflight_paths(self):
        protected = self.fixture.job_dir / "seedance/seedance_part1_prompt.txt"
        protected.parent.mkdir(parents=True, exist_ok=True)
        protected.write_text("protected prompt\n", encoding="utf-8")
        manifest = self.fixture.job_dir / "visual-assets/approved_visual_manifest.json"
        candidates = sorted((self.fixture.job_dir / "final-images").glob("*.png"))
        contract_report = {
            "overall": "PASS",
            "checks": [
                {
                    "name": "fixture_real_image_input_contract",
                    "status": "PASS",
                    "detail": "bound fixture inputs",
                }
            ],
        }
        attach_input_binding(
            contract_report,
            self.fixture.root,
            [manifest, *candidates],
        )
        (self.fixture.job_dir / "checks/image_batch_qc_codex_imagegen_contract_qc.json").write_text(
            json.dumps(contract_report) + "\n",
            encoding="utf-8",
        )
        for name in (
            "storyboard_geometry_compare.jpg",
            "cross_part_continuity_compare.jpg",
            "skincare_progression_compare.jpg",
            "storyboard_geometry_review.json",
            "cross_part_continuity_review.json",
            "skincare_progression_review.json",
            "image_batch_checker_visual_review.json",
        ):
            (self.fixture.job_dir / "checks" / name).write_bytes(b"legacy evidence\n")

        report = run_replay(
            self.fixture.root,
            self.fixture.job_id,
            protected_paths=[protected],
        )

        self.assertTrue(report["isolated_replay"])
        self.assertEqual(report["paid_generation_calls"], {"gpt_image": 0, "seedance": 0})
        self.assertEqual(report["before"]["compare_count"], 3)
        self.assertEqual(report["before"]["review_count"], 4)
        self.assertEqual(report["before"]["checker_invocation_count"], 4)
        self.assertEqual(
            report["changed_state"]["families"],
            [
                "geometry_appearance",
                "identity_product_material_integrity",
                "cross_part_continuity",
                "skincare_progression",
            ],
        )
        self.assertEqual(report["changed_state"]["compare_count"], 1)
        self.assertEqual(report["changed_state"]["semantic_request_count"], 1)
        self.assertEqual(report["changed_state"]["checker_invocation_count"], 1)
        self.assertGreaterEqual(
            report["changed_state"]["imagegen_contract_check_count"],
            1,
        )
        self.assertEqual(report["changed_state"]["accepted_overall"], "PASS")
        self.assertEqual(report["unchanged_state"]["compare_generation_count"], 0)
        self.assertEqual(report["unchanged_state"]["semantic_request_count"], 0)
        self.assertEqual(report["unchanged_state"]["checker_invocation_count"], 0)
        self.assertEqual(report["unchanged_state"]["reused_family_count"], 4)
        self.assertGreater(report["changed_state"]["active_seconds"], 0)
        self.assertGreaterEqual(report["changed_state"]["wait_seconds"], 0)
        self.assertEqual(report["unchanged_state"]["wait_seconds"], 0)
        self.assertEqual(report["mixed_result"]["overall"], "FAIL")
        self.assertEqual(
            report["mixed_result"]["preserved_pass_families"],
            [
                "geometry_appearance",
                "cross_part_continuity",
                "skincare_progression",
            ],
        )
        self.assertEqual(
            report["mixed_result"]["repair_request_families"],
            ["identity_product_material_integrity"],
        )
        self.assertEqual(report["deterministic_failure"]["overall"], "FAIL")
        self.assertEqual(report["deterministic_failure"]["checker_invocation_count"], 0)
        self.assertTrue(report["protected_artifacts"]["unchanged"])


if __name__ == "__main__":
    unittest.main()
