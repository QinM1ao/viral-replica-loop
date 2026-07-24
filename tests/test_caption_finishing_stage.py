import csv
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import caption_finishing_qc
import run_next_loop_round


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CaptionFinishingStageTests(unittest.TestCase):
    def setUp(self):
        rules = json.loads((REPO_ROOT / "rules" / "STAGE_RULES.json").read_text(encoding="utf-8"))
        self.rules = {item["id"]: item for item in rules["rules"]}

    def write_job(self, root):
        source = root / "source.mp4"
        source.write_bytes(b"source-video")
        fields = ["id", "video_path", "output_dir"]
        with (root / "jobs.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerow(
                {
                    "id": "job-001",
                    "video_path": str(source),
                    "output_dir": "output/job-001",
                }
            )
        return caption_finishing_qc.load_job(root, "job-001")

    def test_default_final_qc_path_is_unchanged(self):
        self.assertEqual(self.rules["final_qc"]["next_expected"], "done")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job = {"id": "job-001", "output_dir": "output/job-001"}
            decision = {"canonical_stage": "final_qc", "next_expected": "done"}
            self.assertIs(
                run_next_loop_round.apply_optional_caption_transition(root, job, decision),
                decision,
            )

    def test_explicit_request_redirects_only_after_final_qc(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job = self.write_job(root)
            caption_finishing_qc.write_request(root, "job-001", "最终成片要字幕", True)
            decision = {"canonical_stage": "final_qc", "next_expected": "done"}
            redirected = run_next_loop_round.apply_optional_caption_transition(root, job, decision)
            self.assertEqual(redirected["next_expected"], "caption_finishing")
            self.assertEqual(decision["next_expected"], "done")

            generation = {"canonical_stage": "generation", "next_expected": "finishing"}
            self.assertIs(
                run_next_loop_round.apply_optional_caption_transition(root, job, generation),
                generation,
            )

    def test_invalid_request_cannot_silently_fall_back_to_done(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job = self.write_job(root)
            request_path = caption_finishing_qc.request_path_for(root, job)
            request_path.parent.mkdir(parents=True)
            request_path.write_text('{"requested": true}\n', encoding="utf-8")
            args = Namespace(record_gate_result="PASS", artifact="")
            decision = {"canonical_stage": "final_qc"}
            with self.assertRaisesRegex(ValueError, "caption request is invalid"):
                run_next_loop_round.preflight_pass_recording(root, job, decision, args)

    def test_caption_stage_is_present_and_stays_in_delivery_stage(self):
        stage = self.rules["caption_finishing"]
        self.assertEqual(stage["canonical_stage"], "caption_finishing")
        self.assertEqual(stage["next_expected"], "done")
        self.assertTrue((REPO_ROOT / stage["worker_file"]).is_file())
        self.assertTrue((REPO_ROOT / stage["gate"]).is_file())
        visible = run_next_loop_round.user_visible_stage(
            "caption_finishing", "caption_finishing", "done"
        )
        self.assertEqual(visible["index"], 5)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is required")
    def test_caption_pass_requires_hash_bound_skill_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job = self.write_job(root)
            caption_finishing_qc.write_request(root, "job-001", "最终成片要字幕", True)
            output_dir = caption_finishing_qc.output_dir_for(root, job)
            caption_dir = output_dir / "caption_finishing"
            caption_dir.mkdir(parents=True, exist_ok=True)

            active = output_dir / "final" / "active.mp4"
            active.parent.mkdir(parents=True)
            output = caption_dir / "captioned.mp4"
            for path, color in ((active, "black"), (output, "blue")):
                subprocess.run(
                    [
                        "ffmpeg", "-y", "-loglevel", "error",
                        "-f", "lavfi", "-i", f"color=c={color}:s=16x16:d=0.5",
                        "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono",
                        "-t", "0.5", "-c:v", "mpeg4", "-c:a", "aac",
                        "-shortest", str(path),
                    ],
                    check=True,
                )
            blueprint = caption_dir / "caption_blueprint.json"
            timeline = caption_dir / "caption_timeline.json"
            hyperframes = caption_dir / "hyperframes_check.json"
            visual = caption_dir / "visual_review.json"
            caption_qc = caption_dir / "caption_qc.json"
            blueprint.write_text('{"version": 1}\n', encoding="utf-8")
            timeline.write_text('{"version": 1}\n', encoding="utf-8")
            hyperframes.write_text('{"ok": true}\n', encoding="utf-8")
            visual.write_text(
                json.dumps(
                    {
                        "status": "PASS",
                        "checks": {
                            "no_collision": True,
                            "no_clipping": True,
                            "no_face_or_product_obstruction": True,
                            "all_special_events_visible": True,
                            "source_grammar_match": True,
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            caption_qc.write_text(
                json.dumps({"status": "PASS", "artifact": str(output)}) + "\n",
                encoding="utf-8",
            )

            active_binding = (active.resolve(), sha256(active), [])
            with mock.patch.object(caption_finishing_qc, "_active_final_input", return_value=active_binding):
                caption_finishing_qc.write_report(
                    root,
                    job,
                    {
                        "caption_blueprint": blueprint,
                        "caption_timeline": timeline,
                        "hyperframes_check": hyperframes,
                        "visual_review": visual,
                        "caption_qc": caption_qc,
                        "output_video": output,
                    },
                )
                self.assertEqual(caption_finishing_qc.caption_report_issues(root, job), [])
                args = Namespace(record_gate_result="PASS", artifact="")
                run_next_loop_round.preflight_pass_recording(
                    root,
                    job,
                    {"canonical_stage": "caption_finishing"},
                    args,
                )

                output.write_bytes(b"mutated-captioned-video")
                issues = caption_finishing_qc.caption_report_issues(root, job)
                self.assertTrue(any("hash does not match" in issue for issue in issues))


if __name__ == "__main__":
    unittest.main()
