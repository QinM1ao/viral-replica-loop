import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))


class PreSeedancePartCompilerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.job_dir = self.root / "output" / "job-001"
        self.job_dir.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_compiles_isolated_packets_concurrently_then_merges_in_part_order(self):
        from pre_seedance_part_compiler import compile_and_merge

        barrier = threading.Barrier(2)

        def compile_one(part_id, packet_dir):
            barrier.wait(timeout=5)
            time.sleep(0.02 if part_id == "part1" else 0)
            output = packet_dir / "seedance" / f"{part_id}.txt"
            output.parent.mkdir(parents=True)
            output.write_text(part_id, encoding="utf-8")
            return {"part_id": part_id}

        results = compile_and_merge(
            self.job_dir,
            ["part1", "part2"],
            compile_one,
            max_workers=2,
        )

        self.assertEqual([result.part_id for result in results], ["part1", "part2"])
        self.assertEqual(
            (self.job_dir / "seedance" / "part1.txt").read_text(encoding="utf-8"),
            "part1",
        )
        self.assertEqual(
            (self.job_dir / "seedance" / "part2.txt").read_text(encoding="utf-8"),
            "part2",
        )
        self.assertFalse((self.job_dir / ".pre_seedance_pack_staging").exists())

    def test_rejects_packet_output_collision_before_writing_final_outputs(self):
        from pre_seedance_part_compiler import compile_and_merge

        def compile_one(part_id, packet_dir):
            output = packet_dir / "seedance" / "shared.txt"
            output.parent.mkdir(parents=True)
            output.write_text(part_id, encoding="utf-8")
            return {}

        with self.assertRaisesRegex(ValueError, "collision"):
            compile_and_merge(
                self.job_dir,
                ["part1", "part2"],
                compile_one,
                max_workers=2,
            )

        self.assertFalse((self.job_dir / "seedance" / "shared.txt").exists())
        self.assertFalse((self.job_dir / ".pre_seedance_pack_staging").exists())

    def test_refuses_merge_when_frozen_director_plan_changes(self):
        from pre_seedance_part_compiler import compile_and_merge

        plan = self.job_dir / "seedance" / "director_plan.json"
        plan.parent.mkdir(parents=True)
        plan.write_text('{"version": 1}\n', encoding="utf-8")

        def compile_one(_part_id, packet_dir):
            output = packet_dir / "seedance" / "part1.txt"
            output.parent.mkdir(parents=True)
            output.write_text("ready", encoding="utf-8")
            plan.write_text('{"version": 2}\n', encoding="utf-8")
            return {}

        with self.assertRaisesRegex(RuntimeError, "changed during Part compilation"):
            compile_and_merge(
                self.job_dir,
                ["part1"],
                compile_one,
                frozen_inputs=[plan],
            )

        self.assertFalse((self.job_dir / "seedance" / "part1.txt").exists())
        self.assertFalse((self.job_dir / ".pre_seedance_pack_staging").exists())

    def test_blocks_out_of_bounds_state_write_before_write_and_does_not_merge(self):
        from pre_seedance_part_compiler import compile_and_merge

        state = self.root / "STATE.md"
        state.write_text("coordinator-owned\n", encoding="utf-8")

        def compile_one(_part_id, packet_dir):
            output = packet_dir / "seedance" / "part1.txt"
            output.parent.mkdir(parents=True)
            output.write_text("ready", encoding="utf-8")
            state.write_text("packet-owned\n", encoding="utf-8")
            return {}

        with self.assertRaisesRegex(
            RuntimeError,
            "packet filesystem policy blocked open",
        ):
            compile_and_merge(
                self.job_dir,
                ["part1"],
                compile_one,
            )

        self.assertEqual(
            state.read_text(encoding="utf-8"),
            "coordinator-owned\n",
        )
        self.assertFalse((self.job_dir / "seedance" / "part1.txt").exists())
        self.assertFalse((self.job_dir / ".pre_seedance_pack_staging").exists())

    def test_blocks_out_of_bounds_git_write_before_write_and_does_not_merge(self):
        from pre_seedance_part_compiler import compile_and_merge

        git_config = self.root / ".git" / "config"
        git_config.parent.mkdir()
        git_config.write_text("coordinator-owned\n", encoding="utf-8")

        def compile_one(_part_id, packet_dir):
            output = packet_dir / "seedance" / "part1.txt"
            output.parent.mkdir(parents=True)
            output.write_text("ready", encoding="utf-8")
            git_config.write_text("packet-owned\n", encoding="utf-8")
            return {}

        with self.assertRaisesRegex(
            RuntimeError,
            "packet filesystem policy blocked open",
        ):
            compile_and_merge(
                self.job_dir,
                ["part1"],
                compile_one,
            )

        self.assertEqual(
            git_config.read_text(encoding="utf-8"),
            "coordinator-owned\n",
        )
        self.assertFalse((self.job_dir / "seedance" / "part1.txt").exists())
        self.assertFalse((self.job_dir / ".pre_seedance_pack_staging").exists())

    def test_blocks_sibling_packet_write_before_write_and_does_not_merge(self):
        from pre_seedance_part_compiler import compile_and_merge

        packet_dirs = {}
        barrier = threading.Barrier(2)

        def compile_one(part_id, packet_dir):
            packet_dirs[part_id] = packet_dir
            output = packet_dir / "seedance" / f"{part_id}.txt"
            output.parent.mkdir(parents=True)
            output.write_text(part_id, encoding="utf-8")
            barrier.wait(timeout=5)
            if part_id == "part1":
                sibling = packet_dirs["part2"] / "seedance" / "poisoned.txt"
                sibling.write_text("poisoned", encoding="utf-8")
            return {}

        with self.assertRaisesRegex(
            RuntimeError,
            "packet filesystem policy blocked open",
        ):
            compile_and_merge(
                self.job_dir,
                ["part1", "part2"],
                compile_one,
                max_workers=2,
            )

        self.assertFalse((self.job_dir / "seedance" / "part1.txt").exists())
        self.assertFalse((self.job_dir / "seedance" / "part2.txt").exists())
        self.assertFalse((self.job_dir / ".pre_seedance_pack_staging").exists())

    def test_real_part_compiler_stages_prompt_audio_web_and_api_outputs(self):
        from pre_seedance_pack import compile_part_packet
        from pre_seedance_part_compiler import compile_and_merge

        source = self.root / "source.mp4"
        source.write_bytes(b"source")
        storyboard = self.root / "storyboard.png"
        storyboard.write_bytes(b"storyboard")
        plan = {
            "asset_roles": {},
            "audio_prompt_rule": "@音频1只参考音色和节奏。",
            "global_prompt_rules": "生成约{duration_seconds}秒视频。",
        }
        part = {
            "id": "part1",
            "duration_seconds": 15,
            "scene_rule": "",
            "audio": {
                "source": str(source),
                "source_start": 0,
                "source_end": 15,
            },
            "beats": [
                {
                    "id": "beat1",
                    "panel_start": 1,
                    "panel_end": 2,
                    "target_start": 0,
                    "target_end": 15,
                    "target_visual_action": "Apply product.",
                    "sound_effect": "",
                }
            ],
            "speech_groups": [],
            "execution_blocks": [],
        }
        route = {
            "model": "ep-test",
            "task_code": 2509,
            "endpoint": "task_create",
            "generate_audio": True,
            "ratio": "9:16",
            "resolution": "720p",
        }
        audio_destinations = []

        def fake_audio_runner(command, **_kwargs):
            output = Path(command[-1])
            audio_destinations.append(output)
            output.write_bytes(b"audio")

        results = compile_and_merge(
            self.job_dir,
            ["part1"],
            lambda _part_id, packet_dir: compile_part_packet(
                self.root,
                self.job_dir,
                plan,
                part,
                [("storyboard", storyboard)],
                route,
                "both",
                packet_dir,
                audio_runner=fake_audio_runner,
            ),
        )

        self.assertIn(".stage-execution-part1-", str(audio_destinations[0]))
        self.assertEqual(
            (self.job_dir / "audio-boundary" / "part1_reference_audio.mp3").read_bytes(),
            b"audio",
        )
        self.assertEqual(
            next(
                (self.job_dir / "seedance_web_final" / "Part1_上传素材").glob(
                    "06_*.mp3"
                )
            ).read_bytes(),
            b"audio",
        )
        request = json.loads(
            (
                self.job_dir
                / "seedance"
                / "requests"
                / "part1_request_prepared.json"
            ).read_text(encoding="utf-8")
        )
        content = json.loads(request["body"]["param"])["content"]
        self.assertTrue(any(item["type"] == "audio_url" for item in content))
        self.assertEqual(
            results[0].metadata["audio_path"],
            "audio-boundary/part1_reference_audio.mp3",
        )

    def test_manifest_qc_binds_director_inputs_and_promoted_part_files(self):
        from pre_seedance_part_compiler import validate_compilation_manifest

        director = self.job_dir / "seedance" / "director_plan.json"
        director.parent.mkdir(parents=True, exist_ok=True)
        director.write_text(
            json.dumps({"parts": [{"id": "part1"}]}) + "\n",
            encoding="utf-8",
        )
        prompt = self.job_dir / "seedance" / "seedance_part1_prompt.txt"
        prompt.write_text("locked prompt\n", encoding="utf-8")
        frozen = self.root / "rules.json"
        frozen.write_text('{"model":"locked"}\n', encoding="utf-8")

        import hashlib

        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        manifest = {
            "version": 1,
            "director_plan_sha256": digest(director),
            "frozen_inputs": [
                {"path": str(frozen), "sha256": digest(frozen)}
            ],
            "parts": [
                {
                    "part_id": "part1",
                    "metadata": {
                        "prompt_path": "seedance/seedance_part1_prompt.txt",
                        "audio_path": None,
                        "request_path": None,
                        "web_uploads": [],
                    },
                    "files": [
                        {
                            "path": "seedance/seedance_part1_prompt.txt",
                            "sha256": digest(prompt),
                        }
                    ],
                }
            ],
        }
        manifest_path = (
            self.job_dir / "seedance" / "part_compilation_manifest.json"
        )
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        self.assertEqual(
            validate_compilation_manifest(self.job_dir)["overall"],
            "PASS",
        )
        prompt.write_text("changed\n", encoding="utf-8")
        failed = validate_compilation_manifest(self.job_dir)
        self.assertEqual(failed["overall"], "FAIL")
        self.assertTrue(
            any("compiled file changed" in issue for issue in failed["issues"])
        )


if __name__ == "__main__":
    unittest.main()
