import csv
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from private_plugin_package import build_package  # noqa: E402


class ThinPluginSmokeTest(unittest.TestCase):
    def _generate_signing_keypair(self, root: Path) -> tuple[Path, Path]:
        private_key = root / "release-signing-key.pem"
        public_key = root / "release-signing-key.pub.pem"
        subprocess.run(
            ["openssl", "genrsa", "-out", str(private_key), "2048"],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                "openssl",
                "rsa",
                "-in",
                str(private_key),
                "-pubout",
                "-out",
                str(public_key),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return private_key, public_key

    def _build_package(self, root: Path) -> Path:
        private_key, public_key = self._generate_signing_keypair(root)
        return build_package(
            source_root=ROOT,
            out_root=root / "dist",
            version="0.6.0",
            signing_private_key=private_key,
            signing_public_key=public_key,
            release_registry=root / "release-registry.json",
        ).package_root

    def _fake_codex(self, root: Path) -> Path:
        script = root / "fake-codex"
        script.write_text(
            """#!/usr/bin/env python3
import sys

if sys.argv[1:3] == ["plugin", "add"]:
    print(f"installed {sys.argv[3]}")
    raise SystemExit(0)
if sys.argv[1:3] == ["plugin", "list"]:
    print("shotloom@personal installed, enabled 0.6.0")
    raise SystemExit(0)
if sys.argv[1:4] == ["plugin", "marketplace", "add"]:
    print(f"added marketplace {sys.argv[4]}")
    raise SystemExit(0)
print("unsupported fake codex invocation", file=sys.stderr)
raise SystemExit(2)
""",
            encoding="utf-8",
        )
        script.chmod(0o755)
        return script

    def _host_runtime(self, root: Path) -> Path:
        runtime_root = root / "host-runtime"
        base_python = Path(sys.base_prefix) / "bin" / "python3"
        if not base_python.is_file():
            base_python = Path(sys.executable)
        subprocess.run(
            [str(base_python), "-m", "venv", str(runtime_root)],
            check=True,
            capture_output=True,
            text=True,
        )
        runtime_python = runtime_root / "bin" / "python"
        site_packages = Path(
            subprocess.run(
                [
                    str(runtime_python),
                    "-c",
                    "import site; print(site.getsitepackages()[0])",
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        import PIL

        source_site = Path(PIL.__file__).resolve().parent.parent
        shutil.copytree(source_site / "PIL", site_packages / "PIL")
        pillow_metadata = next(source_site.glob("pillow-*.dist-info"))
        shutil.copytree(
            pillow_metadata,
            site_packages / pillow_metadata.name,
        )
        return runtime_python

    def _tree_digest(self, root: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root).as_posix()
            digest.update(relative.encode("utf-8"))
            if path.is_file():
                digest.update(path.read_bytes())
                digest.update(
                    str(stat.S_IMODE(path.stat().st_mode)).encode("ascii")
                )
        return digest.hexdigest()

    def _make_tree_read_only(self, root: Path) -> None:
        for path in sorted(root.rglob("*"), reverse=True):
            if path.is_file():
                executable = bool(stat.S_IMODE(path.stat().st_mode) & 0o111)
                path.chmod(0o555 if executable else 0o444)
            elif path.is_dir():
                path.chmod(0o555)
        root.chmod(0o555)

    def _make_tree_writable(self, root: Path) -> None:
        root.chmod(0o755)
        for path in root.rglob("*"):
            if path.is_dir():
                path.chmod(0o755)
            elif path.is_file():
                executable = bool(stat.S_IMODE(path.stat().st_mode) & 0o111)
                path.chmod(0o755 if executable else 0o644)

    def test_minimal_install_creates_managed_copy_and_codex_discovers_three_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_root = self._build_package(root)
            package_before = self._tree_digest(package_root)
            personal_root = root
            marketplace_path = (
                personal_root / ".agents" / "plugins" / "marketplace.json"
            )
            fake_codex = self._fake_codex(root)

            installed = subprocess.run(
                [
                    str(package_root / "install.command"),
                    "--marketplace-path",
                    str(marketplace_path),
                    "--codex-bin",
                    str(fake_codex),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(
                installed.returncode,
                0,
                installed.stdout + installed.stderr,
            )
            self.assertIn("PASS installed shotloom", installed.stdout)
            self.assertIn("PASS Codex discovered shotloom", installed.stdout)

            managed_copy = personal_root / "plugins" / "shotloom"
            self.assertTrue(
                (managed_copy / ".codex-plugin" / "plugin.json").is_file()
            )
            self.assertEqual(
                sorted(path.name for path in (managed_copy / "skills").iterdir()),
                [
                    "minimax-h3-replica",
                    "seedance-25-replica",
                    "seedance-run",
                    "video-shot-refinement",
                    "video-subtitle-removal",
                    "viral-replica",
                ],
            )
            marketplace = json.loads(
                marketplace_path.read_text(encoding="utf-8")
            )
            self.assertEqual(marketplace["name"], "personal")
            self.assertEqual(
                marketplace["plugins"],
                [
                    {
                        "name": "shotloom",
                        "source": {
                            "source": "local",
                            "path": "./plugins/shotloom",
                        },
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_INSTALL",
                        },
                        "category": "Productivity",
                    }
                ],
            )
            self.assertEqual(package_before, self._tree_digest(package_root))

            repeated = subprocess.run(
                [
                    str(package_root / "install.command"),
                    "--marketplace-path",
                    str(marketplace_path),
                    "--codex-bin",
                    str(fake_codex),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(repeated.returncode, 2)
            self.assertIn("already exists", repeated.stderr)
            self.assertIn("upgrade is outside this MVP", repeated.stderr)

    def test_installed_plugin_runs_clean_no_spend_handoff_resume_and_specialist_smokes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_root = self._build_package(root)
            personal_root = root / "personal"
            marketplace_path = (
                personal_root / ".agents" / "plugins" / "marketplace.json"
            )
            fake_codex = self._fake_codex(root)
            install = subprocess.run(
                [
                    str(package_root / "install.command"),
                    "--marketplace-path",
                    str(marketplace_path),
                    "--codex-bin",
                    str(fake_codex),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(install.returncode, 0, install.stdout + install.stderr)

            managed_copy = personal_root / "plugins" / "shotloom"
            legacy_checkout = root / "legacy-checkout"
            development_workspace = root / "workspace-dev"
            arbitrary_cwd = root / "arbitrary-cwd"
            for directory in (
                legacy_checkout,
                development_workspace,
                arbitrary_cwd,
            ):
                directory.mkdir()
                (directory / "sentinel.txt").write_text(
                    directory.name + "\n",
                    encoding="utf-8",
                )
            untouched = {
                path: self._tree_digest(path)
                for path in (
                    legacy_checkout,
                    development_workspace,
                    arbitrary_cwd,
                )
            }
            workspace = root / "fresh-workspace"
            report_path = workspace / "no-spend-smoke.json"
            runtime_python = self._host_runtime(root)

            self._make_tree_read_only(managed_copy)
            managed_before = self._tree_digest(managed_copy)
            try:
                smoke = subprocess.run(
                    [
                        str(runtime_python),
                        str(managed_copy / "scripts" / "run-no-spend-smoke.py"),
                        "--workspace",
                        str(workspace),
                        "--report",
                        str(report_path),
                    ],
                    cwd=arbitrary_cwd,
                    text=True,
                    capture_output=True,
                    env={
                        **os.environ,
                        "PYTHONDONTWRITEBYTECODE": "1",
                    },
                )
                managed_after = self._tree_digest(managed_copy)
            finally:
                self._make_tree_writable(managed_copy)

            self.assertEqual(
                smoke.returncode,
                0,
                smoke.stdout + smoke.stderr,
            )
            for label in (
                "看懂原片",
                "改好分镜",
                "写视频脚本",
                "生成视频",
                "质检交付",
            ):
                self.assertIn(label, smoke.stdout)

            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["overall"], "PASS")
            self.assertEqual(report["claim"], "本机可用、行为等效的轻量插件 MVP")
            self.assertFalse(report["customer_ready"])
            self.assertEqual(report["final_status"], "seedance_inputs_prepared")
            self.assertEqual(
                report["progress"],
                ["看懂原片", "改好分镜", "写视频脚本", "生成视频", "质检交付"],
            )
            self.assertEqual(
                report["provider_recorder"],
                {
                    "real_task_count": 0,
                    "paid_task_count": 0,
                    "media_generation_task_count": 0,
                    "unmatched_request_count": 0,
                    "unregistered_outbound_attempt_count": 0,
                    "recorder_fallback_count": 0,
                },
            )
            self.assertEqual(report["resume"]["result"], "PASS")
            self.assertEqual(report["resume"]["replayed_stage_count"], 0)
            self.assertEqual(
                report["resume"]["replayed_external_work_count"],
                0,
            )
            self.assertTrue(report["resume"]["interruption_simulated"])
            self.assertEqual(
                report["resume"]["interrupted_after_status"],
                "seedance_inputs_prepared",
            )
            self.assertEqual(
                report["resume"]["changed_completed_artifact_count"],
                0,
            )
            self.assertRegex(
                report["resume"]["checkpoint_artifact_sha256"],
                r"^[0-9a-f]{64}$",
            )
            self.assertNotIn(
                "required assets missing",
                report["resume"]["runner_output"],
            )
            self.assertIn(
                "Outcome type: `COST_GATE`",
                report["resume"]["runner_output"],
            )
            self.assertEqual(
                sorted(report["specialist_smokes"]),
                ["video-shot-refinement", "video-subtitle-removal"],
            )
            for specialist in report["specialist_smokes"].values():
                self.assertEqual(specialist["overall"], "PASS")
                self.assertEqual(specialist["paid_task_count"], 0)
                self.assertTrue(specialist["input_protected"])
                self.assertTrue(
                    specialist["production_boundary_executed"]
                )
            shot_smoke = report["specialist_smokes"][
                "video-shot-refinement"
            ]
            self.assertEqual(
                shot_smoke["boundary_reason"],
                "expensive generation requires --allow-paid",
            )
            self.assertEqual(
                shot_smoke["production_policy_function"],
                "run_next_loop_round.cost_stop_reason",
            )
            subtitle_smoke = report["specialist_smokes"][
                "video-subtitle-removal"
            ]
            self.assertEqual(subtitle_smoke["classification"], "clean")
            self.assertEqual(
                subtitle_smoke["checker"],
                "independent_product_fixture_checker",
            )
            self.assertEqual(subtitle_smoke["evidence_frame_count"], 16)
            self.assertTrue(
                Path(subtitle_smoke["detection_report"]).is_file()
            )
            self.assertTrue(
                Path(subtitle_smoke["detection_qc"]).is_file()
            )

            inspection = report["inspection_paths"]
            self.assertTrue(Path(inspection["handoff"]).is_file())
            self.assertTrue(Path(inspection["image"]).is_file())
            self.assertTrue(Path(inspection["prompt"]).is_file())
            self.assertTrue(Path(inspection["audio"]).is_file())
            self.assertTrue(Path(inspection["manifest"]).is_file())
            self.assertTrue(Path(inspection["qc"]).is_file())
            self.assertTrue(Path(inspection["smoke_report"]).is_file())
            canonical_workspace = Path(inspection["image"]).parents[4]
            with (
                canonical_workspace
                / ".viral-replica"
                / "state"
                / "jobs.csv"
            ).open(newline="", encoding="utf-8") as handle:
                jobs = list(csv.DictReader(handle))
            self.assertEqual(len(jobs), 1)
            for field, collection in (
                ("video_path", "videos"),
                ("product_assets", "products"),
                ("audio_assets", "audio"),
            ):
                self.assertTrue(
                    Path(jobs[0][field]).is_relative_to(
                        canonical_workspace / "references" / collection
                    ),
                    jobs[0][field],
                )
                self.assertTrue(Path(jobs[0][field]).is_file())
            for bridge in (
                "assets",
                "output",
                "references",
            ):
                self.assertFalse(
                    (
                        canonical_workspace
                        / ".viral-replica"
                        / "state"
                        / bridge
                    ).exists()
                )
            for bridge in ("gates", "rules", "tools", "workers"):
                contract_bridge = (
                    canonical_workspace
                    / ".viral-replica"
                    / "state"
                    / bridge
                )
                self.assertTrue(contract_bridge.is_symlink())
                self.assertTrue(
                    contract_bridge.resolve().is_relative_to(
                        (managed_copy / "engine").resolve()
                    )
                )
            self.assertEqual(managed_before, managed_after)
            for path, digest in untouched.items():
                self.assertEqual(digest, self._tree_digest(path), path)


if __name__ == "__main__":
    unittest.main()
