import hashlib
import json
import subprocess
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


from tools import source_composition_fanout


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class SourceCompositionFanoutTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.job_id = "job-001"
        self.rhythm = (
            self.root / "output" / self.job_id / "剧情分析" / "source_rhythm.json"
        )
        self.rhythm.parent.mkdir(parents=True)
        self.rhythm.write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "source_sha256": "source-video-sha",
                    "beats": [{"id": "sr001"}],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        self.rhythm_sha = sha256(self.rhythm)
        self.qc = (
            self.root / "output" / self.job_id / "checks" / "source_rhythm_qc.json"
        )
        self.qc.parent.mkdir(parents=True)
        self.qc.write_text(
            json.dumps(
                {
                    "overall": "PASS",
                    "issues": [],
                    "source_rhythm": str(self.rhythm.resolve()),
                    "source_rhythm_sha256": self.rhythm_sha,
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def task(self):
        return {
            "task_id": "story-view",
            "family": "story_view",
            "command": [
                "python3",
                "render_story.py",
                "{output_root}",
            ],
            "depends_on": [],
            "resource_class": "cpu",
        }

    def build_plan(self, **overrides):
        kwargs = {
            "root": self.root,
            "job_id": self.job_id,
            "source_rhythm_path": self.rhythm,
            "source_rhythm_sha256": self.rhythm_sha,
            "source_rhythm_qc_path": self.qc,
            "cache_key": "composition-v1",
            "tasks": [self.task()],
        }
        kwargs.update(overrides)
        return source_composition_fanout.build_plan(**kwargs)

    def test_build_plan_requires_passing_qc_bound_to_the_current_rhythm_hash(self):
        plan = self.build_plan()

        self.assertEqual(plan["source_rhythm"]["sha256"], self.rhythm_sha)
        self.assertEqual(plan["source_rhythm_qc"]["overall"], "PASS")
        self.assertEqual(
            plan["source_rhythm_qc"]["source_rhythm_sha256"],
            self.rhythm_sha,
        )
        self.assertEqual(
            plan["source_rhythm_qc"]["report_sha256"],
            sha256(self.qc),
        )
        self.assertEqual(plan["policy"], "locked_source_rhythm_post_qc_fanout")
        self.assertEqual(plan["stage"], "source_blueprint")
        self.assertEqual(
            plan["stage_execution"]["packets"][0]["packet_id"],
            "story-view",
        )
        self.assertTrue(plan["stage_execution"]["plan_sha256"])
        self.assertIn(
            plan["bundle_path"],
            plan["stage_execution"]["coordinator_only_paths"],
        )
        self.assertEqual(
            plan["tasks"][0]["output_root"],
            (
                f"output/{self.job_id}/source-composition/composition-v1/"
                "tasks/story-view"
            ),
        )

        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.build_plan(source_rhythm_sha256="0" * 64)

        self.qc.write_text(
            json.dumps(
                {
                    "overall": "FAIL",
                    "source_rhythm": str(self.rhythm.resolve()),
                    "source_rhythm_sha256": self.rhythm_sha,
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "must PASS"):
            self.build_plan()

    def test_build_plan_rejects_old_passing_qc_after_same_path_rhythm_changes(self):
        original_qc_mtime = self.qc.stat().st_mtime_ns
        self.rhythm.write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "source_sha256": "source-video-sha",
                    "beats": [{"id": "sr001"}, {"id": "sr002"}],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        self.rhythm.touch()
        self.assertGreater(self.rhythm.stat().st_mtime_ns, original_qc_mtime)

        with self.assertRaisesRegex(ValueError, "source hash mismatch"):
            self.build_plan(source_rhythm_sha256=sha256(self.rhythm))

    def test_plan_allows_only_post_rhythm_families_and_an_acyclic_isolated_dag(self):
        tasks = [
            {
                "task_id": "story",
                "family": "story_view",
                "command": ["python3", "story.py"],
                "depends_on": [],
                "resource_class": "higress",
            },
            {
                "task_id": "timeline",
                "family": "timeline_view",
                "command": ["python3", "timeline.py"],
                "depends_on": ["story"],
                "resource_class": "cpu",
            },
            {
                "task_id": "shot",
                "family": "shot_view",
                "command": ["python3", "shot.py"],
                "depends_on": ["story"],
                "resource_class": "ffmpeg",
            },
            {
                "task_id": "audit",
                "family": "role_product_seam_audit",
                "command": ["python3", "audit.py"],
                "depends_on": ["timeline", "shot"],
                "resource_class": "qwen_mlx",
            },
            {
                "task_id": "part1",
                "family": "part_storyboard_rebuild",
                "command": ["python3", "part.py", "--part", "1"],
                "depends_on": ["shot"],
                "resource_class": "ffmpeg",
                "output_root": (
                    f"output/{self.job_id}/source-composition/composition-v1/"
                    "custom/part1"
                ),
            },
        ]

        plan = self.build_plan(tasks=tasks)

        self.assertEqual(
            [item["family"] for item in plan["tasks"]],
            [
                "story_view",
                "timeline_view",
                "shot_view",
                "role_product_seam_audit",
                "part_storyboard_rebuild",
            ],
        )
        self.assertEqual(
            plan["tasks"][-1]["output_root"],
            (
                f"output/{self.job_id}/source-composition/composition-v1/"
                "custom/part1"
            ),
        )
        self.assertEqual(plan["resource_limits"]["qwen_mlx"], 1)

        invalid = self.task()
        invalid["family"] = "source_rhythm_author"
        with self.assertRaisesRegex(ValueError, "post-rhythm task family"):
            self.build_plan(tasks=[invalid])

        cycle = [dict(tasks[0], depends_on=["timeline"]), tasks[1]]
        with self.assertRaisesRegex(ValueError, "cycle"):
            self.build_plan(tasks=cycle)

        overlapping = [
            dict(tasks[0], output_root=tasks[-1]["output_root"]),
            tasks[-1],
        ]
        with self.assertRaisesRegex(ValueError, "isolated"):
            self.build_plan(tasks=overlapping)

        agent_task = {
            "task_id": "story-agent",
            "family": "story_view",
            "executor_kind": "agent",
            "task": "Read only the locked rhythm and render the story view.",
            "depends_on": [],
            "resource_class": "cpu",
        }
        agent_plan = self.build_plan(tasks=[agent_task])
        packet = agent_plan["stage_execution"]["packets"][0]
        self.assertEqual(packet["executor_kind"], "agent")
        self.assertNotIn("command", packet)
        self.assertIn("locked rhythm", packet["task"])

        def fake_agent_dispatcher(task, plan):
            output_root = self.root / task["output_root"]
            output_root.mkdir(parents=True, exist_ok=True)
            output = output_root / "story.md"
            output.write_text("source-locked story\n", encoding="utf-8")
            return {"status": "PASS", "outputs": [output]}

        bundle = source_composition_fanout.run_plan(
            self.root,
            agent_plan,
            agent_dispatcher=fake_agent_dispatcher,
        )
        self.assertEqual(bundle["overall"], "PASS")
        self.assertEqual(bundle["tasks"][0]["outputs"][0]["path"], (
            f"output/{self.job_id}/source-composition/composition-v1/"
            "tasks/story-agent/story.md"
        ))

    def test_run_plan_respects_dag_pool_and_resource_limits_and_writes_stable_bundle(self):
        tasks = []
        for task_id, family, resource_class, dependencies in [
            ("qwen-a", "story_view", "qwen_mlx", []),
            ("qwen-b", "timeline_view", "qwen_mlx", []),
            ("higress-a", "role_product_seam_audit", "higress", []),
            ("higress-b", "role_product_seam_audit", "higress", []),
            ("ffmpeg-a", "part_storyboard_rebuild", "ffmpeg", []),
            ("ffmpeg-b", "part_storyboard_rebuild", "ffmpeg", []),
            ("final", "shot_view", "cpu", ["qwen-a", "higress-a"]),
        ]:
            tasks.append(
                {
                    "task_id": task_id,
                    "family": family,
                    "command": ["worker", task_id, "{output_root}"],
                    "depends_on": dependencies,
                    "resource_class": resource_class,
                }
            )
        plan = self.build_plan(
            tasks=tasks,
            resource_limits={"higress": 2, "ffmpeg": 2, "qwen_mlx": 99},
        )
        active = {"qwen_mlx": 0, "higress": 0, "ffmpeg": 0, "cpu": 0}
        peak = dict(active)
        finished = set()
        start_dependencies = {}
        lock = threading.Lock()
        higress_barrier = threading.Barrier(2, timeout=2)
        task_by_id = {item["task_id"]: item for item in plan["tasks"]}

        def fake_runner(command, **_kwargs):
            task_id = command[1]
            resource_class = task_by_id[task_id]["resource_class"]
            with lock:
                start_dependencies[task_id] = set(finished)
                active[resource_class] += 1
                peak[resource_class] = max(
                    peak[resource_class],
                    active[resource_class],
                )
            if task_id.startswith("higress-"):
                higress_barrier.wait()
            time.sleep(0.02)
            output_root = Path(command[-1])
            output_root.mkdir(parents=True, exist_ok=True)
            (output_root / "result.json").write_text(
                json.dumps({"task_id": task_id}) + "\n",
                encoding="utf-8",
            )
            with lock:
                active[resource_class] -= 1
                finished.add(task_id)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        bundle = source_composition_fanout.run_plan(
            self.root,
            plan,
            max_workers=99,
            runner=fake_runner,
        )

        self.assertEqual(bundle["overall"], "PASS")
        self.assertEqual(peak["qwen_mlx"], 1)
        self.assertEqual(peak["higress"], 2)
        self.assertLessEqual(peak["ffmpeg"], 2)
        self.assertIn("qwen-a", start_dependencies["final"])
        self.assertIn("higress-a", start_dependencies["final"])
        self.assertEqual(
            [item["task_id"] for item in bundle["tasks"]],
            sorted(task_by_id),
        )
        bundle_path = self.root / plan["bundle_path"]
        self.assertEqual(
            json.loads(bundle_path.read_text(encoding="utf-8")),
            bundle,
        )
        self.assertEqual(bundle["source_rhythm"], plan["source_rhythm"])
        for result in bundle["tasks"]:
            self.assertEqual(len(result["outputs"]), 1)
            self.assertEqual(len(result["outputs"][0]["sha256"]), 64)

    def test_run_plan_rewrites_packet_staging_paths_before_promotion(self):
        plan = self.build_plan()

        def fake_runner(command, **_kwargs):
            output_root = Path(command[-1])
            output_root.mkdir(parents=True, exist_ok=True)
            (output_root / "result.json").write_text(
                json.dumps({"path": str(output_root / "story.md")}) + "\n",
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        bundle = source_composition_fanout.run_plan(
            self.root,
            plan,
            runner=fake_runner,
        )

        canonical_root = (self.root / plan["tasks"][0]["output_root"]).resolve()
        promoted = json.loads((canonical_root / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(promoted["path"], str(canonical_root / "story.md"))
        self.assertNotIn(".stage-execution-", promoted["path"])
        self.assertEqual(bundle["overall"], "PASS")

    def test_same_source_and_cache_key_are_singleflight_and_shared_state_is_untouched(self):
        sentinels = {}
        for relative in [
            "jobs.csv",
            "STATE.md",
            "RUNNER_STATE.json",
            f"output/{self.job_id}/checks/gate.json",
        ]:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"sentinel:{relative}\n", encoding="utf-8")
            sentinels[path] = path.read_bytes()
        sentinels[self.rhythm] = self.rhythm.read_bytes()
        sentinels[self.qc] = self.qc.read_bytes()

        plan = self.build_plan()
        calls = 0
        calls_lock = threading.Lock()

        def fake_runner(command, **_kwargs):
            nonlocal calls
            with calls_lock:
                calls += 1
            time.sleep(0.05)
            output_root = Path(command[-1])
            output_root.mkdir(parents=True, exist_ok=True)
            (output_root / "story.md").write_text(
                "locked source story\n",
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    source_composition_fanout.run_plan,
                    self.root,
                    plan,
                    2,
                    fake_runner,
                )
                for _ in range(2)
            ]
            bundles = [future.result() for future in futures]

        self.assertEqual(calls, 1)
        self.assertEqual(bundles[0], bundles[1])
        self.assertEqual(bundles[0]["overall"], "PASS")
        for path, before in sentinels.items():
            self.assertEqual(path.read_bytes(), before, path)

        self.rhythm.write_text('{"schema_version":3,"beats":[]}\n', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            source_composition_fanout.run_plan(
                self.root,
                plan,
                runner=fake_runner,
            )

    def test_write_set_violation_overrides_source_domain_result(self):
        plan = self.build_plan()
        rogue = self.root / "output/job-999/canonical.json"

        def violating_runner(command, **_kwargs):
            output_root = Path(command[-1])
            output_root.mkdir(parents=True, exist_ok=True)
            (output_root / "story.md").write_text(
                "locked source story\n",
                encoding="utf-8",
            )
            rogue.parent.mkdir(parents=True, exist_ok=True)
            rogue.write_text('{"forbidden":true}\n', encoding="utf-8")
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="",
                stderr="",
            )

        bundle = source_composition_fanout.run_plan(
            self.root,
            plan,
            runner=violating_runner,
        )

        self.assertEqual(bundle["overall"], "FAIL")
        self.assertEqual(bundle["tasks"][0]["status"], "FAIL")
        self.assertEqual(bundle["tasks"][0]["outputs"], [])
        self.assertIn(
            "packet filesystem policy blocked os.mkdir",
            bundle["tasks"][0]["error"],
        )
        self.assertIn(
            "output/job-999",
            bundle["tasks"][0]["error"],
        )
        self.assertFalse(rogue.exists())

    def test_cli_builds_and_runs_a_command_only_plan(self):
        repository_root = Path(__file__).resolve().parents[1]
        spec = self.root / "source-composition-spec.json"
        plan_path = self.root / "source-composition-plan.json"
        cli_output = (
            self.root
            / "output"
            / self.job_id
            / "source-composition"
            / "cli-v1"
            / "tasks"
            / "story-view"
            / "story.md"
        )
        spec.write_text(
            json.dumps(
                {
                    "job_id": self.job_id,
                    "source_rhythm_path": str(self.rhythm),
                    "source_rhythm_sha256": self.rhythm_sha,
                    "source_rhythm_qc_path": str(self.qc),
                    "cache_key": "cli-v1",
                    "tasks": [
                        {
                            "task_id": "story-view",
                            "family": "story_view",
                            "command": [
                                "python3",
                                "-c",
                                (
                                    "from pathlib import Path; "
                                    "p=Path(__import__('sys').argv[1])/'story.md'; "
                                    "p.parent.mkdir(parents=True, exist_ok=True); "
                                    "p.write_text('locked story\\n', encoding='utf-8')"
                                ),
                                "{output_root}",
                            ],
                            "depends_on": [],
                            "resource_class": "cpu",
                        }
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )

        planned = subprocess.run(
            [
                "python3",
                str(repository_root / "tools" / "source_composition_fanout.py"),
                "plan",
                "--root",
                str(self.root),
                "--spec",
                str(spec),
                "--out",
                str(plan_path),
            ],
            cwd=repository_root,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(planned.returncode, 0, planned.stderr)
        self.assertTrue(plan_path.is_file())

        executed = subprocess.run(
            [
                "python3",
                str(repository_root / "tools" / "source_composition_fanout.py"),
                "run",
                "--root",
                str(self.root),
                "--plan",
                str(plan_path),
                "--max-workers",
                "2",
            ],
            cwd=repository_root,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(executed.returncode, 0, executed.stderr)
        bundle = json.loads(
            (
                self.root
                / "output"
                / self.job_id
                / "source-composition"
                / "cli-v1"
                / "source_composition_bundle.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(bundle["overall"], "PASS")
        self.assertEqual(bundle["canonical_merge"], "NOT_PERFORMED")
        self.assertEqual(bundle["checker_review"], "NOT_PERFORMED")
        self.assertEqual(cli_output.read_text(encoding="utf-8"), "locked story\n")


if __name__ == "__main__":
    unittest.main()
