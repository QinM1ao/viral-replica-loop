import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from seedance25_request_builder import (  # noqa: E402
    build_seedance25_request,
    load_active_assets,
)
from seedance25_source_fidelity_qc import assess  # noqa: E402
from seedance_request_contract import decode_taskcode_param  # noqa: E402


SPRAY_ACTION = (
    "女性一次按压喷头，液体离开喷口立即分散成均匀细密的雾化微滴，"
    "微滴在空气中短暂悬浮后落到皮肤形成极细小水珠。"
)


class Seedance25PromptModesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = {
            "source_sha256": "accepted-video-sha",
            "beats": [
                {"id": "sr001", "visual_action": "女性举起喷雾瓶。", "confirmed_source_line": "我真的"},
                {"id": "sr002", "visual_action": "女性把喷雾瓶移到脸侧。", "confirmed_source_line": "恨不得把它"},
                {"id": "sr003", "visual_action": SPRAY_ACTION, "confirmed_source_line": "焊在脸上"},
            ],
        }
        self.source_path = self._write_json("source.json", self.source)
        self.directives_path = self._write_text("directives.txt", "保持原台词；深度默认不用。")

    def tearDown(self):
        self.temp.cleanup()

    def _write_json(self, name, payload):
        path = self.root / name
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def _write_text(self, name, value):
        path = self.root / name
        path.write_text(value, encoding="utf-8")
        return path

    def _trace(self, audio_mode):
        return {
            "schema_version": 5,
            "fidelity_mode": "source_locked",
            "audio_mode": audio_mode,
            "depth_reference": {"enabled": False},
            "source_rhythm_sha256": hashlib.sha256(self.source_path.read_bytes()).hexdigest(),
            "events": [
                {"stage": "阶段一", "source_beat_id": "sr001", "target_visual_action": "女性举起喷雾瓶。", "visual_edits": []},
                {"stage": "阶段二", "source_beat_id": "sr002", "target_visual_action": "女性把喷雾瓶移到脸侧。", "visual_edits": []},
                {"stage": "阶段三", "source_beat_id": "sr003", "target_visual_action": SPRAY_ACTION, "visual_edits": []},
            ],
            "speech_groups": [
                {
                    "id": "sg001",
                    "semantic_unit": "complete_sentence",
                    "stage_span": ["阶段一", "阶段二", "阶段三"],
                    "source_parts": [
                        {"source_beat_id": "sr001", "text": "我真的"},
                        {"source_beat_id": "sr002", "text": "恨不得把它"},
                        {"source_beat_id": "sr003", "text": "焊在脸上"},
                    ],
                    "source_line": "我真的恨不得把它焊在脸上",
                    "target_line": "我真的恨不得把它焊在脸上",
                    "line_edits": [],
                    "delivery": "single_continuous_block",
                    "protected_terms": ["焊在脸上"],
                }
            ],
        }

    def _prompt(self, generated):
        dialogue = (
            "从阶段一连续覆盖至阶段三的女性画外音：{我真的恨不得把它焊在脸上}"
            if generated else ""
        )
        return f"""【生成目标】
生成一段真实护肤产品展示视频，女性展示并使用同一瓶补水喷雾。

【参考素材职责】
@图片1用于分镜关键状态、人物姿态、手部位置、产品状态、场景和构图，不采用网格、边框或文字标记。

【主体与道具】
女性与喷雾瓶全片保持同一身份和同一产品外观。

【事件脚本】
阶段一：女性举起喷雾瓶。结束时喷雾瓶稳定朝向镜头。{dialogue}

阶段二：女性把喷雾瓶移到脸侧。结束时喷头与脸部保持可见间距。

阶段三：{SPRAY_ACTION}结束时皮肤表面只留下均匀的极细小水珠。

【保持一致】
保持女性身份、喷雾瓶数量与外观、产品归属和画外音关系稳定。
"""

    def _assess(self, audio_mode):
        prompt = self._prompt(audio_mode == "generated_voiceover")
        prompt_path = self._write_text(f"{audio_mode}.txt", prompt)
        trace_path = self._write_json(f"{audio_mode}.json", self._trace(audio_mode))
        report = assess(
            source_rhythm_path=self.source_path,
            traceability_path=trace_path,
            prompt_path=prompt_path,
            user_directives_path=self.directives_path,
        )
        return prompt, report

    def test_generated_voiceover_uses_one_semantic_block_and_no_depth(self):
        _prompt, report = self._assess("generated_voiceover")
        self.assertEqual(report["overall"], "PASS", report["checks"])
        self.assertFalse(report["depth_reference_enabled"])
        self.assertEqual(report["expected_transcript"], "我真的恨不得把它焊在脸上")

    def test_original_master_postmix_has_no_prompt_dialogue(self):
        prompt, report = self._assess("original_master_postmix")
        self.assertEqual(report["overall"], "PASS", report["checks"])
        self.assertNotIn("{", prompt)
        self.assertNotIn("@音频", prompt)

    def test_fragmented_internal_label_and_weak_spray_prompt_fail(self):
        trace = self._trace("generated_voiceover")
        trace["speech_groups"] = [
            {
                "id": "sg001",
                "semantic_unit": "complete_sentence",
                "stage_span": ["阶段一"],
                "source_parts": [{"source_beat_id": "sr001", "text": "我真的"}],
                "source_line": "我真的",
                "target_line": "我真的",
                "line_edits": [],
                "delivery": "single_continuous_block",
                "protected_terms": ["我真的"],
            },
            {
                "id": "sg002",
                "semantic_unit": "complete_clause",
                "stage_span": ["阶段二"],
                "source_parts": [{"source_beat_id": "sr002", "text": "恨不得把它"}],
                "source_line": "恨不得把它",
                "target_line": "恨不得把它",
                "line_edits": [],
                "delivery": "single_continuous_block",
                "protected_terms": ["恨不得把它"],
            },
            {
                "id": "sg003",
                "semantic_unit": "complete_clause",
                "stage_span": ["阶段三"],
                "source_parts": [{"source_beat_id": "sr003", "text": "焊在脸上"}],
                "source_line": "焊在脸上",
                "target_line": "焊在脸上",
                "line_edits": [],
                "delivery": "single_continuous_block",
                "protected_terms": ["焊在脸上"],
            },
        ]
        trace["events"][2]["target_visual_action"] = "女性按压喷头，喷出细密水雾。"
        prompt = self._prompt(True).replace(
            "从阶段一连续覆盖至阶段三的女性画外音：{我真的恨不得把它焊在脸上}",
            "女性画外音：{我真的}",
        ).replace(
            "女性把喷雾瓶移到脸侧。结束时喷头与脸部保持可见间距。",
            "女性把喷雾瓶移到脸侧。结束时喷头与脸部保持可见间距。女性画外音：{恨不得把它}",
        ).replace(
            SPRAY_ACTION,
            "女性按压喷头，喷出细密水雾。",
        ).replace(
            "结束时皮肤表面只留下均匀的极细小水珠。",
            "结束时皮肤表面留下水珠。女性画外音：{焊在脸上} 对应Shot。",
        )
        prompt_path = self._write_text("bad.txt", prompt)
        trace_path = self._write_json("bad.json", trace)
        report = assess(
            source_rhythm_path=self.source_path,
            traceability_path=trace_path,
            prompt_path=prompt_path,
            user_directives_path=self.directives_path,
        )
        failures = {item["name"] for item in report["checks"] if item["status"] == "FAIL"}
        self.assertEqual(report["overall"], "FAIL")
        self.assertIn("prompt_has_no_internal_labels", failures)
        self.assertIn("sg001_semantic_completeness", failures)
        self.assertIn("sg002_semantic_completeness", failures)
        self.assertIn("sr003_atomized_mist_physics", failures)

    def test_request_modes_and_optional_depth(self):
        generated_prompt, generated_qc = self._assess("generated_voiceover")
        assets = [{
            "asset_type": "Image",
            "asset_ref": "asset://asset-image1",
            "status": "Active",
            "role": "storyboard",
            "source_sha256": "image-sha",
        }]
        request, manifest, request_qc = build_seedance25_request(
            prompt=generated_prompt,
            assets=assets,
            duration=12,
            audio_mode="generated_voiceover",
            source_fidelity_qc=generated_qc,
        )
        _body, param = decode_taskcode_param(request)
        self.assertTrue(param["generate_audio"])
        self.assertEqual(request_qc["overall"], "PASS", request_qc["checks"])
        self.assertFalse(manifest["depth_reference_enabled"])

        postmix_prompt, postmix_qc = self._assess("original_master_postmix")
        postmix_request, _manifest, postmix_request_qc = build_seedance25_request(
            prompt=postmix_prompt,
            assets=assets,
            duration=12,
            audio_mode="original_master_postmix",
            source_fidelity_qc=postmix_qc,
        )
        _body, postmix_param = decode_taskcode_param(postmix_request)
        self.assertFalse(postmix_param["generate_audio"])
        self.assertEqual(postmix_request_qc["overall"], "PASS", postmix_request_qc["checks"])
        with self.assertRaisesRegex(ValueError, "excludes reference audio"):
            build_seedance25_request(
                prompt=postmix_prompt,
                assets=assets,
                duration=12,
                audio_mode="original_master_postmix",
                audio_url="https://example.com/original.mp3",
                source_fidelity_qc=postmix_qc,
            )

    def test_active_assets_accept_zero_or_one_depth(self):
        image = {"asset_type": "Image", "asset_ref": "asset://asset-image1", "status": "Active"}
        video = {"asset_type": "Video", "asset_ref": "asset://asset-video1", "status": "Active"}
        no_depth = self._write_json("images.json", {"overall": "PASS", "items": [image]})
        one_depth = self._write_json("one-video.json", {"overall": "PASS", "items": [image, video]})
        two_depth = self._write_json("two-video.json", {"overall": "PASS", "items": [image, video, video]})
        self.assertEqual(len(load_active_assets(no_depth)), 1)
        self.assertEqual(len(load_active_assets(one_depth)), 2)
        with self.assertRaisesRegex(ValueError, "at most one depth video"):
            load_active_assets(two_depth)


if __name__ == "__main__":
    unittest.main()
