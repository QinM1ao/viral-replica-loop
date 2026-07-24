import csv
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import image_batch_fanout

REPO_ROOT = Path(__file__).resolve().parents[1]
FANOUT = REPO_ROOT / "tools" / "image_batch_fanout.py"
CONTRACT_QC = REPO_ROOT / "tools" / "codex_imagegen_contract_qc.py"


class ImageBatchFanoutTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.job_id = "job-001"
        self.job_dir = self.root / "output" / self.job_id
        self._write_fixture()

    def tearDown(self):
        self.tmp.cleanup()

    def run_fanout(self, *args, check=True):
        result = subprocess.run(
            ["python3", str(FANOUT), "--root", str(self.root), "--job-id", self.job_id, *args],
            text=True,
            capture_output=True,
            check=False,
        )
        if check and result.returncode != 0:
            self.fail(f"fanout failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        return result

    def _write_fixture(self):
        for rel in [
            "assets/product",
            "assets/person",
            "output/job-001/storyboard_source_refs",
            "output/job-001/image-batch/contracts",
            "output/job-001/image-batch/invocations",
            "output/job-001/image-batch/prompts",
            "output/job-001/image-batch/candidates",
            "output/job-001/visual-assets",
            "output/job-001/checks",
            "output/shared/product",
            "output/shared/identity",
            "rules",
        ]:
            (self.root / rel).mkdir(parents=True, exist_ok=True)

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
                    "id": self.job_id,
                    "status": "storyboard_passed",
                    "video_path": str(self.root / "source.mp4"),
                    "product_name": "孔凤春发酵水",
                    "product_assets": str(self.root / "assets/product"),
                    "person_assets": str(self.root / "assets/person"),
                    "audio_assets": "extract_from_original",
                    "target_duration": "30s",
                    "notes": "",
                    "output_dir": "output/job-001",
                    "last_artifact": "",
                    "next_stage": "image_qc_passed",
                    "needs_user_confirmation": "false",
                }
            )

        profile = {
            "version": 1,
            "job_id": self.job_id,
            "category_id": "toner",
            "loaded_rules": ["generic:generic_product", "category:toner"],
            "reference_roles": {
                "required": ["source_storyboard", "product_front", "identity_ref"],
                "optional": [],
                "order_prefix": ["source_storyboard", "product_front", "identity_ref"],
            },
            "review_flags": {
                "required": [
                    "layout_matches_source",
                    "source_aspect_preserved",
                    "same_identity_as_reference",
                    "primary_identity_consistent",
                    "primary_identity_only_on_target_role",
                    "secondary_characters_keep_source_role_gender",
                    "no_source_host_identity",
                    "target_product_packaging",
                    "target_product_label",
                    "no_old_product",
                    "no_subtitles_or_text",
                    "product_visible_text",
                    "no_blank_label",
                ]
            },
            "checks": {"requires_finger_jar_application": False},
            "prompt_required_groups": [
                {"name": "target_product", "patterns": ["孔凤春", "发酵水", "toner"]},
                {"name": "toner_application", "patterns": ["掌心", "轻拍", "toner"]},
            ],
            "source_storyboard_controls": ["layout", "shot_order", "framing", "action_rhythm"],
            "source_storyboard_must_not_control": [
                "old_product",
                "old_tool",
                "old_host_identity",
                "old_mud_color",
                "subtitles",
            ],
        }
        (self.job_dir / "product_profile.json").write_text(
            json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        for path in [
            "output/shared/product/product_front.png",
            "output/shared/identity/identity_ref.png",
            "source.mp4",
        ]:
            (self.root / path).write_bytes(b"x")

        manifest_parts = []
        visual_parts = {}
        for index in [1, 2]:
            part = f"part{index}"
            source = self.root / f"output/job-001/storyboard_source_refs/source_storyboard_{part}.jpg"
            candidate = self.root / f"output/job-001/image-batch/candidates/{part}.png"
            prompt = self.root / f"output/job-001/image-batch/prompts/{part}.md"
            invocation = self.root / f"output/job-001/image-batch/invocations/{part}.json"
            for file_path in [source, candidate]:
                file_path.write_bytes(f"{part}".encode("utf-8"))
            prompt.write_text(
                "孔凤春发酵水 toner 倒在掌心后轻拍上脸，保留源分镜节奏。",
                encoding="utf-8",
            )
            invocation.write_text(
                json.dumps(
                    {
                        "status": "PASS",
                        "inputs_attached_or_loaded": True,
                        "actual_image_inputs_loaded": True,
                        "references_loaded_before_call": [
                            {"role": "source_storyboard", "path": str(source.relative_to(self.root))},
                            {"role": "product_front", "path": "output/shared/product/product_front.png"},
                            {"role": "identity_ref", "path": "output/shared/identity/identity_ref.png"},
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            manifest_parts.append(
                {
                    "part": index,
                    "path": str(source.relative_to(self.root)),
                    "size": [856, 1246],
                    "ratio": 0.687,
                }
            )
            visual_parts[part] = {
                "path": str(candidate.relative_to(self.root)),
                "asset_type": "AI改好分镜图",
                "image_route": "matpool_gpt_image_2_edit",
                "contains_source_video_pixels": False,
            }
            self._write_part_contract(part, source, candidate, prompt, invocation)

        (self.job_dir / "storyboard_source_refs/source_storyboard_manifest.json").write_text(
            json.dumps({"parts": manifest_parts}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (self.job_dir / "visual-assets/approved_visual_manifest.json").write_text(
            json.dumps(
                {
                    "job_id": self.job_id,
                    "part_storyboards": visual_parts,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        self._write_execution_specs()

    def _write_execution_specs(self):
        specs = {
            "schema_version": 1,
            "job_id": self.job_id,
            "parts": [],
        }
        for index in [1, 2]:
            part = f"part{index}"
            specs["parts"].append(
                {
                    "part": part,
                    "prompt_path": f"output/job-001/image-batch/prompts/{part}.md",
                    "references": [
                        {
                            "role": "source_storyboard",
                            "path": (
                                "output/job-001/storyboard_source_refs/"
                                f"source_storyboard_{part}.jpg"
                            ),
                        },
                        {
                            "role": "product_front",
                            "path": "output/shared/product/product_front.png",
                        },
                        {
                            "role": "identity_ref",
                            "path": "output/shared/identity/identity_ref.png",
                        },
                    ],
                    "depends_on": [],
                }
            )
        (self.job_dir / "image-batch/part_execution_specs.json").write_text(
            json.dumps(specs, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _write_part_contract(self, part, source, candidate, prompt, invocation):
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
        }
        contract = {
            "job_id": self.job_id,
            "stage": "image_batch_qc",
            "image_route": "matpool_gpt_image_2_edit",
            "target_application_method": "toner_pour_to_palm_and_pat_to_face",
            "source_storyboard_controls": ["layout", "shot_order", "framing", "action_rhythm"],
            "source_storyboard_must_not_control": [
                "old_product",
                "old_tool",
                "old_host_identity",
                "old_mud_color",
                "subtitles",
            ],
            "api_effect_baseline": {
                "source": "matpool_gpt_image_2_edit",
                "preserve_api_route": True,
                "reference_order": ["source_storyboard", "product_front", "identity_ref"],
                "generation_settings": {
                    "quality": "medium",
                    "resolution": "1K",
                    "ratio_source": str(source.relative_to(self.root)),
                },
            },
            "preserve_api_route": True,
            "matpool_uses_real_image_inputs": True,
            "reference_order": ["source_storyboard", "product_front", "identity_ref"],
            "codex_generation_settings": {
                "quality": "medium",
                "resolution": "1K",
                "ratio_source": str(source.relative_to(self.root)),
                "reference_order": ["source_storyboard", "product_front", "identity_ref"],
                "size": "1024x1536",
            },
            "parts": [
                {
                    "part": part,
                    "source_storyboard": str(source.relative_to(self.root)),
                    "candidate_path": str(candidate.relative_to(self.root)),
                    "prompt_path": str(prompt.relative_to(self.root)),
                    "refs_loaded": {
                        "source_storyboard": {"path": str(source.relative_to(self.root)), "loaded_to_context": True},
                        "product_front": {"path": "output/shared/product/product_front.png", "loaded_to_context": True},
                        "identity_ref": {"path": "output/shared/identity/identity_ref.png", "loaded_to_context": True},
                    },
                    "source_risks": ["old_product", "old_tool"],
                    "required_translations": [{"target_action": "toner to palm and face patting"}],
                    "review": review,
                    "reference_order": ["source_storyboard", "product_front", "identity_ref"],
                    "codex_generation_settings": {
                        "quality": "medium",
                        "resolution": "1K",
                        "ratio_source": str(source.relative_to(self.root)),
                        "reference_order": ["source_storyboard", "product_front", "identity_ref"],
                        "size": "1024x1536",
                    },
                    "invocation_manifest": str(invocation.relative_to(self.root)),
                    "asset_type": "AI改好分镜图",
                }
            ],
        }
        (self.job_dir / f"image-batch/contracts/{part}_contract.json").write_text(
            json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def test_plan_writes_isolated_part_contract_paths(self):
        result = self.run_fanout("plan", "--json")
        plan = json.loads(result.stdout)

        self.assertEqual(plan["fanout_policy"], "part_contracts_then_serial_merge")
        self.assertEqual([part["part"] for part in plan["parts"]], ["part1", "part2"])
        self.assertIn("image-batch/contracts/part1_contract.json", plan["parts"][0]["contract_path"])
        self.assertIn("--contract", plan["parts"][0]["required_generate_flags"])
        self.assertIn("merge", plan["merge_command"])
        self.assertTrue(plan["plan_sha256"])
        self.assertEqual(
            plan["parts"][0]["command"],
            plan["stage_execution"]["packets"][0]["command"],
        )

    def test_plan_stops_when_complete_execution_specs_are_missing(self):
        (self.job_dir / "image-batch/part_execution_specs.json").unlink()

        result = self.run_fanout("plan", "--json", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("part_execution_specs.json is required", result.stderr)

    def test_plan_stops_when_a_required_part_spec_is_missing(self):
        specs_path = self.job_dir / "image-batch/part_execution_specs.json"
        specs = json.loads(specs_path.read_text(encoding="utf-8"))
        specs["parts"] = specs["parts"][:1]
        specs_path.write_text(json.dumps(specs), encoding="utf-8")

        result = self.run_fanout("plan", "--json", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing required Part specs: part2", result.stderr)

    def test_plan_builds_executable_part_packets_from_explicit_specs(self):
        specs = {
            "schema_version": 1,
            "job_id": self.job_id,
            "parts": [
                {
                    "part": "part1",
                    "prompt_path": "output/job-001/image-batch/prompts/part1.md",
                    "references": [
                        {
                            "role": "source_storyboard",
                            "path": (
                                "output/job-001/storyboard_source_refs/"
                                "source_storyboard_part1.jpg"
                            ),
                        },
                        {
                            "role": "product_front",
                            "path": "output/shared/product/product_front.png",
                        },
                        {
                            "role": "identity_ref",
                            "path": "output/shared/identity/identity_ref.png",
                        },
                    ],
                    "depends_on": [],
                },
                {
                    "part": "part2",
                    "prompt_path": "output/job-001/image-batch/prompts/part2.md",
                    "references": [
                        {
                            "role": "source_storyboard",
                            "path": (
                                "output/job-001/storyboard_source_refs/"
                                "source_storyboard_part2.jpg"
                            ),
                        },
                        {
                            "role": "product_front",
                            "path": "output/shared/product/product_front.png",
                        },
                        {
                            "role": "identity_ref",
                            "path": "output/shared/identity/identity_ref.png",
                        },
                    ],
                    "depends_on": ["part1"],
                },
            ],
        }
        (self.job_dir / "image-batch/part_execution_specs.json").write_text(
            json.dumps(specs, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        result = self.run_fanout("plan", "--json")
        plan = json.loads(result.stdout)

        self.assertTrue(plan["parts"][0]["command"])
        self.assertIn(
            ".agents/skills/video-replication/scripts/generate.py",
            plan["parts"][0]["command"][1],
        )
        self.assertIn("--prompt-file", plan["parts"][0]["command"])
        self.assertEqual(plan["parts"][1]["depends_on"], ["part1"])
        self.assertEqual(
            [packet["packet_id"] for packet in plan["stage_execution"]["packets"]],
            ["part1", "part2"],
        )

    def test_run_uses_dependency_waves_and_records_packet_completions(self):
        specs = {
            "schema_version": 1,
            "job_id": self.job_id,
            "parts": [
                {
                    "part": "part1",
                    "prompt_path": "output/job-001/image-batch/prompts/part1.md",
                    "references": [
                        {
                            "role": "source_storyboard",
                            "path": (
                                "output/job-001/storyboard_source_refs/"
                                "source_storyboard_part1.jpg"
                            ),
                        }
                    ],
                    "depends_on": [],
                },
                {
                    "part": "part2",
                    "prompt_path": "output/job-001/image-batch/prompts/part2.md",
                    "references": [
                        {
                            "role": "source_storyboard",
                            "path": (
                                "output/job-001/storyboard_source_refs/"
                                "source_storyboard_part2.jpg"
                            ),
                        }
                    ],
                    "depends_on": ["part1"],
                },
            ],
        }
        (self.job_dir / "image-batch/part_execution_specs.json").write_text(
            json.dumps(specs, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        plan = image_batch_fanout.write_plan(
            self.root,
            image_batch_fanout.build_plan(self.root, self.job_id),
        )
        completed = []

        def fake_runner(command, **_kwargs):
            part = command[command.index("--part") + 1]
            if part == "part2":
                self.assertEqual(completed, ["part1"])
            output = Path(command[command.index("--file") + 1])
            contract = Path(command[command.index("--contract") + 1])
            invocation = Path(command[command.index("--invocation-manifest") + 1])
            for path in [output, contract, invocation]:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(part, encoding="utf-8")
            completed.append(part)
            return mock.Mock(returncode=0, stdout="", stderr="")

        report = image_batch_fanout.run_fanout(
            self.root,
            self.job_id,
            plan["plan_path"],
            max_workers=2,
            runner=fake_runner,
        )

        self.assertEqual(report["overall"], "PASS")
        self.assertEqual(completed, ["part1", "part2"])
        for part in ["part1", "part2"]:
            completion = (
                self.job_dir
                / f"work-packets/image_batch_qc/completions/{part}.json"
            )
            self.assertTrue(completion.exists())
            self.assertTrue(
                (
                    self.job_dir
                    / f"image-batch/fanout/logs/{part}.stdout.txt"
                ).is_file()
            )
            self.assertTrue(
                (
                    self.job_dir
                    / f"image-batch/fanout/logs/{part}.stderr.txt"
                ).is_file()
            )

    def test_run_rewrites_packet_staging_paths_in_promoted_evidence(self):
        plan = image_batch_fanout.write_plan(
            self.root,
            image_batch_fanout.build_plan(self.root, self.job_id),
        )

        def fake_runner(command, **_kwargs):
            output = Path(command[command.index("--file") + 1])
            contract = Path(command[command.index("--contract") + 1])
            invocation = Path(command[command.index("--invocation-manifest") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"generated")
            for path in [contract, invocation]:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(
                        {
                            "candidate_path": str(output),
                            "contract_path": str(contract),
                            "invocation_manifest": str(invocation),
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
            return mock.Mock(returncode=0, stdout="", stderr="")

        report = image_batch_fanout.run_fanout(
            self.root,
            self.job_id,
            plan["plan_path"],
            max_workers=2,
            runner=fake_runner,
        )

        self.assertEqual(report["overall"], "PASS")
        for part in plan["parts"]:
            contract = json.loads(
                (self.root / part["contract_path"]).read_text(encoding="utf-8")
            )
            self.assertNotIn(".stage-execution-", contract["candidate_path"])
            self.assertEqual(
                Path(contract["candidate_path"]).resolve(),
                (self.root / part["candidate_path"]).resolve(),
            )

    def test_run_rejects_cli_job_id_that_does_not_match_the_plan(self):
        plan = image_batch_fanout.write_plan(
            self.root,
            image_batch_fanout.build_plan(self.root, self.job_id),
        )

        with self.assertRaisesRegex(ValueError, "CLI job_id does not match"):
            image_batch_fanout.run_fanout(
                self.root,
                "job-999",
                plan["plan_path"],
                max_workers=2,
            )

    def test_run_rejects_outer_part_mutation_bound_to_sealed_packets(self):
        plan = image_batch_fanout.write_plan(
            self.root,
            image_batch_fanout.build_plan(self.root, self.job_id),
        )
        plan_path = self.root / plan["plan_path"]
        mutated = json.loads(plan_path.read_text(encoding="utf-8"))
        mutated["parts"][0]["command"].append("--unexpected")
        plan_path.write_text(json.dumps(mutated), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "fanout plan hash mismatch"):
            image_batch_fanout.run_fanout(
                self.root,
                self.job_id,
                plan["plan_path"],
                max_workers=2,
            )

    def test_run_rejects_plan_without_stage_execution_instead_of_fallback(self):
        plan = image_batch_fanout.write_plan(
            self.root,
            image_batch_fanout.build_plan(self.root, self.job_id),
        )
        plan_path = self.root / plan["plan_path"]
        mutated = json.loads(plan_path.read_text(encoding="utf-8"))
        mutated.pop("stage_execution")
        mutated.pop("plan_sha256")
        mutated["plan_sha256"] = image_batch_fanout.stage_execution.stable_hash(
            mutated
        )
        plan_path.write_text(json.dumps(mutated), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "requires sealed stage_execution"):
            image_batch_fanout.run_fanout(
                self.root,
                self.job_id,
                plan["plan_path"],
                max_workers=2,
            )

    def test_merge_combines_part_contracts_into_qc_compatible_contract(self):
        result = self.run_fanout("merge", "--json")
        report = json.loads(result.stdout)
        self.assertEqual(report["overall"], "PASS")

        merged_path = self.job_dir / "image-batch/codex_imagegen_contract.json"
        merged = json.loads(merged_path.read_text(encoding="utf-8"))
        self.assertEqual(merged["fanout_policy"], "part_contracts_then_serial_merge")
        self.assertEqual([part["part"] for part in merged["parts"]], ["part1", "part2"])

        qc = subprocess.run(
            [
                "python3",
                str(CONTRACT_QC),
                "--root",
                str(self.root),
                "--job-id",
                self.job_id,
                "--stage",
                "image_batch_qc",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(qc.returncode, 0, qc.stderr)
        self.assertIn("PASS", qc.stdout)

    def test_merge_fails_when_required_part_contract_is_missing(self):
        (self.job_dir / "image-batch/contracts/part2_contract.json").unlink()

        result = self.run_fanout("merge", "--json", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing_part_contracts", result.stderr)


class ImageBatchFanoutRuleTest(unittest.TestCase):
    def test_storyboard_passed_stage_rule_points_to_fanout_entrypoint(self):
        rules = json.loads((REPO_ROOT / "rules/STAGE_RULES.json").read_text(encoding="utf-8"))
        storyboard_rule = next(rule for rule in rules["rules"] if rule["id"] == "storyboard_passed")

        self.assertIn("tools/image_batch_fanout.py plan", storyboard_rule["action"])
        self.assertIn("tools/image_batch_fanout.py merge", storyboard_rule["action"])
        self.assertIn("partX_contract.json", storyboard_rule["action"])
        self.assertEqual(storyboard_rule["script_file"], "tools/image_batch_fanout.py")


if __name__ == "__main__":
    unittest.main()
