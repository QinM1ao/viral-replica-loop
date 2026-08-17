import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import canonical_execution_context
import canonical_plugin_job


class CanonicalExecutionContextTest(unittest.TestCase):
    def test_host_managed_version_directory_is_accepted_by_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_root = Path(tmp) / "personal" / "shotloom" / "0.6.0"
            manifest_path = plugin_root / ".codex-plugin" / "plugin.json"
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_text(
                json.dumps(
                    {
                        "name": canonical_execution_context.PACKAGE_NAME,
                        "version": "0.6.0",
                        "skills": "./skills/",
                    }
                ),
                encoding="utf-8",
            )
            for relative in canonical_execution_context.REQUIRED_WORKFLOW_RESOURCES:
                if relative == ".codex-plugin/plugin.json":
                    continue
                path = plugin_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture\n", encoding="utf-8")

            manifest = canonical_execution_context.validate_plugin_root(plugin_root)

            self.assertEqual(manifest["name"], canonical_execution_context.PACKAGE_NAME)

    def test_runtime_preparation_finishes_before_any_job_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            args = canonical_plugin_job._parser().parse_args(
                ["--workspace", str(workspace), "--prepare-runtime"]
            )
            expected_runtime = (workspace / ".viral-replica" / "runtime").resolve()
            with mock.patch.object(
                canonical_plugin_job,
                "build_workflow_contract",
                return_value={"sha256": "fixture"},
            ), mock.patch.object(
                canonical_plugin_job,
                "initialize_workspace",
                side_effect=lambda _plugin, _workspace: expected_runtime.mkdir(
                    parents=True
                ),
            ), mock.patch.object(
                canonical_plugin_job,
                "check_asr_provider",
                return_value="elevenlabs:scribe_v1 via HIGRESS_API_KEY",
            ) as prepare:
                result = canonical_plugin_job.run(ROOT, args)

            self.assertEqual(result, 0)
            prepare.assert_called_once_with()
            self.assertFalse((workspace / "jobs" / "job-001").exists())


if __name__ == "__main__":
    unittest.main()
