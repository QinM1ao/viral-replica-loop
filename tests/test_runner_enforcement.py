import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "tools" / "run_next_loop_round.py"
PARALLEL_LANES = REPO_ROOT / "scripts" / "parallel-lanes.py"
sys.path.insert(0, str(REPO_ROOT / "tools"))

from qc_risk_ledger import build_stage_ledger  # noqa: E402
from qc_input_binding import attach_input_binding  # noqa: E402
from run_next_loop_round import GENERATION_INTENTS  # noqa: E402


class RunnerEnforcementTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._write_fixture()

    def tearDown(self):
        self.tmp.cleanup()

    def test_final_qc_contract_uses_canonical_final_directory(self):
        worker = (REPO_ROOT / "workers/final_qc_worker.md").read_text(
            encoding="utf-8"
        )
        skill = (
            REPO_ROOT / ".agents/skills/video-replication/SKILL.md"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "--out-dir viral-replica-loop/output/<job-id>/final",
            worker,
        )
        self.assertNotIn("output/<job-id>/final_qc", worker)
        self.assertIn('--out-dir "<输出目录>/final"', skill)
        self.assertNotIn('--out-dir "<输出目录>/final_qc"', skill)

    def test_quality_retake_contract_is_explicit_and_approval_gated(self):
        worker = (REPO_ROOT / "workers/generation_worker.md").read_text(
            encoding="utf-8"
        )
        skill = (
            REPO_ROOT / ".agents/skills/video-replication/SKILL.md"
        ).read_text(encoding="utf-8")

        self.assertIn("quality_retake", GENERATION_INTENTS)
        self.assertIn("--generation-intent quality_retake", worker)
        self.assertIn("selected_outputs.json", worker)
        self.assertIn("旧的已选 Part", worker)
        self.assertNotIn("默认同一 Part 最多 5 次标准生成", skill)
        self.assertNotIn("原样重试一次", skill)
        self.assertIn("不得自动重提", skill)

    def run_loop(self, *args, check=True):
        result = subprocess.run(
            ["python3", str(RUNNER), "--root", str(self.root), "--job-id", "job-001", *args],
            text=True,
            capture_output=True,
            check=False,
        )
        if check and result.returncode != 0:
            self.fail(f"runner failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        return result

    def write_job(
        self,
        status,
        next_stage,
        needs_user_confirmation,
        last_artifact,
        person_assets=None,
    ):
        with (self.root / "jobs.csv").open("w", newline="", encoding="utf-8") as f:
            fieldnames = [
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
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow(
                {
                    "id": "job-001",
                    "status": status,
                    "video_path": str(self.root / "assets/source.mp4"),
                    "product_name": "孔凤春清洁泥膜",
                    "product_assets": str(self.root / "assets/product"),
                    "person_assets": person_assets or str(self.root / "assets/person"),
                    "audio_assets": "extract_from_original",
                    "target_duration": "30s",
                    "notes": "client_profile=kongfengchun",
                    "output_dir": "output/job-001",
                    "last_artifact": last_artifact,
                    "next_stage": next_stage,
                    "needs_user_confirmation": str(needs_user_confirmation).lower(),
                }
            )

    def read_job(self):
        with (self.root / "jobs.csv").open(newline="", encoding="utf-8") as f:
            return next(csv.DictReader(f))

    def bind_qc_report(self, path, inputs):
        report = json.loads(path.read_text(encoding="utf-8"))
        attach_input_binding(report, self.root, inputs)
        path.write_text(json.dumps(report) + "\n", encoding="utf-8")

    def write_valid_video_understanding(self):
        source = self.root / "assets/source.mp4"
        source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
        understanding_dir = self.root / "output/job-001/剧情分析/video_understanding"
        understanding_dir.mkdir(parents=True, exist_ok=True)
        (understanding_dir / "analysis.json").write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "provider": "wujie_higress",
                    "model": "doubao-seed-2-0-mini-260215",
                    "endpoint": "https://higress-api.wujieai.com/v1/chat/completions",
                    "source_sha256": source_sha256,
                    "analysis": {"summary": "fixture", "timeline": []},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (understanding_dir / "request_manifest.json").write_text(
            json.dumps(
                {
                    "http_status": 200,
                    "provider": "wujie_higress",
                    "model": "doubao-seed-2-0-mini-260215",
                    "endpoint": "https://higress-api.wujieai.com/v1/chat/completions",
                    "fps": 2,
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def _write_fixture(self):
        for rel in [
            ".codex/agents",
            "rules",
            "gates",
            "workers",
            "tools",
            "output/job-001/checks",
            "output/job-001/final",
            "output/job-001/final-images",
            "output/job-001/seedance/requests",
            "output/job-001/seedance_web_final/prompts",
            "output/job-001/visual-assets",
            "assets/product",
            "assets/person",
        ]:
            (self.root / rel).mkdir(parents=True, exist_ok=True)

        for rel in ["STATE.md", "QC_RULES.md", "LOOP.md"]:
            (self.root / rel).write_text(f"# {rel}\n", encoding="utf-8")
        (self.root / "assets/source.mp4").write_bytes(b"")
        (self.root / "rules/VIDEO_UNDERSTANDING_MODEL.json").write_text(
            json.dumps(
                {
                    "provider": "wujie_higress",
                    "base_url": "https://higress-api.wujieai.com/v1",
                    "endpoint": "/chat/completions",
                    "model": "doubao-seed-2-0-mini-260215",
                    "fps": 2,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (self.root / "RUNNER_STATE.json").write_text(
            json.dumps({"version": 1, "retry_limit": 2, "updated_at": None, "jobs": {}}, indent=2) + "\n",
            encoding="utf-8",
        )

        for rel in [
            ".codex/agents/viral-replica-checker.toml",
            "gates/cost_approval_gate.md",
            "gates/final_video_gate.md",
            "gates/generation_gate.md",
            "gates/image_sample_review_gate.md",
            "gates/manual_confirmation_gate.md",
            "gates/pre_seedance_pack_gate.md",
            "gates/source_blueprint_gate.md",
            "gates/subtitle_removal_gate.md",
            "gates/warning_gate.md",
            "workers/checker_worker.md",
            "workers/cost_approval_worker.md",
            "workers/final_qc_worker.md",
            "workers/generation_worker.md",
            "workers/manual_review_worker.md",
            "workers/pre_seedance_pack_worker.md",
            "workers/source_blueprint_worker.md",
            "workers/subtitle_removal_worker.md",
            "workers/warning_worker.md",
            "tools/audio_duration_qc.py",
            "tools/checker_review_qc.py",
            "tools/codex_imagegen_contract_qc.py",
            "tools/cross_part_continuity_qc.py",
            "tools/skincare_progression_qc.py",
            "tools/seedance_prompt_contract_qc.py",
            "tools/source_rhythm_qc.py",
            "tools/source_rhythm_visual_review_qc.py",
            "tools/visual_asset_manifest_qc.py",
        ]:
            (self.root / rel).write_text("# fixture\n", encoding="utf-8")

        (self.root / "output/job-001/checks/image_sample_gate_review.md").write_text("PASS\n", encoding="utf-8")
        (self.root / "output/job-001/checks/pre_seedance_pack_gate_review.md").write_text("PASS\n", encoding="utf-8")
        (self.root / "output/job-001/checks/pre_seedance_pack_gate_review_qc.json").write_text(
            json.dumps({"overall": "PASS"}) + "\n",
            encoding="utf-8",
        )
        (self.root / "output/job-001/checks/pre_seedance_pack_visual_asset_manifest_qc.json").write_text(
            json.dumps(
                {
                    "overall": "PASS",
                    "checks": [{"name": "final_upload_dir_exists", "status": "PASS"}],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (self.root / "output/job-001/checks/pre_seedance_pack_storyboard_geometry_qc.json").write_text(
            json.dumps({"overall": "PASS"}) + "\n",
            encoding="utf-8",
        )
        (self.root / "output/job-001/checks/pre_seedance_pack_cross_part_continuity_qc.json").write_text(
            json.dumps({"overall": "PASS"}) + "\n",
            encoding="utf-8",
        )
        (self.root / "output/job-001/checks/pre_seedance_pack_seedance_prompt_contract_qc.json").write_text(
            json.dumps({"overall": "PASS"}) + "\n",
            encoding="utf-8",
        )
        (self.root / "output/job-001/seedance/requests/request_qc.md").write_text("PASS\n", encoding="utf-8")
        (self.root / "output/job-001/seedance/requests/request_qc.json").write_text(
            json.dumps({"overall": "PASS"}) + "\n",
            encoding="utf-8",
        )
        (self.root / "output/job-001/seedance/requests/final_upload_audio_duration_qc.json").write_text(
            json.dumps({"overall": "PASS"}) + "\n",
            encoding="utf-8",
        )
        (self.root / "output/job-001/seedance/requests/part1_request_prepared.json").write_text("{}\n", encoding="utf-8")
        (self.root / "output/job-001/seedance/requests/part2_request_prepared.json").write_text("{}\n", encoding="utf-8")
        (self.root / "output/job-001/final/final_qc.md").write_text("PASS\n", encoding="utf-8")
        final_video = self.root / "output/job-001/final/final_video.mp4"
        final_video.write_bytes(b"video")
        (self.root / "output/job-001/final/final_qc.json").write_text(
            json.dumps(
                {
                    "overall": "PASS",
                    "videos": [
                        {
                            "path": str(final_video),
                            "sha256": hashlib.sha256(final_video.read_bytes()).hexdigest(),
                        }
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (self.root / "output/job-001/final-images/part1_seedance_ref.png").write_bytes(b"image")
        (self.root / "output/job-001/visual-assets/approved_visual_manifest.json").write_text("{}\n", encoding="utf-8")
        (self.root / "output/job-001/seedance_web_final/prompts/Part1_Seedance提示词.txt").write_text("prompt\n", encoding="utf-8")
        (self.root / "output/job-001/seedance_web_final/reference_audio_part1.mp3").write_bytes(b"audio")
        (self.root / "output/job-001/seedance_web_final/README.md").write_text("handoff\n", encoding="utf-8")

        stage_rules = {
            "version": 1,
            "terminal_statuses": ["done", "blocked"],
            "paid_stage_markers": ["generation_approved", "seedance_generating", "paid"],
            "rules": [
                {
                    "id": "pending",
                    "match": {"type": "exact", "status": "pending"},
                    "decision": "continue",
                    "canonical_stage": "source_blueprint",
                    "cost_class": "free_check",
                    "worker": "$video-replication source blueprint",
                    "worker_file": "workers/source_blueprint_worker.md",
                    "script_file": "tools/source_rhythm_qc.py",
                    "action": "Measure and author source rhythm.",
                    "next_expected": "storyboard_passed",
                    "gate": "gates/source_blueprint_gate.md",
                },
                {
                    "id": "image_qc_passed",
                    "match": {"type": "exact", "status": "image_qc_passed"},
                    "decision": "continue",
                    "canonical_stage": "pre_seedance_pack",
                    "cost_class": "free_check",
                    "worker": "$video-replication pre-Seedance pack",
                    "worker_file": "workers/pre_seedance_pack_worker.md",
                    "script_file": "tools/request_body_qc.py",
                    "action": "Build the compact generation-ready package in one stage.",
                    "next_expected": "seedance_inputs_prepared",
                    "gate": "gates/pre_seedance_pack_gate.md",
                },
                {
                    "id": "sample_image_waiting_review",
                    "match": {"type": "prefix", "status": "sample_image_waiting_review"},
                    "decision": "stop",
                    "reason": "Image sample internal review",
                    "canonical_stage": "image_sample_review",
                    "cost_class": "free_check",
                    "worker": "human",
                    "worker_file": "workers/manual_review_worker.md",
                    "action": "Review image sample only when explicitly requested.",
                    "next_expected": "image_sample_approved",
                    "gate": "gates/image_sample_review_gate.md",
                    "self_audit": {
                        "allowed": True,
                        "worker": "$video-replication checker",
                        "worker_file": "workers/checker_worker.md",
                        "script_file": "tools/checker_review_qc.py",
                        "checker_agent": ".codex/agents/viral-replica-checker.toml",
                        "action": "Run independent checker instead of user sample preview.",
                    },
                },
                {
                    "id": "image_warning_stage",
                    "match": {"type": "exact", "status": "image_warning_stage"},
                    "decision": "continue",
                    "canonical_stage": "warning_stage",
                    "cost_class": "free_check",
                    "worker": "fixture",
                    "worker_file": "workers/warning_worker.md",
                    "action": "Fixture warning stage.",
                    "next_expected": "sample_image_waiting_review",
                    "gate": "gates/warning_gate.md",
                },
                {
                    "id": "seedance_inputs_prepared",
                    "match": {"type": "prefix", "status": "seedance_inputs_prepared"},
                    "decision": "stop",
                    "reason": "Seedance generation requires explicit client approval",
                    "canonical_stage": "generation_approval",
                    "cost_class": "expensive_generation",
                    "worker": "human approval",
                    "worker_file": "workers/cost_approval_worker.md",
                    "action": "Stop before paid generation.",
                    "next_expected": "generation_approved",
                    "gate": "gates/cost_approval_gate.md",
                },
                {
                    "id": "generation_approved",
                    "match": {"type": "exact", "status": "generation_approved"},
                    "decision": "continue",
                    "canonical_stage": "generation",
                    "cost_class": "expensive_generation",
                    "worker": "$video-replication generation",
                    "worker_file": "workers/generation_worker.md",
                    "action": "Submit approved tasks.",
                    "next_expected": "final_qc",
                    "gate": "gates/generation_gate.md",
                },
                {
                    "id": "final_qc",
                    "match": {"type": "prefix", "status": "final_qc"},
                    "decision": "continue",
                    "canonical_stage": "final_qc",
                    "cost_class": "free_check",
                    "worker": "$video-replication final qc",
                    "worker_file": "workers/final_qc_worker.md",
                    "action": "Run objective final technical QC.",
                    "next_expected": "done",
                    "gate": "gates/final_video_gate.md",
                },
                {
                    "id": "done",
                    "match": {"type": "exact", "status": "done"},
                    "decision": "stop",
                    "reason": "job is done",
                    "canonical_stage": "terminal",
                    "cost_class": "free_check",
                    "worker": "none",
                    "worker_file": "none",
                    "action": "No action.",
                    "next_expected": "done",
                    "gate": "none",
                },
            ],
        }
        (self.root / "rules/STAGE_RULES.json").write_text(
            json.dumps(stage_rules, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        cost_policy = {
            "version": 1,
            "cost_classes": {
                "free_check": {"auto_allowed": True},
                "cheap_quality_work": {"auto_allowed": True, "counter": "gpt_image_runs"},
                "conditional_paid_repair": {
                    "auto_allowed": True,
                    "requires_detection_evidence": True,
                    "max_tasks_per_job": 1,
                    "requires_new_approval_for_retry": True,
                },
                "expensive_generation": {
                    "auto_allowed": False,
                    "counter": "seedance_runs",
                    "requires_allow_paid": True,
                    "requires_approval_record": True,
                },
            },
            "budgets": {
                "seedance_runs_per_approval": {"hard": 1},
                "seedance_targeted_retries_per_failed_output": {"hard": 1},
            },
            "approval": {
                "direct_generation_request_is_approval": True,
                "direct_generation_phrases": ["跑 Seedance", "直接出视频", "生成最终视频"],
                "default_approval_scope": "current_explicit_job",
                "current_job_approval_covers_required_parts_once": True,
                "failed_part_retry_requires_new_approval": True,
                "batch_requires_explicit_batch_scope": True,
            },
        }
        (self.root / "COST_POLICY.md").write_text(
            "# Cost Policy\n\n```json\n"
            + json.dumps(cost_policy, ensure_ascii=False, indent=2)
            + "\n```\n",
            encoding="utf-8",
        )
        self.write_job("sample_image_waiting_review", "image_sample_approved", True, "output/job-001/checks/image_sample_gate_review.md")
        # The reusable pre-Seedance reports are produced after all of their inputs.
        for name, report in {
            "pre_seedance_pack_visual_asset_manifest_qc.json": {
                "overall": "PASS",
                "checks": [{"name": "final_upload_dir_exists", "status": "PASS"}],
            },
            "pre_seedance_pack_storyboard_geometry_qc.json": {"overall": "PASS"},
            "pre_seedance_pack_cross_part_continuity_qc.json": {"overall": "PASS"},
            "pre_seedance_pack_seedance_prompt_contract_qc.json": {"overall": "PASS"},
        }.items():
            (self.root / "output/job-001/checks" / name).write_text(
                json.dumps(report) + "\n",
                encoding="utf-8",
            )
        for path in (
            self.root / "output/job-001/seedance/requests/request_qc.json",
            self.root / "output/job-001/seedance/requests/final_upload_audio_duration_qc.json",
        ):
            path.write_text(json.dumps({"overall": "PASS"}) + "\n", encoding="utf-8")
        manifest = self.root / "output/job-001/visual-assets/approved_visual_manifest.json"
        image = self.root / "output/job-001/final-images/part1_seedance_ref.png"
        for name in (
            "pre_seedance_pack_visual_asset_manifest_qc.json",
            "pre_seedance_pack_storyboard_geometry_qc.json",
            "pre_seedance_pack_cross_part_continuity_qc.json",
        ):
            self.bind_qc_report(self.root / "output/job-001/checks" / name, [manifest, image])
        self.bind_qc_report(
            self.root / "output/job-001/checks/pre_seedance_pack_seedance_prompt_contract_qc.json",
            [self.root / "output/job-001/seedance_web_final/prompts"],
        )
        self.bind_qc_report(
            self.root / "output/job-001/seedance/requests/request_qc.json",
            [
                self.root / "output/job-001/seedance/requests/part1_request_prepared.json",
                self.root / "output/job-001/seedance/requests/part2_request_prepared.json",
                self.root / "rules/SEEDANCE_MODEL.json",
            ],
        )
        self.bind_qc_report(
            self.root / "output/job-001/seedance/requests/final_upload_audio_duration_qc.json",
            [self.root / "output/job-001/seedance_web_final/reference_audio_part1.mp3"],
        )
        plan = build_stage_ledger(
            self.root,
            self.read_job(),
            "pre_seedance_pack",
            write=False,
        )
        bindings = {
            item["name"]: item["fingerprint_hash"]
            for item in plan["semantic_review_request"]["families"]
        }
        (self.root / "output/job-001/checks/pre_seedance_pack_gate_review_qc.json").write_text(
            json.dumps(
                {
                    "overall": "PASS",
                    "qc_risk_review": {"family_fingerprints": bindings},
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def test_image_sample_review_is_internal_in_self_audit_by_default(self):
        result = self.run_loop("--self-audit", "--dry-run")

        self.assertIn("Decision: **continue**", result.stdout)
        self.assertIn("Self-audit: `true`", result.stdout)
        self.assertIn("User-facing delivery: `none (internal runner decision)`", result.stdout)
        self.assertIn("Run independent checker instead of user sample preview.", result.stdout)

    def test_pending_job_accepts_storyboard_derived_person_assets(self):
        self.write_job(
            "pending",
            "source_blueprint",
            False,
            "",
            person_assets="storyboard_derived",
        )

        result = self.run_loop("--dry-run", check=False)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Decision: **continue**", result.stdout)
        self.assertNotIn("missing required inputs", result.stdout.lower())

    def test_source_blueprint_pass_requires_passing_source_rhythm_qc(self):
        self.write_job(
            "pending",
            "storyboard_passed",
            False,
            "output/job-001/checks/source_blueprint_gate_review.md",
        )

        result = self.run_loop(
            "--record-gate-result",
            "PASS",
            "--artifact",
            "output/job-001/checks/source_blueprint_gate_review.md",
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing passing source rhythm QC", result.stderr)

    def test_source_blueprint_pass_requires_per_beat_visual_review_qc(self):
        self.write_job(
            "pending",
            "storyboard_passed",
            False,
            "output/job-001/checks/source_blueprint_gate_review.md",
        )
        (self.root / "output/job-001/checks/source_rhythm_qc.json").write_text(
            json.dumps({"overall": "PASS"}) + "\n",
            encoding="utf-8",
        )

        result = self.run_loop(
            "--record-gate-result",
            "PASS",
            "--artifact",
            "output/job-001/checks/source_blueprint_gate_review.md",
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing passing source rhythm visual review QC", result.stderr)

    def test_source_blueprint_pass_requires_rhythm_aware_storyboard_manifest(self):
        self.write_job(
            "pending",
            "storyboard_passed",
            False,
            "output/job-001/checks/source_blueprint_gate_review.md",
        )
        for name in ("source_rhythm_qc.json", "source_rhythm_visual_review_qc.json"):
            (self.root / "output/job-001/checks" / name).write_text(
                json.dumps({"overall": "PASS"}) + "\n",
                encoding="utf-8",
            )
        self.write_valid_video_understanding()

        result = self.run_loop(
            "--record-gate-result",
            "PASS",
            "--artifact",
            "output/job-001/checks/source_blueprint_gate_review.md",
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("storyboard is not locked to source rhythm", result.stderr)

    def test_source_blueprint_pass_requires_seed_video_understanding(self):
        self.write_job(
            "pending",
            "storyboard_passed",
            False,
            "output/job-001/checks/source_blueprint_gate_review.md",
        )
        for name in ("source_rhythm_qc.json", "source_rhythm_visual_review_qc.json"):
            (self.root / "output/job-001/checks" / name).write_text(
                json.dumps({"overall": "PASS"}) + "\n",
                encoding="utf-8",
            )

        result = self.run_loop(
            "--record-gate-result",
            "PASS",
            "--artifact",
            "output/job-001/checks/source_blueprint_gate_review.md",
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Seed 2.0 Mini video understanding evidence", result.stderr)

    def test_legacy_story_analysis_pass_also_requires_seed_video_understanding(self):
        rules_path = self.root / "rules/STAGE_RULES.json"
        rules = json.loads(rules_path.read_text(encoding="utf-8"))
        rules["rules"][0].update(
            {
                "canonical_stage": "story_analysis",
                "worker_file": "workers/story_analysis_worker.md",
                "script_file": "tools/prepare_story_analysis.py",
                "gate": "gates/story_analysis_gate.md",
                "next_expected": "story_analyzed",
            }
        )
        rules_path.write_text(json.dumps(rules) + "\n", encoding="utf-8")
        for path in (
            self.root / "workers/story_analysis_worker.md",
            self.root / "tools/prepare_story_analysis.py",
            self.root / "gates/story_analysis_gate.md",
        ):
            path.write_text("# fixture\n", encoding="utf-8")
        artifact = "output/job-001/checks/story_analysis_gate_review.md"
        self.write_job("pending", "story_analyzed", False, artifact)

        result = self.run_loop(
            "--record-gate-result",
            "PASS",
            "--artifact",
            artifact,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Seed 2.0 Mini video understanding evidence", result.stderr)

    def test_source_blueprint_rejects_wrong_video_understanding_endpoint(self):
        self.write_job(
            "pending",
            "storyboard_passed",
            False,
            "output/job-001/checks/source_blueprint_gate_review.md",
        )
        for name in ("source_rhythm_qc.json", "source_rhythm_visual_review_qc.json"):
            (self.root / "output/job-001/checks" / name).write_text(
                json.dumps({"overall": "PASS"}) + "\n",
                encoding="utf-8",
            )
        self.write_valid_video_understanding()
        manifest = self.root / "output/job-001/剧情分析/video_understanding/request_manifest.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["endpoint"] = "https://example.invalid/v1/chat/completions"
        manifest.write_text(json.dumps(data) + "\n", encoding="utf-8")

        result = self.run_loop(
            "--record-gate-result",
            "PASS",
            "--artifact",
            "output/job-001/checks/source_blueprint_gate_review.md",
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("endpoint does not match", result.stderr)

    def test_source_blueprint_pass_accepts_both_rhythm_qc_layers(self):
        self.write_job(
            "pending",
            "storyboard_passed",
            False,
            "output/job-001/checks/source_blueprint_gate_review.md",
        )
        for name in ("source_rhythm_qc.json", "source_rhythm_visual_review_qc.json"):
            (self.root / "output/job-001/checks" / name).write_text(
                json.dumps({"overall": "PASS"}) + "\n",
                encoding="utf-8",
            )
        self.write_valid_video_understanding()
        story_dir = self.root / "output/job-001/剧情分析"
        storyboard_dir = self.root / "output/job-001/storyboard_source_refs"
        story_dir.mkdir(parents=True, exist_ok=True)
        storyboard_dir.mkdir(parents=True, exist_ok=True)
        (story_dir / "source_rhythm.json").write_text(
            json.dumps(
                {
                    "beats": [
                        {
                            "id": "sr001",
                            "replication_priority": "must_keep",
                            "action_peak_times": [0.5],
                        }
                    ]
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (storyboard_dir / "source_storyboard_manifest.json").write_text(
            json.dumps(
                {
                    "selection_mode": "source_rhythm",
                    "parts": [
                        {
                            "selected_frames": [
                                {
                                    "time": 0.5,
                                    "source_beat_ids": ["sr001"],
                                    "selection_reason": "action_peak",
                                }
                            ]
                        }
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )

        result = self.run_loop(
            "--record-gate-result",
            "PASS",
            "--artifact",
            "output/job-001/checks/source_blueprint_gate_review.md",
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_explicit_stop_point_still_stops_self_audit(self):
        result = self.run_loop("--self-audit", "--stop-at", "image_sample_review", "--dry-run")

        self.assertIn("Decision: **stop**", result.stdout)
        self.assertIn("explicit stop-at matched", result.stdout)

    def test_stop_at_future_status_does_not_stop_current_stage(self):
        self.write_job("image_qc_passed", "seedance_inputs_prepared", False, "output/job-001/checks/pre_seedance_pack_gate_review.md")

        result = self.run_loop("--self-audit", "--stop-at", "seedance_inputs_prepared", "--dry-run")

        self.assertIn("Decision: **continue**", result.stdout)
        self.assertIn("Canonical stage: `pre_seedance_pack`", result.stdout)

    def test_stop_at_reached_status_stops(self):
        self.write_job("seedance_inputs_prepared", "generation_approved", False, "output/job-001/seedance/requests/request_qc.md")

        result = self.run_loop("--self-audit", "--stop-at", "seedance_inputs_prepared", "--dry-run")

        self.assertIn("Decision: **stop**", result.stdout)
        self.assertIn("explicit stop-at matched achieved status", result.stdout)

    def test_pre_seedance_handoff_stop_includes_inspection_paths(self):
        self.write_job("seedance_inputs_prepared", "generation_approved", False, "output/job-001/seedance/requests/request_qc.md")

        result = self.run_loop("--dry-run")

        self.assertIn("Decision: **stop**", result.stdout)
        self.assertIn("User-facing delivery: `Pre-Seedance Handoff`", result.stdout)
        self.assertIn("## Inspection Paths", result.stdout)
        self.assertIn("output/job-001/seedance_web_final", result.stdout)
        self.assertIn("Part1_Seedance提示词.txt", result.stdout)

    def test_image_qc_passed_defaults_to_compact_pre_seedance_pack(self):
        self.write_job("image_qc_passed", "seedance_inputs_prepared", False, "output/job-001/checks/pre_seedance_pack_gate_review.md")

        decision = self.run_loop("--dry-run")

        self.assertIn("Canonical stage: `pre_seedance_pack`", decision.stdout)
        self.assertIn("Build the compact generation-ready package in one stage.", decision.stdout)

        result = self.run_loop(
            "--record-gate-result",
            "PASS",
            "--apply-transition",
            "--artifact",
            "output/job-001/checks/pre_seedance_pack_gate_review.md",
        )

        self.assertIn("- To: `seedance_inputs_prepared`", result.stdout)
        job = self.read_job()
        self.assertEqual(job["status"], "seedance_inputs_prepared")
        self.assertEqual(job["next_stage"], "generation_approved")
        self.assertEqual(job["needs_user_confirmation"], "false")

    def test_pre_seedance_pack_pass_requires_seedance_prompt_contract_qc(self):
        self.write_job("image_qc_passed", "seedance_inputs_prepared", False, "output/job-001/checks/pre_seedance_pack_gate_review.md")
        (self.root / "output/job-001/checks/pre_seedance_pack_seedance_prompt_contract_qc.json").unlink()

        result = self.run_loop(
            "--record-gate-result",
            "PASS",
            "--apply-transition",
            "--artifact",
            "output/job-001/checks/pre_seedance_pack_gate_review.md",
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing passing Seedance prompt contract QC", result.stderr)

    def test_web_handoff_mode_does_not_require_api_request_qc(self):
        self.write_job("image_qc_passed", "seedance_inputs_prepared", False, "output/job-001/checks/pre_seedance_pack_gate_review.md")
        (self.root / "output/job-001/seedance/handoff_mode.json").parent.mkdir(parents=True, exist_ok=True)
        (self.root / "output/job-001/seedance/handoff_mode.json").write_text(
            json.dumps({"mode": "web"}) + "\n",
            encoding="utf-8",
        )
        (self.root / "output/job-001/seedance/requests/request_qc.json").unlink()
        (self.root / "output/job-001/seedance/requests/request_qc.md").unlink()

        result = self.run_loop(
            "--record-gate-result",
            "PASS",
            "--apply-transition",
            "--artifact",
            "output/job-001/checks/pre_seedance_pack_gate_review.md",
        )

        self.assertIn("- To: `seedance_inputs_prepared`", result.stdout)

    def test_web_handoff_mode_reports_missing_final_dir_qc_without_name_error(self):
        self.write_job("image_qc_passed", "seedance_inputs_prepared", False, "output/job-001/checks/pre_seedance_pack_gate_review.md")
        (self.root / "output/job-001/seedance/handoff_mode.json").parent.mkdir(parents=True, exist_ok=True)
        (self.root / "output/job-001/seedance/handoff_mode.json").write_text(
            json.dumps({"mode": "web"}) + "\n",
            encoding="utf-8",
        )
        (self.root / "output/job-001/checks/pre_seedance_pack_visual_asset_manifest_qc.json").write_text(
            json.dumps({"overall": "PASS", "checks": []}) + "\n",
            encoding="utf-8",
        )

        result = self.run_loop(
            "--record-gate-result",
            "PASS",
            "--artifact",
            "output/job-001/checks/pre_seedance_pack_gate_review.md",
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("web handoff mode requires final-directory QC", result.stderr)
        self.assertNotIn("NameError", result.stderr)

    def test_direct_current_job_generation_approval_covers_required_parts_once(self):
        self.write_job("seedance_inputs_prepared", "generation_approved", False, "output/job-001/seedance/requests/request_qc.md")

        result = self.run_loop(
            "--allow-paid",
            "--approval-source-message",
            "请直接跑 Seedance 给我视频",
            "--dry-run",
        )

        self.assertIn("Decision: **continue**", result.stdout)
        self.assertIn("Approval scope: `current_job`", result.stdout)
        self.assertIn("Approved task count: `2`", result.stdout)
        self.assertIn("Planned task count: `2`", result.stdout)

    def test_targeted_retry_approval_can_be_recorded_from_confirmation_stop(self):
        (self.root / "output/job-001/checks/generation_gate_review.md").write_text("STOP\n", encoding="utf-8")
        self.write_job("generation_approved", "final_qc", True, "output/job-001/checks/generation_gate_review.md")
        state = json.loads((self.root / "RUNNER_STATE.json").read_text(encoding="utf-8"))
        state["jobs"]["job-001"] = {
            "spent": {
                "gpt_image_runs": 0,
                "seedance_runs": 2,
                "seedance_targeted_retries": 0,
                "final_video_seedance_retries": 0,
            },
            "cost_approval": {
                "scope": "current_job",
                "approved_task_count": 2,
                "submitted_task_count": 2,
                "generation_intent": "current_job",
                "approval_source": "initial final video request",
                "approved_at": "2026-07-03T10:24:28",
            },
        }
        (self.root / "RUNNER_STATE.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

        result = self.run_loop(
            "--record-gate-result",
            "PASS",
            "--outcome-type",
            "PASS",
            "--allow-paid",
            "--approval-recorded",
            "--approval-scope",
            "targeted_retry",
            "--approval-task-count",
            "2",
            "--planned-task-count",
            "2",
            "--generation-intent",
            "failed_part_retry",
            "--approval-source-message",
            "授权全素材库路线重跑 Part1/Part2",
            "--artifact",
            "output/job-001/checks/generation_gate_review.md",
            "--apply-transition",
        )

        self.assertIn("- Approval scope: `targeted_retry`", result.stdout)
        job = self.read_job()
        self.assertEqual(job["status"], "generation_approved")
        self.assertEqual(job["needs_user_confirmation"], "false")
        updated = json.loads((self.root / "RUNNER_STATE.json").read_text(encoding="utf-8"))
        approval = updated["jobs"]["job-001"]["cost_approval"]
        self.assertEqual(approval["scope"], "targeted_retry")
        self.assertEqual(approval["approved_task_count"], 2)
        self.assertEqual(approval["submitted_task_count"], 0)
        self.assertEqual(approval["generation_intent"], "failed_part_retry")

        next_round = self.run_loop("--allow-paid", "--dry-run")
        self.assertIn("Decision: **continue**", next_round.stdout)
        self.assertIn("Approval scope: `targeted_retry`", next_round.stdout)
        self.assertIn("Generation intent: `failed_part_retry`", next_round.stdout)

    def test_quality_retake_requires_new_one_part_targeted_approval(self):
        artifact = (
            self.root
            / "output/job-001/checks/generation_quality_retake_review.md"
        )
        artifact.write_text("STOP\n", encoding="utf-8")
        self.write_job(
            "generation_approved",
            "final_qc",
            True,
            str(artifact),
        )

        rejected = self.run_loop(
            "--record-gate-result",
            "PASS",
            "--allow-paid",
            "--approval-recorded",
            "--approval-scope",
            "current_job",
            "--approval-task-count",
            "1",
            "--planned-task-count",
            "1",
            "--generation-intent",
            "quality_retake",
            "--approval-source-message",
            "只重抽 Part1 一次",
            "--artifact",
            str(artifact),
            check=False,
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn(
            "quality_retake requires new targeted approval",
            rejected.stderr,
        )

        accepted = self.run_loop(
            "--record-gate-result",
            "PASS",
            "--allow-paid",
            "--approval-recorded",
            "--approval-scope",
            "targeted_retry",
            "--approval-task-count",
            "1",
            "--planned-task-count",
            "1",
            "--generation-intent",
            "quality_retake",
            "--approval-source-message",
            "只重抽 Part1 一次",
            "--artifact",
            str(artifact),
            "--apply-transition",
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        state = json.loads(
            (self.root / "RUNNER_STATE.json").read_text(encoding="utf-8")
        )
        approval = state["jobs"]["job-001"]["cost_approval"]
        self.assertEqual(approval["scope"], "targeted_retry")
        self.assertEqual(approval["approved_task_count"], 1)
        self.assertEqual(approval["generation_intent"], "quality_retake")

    def test_mediakit_targeted_retry_approval_reenters_subtitle_removal(self):
        rules_path = self.root / "rules/STAGE_RULES.json"
        rules = json.loads(rules_path.read_text(encoding="utf-8"))
        rules["rules"].insert(
            -2,
            {
                "id": "subtitle_removal",
                "match": {"type": "exact", "status": "subtitle_removal"},
                "decision": "continue",
                "canonical_stage": "subtitle_removal",
                "cost_class": "conditional_paid_repair",
                "worker": "$video-subtitle-removal",
                "worker_file": "workers/subtitle_removal_worker.md",
                "script_file": "none",
                "action": "Inspect or repair the finished master.",
                "next_expected": "final_qc",
                "gate": "gates/subtitle_removal_gate.md",
            },
        )
        rules_path.write_text(
            json.dumps(rules, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        artifact = self.root / "output/job-001/checks/subtitle_removal_stop.md"
        artifact.write_text("STOP\n", encoding="utf-8")
        self.write_job("subtitle_removal", "final_qc", True, str(artifact))
        state = json.loads((self.root / "RUNNER_STATE.json").read_text(encoding="utf-8"))
        state["jobs"]["job-001"] = {
            "spent": {"mediakit_subtitle_removal_runs": 1},
            "last_gate_result": "STOP",
        }
        (self.root / "RUNNER_STATE.json").write_text(
            json.dumps(state, indent=2) + "\n", encoding="utf-8"
        )
        repair_dir = self.root / "output/job-001/subtitle_removal"
        repair_dir.mkdir(parents=True, exist_ok=True)
        (repair_dir / "paid_attempt.json").write_text(
            json.dumps({"schema_version": 1, "attempt_number": 1, "status": "failed"})
            + "\n",
            encoding="utf-8",
        )

        result = self.run_loop(
            "--allow-paid",
            "--approval-recorded",
            "--approval-scope",
            "targeted_retry",
            "--approve-mediakit-subtitle-retry",
            "--approval-source-message",
            "同意重试一次去字幕",
            "--dry-run",
        )

        self.assertIn("Decision: **continue**", result.stdout)
        self.assertIn("Canonical stage: `subtitle_removal`", result.stdout)

    def test_final_qc_pass_advances_to_done_without_confirmation_stop(self):
        self.write_job("final_qc", "done", False, "output/job-001/final/final_qc.md")

        result = self.run_loop(
            "--record-gate-result",
            "PASS",
            "--apply-transition",
            "--artifact",
            "output/job-001/final/final_qc.md",
        )

        self.assertIn("- To: `done`", result.stdout)
        job = self.read_job()
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["needs_user_confirmation"], "false")

        done = self.run_loop("--dry-run")
        self.assertIn("User-facing delivery: `Final Video`", done.stdout)
        self.assertIn("output/job-001/final/final_video.mp4", done.stdout)

    def test_final_qc_pass_rejects_replaced_video_after_qc(self):
        self.write_job("final_qc", "done", False, "output/job-001/final/final_qc.md")
        (self.root / "output/job-001/final/final_video.mp4").write_bytes(b"replaced")

        result = self.run_loop(
            "--record-gate-result",
            "PASS",
            "--apply-transition",
            "--artifact",
            "output/job-001/final/final_qc.md",
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("final video hash does not match", result.stderr)

    def test_visual_warning_pass_does_not_create_user_confirmation_flag(self):
        self.write_job("image_warning_stage", "sample_image_waiting_review", False, "output/job-001/checks/image_sample_gate_review.md")

        result = self.run_loop(
            "--record-gate-result",
            "PASS",
            "--outcome-type",
            "VISUAL_WARNING",
            "--why-not-fail",
            "tiny metric drift only; person product mud and storyboard structure pass",
            "--apply-transition",
            "--artifact",
            "output/job-001/checks/image_sample_gate_review.md",
        )

        self.assertIn("- Outcome type: `VISUAL_WARNING`", result.stdout)
        job = self.read_job()
        self.assertEqual(job["status"], "sample_image_waiting_review")
        self.assertEqual(job["needs_user_confirmation"], "false")

    def test_product_label_microtext_warning_inherits_machine_code(self):
        artifact = "output/job-001/checks/image_sample_gate_review.md"
        self.write_job(
            "image_warning_stage",
            "sample_image_waiting_review",
            False,
            artifact,
        )
        qc_path = self.root / "output/job-001/checks/image_sample_gate_review_qc.json"
        qc_path.write_text(
            json.dumps(
                {
                    "overall": "PASS",
                    "outcome_type": "VISUAL_WARNING",
                    "why_not_fail": (
                        "Distant storyboard-scale label microtext differs, "
                        "while product identity and hero anchors remain correct."
                    ),
                    "fields": {
                        "Failure type": "product_label_microtext_only",
                    },
                }
            ),
            encoding="utf-8",
        )

        result = self.run_loop(
            "--record-gate-result",
            "PASS",
            "--apply-transition",
            "--artifact",
            artifact,
        )

        self.assertIn("- Outcome type: `VISUAL_WARNING`", result.stdout)
        self.assertIn(
            "- Failure type: `product_label_microtext_only`",
            result.stdout,
        )
        job = self.read_job()
        self.assertEqual(job["status"], "sample_image_waiting_review")
        self.assertEqual(job["needs_user_confirmation"], "false")

    def test_parallel_lanes_are_fixed_job_and_report_serialized_state_policy(self):
        result = subprocess.run(
            ["python3", str(PARALLEL_LANES), "--root", str(self.root), "--self-audit", "--max-workers", "1", "--json"],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            self.fail(f"parallel lanes failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")

        report = json.loads(result.stdout)
        self.assertEqual(report["lane_policy"], "fixed_job_id_required")
        self.assertEqual(report["shared_state_policy"], "coordinator_serialized_by_run_loop_lock")
        self.assertIn("--job-id job-001", report["lanes"][0]["command"])
        self.assertIn(".run-loop.lock", report["lanes"][0]["state_policy"])


if __name__ == "__main__":
    unittest.main()
