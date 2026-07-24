import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL = REPO_ROOT / "tools" / "storyboard_visual_acceptance.py"


class StoryboardVisualAcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.job_id = "job-001"
        self.job_dir = self.root / "output" / self.job_id
        self.report = self.job_dir / "checks" / "shadow_visual_acceptance.json"
        self.request = self.job_dir / "checks" / "shadow_visual_request.json"
        self.compare = self.job_dir / "checks" / "shadow_visual_compare.jpg"
        (self.job_dir / "final-images").mkdir(parents=True)
        (self.job_dir / "storyboard_source_refs").mkdir(parents=True)
        (self.job_dir / "visual-assets").mkdir(parents=True)
        (self.job_dir / "checks").mkdir(parents=True)
        (self.root / "output/shared/product").mkdir(parents=True)
        (self.root / "output/shared/identity").mkdir(parents=True)
        (self.root / "assets/product").mkdir(parents=True)
        (self.root / "assets/person").mkdir(parents=True)
        person_asset = self.root / "assets/person/person.png"
        self._write_image(person_asset, (100, 140), "navy")
        (self.root / "jobs.csv").write_text(
            "id,product_name,product_assets,person_assets,output_dir\n"
            f"{self.job_id},Test Product,{self.root / 'assets/product'},"
            f"{person_asset},output/{self.job_id}\n",
            encoding="utf-8",
        )
        self._write_image(self.root / "output/shared/product/front.png", (80, 140), "green")
        self._write_image(self.root / "output/shared/product/open.png", (80, 140), "white")
        self._write_image(
            self.root / "output/shared/product/label-detail.png",
            (160, 280),
            "green",
        )
        self._write_image(self.root / "output/shared/identity/ref.png", (100, 140), "navy")
        self._write_image(
            self.root / "output/shared/identity/afterwash.png",
            (100, 140),
            "lightblue",
        )
        self._write_group_manifests(person_asset)
        self._write_profile(requires_skincare_progression=True)
        self._write_manifest(part_count=2)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _write_image(path, size, color):
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", size, color).save(path)

    @staticmethod
    def _sha256(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _write_json(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _write_profile(self, requires_skincare_progression):
        self._write_json(
            self.job_dir / "product_profile.json",
            {
                "job_id": self.job_id,
                "product_name": "Test Product",
                "loaded_rules": ["generic:generic_product", "category:skincare"],
                "reference_roles": {
                    "required": [
                        "source_storyboard",
                        "product_front",
                        "product_open_mud",
                        "identity_ref",
                    ],
                    "optional": [],
                },
                "checks": {
                    "requires_product_consistency": True,
                    "requires_skincare_progression": requires_skincare_progression,
                },
                "visible_text_patterns": ["Test Product"],
                "label_review_policy": {
                    "storyboard_microtext_exact_required": False,
                    "small_or_distant_product_text": "visual_match_only",
                    "microtext_only_mismatch_outcome": "VISUAL_WARNING",
                    "hero_closeup_major_label_required": True,
                },
            },
        )

    def _write_group_manifests(self, person_asset):
        self._write_json(
            self.root / "output/shared/product/manifest.json",
            {
                "asset_group_type": "product_group",
                "product_id": "product-a",
                "product_name": "Test Product",
                "source_assets": str(self.root / "assets/product"),
                "front_ref": "front.png",
                "open_mud_ref": "open.png",
                "label_detail_ref": "output/shared/product/label-detail.png",
            },
        )
        self._write_json(
            self.root / "output/shared/identity/manifest.json",
            {
                "asset_group_type": "identity_group",
                "identity_id": "identity-a",
                "presenter_gender": "male",
                "allowed_when": {"person_asset": str(person_asset)},
                "identity_ref": "ref.png",
                "afterwash_face_ref": "afterwash.png",
            },
        )

    def _write_manifest(self, part_count):
        parts = {}
        for number in range(1, part_count + 1):
            part = f"part{number}"
            source = self.job_dir / "storyboard_source_refs" / f"source_storyboard_{part}.jpg"
            candidate = self.job_dir / "final-images" / f"{part}_seedance_ref.png"
            evidence = self.job_dir / "checks" / f"{part}_shot_label_restore.json"
            self._write_image(source, (400, 600), "gray")
            self._write_image(candidate, (400, 600), "white")
            candidate_sha = self._sha256(candidate)
            self._write_json(
                evidence,
                {
                    "status": "PASS",
                    "postprocess_type": "shot_label_metadata_only",
                    "output_sha256": candidate_sha,
                    "canvas": [400, 600],
                    "grid": {"cols": 4, "rows": 3},
                    "labels": [f"Shot {index:02d}" for index in range(1, 13)],
                    "outside_label_changed_pixels": 0,
                    "panel_pixels_modified": False,
                    "panel_content_sha256_before": "a" * 64,
                    "panel_content_sha256_after": "a" * 64,
                },
            )
            hard_gate = self.job_dir / "checks" / f"{part}_image_hard_gate_qc.json"
            self._write_json(
                hard_gate,
                {
                    "overall": "PASS",
                    "candidate": str(candidate.relative_to(self.root)),
                    "candidate_sha256": candidate_sha,
                },
            )
            parts[part] = {
                "path": str(candidate.relative_to(self.root)),
                "asset_type": "AI改好分镜图",
                "image_route": "matpool_gpt_image_2_edit",
                "contains_source_video_pixels": False,
                "source_reference": str(source.relative_to(self.root)),
                "candidate_sha256": candidate_sha,
                "hard_gate": str(hard_gate.relative_to(self.root)),
                "shot_label_metadata": {
                    "type": "shot_label_metadata_only",
                    "evidence": str(evidence.relative_to(self.root)),
                    "panel_pixels_modified": False,
                },
            }
        self._write_json(
            self.job_dir / "visual-assets" / "approved_visual_manifest.json",
            {
                "schema_version": 2,
                "job_id": self.job_id,
                "product_group_id": "product-a",
                "product_group_manifest": "output/shared/product/manifest.json",
                "identity_group_id": "identity-a",
                "identity_group_manifest": "output/shared/identity/manifest.json",
                "source_presenter_gender": "male",
                "target_presenter_gender": "male",
                "part_storyboards": parts,
                "reusable_refs": {
                    "product_front": "output/shared/product/front.png",
                    "product_open": "output/shared/product/open.png",
                    "identity_ref": "output/shared/identity/ref.png",
                    "afterwash_face": "output/shared/identity/afterwash.png",
                },
            },
        )

    def run_tool(self):
        return subprocess.run(
            [
                "python3",
                str(TOOL),
                "--root",
                str(self.root),
                "--job-id",
                self.job_id,
                "--out-json",
                str(self.report),
                "--request-out",
                str(self.request),
                "--compare-out",
                str(self.compare),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_changed_multi_part_skincare_batch_prepares_one_visual_review(self):
        result = self.run_tool()

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(self.report.read_text(encoding="utf-8"))
        request = json.loads(self.request.read_text(encoding="utf-8"))
        self.assertEqual(report["mode"], "shadow")
        self.assertEqual(report["deterministic_preflight"]["overall"], "PASS")
        self.assertEqual(report["semantic_review"]["status"], "REVIEW_REQUIRED")
        self.assertEqual(
            [family["name"] for family in request["families"]],
            [
                "geometry_appearance",
                "identity_product_material_integrity",
                "cross_part_continuity",
                "skincare_progression",
            ],
        )
        self.assertEqual(request["invocation_count"], 1)
        self.assertTrue(all(family["fingerprint_hash"] for family in request["families"]))
        self.assertEqual(
            request["profile_expectations"]["loaded_rules"],
            ["generic:generic_product", "category:skincare"],
        )
        self.assertTrue(
            request["profile_expectations"]["checks"]["requires_product_consistency"]
        )
        self.assertEqual(
            request["profile_expectations"]["label_review_policy"],
            {
                "storyboard_microtext_exact_required": False,
                "small_or_distant_product_text": "visual_match_only",
                "microtext_only_mismatch_outcome": "VISUAL_WARNING",
                "hero_closeup_major_label_required": True,
            },
        )
        integrity_family = next(
            family
            for family in request["families"]
            if family["name"] == "identity_product_material_integrity"
        )
        self.assertIn(
            "current_product_and_scale_appropriate_label_preserved",
            integrity_family["required_checks"],
        )
        self.assertNotIn(
            "current_product_and_readable_label_preserved",
            integrity_family["required_checks"],
        )
        preflight = {
            check["name"]: check["status"]
            for check in report["deterministic_preflight"]["checks"]
        }
        for name in (
            "part1_orientation_matches_source",
            "part1_shot_metadata_grid",
            "part_storyboard_part1_shot_label_ordered_labels",
            "part_storyboard_part1_shot_label_output_hash",
        ):
            self.assertEqual(preflight[name], "PASS")
        self.assertEqual(
            report["canonical_compare_context"]["path"],
            str(self.compare.relative_to(self.root)),
        )
        self.assertTrue(self.compare.exists())
        with Image.open(self.compare) as compare_image:
            self.assertGreaterEqual(compare_image.width, 1900)
            self.assertGreaterEqual(compare_image.height, 2900)
        self.assertEqual(
            sorted(path.name for path in self.report.parent.glob("shadow_visual_compare*")),
            [self.compare.name],
        )
        source_artifacts = request["canonical_compare_context"]["source_artifacts"]
        self.assertEqual(request["canonical_compare_context"]["role"], "overview")
        self.assertIn(
            "output/job-001/final-images/part1_seedance_ref.png",
            {item["path"] for item in source_artifacts},
        )
        self.assertIn(
            "output/job-001/storyboard_source_refs/source_storyboard_part1.jpg",
            {item["path"] for item in source_artifacts},
        )
        self.assertIn(
            "output/shared/product/label-detail.png",
            {item["path"] for item in source_artifacts},
        )
        self.assertTrue(all(item["sha256"] for item in source_artifacts))
        self.assertIn("input_binding", report)
        self.assertTrue(
            {
                "output/job-001/product_profile.json",
                "output/job-001/visual-assets/approved_visual_manifest.json",
                "output/job-001/final-images/part1_seedance_ref.png",
                "output/job-001/storyboard_source_refs/source_storyboard_part1.jpg",
                "output/job-001/checks/part1_shot_label_restore.json",
                "output/shared/product/front.png",
                "output/shared/product/open.png",
                "output/shared/product/label-detail.png",
                "output/shared/identity/ref.png",
                "output/shared/identity/afterwash.png",
            }.issubset(report["input_binding"]["manifest"])
        )

    def test_missing_required_identity_reference_stops_before_visual_review(self):
        manifest_path = self.job_dir / "visual-assets" / "approved_visual_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["reusable_refs"].pop("identity_ref")
        self._write_json(manifest_path, manifest)

        result = self.run_tool()

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(self.report.read_text(encoding="utf-8"))
        self.assertEqual(report["deterministic_preflight"]["overall"], "FAIL")
        self.assertEqual(report["semantic_review"]["status"], "NOT_REQUESTED")
        self.assertFalse(self.request.exists())
        self.assertFalse(self.compare.exists())

    def test_non_ai_storyboard_route_fails_before_visual_review(self):
        manifest_path = self.job_dir / "visual-assets" / "approved_visual_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["part_storyboards"]["part1"]["image_route"] = "local_pil_composite"
        self._write_json(manifest_path, manifest)

        result = self.run_tool()

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(self.report.read_text(encoding="utf-8"))
        self.assertEqual(report["deterministic_preflight"]["overall"], "FAIL")
        self.assertEqual(report["semantic_review"]["status"], "NOT_REQUESTED")
        self.assertFalse(self.request.exists())
        self.assertFalse(self.compare.exists())

    def test_source_storyboard_outside_current_job_fails_before_visual_review(self):
        external_source = self.root / "output/shared/source_storyboard_part1.jpg"
        self._write_image(external_source, (400, 600), "gray")
        manifest_path = self.job_dir / "visual-assets" / "approved_visual_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["part_storyboards"]["part1"]["source_reference"] = str(
            external_source.relative_to(self.root)
        )
        self._write_json(manifest_path, manifest)

        result = self.run_tool()

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(self.report.read_text(encoding="utf-8"))
        self.assertEqual(report["deterministic_preflight"]["overall"], "FAIL")
        self.assertEqual(report["semantic_review"]["status"], "NOT_REQUESTED")
        self.assertFalse(self.request.exists())
        self.assertFalse(self.compare.exists())

    def test_missing_active_binding_group_fails_before_visual_review(self):
        manifest_path = self.job_dir / "visual-assets" / "approved_visual_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["identity_group_id"] = ""
        self._write_json(manifest_path, manifest)

        result = self.run_tool()

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(self.report.read_text(encoding="utf-8"))
        self.assertEqual(report["deterministic_preflight"]["overall"], "FAIL")
        self.assertEqual(report["semantic_review"]["status"], "NOT_REQUESTED")
        self.assertFalse(self.request.exists())
        self.assertFalse(self.compare.exists())

    def test_single_part_non_skincare_batch_omits_irrelevant_families_and_preserves_legacy_qc(self):
        self._write_profile(requires_skincare_progression=False)
        self._write_manifest(part_count=1)
        legacy_compare = self.report.parent / "storyboard_geometry_compare.jpg"
        legacy_compare.write_bytes(b"legacy-compare")

        result = self.run_tool()

        self.assertEqual(result.returncode, 0, result.stderr)
        request = json.loads(self.request.read_text(encoding="utf-8"))
        self.assertEqual(
            [family["name"] for family in request["families"]],
            ["geometry_appearance", "identity_product_material_integrity"],
        )
        self.assertEqual(legacy_compare.read_bytes(), b"legacy-compare")

    def test_reusable_identity_must_match_the_declared_identity_group(self):
        rogue_identity = self.root / "output/shared/identity/rogue.png"
        self._write_image(rogue_identity, (100, 140), "red")
        manifest_path = self.job_dir / "visual-assets" / "approved_visual_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["reusable_refs"]["identity_ref"] = str(rogue_identity.relative_to(self.root))
        self._write_json(manifest_path, manifest)

        result = self.run_tool()

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(self.report.read_text(encoding="utf-8"))
        self.assertEqual(report["deterministic_preflight"]["overall"], "FAIL")
        self.assertEqual(report["semantic_review"]["status"], "NOT_REQUESTED")

    def test_family_fingerprints_only_change_for_relevant_support_input(self):
        first = self.run_tool()
        self.assertEqual(first.returncode, 0, first.stderr)
        before = {
            family["name"]: family["fingerprint_hash"]
            for family in json.loads(self.request.read_text(encoding="utf-8"))["families"]
        }

        self._write_image(self.root / "output/shared/product/front.png", (80, 140), "red")
        second = self.run_tool()

        self.assertEqual(second.returncode, 0, second.stderr)
        after = {
            family["name"]: family["fingerprint_hash"]
            for family in json.loads(self.request.read_text(encoding="utf-8"))["families"]
        }
        self.assertNotEqual(
            before["identity_product_material_integrity"],
            after["identity_product_material_integrity"],
        )
        self.assertEqual(before["geometry_appearance"], after["geometry_appearance"])
        self.assertEqual(before["cross_part_continuity"], after["cross_part_continuity"])
        self.assertEqual(before["skincare_progression"], after["skincare_progression"])

    def test_afterwash_reference_only_changes_skincare_fingerprint(self):
        first = self.run_tool()
        self.assertEqual(first.returncode, 0, first.stderr)
        before = {
            family["name"]: family["fingerprint_hash"]
            for family in json.loads(self.request.read_text(encoding="utf-8"))["families"]
        }

        self._write_image(
            self.root / "output/shared/identity/afterwash.png",
            (100, 140),
            "pink",
        )
        second = self.run_tool()

        self.assertEqual(second.returncode, 0, second.stderr)
        after = {
            family["name"]: family["fingerprint_hash"]
            for family in json.loads(self.request.read_text(encoding="utf-8"))["families"]
        }
        self.assertEqual(before["geometry_appearance"], after["geometry_appearance"])
        self.assertEqual(
            before["identity_product_material_integrity"],
            after["identity_product_material_integrity"],
        )
        self.assertEqual(before["cross_part_continuity"], after["cross_part_continuity"])
        self.assertNotEqual(before["skincare_progression"], after["skincare_progression"])

    def test_source_storyboard_change_invalidates_geometry_and_integrity_only(self):
        first = self.run_tool()
        self.assertEqual(first.returncode, 0, first.stderr)
        before = {
            family["name"]: family["fingerprint_hash"]
            for family in json.loads(self.request.read_text(encoding="utf-8"))["families"]
        }

        source = self.job_dir / "storyboard_source_refs/source_storyboard_part1.jpg"
        self._write_image(source, (400, 600), "black")
        second = self.run_tool()

        self.assertEqual(second.returncode, 0, second.stderr)
        after = {
            family["name"]: family["fingerprint_hash"]
            for family in json.loads(self.request.read_text(encoding="utf-8"))["families"]
        }
        self.assertNotEqual(before["geometry_appearance"], after["geometry_appearance"])
        self.assertNotEqual(
            before["identity_product_material_integrity"],
            after["identity_product_material_integrity"],
        )
        self.assertEqual(before["cross_part_continuity"], after["cross_part_continuity"])
        self.assertEqual(before["skincare_progression"], after["skincare_progression"])

    def test_failed_part_hard_gate_stops_before_visual_review(self):
        hard_gate = self.job_dir / "checks" / "part1_image_hard_gate_qc.json"
        gate = json.loads(hard_gate.read_text(encoding="utf-8"))
        gate["overall"] = "FAIL"
        self._write_json(hard_gate, gate)

        result = self.run_tool()

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(self.report.read_text(encoding="utf-8"))
        self.assertEqual(report["deterministic_preflight"]["overall"], "FAIL")
        self.assertEqual(report["semantic_review"]["status"], "NOT_REQUESTED")

    def test_stale_hard_gate_pass_is_not_reused(self):
        candidate = self.job_dir / "final-images/part1_seedance_ref.png"
        self._write_image(candidate, (400, 600), "silver")
        current_sha = self._sha256(candidate)
        evidence_path = self.job_dir / "checks/part1_shot_label_restore.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["output_sha256"] = current_sha
        self._write_json(evidence_path, evidence)
        manifest_path = self.job_dir / "visual-assets/approved_visual_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["part_storyboards"]["part1"]["candidate_sha256"] = current_sha
        self._write_json(manifest_path, manifest)

        result = self.run_tool()

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(self.report.read_text(encoding="utf-8"))
        checks = {
            check["name"]: check
            for check in report["deterministic_preflight"]["checks"]
        }
        freshness = checks["part1_hard_gate_evidence_freshness"]
        self.assertEqual(freshness["status"], "PASS")
        self.assertIn("stale result ignored", freshness["detail"])
        self.assertEqual(report["semantic_review"]["status"], "REVIEW_REQUIRED")

    def test_malformed_manifest_shape_returns_structured_failure(self):
        manifest_path = self.job_dir / "visual-assets" / "approved_visual_manifest.json"
        self._write_json(manifest_path, ["not", "an", "object"])

        result = self.run_tool()

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(self.report.read_text(encoding="utf-8"))
        self.assertEqual(report["deterministic_preflight"]["overall"], "FAIL")
        self.assertEqual(report["semantic_review"]["status"], "NOT_REQUESTED")

    def test_compare_context_omits_unselected_optional_reference(self):
        self._write_profile(requires_skincare_progression=False)
        self._write_manifest(part_count=1)
        style_ref = self.root / "output/shared/product/style.png"
        self._write_image(style_ref, (80, 140), "purple")
        manifest_path = self.job_dir / "visual-assets" / "approved_visual_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["reusable_refs"]["style_ref"] = str(style_ref.relative_to(self.root))
        self._write_json(manifest_path, manifest)

        result = self.run_tool()

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(self.report.read_text(encoding="utf-8"))
        self.assertEqual(report["canonical_compare_context"]["item_count"], 6)
        self.assertNotIn(
            str(style_ref.relative_to(self.root)),
            report["input_binding"]["manifest"],
        )

    def test_invalid_shot_order_stops_before_visual_review(self):
        evidence_path = self.job_dir / "checks" / "part1_shot_label_restore.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["labels"] = list(reversed(evidence["labels"]))
        self._write_json(evidence_path, evidence)

        result = self.run_tool()

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(self.report.read_text(encoding="utf-8"))
        self.assertEqual(report["deterministic_preflight"]["overall"], "FAIL")
        self.assertEqual(report["semantic_review"]["status"], "NOT_REQUESTED")

    def test_invalid_canvas_stops_before_visual_review(self):
        evidence_path = self.job_dir / "checks/part1_shot_label_restore.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["canvas"] = [401, 600]
        self._write_json(evidence_path, evidence)

        result = self.run_tool()

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(self.report.read_text(encoding="utf-8"))
        self.assertEqual(report["deterministic_preflight"]["overall"], "FAIL")
        self.assertEqual(report["semantic_review"]["status"], "NOT_REQUESTED")

    def test_invalid_grid_stops_before_visual_review(self):
        evidence_path = self.job_dir / "checks/part1_shot_label_restore.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["grid"] = {"cols": 3, "rows": 4}
        self._write_json(evidence_path, evidence)

        result = self.run_tool()

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(self.report.read_text(encoding="utf-8"))
        self.assertEqual(report["deterministic_preflight"]["overall"], "FAIL")
        self.assertEqual(report["semantic_review"]["status"], "NOT_REQUESTED")

    def test_invalid_panel_count_stops_before_visual_review(self):
        evidence_path = self.job_dir / "checks/part1_shot_label_restore.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["labels"] = evidence["labels"][:-1]
        self._write_json(evidence_path, evidence)

        result = self.run_tool()

        self.assertNotEqual(result.returncode, 0)
        report = json.loads(self.report.read_text(encoding="utf-8"))
        self.assertEqual(report["deterministic_preflight"]["overall"], "FAIL")
        self.assertEqual(report["semantic_review"]["status"], "NOT_REQUESTED")

    def test_same_active_fingerprint_reuses_the_canonical_compare(self):
        first = self.run_tool()
        self.assertEqual(first.returncode, 0, first.stderr)
        first_request = json.loads(self.request.read_text(encoding="utf-8"))
        os.utime(self.compare, ns=(1_000_000_000, 1_000_000_000))

        second = self.run_tool()

        self.assertEqual(second.returncode, 0, second.stderr)
        second_request = json.loads(self.request.read_text(encoding="utf-8"))
        self.assertEqual(
            first_request["active_input_fingerprint"],
            second_request["active_input_fingerprint"],
        )
        self.assertEqual(self.compare.stat().st_mtime_ns, 1_000_000_000)
        self.assertEqual(
            sorted(path.name for path in self.report.parent.glob("shadow_visual_compare*")),
            [self.compare.name],
        )

    def test_hard_gate_report_change_does_not_invalidate_semantic_families_or_compare(self):
        first = self.run_tool()
        self.assertEqual(first.returncode, 0, first.stderr)
        first_request = json.loads(self.request.read_text(encoding="utf-8"))
        first_families = {
            family["name"]: family["fingerprint_hash"]
            for family in first_request["families"]
        }
        os.utime(self.compare, ns=(1_000_000_000, 1_000_000_000))
        hard_gate = self.job_dir / "checks/part1_image_hard_gate_qc.json"
        gate = json.loads(hard_gate.read_text(encoding="utf-8"))
        gate["diagnostic_note"] = "non-semantic evidence update"
        self._write_json(hard_gate, gate)

        second = self.run_tool()

        self.assertEqual(second.returncode, 0, second.stderr)
        second_request = json.loads(self.request.read_text(encoding="utf-8"))
        second_families = {
            family["name"]: family["fingerprint_hash"]
            for family in second_request["families"]
        }
        self.assertEqual(first_families, second_families)
        self.assertEqual(
            first_request["active_input_fingerprint"],
            second_request["active_input_fingerprint"],
        )
        self.assertNotEqual(
            first_request["deterministic_input_fingerprint"],
            second_request["deterministic_input_fingerprint"],
        )
        self.assertEqual(self.compare.stat().st_mtime_ns, 1_000_000_000)

    def test_skincare_selection_does_not_change_integrity_family_fingerprint(self):
        first = self.run_tool()
        self.assertEqual(first.returncode, 0, first.stderr)
        before = {
            family["name"]: family["fingerprint_hash"]
            for family in json.loads(self.request.read_text(encoding="utf-8"))["families"]
        }

        self._write_profile(requires_skincare_progression=False)
        second = self.run_tool()

        self.assertEqual(second.returncode, 0, second.stderr)
        after = {
            family["name"]: family["fingerprint_hash"]
            for family in json.loads(self.request.read_text(encoding="utf-8"))["families"]
        }
        self.assertEqual(
            before["identity_product_material_integrity"],
            after["identity_product_material_integrity"],
        )
        self.assertNotIn("skincare_progression", after)


if __name__ == "__main__":
    unittest.main()
