import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from tools import stage_execution


class StageExecutionFastAuditTest(unittest.TestCase):
    def test_default_execution_skips_full_repository_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output/job-001/work/result.txt"
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "story",
                            "executor_kind": "agent",
                            "task": "Write the declared result.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work",
                            ],
                            "completion_path": (
                                "output/job-001/work/completion.json"
                            ),
                        }
                    ],
                },
            )

            def dispatch(packet):
                staged = (
                    Path(packet["allowed_write_roots"][0])
                    / "result.txt"
                )
                staged.parent.mkdir(parents=True, exist_ok=True)
                staged.write_text("PASS\n", encoding="utf-8")
                return {"status": "PASS", "outputs": [staged]}

            with mock.patch.object(
                stage_execution,
                "_capture_output_tree",
                side_effect=AssertionError("full repository audit ran"),
            ):
                report = stage_execution.execute_plan(
                    root,
                    plan,
                    dispatcher=dispatch,
                )

            self.assertEqual(report["overall"], "PASS")
            self.assertEqual(
                report["timing"]["audit_mode"],
                "targeted",
            )
            self.assertEqual(output.read_text(encoding="utf-8"), "PASS\n")

    def test_missing_command_sandbox_uses_serial_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet_specs = []
            for part_id in ("part1", "part2"):
                output = f"output/job-001/work/{part_id}/result.txt"
                packet_specs.append(
                    {
                        "packet_id": part_id,
                        "command": ["fake-command", output],
                        "depends_on": [],
                        "allowed_write_roots": [
                            f"output/job-001/work/{part_id}",
                        ],
                        "expected_outputs": [output],
                        "completion_path": (
                            f"output/job-001/work/completions/{part_id}.json"
                        ),
                    }
                )
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "image_batch_qc",
                    "packets": packet_specs,
                },
            )
            lock = threading.Lock()
            active = 0
            max_active = 0

            def runner(command, **unused_kwargs):
                nonlocal active, max_active
                with lock:
                    active += 1
                    max_active = max(max_active, active)
                try:
                    output = Path(command[1])
                    output.parent.mkdir(parents=True, exist_ok=True)
                    time.sleep(0.02)
                    output.write_text("PASS\n", encoding="utf-8")
                finally:
                    with lock:
                        active -= 1
                return subprocess.CompletedProcess(command, 0, "", "")

            with mock.patch.object(
                stage_execution,
                "_sandbox_execution_available",
                return_value=False,
                create=True,
            ):
                report = stage_execution.execute_plan(
                    root,
                    plan,
                    runner=runner,
                )

            self.assertEqual(report["overall"], "PASS")
            self.assertEqual(max_active, 1)
            self.assertEqual(
                report["timing"]["protection_mode"],
                "serial_fallback",
            )
            self.assertEqual(
                report["timing"]["audit_mode"],
                "targeted",
            )

    def test_missing_sandbox_allows_custom_dispatcher_subprocess(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = "output/job-001/work/result.txt"
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "story",
                            "executor_kind": "agent",
                            "task": "Run the injected worker.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work",
                            ],
                            "completion_path": (
                                "output/job-001/work/completion.json"
                            ),
                        }
                    ],
                },
            )

            def dispatch(packet):
                staged = (
                    Path(packet["allowed_write_roots"][0])
                    / "result.txt"
                )
                completed = subprocess.run(
                    [
                        "python3",
                        "-c",
                        (
                            "from pathlib import Path;"
                            f"p=Path({str(staged)!r});"
                            "p.parent.mkdir(parents=True, exist_ok=True);"
                            "p.write_text('PASS\\n')"
                        ),
                    ],
                    check=False,
                )
                return {
                    "status": (
                        "PASS" if completed.returncode == 0 else "FAIL"
                    ),
                    "outputs": [staged],
                }

            with mock.patch.object(
                stage_execution,
                "_sandbox_execution_available",
                return_value=False,
            ):
                report = stage_execution.execute_plan(
                    root,
                    plan,
                    dispatcher=dispatch,
                )

            self.assertEqual(report["overall"], "PASS")
            self.assertEqual(
                report["timing"]["protection_mode"],
                "serial_fallback",
            )

    def test_serial_fallback_restores_changed_tracked_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tracked = root / "tools/worker.py"
            tracked.parent.mkdir(parents=True)
            tracked.write_text("safe = True\n", encoding="utf-8")
            subprocess.run(
                ["git", "init", "-q"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                ["git", "add", "tools/worker.py"],
                cwd=root,
                check=True,
            )
            output = "output/job-001/work/result.txt"
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "story",
                            "command": ["fake-command", output],
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work",
                            ],
                            "expected_outputs": [output],
                            "completion_path": (
                                "output/job-001/work/completion.json"
                            ),
                        }
                    ],
                },
            )

            def runner(command, **unused_kwargs):
                result = Path(command[1])
                result.parent.mkdir(parents=True, exist_ok=True)
                result.write_text("PASS\n", encoding="utf-8")
                tracked.write_text("safe = False\n", encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, "", "")

            with mock.patch.object(
                stage_execution,
                "_sandbox_execution_available",
                return_value=False,
                create=True,
            ):
                report = stage_execution.execute_plan(
                    root,
                    plan,
                    runner=runner,
                )

            self.assertEqual(report["overall"], "FAIL")
            self.assertEqual(
                tracked.read_text(encoding="utf-8"),
                "safe = True\n",
            )
            self.assertIn(
                "tools/worker.py",
                report["completions"][0]["error"],
            )

    def test_report_separates_task_check_and_writeback_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "story",
                            "executor_kind": "agent",
                            "task": "Write the declared result.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work",
                            ],
                            "completion_path": (
                                "output/job-001/work/completion.json"
                            ),
                        }
                    ],
                },
            )

            def dispatch(packet):
                time.sleep(0.01)
                output = (
                    Path(packet["allowed_write_roots"][0])
                    / "result.txt"
                )
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("PASS\n", encoding="utf-8")
                return {"status": "PASS", "outputs": [output]}

            report = stage_execution.execute_plan(
                root,
                plan,
                dispatcher=dispatch,
            )

            timing = report["timing"]
            for name in (
                "prepare_seconds",
                "task_seconds",
                "check_seconds",
                "writeback_seconds",
                "cleanup_seconds",
                "total_seconds",
            ):
                self.assertIn(name, timing)
                self.assertGreaterEqual(timing[name], 0.0)
            self.assertGreater(timing["task_seconds"], 0.005)
            self.assertGreaterEqual(
                timing["total_seconds"],
                timing["task_seconds"],
            )

    def test_targeted_audit_restores_changed_job_control_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            control = root / "output/job-001/seedance/director_plan.json"
            control.parent.mkdir(parents=True)
            control.write_text('{"safe": true}\n', encoding="utf-8")
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "pre_seedance_pack",
                    "packets": [
                        {
                            "packet_id": "part1",
                            "executor_kind": "agent",
                            "task": "Write the declared result.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work/part1",
                            ],
                            "completion_path": (
                                "output/job-001/work/completion.json"
                            ),
                        }
                    ],
                },
            )

            def dispatch(packet):
                output = (
                    Path(packet["allowed_write_roots"][0])
                    / "result.txt"
                )
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("PASS\n", encoding="utf-8")
                escaped = stage_execution._ORIGINAL_POPEN(
                    [
                        "python3",
                        "-c",
                        (
                            "from pathlib import Path;"
                            f"Path({str(control)!r}).write_text("
                            "'{\"safe\": false}\\n')"
                        ),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                escaped.communicate(timeout=5)
                return {"status": "PASS", "outputs": [output]}

            report = stage_execution.execute_plan(
                root,
                plan,
                dispatcher=dispatch,
            )

            self.assertEqual(report["overall"], "FAIL")
            self.assertEqual(
                control.read_text(encoding="utf-8"),
                '{"safe": true}\n',
            )
            self.assertIn(
                "director_plan.json",
                report["completions"][0]["error"],
            )

    def test_targeted_audit_removes_new_job_control_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job_root = root / "output/job-001"
            job_root.mkdir(parents=True)
            created = job_root / "seedance/new-control.json"
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "pre_seedance_pack",
                    "packets": [
                        {
                            "packet_id": "part1",
                            "executor_kind": "agent",
                            "task": "Write the declared result.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work/part1",
                            ],
                            "completion_path": (
                                "output/job-001/work/completion.json"
                            ),
                        }
                    ],
                },
            )

            def dispatch(packet):
                output = (
                    Path(packet["allowed_write_roots"][0])
                    / "result.txt"
                )
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("PASS\n", encoding="utf-8")
                escaped = stage_execution._ORIGINAL_POPEN(
                    [
                        "python3",
                        "-c",
                        (
                            "from pathlib import Path;"
                            f"p=Path({str(created)!r});"
                            "p.parent.mkdir(parents=True, exist_ok=True);"
                            "p.write_text('{}\\n')"
                        ),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                escaped.communicate(timeout=5)
                return {"status": "PASS", "outputs": [output]}

            report = stage_execution.execute_plan(
                root,
                plan,
                dispatcher=dispatch,
            )

            self.assertEqual(report["overall"], "FAIL")
            self.assertFalse(created.exists())
            self.assertIn(
                "new-control.json",
                report["completions"][0]["error"],
            )

    def test_serial_fallback_removes_new_workspace_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            output = "output/job-001/work/result.txt"
            rogue = root / "rogue.bin"
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "story",
                            "command": ["unused"],
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work",
                            ],
                            "expected_outputs": [output],
                            "completion_path": (
                                "output/job-001/work/completion.json"
                            ),
                        }
                    ],
                },
            )

            def dispatch(packet):
                staged = (
                    Path(packet["allowed_write_roots"][0])
                    / "result.txt"
                )
                script = (
                    "from pathlib import Path;"
                    f"out=Path({str(staged)!r});"
                    "out.parent.mkdir(parents=True, exist_ok=True);"
                    "out.write_text('PASS\\n');"
                    f"Path({str(rogue)!r}).write_bytes(b'rogue')"
                )
                completed = subprocess.run(
                    ["python3", "-c", script],
                    check=False,
                )
                return {
                    "status": (
                        "PASS" if completed.returncode == 0 else "FAIL"
                    ),
                    "outputs": [staged],
                }

            with mock.patch.object(
                stage_execution,
                "_sandbox_execution_available",
                return_value=False,
            ):
                report = stage_execution.execute_plan(
                    root,
                    plan,
                    dispatcher=dispatch,
                )

            self.assertEqual(report["overall"], "FAIL")
            self.assertFalse(rogue.exists())
            self.assertIn(
                "rogue.bin",
                report["completions"][0]["error"],
            )

    def test_serial_fallback_removes_new_workspace_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            important = root / "important.txt"
            important.write_text("keep\n", encoding="utf-8")
            rogue = root / "rogue-link"
            output = "output/job-001/work/result.txt"
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "story",
                            "executor_kind": "agent",
                            "task": "Run the injected worker.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work",
                            ],
                            "completion_path": (
                                "output/job-001/work/completion.json"
                            ),
                        }
                    ],
                },
            )

            def dispatch(packet):
                staged = (
                    Path(packet["allowed_write_roots"][0])
                    / "result.txt"
                )
                script = (
                    "from pathlib import Path;"
                    f"out=Path({str(staged)!r});"
                    "out.parent.mkdir(parents=True, exist_ok=True);"
                    "out.write_text('PASS\\n');"
                    f"Path({str(rogue)!r}).symlink_to("
                    f"Path({str(important)!r}))"
                )
                completed = subprocess.run(
                    ["python3", "-c", script],
                    check=False,
                )
                return {
                    "status": (
                        "PASS" if completed.returncode == 0 else "FAIL"
                    ),
                    "outputs": [staged],
                }

            with mock.patch.object(
                stage_execution,
                "_sandbox_execution_available",
                return_value=False,
            ):
                report = stage_execution.execute_plan(
                    root,
                    plan,
                    dispatcher=dispatch,
                )

            self.assertEqual(report["overall"], "FAIL")
            self.assertTrue(important.is_file())
            self.assertEqual(
                important.read_text(encoding="utf-8"),
                "keep\n",
            )
            self.assertFalse(rogue.exists())
            self.assertFalse(rogue.is_symlink())

    def test_serial_fallback_removes_new_file_in_ignored_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / ".gitignore").write_text(
                "output/\n",
                encoding="utf-8",
            )
            rogue = root / "output/job-999/final/final_video.mp4"
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "story",
                            "executor_kind": "agent",
                            "task": "Run the injected worker.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work",
                            ],
                            "completion_path": (
                                "output/job-001/work/completion.json"
                            ),
                        }
                    ],
                },
            )

            def dispatch(packet):
                staged = (
                    Path(packet["allowed_write_roots"][0])
                    / "result.txt"
                )
                script = (
                    "from pathlib import Path;"
                    f"out=Path({str(staged)!r});"
                    "out.parent.mkdir(parents=True, exist_ok=True);"
                    "out.write_text('PASS\\n');"
                    f"rogue=Path({str(rogue)!r});"
                    "rogue.parent.mkdir(parents=True, exist_ok=True);"
                    "rogue.write_bytes(b'rogue')"
                )
                completed = subprocess.run(
                    ["python3", "-c", script],
                    check=False,
                )
                return {
                    "status": (
                        "PASS" if completed.returncode == 0 else "FAIL"
                    ),
                    "outputs": [staged],
                }

            with mock.patch.object(
                stage_execution,
                "_sandbox_execution_available",
                return_value=False,
            ):
                report = stage_execution.execute_plan(
                    root,
                    plan,
                    dispatcher=dispatch,
                )

            self.assertEqual(report["overall"], "FAIL")
            self.assertFalse(rogue.exists())
            self.assertIn(
                "job-999",
                report["completions"][0]["error"],
            )

    def test_serial_fallback_restores_existing_other_job_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / ".gitignore").write_text(
                "output/\n",
                encoding="utf-8",
            )
            protected = root / "output/job-999/final/final_video.mp4"
            protected.parent.mkdir(parents=True)
            protected.write_bytes(b"original")
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "story",
                            "executor_kind": "agent",
                            "task": "Run the injected worker.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work",
                            ],
                            "completion_path": (
                                "output/job-001/work/completion.json"
                            ),
                        }
                    ],
                },
            )

            def dispatch(packet):
                staged = (
                    Path(packet["allowed_write_roots"][0])
                    / "result.txt"
                )
                script = (
                    "from pathlib import Path;"
                    f"out=Path({str(staged)!r});"
                    "out.parent.mkdir(parents=True, exist_ok=True);"
                    "out.write_text('PASS\\n');"
                    f"target=Path({str(protected)!r});"
                    "target.parent.mkdir(parents=True, exist_ok=True);"
                    "target.write_bytes(b'corrupt')"
                )
                completed = subprocess.run(
                    ["python3", "-c", script],
                    check=False,
                )
                return {
                    "status": (
                        "PASS" if completed.returncode == 0 else "FAIL"
                    ),
                    "outputs": [staged],
                }

            with mock.patch.object(
                stage_execution,
                "_sandbox_execution_available",
                return_value=False,
            ):
                report = stage_execution.execute_plan(
                    root,
                    plan,
                    dispatcher=dispatch,
                )

            self.assertEqual(report["overall"], "FAIL")
            self.assertEqual(protected.read_bytes(), b"original")

    def test_serial_fallback_restores_current_job_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / ".gitignore").write_text(
                "output/\n",
                encoding="utf-8",
            )
            protected = root / "output/job-001/final/final_video.mp4"
            protected.parent.mkdir(parents=True)
            protected.write_bytes(b"original-current-job")
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "story",
                            "executor_kind": "agent",
                            "task": "Run the injected worker.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work",
                            ],
                            "completion_path": (
                                "output/job-001/work/completion.json"
                            ),
                        }
                    ],
                },
            )

            def dispatch(packet):
                staged = (
                    Path(packet["allowed_write_roots"][0])
                    / "result.txt"
                )
                script = (
                    "from pathlib import Path;"
                    f"out=Path({str(staged)!r});"
                    "out.parent.mkdir(parents=True, exist_ok=True);"
                    "out.write_text('PASS\\n');"
                    f"Path({str(protected)!r}).write_bytes(b'corrupt')"
                )
                completed = subprocess.run(
                    ["python3", "-c", script],
                    check=False,
                )
                return {
                    "status": (
                        "PASS" if completed.returncode == 0 else "FAIL"
                    ),
                    "outputs": [staged],
                }

            with mock.patch.object(
                stage_execution,
                "_sandbox_execution_available",
                return_value=False,
            ):
                report = stage_execution.execute_plan(
                    root,
                    plan,
                    dispatcher=dispatch,
                )

            self.assertEqual(report["overall"], "FAIL")
            self.assertEqual(
                protected.read_bytes(),
                b"original-current-job",
            )

    def test_serial_fallback_restores_git_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            tracked = root / "tracked.txt"
            tracked.write_text("safe\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", "tracked.txt"],
                cwd=root,
                check=True,
            )
            git_index = root / ".git/index"
            original_index = git_index.read_bytes()
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "story",
                            "executor_kind": "agent",
                            "task": "Run the injected worker.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work",
                            ],
                            "completion_path": (
                                "output/job-001/work/completion.json"
                            ),
                        }
                    ],
                },
            )

            def dispatch(packet):
                staged = (
                    Path(packet["allowed_write_roots"][0])
                    / "result.txt"
                )
                script = (
                    "from pathlib import Path;"
                    f"out=Path({str(staged)!r});"
                    "out.parent.mkdir(parents=True, exist_ok=True);"
                    "out.write_text('PASS\\n');"
                    f"index=Path({str(git_index)!r});"
                    "index.parent.mkdir(parents=True, exist_ok=True);"
                    "index.write_bytes(b'broken')"
                )
                completed = subprocess.run(
                    ["python3", "-c", script],
                    check=False,
                )
                return {
                    "status": (
                        "PASS" if completed.returncode == 0 else "FAIL"
                    ),
                    "outputs": [staged],
                }

            with mock.patch.object(
                stage_execution,
                "_sandbox_execution_available",
                return_value=False,
            ):
                report = stage_execution.execute_plan(
                    root,
                    plan,
                    dispatcher=dispatch,
                )

            self.assertEqual(report["overall"], "FAIL")
            self.assertEqual(git_index.read_bytes(), original_index)
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root,
                check=True,
                capture_output=True,
            )

    def test_serial_fallback_restores_git_branch_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            tracked = root / "tracked.txt"
            tracked.write_text("safe\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Stage Test",
                    "-c",
                    "user.email=stage@example.invalid",
                    "commit",
                    "-qm",
                    "initial",
                ],
                cwd=root,
                check=True,
            )
            head_ref = (
                subprocess.run(
                    ["git", "symbolic-ref", "HEAD"],
                    cwd=root,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                .stdout.strip()
            )
            branch_ref = root / ".git" / head_ref
            original_ref = branch_ref.read_text(encoding="utf-8")
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "story",
                            "executor_kind": "agent",
                            "task": "Run the injected worker.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work",
                            ],
                            "completion_path": (
                                "output/job-001/work/completion.json"
                            ),
                        }
                    ],
                },
            )

            def dispatch(packet):
                staged = (
                    Path(packet["allowed_write_roots"][0])
                    / "result.txt"
                )
                script = (
                    "from pathlib import Path;"
                    f"out=Path({str(staged)!r});"
                    "out.parent.mkdir(parents=True, exist_ok=True);"
                    "out.write_text('PASS\\n');"
                    f"ref=Path({str(branch_ref)!r});"
                    "ref.parent.mkdir(parents=True, exist_ok=True);"
                    "ref.write_text('0' * 40 + '\\n')"
                )
                completed = subprocess.run(
                    ["python3", "-c", script],
                    check=False,
                )
                return {
                    "status": (
                        "PASS" if completed.returncode == 0 else "FAIL"
                    ),
                    "outputs": [staged],
                }

            with mock.patch.object(
                stage_execution,
                "_sandbox_execution_available",
                return_value=False,
            ):
                report = stage_execution.execute_plan(
                    root,
                    plan,
                    dispatcher=dispatch,
                )

            self.assertEqual(report["overall"], "FAIL")
            self.assertEqual(
                branch_ref.read_text(encoding="utf-8"),
                original_ref,
            )

    def test_serial_fallback_rechecks_after_restoring_gitignore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            gitignore = root / ".gitignore"
            gitignore.write_text("# keep visible\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", ".gitignore"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Stage Test",
                    "-c",
                    "user.email=stage@example.invalid",
                    "commit",
                    "-qm",
                    "track ignore rules",
                ],
                cwd=root,
                check=True,
            )
            rogue = root / "hidden.rogue"
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "story",
                            "executor_kind": "agent",
                            "task": "Run the injected worker.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work",
                            ],
                            "completion_path": (
                                "output/job-001/work/completion.json"
                            ),
                        }
                    ],
                },
            )

            def dispatch(packet):
                staged = (
                    Path(packet["allowed_write_roots"][0])
                    / "result.txt"
                )
                script = (
                    "from pathlib import Path;"
                    f"out=Path({str(staged)!r});"
                    "out.parent.mkdir(parents=True, exist_ok=True);"
                    "out.write_text('PASS\\n');"
                    f"Path({str(gitignore)!r}).write_text('*.rogue\\n');"
                    f"Path({str(rogue)!r}).write_bytes(b'rogue')"
                )
                completed = subprocess.run(
                    ["python3", "-c", script],
                    check=False,
                )
                return {
                    "status": (
                        "PASS" if completed.returncode == 0 else "FAIL"
                    ),
                    "outputs": [staged],
                }

            with mock.patch.object(
                stage_execution,
                "_sandbox_execution_available",
                return_value=False,
            ):
                report = stage_execution.execute_plan(
                    root,
                    plan,
                    dispatcher=dispatch,
                )

            self.assertEqual(report["overall"], "FAIL")
            self.assertEqual(
                gitignore.read_text(encoding="utf-8"),
                "# keep visible\n",
            )
            self.assertFalse(rogue.exists())

    def test_serial_fallback_keeps_preexisting_ignored_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            gitignore = root / ".gitignore"
            gitignore.write_text("*.keep\n", encoding="utf-8")
            subprocess.run(
                ["git", "add", ".gitignore"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Stage Test",
                    "-c",
                    "user.email=stage@example.invalid",
                    "commit",
                    "-qm",
                    "track ignore rules",
                ],
                cwd=root,
                check=True,
            )
            ignored = root / "user-file.keep"
            ignored.write_bytes(b"preserve")
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "story",
                            "executor_kind": "agent",
                            "task": "Run the injected worker.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work",
                            ],
                            "completion_path": (
                                "output/job-001/work/completion.json"
                            ),
                        }
                    ],
                },
            )

            def dispatch(packet):
                staged = (
                    Path(packet["allowed_write_roots"][0])
                    / "result.txt"
                )
                script = (
                    "from pathlib import Path;"
                    f"out=Path({str(staged)!r});"
                    "out.parent.mkdir(parents=True, exist_ok=True);"
                    "out.write_text('PASS\\n');"
                    f"Path({str(gitignore)!r}).write_text('# changed\\n')"
                )
                completed = subprocess.run(
                    ["python3", "-c", script],
                    check=False,
                )
                return {
                    "status": (
                        "PASS" if completed.returncode == 0 else "FAIL"
                    ),
                    "outputs": [staged],
                }

            with mock.patch.object(
                stage_execution,
                "_sandbox_execution_available",
                return_value=False,
            ):
                report = stage_execution.execute_plan(
                    root,
                    plan,
                    dispatcher=dispatch,
                )

            self.assertEqual(report["overall"], "FAIL")
            self.assertEqual(ignored.read_bytes(), b"preserve")
            self.assertEqual(
                gitignore.read_text(encoding="utf-8"),
                "*.keep\n",
            )

    def test_serial_fallback_restores_deleted_large_dirty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            important = root / "large-user-file.bin"
            original = b"x" * (stage_execution.MAX_RESTORABLE_BYTES + 1)
            important.write_bytes(original)
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "story",
                            "executor_kind": "agent",
                            "task": "Run the injected worker.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work",
                            ],
                            "completion_path": (
                                "output/job-001/work/completion.json"
                            ),
                        }
                    ],
                },
            )

            def dispatch(packet):
                staged = (
                    Path(packet["allowed_write_roots"][0])
                    / "result.txt"
                )
                script = (
                    "from pathlib import Path;"
                    f"out=Path({str(staged)!r});"
                    "out.parent.mkdir(parents=True, exist_ok=True);"
                    "out.write_text('PASS\\n');"
                    f"Path({str(important)!r}).unlink()"
                )
                completed = subprocess.run(
                    ["python3", "-c", script],
                    check=False,
                )
                return {
                    "status": (
                        "PASS" if completed.returncode == 0 else "FAIL"
                    ),
                    "outputs": [staged],
                }

            with mock.patch.object(
                stage_execution,
                "_sandbox_execution_available",
                return_value=False,
            ):
                report = stage_execution.execute_plan(
                    root,
                    plan,
                    dispatcher=dispatch,
                )

            self.assertEqual(report["overall"], "FAIL")
            self.assertEqual(important.read_bytes(), original)

    def test_prepare_time_includes_target_discovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "story",
                            "executor_kind": "agent",
                            "task": "Write the declared result.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work",
                            ],
                            "completion_path": (
                                "output/job-001/work/completion.json"
                            ),
                        }
                    ],
                },
            )
            original = stage_execution._job_control_paths

            def slow_discovery(*args):
                time.sleep(0.01)
                return original(*args)

            def dispatch(packet):
                output = (
                    Path(packet["allowed_write_roots"][0])
                    / "result.txt"
                )
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("PASS\n", encoding="utf-8")
                return {"status": "PASS", "outputs": [output]}

            with mock.patch.object(
                stage_execution,
                "_job_control_paths",
                side_effect=slow_discovery,
            ):
                report = stage_execution.execute_plan(
                    root,
                    plan,
                    dispatcher=dispatch,
                )

            self.assertGreaterEqual(
                report["timing"]["prepare_seconds"],
                0.009,
            )

    def test_prepare_time_includes_serial_fallback_protection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "story",
                            "executor_kind": "agent",
                            "task": "Write the declared result.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work",
                            ],
                            "completion_path": (
                                "output/job-001/work/completion.json"
                            ),
                        }
                    ],
                },
            )
            original = stage_execution._snapshot_large_status_paths

            def slow_protection(*args):
                time.sleep(0.01)
                return original(*args)

            def dispatch(packet):
                output = (
                    Path(packet["allowed_write_roots"][0])
                    / "result.txt"
                )
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("PASS\n", encoding="utf-8")
                return {"status": "PASS", "outputs": [output]}

            with mock.patch.object(
                stage_execution,
                "_sandbox_execution_available",
                return_value=False,
            ), mock.patch.object(
                stage_execution,
                "_snapshot_large_status_paths",
                side_effect=slow_protection,
            ):
                report = stage_execution.execute_plan(
                    root,
                    plan,
                    dispatcher=dispatch,
                )

            self.assertGreaterEqual(
                report["timing"]["prepare_seconds"],
                0.009,
            )

    def test_full_repository_audit_remains_available_for_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "story",
                            "executor_kind": "agent",
                            "task": "Write the declared result.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work",
                            ],
                            "completion_path": (
                                "output/job-001/work/completion.json"
                            ),
                        }
                    ],
                },
            )

            def dispatch(packet):
                output = (
                    Path(packet["allowed_write_roots"][0])
                    / "result.txt"
                )
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("PASS\n", encoding="utf-8")
                return {"status": "PASS", "outputs": [output]}

            with mock.patch.object(
                stage_execution,
                "_capture_output_tree",
                wraps=stage_execution._capture_output_tree,
            ) as capture:
                report = stage_execution.execute_plan(
                    root,
                    plan,
                    dispatcher=dispatch,
                    audit_mode="full",
                )

            self.assertEqual(report["overall"], "PASS")
            self.assertEqual(capture.call_count, 2)
            self.assertEqual(report["timing"]["audit_mode"], "full")
            self.assertGreaterEqual(
                report["timing"]["repository_audit_seconds"],
                0.0,
            )


if __name__ == "__main__":
    unittest.main()
