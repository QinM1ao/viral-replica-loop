import json
import tempfile
import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from lifecycle_registry import LifecycleRegistry
import run_next_loop_round


class LifecycleRegistryTest(unittest.TestCase):
    def test_one_registry_resolves_exact_prefix_and_contains_in_file_order(self):
        registry = LifecycleRegistry.from_config(
            {
                "version": 1,
                "initial": {
                    "status": "pending",
                    "next_stage": "source_blueprint",
                },
                "terminal_statuses": ["done", "blocked"],
                "paid_stage_markers": [],
                "rules": [
                    {
                        "id": "pending",
                        "match": {"type": "exact", "status": "pending"},
                        "canonical_stage": "source_blueprint",
                        "next_expected": "storyboard_passed",
                    },
                    {
                        "id": "generating",
                        "match": {
                            "type": "prefix",
                            "status": "seedance_generating",
                        },
                        "canonical_stage": "generation",
                        "next_expected": "finishing",
                    },
                    {
                        "id": "legacy_paid",
                        "match": {"type": "contains", "status": "_paid_"},
                        "canonical_stage": "generation",
                        "next_expected": "finishing",
                    },
                ],
            }
        )

        self.assertEqual(registry.resolve("pending")["id"], "pending")
        self.assertEqual(
            registry.resolve("seedance_generating_part1")["id"],
            "generating",
        )
        self.assertEqual(
            registry.resolve("legacy_paid_request")["id"],
            "legacy_paid",
        )

    def test_terminal_and_initial_state_are_owned_by_the_registry(self):
        registry = LifecycleRegistry.load(ROOT)

        self.assertEqual(
            registry.initial(),
            ("pending", "source_blueprint"),
        )
        self.assertTrue(registry.is_terminal("done"))
        self.assertTrue(registry.is_terminal("blocked"))
        self.assertIsNone(registry.execution_stage("blocked"))
        self.assertEqual(
            registry.execution_stage("pending"),
            "source_blueprint",
        )

    def test_registry_owns_the_five_user_progress_stages(self):
        registry = LifecycleRegistry.load(ROOT)

        self.assertEqual(registry.progress(status="pending").label, "看懂原片")
        self.assertEqual(
            registry.progress(status="seedance_generating_part1").label,
            "生成视频",
        )
        self.assertEqual(
            registry.progress(canonical="caption_finishing").label,
            "质检交付",
        )
        self.assertEqual(
            registry.progress(canonical="confirmation_gate").label,
            "看懂原片",
        )

    def test_invalid_registry_fails_before_a_runner_can_guess(self):
        with self.assertRaisesRegex(ValueError, "duplicate rule id"):
            LifecycleRegistry.from_config(
                {
                    "version": 1,
                    "initial": {
                        "status": "pending",
                        "next_stage": "source_blueprint",
                    },
                    "terminal_statuses": ["done"],
                    "paid_stage_markers": [],
                    "rules": [
                        {
                            "id": "same",
                            "match": {
                                "type": "exact",
                                "status": "pending",
                            },
                            "canonical_stage": "source_blueprint",
                            "next_expected": "done",
                        },
                        {
                            "id": "same",
                            "match": {
                                "type": "exact",
                                "status": "other",
                            },
                            "canonical_stage": "source_blueprint",
                            "next_expected": "done",
                        },
                    ],
                }
            )

    def test_load_reports_the_invalid_rules_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rules = root / "rules" / "STAGE_RULES.json"
            rules.parent.mkdir()
            rules.write_text(json.dumps({"version": 1}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "rules"):
                LifecycleRegistry.load(root)

    def test_progress_comes_from_the_selected_registry(self):
        progress = [
            {
                "index": index,
                "label": f"项目阶段{index}",
                "summary": f"项目阶段{index}说明",
                "canonical": ["source_blueprint"] if index == 1 else [],
                "statuses": ["pending"] if index == 1 else [],
                "next_stages": ["source_blueprint"] if index == 1 else [],
                "status_prefixes": [],
            }
            for index in range(1, 6)
        ]
        registry = LifecycleRegistry.from_config(
            {
                "version": 1,
                "initial": {
                    "status": "pending",
                    "next_stage": "source_blueprint",
                },
                "terminal_statuses": ["done", "blocked"],
                "paid_stage_markers": [],
                "progress": progress,
                "rules": [
                    {
                        "id": "pending",
                        "match": {
                            "type": "exact",
                            "status": "pending",
                        },
                        "canonical_stage": "source_blueprint",
                    }
                ],
            }
        )

        self.assertEqual(
            registry.progress(status="pending").label,
            "项目阶段1",
        )
        self.assertEqual(
            run_next_loop_round.user_visible_stage(
                status="pending",
                lifecycle=registry,
            )["label"],
            "项目阶段1",
        )


if __name__ == "__main__":
    unittest.main()
