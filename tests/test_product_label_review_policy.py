import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from product_profile import build_product_profile  # noqa: E402
from storyboard_visual_acceptance import (  # noqa: E402
    FAMILY_CHECKS,
    integrity_profile_expectations,
    profile_expectations,
    selected_support_refs,
)
from visual_asset_manifest_qc import validate_product_group  # noqa: E402


class ProductLabelReviewPolicyTest(unittest.TestCase):
    def test_generic_profile_allows_approximate_microtext_at_storyboard_scale(self):
        profile = build_product_profile(
            ROOT,
            {
                "id": "job-test",
                "product_name": "孔凤春发酵水",
                "client_profile": "kongfengchun",
                "notes": "",
            },
        )

        self.assertEqual(
            profile["label_review_policy"],
            {
                "storyboard_microtext_exact_required": False,
                "small_or_distant_product_text": "visual_match_only",
                "microtext_only_mismatch_outcome": "VISUAL_WARNING",
                "hero_closeup_major_label_required": True,
            },
        )

    def test_checker_contract_forbids_microtext_only_hard_failure(self):
        checker = (ROOT / "workers/checker_worker.md").read_text(encoding="utf-8")
        gate = (ROOT / "gates/image_batch_gate.md").read_text(encoding="utf-8")

        for contract in (checker, gate):
            self.assertIn("small_or_distant_product_text=visual_match_only", contract)
            self.assertIn("microtext_only_mismatch_outcome=VISUAL_WARNING", contract)
            self.assertIn("must not be the sole reason for hard `FAIL`", contract)

    def test_visual_request_uses_scale_policy_and_label_detail_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            group_dir = root / "output/shared/product"
            group_dir.mkdir(parents=True)
            (group_dir / "front.png").write_bytes(b"front")
            (group_dir / "label-detail.png").write_bytes(b"label")
            (root / "label-detail.png").write_bytes(b"wrong-root-label")
            group_manifest = group_dir / "manifest.json"
            group_manifest.write_text(
                json.dumps(
                    {
                        "asset_group_type": "product_group",
                        "product_id": "product-test",
                        "product_name": "Test Product",
                        "source_assets": str(group_dir),
                        "front_ref": "front.png",
                        "label_detail_ref": "label-detail.png",
                    }
                ),
                encoding="utf-8",
            )
            profile = {
                "label_review_policy": {
                    "storyboard_microtext_exact_required": False,
                    "small_or_distant_product_text": "visual_match_only",
                    "microtext_only_mismatch_outcome": "VISUAL_WARNING",
                    "hero_closeup_major_label_required": True,
                }
            }
            manifest = {
                "product_group_manifest": str(group_manifest.relative_to(root)),
                "reusable_refs": {
                    "product_front": str(
                        (group_dir / "front.png").relative_to(root)
                    )
                },
            }

            refs = selected_support_refs(root, manifest, profile)
            expectations = profile_expectations(profile)
            integrity = integrity_profile_expectations(expectations)

            self.assertEqual(
                {ref["role"] for ref in refs},
                {"product_front", "product_label_detail"},
            )
            self.assertEqual(
                next(
                    ref["path"]
                    for ref in refs
                    if ref["role"] == "product_label_detail"
                ),
                (group_dir / "label-detail.png").resolve(),
            )
            self.assertEqual(
                integrity["label_review_policy"]["small_or_distant_product_text"],
                "visual_match_only",
            )
            self.assertFalse(
                integrity["label_review_policy"][
                    "hero_closeup_major_label_required"
                ]
            )
            self.assertIn(
                "current_product_and_scale_appropriate_label_preserved",
                FAMILY_CHECKS["identity_product_material_integrity"],
            )
            checks = []
            _, bound_label_detail = validate_product_group(
                root,
                checks,
                {
                    "product_name": "Test Product",
                    "product_assets": str(group_dir),
                },
                {
                    "product_group_id": "product-test",
                    "reusable_refs": {},
                },
                json.loads(group_manifest.read_text(encoding="utf-8")),
                group_manifest,
                {},
            )
            self.assertEqual(
                bound_label_detail.resolve(),
                (group_dir / "label-detail.png").resolve(),
            )
            label_check = next(
                check
                for check in checks
                if check["name"] == "product_label_detail_ref_exists"
            )
            self.assertEqual(label_check["status"], "PASS")

    def test_label_detail_blank_or_directory_is_not_a_visual_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            group_dir = root / "product"
            group_dir.mkdir()
            group_manifest = group_dir / "manifest.json"
            profile = {}

            group_manifest.write_text(
                json.dumps({"label_detail_ref": "   "}),
                encoding="utf-8",
            )
            refs = selected_support_refs(
                root,
                {
                    "product_group_manifest": str(group_manifest),
                    "reusable_refs": {},
                },
                profile,
            )
            self.assertEqual(refs, [])

            label_directory = group_dir / "label-directory"
            label_directory.mkdir()
            product_manifest = {
                "asset_group_type": "product_group",
                "product_id": "product-test",
                "product_name": "Test Product",
                "source_assets": str(group_dir),
                "front_ref": "label-directory",
                "label_detail_ref": "label-directory",
            }
            checks = []
            _, bound_label_detail = validate_product_group(
                root,
                checks,
                {
                    "product_name": "Test Product",
                    "product_assets": str(group_dir),
                },
                {
                    "product_group_id": "product-test",
                    "reusable_refs": {},
                },
                product_manifest,
                group_manifest,
                profile,
            )
            self.assertEqual(bound_label_detail, label_directory)
            label_check = next(
                check
                for check in checks
                if check["name"] == "product_label_detail_ref_exists"
            )
            self.assertEqual(label_check["status"], "STOP")


if __name__ == "__main__":
    unittest.main()
