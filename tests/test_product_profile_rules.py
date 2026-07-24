import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from product_profile import build_product_profile, load_product_profile, write_product_profile  # noqa: E402
from run_next_loop_round import preflight_pass_recording  # noqa: E402
from qc_risk_ledger import build_stage_ledger  # noqa: E402
from qc_input_binding import attach_input_binding  # noqa: E402


VISUAL_QC = REPO_ROOT / "tools" / "visual_asset_manifest_qc.py"
IMAGEGEN_QC = REPO_ROOT / "tools" / "codex_imagegen_contract_qc.py"


class ProductProfileRulesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._copy_rule_files()
        (self.root / "output/job-001/checks").mkdir(parents=True)
        (self.root / "assets/product").mkdir(parents=True)
        (self.root / "assets/person").mkdir(parents=True)
        (self.root / "assets/source").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _copy_rule_files(self):
        for src in (REPO_ROOT / "rules/product-profiles").rglob("*.json"):
            dest = self.root / src.relative_to(REPO_ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    def write_jobs(
        self,
        product_name,
        client_profile="kongfengchun",
        notes="",
        person_assets=None,
    ):
        with (self.root / "jobs.csv").open("w", newline="", encoding="utf-8") as f:
            fields = [
                "id",
                "status",
                "video_path",
                "product_name",
                "client_profile",
                "product_assets",
                "person_assets",
                "audio_assets",
                "target_duration",
                "notes",
                "output_dir",
                "last_artifact",
                "next_stage",
                "needs_user_confirmation",
            ]
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerow(
                {
                    "id": "job-001",
                    "status": "storyboard_passed",
                    "video_path": str(self.root / "assets/source/source.mp4"),
                    "product_name": product_name,
                    "client_profile": client_profile,
                    "product_assets": str(self.root / "assets/product"),
                    "person_assets": person_assets or str(self.root / "assets/person"),
                    "audio_assets": "extract_from_original",
                    "target_duration": "30s",
                    "notes": notes,
                    "output_dir": "output/job-001",
                    "last_artifact": "",
                    "next_stage": "image_batch_qc",
                    "needs_user_confirmation": "false",
                }
            )
        job = self.read_job()
        write_product_profile(self.root, job)
        return job

    def read_job(self):
        with (self.root / "jobs.csv").open(newline="", encoding="utf-8") as f:
            return next(csv.DictReader(f))

    def touch(self, rel, data=b"data"):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def write_visual_fixture(self, product_name, include_open_mud=False, include_afterwash=False):
        self.write_jobs(product_name)
        self.touch("assets/product/front.png")
        self.touch("assets/person/identity.png")
        if include_open_mud:
            self.touch("assets/product/open_mud.png")
        if include_afterwash:
            self.touch("assets/person/afterwash.png")
        candidate = self.touch("output/job-001/final-images/part1.png")

        product_manifest = {
            "asset_group_type": "product_group",
            "product_id": "product",
            "product_name": product_name,
            "source_assets": str(self.root / "assets/product"),
            "front_ref": "front.png",
        }
        if include_open_mud:
            product_manifest["open_mud_ref"] = "open_mud.png"
        (self.root / "assets/product/manifest.json").write_text(
            json.dumps(product_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        identity_manifest = {
            "asset_group_type": "identity_group",
            "identity_id": "identity",
            "presenter_gender": "female",
            "identity_ref": "identity.png",
            "allowed_when": {"person_asset": str(self.root / "assets/person")},
        }
        if include_afterwash:
            identity_manifest["afterwash_face_ref"] = "afterwash.png"
        (self.root / "assets/person/manifest.json").write_text(
            json.dumps(identity_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        refs = {
            "product_front": str(self.root / "assets/product/front.png"),
            "identity_ref": str(self.root / "assets/person/identity.png"),
        }
        if include_open_mud:
            refs["product_open"] = str(self.root / "assets/product/open_mud.png")
        if include_afterwash:
            refs["afterwash_face"] = str(self.root / "assets/person/afterwash.png")
        evidence_path = self.root / "output/job-001/checks/part1_shot_label_restore.json"
        evidence_path.write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "postprocess_type": "shot_label_metadata_only",
                    "output_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
                    "labels": [f"Shot {index:02d}" for index in range(1, 13)],
                    "outside_label_changed_pixels": 0,
                    "panel_pixels_modified": False,
                    "panel_content_sha256_before": "a" * 64,
                    "panel_content_sha256_after": "a" * 64,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        manifest = {
            "schema_version": 2,
            "job_id": "job-001",
            "source_presenter_gender": "female",
            "target_presenter_gender": "female",
            "product_group_id": "product",
            "product_group_manifest": str(self.root / "assets/product/manifest.json"),
            "identity_group_id": "identity",
            "identity_group_manifest": str(self.root / "assets/person/manifest.json"),
            "reusable_refs": refs,
            "part_storyboards": {
                "part1": {
                    "asset_type": "AI改好分镜图",
                    "image_route": "matpool_gpt_image_2_edit",
                    "contains_source_video_pixels": False,
                    "path": str(candidate),
                    "shot_label_metadata": {
                        "type": "shot_label_metadata_only",
                        "evidence": str(evidence_path),
                        "panel_pixels_modified": False,
                    },
                }
            },
        }
        manifest_path = self.root / "output/job-001/visual-assets/approved_visual_manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return manifest_path

    def run_visual_qc(self, manifest, expect_success=True, stage="image_batch_qc", check_final_dir=False):
        out_json = self.root / "visual_qc.json"
        command = [
            "python3",
            str(VISUAL_QC),
            "--root",
            str(self.root),
            "--job-id",
            "job-001",
            "--stage",
            stage,
            "--manifest",
            str(manifest),
            "--out-json",
            str(out_json),
            "--out-md",
            str(self.root / "visual_qc.md"),
        ]
        if check_final_dir:
            command.append("--check-final-dir")
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
        )
        if expect_success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return json.loads(out_json.read_text(encoding="utf-8"))

    def test_visual_manifest_accepts_current_job_storyboard_derived_roles(self):
        manifest_path = self.write_visual_fixture("Test Product")
        self.write_jobs("Test Product", person_assets="storyboard_derived")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        storyboard = Path(manifest["part_storyboards"]["part1"]["path"])
        derived_dir = self.root / "output/job-001/visual-assets/derived-identities"
        derived_dir.mkdir(parents=True)
        role_map_path = self.root / "output/job-001/visual-assets/role_map.json"
        role_map_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "job_id": "job-001",
                    "roles": [
                        {
                            "id": "role_A",
                            "gender": "female",
                            "parts": ["part1"],
                            "source_role": "产品演示者",
                            "identity_required": True,
                        },
                        {
                            "id": "role_D",
                            "gender": "female",
                            "parts": ["part1"],
                            "source_role": "近景体验者",
                            "identity_required": True,
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        role_manifests = {}
        part_refs = {}
        for role in ("role_A", "role_D"):
            identity_ref = derived_dir / f"{role}.png"
            identity_ref.write_bytes(role.encode("utf-8"))
            role_manifest = derived_dir / f"{role}_manifest.json"
            role_manifest.write_text(
                json.dumps(
                    {
                        "asset_group_type": "identity_group",
                        "identity_id": role,
                        "role_id": role,
                        "presenter_gender": "female",
                        "origin": "storyboard_derived",
                        "source_job_id": "job-001",
                        "source_part": "part1",
                        "source_storyboard": str(storyboard),
                        "identity_ref": identity_ref.name,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            role_manifests[role] = str(role_manifest)
            part_refs[f"identity_{role}"] = str(identity_ref)

        manifest["schema_version"] = 3
        manifest["person_asset_mode"] = "storyboard_derived"
        manifest["role_map"] = str(role_map_path)
        manifest["identity_role_manifests"] = role_manifests
        manifest["part_identity_roles"] = {"part1": ["role_A", "role_D"]}
        manifest["part_reusable_refs"] = {"part1": part_refs}
        manifest["reusable_refs"].pop("identity_ref")
        manifest.pop("identity_group_id")
        manifest.pop("identity_group_manifest")
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        report = self.run_visual_qc(manifest_path)

        self.assertEqual(report["overall"], "PASS")
        checks = {check["name"]: check for check in report["checks"]}
        self.assertEqual(checks["storyboard_derived_role_map"]["status"], "PASS")
        self.assertEqual(checks["storyboard_derived_role_A_provenance"]["status"], "PASS")
        self.assertEqual(checks["storyboard_derived_role_D_provenance"]["status"], "PASS")

        handoff = self.root / "output/job-001/seedance/handoff_mode.json"
        handoff.parent.mkdir(parents=True, exist_ok=True)
        handoff.write_text(json.dumps({"audio_parts": []}), encoding="utf-8")
        upload_dir = self.root / "output/job-001/seedance_web_final/Part1_上传素材"
        upload_dir.mkdir(parents=True)
        (upload_dir / "01_storyboard.png").write_bytes(storyboard.read_bytes())
        (upload_dir / "02_product.png").write_bytes(
            (self.root / "assets/product/front.png").read_bytes()
        )
        for prefix, role in (("04", "role_A"), ("05", "role_D")):
            (upload_dir / f"{prefix}_{role}.png").write_bytes(
                (derived_dir / f"{role}.png").read_bytes()
            )

        final_report = self.run_visual_qc(
            manifest_path,
            stage="request_qc",
            check_final_dir=True,
        )
        self.assertEqual(final_report["overall"], "PASS")
        final_checks = {check["name"]: check for check in final_report["checks"]}
        self.assertEqual(final_checks["final_part1_04_matches_manifest"]["status"], "PASS")
        self.assertEqual(final_checks["final_part1_05_matches_manifest"]["status"], "PASS")

    def write_contract_fixture(self, product_name, include_open_mud=False):
        manifest = self.write_visual_fixture(product_name, include_open_mud=include_open_mud, include_afterwash=include_open_mud)
        source = self.touch("output/job-001/storyboard_source_refs/source_storyboard_part1.jpg")
        prompt = self.root / "output/job-001/image-batch/prompt.md"
        prompt.parent.mkdir(parents=True, exist_ok=True)
        prompt_text = (
            "孔凤春发酵水倒在掌心后轻拍上脸，"
            "PORTULACA OLERACEA FERMENTED ESSENCE TONER 马齿苋发酵精华水 visible on bottle label"
            if not include_open_mud
            else "孔凤春清洁泥膜，手指从罐内取乳白白色厚泥，用指腹涂到脸上"
        )
        prompt.write_text(prompt_text, encoding="utf-8")
        refs = {
            "source_storyboard": {"path": str(source), "loaded_to_context": True},
            "product_front": {"path": str(self.root / "assets/product/front.png"), "loaded_to_context": True},
            "identity_ref": {"path": str(self.root / "assets/person/identity.png"), "loaded_to_context": True},
        }
        if include_open_mud:
            refs["product_open_mud"] = {"path": str(self.root / "assets/product/open_mud.png"), "loaded_to_context": True}
        review = {
            "layout_matches_source": True,
            "source_aspect_preserved": True,
            "same_identity_as_reference": True,
            "primary_identity_consistent": True,
            "primary_identity_only_on_target_role": True,
            "secondary_characters_keep_source_role_gender": True,
            "no_source_host_identity": True,
            "target_product_packaging": True,
            "target_product_label": True,
            "no_old_product": True,
            "no_subtitles_or_text": True,
            "product_visible_text": True,
            "no_blank_label": True,
            "source_scene_preserved": True,
            "no_product_reference_background": True,
            "no_identity_reference_background": True,
        }
        if include_open_mud:
            review.update(
                {
                    "white_milky_thick_mud": True,
                    "finger_or_fingertip_application": True,
                    "no_tube_stick_brush_cotton_swatch": True,
                    "no_arm_swatch": True,
                }
            )
        contract = {
            "job_id": "job-001",
            "stage": "image_batch_qc",
            "image_route": "matpool_gpt_image_2_edit",
            "api_effect_baseline": {"source": "matpool_gpt_image_2_edit", "preserve_api_route": True},
            "matpool_uses_real_image_inputs": True,
            "source_storyboard_controls": ["layout", "shot_order", "framing", "action_rhythm", "scene_family", "shot_labels"],
            "source_storyboard_must_not_control": ["old_product", "old_tool", "old_host_identity", "old_mud_color", "subtitles"],
            "target_application_method": "finger_from_open_jar_to_face" if include_open_mud else "toner_pour_to_palm_and_pat_to_face",
            "reference_order": ["source_storyboard", "product_front", "product_open_mud", "identity_ref"]
            if include_open_mud
            else ["source_storyboard", "product_front", "identity_ref"],
            "quality": "medium",
            "resolution": "1k",
            "ratio": "source",
            "parts": [
                {
                    "part": "part1",
                    "source_storyboard": str(source),
                    "candidate_path": str(self.root / "output/job-001/final-images/part1.png"),
                    "refs_loaded": refs,
                    "prompt_path": str(prompt),
                    "source_risks": [],
                    "required_translations": [],
                    "review": review,
                }
            ],
        }
        contract_path = self.root / "output/job-001/image-batch/codex_imagegen_contract.json"
        contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return manifest, contract_path

    def run_contract_qc(self, manifest, contract):
        out_json = self.root / "contract_qc.json"
        result = subprocess.run(
            [
                "python3",
                str(IMAGEGEN_QC),
                "--root",
                str(self.root),
                "--job-id",
                "job-001",
                "--stage",
                "image_batch_qc",
                "--manifest",
                str(manifest),
                "--contract",
                str(contract),
                "--out-json",
                str(out_json),
                "--out-md",
                str(self.root / "contract_qc.md"),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(out_json.read_text(encoding="utf-8"))

    def test_profile_loader_separates_toner_clay_mask_and_unknown(self):
        toner = build_product_profile(self.root, {"id": "job-001", "product_name": "孔凤春发酵水", "client_profile": "kongfengchun", "notes": ""})
        clay = build_product_profile(self.root, {"id": "job-002", "product_name": "孔凤春清洁泥膜", "client_profile": "kongfengchun", "notes": ""})
        unknown = build_product_profile(self.root, {"id": "job-003", "product_name": "新产品X", "client_profile": "", "notes": ""})

        self.assertIn("category:toner", toner["loaded_rules"])
        self.assertNotIn("category:clay_mask", toner["loaded_rules"])
        self.assertFalse(toner["checks"]["requires_mud_checks"])
        self.assertIn("product_visible_text", toner["review_flags"]["required"])
        self.assertIn("no_blank_label", toner["review_flags"]["required"])
        self.assertIn("primary_identity_only_on_target_role", toner["review_flags"]["required"])
        self.assertNotIn("single_identity", toner["review_flags"]["required"])
        self.assertIn("PORTULACA OLERACEA FERMENTED ESSENCE TONER", toner["visible_text_patterns"])
        self.assertIn("shot_labels", toner["source_storyboard_controls"])
        self.assertNotIn("clay_mask", json.dumps(toner, ensure_ascii=False))
        self.assertIn("category:clay_mask", clay["loaded_rules"])
        self.assertTrue(clay["checks"]["requires_mud_checks"])
        self.assertNotIn("afterwash_face", clay["reference_roles"]["required"])
        self.assertNotIn("afterwash_face", clay["reference_roles"]["optional"])
        self.assertFalse(clay["checks"]["requires_afterwash_ref"])
        self.assertEqual(unknown["category_id"], "unknown")
        self.assertEqual(unknown["loaded_rules"], ["generic:generic_product"])
        self.assertNotIn("clay_mask", json.dumps(unknown, ensure_ascii=False))

    def test_visual_manifest_qc_does_not_require_open_mud_for_toner(self):
        report = self.run_visual_qc(self.write_visual_fixture("孔凤春发酵水", include_open_mud=False))

        self.assertEqual(report["overall"], "PASS")
        open_check = next(item for item in report["checks"] if item["name"] == "product_open_mud_ref_exists")
        self.assertEqual(open_check["status"], "PASS")
        self.assertIn("not required", open_check["detail"])

    def test_visual_manifest_qc_requires_open_mud_for_clay_mask(self):
        report = self.run_visual_qc(self.write_visual_fixture("孔凤春清洁泥膜", include_open_mud=False))

        self.assertEqual(report["overall"], "STOP")
        open_check = next(item for item in report["checks"] if item["name"] == "product_open_mud_ref_exists")
        self.assertEqual(open_check["status"], "STOP")

    def test_visual_manifest_qc_rejects_source_target_gender_mismatch(self):
        manifest_path = self.write_visual_fixture("孔凤春发酵水", include_open_mud=False)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["source_presenter_gender"] = "male"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        report = self.run_visual_qc(manifest_path)

        self.assertEqual(report["overall"], "FAIL")
        gender_check = next(
            item for item in report["checks"] if item["name"] == "presenter_gender_binding"
        )
        self.assertEqual(gender_check["status"], "FAIL")

    def test_gpt_image_contract_qc_uses_toner_refs_and_action(self):
        manifest, contract = self.write_contract_fixture("孔凤春发酵水", include_open_mud=False)
        report = self.run_contract_qc(manifest, contract)

        self.assertEqual(report["overall"], "PASS")
        ref_check = next(item for item in report["checks"] if item["name"] == "part1_required_ref_roles")
        self.assertEqual(ref_check["status"], "PASS")
        self.assertNotIn("product_open_mud", ref_check["detail"])

    def test_gpt_image_contract_accepts_declared_storyboard_derived_first_edit(self):
        manifest, contract = self.write_contract_fixture("孔凤春发酵水", include_open_mud=False)
        self.write_jobs("孔凤春发酵水", person_assets="storyboard_derived")
        role_map = self.root / "output/job-001/visual-assets/role_map.json"
        role_map.parent.mkdir(parents=True, exist_ok=True)
        role_map.write_text(
            json.dumps(
                {
                    "version": 1,
                    "job_id": "job-001",
                    "roles": [
                        {
                            "id": "role_A",
                            "gender": "female",
                            "parts": ["part1"],
                            "source_role": "产品演示者",
                            "identity_required": True,
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        data = json.loads(contract.read_text(encoding="utf-8"))
        data["person_asset_mode"] = "storyboard_derived"
        data["identity_strategy"] = "generate_from_source_roles_then_derive"
        data["reference_order"] = ["source_storyboard", "product_front"]
        part = data["parts"][0]
        part["person_asset_mode"] = "storyboard_derived"
        part["identity_strategy"] = "generate_from_source_roles_then_derive"
        part["role_map"] = str(role_map)
        part["role_map_loaded_to_context"] = True
        part["refs_loaded"].pop("identity_ref")
        part["review"].pop("same_identity_as_reference")
        part["review"].update(
            {
                "new_people_are_photoreal": True,
                "source_role_gender_preserved": True,
                "same_role_repeats_consistently": True,
            }
        )
        contract.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        report = self.run_contract_qc(manifest, contract)

        self.assertEqual(report["overall"], "PASS")
        checks = {item["name"]: item for item in report["checks"]}
        self.assertEqual(checks["part1_storyboard_derived_initial_edit"]["status"], "PASS")
        self.assertNotIn("identity_ref", checks["part1_required_ref_roles"]["detail"])

    def test_gpt_image_contract_accepts_multiple_storyboard_derived_role_refs(self):
        manifest, contract = self.write_contract_fixture("孔凤春发酵水", include_open_mud=False)
        self.write_jobs("孔凤春发酵水", person_assets="storyboard_derived")
        role_a = self.touch("output/job-001/visual-assets/derived-identities/role_A.png", b"A")
        role_d = self.touch("output/job-001/visual-assets/derived-identities/role_D.png", b"D")
        data = json.loads(contract.read_text(encoding="utf-8"))
        data["person_asset_mode"] = "storyboard_derived"
        data["identity_strategy"] = "reuse_storyboard_derived_roles"
        data["reference_order"] = [
            "source_storyboard",
            "product_front",
            "identity_role_A",
            "identity_role_D",
        ]
        part = data["parts"][0]
        part["person_asset_mode"] = "storyboard_derived"
        part["identity_strategy"] = "reuse_storyboard_derived_roles"
        part["refs_loaded"].pop("identity_ref")
        part["refs_loaded"].update(
            {
                "identity_role_A": {
                    "path": str(role_a),
                    "loaded_to_context": True,
                },
                "identity_role_D": {
                    "path": str(role_d),
                    "loaded_to_context": True,
                },
            }
        )
        contract.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        report = self.run_contract_qc(manifest, contract)

        self.assertEqual(report["overall"], "PASS")
        checks = {item["name"]: item for item in report["checks"]}
        self.assertEqual(checks["part1_storyboard_derived_identity_reuse"]["status"], "PASS")
        self.assertEqual(checks["part1_ref_identity_role_A_exists"]["status"], "PASS")
        self.assertEqual(checks["part1_ref_identity_role_D_exists"]["status"], "PASS")

    def test_gpt_image_contract_qc_requires_shot_labels(self):
        manifest, contract = self.write_contract_fixture("孔凤春发酵水", include_open_mud=False)
        data = json.loads(contract.read_text(encoding="utf-8"))
        data["source_storyboard_controls"].remove("shot_labels")
        contract.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        report = self.run_contract_qc(manifest, contract)

        self.assertEqual(report["overall"], "FAIL")
        control_check = next(item for item in report["checks"] if item["name"] == "source_storyboard_controls_contract")
        self.assertIn("shot_labels", control_check["detail"])

    def test_gpt_image_contract_qc_allows_optional_toner_product_ref_before_identity(self):
        manifest, contract = self.write_contract_fixture("孔凤春发酵水", include_open_mud=False)
        open_ref = self.touch("assets/product/open_cap.png")
        data = json.loads(contract.read_text(encoding="utf-8"))
        order = ["source_storyboard", "product_front", "product_open_or_cap", "identity_ref"]
        data["reference_order"] = order
        data["api_effect_baseline"]["reference_order"] = order
        data["parts"][0]["reference_order"] = order
        data["parts"][0]["refs_loaded"]["product_open_or_cap"] = {
            "path": str(open_ref),
            "loaded_to_context": True,
        }
        contract.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        report = self.run_contract_qc(manifest, contract)

        self.assertEqual(report["overall"], "PASS")
        order_check = next(item for item in report["checks"] if item["name"] == "part1_reference_order_matches_api_baseline")
        self.assertEqual(order_check["status"], "PASS")

    def test_gpt_image_contract_qc_requires_toner_visible_label_review(self):
        manifest, contract = self.write_contract_fixture("孔凤春发酵水", include_open_mud=False)
        data = json.loads(contract.read_text(encoding="utf-8"))
        data["parts"][0]["review"].pop("product_visible_text")
        contract.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        report = self.run_contract_qc(manifest, contract)

        self.assertEqual(report["overall"], "FAIL")
        review_check = next(item for item in report["checks"] if item["name"] == "part1_review_required_flags")
        self.assertIn("product_visible_text", review_check["detail"])

    def test_gpt_image_contract_qc_requires_clay_mask_refs(self):
        manifest, contract = self.write_contract_fixture("孔凤春清洁泥膜", include_open_mud=False)
        report = self.run_contract_qc(manifest, contract)

        self.assertEqual(report["overall"], "FAIL")
        ref_check = next(item for item in report["checks"] if item["name"] == "part1_required_ref_roles")
        self.assertIn("product_open_mud", ref_check["detail"])

    def write_pass(self, rel):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"overall": "PASS"}) + "\n", encoding="utf-8")

    def write_runner_visual_fixture(self, product_name):
        from PIL import Image

        job = self.write_jobs(product_name)
        job_dir = self.root / "output/job-001"
        product_dir = self.root / "assets/product"
        identity_dir = self.root / "assets/person"
        source = job_dir / "storyboard_source_refs/source_storyboard_part1.jpg"
        candidate = job_dir / "final-images/part1.png"
        front = product_dir / "front.png"
        open_mud = product_dir / "open_mud.png"
        identity = identity_dir / "identity.png"
        afterwash = identity_dir / "afterwash.png"
        for path, color in (
            (source, "gray"),
            (candidate, "white"),
            (front, "green"),
            (open_mud, "white"),
            (identity, "navy"),
            (afterwash, "lightblue"),
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (400, 600), color).save(path)
        candidate_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
        (product_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "asset_group_type": "product_group",
                    "product_id": "product",
                    "product_name": product_name,
                    "source_assets": str(product_dir),
                    "front_ref": "front.png",
                    "open_mud_ref": "open_mud.png",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (identity_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "asset_group_type": "identity_group",
                    "identity_id": "identity",
                    "presenter_gender": "female",
                    "identity_ref": "identity.png",
                    "afterwash_face_ref": "afterwash.png",
                    "allowed_when": {"person_asset": str(identity_dir)},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        evidence = job_dir / "checks/part1_shot_label_restore.json"
        evidence.write_text(
            json.dumps(
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
                }
            )
            + "\n",
            encoding="utf-8",
        )
        hard_gate = job_dir / "checks/part1_image_hard_gate_qc.json"
        hard_gate.write_text(
            json.dumps(
                {
                    "overall": "PASS",
                    "candidate": str(candidate),
                    "candidate_sha256": candidate_sha,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        manifest = job_dir / "visual-assets/approved_visual_manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "job_id": "job-001",
                    "source_presenter_gender": "female",
                    "target_presenter_gender": "female",
                    "product_group_id": "product",
                    "product_group_manifest": str(product_dir / "manifest.json"),
                    "identity_group_id": "identity",
                    "identity_group_manifest": str(identity_dir / "manifest.json"),
                    "reusable_refs": {
                        "product_front": str(front),
                        "product_open": str(open_mud),
                        "identity_ref": str(identity),
                        "afterwash_face": str(afterwash),
                    },
                    "part_storyboards": {
                        "part1": {
                            "path": str(candidate),
                            "asset_type": "AI改好分镜图",
                            "image_route": "matpool_gpt_image_2_edit",
                            "contains_source_video_pixels": False,
                            "source_reference": str(source),
                            "candidate_sha256": candidate_sha,
                            "hard_gate": str(hard_gate),
                            "shot_label_metadata": {
                                "type": "shot_label_metadata_only",
                                "evidence": str(evidence),
                                "panel_pixels_modified": False,
                            },
                        }
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        contract = {"overall": "PASS", "checks": []}
        attach_input_binding(contract, self.root, [manifest, candidate])
        contract_path = job_dir / "checks/image_batch_qc_codex_imagegen_contract_qc.json"
        contract_path.write_text(json.dumps(contract) + "\n", encoding="utf-8")
        return job

    def test_runner_skincare_progression_requirement_is_profile_driven(self):
        from checker_review_qc import (
            bind_risk_request,
            review_report,
            write_bound_report_json,
        )
        from tests.test_qc_outcomes import write_review

        job = self.write_runner_visual_fixture("孔凤春发酵水")
        checks = "output/job-001/checks"
        decision = {"canonical_stage": "image_batch_qc", "gate": "gates/image_batch_gate.md"}
        args = SimpleNamespace(record_gate_result="PASS", artifact="", dry_run=True)
        plan = build_stage_ledger(self.root, job, "image_batch_qc", write=True)
        bindings = {
            item["name"]: item["fingerprint_hash"]
            for item in plan["semantic_review_request"]["families"]
        }
        review_path = self.root / checks / "image_batch_qc_gate_review.md"
        write_review(review_path, reason="unified toner visual families passed")
        review_path.write_text(
            review_path.read_text(encoding="utf-8")
            .replace("Job: job-test", "Job: job-001")
            + "Family results: "
            + json.dumps({name: "PASS" for name in bindings})
            + "\n",
            encoding="utf-8",
        )
        checker_report = bind_risk_request(
            review_report(review_path),
            self.root / checks / "image_batch_qc_semantic_review_request.json",
            self.root,
        )
        write_bound_report_json(
            checker_report,
            self.root / checks / "image_batch_qc_gate_review_qc.json",
            self.root,
        )

        preflight_pass_recording(self.root, job, decision, args)

        job = self.write_runner_visual_fixture("孔凤春清洁泥膜")
        with self.assertRaisesRegex(ValueError, "skincare_progression"):
            preflight_pass_recording(self.root, job, decision, args)


if __name__ == "__main__":
    unittest.main()
