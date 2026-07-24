import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock


from tools import prepare_source_blueprint


def write_fake_video_understanding(story_dir, include_hook=True):
    config = prepare_source_blueprint.blueprint_parameters(30)["video_understanding"]
    understanding_dir = story_dir / "video_understanding"
    understanding_dir.mkdir(parents=True)
    analysis = {
        "status": "PASS",
        "provider": config["provider"],
        "model": config["model"],
        "analysis": {"summary": "source story", "timeline": []},
    }
    (understanding_dir / "analysis.json").write_text(
        json.dumps(analysis), encoding="utf-8"
    )
    (understanding_dir / "analysis.md").write_text("analysis\n", encoding="utf-8")
    (understanding_dir / "request_manifest.json").write_text("{}\n", encoding="utf-8")
    (understanding_dir / "raw_response.json").write_text("{}\n", encoding="utf-8")
    if include_hook:
        hook_config = prepare_source_blueprint.blueprint_parameters(30)[
            "rapid_hook_review"
        ]
        hook_dir = understanding_dir / "hook_review"
        hook_dir.mkdir()
        hook = {
            "status": "PASS",
            "provider": config["provider"],
            "model": config["model"],
            "analysis_mode": hook_config["mode"],
            "sampling_fps": hook_config["fps"],
            "source_segment": {
                "start_seconds": hook_config["start_seconds"],
                "end_seconds": hook_config["duration_seconds"],
                "timebase": "source_absolute",
            },
            "analysis": {
                "summary": "rapid hook",
                "timeline": [
                    {
                        "start_seconds": 0.0,
                        "end_seconds": 0.6,
                        "visual_action_type": "gesture",
                    }
                ],
            },
        }
        (hook_dir / "analysis.json").write_text(
            json.dumps(hook), encoding="utf-8"
        )
        (hook_dir / "analysis.md").write_text("hook analysis\n", encoding="utf-8")
        (hook_dir / "request_manifest.json").write_text("{}\n", encoding="utf-8")
        (hook_dir / "raw_response.json").write_text("{}\n", encoding="utf-8")
        (hook_dir / "aligned_timeline.json").write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "timing_source": "measured_scene_cuts",
                    "timeline": [
                        {
                            "start_seconds": 0.0,
                            "end_seconds": 0.6,
                            "visual_action_type": "gesture",
                        }
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )


