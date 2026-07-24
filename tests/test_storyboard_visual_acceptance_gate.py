import csv
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from qc_input_binding import attach_input_binding  # noqa: E402
from qc_risk_ledger import build_stage_ledger  # noqa: E402
from tests import test_qc_outcomes as review_fixture  # noqa: E402
from tests import test_storyboard_visual_acceptance as visual_fixture  # noqa: E402


CHECKER_QC = ROOT / "tools" / "checker_review_qc.py"
RUNNER = ROOT / "tools" / "run_next_loop_round.py"


class StoryboardVisualAcceptanceGateTest(unittest.TestCase):
    def setUp(self):
        self.fixture = visual_fixture.StoryboardVisualAcceptanceTest(methodName="runTest")
        self.fixture.setUp()
        self.root = self.fixture.root
        self.job_id = self.fixture.job_id
        self.job_dir = self.fixture.job_dir
        with (self.root / "jobs.csv").open(newline="", encoding="utf-8") as handle:
            self.job = next(csv.DictReader(handle))
        self._write_imagegen_contract_qc()

    def tearDown(self):
        self.fixture.tearDown()

    def _write_imagegen_contract_qc(self):
        path = self.job_dir / "checks/image_batch_qc_codex_imagegen_contract_qc.json"
        report = {"overall": "PASS", "checks": []}
        manifest = self.job_dir / "visual-assets/approved_visual_manifest.json"
        candidates = sorted((self.job_dir / "final-images").glob("*.png"))
        attach_input_binding(report, self.root, [manifest, *candidates])
        path.write_text(json.dumps(report) + "\n", encoding="utf-8")

    def _run_checker(self, family_results, result="PASS", outcome="PASS"):
        review = self.job_dir / "checks/image_batch_qc_gate_review.md"
        request = self.job_dir / "checks/image_batch_qc_semantic_review_request.json"
        out_json = self.job_dir / "checks/image_batch_qc_gate_review_qc.json"
        out_md = self.job_dir / "checks/image_batch_qc_gate_review_qc.md"
        review_fixture.write_review(
            review,
            result=result,
            outcome=outcome,
            reason="one-pass storyboard visual acceptance",
            failed_item="identity_product_material_integrity" if result != "PASS" else "none",
            failure_type="wrong_product" if result == "FAIL" else "none",
            retry_variable="product_reference" if result == "FAIL" else "none",
            needs_confirmation="yes" if result == "STOP" else "false",
        )
        review.write_text(
            review.read_text(encoding="utf-8").replace("Job: job-test", f"Job: {self.job_id}"),
            encoding="utf-8",
        )
        with review.open("a", encoding="utf-8") as handle:
            handle.write("Family results: " + json.dumps(family_results) + "\n")
        return subprocess.run(
            [
                "python3",
                str(CHECKER_QC),
                "--root",
                str(self.root),
                "--review",
                str(review),
                "--risk-request",
                str(request),
                "--out-json",
                str(out_json),
                "--out-md",
                str(out_md),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def _prepare_runner_contract(self):
        for path in (
            self.root / "assets/source.mp4",
            self.root / "gates/image_batch_gate.md",
            self.root / "workers/image_batch_worker.md",
            self.root / "workers/checker_worker.md",
            self.root / "tools/storyboard_visual_acceptance.py",
            self.root / "tools/checker_review_qc.py",
            self.root / "tools/qc_risk_ledger.py",
            self.root / ".codex/agents/viral-replica-checker.toml",
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture\n")
        for name in ("STATE.md", "QC_RULES.md", "LOOP.md"):
            (self.root / name).write_text(f"# {name}\n", encoding="utf-8")
        (self.root / "RUNNER_STATE.json").write_text(
            json.dumps({"version": 1, "retry_limit": 2, "updated_at": None, "jobs": {}})
            + "\n",
            encoding="utf-8",
        )
        (self.root / "COST_POLICY.md").write_text(
            "# Cost Policy\n\n```json\n{}\n```\n",
            encoding="utf-8",
        )
        (self.root / "rules").mkdir(exist_ok=True)
        (self.root / "rules/STAGE_RULES.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "terminal_statuses": ["done", "blocked"],
                    "paid_stage_markers": ["generation_approved", "paid"],
                    "rules": [
                        {
                            "id": "storyboard_passed",
                            "match": {"type": "exact", "status": "storyboard_passed"},
                            "decision": "continue",
                            "canonical_stage": "image_batch_qc",
                            "cost_class": "free_check",
                            "worker": "fixture",
                            "worker_file": "workers/image_batch_worker.md",
                            "script_file": "tools/storyboard_visual_acceptance.py",
                            "action": "Run one-pass storyboard visual acceptance.",
                            "next_expected": "image_qc_passed",
                            "gate": "gates/image_batch_gate.md",
                        }
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        review = self.job_dir / "checks/image_batch_qc_gate_review.md"
        review.write_text("pending checker review\n", encoding="utf-8")
        with (self.root / "jobs.csv").open("w", newline="", encoding="utf-8") as handle:
            fields = [
                "id",
                "status",
                "video_path",
                "product_name",
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
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerow(
                {
                    "id": self.job_id,
                    "status": "storyboard_passed",
                    "video_path": str(self.root / "assets/source.mp4"),
                    "product_name": "Test Product",
                    "product_assets": str(self.root / "assets/product"),
                    "person_assets": str(self.root / "assets/person/person.png"),
                    "audio_assets": "extract_from_original",
                    "target_duration": "30s",
                    "notes": "one-pass fixture",
                    "output_dir": f"output/{self.job_id}",
                    "last_artifact": f"output/{self.job_id}/checks/image_batch_qc_gate_review.md",
                    "next_stage": "image_qc_passed",
                    "needs_user_confirmation": "false",
                }
            )
        with (self.root / "jobs.csv").open(newline="", encoding="utf-8") as handle:
            self.job = next(csv.DictReader(handle))

    def _run_runner(self):
        return subprocess.run(
            [
                "python3",
                str(RUNNER),
                "--root",
                str(self.root),
                "--job-id",
                self.job_id,
                "--record-gate-result",
                "PASS",
                "--artifact",
                f"output/{self.job_id}/checks/image_batch_qc_gate_review.md",
                "--dry-run",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def _accept_all_image_families(self):
        first = build_stage_ledger(self.root, self.job, "image_batch_qc", write=True)
        names = [family["name"] for family in first["semantic_review_request"]["families"]]
        checker = self._run_checker({name: "PASS" for name in names})
        self.assertEqual(checker.returncode, 0, checker.stderr)
        accepted = build_stage_ledger(self.root, self.job, "image_batch_qc", write=True)
        self.assertEqual(accepted["overall"], "PASS")
        return names

    def _write_downstream_sync_evidence(self):
        prompt_dir = self.job_dir / "seedance_web_final/prompts"
        prompt_dir.mkdir(parents=True, exist_ok=True)
        (prompt_dir / "Part1.txt").write_text("prompt\n", encoding="utf-8")
        seedance = self.job_dir / "seedance"
        seedance.mkdir(parents=True, exist_ok=True)
        director_plan = seedance / "director_plan.json"
        director_plan.write_text('{"beats": []}\n', encoding="utf-8")
        (seedance / "handoff_mode.json").write_text('{"mode": "web"}\n', encoding="utf-8")
        material_role = seedance / "seedance_\u7d20\u6750\u89d2\u8272\u8868.md"
        material_role.write_text("roles v1\n", encoding="utf-8")
        manifest = self.job_dir / "visual-assets/approved_visual_manifest.json"
        candidates = sorted((self.job_dir / "final-images").glob("*.png"))
        visual_report = {
            "overall": "PASS",
            "checks": [{"name": "final_upload_dir_exists", "status": "PASS"}],
        }
        attach_input_binding(visual_report, self.root, [manifest, *candidates])
        (self.job_dir / "checks/pre_seedance_pack_visual_asset_manifest_qc.json").write_text(
            json.dumps(visual_report) + "\n",
            encoding="utf-8",
        )
        prompt_report = {
            "overall": "PASS",
            "material_role_path": str(material_role.relative_to(self.root)),
        }
        attach_input_binding(
            prompt_report,
            self.root,
            [
                director_plan,
                material_role,
                prompt_dir,
                self.job_dir / "product_profile.json",
            ],
        )
        (self.job_dir / "checks/pre_seedance_pack_seedance_prompt_contract_qc.json").write_text(
            json.dumps(prompt_report) + "\n",
            encoding="utf-8",
        )
        return material_role

    def test_changed_mult_part_skincare_gate_uses_one_checker_for_all_visual_families(self):
        first = build_stage_ledger(
            self.root,
            self.job,
            "image_batch_qc",
            write=True,
        )

        request = first["semantic_review_request"]
        family_names = [family["name"] for family in request["families"]]
        self.assertEqual(first["overall"], "STOP")
        self.assertEqual(
            family_names,
            [
                "geometry_appearance",
                "identity_product_material_integrity",
                "cross_part_continuity",
                "skincare_progression",
            ],
        )
        self.assertEqual(request["request_type"], "storyboard_visual_acceptance")
        self.assertEqual(request["mode"], "active")
        self.assertEqual(request["invocation_count"], 1)
        self.assertEqual(request["canonical_compare_context"]["item_count"], 9)

        checker = self._run_checker({name: "PASS" for name in family_names})
        self.assertEqual(checker.returncode, 0, checker.stderr)
        second = build_stage_ledger(
            self.root,
            self.job,
            "image_batch_qc",
            write=True,
        )

        self.assertEqual(second["overall"], "PASS")
        self.assertFalse(second["semantic_review_request"]["required"])
        self.assertEqual(second["semantic_review_request"]["invocation_count"], 0)
        for name in family_names:
            self.assertEqual(second["families"][name]["status"], "PASS")

    def test_mixed_checker_result_fails_only_the_named_family_and_keeps_retry_scope(self):
        first = build_stage_ledger(self.root, self.job, "image_batch_qc", write=True)
        names = [family["name"] for family in first["semantic_review_request"]["families"]]
        results = {name: "PASS" for name in names}
        results["identity_product_material_integrity"] = "FAIL"

        checker = self._run_checker(results, result="FAIL", outcome="HARD_FAILURE")
        self.assertEqual(checker.returncode, 0, checker.stderr)
        second = build_stage_ledger(self.root, self.job, "image_batch_qc", write=True)

        self.assertEqual(second["overall"], "FAIL")
        self.assertFalse(second["semantic_review_request"]["required"])
        self.assertEqual(
            second["families"]["identity_product_material_integrity"]["status"],
            "FAIL",
        )
        self.assertEqual(
            second["families"]["identity_product_material_integrity"]["retry_scope"][
                "retry_variable"
            ],
            "product_reference",
        )
        for name in set(names) - {"identity_product_material_integrity"}:
            self.assertEqual(second["families"][name]["status"], "PASS")

    def test_checker_evidence_stop_cannot_record_gate_pass(self):
        first = build_stage_ledger(self.root, self.job, "image_batch_qc", write=True)
        names = [family["name"] for family in first["semantic_review_request"]["families"]]
        results = {name: "PASS" for name in names}
        results["geometry_appearance"] = "STOP"

        checker = self._run_checker(results, result="STOP", outcome="EVIDENCE_STOP")
        self.assertEqual(checker.returncode, 0, checker.stderr)
        second = build_stage_ledger(self.root, self.job, "image_batch_qc", write=True)

        self.assertEqual(second["overall"], "STOP")
        self.assertFalse(second["semantic_review_request"]["required"])
        self.assertEqual(second["families"]["geometry_appearance"]["status"], "STOP")

    def test_incomplete_top_level_pass_cannot_satisfy_unified_checker_binding(self):
        first = build_stage_ledger(self.root, self.job, "image_batch_qc", write=True)
        fingerprints = {
            family["name"]: family["fingerprint_hash"]
            for family in first["semantic_review_request"]["families"]
        }
        (self.job_dir / "checks/image_batch_qc_gate_review_qc.json").write_text(
            json.dumps(
                {
                    "overall": "PASS",
                    "qc_risk_review": {"family_fingerprints": fingerprints},
                }
            )
            + "\n",
            encoding="utf-8",
        )

        rejected = build_stage_ledger(self.root, self.job, "image_batch_qc", write=False)

        self.assertEqual(rejected["overall"], "STOP")
        self.assertEqual(
            [item["name"] for item in rejected["semantic_review_request"]["families"]],
            list(fingerprints),
        )

    def test_runner_refuses_pass_until_the_single_unified_checker_result_is_bound(self):
        self._prepare_runner_contract()

        before_checker = self._run_runner()

        self.assertNotEqual(before_checker.returncode, 0)
        self.assertIn("semantic review required", before_checker.stderr)
        self.assertFalse(
            (self.job_dir / "checks/image_batch_qc_semantic_review_request.json").exists()
        )
        build_stage_ledger(self.root, self.job, "image_batch_qc", write=True)
        request = json.loads(
            (self.job_dir / "checks/image_batch_qc_semantic_review_request.json").read_text(
                encoding="utf-8"
            )
        )
        names = [family["name"] for family in request["families"]]
        checker = self._run_checker({name: "PASS" for name in names})
        self.assertEqual(checker.returncode, 0, checker.stderr)

        after_checker = self._run_runner()

        self.assertEqual(after_checker.returncode, 0, after_checker.stderr)
        self.assertEqual(request["invocation_count"], 1)

    def test_unchanged_visual_state_reuses_every_family_without_request_or_compare_regeneration(self):
        first = build_stage_ledger(self.root, self.job, "image_batch_qc", write=True)
        names = [family["name"] for family in first["semantic_review_request"]["families"]]
        checker = self._run_checker({name: "PASS" for name in names})
        self.assertEqual(checker.returncode, 0, checker.stderr)
        accepted = build_stage_ledger(self.root, self.job, "image_batch_qc", write=True)
        self.assertEqual(accepted["overall"], "PASS")
        compare = self.job_dir / "checks/storyboard_visual_acceptance_compare.jpg"
        os.utime(compare, ns=(1_000_000_000, 1_000_000_000))

        replay = build_stage_ledger(self.root, self.job, "image_batch_qc", write=True)

        self.assertEqual(replay["overall"], "PASS")
        self.assertEqual(replay["semantic_review_request"]["invocation_count"], 0)
        self.assertFalse(
            (self.job_dir / "checks/image_batch_qc_semantic_review_request.json").exists()
        )
        self.assertEqual(compare.stat().st_mtime_ns, 1_000_000_000)
        for name in names:
            self.assertEqual(replay["families"][name]["status"], "REUSED_PASS")
        self.assertEqual(replay["metrics"]["compare_generation_count"], 0)
        self.assertEqual(replay["metrics"]["semantic_request_count"], 0)
        self.assertEqual(replay["metrics"]["checker_invocation_count"], 0)
        self.assertEqual(replay["metrics"]["requested_family_count"], 0)
        self.assertEqual(replay["metrics"]["reused_family_count"], 4)
        self.assertGreaterEqual(replay["metrics"]["active_seconds"], 0)
        self.assertGreaterEqual(replay["metrics"]["wait_seconds"], 0)

    def test_downstream_state_does_not_force_unchanged_compare_regeneration(self):
        names = self._accept_all_image_families()
        compare = self.job_dir / "checks/storyboard_visual_acceptance_compare.jpg"
        os.utime(compare, ns=(1_000_000_000, 1_000_000_000))
        build_stage_ledger(self.root, self.job, "pre_seedance_pack", write=True)

        replay = build_stage_ledger(self.root, self.job, "image_batch_qc", write=True)

        self.assertEqual(replay["overall"], "PASS")
        self.assertEqual(replay["metrics"]["compare_generation_count"], 0)
        self.assertEqual(compare.stat().st_mtime_ns, 1_000_000_000)
        for name in names:
            self.assertEqual(replay["families"][name]["status"], "REUSED_PASS")

    def test_product_reference_change_reopens_only_integrity_family(self):
        first = build_stage_ledger(self.root, self.job, "image_batch_qc", write=True)
        names = [family["name"] for family in first["semantic_review_request"]["families"]]
        checker = self._run_checker({name: "PASS" for name in names})
        self.assertEqual(checker.returncode, 0, checker.stderr)
        accepted = build_stage_ledger(self.root, self.job, "image_batch_qc", write=True)
        self.assertEqual(accepted["overall"], "PASS")
        self.fixture._write_image(
            self.root / "output/shared/product/front.png",
            (80, 140),
            "red",
        )

        changed = build_stage_ledger(self.root, self.job, "image_batch_qc", write=True)

        requested = [
            family["name"]
            for family in changed["semantic_review_request"]["families"]
        ]
        self.assertEqual(requested, ["identity_product_material_integrity"])
        self.assertEqual(changed["semantic_review_request"]["invocation_count"], 1)
        for name in set(names) - {"identity_product_material_integrity"}:
            self.assertEqual(changed["families"][name]["status"], "REUSED_PASS")

    def test_localized_repair_preserves_passes_from_a_mixed_result(self):
        first = build_stage_ledger(self.root, self.job, "image_batch_qc", write=True)
        names = [family["name"] for family in first["semantic_review_request"]["families"]]
        results = {name: "PASS" for name in names}
        results["identity_product_material_integrity"] = "FAIL"
        checker = self._run_checker(results, result="FAIL", outcome="HARD_FAILURE")
        self.assertEqual(checker.returncode, 0, checker.stderr)
        failed = build_stage_ledger(self.root, self.job, "image_batch_qc", write=True)
        self.assertEqual(failed["overall"], "FAIL")
        self.fixture._write_image(
            self.root / "output/shared/product/front.png",
            (80, 140),
            "red",
        )

        repaired = build_stage_ledger(self.root, self.job, "image_batch_qc", write=True)

        self.assertEqual(
            [family["name"] for family in repaired["semantic_review_request"]["families"]],
            ["identity_product_material_integrity"],
        )
        for name in set(names) - {"identity_product_material_integrity"}:
            self.assertEqual(repaired["families"][name]["status"], "REUSED_PASS")

        checker = self._run_checker(
            {"identity_product_material_integrity": "PASS"}
        )
        self.assertEqual(checker.returncode, 0, checker.stderr)
        accepted = build_stage_ledger(self.root, self.job, "image_batch_qc", write=True)

        self.assertEqual(accepted["overall"], "PASS")
        self.assertFalse(accepted["semantic_review_request"]["required"])
        for name in set(names) - {"identity_product_material_integrity"}:
            self.assertEqual(accepted["families"][name]["status"], "REUSED_PASS")

    def test_user_visible_defect_invalidates_only_its_named_family(self):
        first = build_stage_ledger(self.root, self.job, "image_batch_qc", write=True)
        names = [family["name"] for family in first["semantic_review_request"]["families"]]
        checker = self._run_checker({name: "PASS" for name in names})
        self.assertEqual(checker.returncode, 0, checker.stderr)
        accepted = build_stage_ledger(self.root, self.job, "image_batch_qc", write=True)
        self.assertEqual(accepted["overall"], "PASS")
        defect_path = self.job_dir / "checks/user_visible_defects.json"
        defect_path.write_text(
            json.dumps(
                {
                    "defects": [
                        {
                            "status": "open",
                            "family": "identity_product_material_integrity",
                            "part": "part1",
                            "issue": "wrong product label",
                        }
                    ]
                }
            )
            + "\n",
            encoding="utf-8",
        )

        invalidated = build_stage_ledger(self.root, self.job, "image_batch_qc", write=True)

        self.assertEqual(invalidated["overall"], "FAIL")
        self.assertEqual(
            invalidated["families"]["identity_product_material_integrity"]["status"],
            "FAIL",
        )
        for name in set(names) - {"identity_product_material_integrity"}:
            self.assertEqual(invalidated["families"][name]["status"], "REUSED_PASS")

    def test_pre_seedance_reuses_unified_visual_pass_without_visual_request(self):
        names = self._accept_all_image_families()

        downstream = build_stage_ledger(
            self.root,
            self.job,
            "pre_seedance_pack",
            write=True,
        )

        requested = {
            family["name"]
            for family in downstream["semantic_review_request"]["families"]
        }
        self.assertTrue(requested.isdisjoint(names))
        for name in names:
            self.assertEqual(downstream["families"][name]["status"], "REUSED_PASS")

    def test_downstream_unified_pass_does_not_require_legacy_visual_contracts(self):
        self._accept_all_image_families()

        downstream = build_stage_ledger(
            self.root,
            self.job,
            "pre_seedance_pack",
            write=True,
        )

        self.assertNotIn("visual_contracts", downstream["families"])
        evidence_names = {
            item.get("name")
            for family in downstream["families"].values()
            for item in family.get("evidence") or []
        }
        self.assertTrue(
            evidence_names.isdisjoint(
                {"storyboard_geometry", "cross_part_continuity", "skincare_progression"}
            )
        )

    def test_single_part_non_skincare_downstream_reuses_selected_families_only(self):
        profile_path = self.job_dir / "product_profile.json"
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        profile["checks"]["requires_skincare_progression"] = False
        profile_path.write_text(json.dumps(profile) + "\n", encoding="utf-8")
        manifest_path = self.job_dir / "visual-assets/approved_visual_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["part_storyboards"].pop("part2")
        manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        self._write_imagegen_contract_qc()
        names = self._accept_all_image_families()

        downstream = build_stage_ledger(
            self.root,
            self.job,
            "pre_seedance_pack",
            write=True,
        )

        self.assertEqual(
            names,
            ["geometry_appearance", "identity_product_material_integrity"],
        )
        self.assertNotIn("visual_integrity", downstream["families"])
        self.assertNotIn("visual_contracts", downstream["families"])
        for name in names:
            self.assertEqual(downstream["families"][name]["status"], "REUSED_PASS")

    def test_changed_storyboard_source_invalidates_downstream_visual_reuse(self):
        names = self._accept_all_image_families()
        source = self.job_dir / "storyboard_source_refs/source_storyboard_part1.jpg"
        self.fixture._write_image(source, (400, 600), "black")

        downstream = build_stage_ledger(
            self.root,
            self.job,
            "pre_seedance_pack",
            write=True,
        )

        self.assertEqual(
            downstream["families"]["geometry_appearance"]["status"],
            "STOP",
        )
        self.assertNotEqual(
            downstream["families"]["geometry_appearance"]["fingerprint_hash"],
            "",
        )
        self.assertIn("geometry_appearance", names)

    def test_missing_immutable_checker_evidence_blocks_downstream_reuse(self):
        names = self._accept_all_image_families()
        state = json.loads(
            (self.job_dir / "checks/qc_risk_ledger_state.json").read_text(
                encoding="utf-8"
            )
        )
        evidence_paths = {
            self.root / item["path"]
            for name in names
            for item in state["families"][name]["evidence"]
        }
        for path in evidence_paths:
            path.unlink()

        downstream = build_stage_ledger(
            self.root,
            self.job,
            "pre_seedance_pack",
            write=True,
        )

        for name in names:
            self.assertEqual(downstream["families"][name]["status"], "STOP")

    def test_read_only_image_ledger_does_not_write_acceptance_artifacts(self):
        checks = self.job_dir / "checks"
        paths = [
            checks / "image_batch_qc_storyboard_visual_acceptance.json",
            checks / "image_batch_qc_semantic_review_request.json",
            checks / "storyboard_visual_acceptance_compare.jpg",
            checks / "image_batch_qc_qc_risk_ledger.json",
            checks / "qc_risk_ledger_state.json",
        ]

        ledger = build_stage_ledger(
            self.root,
            self.job,
            "image_batch_qc",
            write=False,
        )

        self.assertEqual(ledger["overall"], "STOP")
        self.assertTrue(ledger["semantic_review_request"]["required"])
        self.assertTrue(all(not path.exists() for path in paths))

    def test_changed_material_role_blocks_downstream_sync_without_reopening_visual_families(self):
        names = self._accept_all_image_families()
        material_role = self._write_downstream_sync_evidence()
        initial = build_stage_ledger(
            self.root,
            self.job,
            "pre_seedance_pack",
            write=True,
        )
        self.assertEqual(initial["families"]["generation_pack_consistency"]["status"], "PASS")
        material_role.write_text("roles v2\n", encoding="utf-8")

        changed = build_stage_ledger(
            self.root,
            self.job,
            "pre_seedance_pack",
            write=True,
        )

        self.assertEqual(changed["overall"], "STOP")
        self.assertEqual(
            changed["families"]["generation_pack_consistency"]["status"],
            "STOP",
        )
        for name in names:
            self.assertEqual(changed["families"][name]["status"], "REUSED_PASS")


if __name__ == "__main__":
    unittest.main()
