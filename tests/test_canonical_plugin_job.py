import csv
import hashlib
import json
import os
import re
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


class CanonicalPluginJobTest(unittest.TestCase):
    def _public_launcher(self, package_root: Path) -> Path:
        skill_root = package_root / "skills" / "viral-replica"
        skill_text = (skill_root / "SKILL.md").read_text(encoding="utf-8")
        match = re.search(
            r"Launcher path \(relative to this Skill\): "
            r"`(\.\./\.\./scripts/run-canonical-job\.py)`",
            skill_text,
        )
        self.assertIsNotNone(match, skill_text)
        return (skill_root / match.group(1)).resolve()

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
            version="0.4.0",
            signing_private_key=private_key,
            signing_public_key=public_key,
            release_registry=root / "release-registry.json",
        ).package_root

    def _write_source_video(self, path: Path) -> None:
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=blue:s=32x32:d=1.25",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=44100:cl=mono",
                "-shortest",
                "-c:v",
                "mpeg4",
                "-c:a",
                "aac",
                str(path),
            ],
            check=True,
            capture_output=True,
        )

    def _snapshot(self, root: Path) -> dict[str, tuple[int, int, str]]:
        snapshot = {}
        for path in sorted(root.rglob("*")):
            if path.is_file():
                snapshot[path.relative_to(root).as_posix()] = (
                    stat.S_IMODE(path.stat().st_mode),
                    path.stat().st_size,
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
        return snapshot

    def _make_tree_read_only(self, root: Path) -> None:
        for path in sorted(root.rglob("*"), reverse=True):
            if path.is_file():
                executable = bool(stat.S_IMODE(path.stat().st_mode) & 0o111)
                path.chmod(0o555 if executable else 0o444)
            elif path.is_dir():
                path.chmod(0o555)
        root.chmod(0o555)

    def _make_tree_writable(self, root: Path) -> None:
        if not root.exists():
            return
        root.chmod(0o755)
        for path in root.rglob("*"):
            if path.is_dir():
                path.chmod(0o755)
            elif path.is_file():
                executable = bool(stat.S_IMODE(path.stat().st_mode) & 0o111)
                path.chmod(0o755 if executable else 0o644)

    def _invoke(
        self,
        package_root: Path,
        workspace: Path,
        source_video: Path,
        product_assets: Path,
        *,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        launcher = self._public_launcher(package_root)
        return subprocess.run(
            [
                sys.executable,
                str(launcher),
                "--workspace",
                str(workspace),
                "--video",
                str(source_video),
                "--product-name",
                "Synthetic Toner",
                "--product-assets",
                str(product_assets),
            ],
            cwd=cwd,
            text=True,
            capture_output=True,
            env={
                **os.environ,
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )

    def test_public_launcher_creates_one_canonical_job_and_first_runner_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_root = self._build_package(root)
            workspace = root / "selected-workspace"
            other_workspace = root / "other-workspace"
            legacy_checkout = root / "viral-replica-loop"
            arbitrary_cwd = root / "arbitrary-cwd"
            for directory in (
                workspace,
                other_workspace,
                legacy_checkout,
                arbitrary_cwd,
            ):
                directory.mkdir()
            (other_workspace / "sentinel.txt").write_text(
                "other workspace\n",
                encoding="utf-8",
            )
            (legacy_checkout / "sentinel.txt").write_text(
                "legacy checkout\n",
                encoding="utf-8",
            )
            (arbitrary_cwd / "sentinel.txt").write_text(
                "arbitrary cwd\n",
                encoding="utf-8",
            )
            source_video = root / "source.mp4"
            self._write_source_video(source_video)
            product_assets = root / "product-assets"
            product_assets.mkdir()
            (product_assets / "product.txt").write_text(
                "synthetic product fixture\n",
                encoding="utf-8",
            )

            untouched_before = {
                "other": self._snapshot(other_workspace),
                "legacy": self._snapshot(legacy_checkout),
                "cwd": self._snapshot(arbitrary_cwd),
            }
            self._make_tree_read_only(package_root)
            package_before = self._snapshot(package_root)
            secret = "service-authorization-secret-123456789"
            try:
                launcher = self._public_launcher(package_root)
                result = subprocess.run(
                    [
                        sys.executable,
                        str(launcher),
                        "--workspace",
                        str(workspace),
                        "--video",
                        str(source_video),
                        "--product-name",
                        "Synthetic Toner",
                        "--product-assets",
                        str(product_assets),
                        "--notes",
                        "生成视频前停",
                    ],
                    cwd=arbitrary_cwd,
                    text=True,
                    capture_output=True,
                    env={
                        **os.environ,
                        "MATPOOL_API_KEY": secret,
                        "PYTHONDONTWRITEBYTECODE": "1",
                    },
                )
                package_after = self._snapshot(package_root)
            finally:
                self._make_tree_writable(package_root)

            self.assertEqual(
                result.returncode,
                0,
                result.stdout + result.stderr,
            )
            self.assertIn("看懂原片", result.stdout)
            self.assertIn("job-001", result.stdout)

            job_root = workspace / "jobs" / "job-001"
            intake_path = job_root / "input" / "intake.json"
            decision_path = (
                workspace
                / ".viral-replica"
                / "state"
                / "RUNNER_LAST_DECISION.md"
            )
            context_path = (
                workspace
                / ".viral-replica"
                / "state"
                / "execution-context-job-001.json"
            )
            self.assertTrue(intake_path.is_file())
            self.assertTrue(decision_path.is_file())
            self.assertTrue(context_path.is_file())

            intake = json.loads(intake_path.read_text(encoding="utf-8"))
            self.assertFalse(intake["target_duration"]["explicitly_requested"])
            duration = float(
                intake["target_duration"]["value"].removesuffix("s")
            )
            self.assertGreater(duration, 1.0)
            self.assertLess(duration, 2.0)
            source_reference = Path(intake["source_video"]["path"])
            self.assertTrue(source_reference.is_file())
            self.assertTrue(
                source_reference.is_relative_to(
                    workspace.resolve() / "references" / "videos"
                ),
                str(source_reference),
            )

            with (
                workspace
                / ".viral-replica"
                / "state"
                / "jobs.csv"
            ).open(newline="", encoding="utf-8") as handle:
                jobs = list(csv.DictReader(handle))
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["id"], "job-001")
            self.assertEqual(jobs[0]["status"], "pending")
            self.assertEqual(jobs[0]["next_stage"], "source_blueprint")
            self.assertEqual(
                Path(jobs[0]["output_dir"]).resolve(),
                (job_root / "work").resolve(),
            )
            self.assertTrue(
                Path(jobs[0]["product_assets"]).is_relative_to(
                    workspace.resolve() / "references" / "products"
                )
            )
            provenance = json.loads(
                (
                    job_root / "input" / "job_provenance.json"
                ).read_text(encoding="utf-8")
            )
            binding = provenance["reference_binding"]
            self.assertEqual(
                Path(binding["source_video"]["path"]),
                source_reference,
            )
            self.assertTrue(binding["source_video"]["sha256"])
            self.assertTrue(binding["product_assets"]["sha256"])

            context = json.loads(context_path.read_text(encoding="utf-8"))
            self.assertEqual(
                Path(context["plugin_root"]).resolve(),
                package_root.resolve(),
            )
            self.assertEqual(
                Path(context["workspace_root"]).resolve(),
                workspace.resolve(),
            )
            self.assertEqual(context["job_id"], "job-001")
            self.assertTrue(context["workflow_contract"]["sha256"])
            self.assertFalse(
                (workspace / ".viral-replica" / "state" / "rules").exists()
            )
            contract_paths = {
                item["path"]
                for item in context["workflow_contract"]["resources"]
            }
            self.assertTrue(
                {
                    "skills/viral-replica/SKILL.md",
                    "engine/tools/canonical_plugin_job.py",
                    "engine/tools/job_intake.py",
                    "engine/tools/product_profile.py",
                    "engine/workers/source_blueprint_worker.md",
                    "profiles/builtin/generic_product.json",
                }.issubset(contract_paths)
            )
            decision = decision_path.read_text(encoding="utf-8")
            self.assertIn("看懂原片", decision)
            self.assertIn("source_blueprint_gate.md", decision)
            self.assertIn("prepare_source_blueprint.py", decision)

            workspace_bytes = b"\n".join(
                path.read_bytes()
                for path in workspace.rglob("*")
                if path.is_file()
            )
            self.assertNotIn(secret.encode("utf-8"), workspace_bytes)
            self.assertEqual(package_before, package_after)
            self.assertEqual(
                untouched_before["other"],
                self._snapshot(other_workspace),
            )
            self.assertEqual(
                untouched_before["legacy"],
                self._snapshot(legacy_checkout),
            )
            self.assertEqual(
                untouched_before["cwd"],
                self._snapshot(arbitrary_cwd),
            )
            self.assertTrue(source_video.is_file())
            self.assertTrue((product_assets / "product.txt").is_file())

    def test_invalid_workspace_or_missing_plugin_resource_stops_before_job_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_root = self._build_package(root)
            source_video = root / "source.mp4"
            self._write_source_video(source_video)
            product_assets = root / "product-assets"
            product_assets.mkdir()
            cwd = root / "cwd"
            cwd.mkdir()

            missing_workspace = root / "missing-workspace"
            missing = self._invoke(
                package_root,
                missing_workspace,
                source_video,
                product_assets,
                cwd=cwd,
            )
            self.assertEqual(missing.returncode, 2)
            self.assertIn("Workspace does not exist", missing.stderr)
            self.assertFalse(missing_workspace.exists())

            real_workspace = root / "real-workspace"
            real_workspace.mkdir()
            linked_workspace = root / "linked-workspace"
            linked_workspace.symlink_to(real_workspace, target_is_directory=True)
            rejected = self._invoke(
                package_root,
                linked_workspace,
                source_video,
                product_assets,
                cwd=cwd,
            )
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("one real directory", rejected.stderr)
            self.assertEqual(list(real_workspace.iterdir()), [])

            unrecognized = root / "unrecognized-workspace"
            (unrecognized / "jobs").mkdir(parents=True)
            (unrecognized / "workspace.yaml").write_text(
                "\n".join(
                    [
                        "schema_version: 1",
                        "workspace_kind: viral-replica",
                        "default_handoff_mode: web",
                        "supported_host: apple-silicon-macos",
                    ]
                ),
                encoding="utf-8",
            )
            (unrecognized / "jobs" / "mystery.txt").write_text(
                "not a canonical Job\n",
                encoding="utf-8",
            )
            unrecognized_before = self._snapshot(unrecognized)
            rejected = self._invoke(
                package_root,
                unrecognized,
                source_video,
                product_assets,
                cwd=cwd,
            )
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("unrecognized content", rejected.stderr)
            self.assertEqual(unrecognized_before, self._snapshot(unrecognized))

            unknown_system = root / "unknown-system-workspace"
            shutil.copytree(
                package_root / "workspace-template",
                unknown_system,
            )
            (
                unknown_system
                / ".viral-replica"
                / "unknown.txt"
            ).write_text("unrecognized system content\n", encoding="utf-8")
            unknown_system_before = self._snapshot(unknown_system)
            rejected = self._invoke(
                package_root,
                unknown_system,
                source_video,
                product_assets,
                cwd=cwd,
            )
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("unrecognized content", rejected.stderr)
            self.assertEqual(
                unknown_system_before,
                self._snapshot(unknown_system),
            )

            read_only = root / "read-only-workspace"
            read_only.mkdir()
            read_only.chmod(0o555)
            try:
                rejected = self._invoke(
                    package_root,
                    read_only,
                    source_video,
                    product_assets,
                    cwd=cwd,
                )
            finally:
                read_only.chmod(0o755)
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("not writable", rejected.stderr)
            self.assertEqual(list(read_only.iterdir()), [])

            nested_read_only = root / "nested-read-only-workspace"
            shutil.copytree(
                package_root / "workspace-template",
                nested_read_only,
            )
            nested_state = nested_read_only / ".viral-replica" / "state"
            nested_state.mkdir()
            nested_state.chmod(0o555)
            nested_before = self._snapshot(nested_read_only)
            try:
                rejected = self._invoke(
                    package_root,
                    nested_read_only,
                    source_video,
                    product_assets,
                    cwd=cwd,
                )
            finally:
                nested_state.chmod(0o755)
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("not writable", rejected.stderr)
            self.assertEqual(
                nested_before,
                self._snapshot(nested_read_only),
            )

            package_before = self._snapshot(package_root)
            overlap = self._invoke(
                package_root,
                package_root,
                source_video,
                product_assets,
                cwd=cwd,
            )
            self.assertEqual(overlap.returncode, 2)
            self.assertIn("overlaps Plugin Root", overlap.stderr)
            self.assertEqual(package_before, self._snapshot(package_root))

            broken_root = root / "broken-package" / "shotloom"
            shutil.copytree(package_root, broken_root)
            (
                broken_root
                / "engine"
                / "gates"
                / "source_blueprint_gate.md"
            ).unlink()
            broken_workspace = root / "broken-workspace"
            broken_workspace.mkdir()
            broken = self._invoke(
                broken_root,
                broken_workspace,
                source_video,
                product_assets,
                cwd=cwd,
            )
            self.assertEqual(broken.returncode, 2)
            self.assertIn("missing plugin resource", broken.stderr)
            self.assertIn("root fallback is forbidden", broken.stderr)
            self.assertEqual(list(broken_workspace.iterdir()), [])

    def test_interrupted_job_staging_and_missing_state_row_resume_one_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_root = self._build_package(root)
            source_video = root / "source.mp4"
            self._write_source_video(source_video)
            product_assets = root / "product-assets"
            product_assets.mkdir()
            cwd = root / "cwd"
            cwd.mkdir()
            workspace = root / "workspace"
            shutil.copytree(
                package_root / "workspace-template",
                workspace,
            )
            interrupted = workspace / "jobs" / ".job-001.staging"
            (interrupted / "input").mkdir(parents=True)
            (interrupted / "input" / "partial.json").write_text(
                '{"status":"interrupted"}\n',
                encoding="utf-8",
            )

            first = self._invoke(
                package_root,
                workspace,
                source_video,
                product_assets,
                cwd=cwd,
            )
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertFalse(interrupted.exists())
            self.assertIn("Created job-001", first.stdout)

            state_root = workspace / ".viral-replica" / "state"
            (state_root / "RUNNER_LAST_DECISION.md").unlink()
            (state_root / "jobs.csv").unlink()
            second = self._invoke(
                package_root,
                workspace,
                source_video,
                product_assets,
                cwd=cwd,
            )
            self.assertEqual(
                second.returncode,
                0,
                second.stdout + second.stderr,
            )
            self.assertIn("Resumed job-001", second.stdout)
            with (state_root / "jobs.csv").open(
                newline="",
                encoding="utf-8",
            ) as handle:
                jobs = list(csv.DictReader(handle))
            self.assertEqual([job["id"] for job in jobs], ["job-001"])
            self.assertTrue(
                (state_root / "RUNNER_LAST_DECISION.md").is_file()
            )
            self.assertTrue(
                (state_root / "execution-context-job-001.json").is_file()
            )
            self.assertFalse(
                (state_root / "execution-context.json").exists()
            )

    def test_upgrade_resumes_with_the_existing_stable_workflow_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_v1 = root / "stable" / "shotloom"
            package_v1.parent.mkdir()
            shutil.copytree(self._build_package(root), package_v1)
            manifest_path = package_v1 / ".codex-plugin" / "plugin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["version"] = "0.6.0"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            workspace = root / "workspace"
            workspace.mkdir()
            source_video = root / "source.mp4"
            self._write_source_video(source_video)
            product_assets = root / "product-assets"
            product_assets.mkdir()
            cwd = root / "cwd"
            cwd.mkdir()

            created = self._invoke(
                package_v1,
                workspace,
                source_video,
                product_assets,
                cwd=cwd,
            )
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            state_root = workspace / ".viral-replica" / "state"
            context_path = state_root / "execution-context-job-001.json"
            original_context = context_path.read_bytes()

            package_v2 = root / "upgraded" / "shotloom"
            shutil.copytree(package_v1, package_v2)
            upgraded_manifest_path = package_v2 / ".codex-plugin" / "plugin.json"
            upgraded_manifest = json.loads(
                upgraded_manifest_path.read_text(encoding="utf-8")
            )
            upgraded_manifest["version"] = "0.6.2"
            upgraded_manifest_path.write_text(
                json.dumps(upgraded_manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            resumed = self._invoke(
                package_v2,
                workspace,
                source_video,
                product_assets,
                cwd=cwd,
            )

            self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
            self.assertIn("Resumed job-001", resumed.stdout)
            self.assertEqual(
                sorted(path.name for path in (workspace / "jobs").glob("job-*")),
                ["job-001"],
            )
            context = json.loads(
                context_path.read_text(encoding="utf-8")
            )
            self.assertEqual(Path(context["plugin_root"]), package_v1.resolve())
            self.assertEqual(context_path.read_bytes(), original_context)

    def test_execution_context_rejects_cwd_root_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_root = self._build_package(root)
            workspace = root / "workspace"
            workspace.mkdir()
            source_video = root / "source.mp4"
            self._write_source_video(source_video)
            product_assets = root / "product-assets"
            product_assets.mkdir()
            cwd = root / "cwd"
            cwd.mkdir()

            created = self._invoke(
                package_root,
                workspace,
                source_video,
                product_assets,
                cwd=cwd,
            )
            self.assertEqual(
                created.returncode,
                0,
                created.stdout + created.stderr,
            )
            state_root = workspace / ".viral-replica" / "state"
            context_path = state_root / "execution-context-job-001.json"
            context = json.loads(context_path.read_text(encoding="utf-8"))
            runner = (
                package_root
                / "engine"
                / "tools"
                / "run_next_loop_round.py"
            )

            cases = (
                ("missing-plugin-root.json", "plugin_root", None, package_root),
                ("relative-workspace-root.json", "workspace_root", ".", workspace),
            )
            for filename, field, value, induced_cwd in cases:
                with self.subTest(field=field):
                    broken = dict(context)
                    if value is None:
                        broken.pop(field)
                    else:
                        broken[field] = value
                    broken_path = state_root / filename
                    broken_path.write_text(
                        json.dumps(broken, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(runner),
                            "--execution-context",
                            str(broken_path),
                        ],
                        cwd=induced_cwd,
                        text=True,
                        capture_output=True,
                        env={
                            **os.environ,
                            "PYTHONDONTWRITEBYTECODE": "1",
                        },
                    )
                    self.assertEqual(result.returncode, 2)
                    self.assertIn(
                        f"{field} must be a non-empty absolute path",
                        result.stderr,
                    )


if __name__ == "__main__":
    unittest.main()