class PrepareSourceBlueprintTest(unittest.TestCase):
    def test_duration_parsing(self):
        cases = {
            "30s": 30,
            "1m30s": 90,
            "00:45": 45,
            "1:02:03": 3723,
            "1分15秒": 75,
            15: 15,
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(
                    prepare_source_blueprint.parse_duration_seconds(value),
                    expected,
                )

        for value in ["", "0s", "1:75", "not-a-duration"]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    prepare_source_blueprint.parse_duration_seconds(value)

    def test_cache_key_is_stable_for_equivalent_parameters(self):
        source_sha256 = "a" * 64
        first = {
            "groups": 2,
            "total_frames": 24,
            "nested": {"cols": 4, "run_asr": True},
        }
        second = {
            "nested": {"run_asr": True, "cols": 4},
            "total_frames": 24,
            "groups": 2,
        }

        self.assertEqual(
            prepare_source_blueprint.build_cache_key(source_sha256, first),
            prepare_source_blueprint.build_cache_key(source_sha256, second),
        )
        changed = dict(first, total_frames=36)
        self.assertNotEqual(
            prepare_source_blueprint.build_cache_key(source_sha256, first),
            prepare_source_blueprint.build_cache_key(source_sha256, changed),
        )

    def test_commands_use_duration_derived_groups_and_frames(self):
        parameters = prepare_source_blueprint.blueprint_parameters(31)
        commands = prepare_source_blueprint.build_commands(
            Path("/tmp/source.mp4"),
            Path("/tmp/source-blueprint"),
            parameters,
        )

        self.assertEqual(parameters["groups"], 3)
        self.assertEqual(parameters["total_frames"], 36)
        self.assertIn("--run-asr", commands["prepare_story_analysis"])
        storyboard_command = commands["build_part_storyboards"]
        self.assertEqual(storyboard_command[storyboard_command.index("--groups") + 1], "3")
        self.assertEqual(storyboard_command[storyboard_command.index("--total-frames") + 1], "36")

    def test_blueprint_command_requests_the_standard_rapid_hook_review(self):
        parameters = prepare_source_blueprint.blueprint_parameters(30)
        commands = prepare_source_blueprint.build_commands(
            Path("/tmp/source.mp4"),
            Path("/tmp/source-blueprint"),
            parameters,
        )

        self.assertEqual(
            parameters["rapid_hook_review"],
            {"mode": "rapid_hook", "start_seconds": 0.0, "duration_seconds": 3.0, "fps": 5.0},
        )
        story_command = commands["prepare_story_analysis"]
        self.assertEqual(
            story_command[story_command.index("--rapid-hook-seconds") + 1],
            "3.0",
        )
        self.assertEqual(
            story_command[story_command.index("--rapid-hook-fps") + 1],
            "5.0",
        )

    def test_blueprint_validation_rejects_a_missing_rapid_hook_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            story_dir = root / "story_analysis"
            story_dir.mkdir(parents=True)
            write_fake_video_understanding(story_dir, include_hook=False)

            errors = prepare_source_blueprint.validate_generated_artifacts(
                root,
                prepare_source_blueprint.blueprint_parameters(30),
            )

        self.assertTrue(
            any("video_understanding/hook_review/analysis.json" in error for error in errors),
            errors,
        )

    def test_blueprint_validation_rejects_a_non_rapid_hook_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            story_dir = root / "story_analysis"
            story_dir.mkdir(parents=True)
            write_fake_video_understanding(story_dir, include_hook=False)
            config = prepare_source_blueprint.blueprint_parameters(30)[
                "video_understanding"
            ]
            hook_dir = story_dir / "video_understanding" / "hook_review"
            hook_dir.mkdir(parents=True)
            (hook_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "status": "PASS",
                        "provider": config["provider"],
                        "model": config["model"],
                        "analysis_mode": "full",
                        "sampling_fps": 2,
                        "source_segment": None,
                        "analysis": {"summary": "wrong review", "timeline": []},
                    }
                ),
                encoding="utf-8",
            )
            for name in ["analysis.md", "request_manifest.json", "raw_response.json"]:
                (hook_dir / name).write_text("{}\n", encoding="utf-8")

            errors = prepare_source_blueprint.validate_generated_artifacts(
                root,
                prepare_source_blueprint.blueprint_parameters(30),
            )

        self.assertIn("rapid hook analysis mode does not match project config", errors)
        self.assertIn("rapid hook sampling fps does not match project config", errors)
        self.assertIn("rapid hook source segment does not match project config", errors)

    def test_blueprint_validation_rejects_an_empty_aligned_hook_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            story_dir = root / "story_analysis"
            story_dir.mkdir(parents=True)
            write_fake_video_understanding(story_dir)
            aligned_path = (
                story_dir
                / "video_understanding"
                / "hook_review"
                / "aligned_timeline.json"
            )
            aligned_path.write_text(
                json.dumps(
                    {
                        "status": "PASS",
                        "timing_source": "measured_scene_cuts",
                        "timeline": [],
                    }
                ),
                encoding="utf-8",
            )

            errors = prepare_source_blueprint.validate_generated_artifacts(
                root,
                prepare_source_blueprint.blueprint_parameters(30),
            )

        self.assertIn("rapid hook aligned timeline is empty", errors)

    def test_rapid_hook_actions_are_aligned_to_measured_scene_cuts(self):
        hook = {
            "source_segment": {
                "start_seconds": 0.0,
                "end_seconds": 3.0,
                "timebase": "source_absolute",
            },
            "analysis": {
                "timeline": [
                    {"start_seconds": 0.0, "end_seconds": 0.5, "visual_action_type": "gesture"},
                    {
                        "start_seconds": 0.5,
                        "end_seconds": 1.0,
                        "visual_action_type": "physical_change",
                    },
                    {"start_seconds": 1.0, "end_seconds": 1.5, "visual_action_type": "gesture"},
                    {
                        "start_seconds": 1.5,
                        "end_seconds": 2.0,
                        "visual_action_type": "physical_change",
                    },
                    {
                        "start_seconds": 2.0,
                        "end_seconds": 3.0,
                        "visual_action_type": "physical_change",
                    },
                ]
            },
        }
        rhythm = {
            "actual_cut_points": [
                {"time": 0.6, "score": 0.425409},
                {"time": 1.133, "score": 0.47006},
                {"time": 1.7, "score": 0.415065},
                {"time": 1.733, "score": 0.181979},
                {"time": 2.167, "score": 0.303268},
            ],
            "evidence_frames": [
                {"time": 0.4, "path": "frame_0003.jpg"},
                {"time": 0.8, "path": "frame_0005.jpg"},
                {"time": 1.0, "path": "frame_0006.jpg"},
                {"time": 1.6, "path": "frame_0009.jpg"},
                {"time": 1.8, "path": "frame_0010.jpg"},
                {"time": 2.0, "path": "frame_0011.jpg"},
            ],
        }

        aligned = prepare_source_blueprint.align_rapid_hook_timeline(hook, rhythm)

        self.assertEqual(
            [
                (item["start_seconds"], item["end_seconds"], item["visual_action_type"])
                for item in aligned["timeline"]
            ],
            [
                (0.0, 0.6, "gesture"),
                (0.6, 1.133, "physical_change"),
                (1.133, 1.7, "gesture"),
                (1.7, 2.167, "physical_change"),
                (2.167, 3.0, "physical_change"),
            ],
        )
        self.assertEqual(aligned["timing_source"], "measured_scene_cuts")
        self.assertEqual(
            aligned["timeline"][1]["evidence_frame_candidates"],
            {
                "before": {"time": 0.4, "path": "frame_0003.jpg"},
                "contact_motion": [{"time": 0.8, "path": "frame_0005.jpg"}],
                "visible_after": {"time": 1.0, "path": "frame_0006.jpg"},
            },
        )
        self.assertEqual(
            aligned["timeline"][3]["evidence_frame_candidates"],
            {
                "before": {"time": 1.6, "path": "frame_0009.jpg"},
                "contact_motion": [{"time": 1.8, "path": "frame_0010.jpg"}],
                "visible_after": {"time": 2.0, "path": "frame_0011.jpg"},
            },
        )

    def test_commands_prepare_measured_source_rhythm_as_a_source_fact(self):
        parameters = prepare_source_blueprint.blueprint_parameters(30)
        commands = prepare_source_blueprint.build_commands(
            Path("/tmp/source.mp4"),
            Path("/tmp/source-blueprint"),
            parameters,
        )

        self.assertIn("prepare_source_rhythm", commands)
        rhythm_command = commands["prepare_source_rhythm"]
        self.assertIn("prepare_source_rhythm.py", " ".join(rhythm_command))
        self.assertEqual(
            rhythm_command[rhythm_command.index("--output") + 1],
            (
                "/tmp/source-blueprint/prepare_source_rhythm/"
                "source_rhythm/source_rhythm.json"
            ),
        )

    def test_packet_staging_paths_are_rewritten_before_promotion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staged = root / ".stage-execution-source" / "story_analysis"
            canonical = root / "sealed_execution/output/job-001/story_analysis"
            staged.mkdir(parents=True)
            reference = staged / "source_rhythm.json"
            reference.write_text(
                json.dumps(
                    {
                        "evidence_frames": [
                            {"path": str(staged / "frame_0001.jpg")}
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            prepare_source_blueprint.rewrite_packet_staging_references(
                {
                    "_stage_path_map": [
                        {
                            "staged": str(staged),
                            "canonical": str(canonical),
                        }
                    ]
                }
            )

            rewritten = json.loads(reference.read_text(encoding="utf-8"))
            self.assertEqual(
                rewritten["evidence_frames"][0]["path"],
                str(canonical / "frame_0001.jpg"),
            )

    def test_source_tasks_run_concurrently_through_one_sealed_stage_plan(self):
        barrier = threading.Barrier(3)

        def run_at_barrier(command):
            barrier.wait(timeout=1)
            return {"status": "PASS", "command": command}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            job_id = "job-001"
            task_root = root / "output" / job_id / "source_blueprint_tasks"
            task_roots = prepare_source_blueprint.build_task_roots(task_root)
            commands = {
                "prepare_story_analysis": ["story"],
                "build_part_storyboards": ["storyboard"],
                "prepare_source_rhythm": ["rhythm"],
            }
            plans = []
            execute_plan = prepare_source_blueprint.stage_execution.execute_plan

            def capture_plan(*args, **kwargs):
                plans.append(args[1])
                return execute_plan(*args, **kwargs)

            with mock.patch.object(
                prepare_source_blueprint,
                "run_command",
                side_effect=run_at_barrier,
            ), mock.patch.object(
                prepare_source_blueprint.stage_execution,
                "execute_plan",
                side_effect=capture_plan,
            ):
                results = prepare_source_blueprint.run_parallel_tasks(
                    commands,
                    execution_root=root,
                    job_id=job_id,
                    task_roots=task_roots,
                    max_workers=3,
                )

        self.assertEqual(set(results), set(commands))
        self.assertTrue(all(result["status"] == "PASS" for result in results.values()))
        self.assertEqual(len(plans), 1)
        self.assertIn("plan_sha256", plans[0])
        self.assertEqual(plans[0]["stage"], "source_blueprint")
        write_roots = [
            packet["allowed_write_roots"][0]
            for packet in plans[0]["packets"]
        ]
        self.assertEqual(len(write_roots), len(set(write_roots)))

    def test_source_task_cannot_write_workspace_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            job_id = "job-001"
            state_path = root / "STATE.md"
            state_path.write_text("coordinator owns this\n", encoding="utf-8")
            task_root = root / "output" / job_id / "source_blueprint_tasks"
            task_roots = prepare_source_blueprint.build_task_roots(task_root)
            commands = {}
            for name in prepare_source_blueprint.TASK_NAMES:
                output = task_roots[name] / f"{name}.txt"
                if name == "prepare_story_analysis":
                    script = (
                        "from pathlib import Path; import sys; "
                        "Path(sys.argv[1]).write_text('poisoned\\n'); "
                        "Path(sys.argv[2]).parent.mkdir(parents=True, exist_ok=True); "
                        "Path(sys.argv[2]).write_text('done\\n')"
                    )
                    commands[name] = [
                        sys.executable,
                        "-c",
                        script,
                        str(state_path),
                        str(output),
                    ]
                else:
                    script = (
                        "from pathlib import Path; import sys; "
                        "Path(sys.argv[1]).parent.mkdir(parents=True, exist_ok=True); "
                        "Path(sys.argv[1]).write_text('done\\n')"
                    )
                    commands[name] = [
                        sys.executable,
                        "-c",
                        script,
                        str(output),
                    ]

            results = prepare_source_blueprint.run_parallel_tasks(
                commands,
                execution_root=root,
                job_id=job_id,
                task_roots=task_roots,
                max_workers=3,
            )

            self.assertEqual(
                state_path.read_text(encoding="utf-8"),
                "coordinator owns this\n",
            )
            self.assertEqual(
                results["prepare_story_analysis"]["status"],
                "FAIL",
            )
            self.assertEqual(
                results["build_part_storyboards"]["status"],
                "PASS",
            )
            self.assertEqual(
                results["prepare_source_rhythm"]["status"],
                "PASS",
            )

    def test_cache_miss_locks_raw_asr_text_into_source_rhythm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            video = root / "source.mp4"
            video.write_bytes(b"source bytes")
            output_dir = root / "output" / "job-001"
            cache_dir = root / "cache"

            def fake_parallel(commands, **_kwargs):
                story_command = commands["prepare_story_analysis"]
                story_dir = Path(story_command[story_command.index("--out-dir") + 1])
                story_dir.mkdir(parents=True)
                (story_dir / "asr").mkdir()
                (story_dir / "video_probe.json").write_text("{}\n", encoding="utf-8")
                (story_dir / "contact_sheet.jpg").write_bytes(b"contact")
                (story_dir / "story_analysis_materials.md").write_text("materials\n", encoding="utf-8")
                write_fake_video_understanding(story_dir)
                (story_dir / "asr" / "transcript.md").write_text(
                    "# ASR\n\n## Full Text\n\n黑头闭口涂油皮粉丝涂。\n\n## Chunks\n",
                    encoding="utf-8",
                )

                rhythm_command = commands["prepare_source_rhythm"]
                rhythm_path = Path(rhythm_command[rhythm_command.index("--output") + 1])
                rhythm_path.parent.mkdir(parents=True)
                rhythm_path.write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "source_evidence": {"asr_text": "", "subtitle_observations": []},
                            "beats": [],
                        }
                    ),
                    encoding="utf-8",
                )

                storyboard_command = commands["build_part_storyboards"]
                storyboard_dir = Path(storyboard_command[storyboard_command.index("--output") + 1])
                storyboard_dir.mkdir(parents=True)
                parts = []
                for part in [1, 2]:
                    path = storyboard_dir / f"source_storyboard_part{part}.jpg"
                    path.write_bytes(f"part-{part}".encode())
                    parts.append({"part": part, "path": str(path)})
                (storyboard_dir / "source_storyboard_manifest.json").write_text(
                    json.dumps({"groups": 2, "total_frames": 24, "parts": parts}),
                    encoding="utf-8",
                )
                return {
                    name: {"status": "PASS", "duration_seconds": 0.01}
                    for name in commands
                }

            with mock.patch.object(
                prepare_source_blueprint,
                "run_parallel_tasks",
                side_effect=fake_parallel,
            ):
                report = prepare_source_blueprint.prepare_blueprint(
                    video=video,
                    output_dir=output_dir,
                    target_duration="30s",
                    cache_dir=cache_dir,
                )

            self.assertEqual(report["overall"], "PASS")
            self.assertTrue(
                (
                    output_dir
                    / "剧情分析"
                    / "video_understanding"
                    / "hook_review"
                    / "aligned_timeline.json"
                ).is_file()
            )
            rhythm = json.loads(
                (output_dir / "剧情分析" / "source_rhythm.json").read_text(encoding="utf-8")
            )
            self.assertEqual(rhythm["source_evidence"]["asr_text"], "黑头闭口涂油皮粉丝涂。")
            self.assertTrue(rhythm["source_evidence"]["asr_source"].endswith("transcript.md"))

    def test_cache_hit_restores_facts_without_touching_product_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            video = root / "current-source.mp4"
            video.write_bytes(b"same source bytes")
            output_dir = root / "output" / "job-002"
            cache_dir = root / ".cache" / "source-blueprint"
            product_analysis = output_dir / "剧情分析" / "剧情分析.md"
            product_analysis.parent.mkdir(parents=True)
            product_analysis.write_text("current product analysis\n", encoding="utf-8")

            source_sha256 = prepare_source_blueprint.sha256_file(video)
            authored_rhythm = output_dir / "剧情分析" / "source_rhythm.json"
            authored_rhythm.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "source_sha256": source_sha256,
                        "source_evidence": {
                            "asr_text": "source transcript",
                            "subtitle_observations": [
                                {"time": 0.5, "text": "人工校准字幕"}
                            ],
                        },
                        "beats": [{"id": "authored-beat"}],
                    }
                ),
                encoding="utf-8",
            )
            parameters = prepare_source_blueprint.blueprint_parameters(30)
            cache_key = prepare_source_blueprint.build_cache_key(source_sha256, parameters)
            cache_entry = cache_dir / cache_key
            story_dir = cache_entry / "story_analysis"
            storyboard_dir = cache_entry / "storyboard_source_refs"
            (story_dir / "asr").mkdir(parents=True)
            storyboard_dir.mkdir(parents=True)

            old_source = "/archive/source.mp4"
            (story_dir / "video_probe.json").write_text("{}\n", encoding="utf-8")
            (story_dir / "contact_sheet.jpg").write_bytes(b"contact")
            (story_dir / "source_rhythm.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "source_sha256": source_sha256,
                        "source_evidence": {
                            "asr_text": "source transcript",
                            "asr_source": str(story_dir / "asr" / "transcript.md"),
                            "subtitle_observations": [],
                        },
                        "beats": [],
                    }
                ),
                encoding="utf-8",
            )
            (story_dir / "story_analysis_materials.md").write_text(
                f"source={old_source}\nprobe={story_dir / 'video_probe.json'}\n",
                encoding="utf-8",
            )
            write_fake_video_understanding(story_dir)
            (story_dir / "asr" / "transcript.md").write_text("source transcript\n", encoding="utf-8")

            parts = []
            for part in [1, 2]:
                storyboard = storyboard_dir / f"source_storyboard_part{part}.jpg"
                storyboard.write_bytes(f"part-{part}".encode("utf-8"))
                parts.append({"part": part, "path": str(storyboard)})
            (storyboard_dir / "source_storyboard_manifest.json").write_text(
                json.dumps(
                    {
                        "video": old_source,
                        "groups": 2,
                        "total_frames": 24,
                        "parts": parts,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            (cache_entry / "cache_manifest.json").write_text(
                json.dumps(
                    {
                        "version": prepare_source_blueprint.CACHE_SCHEMA_VERSION,
                        "cache_key": cache_key,
                        "source_sha256": source_sha256,
                        "source_path": old_source,
                        "parameters": parameters,
                        "overall": "PASS",
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            with mock.patch.object(
                prepare_source_blueprint,
                "run_parallel_tasks",
                side_effect=AssertionError("cache hit must not run source tools"),
            ):
                report = prepare_source_blueprint.prepare_blueprint(
                    video=video,
                    output_dir=output_dir,
                    target_duration="30s",
                    cache_dir=cache_dir,
                )

            self.assertTrue(report["cache_hit"])
            self.assertEqual(report["overall"], "PASS")
            self.assertEqual(
                report["task_timings"]["prepare_story_analysis"]["status"],
                "CACHE_HIT",
            )
            self.assertEqual(product_analysis.read_text(encoding="utf-8"), "current product analysis\n")

            restored_rhythm = json.loads(
                (output_dir / "剧情分析" / "source_rhythm.json").read_text(encoding="utf-8")
            )
            self.assertEqual(restored_rhythm["beats"], [{"id": "authored-beat"}])
            self.assertEqual(
                restored_rhythm["source_evidence"]["subtitle_observations"],
                [{"time": 0.5, "text": "人工校准字幕"}],
            )

            restored_manifest_path = output_dir / "storyboard_source_refs" / "source_storyboard_manifest.json"
            restored_manifest = json.loads(restored_manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(restored_manifest["video"], str(video.resolve()))
            self.assertEqual(
                restored_manifest["parts"][0]["path"],
                str(output_dir / "storyboard_source_refs" / "source_storyboard_part1.jpg"),
            )
            self.assertIn("storyboard_source_refs/source_storyboard_part1.jpg", report["artifacts"])
            report_on_disk = json.loads(
                (output_dir / "checks" / "source_blueprint_report.json").read_text(encoding="utf-8")
            )
            self.assertTrue(report_on_disk["cache_hit"])


if __name__ == "__main__":
    unittest.main()
