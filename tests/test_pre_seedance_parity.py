from __future__ import annotations

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
TOOL = ROOT / "tools" / "pre_seedance_parity.py"
sys.path.insert(0, str(ROOT / "tools"))

from private_plugin_package import build_package  # noqa: E402
from pre_seedance_parity import (  # noqa: E402
    PINNED_EXECUTABLE_PATH,
    ParityStop,
    activate_subprocess_network_guard,
    assert_no_subprocess_network_attempts,
    branch_mismatch_failure,
    build_sandbox_profile,
    deactivate_subprocess_network_guard,
    derive_storyboard_identity_reference,
    instability_failure,
    MULTI_PERSON_HOST_BOX,
    MULTI_PERSON_SUPPORT_BOX,
    normalize_job_root_aliases,
    render_multi_person_storyboard_fixture,
    safe_target_environment,
    storyboard_identity_pixel_projection,
    tree_snapshot,
)


REQUIRED_ROWS = [
    "intake_normalization",
    "effective_profile",
    "source_rhythm",
    "part_coverage",
    "director_plan",
    "source_script_fidelity",
    "line_edits",
    "visual_edits",
    "audio_boundary",
    "reference_roles_and_order",
    "prompt",
    "provider_request",
    "approval",
    "cost",
    "retry_authority",
    "qc_risk_families",
    "gate_conclusions",
    "pre_seedance_handoff",
]
REQUIRED_BRANCHES = [
    "missing-required-input",
    "generic-profile-routing",
    "clay-mask-profile-routing",
    "toner-profile-routing",
    "storyboard-derived-identity",
    "generation-approval-boundary",
    "failed-part-retry-boundary",
    "request-rejection",
    "local-finishing",
    "subtitle-clean-classification",
    "subtitle-burned-in-classification",
    "final-technical-qc",
]


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


class PreSeedanceParityCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.package_tmp = tempfile.TemporaryDirectory()
        package_build_root = Path(cls.package_tmp.name)
        cls.legacy_root = package_build_root / "legacy-root"
        shutil.copytree(
            ROOT,
            cls.legacy_root,
            ignore=shutil.ignore_patterns(
                ".git",
                "__pycache__",
                ".cache",
                ".pytest_cache",
            ),
        )
        # The sealed Legacy Baseline predates the product-fixture helpers.
        # Keeping them here would turn this into a self-comparison of two
        # copies of the new repository.
        for relative in (
            "tools/product_fixture_suite.py",
            "tools/provider_fixture_recorder.py",
        ):
            (cls.legacy_root / relative).unlink()
        cls.legacy_baseline = (
            cls.legacy_root
            / "migration"
            / "baselines"
            / "legacy-layout-v1"
            / "baseline.lock.json"
        )
        cls.legacy_baseline.parent.mkdir(parents=True)
        legacy_verifier = cls.legacy_root / "tools" / "legacy_baseline.py"
        legacy_verifier.write_text(
            "\n".join(
                [
                    "import argparse",
                    "import json",
                    "from pathlib import Path",
                    "p=argparse.ArgumentParser()",
                    "s=p.add_subparsers(dest='command',required=True)",
                    "v=s.add_parser('verify')",
                    "v.add_argument('--root',required=True)",
                    "v.add_argument('--baseline',required=True)",
                    "a=p.parse_args()",
                    "path=Path(a.root)/a.baseline",
                    "contract=json.loads(path.read_text(encoding='utf-8'))",
                    "if contract.get('kind') != "
                    "'unit-test-legacy-baseline' or "
                    "contract.get('sealed') is not True:",
                    "    raise SystemExit('missing sealed test baseline')",
                    "print('PASS')",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        cls.legacy_baseline.write_text(
            json.dumps(
                {
                    "kind": "unit-test-legacy-baseline",
                    "sealed": True,
                    "runtime_contract": {
                        "python": {
                            "executable": str(
                                Path(sys.executable).resolve()
                            )
                        }
                    },
                    "source_closure": {
                        "objects": [
                            {
                                "path": "tools/legacy_baseline.py",
                                "kind": "file",
                                "sha256": hashlib.sha256(
                                    legacy_verifier.read_bytes()
                                ).hexdigest(),
                                "size_bytes": legacy_verifier.stat().st_size,
                                "mode": oct(
                                    legacy_verifier.stat().st_mode & 0o777
                                ),
                            }
                        ]
                    },
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        private_key = package_build_root / "release-signing-key.pem"
        public_key = package_build_root / "release-signing-key.pub.pem"
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
        cls.package_root = build_package(
            source_root=ROOT,
            out_root=package_build_root / "dist",
            version="0.5.0",
            signing_private_key=private_key,
            signing_public_key=public_key,
            release_registry=package_build_root / "release-registry.json",
        ).package_root

    @classmethod
    def tearDownClass(cls):
        cls.package_tmp.cleanup()

    def run_harness(
        self,
        out_dir: Path,
        *,
        plugin_root: Path | None = None,
        expected: int = 0,
    ) -> tuple[subprocess.CompletedProcess[str], dict]:
        result = subprocess.run(
            [
                sys.executable,
                str(TOOL),
                "run",
                "--legacy-root",
                str(self.legacy_root),
                "--legacy-baseline",
                str(self.legacy_baseline),
                "--plugin-root",
                str(plugin_root or self.package_root),
                "--fixture-root",
                str(ROOT / "product-fixtures" / "v1"),
                "--out-dir",
                str(out_dir),
            ],
            cwd=out_dir.parent,
            text=True,
            capture_output=True,
            env={
                **os.environ,
                "LANG": "C",
                "LC_ALL": "C",
                "TZ": "UTC",
                "PYTHONHASHSEED": "0",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        self.assertEqual(
            result.returncode,
            expected,
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        report_path = out_dir / "parity_report.json"
        self.assertTrue(report_path.is_file(), result.stdout + result.stderr)
        return result, json.loads(report_path.read_text(encoding="utf-8"))

    def test_ab_harness_proves_required_pre_seedance_rows_with_zero_side_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_before = tree_digest(self.legacy_root)
            package_before = tree_digest(self.package_root)

            result, report = self.run_harness(root / "evidence")

            self.assertEqual(report["overall"], "PASS")
            self.assertEqual(report["legacy_baseline"]["result"], "PASS")
            self.assertRegex(
                report["legacy_baseline"]["sha256"],
                r"^[0-9a-f]{64}$",
            )
            self.assertEqual(
                [row["row_id"] for row in report["required_rows"]],
                REQUIRED_ROWS,
            )
            self.assertTrue(
                all(row["result"] == "PASS" for row in report["required_rows"])
            )
            self.assertEqual(
                [row["case_id"] for row in report["branch_rows"]],
                REQUIRED_BRANCHES,
            )
            self.assertTrue(
                all(row["result"] == "PASS" for row in report["branch_rows"])
            )

            for target in ("legacy", "plugin"):
                runs = report["targets"][target]["runs"]
                self.assertEqual(len(runs), 2)
                self.assertEqual(runs[0]["behavior_sha256"], runs[1]["behavior_sha256"])
                self.assertEqual(
                    runs[0]["stage_order"],
                    ["source_blueprint", "image_batch_qc", "pre_seedance_pack"],
                )
                for stage in runs[0]["stage_audit"]:
                    self.assertEqual(
                        stage["execution_order"],
                        ["maker", "qc_risk_ledger", "checker", "gate"],
                    )
                    self.assertEqual(stage["checker_invocation_count"], 1)
                    self.assertEqual(stage["gate_conclusion"], "PASS")
                    self.assertTrue(stage["maker_artifacts"])
                    self.assertRegex(stage["worker_sha256"], r"^[0-9a-f]{64}$")
                    self.assertRegex(stage["gate_sha256"], r"^[0-9a-f]{64}$")

                target_report = json.loads(
                    Path(runs[0]["report_path"]).read_text(encoding="utf-8")
                )
                runtime = target_report["behavior"]["environment"]["runtime"]
                self.assertFalse(runtime["user_site_enabled"])
                self.assertEqual(
                    runtime["python_executable_sha256"],
                    hashlib.sha256(
                        Path(sys.executable).resolve().read_bytes()
                    ).hexdigest(),
                )
                self.assertRegex(
                    runtime["pillow_init_sha256"],
                    r"^[0-9a-f]{64}$",
                )
                identity_branch = next(
                    row
                    for row in target_report["behavior"]["branch_rows"]
                    if row["case_id"] == "storyboard-derived-identity"
                )
                self.assertEqual(
                    identity_branch["production_evidence"]["overall"],
                    "PASS",
                )
                self.assertEqual(
                    identity_branch["production_evidence"]["people_mode"],
                    "multi-person",
                )
                self.assertEqual(
                    identity_branch["production_evidence"]["roles"],
                    ["host", "support"],
                )
                self.assertTrue(
                    identity_branch["production_evidence"][
                        "cross_part_host_reuse"
                    ]
                )
                self.assertEqual(
                    identity_branch["production_evidence"][
                        "support_part_scope"
                    ],
                    ["part1"],
                )
                pixel_bindings = identity_branch[
                    "production_evidence"
                ]["pixel_bindings"]
                self.assertTrue(pixel_bindings["part_content_distinct"])
                self.assertTrue(
                    pixel_bindings["role_identity_content_distinct"]
                )
                self.assertTrue(
                    pixel_bindings[
                        "host_ref_derived_from_passed_part1"
                    ]
                )
                self.assertTrue(
                    pixel_bindings[
                        "support_ref_derived_from_passed_part1"
                    ]
                )
                self.assertTrue(
                    all(
                        status == "PASS"
                        for status in identity_branch[
                            "production_evidence"
                        ]["required_checks"].values()
                    )
                )
                target_artifacts = target_report["behavior"]["artifacts"]
                self.assertEqual(
                    target_artifacts["provider_request"]["request_body_qc"][
                        "overall"
                    ],
                    "PASS",
                )
                self.assertIn(
                    "workspace://actual-pre-seedance/output/job-001/"
                    "final-images/part1_seedance_ref.png",
                    target_artifacts["reference_roles_and_order"],
                )
                self.assertEqual(
                    target_artifacts["pre_seedance_handoff"]["handoff"]["mode"],
                    "both",
                )
                self.assertEqual(
                    target_artifacts["intake_normalization"][
                        "production_evidence"
                    ]["entrypoint_executed"],
                    True,
                )
                self.assertEqual(
                    target_artifacts["intake_normalization"][
                        "production_evidence"
                    ]["first_runner_decision"]["matched_rule"],
                    "pending_source_blueprint",
                )
                understanding = target_artifacts["source_rhythm"][
                    "understanding_evidence"
                ]
                self.assertEqual(
                    understanding["model"],
                    "doubao-seed-2-0-mini-260215",
                )
                self.assertEqual(
                    understanding["endpoint"],
                    "https://higress-api.wujieai.com/v1/chat/completions",
                )
                self.assertEqual(
                    understanding["matched_offline_request_count"],
                    1,
                )
                self.assertFalse(understanding["network_access"])
                workspace = Path(runs[0]["report_path"]).parent
                qc_bundle = json.loads(
                    (
                        workspace
                        / "actual-intake"
                        / "output"
                        / "job-001"
                        / "checks"
                        / "pre_seedance_pack_qc_bundle.json"
                    ).read_text(encoding="utf-8")
                )
                self.assertEqual(qc_bundle["overall"], "PASS")
                if target == "plugin":
                    runner_state = json.loads(
                        (
                            workspace
                            / "actual-intake"
                            / ".viral-replica"
                            / "state"
                            / "RUNNER_STATE.json"
                        ).read_text(encoding="utf-8")
                    )["jobs"]["job-001"]
                    self.assertEqual(
                        [
                            (entry["stage"], entry["result"])
                            for entry in runner_state["gate_history"]
                        ],
                        [
                            ("source_blueprint", "PASS"),
                            ("image_batch_qc", "PASS"),
                            ("pre_seedance_pack", "PASS"),
                        ],
                    )
                    self.assertEqual(
                        runner_state["last_stage"],
                        "pre_seedance_pack",
                    )
                    self.assertIsNone(runner_state["active_stage_attempt"])

            self.assertEqual(
                report["targets"]["legacy"]["runs"][0]["behavior_sha256"],
                report["targets"]["plugin"]["runs"][0]["behavior_sha256"],
            )
            self.assertEqual(
                report["side_effects"],
                {
                    "network_attempt_count": 0,
                    "unmatched_request_count": 0,
                    "real_task_count": 0,
                    "paid_task_count": 0,
                    "media_generation_task_count": 0,
                    "recorder_fallback_count": 0,
                    "forbidden_write_count": 0,
                },
            )
            self.assertEqual(report["final_status"], "seedance_inputs_prepared")
            self.assertIn("PASS", result.stdout)
            self.assertEqual(tree_digest(self.legacy_root), source_before)
            self.assertEqual(tree_digest(self.package_root), package_before)
            self.assertFalse(
                (
                    self.package_root
                    / "engine"
                    / "tools"
                    / "pre_seedance_parity.py"
                ).exists(),
                "the top-level A/B harness must not become a LegacyLayout adapter "
                "inside the plugin",
            )

    def test_target_sandbox_denies_undeclared_sibling_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = root / "declared-engine"
            fixture = root / "declared-fixture"
            workspace = root / "workspace"
            for path in (engine, fixture, workspace):
                path.mkdir()
            declared = fixture / "declared.txt"
            declared.write_text("declared\n", encoding="utf-8")
            poison = root / "undeclared-poison.txt"
            poison.write_text("poison\n", encoding="utf-8")
            profile = build_sandbox_profile(
                engine_root=engine,
                fixture_root=fixture,
                workspace=workspace,
                target_root=engine,
            )
            allowed = subprocess.run(
                [
                    "/usr/bin/sandbox-exec",
                    "-p",
                    profile,
                    sys.executable,
                    "-c",
                    (
                        "from pathlib import Path;"
                        f"print(Path({str(declared)!r}).read_text())"
                    ),
                ],
                text=True,
                capture_output=True,
                cwd=workspace,
            )
            self.assertEqual(allowed.returncode, 0, allowed.stderr)
            denied = subprocess.run(
                [
                    "/usr/bin/sandbox-exec",
                    "-p",
                    profile,
                    sys.executable,
                    "-c",
                    (
                        "from pathlib import Path;"
                        f"print(Path({str(poison)!r}).read_text())"
                    ),
                ],
                text=True,
                capture_output=True,
                cwd=workspace,
            )
            self.assertNotEqual(denied.returncode, 0)
            denied_metadata = subprocess.run(
                [
                    "/usr/bin/sandbox-exec",
                    "-p",
                    profile,
                    sys.executable,
                    "-c",
                    (
                        "from pathlib import Path;"
                        f"print(Path({str(poison)!r}).stat())"
                    ),
                ],
                text=True,
                capture_output=True,
                cwd=workspace,
            )
            self.assertNotEqual(denied_metadata.returncode, 0)
            external_write = root / "external-write.txt"
            denied_write = subprocess.run(
                [
                    "/usr/bin/sandbox-exec",
                    "-p",
                    profile,
                    sys.executable,
                    "-c",
                    (
                        "from pathlib import Path;"
                        f"Path({str(external_write)!r}).write_text('denied')"
                    ),
                ],
                text=True,
                capture_output=True,
                cwd=workspace,
            )
            self.assertNotEqual(denied_write.returncode, 0)
            self.assertFalse(external_write.exists())
            denied_socket = subprocess.run(
                [
                    "/usr/bin/sandbox-exec",
                    "-p",
                    profile,
                    sys.executable,
                    "-c",
                    (
                        "import socket;"
                        "socket.socket().connect(('127.0.0.1',9))"
                    ),
                ],
                text=True,
                capture_output=True,
                cwd=workspace,
            )
            self.assertNotEqual(denied_socket.returncode, 0)
            self.assertIn("Operation not permitted", denied_socket.stderr)

    def test_tree_snapshot_detects_metadata_only_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "sealed.txt"
            path.write_text("unchanged\n", encoding="utf-8")
            before = tree_snapshot(root)
            path.chmod(0o600)
            after = tree_snapshot(root)
            self.assertNotEqual(after, before)

    def test_target_environment_strips_injection_paths_and_secrets(self):
        original = {
            "PYTHONPATH": os.environ.get("PYTHONPATH"),
            "PYTHONHOME": os.environ.get("PYTHONHOME"),
            "PYTHONUSERBASE": os.environ.get("PYTHONUSERBASE"),
            "PARITY_TEST_API_KEY": os.environ.get("PARITY_TEST_API_KEY"),
            "PATH": os.environ.get("PATH"),
        }
        try:
            os.environ.update(
                {
                    "PYTHONPATH": "/tmp/poison",
                    "PYTHONHOME": "/tmp/poison-home",
                    "PYTHONUSERBASE": "/tmp/poison-user",
                    "PARITY_TEST_API_KEY": "must-not-leak",
                    "PATH": "/tmp/poison-bin",
                }
            )
            environment = safe_target_environment()
        finally:
            for key, value in original.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.assertNotIn("PYTHONPATH", environment)
        self.assertNotIn("PYTHONHOME", environment)
        self.assertNotIn("PYTHONUSERBASE", environment)
        self.assertNotIn("PARITY_TEST_API_KEY", environment)
        self.assertEqual(environment["PATH"], PINNED_EXECUTABLE_PATH)
        self.assertEqual(environment["PYTHONNOUSERSITE"], "1")

    def test_caught_child_network_attempt_is_still_a_hard_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = {"network_attempt_count": 0}
            activate_subprocess_network_guard(root, events)
            try:
                result = subprocess.run(
                    [
                        sys.executable,
                        "-s",
                        "-c",
                        (
                            "import socket;"
                            "\ntry:"
                            "\n socket.socket().connect(('127.0.0.1', 9))"
                            "\nexcept PermissionError:"
                            "\n print('caught')"
                        ),
                    ],
                    text=True,
                    capture_output=True,
                    env=safe_target_environment(),
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "caught")
                with self.assertRaisesRegex(
                    ParityStop,
                    "outbound network",
                ):
                    assert_no_subprocess_network_attempts()
                self.assertEqual(events["network_attempt_count"], 1)
            finally:
                deactivate_subprocess_network_guard()

    def test_uninstrumented_process_and_python_bypass_are_hard_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = {"network_attempt_count": 0}
            activate_subprocess_network_guard(root, events)
            try:
                with self.assertRaises(PermissionError):
                    subprocess.run(
                        ["/usr/bin/true"],
                        check=False,
                    )
                with self.assertRaisesRegex(
                    ParityStop,
                    "guard-bypass",
                ):
                    assert_no_subprocess_network_attempts()

                with self.assertRaises(PermissionError):
                    subprocess.run(
                        [sys.executable, "-S", "-c", "pass"],
                        check=False,
                    )
                with self.assertRaisesRegex(
                    ParityStop,
                    "guard-bypass",
                ):
                    assert_no_subprocess_network_attempts()
                self.assertEqual(events["network_attempt_count"], 2)
            finally:
                deactivate_subprocess_network_guard()

    def test_storyboard_derived_roles_require_distinct_bound_pixels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            part1 = root / "part1.png"
            part2 = root / "part2.png"
            host = root / "host.png"
            support = root / "support.png"
            render_multi_person_storyboard_fixture(
                part1,
                part_id="part1",
                source_variant=False,
            )
            render_multi_person_storyboard_fixture(
                part2,
                part_id="part2",
                source_variant=False,
            )
            derive_storyboard_identity_reference(
                part1,
                MULTI_PERSON_HOST_BOX,
                host,
            )
            derive_storyboard_identity_reference(
                part1,
                MULTI_PERSON_SUPPORT_BOX,
                support,
            )
            projection = storyboard_identity_pixel_projection(
                part1=part1,
                part2=part2,
                host_ref=host,
                support_ref=support,
            )
            self.assertTrue(projection["role_identity_content_distinct"])

            shutil.copy2(host, support)
            with self.assertRaisesRegex(
                ParityStop,
                "pixel bindings",
            ):
                storyboard_identity_pixel_projection(
                    part1=part1,
                    part2=part2,
                    host_ref=host,
                    support_ref=support,
                )

    def test_relative_job_alias_normalization_does_not_rewrite_prose(self):
        workspace = Path("/sealed/workspace")
        job_root = workspace / "output" / "job-001"
        legacy_prompt = "Prompt says output/job-001/SAFE"
        aliased_prompt = "Prompt says job_root://SAFE"

        self.assertEqual(
            normalize_job_root_aliases(
                "output/job-001/SAFE",
                workspace=workspace,
                job_root=job_root,
            ),
            "job_root://SAFE",
        )
        self.assertNotEqual(
            normalize_job_root_aliases(
                legacy_prompt,
                workspace=workspace,
                job_root=job_root,
            ),
            normalize_job_root_aliases(
                aliased_prompt,
                workspace=workspace,
                job_root=job_root,
            ),
        )
        embedded_absolute = (
            "semantic-/sealed/workspace/output/job-001/SAFE-tail"
        )
        embedded_alias = "semantic-job_root://SAFE-tail"
        self.assertNotEqual(
            normalize_job_root_aliases(
                embedded_absolute,
                workspace=workspace,
                job_root=job_root,
            ),
            normalize_job_root_aliases(
                embedded_alias,
                workspace=workspace,
                job_root=job_root,
            ),
        )
        self.assertEqual(
            normalize_job_root_aliases(
                "candidate=/sealed/workspace/output/job-001/SAFE",
                workspace=workspace,
                job_root=job_root,
                _field="detail",
            ),
            "candidate=job_root://SAFE",
        )

    def test_instability_failure_includes_first_difference_contract(self):
        failure = instability_failure(
            "plugin",
            {"stage_order": ["source_blueprint"]},
            {"stage_order": ["pre_seedance_pack"]},
        )

        self.assertEqual(failure["stage"], "target_stability")
        self.assertEqual(failure["artifact_family"], "complete_behavior")
        self.assertEqual(failure["path"], "stage_order[0]")
        self.assertEqual(failure["expected"], "source_blueprint")
        self.assertEqual(failure["actual"], "pre_seedance_pack")

    def test_branch_failure_includes_first_difference_contract(self):
        failure = branch_mismatch_failure(
            {
                "case_id": "request-rejection",
                "actual": {"conclusion": "STOP"},
            },
            {
                "case_id": "request-rejection",
                "actual": {"conclusion": "PASS"},
            },
        )

        self.assertEqual(failure["stage"], "branch_matrix")
        self.assertEqual(
            failure["artifact_family"],
            "request-rejection",
        )
        self.assertEqual(failure["path"], "actual.conclusion")
        self.assertEqual(failure["expected"], "STOP")
        self.assertEqual(failure["actual"], "PASS")

    def test_python_write_guard_blocks_dir_fd_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            victim = root / "outside.txt"
            probe = "\n".join(
                [
                    "import json, os, sys",
                    f"sys.path.insert(0, {str(ROOT / 'tools')!r})",
                    "from pre_seedance_parity import install_write_guard",
                    f"parent_fd = os.open({str(root)!r}, os.O_RDONLY)",
                    "events = {'forbidden_write_count': 0}",
                    f"install_write_guard(__import__('pathlib').Path({str(workspace)!r}), events)",
                    "try:",
                    "    os.open('outside.txt', os.O_WRONLY | os.O_CREAT, 0o600, dir_fd=parent_fd)",
                    "except PermissionError:",
                    "    print(json.dumps(events))",
                    "else:",
                    "    raise SystemExit('dir_fd escape unexpectedly succeeded')",
                ]
            )
            result = subprocess.run(
                [sys.executable, "-c", probe],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                json.loads(result.stdout),
                {"forbidden_write_count": 1},
            )
            self.assertFalse(victim.exists())

    def test_legacy_verifier_cannot_write_to_the_sealed_tree(self):
        tool = self.legacy_root / "tools" / "legacy_baseline.py"
        original = tool.read_text(encoding="utf-8")
        original_baseline = self.legacy_baseline.read_text(encoding="utf-8")
        victim = self.legacy_root / "verifier-write.txt"
        tool.write_text(
            "\n".join(
                [
                    "from pathlib import Path",
                    f"Path({str(victim)!r}).write_text('forbidden')",
                    "print('PASS')",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        contract = json.loads(original_baseline)
        verifier_object = contract["source_closure"]["objects"][0]
        verifier_object["sha256"] = hashlib.sha256(
            tool.read_bytes()
        ).hexdigest()
        verifier_object["size_bytes"] = tool.stat().st_size
        verifier_object["mode"] = oct(tool.stat().st_mode & 0o777)
        self.legacy_baseline.write_text(
            json.dumps(contract, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        try:
            with tempfile.TemporaryDirectory() as tmp:
                _, report = self.run_harness(
                    Path(tmp) / "evidence",
                    expected=2,
                )
            self.assertEqual(
                report["failure"]["code"],
                "baseline_integrity_failed",
            )
            self.assertFalse(victim.exists())
        finally:
            tool.write_text(original, encoding="utf-8")
            self.legacy_baseline.write_text(
                original_baseline,
                encoding="utf-8",
            )

    def test_first_forbidden_difference_names_stage_family_expected_and_actual(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            changed_plugin = root / "changed-plugin" / "shotloom"
            shutil.copytree(self.package_root, changed_plugin)
            model_path = changed_plugin / "engine" / "rules" / "SEEDANCE_MODEL.json"
            model = json.loads(model_path.read_text(encoding="utf-8"))
            model["model"] = "ep-parity-regression"
            model_path.write_text(
                json.dumps(model, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            _, report = self.run_harness(
                root / "evidence",
                plugin_root=changed_plugin,
                expected=3,
            )

            self.assertEqual(report["overall"], "FAIL")
            self.assertEqual(report["failure"]["code"], "deterministic_parity_mismatch")
            self.assertEqual(report["failure"]["stage"], "pre_seedance_pack")
            self.assertEqual(report["failure"]["artifact_family"], "director_plan")
            self.assertEqual(
                report["failure"]["expected"]["model_route"]["model"],
                "ep-20260521101914-nwv8j",
            )
            self.assertEqual(
                report["failure"]["actual"]["model_route"]["model"],
                "ep-parity-regression",
            )
            self.assertEqual(
                report["normalization"]["applied"],
                ["workspace_root"],
            )
            self.assertNotIn("model", report["normalization"]["allowlist"])

    def test_packaged_request_qc_preserves_local_path_rejection(self):
        probe = (
            "import json,sys;"
            "sys.path.insert(0,sys.argv[1]);"
            "import request_body_qc;"
            "print(json.dumps(request_body_qc.collect_values("
            "{'image':'/Users/example/local.png'})['local_paths']))"
        )

        def collect(tool_root: Path) -> list[list[str]]:
            result = subprocess.run(
                [sys.executable, "-c", probe, str(tool_root)],
                text=True,
                capture_output=True,
                check=True,
            )
            return json.loads(result.stdout)

        legacy_paths = collect(ROOT / "tools")
        plugin_paths = collect(self.package_root / "engine" / "tools")
        self.assertEqual(legacy_paths, [["$.image", "/Users/example/local.png"]])
        self.assertEqual(plugin_paths, legacy_paths)

    def test_semantic_behavior_contract_ignores_comment_only_engine_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            changed_plugin = root / "changed-plugin" / "shotloom"
            shutil.copytree(self.package_root, changed_plugin)
            checker = changed_plugin / "engine" / "tools" / "checker_review_qc.py"
            checker.write_text(
                checker.read_text(encoding="utf-8") + "\n# parity drift\n",
                encoding="utf-8",
            )

            _, report = self.run_harness(
                root / "evidence",
                plugin_root=changed_plugin,
            )

            self.assertEqual(
                report["overall"],
                "PASS",
            )
            self.assertEqual(report["final_status"], "seedance_inputs_prepared")

    def test_semantic_behavior_contract_rejects_qc_threshold_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            changed_plugin = root / "changed-plugin" / "shotloom"
            shutil.copytree(self.package_root, changed_plugin)
            checker = changed_plugin / "engine" / "tools" / "source_rhythm_qc.py"
            original = checker.read_text(encoding="utf-8")
            changed = original.replace(
                "tolerance = max(0.12, expected_target_span * 0.12)",
                "tolerance = max(0.50, expected_target_span * 0.50)",
                1,
            )
            self.assertNotEqual(changed, original)
            checker.write_text(changed, encoding="utf-8")

            _, report = self.run_harness(
                root / "evidence",
                plugin_root=changed_plugin,
                expected=3,
            )

            self.assertEqual(report["overall"], "FAIL")
            self.assertEqual(
                report["failure"]["code"],
                "deterministic_parity_mismatch",
            )
            self.assertEqual(report["failure"]["stage"], "behavior_contract")
            self.assertEqual(
                report["failure"]["artifact_family"],
                "qc_executable_semantics",
            )
            self.assertIn(
                "tools/source_rhythm_qc.py",
                report["failure"]["path"],
            )

    def test_full_semantic_closure_rejects_request_endpoint_weakening(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            changed_plugin = root / "changed-plugin" / "shotloom"
            shutil.copytree(self.package_root, changed_plugin)
            checker = (
                changed_plugin
                / "engine"
                / "tools"
                / "request_body_qc.py"
            )
            original = checker.read_text(encoding="utf-8")
            changed = original.replace(
                "ok = args.expected_endpoint in body_text",
                "ok = True",
                1,
            )
            self.assertNotEqual(changed, original)
            checker.write_text(changed, encoding="utf-8")

            _, report = self.run_harness(
                root / "evidence",
                plugin_root=changed_plugin,
                expected=3,
            )

            self.assertEqual(report["overall"], "FAIL")
            self.assertEqual(
                report["failure"]["artifact_family"],
                "qc_executable_semantics",
            )
            self.assertIn(
                "tools/request_body_qc.py",
                report["failure"]["path"],
            )

    def test_behavior_probe_rejects_storyboard_aspect_threshold_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            changed_plugin = root / "changed-plugin" / "shotloom"
            shutil.copytree(self.package_root, changed_plugin)
            checker = (
                changed_plugin
                / "engine"
                / "tools"
                / "storyboard_visual_acceptance.py"
            )
            original = checker.read_text(encoding="utf-8")
            changed = original.replace(
                (
                    '"PASS" if aspect_drift <= '
                    'max_canvas_aspect_drift else "FAIL"'
                ),
                (
                    '"PASS" if (aspect_drift <= '
                    "max_canvas_aspect_drift or aspect_drift <= 0.30) "
                    'else "FAIL"'
                ),
                1,
            )
            self.assertNotEqual(changed, original)
            checker.write_text(changed, encoding="utf-8")

            _, report = self.run_harness(
                root / "evidence",
                plugin_root=changed_plugin,
                expected=3,
            )

            self.assertEqual(report["overall"], "FAIL")
            self.assertEqual(
                report["failure"]["artifact_family"],
                "qc_executable_semantics",
            )
            self.assertIn(
                "storyboard_visual_acceptance",
                report["failure"]["path"],
            )

    def test_behavior_probe_rejects_image_contract_gate_weakening(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            changed_plugin = root / "changed-plugin" / "shotloom"
            shutil.copytree(self.package_root, changed_plugin)
            checker = (
                changed_plugin
                / "engine"
                / "tools"
                / "codex_imagegen_contract_qc.py"
            )
            original = checker.read_text(encoding="utf-8")
            changed = original.replace(
                '"PASS" if quality == "medium" else "FAIL"',
                (
                    '"PASS" if quality in {"medium", "low"} '
                    'else "FAIL"'
                ),
                1,
            )
            self.assertNotEqual(changed, original)
            checker.write_text(changed, encoding="utf-8")

            _, report = self.run_harness(
                root / "evidence",
                plugin_root=changed_plugin,
                expected=3,
            )

            self.assertEqual(report["overall"], "FAIL")
            self.assertEqual(
                report["failure"]["artifact_family"],
                "qc_executable_semantics",
            )
            self.assertIn(
                "codex_imagegen_contract_qc",
                report["failure"]["path"],
            )


if __name__ == "__main__":
    unittest.main()
