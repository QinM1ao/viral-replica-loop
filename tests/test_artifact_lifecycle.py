import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import artifact_lifecycle


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "artifact_lifecycle.py"


class ArtifactLifecycleTest(unittest.TestCase):
    def test_bounded_replacement_supports_canonical_job_work_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "jobs" / "job-001" / "work"
            prompt = job_dir / "seedance" / "seedance_part1_prompt.txt"
            prompt.parent.mkdir(parents=True)
            prompt.write_text("before\n", encoding="utf-8")

            @artifact_lifecycle.artifact_replacement_scope
            def replace_prompt():
                artifact_lifecycle.stage_bounded_replacement(
                    job_dir,
                    [prompt],
                    "prompt_only",
                )
                prompt.parent.mkdir(parents=True, exist_ok=True)
                prompt.write_text("after\n", encoding="utf-8")

            replace_prompt()

            self.assertEqual(prompt.read_text(encoding="utf-8"), "after\n")
            rollback = (
                job_dir.parents[2]
                / ".viral-replica"
                / "state"
                / "artifact-history"
                / "job-001"
                / "rollback"
                / "prompt_only"
                / "seedance"
                / "seedance_part1_prompt.txt"
            )
            self.assertEqual(rollback.read_text(encoding="utf-8"), "before\n")

    def test_legacy_migration_rejects_symlinked_history_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job_dir = root / "output" / "job-symlink"
            final = job_dir / "final"
            subtitle = job_dir / "subtitle_removal"
            trials = subtitle / "provider" / "normalization_tests"
            final.mkdir(parents=True)
            trials.mkdir(parents=True)
            source = final / "source.mp4"
            output = final / "output.mp4"
            source.write_bytes(b"source")
            output.write_bytes(b"output")
            (subtitle / "subtitle_removal_report.json").write_text(
                '{"overall":"PASS"}\n',
                encoding="utf-8",
            )
            outside = root / "outside"
            outside.mkdir()
            (job_dir.parent / ".history").symlink_to(outside, target_is_directory=True)

            result = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "migrate-subtitle-cleanup",
                    "--job-dir",
                    str(job_dir),
                    "--source-video",
                    str(source),
                    "--output-video",
                    str(output),
                    "--confirm-job-id",
                    job_dir.name,
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symlink", result.stderr)
            self.assertEqual(list(outside.rglob("*")), [])

    def test_explicit_legacy_subtitle_migration_unlocks_only_bound_trials(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "output" / "job-legacy"
            final = job_dir / "final"
            subtitle = job_dir / "subtitle_removal"
            trials = subtitle / "provider" / "normalization_tests"
            final.mkdir(parents=True)
            trials.mkdir(parents=True)
            source = final / "final_video.mp4"
            output = final / "final_video_no_subtitles.mp4"
            source.write_bytes(b"current source")
            output.write_bytes(b"current output")
            (trials / "trial.mp4").write_bytes(b"disposable trial")
            (subtitle / "subtitle_removal_report.json").write_text(
                json.dumps(
                    {
                        "overall": "PASS",
                        "source_video": str(source),
                        "source_sha256": "0" * 64,
                        "output_video": str(output),
                        "output_sha256": "1" * 64,
                    }
                ),
                encoding="utf-8",
            )

            migrated = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "migrate-subtitle-cleanup",
                    "--job-dir",
                    str(job_dir),
                    "--source-video",
                    str(source),
                    "--output-video",
                    str(output),
                    "--confirm-job-id",
                    "job-legacy",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(migrated.returncode, 0, migrated.stderr)
            migration = json.loads(migrated.stdout)
            self.assertEqual(migration["job_id"], "job-legacy")
            self.assertEqual(migration["scope"], "subtitle_normalization_trials")
            preview = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "preview",
                    "--job-dir",
                    str(job_dir),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(preview.returncode, 0, preview.stderr)
            family = json.loads(preview.stdout)["managed_families"][
                "subtitle_normalization"
            ]
            self.assertEqual(
                [item["path"] for item in family["candidates"]],
                ["subtitle_removal/provider/normalization_tests"],
            )

            (subtitle / "subtitle_removal_report.json").write_text(
                '{"overall":"FAIL"}\n',
                encoding="utf-8",
            )
            stale = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "preview",
                    "--job-dir",
                    str(job_dir),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(stale.returncode, 0, stale.stderr)
            stale_family = json.loads(stale.stdout)["managed_families"][
                "subtitle_normalization"
            ]
            self.assertEqual(stale_family["candidates"], [])
            self.assertIn("migration", stale_family["reason"])

    def test_preview_identifies_old_pack_archives_without_deleting_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "output" / "job-001"
            older = job_dir / "deprecated" / "pre_seedance_pack_20240101" / "old.bin"
            newer = job_dir / "deprecated" / "pre_seedance_pack_20240201" / "new.bin"
            duplicate_a = job_dir / "active" / "a.bin"
            duplicate_b = job_dir / "active" / "b.bin"
            for path, payload in (
                (older, b"older"),
                (newer, b"newer-data"),
                (duplicate_a, b"same"),
                (duplicate_b, b"same"),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)

            result = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "preview",
                    "--job-dir",
                    str(job_dir),
                    "--out",
                    str(job_dir / "checks" / "artifact_retention_preview.json"),
                    "--diagnose-duplicates",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["mode"], "dry_run")
            self.assertEqual(report["legacy_pack_archives"]["found"], 2)
            self.assertEqual(
                report["legacy_pack_archives"]["keep"],
                "deprecated/pre_seedance_pack_20240201",
            )
            self.assertEqual(report["legacy_pack_archives"]["reclaimable_bytes"], 5)
            self.assertEqual(report["exact_duplicates"]["reclaimable_bytes"], 4)
            self.assertTrue(older.exists())
            self.assertTrue(newer.exists())

            quick = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "preview",
                    "--job-dir",
                    str(job_dir),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(quick.returncode, 0, quick.stderr)
            self.assertEqual(
                json.loads(quick.stdout)["exact_duplicates"]["mode"],
                "not_scanned",
            )

            repeated = subprocess.run(
                result.args,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                json.loads(repeated.stdout)["total_files"],
                report["total_files"],
            )

            cleaned = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "cleanup",
                    "--job-dir",
                    str(job_dir),
                    "--preview",
                    str(job_dir / "checks" / "artifact_retention_preview.json"),
                    "--confirm-job-id",
                    "job-001",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(cleaned.returncode, 0, cleaned.stderr)
            self.assertFalse(older.exists())
            self.assertTrue(newer.exists())

    def test_preview_and_cleanup_manage_only_unreferenced_reproducible_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "output" / "job-002"
            rhythm = job_dir / "剧情分析" / "source_rhythm.json"
            rhythm.parent.mkdir(parents=True)
            rhythm.write_text('{"beats":[]}\n', encoding="utf-8")
            rhythm_sha = __import__("hashlib").sha256(rhythm.read_bytes()).hexdigest()

            active_cache = job_dir / "source-composition" / "current"
            rollback_cache = job_dir / "source-composition" / "rollback"
            stale_cache = job_dir / "source-composition" / "stale"
            for cache, source_sha in (
                (active_cache, rhythm_sha),
                (stale_cache, "0" * 64),
                (rollback_cache, "1" * 64),
            ):
                cache.mkdir(parents=True)
                (cache / "payload.bin").write_bytes(b"cache")
                (cache / "source_composition_bundle.json").write_text(
                    json.dumps(
                        {
                            "overall": "PASS",
                            "source_rhythm": {"sha256": source_sha},
                        }
                    ),
                    encoding="utf-8",
                )
            composition_root = job_dir / "source-composition"
            for name, value in (
                (
                    "source_composition_plan.json",
                    {
                        "cache_key": "current",
                        "output_root": "output/job-002/source-composition/current",
                        "source_rhythm": {"sha256": rhythm_sha},
                    },
                ),
                (
                    "source_composition_spec.json",
                    {
                        "cache_key": "current",
                        "output_root": "output/job-002/source-composition/current",
                        "source_rhythm_sha256": rhythm_sha,
                    },
                ),
            ):
                (composition_root / name).write_text(
                    json.dumps(value),
                    encoding="utf-8",
                )

            approved_candidate = job_dir / "image-batch" / "candidates" / "approved.png"
            unused_candidate = job_dir / "image-batch" / "candidates" / "unused.png"
            approved_candidate.parent.mkdir(parents=True)
            approved_candidate.write_bytes(b"approved")
            unused_candidate.write_bytes(b"unused")
            approved_sha = __import__("hashlib").sha256(
                approved_candidate.read_bytes()
            ).hexdigest()
            promoted = job_dir / "AI改好分镜图" / "Part1.png"
            promoted.parent.mkdir(parents=True)
            promoted.write_bytes(b"approved")
            manifest = job_dir / "visual-assets" / "approved_visual_manifest.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                json.dumps(
                    {
                        "job_id": "job-002",
                        "part_storyboards": {
                            "part1": {
                                "path": str(promoted),
                                "candidate_sha256": approved_sha,
                                "synced_from_candidate": (
                                    "output/job-002/image-batch/candidates/approved.png"
                                ),
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            selected = job_dir / "generation" / "selected_outputs.json"
            selected.parent.mkdir(parents=True)
            selected_video = job_dir / "generation" / "part1.mp4"
            selected_video.write_bytes(b"selected")
            selected_sha = __import__("hashlib").sha256(
                selected_video.read_bytes()
            ).hexdigest()
            selected.write_text(
                json.dumps(
                    {
                        "outputs": [
                            {
                                "part_id": "part1",
                                "path": str(selected_video),
                                "sha256": selected_sha,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            debug = job_dir / "generation" / "debug_preflight"
            debug.mkdir()
            (debug / "request.json").write_text("{}", encoding="utf-8")

            final_video = job_dir / "final" / "final_video.mp4"
            final_video.parent.mkdir(parents=True)
            final_video.write_bytes(b"final")
            final_sha = __import__("hashlib").sha256(
                final_video.read_bytes()
            ).hexdigest()
            subtitle_report = (
                job_dir / "subtitle_removal" / "subtitle_removal_report.json"
            )
            subtitle_report.parent.mkdir(parents=True)
            subtitle_report.write_text(
                json.dumps(
                    {
                        "overall": "PASS",
                        "source_video": str(final_video),
                        "source_sha256": final_sha,
                        "output_video": str(final_video),
                        "output_sha256": final_sha,
                    }
                ),
                encoding="utf-8",
            )
            normalization = (
                job_dir
                / "subtitle_removal"
                / "provider"
                / "normalization_tests"
            )
            normalization.mkdir(parents=True)
            (normalization / "trial.mp4").write_bytes(b"trial")

            preview_path = job_dir / "checks" / "artifact_retention_preview.json"
            result = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "preview",
                    "--job-dir",
                    str(job_dir),
                    "--out",
                    str(preview_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            candidates = {
                item["path"]
                for family in report["managed_families"].values()
                for item in family["candidates"]
            }
            self.assertIn("source-composition/stale", candidates)
            self.assertIn("image-batch/candidates/unused.png", candidates)
            self.assertIn("generation/debug_preflight", candidates)
            self.assertIn("subtitle_removal/provider/normalization_tests", candidates)
            self.assertNotIn("source-composition/current", candidates)
            self.assertNotIn("source-composition/rollback", candidates)
            self.assertNotIn(
                "image-batch/candidates/approved.png",
                candidates,
            )
            self.assertEqual(report["storage_budget"]["class"], "completed")

            cleaned = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "cleanup",
                    "--job-dir",
                    str(job_dir),
                    "--preview",
                    str(preview_path),
                    "--confirm-job-id",
                    "job-002",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(cleaned.returncode, 0, cleaned.stderr)
            self.assertFalse(stale_cache.exists())
            self.assertFalse(unused_candidate.exists())
            self.assertFalse(debug.exists())
            self.assertFalse(normalization.exists())
            self.assertTrue(active_cache.exists())
            self.assertTrue(rollback_cache.exists())
            self.assertTrue(approved_candidate.exists())
            self.assertTrue(final_video.exists())

    def test_cleanup_refuses_a_stale_managed_artifact_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "output" / "job-003"
            rhythm = job_dir / "剧情分析" / "source_rhythm.json"
            rhythm.parent.mkdir(parents=True)
            rhythm.write_text('{"beats":[]}\n', encoding="utf-8")
            rhythm_sha = __import__("hashlib").sha256(rhythm.read_bytes()).hexdigest()
            composition = job_dir / "source-composition"
            for name, source_hash in (
                ("active", rhythm_sha),
                ("stale", "0" * 64),
                ("rollback", "1" * 64),
            ):
                cache = composition / name
                cache.mkdir(parents=True)
                (cache / "payload.bin").write_bytes(b"cache")
                (cache / "source_composition_bundle.json").write_text(
                    json.dumps(
                        {
                            "overall": "PASS",
                            "source_rhythm": {"sha256": source_hash},
                        }
                    ),
                    encoding="utf-8",
                )
            (composition / "source_composition_plan.json").write_text(
                json.dumps(
                    {
                        "cache_key": "active",
                        "output_root": "output/job-003/source-composition/active",
                        "source_rhythm": {"sha256": rhythm_sha},
                    }
                ),
                encoding="utf-8",
            )
            (composition / "source_composition_spec.json").write_text(
                json.dumps(
                    {
                        "cache_key": "active",
                        "output_root": "output/job-003/source-composition/active",
                        "source_rhythm_sha256": rhythm_sha,
                    }
                ),
                encoding="utf-8",
            )
            debug = composition / "stale"
            preview_path = job_dir / "preview.json"

            preview = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "preview",
                    "--job-dir",
                    str(job_dir),
                    "--out",
                    str(preview_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(preview.returncode, 0, preview.stderr)
            (debug / "new.json").write_text("{}", encoding="utf-8")

            cleaned = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "cleanup",
                    "--job-dir",
                    str(job_dir),
                    "--preview",
                    str(preview_path),
                    "--confirm-job-id",
                    "job-003",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(cleaned.returncode, 0)
            self.assertIn("stale", cleaned.stderr)
            self.assertTrue(debug.exists())

    def test_local_repair_keeps_current_master_one_rollback_and_patch(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "output" / "job-004"
            final = job_dir / "final"
            archive = final / "archive"
            retake = job_dir / "quality_retake" / "repair-1"
            edit = retake / "edit"
            generation = retake / "generation"
            old_edit = job_dir / "edit" / "repair-0"
            for path in (archive, edit, generation, old_edit):
                path.mkdir(parents=True, exist_ok=True)
            master = final / "final_video.mp4"
            candidate = edit / "final_video_candidate.mp4"
            rollback = archive / "before_retake.mp4"
            older_rollback = archive / "before_old_repair.mp4"
            patch = generation / "patch.mp4"
            intermediate = old_edit / "full_intermediate.mp4"
            replacement = old_edit / "segment_replacement.mp4"
            for path, payload in (
                (master, b"current"),
                (candidate, b"current"),
                (rollback, b"baseline"),
                (older_rollback, b"older"),
                (patch, b"patch"),
                (intermediate, b"baseline"),
                (replacement, b"replacement"),
            ):
                path.write_bytes(payload)
            sha = lambda path: __import__("hashlib").sha256(
                path.read_bytes()
            ).hexdigest()
            (edit / "retake_report.json").write_text(
                json.dumps(
                    {
                        "decision": "PASS",
                        "candidate": {
                            "path": str(candidate),
                            "sha256": sha(candidate),
                        },
                        "baseline": {
                            "path": str(rollback),
                            "sha256": sha(rollback),
                        },
                        "generated_patch": {"path": str(patch)},
                        "rollback": str(rollback),
                    }
                ),
                encoding="utf-8",
            )
            (old_edit / "shot_repair_report.json").write_text(
                json.dumps(
                    {
                        "overall": "PASS",
                        "output_master_sha256": sha(rollback),
                    }
                ),
                encoding="utf-8",
            )
            preview_path = job_dir / "preview.json"
            preview = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "preview",
                    "--job-dir",
                    str(job_dir),
                    "--out",
                    str(preview_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(preview.returncode, 0, preview.stderr)
            cleaned = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "cleanup",
                    "--job-dir",
                    str(job_dir),
                    "--preview",
                    str(preview_path),
                    "--confirm-job-id",
                    "job-004",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(cleaned.returncode, 0, cleaned.stderr)
            self.assertTrue(master.exists())
            self.assertTrue(rollback.exists())
            self.assertTrue(patch.exists())
            self.assertTrue(replacement.exists())
            self.assertFalse(candidate.exists())
            self.assertFalse(older_rollback.exists())
            self.assertFalse(intermediate.exists())

    def test_preview_can_fail_mechanically_when_projected_size_exceeds_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp) / "output" / "job-005"
            job_dir.mkdir(parents=True)
            large = job_dir / "large.bin"
            large.touch()
            with large.open("r+b") as handle:
                handle.truncate(151 * 1024 * 1024)

            result = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "preview",
                    "--job-dir",
                    str(job_dir),
                    "--fail-on-budget",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            report = json.loads(result.stdout)
            self.assertGreater(
                report["storage_budget"]["projected_bytes_after_cleanup"],
                report["storage_budget"]["budget_bytes"],
            )


if __name__ == "__main__":
    unittest.main()
