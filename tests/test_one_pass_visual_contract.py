import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import image_batch_run  # noqa: E402


class OnePassVisualContractTest(unittest.TestCase):
    def test_image_batch_plan_uses_only_the_unified_visual_gate(self):
        commands = image_batch_run.qc_commands_for_job("job-012")

        self.assertEqual(
            commands,
            [
                "python3 tools/codex_imagegen_contract_qc.py --root . --job-id job-012 --stage image_batch_qc",
                "python3 tools/visual_asset_manifest_qc.py --root . --job-id job-012 --stage image_batch_qc",
                "python3 tools/qc_risk_ledger.py --root . --job-id job-012 --stage image_batch_qc",
            ],
        )
        joined = "\n".join(commands)
        for legacy in (
            "storyboard_geometry_qc.py",
            "cross_part_continuity_qc.py",
            "skincare_progression_qc.py",
        ):
            self.assertNotIn(legacy, joined)

    def test_active_worker_and_gate_docs_do_not_call_legacy_visual_review_tools(self):
        active_contracts = [
            "workers/image_batch_worker.md",
            "workers/checker_worker.md",
            "workers/seedance_prompt_worker.md",
            "workers/request_build_worker.md",
            "gates/image_batch_gate.md",
            "gates/seedance_prompt_gate.md",
            "gates/request_gate.md",
        ]
        legacy_tools = (
            "storyboard_geometry_qc.py",
            "cross_part_continuity_qc.py",
            "skincare_progression_qc.py",
        )

        for relative in active_contracts:
            content = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(contract=relative):
                self.assertIn("storyboard_visual_acceptance", content)
                for legacy in legacy_tools:
                    self.assertNotIn(legacy, content)

    def test_operator_and_skill_contracts_name_the_one_pass_source_of_truth(self):
        for relative in (
            "AGENTS.md",
            "LOOP.md",
            ".agents/skills/video-replication/SKILL.md",
        ):
            content = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(contract=relative):
                self.assertIn("storyboard_visual_acceptance", content)
                self.assertNotIn(
                    "python3 tools/storyboard_geometry_qc.py --job-id <job-id> --stage <stage>",
                    content,
                )
                self.assertNotIn(
                    "python3 tools/cross_part_continuity_qc.py --job-id <job-id> --stage <stage>",
                    content,
                )
                self.assertNotIn(
                    "python3 tools/skincare_progression_qc.py --job-id <job-id> --stage <stage>",
                    content,
                )


if __name__ == "__main__":
    unittest.main()
