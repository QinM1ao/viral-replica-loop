import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from hash_gated_visual_qc import record_snapshot  # noqa: E402
from qc_input_binding import attach_input_binding  # noqa: E402
from qc_risk_ledger import (  # noqa: E402
    build_stage_ledger,
    evaluate_risk_families,
    handoff_mode,
    ledger_failure_message,
)


class QcRiskLedgerTest(unittest.TestCase):
    def test_unchanged_semantic_family_reuses_pass_without_checker(self):
        previous = {
            "families": {
                "visual_integrity": {
                    "status": "PASS",
                    "fingerprint_hash": "95bd805aa49304b3491e4fa1d12496cec83c9f8f0c060aa90c53f060a0dc8f0c",
                    "evidence": [{"path": "checks/visual.json", "sha256": "old-pass"}],
                }
            }
        }

        ledger = evaluate_risk_families(
            job_id="job-001",
            stage="pre_seedance_pack",
            families=[
                {
                    "name": "visual_integrity",
                    "kind": "semantic",
                    "fingerprint": {"image": "abc"},
                    "reuse_evidence_valid": True,
                    "evidence": [],
                }
            ],
            previous=previous,
        )

        self.assertEqual(ledger["overall"], "PASS")
        self.assertEqual(ledger["families"]["visual_integrity"]["status"], "REUSED_PASS")
        self.assertEqual(ledger["semantic_review_request"]["families"], [])

    def test_changed_semantic_families_share_one_review_request(self):
        ledger = evaluate_risk_families(
            job_id="job-001",
            stage="pre_seedance_pack",
            families=[
                {
                    "name": "visual_integrity",
                    "kind": "semantic",
                    "fingerprint": {"image": "changed"},
                    "reuse_evidence_valid": False,
                },
                {
                    "name": "source_to_generation_fidelity",
                    "kind": "semantic",
                    "fingerprint": {"director_plan": "new"},
                    "reuse_evidence_valid": False,
                },
            ],
            previous={"families": {}},
        )

        request = ledger["semantic_review_request"]
        self.assertTrue(request["required"])
        self.assertEqual(request["invocation_count"], 1)
        self.assertEqual(
            [family["name"] for family in request["families"]],
            ["visual_integrity", "source_to_generation_fidelity"],
        )

    def test_unchanged_semantic_request_keeps_stable_created_at_and_file_hash(self):
        families = [
            {
                "name": "finishing_story_integrity",
                "kind": "semantic",
                "fingerprint": {"final_video": "same"},
                "reuse_evidence_valid": False,
            }
        ]
        first = evaluate_risk_families(
            job_id="job-001",
            stage="finishing",
            families=families,
            previous={"families": {}},
        )
        first["semantic_review_request"]["created_at"] = "2000-01-01T00:00:00"

        second = evaluate_risk_families(
            job_id="job-001",
            stage="finishing",
            families=families,
            previous=first,
        )

        self.assertEqual(
            second["semantic_review_request"]["request_id"],
            first["semantic_review_request"]["request_id"],
        )
        self.assertEqual(
            second["semantic_review_request"]["created_at"],
            "2000-01-01T00:00:00",
        )

    def test_changed_deterministic_family_passes_from_program_evidence(self):
        ledger = evaluate_risk_families(
            job_id="job-001",
            stage="pre_seedance_pack",
            families=[
                {
                    "name": "generation_pack_consistency",
                    "kind": "deterministic",
                    "fingerprint": {"prompt": "new"},
                    "reuse_evidence_valid": False,
                    "active_seconds": 0.12,
                    "wait_seconds": 1.5,
                    "evidence": [
                        {"name": "prompt_contract", "status": "PASS", "path": "checks/prompt.json"},
                        {"name": "audio_duration", "status": "PASS", "path": "checks/audio.json"},
                    ],
                }
            ],
        )

        self.assertEqual(ledger["overall"], "PASS")
        self.assertEqual(
            ledger["families"]["generation_pack_consistency"]["status"],
            "PASS",
        )
        self.assertFalse(ledger["semantic_review_request"]["required"])
        self.assertEqual(
            ledger["families"]["generation_pack_consistency"]["decision_trace"],
            {
                "active_seconds": 0.12,
                "wait_seconds": 1.5,
                "decision": "PASS",
                "reason": "all deterministic evidence passed",
            },
        )

    def test_semantic_family_accepts_only_review_bound_to_current_fingerprint(self):
        ledger = evaluate_risk_families(
            job_id="job-001",
            stage="pre_seedance_pack",
            families=[
                {
                    "name": "source_to_generation_fidelity",
                    "kind": "semantic",
                    "fingerprint": {"director_plan": "new"},
                    "reuse_evidence_valid": False,
                    "evidence": [
                        {
                            "name": "batched_checker_review",
                            "status": "PASS",
                            "fingerprint_hash": "8bc77a57bc9451fe6df7843f86a8f70b624ad5adf8f4b0f04c75e90d67896af6",
                            "path": "checks/pre_seedance_pack_gate_review_qc.json",
                        }
                    ],
                }
            ],
        )

        self.assertEqual(ledger["overall"], "PASS")
        self.assertEqual(
            ledger["families"]["source_to_generation_fidelity"]["status"],
            "PASS",
        )
        self.assertFalse(ledger["semantic_review_request"]["required"])

    def test_bound_semantic_fail_is_final_and_does_not_request_another_review(self):
        ledger = evaluate_risk_families(
            job_id="job-001",
            stage="pre_seedance_pack",
            families=[
                {
                    "name": "source_to_generation_fidelity",
                    "kind": "semantic",
                    "fingerprint": {"director_plan": "new"},
                    "reuse_evidence_valid": False,
                    "evidence": [
                        {
                            "name": "batched_checker_review",
                            "status": "FAIL",
                            "fingerprint_hash": "8bc77a57bc9451fe6df7843f86a8f70b624ad5adf8f4b0f04c75e90d67896af6",
                            "path": "checks/pre_seedance_pack_gate_review_qc.json",
                        }
                    ],
                }
            ],
        )

        self.assertEqual(ledger["overall"], "FAIL")
        self.assertFalse(ledger["semantic_review_request"]["required"])

    def test_user_visible_defect_invalidates_only_its_scoped_family(self):
        previous = {
            "families": {
                "visual_integrity": {
                    "status": "PASS",
                    "fingerprint_hash": "95bd805aa49304b3491e4fa1d12496cec83c9f8f0c060aa90c53f060a0dc8f0c",
                },
                "generation_pack_consistency": {
                    "status": "PASS",
                    "fingerprint_hash": "a6ead125e7320e05ba39ff7f0b1d290b6cb109b3cbaeb9a0728f1e637cb189be",
                },
            }
        }
        ledger = evaluate_risk_families(
            job_id="job-001",
            stage="pre_seedance_pack",
            families=[
                {
                    "name": "visual_integrity",
                    "kind": "semantic",
                    "fingerprint": {"image": "abc"},
                    "reuse_evidence_valid": True,
                    "defects": [{"part": "Part1", "shot": "Shot 02", "issue": "wrong action"}],
                },
                {
                    "name": "generation_pack_consistency",
                    "kind": "deterministic",
                    "fingerprint": {"prompt": "unchanged"},
                    "reuse_evidence_valid": True,
                },
            ],
            previous=previous,
        )

        self.assertEqual(ledger["overall"], "FAIL")
        self.assertEqual(ledger["families"]["visual_integrity"]["status"], "FAIL")
        self.assertEqual(
            ledger["families"]["visual_integrity"]["defect_scopes"][0]["shot"],
            "Shot 02",
        )
        self.assertEqual(
            ledger["families"]["generation_pack_consistency"]["status"],
            "REUSED_PASS",
        )

    def test_failure_message_reports_semantic_and_all_deterministic_blockers_together(self):
        ledger = {
            "semantic_review_request": {
                "required": True,
                "families": [{"name": "source_to_generation_fidelity"}],
            },
            "families": {
                "generation_pack_consistency": {
                    "evidence": [
                        {"name": "seedance_prompt_contract", "status": "STOP"},
                        {"name": "audio_duration", "status": "FAIL"},
                    ]
                }
            },
        }

        message = ledger_failure_message(ledger)

        self.assertIn("source_to_generation_fidelity", message)
        self.assertIn("missing passing Seedance prompt contract QC", message)
        self.assertIn("no passing audio duration QC", message)


class QcRiskLedgerAdapterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.job_id = "job-001"
        self.job_dir = self.root / "output" / self.job_id
        (self.job_dir / "checks").mkdir(parents=True)
        (self.job_dir / "visual-assets").mkdir(parents=True)
        (self.job_dir / "seedance_web_final" / "prompts").mkdir(parents=True)
        (self.job_dir / "seedance").mkdir(parents=True)
        (self.root / "rules").mkdir()
        self.write_json(
            self.job_dir / "visual-assets" / "approved_visual_manifest.json",
            {
                "job_id": self.job_id,
                "product_group_id": "product-a",
                "identity_group_id": "identity-a",
                "part_storyboards": {},
            },
        )
        for name in (
            "image_batch_qc_storyboard_geometry_qc.json",
            "image_batch_qc_cross_part_continuity_qc.json",
        ):
            self.write_json(self.job_dir / "checks" / name, {"overall": "PASS"})
        record_snapshot(self.root, self.job_id, write=True)

        self.write_json(
            self.job_dir / "checks" / "pre_seedance_pack_visual_asset_manifest_qc.json",
            {
                "overall": "PASS",
                "checks": [{"name": "final_upload_dir_exists", "status": "PASS"}],
            },
        )
        self.write_json(
            self.job_dir / "checks" / "pre_seedance_pack_seedance_prompt_contract_qc.json",
            {"overall": "PASS"},
        )
        self.write_json(self.job_dir / "seedance" / "handoff_mode.json", {"mode": "web"})
        self.write_json(self.job_dir / "seedance" / "director_plan.json", {"beats": ["new"]})
        self.write_json(
            self.job_dir / "product_profile.json",
            {"job_id": self.job_id, "product_name": "generic", "checks": {}},
        )
        (self.job_dir / "seedance_web_final" / "prompts" / "Part1.txt").write_text(
            "new prompt\n",
            encoding="utf-8",
        )
        # Program reports are produced after their current inputs.
        self.write_json(
            self.job_dir / "checks" / "pre_seedance_pack_visual_asset_manifest_qc.json",
            {
                "overall": "PASS",
                "checks": [{"name": "final_upload_dir_exists", "status": "PASS"}],
            },
        )
        self.write_json(
            self.job_dir / "checks" / "pre_seedance_pack_seedance_prompt_contract_qc.json",
            {"overall": "PASS"},
        )
        manifest = self.job_dir / "visual-assets" / "approved_visual_manifest.json"
        for name in (
            "image_batch_qc_storyboard_geometry_qc.json",
            "image_batch_qc_cross_part_continuity_qc.json",
            "pre_seedance_pack_visual_asset_manifest_qc.json",
        ):
            self.bind_report(self.job_dir / "checks" / name, [manifest])
        self.bind_prompt_report()
        record_snapshot(self.root, self.job_id, write=True)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def write_json(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value) + "\n", encoding="utf-8")

    def bind_report(self, path, inputs):
        report = json.loads(path.read_text(encoding="utf-8"))
        attach_input_binding(report, self.root, inputs)
        self.write_json(path, report)

    def bind_prompt_report(self):
        self.bind_report(
            self.job_dir / "checks" / "pre_seedance_pack_seedance_prompt_contract_qc.json",
            [
                self.job_dir / "seedance" / "director_plan.json",
                self.job_dir / "seedance_web_final" / "prompts",
                self.job_dir / "product_profile.json",
            ],
        )

    def test_downstream_plan_reuses_visual_before_requesting_checker(self):
        ledger = build_stage_ledger(
            self.root,
            {"id": self.job_id, "product_name": "generic"},
            "pre_seedance_pack",
            write=False,
        )

        self.assertEqual(ledger["families"]["visual_integrity"]["status"], "REUSED_PASS")
        self.assertEqual(
            [family["name"] for family in ledger["semantic_review_request"]["families"]],
            ["source_to_generation_fidelity"],
        )

    def test_pre_seedance_source_review_request_lists_every_line_edit(self):
        self.write_json(
            self.job_dir / "seedance" / "director_plan.json",
            {
                "parts": [
                    {
                        "id": "part3",
                        "speech_groups": [
                            {
                                "id": "speech_p3_02",
                                "line": "我反正老是素颜出门",
                                "line_edits": [
                                    {
                                        "kind": "replace",
                                        "from": "血气很充足的样子",
                                        "to": "皮肤很水润",
                                        "reason": "product_fact",
                                        "reason_detail": "Replace the unsupported result only.",
                                        "fact_evidence": {"source": "product_profile"},
                                    }
                                ],
                            }
                        ],
                    }
                ]
            },
        )
        self.bind_prompt_report()

        ledger = build_stage_ledger(
            self.root,
            {"id": self.job_id, "product_name": "generic"},
            "pre_seedance_pack",
            write=False,
        )

        source_family = next(
            family
            for family in ledger["semantic_review_request"]["families"]
            if family["name"] == "source_to_generation_fidelity"
        )
        self.assertEqual(
            source_family["scope"]["line_edit_audit"],
            [
                {
                    "id": "part3:speech_p3_02:1",
                    "part_id": "part3",
                    "speech_group_id": "speech_p3_02",
                    "edit_index": 1,
                    "source_line": "",
                    "target_line": "我反正老是素颜出门",
                    "kind": "replace",
                    "from": "血气很充足的样子",
                    "to": "皮肤很水润",
                    "reason": "product_fact",
                    "reason_detail": "Replace the unsupported result only.",
                    "evidence": {
                        "fact_evidence": {"source": "product_profile"}
                    },
                }
            ],
        )

    def test_source_blueprint_requests_source_review_without_visual_manifest_contracts(self):
        (self.job_dir / "剧情分析").mkdir(exist_ok=True)
        self.write_json(
            self.job_dir / "剧情分析" / "source_rhythm.json",
            {"schema_version": 3, "beats": [{"id": "sr001"}]},
        )
        self.write_json(
            self.job_dir / "checks" / "source_blueprint_report.json",
            {"overall": "PASS"},
        )
        self.write_json(
            self.job_dir / "checks" / "source_rhythm_qc.json",
            {"overall": "PASS"},
        )

        ledger = build_stage_ledger(
            self.root,
            {"id": self.job_id, "product_name": "generic"},
            "source_blueprint",
            write=False,
        )

        self.assertEqual(
            set(ledger["families"]),
            {"source_fact_contracts", "source_fidelity"},
        )
        self.assertEqual(
            [family["name"] for family in ledger["semantic_review_request"]["families"]],
            ["source_fidelity"],
        )
        self.assertNotIn("visual_integrity", ledger["families"])

    def test_missing_handoff_mode_infers_one_consumer_instead_of_both(self):
        self.assertEqual(
            handoff_mode(self.root, {"id": "missing", "status": "generation_approved"}),
            "api",
        )
        self.assertEqual(
            handoff_mode(self.root, {"id": "missing", "status": "image_qc_passed"}),
            "web",
        )

    def test_missing_visual_manifest_becomes_aggregated_stop_instead_of_exception(self):
        missing_job = "job-missing"
        (self.root / "output" / missing_job / "checks").mkdir(parents=True)

        ledger = build_stage_ledger(
            self.root,
            {"id": missing_job, "product_name": "generic", "handoff_mode": "web"},
            "pre_seedance_pack",
            write=False,
        )

        self.assertEqual(ledger["overall"], "STOP")
        message = ledger_failure_message(ledger)
        self.assertIn("missing approved visual manifest", message)
        self.assertIn("missing passing Seedance prompt contract QC", message)

    def bind_current_review(self, plan, status="PASS"):
        requested = {
            item["name"]: item["fingerprint_hash"]
            for item in plan["semantic_review_request"]["families"]
        }
        self.write_json(
            self.job_dir / "checks" / "pre_seedance_pack_gate_review_qc.json",
            {
                "overall": status,
                "qc_risk_review": {"family_fingerprints": requested},
            },
        )

    def bind_family_review(self, plan, family_results):
        requested = {
            item["name"]: item["fingerprint_hash"]
            for item in plan["semantic_review_request"]["families"]
        }
        self.write_json(
            self.job_dir / "checks" / "pre_seedance_pack_gate_review_qc.json",
            {
                "overall": "FAIL" if "FAIL" in family_results.values() else "PASS",
                "qc_risk_review": {
                    "family_fingerprints": requested,
                    "family_results": family_results,
                },
            },
        )

    def test_unbound_legacy_checker_cannot_bootstrap_changed_semantics(self):
        self.write_json(
            self.job_dir / "checks" / "pre_seedance_pack_gate_review_qc.json",
            {"overall": "PASS"},
        )

        ledger = build_stage_ledger(
            self.root,
            {"id": self.job_id, "product_name": "generic"},
            "pre_seedance_pack",
            write=False,
        )

        self.assertEqual(ledger["overall"], "STOP")
        self.assertEqual(
            [item["name"] for item in ledger["semantic_review_request"]["families"]],
            ["source_to_generation_fidelity"],
        )

    def test_one_bound_checker_pass_then_next_run_reuses_it(self):
        plan = build_stage_ledger(
            self.root,
            {"id": self.job_id, "product_name": "generic"},
            "pre_seedance_pack",
            write=True,
        )
        self.bind_current_review(plan)

        first = build_stage_ledger(
            self.root,
            {"id": self.job_id, "product_name": "generic"},
            "pre_seedance_pack",
            write=True,
        )
        second = build_stage_ledger(
            self.root,
            {"id": self.job_id, "product_name": "generic"},
            "pre_seedance_pack",
            write=False,
        )

        self.assertEqual(first["overall"], "PASS")
        self.assertEqual(
            first["families"]["source_to_generation_fidelity"]["status"],
            "PASS",
        )
        self.assertEqual(second["families"]["visual_integrity"]["status"], "REUSED_PASS")
        self.assertEqual(
            second["families"]["source_to_generation_fidelity"]["status"],
            "REUSED_PASS",
        )
        self.assertEqual(second["semantic_review_request"]["invocation_count"], 0)

    def test_bound_checker_fail_is_preserved_without_another_request(self):
        plan = build_stage_ledger(
            self.root,
            {"id": self.job_id, "product_name": "generic"},
            "pre_seedance_pack",
            write=True,
        )
        self.bind_current_review(plan, status="FAIL")

        checked = build_stage_ledger(
            self.root,
            {"id": self.job_id, "product_name": "generic"},
            "pre_seedance_pack",
            write=False,
        )

        self.assertEqual(checked["overall"], "FAIL")
        self.assertFalse(checked["semantic_review_request"]["required"])

    def test_changed_input_rejects_stale_deterministic_report(self):
        plan = build_stage_ledger(
            self.root,
            {"id": self.job_id, "product_name": "generic"},
            "pre_seedance_pack",
            write=True,
        )
        self.bind_current_review(plan)
        passed = build_stage_ledger(
            self.root,
            {"id": self.job_id, "product_name": "generic"},
            "pre_seedance_pack",
            write=True,
        )
        self.assertEqual(passed["overall"], "PASS")

        self.write_json(
            self.job_dir / "seedance" / "director_plan.json",
            {"beats": ["changed-after-qc"]},
        )
        stale = build_stage_ledger(
            self.root,
            {"id": self.job_id, "product_name": "generic"},
            "pre_seedance_pack",
            write=False,
        )

        pack = stale["families"]["generation_pack_consistency"]
        self.assertEqual(pack["status"], "STOP")
        self.assertTrue(
            any("does not match" in item.get("reason", "") for item in pack["evidence"]),
            pack,
        )

    def test_deleted_prompt_after_qc_invalidates_program_evidence(self):
        prompt = self.job_dir / "seedance" / "seedance_part1_prompt.txt"
        prompt.write_text("prompt\n", encoding="utf-8")
        self.write_json(
            self.job_dir / "checks" / "pre_seedance_pack_seedance_prompt_contract_qc.json",
            {
                "overall": "PASS",
                "prompts": [{"path": str(prompt), "overall": "PASS"}],
            },
        )
        self.bind_report(
            self.job_dir / "checks" / "pre_seedance_pack_seedance_prompt_contract_qc.json",
            [self.job_dir / "seedance" / "director_plan.json", prompt],
        )
        prompt.unlink()

        ledger = build_stage_ledger(
            self.root,
            {"id": self.job_id, "product_name": "generic"},
            "pre_seedance_pack",
            write=False,
        )

        pack = ledger["families"]["generation_pack_consistency"]
        self.assertEqual(pack["status"], "STOP")
        self.assertTrue(
            any("does not match" in item.get("reason", "") for item in pack["evidence"]),
            pack,
        )

    def test_replaced_prompt_with_backdated_mtime_invalidates_exact_binding(self):
        prompt = self.job_dir / "seedance_web_final" / "prompts" / "Part1.txt"
        prompt.write_text("replacement with forged old timestamp\n", encoding="utf-8")
        os.utime(prompt, (1, 1))

        ledger = build_stage_ledger(
            self.root,
            {"id": self.job_id, "product_name": "generic"},
            "pre_seedance_pack",
            write=False,
        )

        pack = ledger["families"]["generation_pack_consistency"]
        self.assertEqual(pack["status"], "STOP")
        self.assertTrue(
            any("does not match" in item.get("reason", "") for item in pack["evidence"]),
            pack,
        )

    def test_reuse_rechecks_report_binding_inputs_outside_ledger_subjects(self):
        plan = build_stage_ledger(
            self.root,
            {"id": self.job_id, "product_name": "generic"},
            "pre_seedance_pack",
            write=True,
        )
        self.bind_current_review(plan)
        passed = build_stage_ledger(
            self.root,
            {"id": self.job_id, "product_name": "generic"},
            "pre_seedance_pack",
            write=True,
        )
        self.assertEqual(passed["overall"], "PASS")

        self.write_json(
            self.job_dir / "product_profile.json",
            {"job_id": self.job_id, "product_name": "changed-only-in-binding", "checks": {}},
        )
        checked = build_stage_ledger(
            self.root,
            {"id": self.job_id, "product_name": "generic"},
            "pre_seedance_pack",
            write=False,
        )

        self.assertEqual(
            checked["families"]["generation_pack_consistency"]["status"],
            "STOP",
        )

    def test_batched_checker_keeps_results_scoped_per_family_and_saves_passes(self):
        manifest = self.job_dir / "visual-assets" / "approved_visual_manifest.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["identity_group_id"] = "identity-changed"
        self.write_json(manifest, data)
        plan = build_stage_ledger(
            self.root,
            {"id": self.job_id, "product_name": "generic"},
            "pre_seedance_pack",
            write=True,
        )
        requested = {
            item["name"] for item in plan["semantic_review_request"]["families"]
        }
        self.assertEqual(
            requested,
            {"visual_integrity", "source_to_generation_fidelity"},
        )
        self.bind_family_review(
            plan,
            {
                "visual_integrity": "PASS",
                "source_to_generation_fidelity": "FAIL",
            },
        )

        checked = build_stage_ledger(
            self.root,
            {"id": self.job_id, "product_name": "generic"},
            "pre_seedance_pack",
            write=True,
        )

        self.assertEqual(checked["overall"], "FAIL")
        self.assertEqual(checked["families"]["visual_integrity"]["status"], "PASS")
        self.assertEqual(
            checked["families"]["source_to_generation_fidelity"]["status"],
            "FAIL",
        )
        state = json.loads(
            (self.job_dir / "checks" / "qc_risk_ledger_state.json").read_text(encoding="utf-8")
        )
        self.assertEqual(state["families"]["visual_integrity"]["status"], "PASS")

        self.write_json(
            self.job_dir / "seedance" / "director_plan.json",
            {"beats": ["repair-only-failed-source-family"]},
        )
        self.write_json(
            self.job_dir / "checks" / "pre_seedance_pack_seedance_prompt_contract_qc.json",
            {"overall": "PASS"},
        )
        self.bind_prompt_report()
        follow_up = build_stage_ledger(
            self.root,
            {"id": self.job_id, "product_name": "generic"},
            "pre_seedance_pack",
            write=False,
        )
        self.assertEqual(
            follow_up["families"]["visual_integrity"]["status"],
            "REUSED_PASS",
        )
        self.assertEqual(
            [item["name"] for item in follow_up["semantic_review_request"]["families"]],
            ["source_to_generation_fidelity"],
        )

    def test_changed_prompt_requires_a_checker_bound_to_the_new_request(self):
        first_plan = build_stage_ledger(
            self.root,
            {"id": self.job_id, "product_name": "generic"},
            "pre_seedance_pack",
            write=True,
        )
        self.bind_current_review(first_plan)
        build_stage_ledger(
            self.root,
            {"id": self.job_id, "product_name": "generic"},
            "pre_seedance_pack",
            write=True,
        )

        self.write_json(self.job_dir / "seedance" / "director_plan.json", {"beats": ["changed-again"]})
        plan = build_stage_ledger(
            self.root,
            {"id": self.job_id, "product_name": "generic"},
            "pre_seedance_pack",
            write=True,
        )
        self.assertEqual(
            [family["name"] for family in plan["semantic_review_request"]["families"]],
            ["source_to_generation_fidelity"],
        )

        self.bind_current_review(plan)
        self.write_json(
            self.job_dir / "checks" / "pre_seedance_pack_seedance_prompt_contract_qc.json",
            {"overall": "PASS"},
        )
        self.bind_prompt_report()
        checked = build_stage_ledger(
            self.root,
            {"id": self.job_id, "product_name": "generic"},
            "pre_seedance_pack",
            write=False,
        )

        self.assertEqual(checked["overall"], "PASS")
        self.assertEqual(
            checked["families"]["source_to_generation_fidelity"]["status"],
            "PASS",
        )


if __name__ == "__main__":
    unittest.main()
