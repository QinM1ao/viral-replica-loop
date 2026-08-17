import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL = REPO_ROOT / "tools" / "legacy_baseline.py"


class LegacyBaselineCliTest(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "app").mkdir()
        (self.root / "tests").mkdir()
        (self.root / "state").mkdir()
        (self.root / "migration" / "policies").mkdir(parents=True)
        (self.root / "migration" / "baselines" / "legacy-layout-v1").mkdir(
            parents=True
        )

        (self.root / "app" / "engine.py").write_text(
            "VALUE = 'current dirty bytes'\n",
            encoding="utf-8",
        )
        (self.root / "tests" / "test_sample.py").write_text(
            "import unittest\n"
            "\n"
            "class SampleTest(unittest.TestCase):\n"
            "    def test_passes(self):\n"
            "        self.assertEqual(2 + 2, 4)\n"
            "\n"
            "    def test_nested_partition(self):\n"
            "        self.assertTrue(True)\n",
            encoding="utf-8",
        )
        (self.root / "tests" / "test_unselected_import.py").write_text(
            "import os\n"
            "import unittest\n"
            "from pathlib import Path\n"
            "\n"
            "if os.environ.get('VIRAL_REPLICA_BASELINE_TEST_PARTITION') == "
            "'nested-sandbox':\n"
            "    marker = Path(__file__).resolve().parents[1] / "
            "'state/nested-discovery-leak'\n"
            "    marker.write_text('imported outside OS sandbox\\n')\n"
            "\n"
            "class UnselectedImportTest(unittest.TestCase):\n"
            "    def test_passes_in_external_deny_partition(self):\n"
            "        self.assertTrue(True)\n",
            encoding="utf-8",
        )
        (self.root / "state" / "control.json").write_text(
            '{"status":"unchanged"}\n',
            encoding="utf-8",
        )

        self.write_json(
            "migration/policies/legacy-source-closure-v1.json",
            {
                "schema_version": 1,
                "policy_id": "legacy-source-closure-v1",
                "source_selectors": [
                    {
                        "root": "app",
                        "include": ["**"],
                        "exclude": [],
                        "role": "engine",
                        "retention": "plugin_content",
                        "reason": "fixture engine",
                    },
                    {
                        "root": "tests",
                        "include": ["test_*.py"],
                        "exclude": ["__pycache__/**"],
                        "role": "test",
                        "retention": "plugin_content",
                        "reason": "fixture tests",
                    },
                ],
                "protected_selectors": [
                    {
                        "path": "state/control.json",
                        "role": "legacy_control_state",
                        "reason": "must remain unchanged",
                    }
                ],
                "test_discovery": {
                    "start_directory": "tests",
                    "pattern": "test_*.py",
                    "top_level_directory": None,
                    "nested_sandbox_test_ids": [
                        "test_sample.SampleTest.test_nested_partition"
                    ],
                },
            },
        )
        self.write_json(
            "migration/policies/migration-retention-v1.json",
            {
                "schema_version": 1,
                "policy_id": "migration-retention-v1",
                "roles": [
                    "plugin_content",
                    "development_workspace_content",
                    "legacy_archive_content",
                    "excluded_rebuildable_content",
                ],
                "exactly_one_role_per_object": True,
                "mixed_directories_require_per_object_classification": True,
                "forbidden_copy_sources": ["whole_tree", "git_head", "directory_name"],
            },
        )
        self.write_json(
            "migration/policies/product-fixture-v1.json",
            {
                "schema_version": 1,
                "policy_id": "product-fixture-v1",
                "customer_media_allowed": False,
                "required_origin_manifest": True,
                "legacy_observation_jobs": ["job-011", "job-013"],
            },
        )
        self.write_json(
            "migration/policies/parity-policy-v1.json",
            {
                "schema_version": 1,
                "policy_id": "parity-policy-v1",
                "levels": ["I", "B", "C", "M", "S"],
            },
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_json(self, relative_path, payload):
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def run_cli(self, *args, expected=0):
        result = subprocess.run(
            ["python3", str(TOOL), *args],
            cwd=self.root,
            text=True,
            capture_output=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(
            result.returncode,
            expected,
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        return result

    def create_test_runs(self):
        outputs = []
        for name in ("run-1.json", "run-2.json"):
            relative = f"migration/baselines/legacy-layout-v1/{name}"
            self.run_cli(
                "run-tests",
                "--root",
                str(self.root),
                "--out",
                relative,
            )
            outputs.append(relative)
        return outputs

    def freeze(self):
        run_paths = self.create_test_runs()
        self.run_cli(
            "freeze",
            "--root",
            str(self.root),
            "--test-run",
            run_paths[0],
            "--test-run",
            run_paths[1],
            "--out",
            "migration/baselines/legacy-layout-v1/baseline.lock.json",
        )
        return self.root / "migration/baselines/legacy-layout-v1/baseline.lock.json"

    def verify(self, expected=0):
        return self.run_cli(
            "verify",
            "--root",
            str(self.root),
            "--baseline",
            "migration/baselines/legacy-layout-v1/baseline.lock.json",
            expected=expected,
        )

    def test_freeze_records_actual_untracked_bytes_and_two_stable_test_runs(self):
        baseline_path = self.freeze()
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))

        self.assertEqual(baseline["kind"], "legacy_layout_baseline")
        self.assertTrue(baseline["baseline_id"].startswith("legacy-"))
        self.assertEqual(
            [item["path"] for item in baseline["source_closure"]["objects"]],
            [
                "app/engine.py",
                "tests/test_sample.py",
                "tests/test_unselected_import.py",
            ],
        )
        self.assertEqual(
            baseline["source_closure"]["objects"][0]["git_state"],
            "not_in_git",
        )
        self.assertEqual(
            baseline["test_reproducibility"]["result"],
            "PASS",
        )
        self.assertEqual(len(baseline["test_runs"]), 2)
        self.assertEqual(
            baseline["test_runs"][0]["stable_result_id"],
            baseline["test_runs"][1]["stable_result_id"],
        )
        self.assertEqual(
            baseline["protected_legacy_snapshot"]["objects"][0]["path"],
            "state/control.json",
        )
        self.assertEqual(
            baseline["test_runs"][0]["stable_result_id"],
            baseline["test_reproducibility"]["stable_result_id"],
        )
        first_run = json.loads(
            (self.root / baseline["test_runs"][0]["path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(
            first_run["no_spend_guard"]["kind"],
            "partitioned_fail_closed_external_network",
        )
        self.assertEqual(
            first_run["no_spend_guard"]["nested_sandbox_partition"]["test_ids"],
            ["test_sample.SampleTest.test_nested_partition"],
        )
        self.assertFalse((self.root / "state/nested-discovery-leak").exists())
        self.assertEqual(self.verify().stdout.strip(), "PASS")

    def test_verify_is_read_only_and_reports_changed_source_object(self):
        baseline_path = self.freeze()
        before_stat = baseline_path.stat()
        self.verify()
        after_stat = baseline_path.stat()
        self.assertEqual(before_stat.st_mtime_ns, after_stat.st_mtime_ns)

        (self.root / "app" / "engine.py").write_text(
            "VALUE = 'tampered'\n",
            encoding="utf-8",
        )
        result = self.verify(expected=1)
        self.assertIn("changed source object: app/engine.py", result.stderr)

    def test_verify_reports_added_and_missing_source_objects(self):
        self.freeze()

        (self.root / "app" / "unexpected.py").write_text(
            "UNDECLARED = True\n",
            encoding="utf-8",
        )
        added = self.verify(expected=1)
        self.assertIn("added source object: app/unexpected.py", added.stderr)

        (self.root / "app" / "unexpected.py").unlink()
        (self.root / "app" / "engine.py").unlink()
        missing = self.verify(expected=1)
        self.assertIn("missing source object: app/engine.py", missing.stderr)

    def test_freeze_rejects_boundary_escaping_symlink(self):
        outside = self.root.parent / f"{self.root.name}-outside.txt"
        outside.write_text("outside\n", encoding="utf-8")
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        (self.root / "app" / "escape.py").symlink_to(outside)

        result = self.run_cli(
            "run-tests",
            "--root",
            str(self.root),
            "--out",
            "migration/baselines/legacy-layout-v1/run-1.json",
            expected=1,
        )
        self.assertIn("boundary-escaping symlink: app/escape.py", result.stderr)

    def test_freeze_requires_two_matching_no_spend_test_runs(self):
        run_paths = self.create_test_runs()
        second = self.root / run_paths[1]
        payload = json.loads(second.read_text(encoding="utf-8"))
        payload["stable_result_id"] = "changed"
        second.write_text(json.dumps(payload) + "\n", encoding="utf-8")

        result = self.run_cli(
            "freeze",
            "--root",
            str(self.root),
            "--test-run",
            run_paths[0],
            "--test-run",
            run_paths[1],
            "--out",
            "migration/baselines/legacy-layout-v1/baseline.lock.json",
            expected=1,
        )
        self.assertIn("test runs are not reproducible", result.stderr)


if __name__ == "__main__":
    unittest.main()
