import csv
import hashlib
import json
import os
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class KongfengchunFromZeroAcceptanceTest(unittest.TestCase):
    """Public-artifact acceptance test for a fresh task stopped before Seedance."""

    @classmethod
    def setUpClass(cls):
        cls.job_id = os.environ.get("VREP_ACCEPTANCE_JOB_ID")
        if not cls.job_id:
            raise unittest.SkipTest("set VREP_ACCEPTANCE_JOB_ID to run the real acceptance case")
        cls.job_dir = ROOT / "output" / cls.job_id

    def test_fresh_task_reaches_the_accepted_pre_seedance_result(self):
        self.assertTrue(self.job_dir.is_dir(), f"missing fresh output: {self.job_dir}")

        with (ROOT / "jobs.csv").open(encoding="utf-8", newline="") as handle:
            rows = {row["id"]: row for row in csv.DictReader(handle)}
        self.assertIn(self.job_id, rows)
        self.assertEqual(rows[self.job_id]["status"], "seedance_inputs_prepared")

        runner = load_json(ROOT / "RUNNER_STATE.json")["jobs"][self.job_id]
        self.assertEqual(runner["spent"]["seedance_runs"], 0)

        profile = load_json(self.job_dir / "product_profile.json")
        self.assertEqual(profile["product_name"], "孔凤春清洁泥膜")
        self.assertEqual(profile["category_id"], "clay_mask")
        self.assertEqual(profile["sku_id"], "kongfengchun_clean_mud_mask")
        self.assertEqual(
            profile["reference_roles"]["required"],
            ["source_storyboard", "product_front", "identity_ref", "product_open_mud"],
        )
        self.assertFalse(profile["checks"]["requires_afterwash_ref"])

        blueprint = load_json(self.job_dir / "checks" / "source_blueprint_report.json")
        self.assertEqual(blueprint["overall"], "PASS")
        self.assertFalse(blueprint["cache_hit"], "acceptance run must rebuild source facts")

        rhythm = load_json(self.job_dir / "剧情分析" / "source_rhythm.json")
        self.assertEqual(rhythm["schema_version"], 2)
        self.assertEqual(len(rhythm["beats"]), 17)
        self.assertEqual(
            [beat["confirmed_source_line"] for beat in rhythm["beats"][:4]],
            ["黑头闭口", "涂！", "油皮粉刺", "涂！"],
        )
        for beat_id in ("sr002", "sr004"):
            beat = next(item for item in rhythm["beats"] if item["id"] == beat_id)
            self.assertEqual(beat["visual_action_type"], "physical_change")
            evidence = beat["action_evidence"]
            frames = {
                evidence["before_frame_ref"],
                evidence["peak_frame_ref"],
                evidence["after_frame_ref"],
            }
            self.assertEqual(len(frames), 3)
            self.assertTrue(evidence["motion"])
            self.assertTrue(evidence["visible_result"])

        storyboard = load_json(
            self.job_dir / "storyboard_source_refs" / "source_storyboard_manifest.json"
        )
        self.assertEqual(storyboard["selection_mode"], "source_rhythm")
        self.assertEqual(storyboard["groups"], 2)
        self.assertEqual(storyboard["total_frames"], 24)
        self.assertEqual([part["frame_count"] for part in storyboard["parts"]], [12, 12])

        image_contract = load_json(
            self.job_dir / "image-batch" / "codex_imagegen_contract.json"
        )
        self.assertEqual(image_contract["image_route"], "matpool_gpt_image_2_edit")
        self.assertTrue(image_contract["matpool_uses_real_image_inputs"])
        self.assertEqual(len(image_contract["parts"]), 2)
        for part in image_contract["parts"]:
            self.assertTrue(part["candidate_path"].startswith(f"output/{self.job_id}/"))
            self.assertTrue(all(part["review"].values()))
            self.assertEqual(
                part["reference_order"],
                ["source_storyboard", "product_front", "product_open_mud", "identity_ref"],
            )

        visual = load_json(
            self.job_dir / "visual-assets" / "approved_visual_manifest.json"
        )
        self.assertEqual(visual["schema_version"], 2)
        self.assertEqual(visual["source_presenter_gender"], "male")
        self.assertEqual(visual["target_presenter_gender"], "male")
        self.assertEqual(visual["identity_group_id"], "kongfengchun_male_content4")
        self.assertEqual(set(visual["part_storyboards"]), {"part1", "part2"})
        for item in visual["part_storyboards"].values():
            self.assertEqual(item["asset_type"], "AI改好分镜图")
            self.assertFalse(item["contains_source_video_pixels"])
            self.assertTrue(item["path"].startswith(f"output/{self.job_id}/"))
            metadata = item["shot_label_metadata"]
            self.assertEqual(metadata["type"], "shot_label_metadata_only")
            self.assertFalse(metadata["panel_pixels_modified"])
            evidence = load_json(ROOT / metadata["evidence"])
            promoted = ROOT / item["path"]
            promoted_hash = hashlib.sha256(promoted.read_bytes()).hexdigest()
            self.assertEqual(evidence["status"], "PASS")
            self.assertEqual(evidence["outside_label_changed_pixels"], 0)
            self.assertFalse(evidence["panel_pixels_modified"])
            self.assertEqual(evidence["output_sha256"], promoted_hash)

        plan = load_json(self.job_dir / "seedance" / "director_plan.json")
        self.assertEqual(plan["version"], 4)
        self.assertEqual(plan["presenter_gender"], {"source": "male", "target": "male"})
        self.assertEqual(plan["spoken_product_anchor"]["full_name"], "孔凤春清洁泥膜")
        self.assertEqual([part["id"] for part in plan["parts"]], ["part1", "part2"])
        self.assertEqual([len(part["execution_blocks"]) for part in plan["parts"]], [6, 6])

        expected_lines = {
            "part1": [
                "黑头闭口，涂！油皮粉刺，涂！",
                "管它黑头还是油光。孔凤春清洁泥膜。",
                "油皮看好了。四种果酸松动毛孔油脂。",
                "三重矿物泥在外吸附带走。",
                "你就涂在黑头闭口的地方。",
                "涂完之后等五分钟。",
            ],
            "part2": [
                "直接水洗，脏东西连根拔起。",
                "这个皮肤，女朋友凑再近都不怕。",
                "今天是我打卡这罐泥膜的第三十天。这一罐已经快用空了。",
                "说真的，男生护肤不用那些——",
                "瓶瓶罐罐的。",
                "这一罐就够了。",
            ],
        }
        for part in plan["parts"]:
            self.assertEqual(
                [group["line"] for group in part["speech_groups"]],
                expected_lines[part["id"]],
            )

        part1_action = plan["parts"][0]["beats"][0]["target_visual_action"]
        for phrase in ("指腹", "划过鼻翼", "留下白泥", "划过下巴", "四拍依次完成"):
            self.assertIn(phrase, part1_action)
        part2_actions = [beat["target_visual_action"] for beat in plan["parts"][1]["beats"]]
        self.assertIn("洗脸中段", part2_actions[0])
        self.assertIn("完全无瑕疵", part2_actions[1])
        self.assertIn("虚焦B-roll", part2_actions[-2])
        self.assertIn("不重新起手推近", part2_actions[-1])

        prompts = []
        for part_no in (1, 2):
            prompt = (self.job_dir / "seedance" / f"seedance_part{part_no}_prompt.txt").read_text(
                encoding="utf-8"
            )
            prompts.append(prompt)
            self.assertEqual(len(re.findall(r"^\d+(?:\.\d+)?–\d+(?:\.\d+)?秒｜Shot ", prompt, re.M)), 6)
            self.assertNotIn("音效：无", prompt)
            self.assertNotRegex(
                prompt,
                r"原片|源片|原视频|按分镜|source video|source rhythm|source beat|同Part1|承接上一段",
            )
            self.assertIn("无字幕", prompt)
            self.assertIn("无背景音乐", prompt)
        self.assertEqual("\n".join(prompts).count("孔凤春清洁泥膜"), 1)

        for part_no in (1, 2):
            audio = self.job_dir / "audio-boundary" / f"part{part_no}_reference_audio.mp3"
            self.assertTrue(audio.is_file())
            duration = float(
                subprocess.check_output(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-show_entries",
                        "format=duration",
                        "-of",
                        "default=noprint_wrappers=1:nokey=1",
                        str(audio),
                    ],
                    text=True,
                ).strip()
            )
            self.assertLessEqual(duration, 15.0)

            request = load_json(
                self.job_dir / "seedance" / "requests" / f"part{part_no}_request_prepared.json"
            )
            self.assertTrue(request["prepared_only"])
            self.assertTrue(request["do_not_submit"])
            self.assertEqual(request["body"]["param"]["model"], "ep-20260521101914-nwv8j")
            self.assertEqual(request["body"]["param"]["duration"], 13.0)

        qc_bundle = load_json(
            self.job_dir / "checks" / "pre_seedance_pack_qc_bundle.json"
        )
        self.assertEqual(qc_bundle["overall"], "PASS")
        self.assertTrue(all(task["overall"] == "PASS" for task in qc_bundle["tasks"]))


if __name__ == "__main__":
    unittest.main()
