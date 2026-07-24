import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "pre_seedance_pack_qc.py"
sys.path.insert(0, str(REPO_ROOT / "tools"))

import pre_seedance_pack_qc
from pre_seedance_pack_qc import build_plan, run_bundle


class PreSeedancePackQCTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.job_id = "job-007"
        self.job_dir = self.root / "output" / self.job_id
        self._write_part_files()

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, relative, content="fixture\n"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def _write_part_files(self):
        for part in (1, 2, 10):
            self._write(f"output/{self.job_id}/seedance/seedance_part{part}_prompt.txt")
            self._write(
                f"output/{self.job_id}/seedance/requests/part{part}_request_prepared.json",
                "{}\n",
            )
            self._write(
                f"output/{self.job_id}/audio-boundary/part{part}_reference_audio.mp3"
            )
            self._write(
                f"output/{self.job_id}/seedance_web_final/Part{part}_上传素材/06_Part{part}_声音参考.mp3"
            )

    def _write_mode(self, mode):
        self._write(
            f"output/{self.job_id}/seedance/handoff_mode.json",
            json.dumps({"mode": mode}) + "\n",
        )

    @staticmethod
    def _task(plan, name):
        return next(item for item in plan["tasks"] if item["name"] == name)

    def test_missing_mode_defaults_to_both_and_discovers_all_parts(self):
        plan = build_plan(self.root, self.job_id)

        self.assertEqual(plan["handoff_mode"], "both")
        self.assertEqual(
            [item["name"] for item in plan["tasks"]],
            [
                "part_compilation_qc",
                "visual_asset_manifest_qc",
                "seedance_prompt_contract_qc",
                "source_rhythm_qc",
                "audio_duration_qc",
                "request_body_qc",
            ],
        )
        self.assertIn("--check-final-dir", self._task(plan, "visual_asset_manifest_qc")["command"])
        self.assertEqual(
            [Path(path).name for path in plan["inputs"]["prompt_files"]],
            [
                "seedance_part1_prompt.txt",
                "seedance_part2_prompt.txt",
                "seedance_part10_prompt.txt",
            ],
        )
        self.assertEqual(
            [Path(path).name for path in plan["inputs"]["request_files"]],
            [
                "part1_request_prepared.json",
                "part2_request_prepared.json",
                "part10_request_prepared.json",
            ],
        )
        self.assertEqual(len(plan["inputs"]["audio_files"]), 3)
        self.assertTrue(all("seedance_web_final" in path for path in plan["inputs"]["audio_files"]))

    def test_web_omits_request_and_api_uses_canonical_audio(self):
        self._write_mode("web")
        web_plan = build_plan(self.root, self.job_id)
        self.assertNotIn("request_body_qc", [item["name"] for item in web_plan["tasks"]])
        self.assertIn("--check-final-dir", self._task(web_plan, "visual_asset_manifest_qc")["command"])

        self._write_mode("api")
        api_plan = build_plan(self.root, self.job_id)
        self.assertIn("request_body_qc", [item["name"] for item in api_plan["tasks"]])
        self.assertNotIn("--check-final-dir", self._task(api_plan, "visual_asset_manifest_qc")["command"])
        self.assertTrue(all("audio-boundary" in path for path in api_plan["inputs"]["audio_files"]))

    def test_new_flow_rechecks_source_rhythm_against_director_plan(self):
        rhythm_path = self._write(
            f"output/{self.job_id}/剧情分析/source_rhythm.json",
            "{}\n",
        )
        director_path = self._write(
            f"output/{self.job_id}/seedance/director_plan.json",
            "{}\n",
        )

        plan = build_plan(self.root, self.job_id)

        rhythm_task = self._task(plan, "source_rhythm_qc")
        self.assertIn("tools/source_rhythm_qc.py", rhythm_task["command"])
        self.assertEqual(
            rhythm_task["command"][rhythm_task["command"].index("--source-rhythm") + 1],
            str(rhythm_path.relative_to(self.root)),
        )
        self.assertEqual(
            rhythm_task["command"][rhythm_task["command"].index("--director-plan") + 1],
            str(director_path.relative_to(self.root)),
        )

    def test_new_flow_schedules_source_rhythm_qc_even_when_inputs_are_missing(self):
        plan = build_plan(self.root, self.job_id)

        rhythm_task = self._task(plan, "source_rhythm_qc")
        self.assertIn(
            f"output/{self.job_id}/剧情分析/source_rhythm.json",
            rhythm_task["command"],
        )
        self.assertIn(
            f"output/{self.job_id}/seedance/director_plan.json",
            rhythm_task["command"],
        )

    def test_injected_runner_runs_in_parallel_and_report_failure_wins(self):
        barrier = threading.Barrier(6, timeout=2)
        thread_ids = set()
        lock = threading.Lock()

        def fake_runner(command, **kwargs):
            with lock:
                thread_ids.add(threading.get_ident())
            barrier.wait()
            report_path = self.root / command[command.index("--out-json") + 1]
            report_path.parent.mkdir(parents=True, exist_ok=True)
            child_overall = "FAIL" if "request_body_qc.py" in command[1] else "PASS"
            report_path.write_text(json.dumps({"overall": child_overall}) + "\n", encoding="utf-8")
            markdown_path = self.root / command[command.index("--out-md") + 1]
            markdown_path.parent.mkdir(parents=True, exist_ok=True)
            markdown_path.write_text(f"# {child_overall}\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout=child_overall + "\n", stderr="")

        with mock.patch.object(
            pre_seedance_pack_qc.qc_evidence_fanout,
            "coordinate_ledger",
            wraps=pre_seedance_pack_qc.qc_evidence_fanout.coordinate_ledger,
        ) as coordinator:
            bundle = run_bundle(self.root, self.job_id, runner=fake_runner)

        self.assertEqual(coordinator.call_count, 1)
        self.assertEqual(len(thread_ids), 6)
        self.assertEqual(bundle["overall"], "FAIL")
        self.assertEqual(
            [item["name"] for item in bundle["tasks"]],
            [
                "part_compilation_qc",
                "visual_asset_manifest_qc",
                "seedance_prompt_contract_qc",
                "source_rhythm_qc",
                "audio_duration_qc",
                "request_body_qc",
            ],
        )
        request_result = next(item for item in bundle["tasks"] if item["name"] == "request_body_qc")
        self.assertEqual(request_result["returncode"], 0)
        self.assertEqual(request_result["report_overall"], "FAIL")
        self.assertEqual(request_result["overall"], "FAIL")
        for item in bundle["tasks"]:
            self.assertIsInstance(item["command"], list)
            self.assertIsInstance(item["returncode"], int)
            self.assertGreaterEqual(item["duration_seconds"], 0)

        json_bundle = self.job_dir / "checks" / "pre_seedance_pack_qc_bundle.json"
        md_bundle = self.job_dir / "checks" / "pre_seedance_pack_qc_bundle.md"
        self.assertTrue(json_bundle.is_file())
        self.assertTrue(md_bundle.is_file())
        self.assertIn("request_body_qc", md_bundle.read_text(encoding="utf-8"))
        checks = self.job_dir / "checks"
        self.assertTrue(
            (checks / "pre_seedance_pack_qc_risk_ledger.json").is_file()
        )
        self.assertTrue((checks / "qc_risk_ledger_state.json").is_file())
        self.assertTrue(
            (checks / "pre_seedance_pack_semantic_review_request.json").is_file()
        )
        self.assertEqual(
            bundle["qc_risk_ledger"],
            f"output/{self.job_id}/checks/pre_seedance_pack_qc_risk_ledger.json",
        )

    def test_dry_plan_does_not_run_qc_tools(self):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--root",
                str(self.root),
                "--job-id",
                self.job_id,
                "--dry-plan",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["handoff_mode"], "both")
        self.assertFalse((self.job_dir / "checks" / "pre_seedance_pack_qc_bundle.json").exists())


if __name__ == "__main__":
    unittest.main()
