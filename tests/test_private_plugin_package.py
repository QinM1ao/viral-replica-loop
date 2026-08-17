import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from private_plugin_package import (  # noqa: E402
    PackageBuildError,
    build_package,
    record_release_identity,
    scan_package_tree,
)


class PrivatePluginPackageTest(unittest.TestCase):
    def _plugin_validator(self) -> Path:
        configured = os.environ.get("PLUGIN_CREATOR_VALIDATOR")
        candidate = (
            Path(configured).expanduser()
            if configured
            else Path.home()
            / ".codex"
            / "skills"
            / "plugin-creator"
            / "scripts"
            / "validate_plugin.py"
        )
        if not candidate.is_file():
            self.skipTest(
                "official Plugin Creator validator is not installed; "
                "package-local validation still runs"
            )
        return candidate

    def _plugin_validator_python(self) -> str:
        candidates = [
            sys.executable,
            shutil.which("python3"),
        ]
        for candidate in dict.fromkeys(
            str(value) for value in candidates if value
        ):
            available = subprocess.run(
                [candidate, "-c", "import yaml"],
                capture_output=True,
                text=True,
            )
            if available.returncode == 0:
                return candidate
        self.skipTest(
            "official Plugin Creator validator has no local Python "
            "runtime with PyYAML"
        )

    def _generate_signing_keypair(self, root: Path) -> tuple[Path, Path]:
        root.mkdir(parents=True, exist_ok=True)
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

    def test_build_emits_canonical_plugin_layout_and_passes_plugin_creator_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_root = Path(tmp)
            private_key, public_key = self._generate_signing_keypair(out_root)

            result = build_package(
                source_root=ROOT,
                out_root=out_root / "dist",
                version="0.1.0",
                signing_private_key=private_key,
                signing_public_key=public_key,
                release_registry=out_root / "release-registry.json",
            )

            package_root = result.package_root
            self.assertEqual(package_root.name, "shotloom")
            self.assertTrue((package_root / ".codex-plugin" / "plugin.json").is_file())
            self.assertTrue((package_root / "marketplace.json").is_file())
            self.assertTrue((package_root / "install.command").is_file())
            for rel in (
                "engine",
                "engine/docs",
                "engine/tests",
                "engine/migration/policies",
                "engine/tools/seedance_taskcode_runner.py",
                "engine/workers/caption_finishing_worker.md",
                "profiles/builtin",
                "workspace-template",
                "assets/fixtures",
                "assets/fixtures/v1/fixture_origin.json",
                "assets/fixtures/v1/provider/recording.json",
                "engine/tools/product_fixture_suite.py",
                "engine/tools/provider_fixture_recorder.py",
                "tests",
                "docs",
                "docs/product-fixtures.md",
                "docs/no-spend-smoke.md",
                "scripts",
                "scripts/run-no-spend-smoke.py",
            ):
                self.assertTrue((package_root / rel).exists(), rel)

            source_fixture_root = ROOT / "product-fixtures" / "v1"
            packaged_fixture_root = package_root / "assets" / "fixtures" / "v1"
            source_files = {
                path.relative_to(source_fixture_root).as_posix(): path.read_bytes()
                for path in source_fixture_root.rglob("*")
                if path.is_file()
            }
            packaged_files = {
                path.relative_to(packaged_fixture_root).as_posix(): path.read_bytes()
                for path in packaged_fixture_root.rglob("*")
                if path.is_file()
            }
            self.assertEqual(source_files, packaged_files)

            required_origin_fields = {
                "source",
                "license_or_authorization",
                "non_client",
                "content_summary",
                "expected_logical_roles",
            }
            timing_origin = json.loads(
                (package_root / "assets" / "fixtures" / "fixture_origin.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(required_origin_fields.issubset(timing_origin))
            product_origin = json.loads(
                (packaged_fixture_root / "fixture_origin.json").read_text(
                    encoding="utf-8"
                )
            )
            for fixture in product_origin["fixtures"]:
                self.assertTrue(required_origin_fields.issubset(fixture))

            fixture_validation = subprocess.run(
                [
                    sys.executable,
                    str(package_root / "engine" / "tools" / "product_fixture_suite.py"),
                    str(packaged_fixture_root),
                ],
                capture_output=True,
                text=True,
                cwd=out_root,
                env={"PATH": os.environ["PATH"]},
            )
            self.assertEqual(fixture_validation.returncode, 0, fixture_validation.stdout)
            self.assertIn('"paid_task_count": 0', fixture_validation.stdout)
            self.assertIn('"media_generation_task_count": 0', fixture_validation.stdout)

            skill_names = sorted(
                path.name
                for path in (package_root / "skills").iterdir()
                if path.is_dir()
            )
            self.assertEqual(
                skill_names,
                [
                    "minimax-h3-replica",
                    "seedance-25-replica",
                    "seedance-run",
                    "video-shot-refinement",
                    "video-subtitle-removal",
                    "viral-replica",
                ],
            )
            self.assertFalse((package_root / "skills" / "video-replication").exists())
            public_skill = (
                package_root / "skills" / "viral-replica" / "SKILL.md"
            ).read_text(encoding="utf-8")
            self.assertIn("--prepare-runtime", public_skill)
            self.assertIn(
                "If the user explicitly requests ordinary Seedance 2.0 API generation",
                public_skill,
            )
            self.assertIn("../seedance-run/SKILL.md", public_skill)
            seedance_run_skill = (
                package_root / "skills" / "seedance-run" / "SKILL.md"
            ).read_text(encoding="utf-8")
            self.assertIn("handoff_mode=api", seedance_run_skill)
            self.assertIn("engine/workers/generation_worker.md", seedance_run_skill)
            self.assertIn("engine/tools/generation_fanout.py", seedance_run_skill)
            self.assertIn("engine/tools/seedance_taskcode_runner.py", seedance_run_skill)
            self.assertIn("Never invoke a global Seedance Skill", seedance_run_skill)
            self.assertIn("Status=Active", seedance_run_skill)
            self.assertIn("asset://asset-...", seedance_run_skill)
            self.assertIn("public `.mp3` URL", seedance_run_skill)
            self.assertIn("provider outcome is unknown", seedance_run_skill)
            minimax_h3_skill = (
                package_root / "skills" / "minimax-h3-replica" / "SKILL.md"
            ).read_text(encoding="utf-8")
            self.assertIn("explicitly requests MiniMax H3", minimax_h3_skill)
            self.assertIn(
                "engine/.agents/skills/minimax-h3-replica/SKILL.md",
                minimax_h3_skill,
            )
            self.assertIn("audio_master_gate.py", minimax_h3_skill)
            self.assertIn("direct user listening approval", minimax_h3_skill)
            self.assertTrue(
                (
                    package_root
                    / "engine"
                    / ".agents"
                    / "skills"
                    / "minimax-h3-replica"
                    / "scripts"
                    / "audio_master_gate.py"
                ).is_file()
            )
            self.assertTrue(
                (
                    package_root
                    / "engine"
                    / ".agents"
                    / "skills"
                    / "minimax-h3-replica"
                    / "scripts"
                    / "voxcpm2_generate.py"
                ).is_file()
            )
            self.assertIn(
                "If the user explicitly requests MiniMax H3",
                public_skill,
            )
            h3_prompt_standard = (
                package_root
                / "engine"
                / ".agents"
                / "skills"
                / "minimax-h3-replica"
                / "references"
                / "ref2va-prompt-standard.md"
            ).read_text(encoding="utf-8")
            self.assertIn("subject_definitions:", h3_prompt_standard)
            self.assertIn("[Shot 2] At 00:01.067", h3_prompt_standard)
            self.assertIn("<Audio 1>: fully_copy", h3_prompt_standard)
            h3_request_standard = (
                package_root
                / "engine"
                / ".agents"
                / "skills"
                / "minimax-h3-replica"
                / "references"
                / "wujie-request.md"
            ).read_text(encoding="utf-8")
            self.assertIn("taskCode", h3_request_standard)
            self.assertIn("MiniMax-H3", h3_request_standard)
            self.assertIn("task_create", h3_request_standard)
            seedance_25_skill = (
                package_root / "skills" / "seedance-25-replica" / "SKILL.md"
            ).read_text(encoding="utf-8")
            self.assertIn("Depth is optional and disabled by", seedance_25_skill)
            self.assertIn("generated_voiceover", seedance_25_skill)
            self.assertIn("original_master_postmix", seedance_25_skill)
            self.assertIn("30-second", seedance_25_skill)
            worker = (
                package_root / "engine" / "workers" / "source_blueprint_worker.md"
            ).read_text(encoding="utf-8")
            self.assertIn('ENGINE_ROOT=', worker)
            self.assertIn('JOB_OUTPUT=', worker)
            self.assertNotIn("python3 tools/", worker)

            manifest = json.loads(
                (package_root / ".codex-plugin" / "plugin.json").read_text(
                    encoding="utf-8"
                )
            )
            marketplace = json.loads(
                (package_root / "marketplace.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["name"], "shotloom")
            self.assertEqual(manifest["author"]["name"], "ShotLoom")
            self.assertEqual(manifest["interface"]["displayName"], "ShotLoom")
            self.assertEqual(manifest["interface"]["developerName"], "ShotLoom")
            self.assertEqual(manifest["skills"], "./skills/")
            self.assertEqual(marketplace["plugins"][0]["name"], "shotloom")
            self.assertEqual(marketplace["plugins"][0]["source"]["path"], "./plugins/shotloom")

            package_validation = subprocess.run(
                [
                    sys.executable,
                    str(package_root / "scripts" / "validate-package.py"),
                    str(package_root),
                ],
                capture_output=True,
                text=True,
                cwd=out_root,
                env={"PATH": os.environ["PATH"]},
            )
            self.assertEqual(
                package_validation.returncode,
                0,
                package_validation.stdout + package_validation.stderr,
            )
            install = subprocess.run(
                [
                    str(package_root / "install.command"),
                    "--marketplace-path",
                    str(
                        out_root
                        / "personal"
                        / ".agents"
                        / "plugins"
                        / "marketplace.json"
                    ),
                    "--codex-bin",
                    str(out_root / "missing-codex"),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(install.returncode, 2)
            self.assertIn("Codex CLI is unavailable", install.stderr)

            broken_manifest = dict(manifest)
            broken_manifest["name"] = "wrong-name"
            (package_root / ".codex-plugin" / "plugin.json").write_text(
                json.dumps(broken_manifest),
                encoding="utf-8",
            )
            invalid = subprocess.run(
                [
                    sys.executable,
                    str(package_root / "scripts" / "validate-package.py"),
                    str(package_root),
                ],
                capture_output=True,
                text=True,
                cwd=out_root,
                env={"PATH": os.environ["PATH"]},
            )
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("manifest name", invalid.stdout)

    def test_official_plugin_creator_validation_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_root = Path(tmp)
            private_key, public_key = self._generate_signing_keypair(out_root)
            result = build_package(
                source_root=ROOT,
                out_root=out_root / "dist",
                version="0.1.1",
                signing_private_key=private_key,
                signing_public_key=public_key,
                release_registry=out_root / "release-registry.json",
            )
            subprocess.run(
                [
                    self._plugin_validator_python(),
                    str(self._plugin_validator()),
                    str(result.package_root),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

    def test_content_manifest_and_release_identity_cover_every_packaged_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_root = Path(tmp)
            private_key, public_key = self._generate_signing_keypair(out_root)

            result = build_package(
                source_root=ROOT,
                out_root=out_root / "dist",
                version="0.2.0",
                signing_private_key=private_key,
                signing_public_key=public_key,
                release_registry=out_root / "release-registry.json",
            )

            package_root = result.package_root
            content_manifest = json.loads(
                result.content_manifest_path.read_text(encoding="utf-8")
            )
            release_manifest = json.loads(
                result.release_manifest_path.read_text(encoding="utf-8")
            )
            packaged_files = sorted(
                str(path.relative_to(package_root))
                for path in package_root.rglob("*")
                if path.is_file()
            )
            manifest_files = sorted(
                entry["path"] for entry in content_manifest["files"]
            )
            self.assertEqual(packaged_files, manifest_files)
            self.assertEqual(content_manifest["package_name"], "shotloom")
            self.assertEqual(content_manifest["version"], "0.2.0")
            self.assertTrue(all(entry["type"] == "file" for entry in content_manifest["files"]))
            self.assertTrue(all(isinstance(entry["bytes"], int) and entry["bytes"] >= 0 for entry in content_manifest["files"]))
            self.assertTrue(all(len(entry["sha256"]) == 64 for entry in content_manifest["files"]))

            self.assertEqual(release_manifest["package_name"], "shotloom")
            self.assertEqual(release_manifest["version"], "0.2.0")
            signed_manifest = release_manifest["signed_release_manifest"]
            release_payload = signed_manifest["payload"]
            self.assertEqual(release_payload["key_id"], "shotloom-rsa-sha256")
            self.assertRegex(
                release_manifest["release_identity"],
                r"^0\.2\.0\+[0-9a-f]{64}$",
            )
            self.assertEqual(
                release_payload["content_manifest_sha256"],
                result.content_manifest_sha256,
            )
            self.assertEqual(
                release_manifest["signed_manifest_sha256"],
                result.release_identity.split("+", 1)[1],
            )
            self.assertEqual(
                release_payload["archive_sha256"],
                result.archive_sha256,
            )
            self.assertEqual(signed_manifest["signature_algorithm"], "rsa-sha256")
            self.assertTrue(signed_manifest["signature"])

    def test_repeated_build_is_byte_identical_and_same_semver_different_bytes_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_root = Path(tmp)
            private_key, public_key = self._generate_signing_keypair(out_root)
            registry = out_root / "release-registry.json"

            first = build_package(
                source_root=ROOT,
                out_root=out_root / "dist-one",
                version="0.3.0",
                signing_private_key=private_key,
                signing_public_key=public_key,
                release_registry=registry,
            )
            second = build_package(
                source_root=ROOT,
                out_root=out_root / "dist-two",
                version="0.3.0",
                signing_private_key=private_key,
                signing_public_key=public_key,
                release_registry=registry,
            )

            self.assertEqual(first.archive_sha256, second.archive_sha256)
            self.assertEqual(
                first.archive_path.read_bytes(),
                second.archive_path.read_bytes(),
            )
            self.assertEqual(
                first.content_manifest_path.read_text(encoding="utf-8"),
                second.content_manifest_path.read_text(encoding="utf-8"),
            )
            self.assertEqual(
                first.release_manifest_path.read_text(encoding="utf-8"),
                second.release_manifest_path.read_text(encoding="utf-8"),
            )

            with self.assertRaises(PackageBuildError):
                record_release_identity(
                    registry_path=registry,
                    version="0.3.0",
                    package_name="shotloom",
                    archive_sha256="f" * 64,
                    release_identity="0.3.0+" + ("f" * 64),
                )

    def test_scan_rejects_forbidden_workspace_secrets_urls_and_global_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_root = Path(tmp) / "shotloom"
            (package_root / "docs").mkdir(parents=True)
            (package_root / "engine" / "output" / "job-001").mkdir(parents=True)
            (package_root / "assets" / "fixtures").mkdir(parents=True)
            (package_root / "docs" / "evidence").mkdir(parents=True)
            (package_root / "docs" / "bad.md").write_text(
                "\n".join(
                    [
                        "local path: /Users/qmio/.codex/skills/source-faithful-captions/SKILL.md",
                        "signed url: https://example.com/object.mp4?X-Amz-Signature=deadbeef",
                        "global skill dependency: ~/.codex/skills/seedance/scripts/seedance.py",
                    ]
                ),
                encoding="utf-8",
            )
            (package_root / "engine" / "output" / "job-001" / "secret.txt").write_text(
                "workspace leakage",
                encoding="utf-8",
            )
            (package_root / "assets" / "fixtures" / "customer.jpg").write_bytes(
                b"not an authorized product fixture"
            )
            (package_root / "docs" / "evidence" / "run.json").write_text(
                "{}",
                encoding="utf-8",
            )
            (package_root / "docs" / ".env").write_text(
                "API_KEY=abcdefghijklmnop",
                encoding="utf-8",
            )

            issues = scan_package_tree(package_root)
            joined = "\n".join(issues)
            self.assertIn("maintainer_absolute_path", joined)
            self.assertIn("signed_url", joined)
            self.assertIn("global_skill_dependency", joined)
            self.assertIn("historical_job_or_workspace_state", joined)
            self.assertIn("credential_material", joined)
            self.assertIn("credential_value", joined)
            self.assertIn("client_media_or_generated_asset", joined)

    def test_scan_rejects_media_not_declared_by_a_fixture_origin_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_root = Path(tmp) / "shotloom"
            fixture_root = package_root / "assets" / "fixtures" / "v1"
            fixture_root.mkdir(parents=True)
            (fixture_root / "fixture_origin.json").write_text(
                json.dumps({"schema_version": 1, "fixtures": [], "suite_files": []}),
                encoding="utf-8",
            )
            (fixture_root / "undeclared.y4m").write_text(
                "YUV4MPEG2 W2 H2 F1:1 Ip A1:1 Cmono\nFRAME\nABCD\n",
                encoding="utf-8",
            )

            self.assertIn(
                "client_media_or_generated_asset: assets/fixtures/v1/undeclared.y4m",
                scan_package_tree(package_root),
            )

    def test_scan_rejects_undeclared_product_svg(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_root = Path(tmp) / "shotloom"
            fixture_root = package_root / "assets" / "fixtures"
            fixture_root.mkdir(parents=True)
            (fixture_root / "customer-product.svg").write_text(
                '<svg xmlns="http://www.w3.org/2000/svg"><text>Client SKU</text></svg>',
                encoding="utf-8",
            )

            self.assertIn(
                "client_media_or_generated_asset: "
                "assets/fixtures/customer-product.svg",
                scan_package_tree(package_root),
            )

    def test_unknown_fixture_origin_cannot_authorize_customer_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_root = Path(tmp) / "shotloom"
            forged_root = package_root / "assets" / "fixtures" / "forged"
            forged_root.mkdir(parents=True)
            media = forged_root / "customer.mp4"
            media.write_bytes(b"forged customer media")
            digest = hashlib.sha256(media.read_bytes()).hexdigest()
            (forged_root / "fixture_origin.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "fixtures": [
                            {
                                "fixture_id": "forged-customer-fixture",
                                "source": "claimed synthetic source",
                                "license_or_authorization": "claimed authorization",
                                "non_client": True,
                                "content_summary": "claimed non-client media",
                                "expected_logical_roles": ["source_video"],
                                "sha256": digest,
                                "creation_tool": "unknown",
                                "redistribution_rights": "claimed",
                                "files": [
                                    {
                                        "path": "customer.mp4",
                                        "sha256": digest,
                                        "bytes": media.stat().st_size,
                                    }
                                ],
                            }
                        ],
                        "suite_files": [],
                    }
                ),
                encoding="utf-8",
            )

            issues = scan_package_tree(package_root)
            self.assertIn(
                "unknown_fixture_origin: assets/fixtures/forged/fixture_origin.json",
                issues,
            )
            self.assertIn(
                "client_media_or_generated_asset: assets/fixtures/forged/customer.mp4",
                issues,
            )

    def test_packaged_validator_rejects_unknown_origin_and_invalid_known_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            private_key, public_key = self._generate_signing_keypair(root)
            result = build_package(
                source_root=ROOT,
                out_root=root / "dist",
                version="0.19.2",
                signing_private_key=private_key,
                signing_public_key=public_key,
                release_registry=root / "registry.json",
            )
            package_root = result.package_root
            validator = package_root / "scripts" / "validate-package.py"

            unknown_case = root / "unknown-case" / "shotloom"
            shutil.copytree(package_root, unknown_case)
            forged_root = unknown_case / "assets" / "fixtures" / "forged"
            forged_root.mkdir()
            media = forged_root / "customer.mp4"
            media.write_bytes(b"forged customer media")
            digest = hashlib.sha256(media.read_bytes()).hexdigest()
            (forged_root / "fixture_origin.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "fixtures": [
                            {
                                "fixture_id": "forged-customer-fixture",
                                "source": "claimed synthetic source",
                                "license_or_authorization": "claimed authorization",
                                "non_client": True,
                                "content_summary": "claimed non-client media",
                                "expected_logical_roles": ["source_video"],
                                "sha256": digest,
                                "creation_tool": "unknown",
                                "redistribution_rights": "claimed",
                                "files": [
                                    {
                                        "path": "customer.mp4",
                                        "sha256": digest,
                                        "bytes": media.stat().st_size,
                                    }
                                ],
                            }
                        ],
                        "suite_files": [],
                    }
                ),
                encoding="utf-8",
            )
            unknown = subprocess.run(
                [sys.executable, str(validator), str(unknown_case)],
                capture_output=True,
                text=True,
                env={"PATH": os.environ["PATH"]},
            )
            self.assertNotEqual(unknown.returncode, 0)
            self.assertIn("unknown_fixture_origin", unknown.stdout)
            self.assertIn("client_media_or_generated_asset", unknown.stdout)

            known_root_case = root / "known-root-case" / "shotloom"
            shutil.copytree(package_root, known_root_case)
            suite_root = known_root_case / "assets" / "fixtures" / "v1"
            known_media = suite_root / "core" / "customer.mp4"
            known_media.write_bytes(b"forged customer media")
            known_digest = hashlib.sha256(known_media.read_bytes()).hexdigest()
            suite_origin_path = suite_root / "fixture_origin.json"
            suite_origin = json.loads(
                suite_origin_path.read_text(encoding="utf-8")
            )
            injected_entry = {
                "path": "core/customer.mp4",
                "sha256": known_digest,
                "bytes": known_media.stat().st_size,
            }
            suite_origin["fixtures"][0]["files"].append(injected_entry)
            suite_origin["fixtures"][0]["sha256"] = hashlib.sha256(
                (
                    json.dumps(
                        suite_origin["fixtures"][0]["files"],
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                ).encode("utf-8")
            ).hexdigest()
            suite_origin_path.write_text(
                json.dumps(suite_origin, ensure_ascii=False),
                encoding="utf-8",
            )
            known_root = subprocess.run(
                [sys.executable, str(validator), str(known_root_case)],
                capture_output=True,
                text=True,
                env={"PATH": os.environ["PATH"]},
            )
            self.assertNotEqual(known_root.returncode, 0)
            self.assertIn("invalid_fixture_origin", known_root.stdout)
            self.assertIn("client_media_or_generated_asset", known_root.stdout)

            svg_case = root / "svg-case" / "shotloom"
            shutil.copytree(package_root, svg_case)
            customer_svg = svg_case / "assets" / "fixtures" / "customer-product.svg"
            customer_svg.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg"><text>Client SKU</text></svg>',
                encoding="utf-8",
            )
            svg_result = subprocess.run(
                [sys.executable, str(validator), str(svg_case)],
                capture_output=True,
                text=True,
                env={"PATH": os.environ["PATH"]},
            )
            self.assertNotEqual(svg_result.returncode, 0)
            self.assertIn(
                "client_media_or_generated_asset: "
                "assets/fixtures/customer-product.svg",
                svg_result.stdout,
            )

            for case_name, mutation in (
                ("missing-summary", lambda payload: payload.pop("content_summary")),
                ("client-declaration", lambda payload: payload.__setitem__("non_client", False)),
                ("digest-mismatch", lambda payload: payload.__setitem__("sha256", "0" * 64)),
            ):
                with self.subTest(case=case_name):
                    case_root = root / case_name / "shotloom"
                    shutil.copytree(package_root, case_root)
                    origin_path = case_root / "assets" / "fixtures" / "fixture_origin.json"
                    origin = json.loads(origin_path.read_text(encoding="utf-8"))
                    mutation(origin)
                    origin_path.write_text(json.dumps(origin), encoding="utf-8")
                    invalid = subprocess.run(
                        [sys.executable, str(validator), str(case_root)],
                        capture_output=True,
                        text=True,
                        env={"PATH": os.environ["PATH"]},
                    )
                    self.assertNotEqual(invalid.returncode, 0)
                    self.assertIn("invalid_fixture_origin", invalid.stdout)

    def test_semver_is_strict_and_public_key_must_match_private_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            private_key, public_key = self._generate_signing_keypair(root)
            other_private_key, other_public_key = self._generate_signing_keypair(
                root / "other"
            )
            self.assertTrue(other_private_key.is_file())

            for invalid in ("01.2.3", "1.2.3-01", "1.2.3-."):
                with self.assertRaises(PackageBuildError):
                    build_package(
                        source_root=ROOT,
                        out_root=root / f"invalid-{invalid}",
                        version=invalid,
                        signing_private_key=private_key,
                        signing_public_key=public_key,
                        release_registry=root / "registry.json",
                    )

            with self.assertRaises(PackageBuildError):
                build_package(
                    source_root=ROOT,
                    out_root=root / "mismatched-key",
                    version="1.2.3+build.7",
                    signing_private_key=private_key,
                    signing_public_key=other_public_key,
                    release_registry=root / "registry.json",
                )

            build_package(
                source_root=ROOT,
                out_root=root / "signed-one",
                version="1.2.4",
                signing_private_key=private_key,
                signing_public_key=public_key,
                release_registry=root / "registry.json",
            )
            with self.assertRaises(PackageBuildError):
                build_package(
                    source_root=ROOT,
                    out_root=root / "signed-two",
                    version="1.2.4",
                    signing_private_key=other_private_key,
                    signing_public_key=other_public_key,
                    release_registry=root / "registry.json",
                )


if __name__ == "__main__":
    unittest.main()
