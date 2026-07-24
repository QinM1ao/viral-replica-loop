import _thread
import importlib
import json
import os
import socket
import stat
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from tools import stage_execution


class StageExecutionTest(unittest.TestCase):
    @staticmethod
    def runtime_path(root, value):
        path = Path(value)
        return path if path.is_absolute() else root / path

    def test_execute_rejects_an_unsealed_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = {
                "schema_version": 1,
                "job_id": "job-001",
                "stage": "source_blueprint",
                "packets": [
                    {
                        "packet_id": "story",
                        "command": ["python3", "story.py"],
                        "depends_on": [],
                        "allowed_write_roots": [
                            "output/job-001/work/story",
                        ],
                        "completion_path": (
                            "output/job-001/work/completions/story.json"
                        ),
                    }
                ],
            }

            with self.assertRaisesRegex(
                stage_execution.PlanError,
                "sealed plan",
            ):
                stage_execution.execute_plan(root, plan)

    def test_rejects_job_id_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(
                stage_execution.PlanError,
                "job_id",
            ):
                stage_execution.validate_plan(
                    root,
                    {
                        "schema_version": 1,
                        "job_id": "../escape",
                        "stage": "image_batch_qc",
                        "packets": [
                            {
                                "packet_id": "part1",
                                "command": ["python3", "generate.py"],
                                "depends_on": [],
                                "allowed_write_roots": [
                                    "output/escape/part1",
                                ],
                                "completion_path": (
                                    "output/escape/part1/completion.json"
                                ),
                            }
                        ],
                    },
                )

    def test_coordinator_only_mutation_is_blocked_before_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "STATE.md"
            state.write_text("coordinator-owned\n", encoding="utf-8")
            output = root / "output/job-001/work/part1/result.txt"
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "image_batch_qc",
                    "packets": [
                        {
                            "packet_id": "part1",
                            "executor_kind": "agent",
                            "task": "Write only the declared Part output.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work/part1",
                            ],
                            "completion_path": (
                                "output/job-001/work/completions/part1.json"
                            ),
                        }
                    ],
                },
            )

            def violating_dispatcher(unused_packet):
                staged_output = (
                    self.runtime_path(
                        root,
                        unused_packet["allowed_write_roots"][0],
                    )
                    / "result.txt"
                )
                staged_output.parent.mkdir(parents=True)
                staged_output.write_text("part output\n", encoding="utf-8")
                state.write_text("sub-agent mutation\n", encoding="utf-8")
                return {"status": "PASS", "outputs": [staged_output]}

            report = stage_execution.execute_plan(
                root,
                plan,
                dispatcher=violating_dispatcher,
            )

            self.assertEqual(report["overall"], "FAIL")
            self.assertIn(
                "packet filesystem policy blocked open",
                report["completions"][0]["error"],
            )
            self.assertEqual(
                state.read_text(encoding="utf-8"),
                "coordinator-owned\n",
            )

    def test_ready_packets_respect_dependencies_and_isolated_write_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = {
                "schema_version": 1,
                "job_id": "job-001",
                "stage": "image_batch_qc",
                "coordinator_only_paths": [
                    "output/job-001/image-batch/codex_imagegen_contract.json",
                ],
                "packets": [
                    {
                        "packet_id": "part1",
                        "command": ["python3", "generate.py", "--part", "part1"],
                        "depends_on": [],
                        "allowed_write_roots": [
                            "output/job-001/image-batch/parts/part1",
                        ],
                        "completion_path": (
                            "output/job-001/work-packets/image_batch_qc/"
                            "completions/part1.json"
                        ),
                    },
                    {
                        "packet_id": "part2",
                        "command": ["python3", "generate.py", "--part", "part2"],
                        "depends_on": ["part1"],
                        "allowed_write_roots": [
                            "output/job-001/image-batch/parts/part2",
                        ],
                        "completion_path": (
                            "output/job-001/work-packets/image_batch_qc/"
                            "completions/part2.json"
                        ),
                    },
                ],
            }

            validated = stage_execution.validate_plan(root, plan)

            self.assertEqual(
                stage_execution.ready_packet_ids(validated, completed=set()),
                ["part1"],
            )
            self.assertEqual(
                stage_execution.ready_packet_ids(validated, completed={"part1"}),
                ["part2"],
            )

    def test_record_completion_binds_outputs_to_the_packet_write_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output/job-001/image-batch/parts/part1/candidate.png"
            output.parent.mkdir(parents=True)
            output.write_bytes(b"candidate")
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "image_batch_qc",
                    "packets": [
                        {
                            "packet_id": "part1",
                            "command": ["python3", "generate.py"],
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/image-batch/parts/part1",
                            ],
                            "completion_path": (
                                "output/job-001/work-packets/image_batch_qc/"
                                "completions/part1.json"
                            ),
                        }
                    ],
                },
            )

            completion = stage_execution.record_completion(
                root,
                plan,
                "part1",
                "PASS",
                [output],
            )

            self.assertEqual(completion["packet_id"], "part1")
            self.assertEqual(completion["status"], "PASS")
            self.assertEqual(
                completion["outputs"],
                [
                    {
                        "path": "output/job-001/image-batch/parts/part1/candidate.png",
                        "sha256": (
                            "dda18a0e21ae47c53b4309434cbc02ae8bf764fa83a6defb"
                            "b719431242722aa7"
                        ),
                    }
                ],
            )
            completion_path = (
                root
                / "output/job-001/work-packets/image_batch_qc/"
                "completions/part1.json"
            )
            self.assertEqual(
                json.loads(completion_path.read_text(encoding="utf-8")),
                completion,
            )

    def test_execute_dispatches_ready_packets_then_commits_once(self):
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
                            "task": "Render the story view from locked rhythm.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work/source/story",
                            ],
                            "completion_path": (
                                "output/job-001/work/source/story/completion.json"
                            ),
                        },
                        {
                            "packet_id": "timeline",
                            "executor_kind": "agent",
                            "task": "Render the timeline view from locked rhythm.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work/source/timeline",
                            ],
                            "completion_path": (
                                "output/job-001/work/source/timeline/completion.json"
                            ),
                        },
                        {
                            "packet_id": "merge-check",
                            "command": [
                                "python3",
                                "check.py",
                                "--out",
                                "output/job-001/work/check/result.json",
                            ],
                            "depends_on": ["story", "timeline"],
                            "allowed_write_roots": [
                                "output/job-001/work/source/merge",
                            ],
                            "completion_path": (
                                "output/job-001/work/source/merge/completion.json"
                            ),
                        },
                    ],
                },
            )
            barrier = threading.Barrier(2, timeout=2)
            started = []
            finished = set()
            dependency_snapshots = {}
            lock = threading.Lock()

            def dispatcher(packet):
                with lock:
                    started.append(packet["packet_id"])
                    dependency_snapshots[packet["packet_id"]] = set(finished)
                if packet["packet_id"] in {"story", "timeline"}:
                    barrier.wait()
                    time.sleep(0.01)
                output = (
                    root
                    / packet["allowed_write_roots"][0]
                    / f"{packet['packet_id']}.json"
                )
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text('{"overall":"PASS"}\n', encoding="utf-8")
                with lock:
                    finished.add(packet["packet_id"])
                return {"status": "PASS", "outputs": [output]}

            commits = []
            report = stage_execution.execute_plan(
                root,
                plan,
                dispatcher=dispatcher,
                coordinator_commit=commits.append,
                max_workers=3,
            )

            self.assertEqual(report["overall"], "PASS")
            self.assertEqual(len(commits), 1)
            self.assertEqual(commits[0], report)
            self.assertEqual(set(started[:2]), {"story", "timeline"})
            self.assertEqual(
                dependency_snapshots["merge-check"],
                {"story", "timeline"},
            )
            self.assertEqual(
                [item["packet_id"] for item in report["completions"]],
                ["story", "timeline", "merge-check"],
            )

    def test_command_packet_can_create_outputs_under_a_new_write_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "助理"
            root.mkdir()
            allowed = "output/job-001/work/new-root"
            output = f"{allowed}/nested/result.json"
            script = (
                "import pathlib,sys;"
                "p=pathlib.Path(sys.argv[1]);"
                "p.parent.mkdir(parents=True,exist_ok=True);"
                "p.write_text('{\"overall\":\"PASS\"}\\n')"
            )
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "source-task",
                            "command": ["python3", "-c", script, output],
                            "depends_on": [],
                            "allowed_write_roots": [allowed],
                            "expected_outputs": [output],
                            "completion_path": (
                                "output/job-001/work/completions/"
                                "source-task.json"
                            ),
                        }
                    ],
                },
            )

            report = stage_execution.execute_plan(root, plan)

            self.assertEqual(report["overall"], "PASS")
            self.assertEqual(
                json.loads((root / output).read_text(encoding="utf-8")),
                {"overall": "PASS"},
            )
            for packet in plan["packets"]:
                self.assertTrue(
                    (root / packet["completion_path"]).is_file()
                )

    def test_default_dispatcher_runs_only_command_packets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output/job-001/work/check/result.json"
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "request_qc",
                    "packets": [
                        {
                            "packet_id": "check",
                            "command": [
                                "python3",
                                "check.py",
                                "--out",
                                "output/job-001/work/check/result.json",
                            ],
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work/check",
                            ],
                            "expected_outputs": [
                                "output/job-001/work/check/result.json",
                            ],
                            "completion_path": (
                                "output/job-001/work/check/completion.json"
                            ),
                        }
                    ],
                },
            )

            def runner(command, **kwargs):
                command_output = self.runtime_path(
                    root,
                    command[command.index("--out") + 1],
                )
                command_output.parent.mkdir(parents=True, exist_ok=True)
                command_output.write_text(
                    '{"overall":"PASS"}\n',
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout="ok",
                    stderr="",
                )

            report = stage_execution.execute_plan(
                root,
                plan,
                runner=runner,
            )
            self.assertEqual(report["overall"], "PASS")
            self.assertEqual(report["completions"][0]["outputs"][0]["path"], (
                "output/job-001/work/check/result.json"
            ))

    def test_wave_blocks_current_job_side_write_before_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical = root / "output/job-001/checks/canonical.json"
            canonical.parent.mkdir(parents=True)
            canonical.write_text('{"owner":"coordinator"}\n', encoding="utf-8")
            allowed = root / "output/job-001/work/part1/result.json"
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "part1",
                            "executor_kind": "agent",
                            "task": "Write only the declared output.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work/part1",
                            ],
                            "completion_path": (
                                "output/job-001/work/completions/part1.json"
                            ),
                        }
                    ],
                },
            )

            def dispatcher(unused_packet):
                staged_allowed = (
                    self.runtime_path(
                        root,
                        unused_packet["allowed_write_roots"][0],
                    )
                    / "result.json"
                )
                staged_allowed.parent.mkdir(parents=True)
                staged_allowed.write_text(
                    '{"overall":"PASS"}\n',
                    encoding="utf-8",
                )
                canonical.write_text('{"owner":"packet"}\n', encoding="utf-8")
                return {"status": "PASS", "outputs": [staged_allowed]}

            report = stage_execution.execute_plan(
                root,
                plan,
                dispatcher=dispatcher,
            )

            self.assertEqual(report["overall"], "FAIL")
            self.assertEqual(report["completions"][0]["status"], "FAIL")
            self.assertIn(
                "packet filesystem policy blocked open",
                report["completions"][0]["error"],
            )
            self.assertIn(
                "output/job-001/checks/canonical.json",
                report["completions"][0]["error"],
            )
            self.assertEqual(
                canonical.read_text(encoding="utf-8"),
                '{"owner":"coordinator"}\n',
            )
            self.assertFalse(allowed.exists())

    def test_wave_blocks_cross_job_side_write_before_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            allowed = root / "output/job-001/work/part1/result.json"
            rogue = root / "output/job-002/rogue/nested/result.json"
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "part1",
                            "executor_kind": "agent",
                            "task": "Write only the declared output.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work/part1",
                            ],
                            "completion_path": (
                                "output/job-001/work/completions/part1.json"
                            ),
                        }
                    ],
                },
            )

            def dispatcher(unused_packet):
                staged_allowed = (
                    self.runtime_path(
                        root,
                        unused_packet["allowed_write_roots"][0],
                    )
                    / "result.json"
                )
                staged_allowed.parent.mkdir(parents=True)
                staged_allowed.write_text(
                    '{"overall":"PASS"}\n',
                    encoding="utf-8",
                )
                rogue.parent.mkdir(parents=True)
                rogue.write_text('{"forbidden":true}\n', encoding="utf-8")
                return {"status": "PASS", "outputs": [staged_allowed]}

            report = stage_execution.execute_plan(
                root,
                plan,
                dispatcher=dispatcher,
            )

            self.assertEqual(report["overall"], "FAIL")
            self.assertIn(
                "packet filesystem policy blocked os.mkdir",
                report["completions"][0]["error"],
            )
            self.assertIn(
                "output/job-002/rogue/nested",
                report["completions"][0]["error"],
            )
            self.assertFalse(rogue.exists())
            self.assertFalse((root / "output/job-002").exists())

    def test_wave_blocks_large_file_mutation_before_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            allowed = root / "output/job-001/work/part1/result.json"
            foreign = root / "output/job-002/existing.mp4"
            foreign.parent.mkdir(parents=True)
            foreign.write_bytes(b"x" * (1024 * 1024 + 1))
            foreign_before = foreign.stat()
            foreign_before_hash = stage_execution.sha256_file(foreign)
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "part1",
                            "executor_kind": "agent",
                            "task": "Write only the declared output.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work/part1",
                            ],
                            "completion_path": (
                                "output/job-001/work/completions/part1.json"
                            ),
                        }
                    ],
                },
            )

            def dispatcher(unused_packet):
                staged_allowed = (
                    self.runtime_path(
                        root,
                        unused_packet["allowed_write_roots"][0],
                    )
                    / "result.json"
                )
                staged_allowed.parent.mkdir(parents=True)
                staged_allowed.write_text(
                    '{"overall":"PASS"}\n',
                    encoding="utf-8",
                )
                foreign.write_bytes(b"y" * (1024 * 1024 + 1))
                os.utime(
                    foreign,
                    ns=(
                        foreign_before.st_atime_ns,
                        foreign_before.st_mtime_ns,
                    ),
                )
                return {"status": "PASS", "outputs": [staged_allowed]}

            report = stage_execution.execute_plan(
                root,
                plan,
                dispatcher=dispatcher,
            )

            self.assertEqual(report["overall"], "FAIL")
            self.assertIn(
                "packet filesystem policy blocked open",
                report["completions"][0]["error"],
            )
            self.assertIn(
                "output/job-002/existing.mp4",
                report["completions"][0]["error"],
            )
            self.assertNotIn(
                "restore unavailable",
                report["completions"][0]["error"],
            )
            self.assertEqual(
                stage_execution.sha256_file(foreign),
                foreign_before_hash,
            )

    def test_same_wave_packet_cannot_write_another_packets_final_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet_b_sentinel = (
                root / "output/job-001/work/part-b/sentinel.txt"
            )
            packet_b_sentinel.parent.mkdir(parents=True)
            packet_b_sentinel.write_text("owned-by-b\n", encoding="utf-8")
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "part-a",
                            "executor_kind": "agent",
                            "task": "Write only Part A.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work/part-a",
                            ],
                            "completion_path": (
                                "output/job-001/work/completions/part-a.json"
                            ),
                        },
                        {
                            "packet_id": "part-b",
                            "executor_kind": "agent",
                            "task": "Write only Part B.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work/part-b",
                            ],
                            "completion_path": (
                                "output/job-001/work/completions/part-b.json"
                            ),
                        },
                    ],
                },
            )
            barrier = threading.Barrier(2, timeout=2)

            def dispatcher(packet):
                staged = (
                    self.runtime_path(
                        root,
                        packet["allowed_write_roots"][0],
                    )
                    / f"{packet['packet_id']}.json"
                )
                staged.parent.mkdir(parents=True, exist_ok=True)
                staged.write_text('{"overall":"PASS"}\n', encoding="utf-8")
                if packet["packet_id"] == "part-a":
                    packet_b_sentinel.write_text(
                        "overwritten-by-a\n",
                        encoding="utf-8",
                    )
                barrier.wait()
                return {"status": "PASS", "outputs": [staged]}

            report = stage_execution.execute_plan(
                root,
                plan,
                dispatcher=dispatcher,
                max_workers=2,
            )

            self.assertEqual(report["overall"], "FAIL")
            self.assertEqual(
                {item["status"] for item in report["completions"]},
                {"FAIL"},
            )
            self.assertIn(
                "output/job-001/work/part-b/sentinel.txt",
                report["completions"][0]["error"],
            )
            self.assertEqual(
                packet_b_sentinel.read_text(encoding="utf-8"),
                "owned-by-b\n",
            )

    def test_same_wave_packet_cannot_poison_another_packets_staging_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet_b_sentinel = (
                root / "output/job-001/work/part-b/sentinel.txt"
            )
            packet_b_sentinel.parent.mkdir(parents=True)
            packet_b_sentinel.write_text("owned-by-b\n", encoding="utf-8")
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": packet_id,
                            "executor_kind": "agent",
                            "task": f"Write only {packet_id}.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                f"output/job-001/work/{packet_id}",
                            ],
                            "completion_path": (
                                "output/job-001/work/completions/"
                                f"{packet_id}.json"
                            ),
                        }
                        for packet_id in ("part-a", "part-b")
                    ],
                },
            )
            roots = {}
            barrier = threading.Barrier(2, timeout=2)
            lock = threading.Lock()

            def dispatcher(packet):
                own_root = Path(packet["allowed_write_roots"][0])
                with lock:
                    roots[packet["packet_id"]] = own_root
                output = own_root / f"{packet['packet_id']}.json"
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text('{"overall":"PASS"}\n', encoding="utf-8")
                barrier.wait()
                if packet["packet_id"] == "part-a":
                    (roots["part-b"] / "sentinel.txt").write_text(
                        "poisoned-by-a\n",
                        encoding="utf-8",
                    )
                barrier.wait()
                return {"status": "PASS", "outputs": [output]}

            report = stage_execution.execute_plan(
                root,
                plan,
                dispatcher=dispatcher,
                max_workers=2,
            )

            self.assertNotEqual(
                roots["part-a"].parents[1],
                roots["part-b"].parents[1],
            )
            self.assertEqual(report["overall"], "FAIL")
            self.assertIn("sentinel.txt", report["completions"][0]["error"])
            self.assertEqual(
                packet_b_sentinel.read_text(encoding="utf-8"),
                "owned-by-b\n",
            )

    def test_packet_cannot_overwrite_another_packets_declared_staging_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical_b = (
                root / "output/job-001/work/part-b/declared.json"
            )
            canonical_b.parent.mkdir(parents=True)
            canonical_b.write_text("original-b\n", encoding="utf-8")
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": packet_id,
                            "executor_kind": "agent",
                            "task": f"Write only {packet_id}.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                f"output/job-001/work/{packet_id}",
                            ],
                            "completion_path": (
                                "output/job-001/work/completions/"
                                f"{packet_id}.json"
                            ),
                        }
                        for packet_id in ("part-a", "part-b")
                    ],
                },
            )
            roots = {}
            first_barrier = threading.Barrier(2, timeout=2)
            second_barrier = threading.Barrier(2, timeout=2)
            third_barrier = threading.Barrier(2, timeout=2)
            blocked = []
            lock = threading.Lock()

            def dispatcher(packet):
                own_root = Path(packet["allowed_write_roots"][0])
                with lock:
                    roots[packet["packet_id"]] = own_root
                first_barrier.wait()
                output = own_root / "declared.json"
                if packet["packet_id"] == "part-b":
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_text("owned-by-b\n", encoding="utf-8")
                second_barrier.wait()
                if packet["packet_id"] == "part-a":
                    try:
                        (roots["part-b"] / "declared.json").write_text(
                            "poisoned-by-a\n",
                            encoding="utf-8",
                        )
                    except OSError:
                        blocked.append(True)
                third_barrier.wait()
                if packet["packet_id"] == "part-a":
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_text("owned-by-a\n", encoding="utf-8")
                return {"status": "PASS", "outputs": [output]}

            report = stage_execution.execute_plan(
                root,
                plan,
                dispatcher=dispatcher,
                max_workers=2,
            )

            self.assertTrue(blocked)
            self.assertEqual(report["overall"], "FAIL")
            self.assertEqual(
                canonical_b.read_text(encoding="utf-8"),
                "original-b\n",
            )

    def test_runtime_symlink_cannot_write_an_external_victim(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace_parent = Path(tmp)
            root = workspace_parent / "workspace"
            root.mkdir()
            victim = workspace_parent / "external-victim.txt"
            victim.write_text("safe\n", encoding="utf-8")
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "part1",
                            "executor_kind": "agent",
                            "task": "Write only the declared output.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work/part1",
                            ],
                            "completion_path": (
                                "output/job-001/work/completions/part1.json"
                            ),
                        }
                    ],
                },
            )
            blocked = []

            def dispatcher(packet):
                own_root = Path(packet["allowed_write_roots"][0])
                own_root.mkdir(parents=True, exist_ok=True)
                escape = own_root / "escape"
                try:
                    escape.symlink_to(
                        workspace_parent,
                        target_is_directory=True,
                    )
                    (escape / victim.name).write_text(
                        "hacked\n",
                        encoding="utf-8",
                    )
                except OSError:
                    blocked.append(True)
                output = own_root / "declared.json"
                output.write_text('{"overall":"PASS"}\n', encoding="utf-8")
                return {"status": "PASS", "outputs": [output]}

            report = stage_execution.execute_plan(
                root,
                plan,
                dispatcher=dispatcher,
            )

            self.assertTrue(blocked)
            self.assertEqual(report["overall"], "FAIL")
            self.assertEqual(victim.read_text(encoding="utf-8"), "safe\n")

    def test_packet_child_thread_inherits_write_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace_parent = Path(tmp)
            root = workspace_parent / "workspace"
            root.mkdir()
            victim = workspace_parent / "external-victim.txt"
            victim.write_text("safe\n", encoding="utf-8")
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "part1",
                            "executor_kind": "agent",
                            "task": "Write only the declared output.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work/part1",
                            ],
                            "completion_path": (
                                "output/job-001/work/completions/part1.json"
                            ),
                        }
                    ],
                },
            )
            blocked = []

            def dispatcher(packet):
                own_root = Path(packet["allowed_write_roots"][0])
                output = own_root / "declared.json"
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text('{"overall":"PASS"}\n', encoding="utf-8")

                def child_write():
                    try:
                        victim.write_text("hacked\n", encoding="utf-8")
                    except OSError:
                        blocked.append(True)

                child = threading.Thread(target=child_write)
                child.start()
                child.join(timeout=2)
                self.assertFalse(child.is_alive())
                return {"status": "PASS", "outputs": [output]}

            report = stage_execution.execute_plan(
                root,
                plan,
                dispatcher=dispatcher,
            )

            self.assertTrue(blocked)
            self.assertEqual(report["overall"], "FAIL")
            self.assertEqual(victim.read_text(encoding="utf-8"), "safe\n")

    def test_low_level_thread_entrypoints_are_blocked_after_module_reload(self):
        importlib.reload(stage_execution)
        importlib.reload(stage_execution)

        for entrypoint in ("start_new_thread", "start_new"):
            with self.subTest(entrypoint=entrypoint):
                with tempfile.TemporaryDirectory() as tmp:
                    workspace_parent = Path(tmp)
                    root = workspace_parent / "workspace"
                    root.mkdir()
                    victim = workspace_parent / "external-victim.txt"
                    victim.write_text("safe\n", encoding="utf-8")
                    plan = stage_execution.seal_plan(
                        root,
                        {
                            "schema_version": 1,
                            "job_id": "job-001",
                            "stage": "source_blueprint",
                            "packets": [
                                {
                                    "packet_id": "part1",
                                    "executor_kind": "agent",
                                    "task": "Write only the declared output.",
                                    "depends_on": [],
                                    "allowed_write_roots": [
                                        "output/job-001/work/part1",
                                    ],
                                    "completion_path": (
                                        "output/job-001/work/completions/"
                                        "part1.json"
                                    ),
                                }
                            ],
                        },
                    )
                    blocked = []
                    child_finished = threading.Event()

                    def dispatcher(packet):
                        own_root = Path(packet["allowed_write_roots"][0])
                        output = own_root / "declared.json"
                        output.parent.mkdir(parents=True, exist_ok=True)
                        output.write_text(
                            '{"overall":"PASS"}\n',
                            encoding="utf-8",
                        )

                        def low_level_write():
                            victim.write_text("hacked\n", encoding="utf-8")
                            child_finished.set()

                        try:
                            getattr(_thread, entrypoint)(low_level_write, ())
                        except PermissionError:
                            blocked.append(True)
                        return {"status": "PASS", "outputs": [output]}

                    report = stage_execution.execute_plan(
                        root,
                        plan,
                        dispatcher=dispatcher,
                    )
                    child_finished.wait(timeout=0.2)

                    self.assertTrue(blocked)
                    self.assertEqual(report["overall"], "FAIL")
                    self.assertEqual(
                        victim.read_text(encoding="utf-8"),
                        "safe\n",
                    )

    def test_agent_dispatcher_cannot_modify_ignored_git_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git_config = root / ".git/config"
            git_config.parent.mkdir()
            git_config.write_text("[safe]\n", encoding="utf-8")
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "part1",
                            "executor_kind": "agent",
                            "task": "Write only the declared output.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work/part1",
                            ],
                            "completion_path": (
                                "output/job-001/work/completions/part1.json"
                            ),
                        }
                    ],
                },
            )

            def dispatcher(packet):
                own_root = Path(packet["allowed_write_roots"][0])
                output = own_root / "declared.json"
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text('{"overall":"PASS"}\n', encoding="utf-8")
                git_config.write_text("[hacked]\n", encoding="utf-8")
                return {"status": "PASS", "outputs": [output]}

            report = stage_execution.execute_plan(
                root,
                plan,
                dispatcher=dispatcher,
            )

            self.assertEqual(report["overall"], "FAIL")
            self.assertIn(
                "packet filesystem policy blocked open",
                report["completions"][0]["error"],
            )
            self.assertEqual(
                git_config.read_text(encoding="utf-8"),
                "[safe]\n",
            )

    @unittest.skipUnless(hasattr(os, "fork"), "os.fork is unavailable")
    def test_os_fork_cannot_delay_canonical_write_past_execution(self):
        importlib.reload(stage_execution)
        importlib.reload(stage_execution)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical = root / "output/job-001/canonical.txt"
            canonical.parent.mkdir(parents=True)
            canonical.write_text("safe\n", encoding="utf-8")
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "part1",
                            "executor_kind": "agent",
                            "task": "Write only the declared output.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work/part1",
                            ],
                            "completion_path": (
                                "output/job-001/work/completions/part1.json"
                            ),
                        }
                    ],
                },
            )
            blocked = []
            child_pids = []

            def dispatcher(packet):
                own_root = Path(packet["allowed_write_roots"][0])
                output = own_root / "declared.json"
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text('{"overall":"PASS"}\n', encoding="utf-8")
                try:
                    child_pid = os.fork()
                except PermissionError:
                    blocked.append(True)
                else:
                    if child_pid == 0:
                        time.sleep(0.1)
                        canonical.write_text("hacked\n", encoding="utf-8")
                        os._exit(0)
                    child_pids.append(child_pid)
                return {"status": "PASS", "outputs": [output]}

            report = stage_execution.execute_plan(
                root,
                plan,
                dispatcher=dispatcher,
            )
            for child_pid in child_pids:
                os.waitpid(child_pid, 0)

            self.assertTrue(blocked)
            self.assertEqual(report["overall"], "FAIL")
            self.assertEqual(
                canonical.read_text(encoding="utf-8"),
                "safe\n",
            )

    @unittest.skipUnless(hasattr(os, "forkpty"), "os.forkpty is unavailable")
    def test_os_forkpty_is_blocked_inside_packet_policy(self):
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
                            "packet_id": "part1",
                            "executor_kind": "agent",
                            "task": "Write only the declared output.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work/part1",
                            ],
                            "completion_path": (
                                "output/job-001/work/completions/part1.json"
                            ),
                        }
                    ],
                },
            )
            blocked = []
            children = []

            def dispatcher(packet):
                own_root = Path(packet["allowed_write_roots"][0])
                output = own_root / "declared.json"
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text('{"overall":"PASS"}\n', encoding="utf-8")
                try:
                    child_pid, child_fd = os.forkpty()
                except PermissionError:
                    blocked.append(True)
                else:
                    if child_pid == 0:
                        os._exit(0)
                    os.close(child_fd)
                    children.append(child_pid)
                return {"status": "PASS", "outputs": [output]}

            report = stage_execution.execute_plan(
                root,
                plan,
                dispatcher=dispatcher,
            )
            for child_pid in children:
                os.waitpid(child_pid, 0)

            self.assertTrue(blocked)
            self.assertEqual(report["overall"], "FAIL")

    def test_timed_out_packet_child_cannot_write_canonical_after_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical = root / "output/job-001/canonical.txt"
            canonical.parent.mkdir(parents=True)
            canonical.write_text("safe\n", encoding="utf-8")
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "part1",
                            "executor_kind": "agent",
                            "task": "Write only the declared output.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work/part1",
                            ],
                            "completion_path": (
                                "output/job-001/work/completions/part1.json"
                            ),
                        }
                    ],
                },
            )
            release_child = threading.Event()
            child_finished = threading.Event()
            child_errors = []

            def dispatcher(packet):
                own_root = Path(packet["allowed_write_roots"][0])
                output = own_root / "declared.json"
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text('{"overall":"PASS"}\n', encoding="utf-8")

                def delayed_write():
                    release_child.wait(timeout=2)

                    def nested_write():
                        try:
                            canonical.write_text("hacked\n", encoding="utf-8")
                        except OSError as exc:
                            child_errors.append(exc)

                    nested = threading.Thread(target=nested_write)
                    nested.start()
                    nested.join(timeout=2)
                    child_finished.set()

                threading.Thread(target=delayed_write).start()
                return {"status": "PASS", "outputs": [output]}

            original_wait = stage_execution._wait_for_packet_threads

            def short_wait(policy):
                return original_wait(policy, timeout_seconds=0.01)

            stage_execution._wait_for_packet_threads = short_wait
            try:
                report = stage_execution.execute_plan(
                    root,
                    plan,
                    dispatcher=dispatcher,
                )
            finally:
                stage_execution._wait_for_packet_threads = original_wait
                release_child.set()

            self.assertTrue(child_finished.wait(timeout=2))
            self.assertEqual(report["overall"], "FAIL")
            self.assertTrue(child_errors)
            self.assertEqual(
                canonical.read_text(encoding="utf-8"),
                "safe\n",
            )

    def test_command_packet_cannot_write_through_symlink_to_external_victim(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace_parent = Path(tmp)
            root = workspace_parent / "workspace"
            root.mkdir()
            victim = workspace_parent / "external-victim.txt"
            victim.write_text("safe\n", encoding="utf-8")
            allowed = "output/job-001/work/part1"
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "part1",
                            "command": [
                                "/bin/sh",
                                "-c",
                                (
                                    'mkdir -p "$2" && '
                                    'ln -s "$1" "$2/escape" && '
                                    'echo hacked > "$2/escape/'
                                    f'{victim.name}"'
                                ),
                                "sh",
                                str(workspace_parent),
                                allowed,
                            ],
                            "depends_on": [],
                            "allowed_write_roots": [allowed],
                            "expected_outputs": [],
                            "completion_path": (
                                "output/job-001/work/completions/part1.json"
                            ),
                        }
                    ],
                },
            )

            report = stage_execution.execute_plan(root, plan)

            self.assertEqual(report["overall"], "FAIL")
            self.assertEqual(victim.read_text(encoding="utf-8"), "safe\n")

    def test_detached_command_child_cannot_overwrite_canonical_after_promotion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical = root / "output/job-001/canonical.txt"
            canonical.parent.mkdir(parents=True)
            canonical.write_text("safe\n", encoding="utf-8")
            allowed = "output/job-001/work/part1"
            output = f"{allowed}/declared.json"
            child_script = (
                "import pathlib,sys,time;"
                "time.sleep(0.25);"
                "pathlib.Path(sys.argv[1]).write_text('hacked\\n')"
            )
            parent_script = (
                "import pathlib,subprocess,sys;"
                "subprocess.Popen("
                "[sys.executable,'-c',sys.argv[3],sys.argv[2]],"
                "stdin=subprocess.DEVNULL,"
                "stdout=subprocess.DEVNULL,"
                "stderr=subprocess.DEVNULL,"
                "start_new_session=True);"
                "p=pathlib.Path(sys.argv[1]);"
                "p.parent.mkdir(parents=True,exist_ok=True);"
                "p.write_text('{\"overall\":\"PASS\"}\\n')"
            )
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "part1",
                            "command": [
                                "python3",
                                "-c",
                                parent_script,
                                output,
                                str(canonical),
                                child_script,
                            ],
                            "depends_on": [],
                            "allowed_write_roots": [allowed],
                            "expected_outputs": [output],
                            "completion_path": (
                                "output/job-001/work/completions/part1.json"
                            ),
                        }
                    ],
                },
            )

            report = stage_execution.execute_plan(root, plan)
            time.sleep(0.5)

            self.assertEqual(report["overall"], "PASS")
            self.assertEqual(
                canonical.read_text(encoding="utf-8"),
                "safe\n",
            )

    def test_detached_child_fd_cannot_mutate_promoted_output_inode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            allowed = "output/job-001/work/part1"
            output = f"{allowed}/declared.txt"
            child_script = (
                "import os,sys,time;"
                "time.sleep(0.25);"
                "os.write(int(sys.argv[1]),b'hacked\\n')"
            )
            parent_script = (
                "import os,pathlib,subprocess,sys;"
                "p=pathlib.Path(sys.argv[1]);"
                "p.parent.mkdir(parents=True,exist_ok=True);"
                "p.parent.chmod(0o750);"
                "fd=os.open(p,os.O_CREAT|os.O_TRUNC|os.O_RDWR,0o640);"
                "os.write(fd,b'safe\\n');"
                "subprocess.Popen("
                "[sys.executable,'-c',sys.argv[2],str(fd)],"
                "pass_fds=(fd,),"
                "stdin=subprocess.DEVNULL,"
                "stdout=subprocess.DEVNULL,"
                "stderr=subprocess.DEVNULL,"
                "start_new_session=True);"
                "os.close(fd)"
            )
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "part1",
                            "command": [
                                "python3",
                                "-c",
                                parent_script,
                                output,
                                child_script,
                            ],
                            "depends_on": [],
                            "allowed_write_roots": [allowed],
                            "expected_outputs": [output],
                            "completion_path": (
                                "output/job-001/work/completions/part1.json"
                            ),
                        }
                    ],
                },
            )

            report = stage_execution.execute_plan(root, plan)
            canonical = root / output
            promoted_hash = stage_execution.sha256_file(canonical)
            time.sleep(0.5)

            self.assertEqual(report["overall"], "PASS")
            self.assertEqual(canonical.read_text(encoding="utf-8"), "safe\n")
            self.assertEqual(
                stage_execution.sha256_file(canonical),
                promoted_hash,
            )
            self.assertEqual(stat.S_IMODE(canonical.stat().st_mode), 0o640)
            self.assertEqual(
                stat.S_IMODE(canonical.parent.stat().st_mode),
                0o750,
            )

    def test_promotion_copy_failure_rolls_back_all_canonical_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical_roots = [
                root / "output/job-001/work/part-a",
                root / "output/job-001/work/part-b",
            ]
            for index, canonical_root in enumerate(canonical_roots):
                canonical_root.mkdir(parents=True)
                (canonical_root / "result.txt").write_text(
                    f"old-{index}\n",
                    encoding="utf-8",
                )
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "part1",
                            "executor_kind": "agent",
                            "task": "Write both declared roots.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work/part-a",
                                "output/job-001/work/part-b",
                            ],
                            "completion_path": (
                                "output/job-001/work/completions/part1.json"
                            ),
                        }
                    ],
                },
            )

            def dispatcher(packet):
                outputs = []
                for index, raw_root in enumerate(
                    packet["allowed_write_roots"]
                ):
                    output = Path(raw_root) / "result.txt"
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_text(
                        f"new-{index}\n",
                        encoding="utf-8",
                    )
                    outputs.append(output)
                return {"status": "PASS", "outputs": outputs}

            original_copy = getattr(
                stage_execution,
                "_copy_path_for_promotion",
                None,
            )
            copy_calls = []

            def fail_second_copy(source, destination):
                copy_calls.append((Path(source), Path(destination)))
                if len(copy_calls) == 2:
                    raise OSError("injected promotion copy failure")
                if original_copy is not None:
                    return original_copy(source, destination)
                return stage_execution._copy_path_for_staging(
                    source,
                    destination,
                )

            stage_execution._copy_path_for_promotion = fail_second_copy
            try:
                report = stage_execution.execute_plan(
                    root,
                    plan,
                    dispatcher=dispatcher,
                )
            finally:
                if original_copy is None:
                    del stage_execution._copy_path_for_promotion
                else:
                    stage_execution._copy_path_for_promotion = original_copy

            self.assertEqual(report["overall"], "FAIL")
            self.assertIn(
                "injected promotion copy failure",
                report["completions"][0]["error"],
            )
            for index, canonical_root in enumerate(canonical_roots):
                self.assertEqual(
                    (canonical_root / "result.txt").read_text(
                        encoding="utf-8"
                    ),
                    f"old-{index}\n",
                )

    def test_sandboxed_command_keeps_network_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            port = server.getsockname()[1]

            def serve_once():
                connection, unused_address = server.accept()
                with connection:
                    connection.recv(4096)
                    connection.sendall(
                        b"HTTP/1.1 200 OK\r\n"
                        b"Content-Length: 7\r\n"
                        b"Connection: close\r\n\r\n"
                        b"network"
                    )

            server_thread = threading.Thread(target=serve_once)
            server_thread.start()
            allowed = "output/job-001/work/part1"
            output = f"{allowed}/network.txt"
            script = (
                "import pathlib,sys,urllib.request;"
                "data=urllib.request.urlopen(sys.argv[1],timeout=2).read();"
                "p=pathlib.Path(sys.argv[2]);"
                "p.parent.mkdir(parents=True,exist_ok=True);"
                "p.write_bytes(data)"
            )
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "part1",
                            "command": [
                                "python3",
                                "-c",
                                script,
                                f"http://127.0.0.1:{port}/",
                                output,
                            ],
                            "depends_on": [],
                            "allowed_write_roots": [allowed],
                            "expected_outputs": [output],
                            "completion_path": (
                                "output/job-001/work/completions/part1.json"
                            ),
                        }
                    ],
                },
            )
            try:
                report = stage_execution.execute_plan(root, plan)
            finally:
                server.close()
                server_thread.join(timeout=2)

            self.assertEqual(report["overall"], "PASS")
            self.assertEqual((root / output).read_bytes(), b"network")

    def test_sandboxed_command_packets_still_run_concurrently(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packets = []
            script = (
                "import pathlib,sys,time;"
                "started=time.time();"
                "time.sleep(0.25);"
                "p=pathlib.Path(sys.argv[1]);"
                "p.parent.mkdir(parents=True,exist_ok=True);"
                "p.write_text(str(started))"
            )
            for packet_id in ("part-a", "part-b"):
                allowed = f"output/job-001/work/{packet_id}"
                output = f"{allowed}/started.txt"
                packets.append(
                    {
                        "packet_id": packet_id,
                        "command": ["python3", "-c", script, output],
                        "depends_on": [],
                        "allowed_write_roots": [allowed],
                        "expected_outputs": [output],
                        "completion_path": (
                            "output/job-001/work/completions/"
                            f"{packet_id}.json"
                        ),
                    }
                )
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": packets,
                },
            )

            report = stage_execution.execute_plan(
                root,
                plan,
                max_workers=2,
            )

            starts = [
                float(
                    (
                        root
                        / f"output/job-001/work/{packet_id}/started.txt"
                    ).read_text(encoding="utf-8")
                )
                for packet_id in ("part-a", "part-b")
            ]
            self.assertEqual(report["overall"], "PASS")
            self.assertLess(abs(starts[0] - starts[1]), 0.2)

    def test_fail_packet_is_not_promoted_but_same_wave_pass_packet_is(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            failed_root = root / "output/job-001/work/failed"
            failed_root.mkdir(parents=True)
            (failed_root / "old.txt").write_text("old\n", encoding="utf-8")
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": packet_id,
                            "executor_kind": "agent",
                            "task": f"Write only {packet_id}.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                f"output/job-001/work/{packet_id}",
                            ],
                            "completion_path": (
                                "output/job-001/work/completions/"
                                f"{packet_id}.json"
                            ),
                        }
                        for packet_id in ("failed", "passed")
                    ],
                },
            )

            def dispatcher(packet):
                output = (
                    Path(packet["allowed_write_roots"][0])
                    / "new.txt"
                )
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(packet["packet_id"], encoding="utf-8")
                return {
                    "status": (
                        "FAIL"
                        if packet["packet_id"] == "failed"
                        else "PASS"
                    ),
                    "outputs": [output],
                }

            report = stage_execution.execute_plan(
                root,
                plan,
                dispatcher=dispatcher,
                max_workers=2,
            )

            self.assertEqual(report["overall"], "FAIL")
            self.assertEqual(
                (failed_root / "old.txt").read_text(encoding="utf-8"),
                "old\n",
            )
            self.assertFalse((failed_root / "new.txt").exists())
            self.assertEqual(
                (
                    root / "output/job-001/work/passed/new.txt"
                ).read_text(encoding="utf-8"),
                "passed",
            )

    def test_existing_symlink_inside_write_root_is_rejected_before_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            victim = root / "victim.txt"
            victim.write_text("safe\n", encoding="utf-8")
            allowed = root / "output/job-001/work/part1"
            allowed.mkdir(parents=True)
            (allowed / "nested-link").symlink_to(victim)
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "part1",
                            "executor_kind": "agent",
                            "task": "Write only the declared output.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work/part1",
                            ],
                            "completion_path": (
                                "output/job-001/work/completions/part1.json"
                            ),
                        }
                    ],
                },
            )
            called = False

            def dispatcher(packet):
                nonlocal called
                called = True
                return {"status": "PASS", "outputs": []}

            with self.assertRaisesRegex(
                stage_execution.PlanError,
                "symlink",
            ):
                stage_execution.execute_plan(
                    root,
                    plan,
                    dispatcher=dispatcher,
                )
            self.assertFalse(called)
            self.assertEqual(victim.read_text(encoding="utf-8"), "safe\n")

    def test_runtime_symlink_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            victim = root / "victim.txt"
            victim.write_text("safe\n", encoding="utf-8")
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "source_blueprint",
                    "packets": [
                        {
                            "packet_id": "part1",
                            "executor_kind": "agent",
                            "task": "Write only the declared output.",
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/work/part1",
                            ],
                            "completion_path": (
                                "output/job-001/work/completions/part1.json"
                            ),
                        }
                    ],
                },
            )

            def dispatcher(packet):
                output = Path(packet["allowed_write_roots"][0]) / "link"
                output.parent.mkdir(parents=True, exist_ok=True)
                output.symlink_to(victim)
                return {"status": "PASS", "outputs": [output]}

            report = stage_execution.execute_plan(
                root,
                plan,
                dispatcher=dispatcher,
            )

            self.assertEqual(report["overall"], "FAIL")
            self.assertIn("symlink", report["completions"][0]["error"])
            self.assertFalse(
                (root / "output/job-001/work/part1/link").exists()
            )

    def test_sealed_plan_rejects_packet_mutation_before_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "generation",
                    "packets": [
                        {
                            "packet_id": "part1",
                            "command": ["python3", "submit.py", "--part", "1"],
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/generation/part1",
                            ],
                            "completion_path": (
                                "output/job-001/generation/part1/completion.json"
                            ),
                        }
                    ],
                },
            )
            plan["packets"][0]["command"][-1] = "2"

            with self.assertRaisesRegex(
                stage_execution.PlanError,
                "plan hash mismatch",
            ):
                stage_execution.execute_plan(root, plan)

    def test_sandboxed_command_gets_a_writable_packet_local_temp_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output/job-001/generation/part1/result.txt"
            command = [
                "python3",
                "-c",
                (
                    "import pathlib,sys,tempfile;"
                    "out=pathlib.Path(sys.argv[1]);"
                    "out.parent.mkdir(parents=True,exist_ok=True);"
                    "temp=tempfile.TemporaryDirectory();"
                    "pathlib.Path(temp.name,'probe.txt').write_text('ok');"
                    "temp.cleanup();"
                    "out.write_text('PASS\\n')"
                ),
                str(output),
            ]
            plan = stage_execution.seal_plan(
                root,
                {
                    "schema_version": 1,
                    "job_id": "job-001",
                    "stage": "generation",
                    "packets": [
                        {
                            "packet_id": "part1",
                            "command": command,
                            "depends_on": [],
                            "allowed_write_roots": [
                                "output/job-001/generation/part1",
                            ],
                            "completion_path": (
                                "output/job-001/generation/part1/completion.json"
                            ),
                            "expected_outputs": [str(output)],
                        }
                    ],
                },
            )

            report = stage_execution.execute_plan(root, plan)

            self.assertEqual(report["overall"], "PASS")
            self.assertEqual(output.read_text(encoding="utf-8"), "PASS\n")


if __name__ == "__main__":
    unittest.main()
