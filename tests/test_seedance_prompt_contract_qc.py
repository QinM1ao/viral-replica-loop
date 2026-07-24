import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "seedance_prompt_contract_qc.py"
sys.path.insert(0, str(REPO_ROOT / "tools"))

from seedance_prompt_contract_qc import (
    CANONICAL_SFX_LINE_RE,
    CANONICAL_VOICE_LINE_RE,
    check_spoken_product_anchor,
    parse_execution_blocks,
)


SHOT_LINE_MAP = """# Shot-Line Map

## Part1

| Target time | Source time | Source visual action | Source speaker mode / line | Target visual action | Speech group | Speech time | Target speaker mode / line | Reference binding | Must-keep reason |
|---|---|---|---|---|---|---|---|---|---|
| 0.0-1.5s | 0.0-1.5s | Face hook. | 女主画面内同期口播：“原第一句。” | Host face hook. | speech1 | 0.0-1.5s | 女主画面内同期口播：“第一句。” | @图片1/@图片4 | Hook. |
| 1.5-3.0s | 1.5-3.0s | Product reveal. | 女主画外音旁白：“原第二句。” | Handheld product reveal. | speech2 | 1.5-7.0s | 女主画外音旁白：“第二句，覆盖产品、手机和质地证明。” | @图片1/@图片2 | Product. |
| 3.0-5.0s | 3.0-5.0s | Phone proof. | 女主画外音旁白：“原第三句。” | Phone proof. | speech2 |  | 女主画外音旁白（speech2承接，无新增台词） | @图片1 | Proof. |
| 5.0-7.0s | 5.0-7.0s | Texture proof. | 女主画外音旁白：“原第四句。” | Open jar proof. | speech2 |  | 女主画外音旁白（speech2承接，无新增台词） | @图片2/@图片3 | Texture. |
| 7.0-10.0s | 7.0-10.0s | Apply product. | 女主画面内同期口播：“原第五句。” | Fingertip applies product while face stays visible. | speech3 | 7.0-9.5s | 女主画面内同期口播：“第五句。” | @图片1/@图片4 | Use. |
| 10.0-15.0s | 10.0-15.0s | Result close. | 无台词，只留环境声 | Final product and face close. |  |  | 无台词，只留环境声 | @图片1/@图片5 | Close. |
"""


LEGACY_SHOT_LINE_MAP = """# Shot-Line Map

## Part1

| Target time | Source time | Source visual action | Target visual action | Speaker mode / line |
|---|---|---|---|---|
| 0.0-1.5s | 0.0-1.5s | Face hook. | Host face hook. | 女主画面内同期口播：“第一句。” |
| 1.5-3.0s | 1.5-3.0s | Product reveal. | Handheld product reveal. | 女主画外音旁白：“第二句。” |
| 3.0-5.0s | 3.0-5.0s | Phone proof. | Phone proof. | 女主画外音旁白：“第三句。” |
| 5.0-7.0s | 5.0-7.0s | Texture proof. | Open jar proof. | 女主画外音旁白：“第四句。” |
| 7.0-10.0s | 7.0-10.0s | Apply product. | Fingertip applies product. | 女主画面内同期口播：“第五句。” |
| 10.0-15.0s | 10.0-15.0s | Result close. | Final product and face close. | 女主画外音旁白：“第六句。” |
"""


MISMATCHED_SHOT_LINE_MAP = SHOT_LINE_MAP.replace(
    '女主画外音旁白：“第二句，覆盖产品、手机和质地证明。”',
    '女主画面内同期口播：“第二句，覆盖产品、手机和质地证明。”',
)


GOOD_PROMPT = """参考图角色：
@图片1 只控制镜头顺序、景别、人物动作、产品出现节奏；不要复制分镜网格、边框、编号和任何画面文字。
@图片2 只校准目标产品的正面包装身份和标签文字；镜头构图、手部动作和产品出现节奏仍以@图片1为准。
@图片3 只校准开盖质地；真实手持操作环境里出现。
@图片4 控制同一位女主的脸、发型、肤色、年龄感和服装。
@图片5 只控制洗后状态。
音频1 只控制音色、语速、停顿、真人测评感和室内环境声。

生成约15秒、9:16竖屏、720p真实护肤测评短视频。严格按Shot编号顺序执行。全片无字幕、无标题条、无贴纸和水印。不生成任何背景音乐，只保留台词、环境声和与可见动作同步的真实音效。每个镜头都保持可见动作和轻微镜头运动，不出现连续静止不动的镜头。

0.0–1.5秒｜Shot 01
画面：女主近脸看镜头，手部轻微移动。
声音：女主画面内同期口播{第一句。}。
音效：<轻微衣料摩擦声>

1.5–7.0秒｜Shot 02–04
画面：产品在手中靠近镜头；硬切到手机证明镜头，手指滑动；硬切到开盖产品近景，手指挑起质地。
声音：旁白{第二句，覆盖产品、手机和质地证明。}。
音效：<手指滑动声>；<开盖和挑起质地的轻微操作声>

7.0–10.0秒｜Shot 05
画面：女主用指腹上脸，脸部稳定看向镜头。
声音：女主画面内同期口播{第五句。}。
音效：<指腹接触皮肤的轻微声音>

10.0–15.0秒｜Shot 06
画面：洗后脸证明，镜头轻微推进；随后产品自然落位收口，保持真实接触阴影。
声音：无台词。
音效：<室内环境声>；<产品轻放的接触声>
"""


BROAD_PROMPT = """参考图角色：
@图片1 只控制镜头顺序、景别、人物动作、产品出现节奏；不要复制分镜网格。
@图片2 只校准目标产品的正面包装身份和标签文字；镜头构图、手部动作和产品出现节奏仍以@图片1为准。
音频1 只控制音色、语速、停顿、真人测评感和室内环境声。

生成15秒9:16真实护肤测评短视频。无字幕。禁止BGM。
主目标：复刻@图片1的镜头节奏。
次目标：保持人物和产品一致。
简化：不增加无关人物。

Shot 1，0.0-5.0秒，女主开场、展示产品、看手机证明。女主画面内同期口播：“第一句。”产品镜头里女主不张口。女主画外音旁白：“第二句。”
Shot 2，5.0-10.0秒，展示质地并上脸。女主画外音旁白：“第三句。”
Shot 3，10.0-15.0秒，展示结果和产品收口。女主画外音旁白：“第四句。”
"""


class SeedancePromptContractQCTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "output/job-001/voiceover").mkdir(parents=True)
        (self.root / "output/job-001/seedance_web_final/prompts").mkdir(parents=True)
        (self.root / "output/job-001/voiceover/shot_line_map.md").write_text(SHOT_LINE_MAP, encoding="utf-8")
        (self.root / "output/job-001/seedance").mkdir(parents=True)
        (self.root / "output/job-001/seedance/director_plan.json").write_text(
            json.dumps(
                {
                    "presenter_gender": {"source": "female", "target": "female"},
                    "spoken_product_anchor": {
                        "full_name": "第一句",
                        "brand_name": "第一",
                        "part_id": "part1",
                        "speech_group_id": "speech1",
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        self.prompt_file = self.root / "output/job-001/seedance_web_final/prompts/Part1_Seedance提示词.txt"

    def tearDown(self):
        self.tmp.cleanup()

    def run_qc(self, prompt_files=None):
        bound_files = [
            Path(path) for path in (prompt_files or [self.prompt_file]) if Path(path).is_file()
        ]
        if bound_files:
            manifest_path = (
                self.root
                / "output/job-001/seedance/part_compilation_manifest.json"
            )
            manifest_path.write_text(
                json.dumps(
                    {
                        "job_id": "job-001",
                        "director_plan_sha256": hashlib.sha256(
                            (
                                self.root
                                / "output/job-001/seedance/director_plan.json"
                            ).read_bytes()
                        ).hexdigest(),
                        "parts": [
                            {
                                "part_id": f"part{index}",
                                "files": [
                                    {
                                        "path": f"seedance/seedance_part{index}_prompt.txt",
                                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                    }
                                ],
                            }
                            for index, path in enumerate(bound_files, start=1)
                        ],
                    }
                ),
                encoding="utf-8",
            )
        command = ["python3", str(SCRIPT), "--root", str(self.root), "--job-id", "job-001"]
        if prompt_files:
            command.extend(["--prompt-files", *(str(path) for path in prompt_files)])
        return subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
        )

    def read_report(self):
        return json.loads(
            (self.root / "output/job-001/checks/pre_seedance_pack_seedance_prompt_contract_qc.json").read_text(
                encoding="utf-8"
            )
        )

    def test_validated_source_faithful_example_is_packaged_as_standard(self):
        example = (
            REPO_ROOT
            / ".agents/skills/video-replication/references/examples/seedance-20-source-faithful-part1.txt"
        ).read_text(encoding="utf-8")
        blocks = parse_execution_blocks(example)

        self.assertEqual(len(blocks), 7)
        self.assertNotIn("声音执行", example)
        self.assertTrue(all(all(label in block["text"] for label in ("画面：", "声音：", "音效：")) for block in blocks))
        self.assertIn("已经打开的黑色手提包", blocks[2]["text"])
        self.assertNotIn("拉链", blocks[2]["text"])
        voice_lines = [
            line.strip() for line in example.splitlines() if line.strip().startswith("声音")
        ]
        sfx_lines = [
            line.strip() for line in example.splitlines() if line.strip().startswith("音效")
        ]
        self.assertTrue(
            all(CANONICAL_VOICE_LINE_RE.fullmatch(line) for line in voice_lines)
        )
        self.assertTrue(
            all(CANONICAL_SFX_LINE_RE.fullmatch(line) for line in sfx_lines)
        )

    def test_kongfengchun_part2_actual_validation_is_current_standard(self):
        example = (
            REPO_ROOT
            / ".agents/skills/video-replication/references/examples/seedance-20-kongfengchun-part2-validated.txt"
        ).read_text(encoding="utf-8")
        blocks = parse_execution_blocks(example)

        self.assertEqual(len(blocks), 6)
        self.assertIn("完全无瑕疵", example)
        self.assertNotIn("保留真实毛孔", example)
        self.assertNotIn("保留真实皮肤纹理", example)
        self.assertEqual(blocks[4]["storyboard_panels"], (11, 11))
        self.assertIn("瓶瓶罐罐的", blocks[4]["text"])
        self.assertEqual(blocks[5]["storyboard_panels"], (12, 12))
        self.assertIn("景别与Shot 10一致", blocks[5]["text"])
        self.assertIn("@图片4", example)

    def test_prompt_with_bound_visual_voice_and_sfx_passes(self):
        self.prompt_file.write_text(GOOD_PROMPT, encoding="utf-8")

        result = self.run_qc()

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        report = self.read_report()
        self.assertEqual(report["overall"], "PASS")

    def test_noncanonical_voice_and_sfx_delimiters_fail(self):
        noncanonical = (
            GOOD_PROMPT.replace(
                "声音：女主画面内同期口播{第一句。}。",
                "声音：女主画面内同期口播：“第一句。”",
            )
            .replace("音效：<轻微衣料摩擦声>", "音效：轻微衣料摩擦声。")
        )
        self.prompt_file.write_text(noncanonical, encoding="utf-8")

        result = self.run_qc()

        self.assertNotEqual(result.returncode, 0)
        failed = {
            check["name"]
            for check in self.read_report()["prompts"][0]["checks"]
            if check["status"] != "PASS"
        }
        self.assertIn("part1_canonical_voice_delimiters", failed)
        self.assertIn("part1_canonical_sfx_delimiters", failed)

    def test_indented_or_ascii_colon_sound_lines_cannot_bypass_format_qc(self):
        noncanonical = GOOD_PROMPT.replace(
            "声音：女主画面内同期口播{第一句。}。",
            "  声音：女主画面内同期口播：“第一句。”",
        ).replace(
            "音效：<轻微衣料摩擦声>",
            "  音效: 轻微衣料摩擦声",
        )
        self.prompt_file.write_text(noncanonical, encoding="utf-8")

        result = self.run_qc()

        self.assertNotEqual(result.returncode, 0)
        failed = {
            check["name"]
            for check in self.read_report()["prompts"][0]["checks"]
            if check["status"] != "PASS"
        }
        self.assertIn("part1_canonical_voice_delimiters", failed)
        self.assertIn("part1_canonical_sfx_delimiters", failed)

    def test_each_sound_effect_requires_its_own_angle_brackets(self):
        self.prompt_file.write_text(
            GOOD_PROMPT.replace(
                "音效：<手指滑动声>；<开盖和挑起质地的轻微操作声>",
                "音效：<手指滑动声；开盖和挑起质地的轻微操作声>",
            ),
            encoding="utf-8",
        )

        result = self.run_qc()

        self.assertNotEqual(result.returncode, 0)
        failed = {
            check["name"]
            for check in self.read_report()["prompts"][0]["checks"]
            if check["status"] != "PASS"
        }
        self.assertIn("part1_canonical_sfx_delimiters", failed)

    def test_prompt_outside_managed_output_paths_fails(self):
        manual_prompt = (
            self.root
            / "output/job-001/prompt-review/full-replica-v1/Part1_最终提示词.txt"
        )
        manual_prompt.parent.mkdir(parents=True)
        manual_prompt.write_text(GOOD_PROMPT, encoding="utf-8")

        result = self.run_qc([manual_prompt])

        self.assertNotEqual(result.returncode, 0)
        failed = {
            check["name"]
            for check in self.read_report()["checks"]
            if check["status"] != "PASS"
        }
        self.assertIn("prompt_files_are_managed_outputs", failed)
        report_md = (
            self.root
            / "output/job-001/checks/pre_seedance_pack_seedance_prompt_contract_qc.md"
        ).read_text(encoding="utf-8")
        self.assertIn("prompt_files_are_managed_outputs", report_md)
        self.assertIn("prompt-review/full-replica-v1", report_md)

    def test_managed_prompt_must_match_compiler_manifest(self):
        self.prompt_file.write_text(GOOD_PROMPT, encoding="utf-8")
        manifest_path = (
            self.root
            / "output/job-001/seedance/part_compilation_manifest.json"
        )
        manifest_path.write_text(
            json.dumps(
                {
                    "job_id": "job-001",
                    "director_plan_sha256": hashlib.sha256(
                        (
                            self.root
                            / "output/job-001/seedance/director_plan.json"
                        ).read_bytes()
                    ).hexdigest(),
                    "parts": [
                        {
                            "part_id": "part1",
                            "files": [
                                {
                                    "path": "seedance/seedance_part1_prompt.txt",
                                    "sha256": hashlib.sha256(
                                        GOOD_PROMPT.encode("utf-8")
                                    ).hexdigest(),
                                }
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.prompt_file.write_text(
            GOOD_PROMPT.replace("第一句。", "第一句被手工改过。"),
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                "python3",
                str(SCRIPT),
                "--root",
                str(self.root),
                "--job-id",
                "job-001",
                "--prompt-files",
                str(self.prompt_file),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        failed = {
            check["name"]
            for check in self.read_report()["checks"]
            if check["status"] != "PASS"
        }
        self.assertIn("prompt_files_match_compilation_manifest", failed)

    def test_compiler_manifest_must_bind_current_director_plan(self):
        self.prompt_file.write_text(GOOD_PROMPT, encoding="utf-8")
        plan_path = self.root / "output/job-001/seedance/director_plan.json"
        manifest_path = (
            self.root
            / "output/job-001/seedance/part_compilation_manifest.json"
        )
        manifest_path.write_text(
            json.dumps(
                {
                    "job_id": "job-001",
                    "director_plan_sha256": hashlib.sha256(
                        plan_path.read_bytes()
                    ).hexdigest(),
                    "parts": [
                        {
                            "part_id": "part1",
                            "files": [
                                {
                                    "path": "seedance/seedance_part1_prompt.txt",
                                    "sha256": hashlib.sha256(
                                        GOOD_PROMPT.encode("utf-8")
                                    ).hexdigest(),
                                }
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["revision_probe"] = "changed after compilation"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")

        result = subprocess.run(
            [
                "python3",
                str(SCRIPT),
                "--root",
                str(self.root),
                "--job-id",
                "job-001",
                "--prompt-files",
                str(self.prompt_file),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        failed = {
            check["name"]
            for check in self.read_report()["checks"]
            if check["status"] != "PASS"
        }
        self.assertIn("prompt_files_match_compilation_manifest", failed)

    def test_part1_prompt_cannot_reuse_part2_compiler_binding(self):
        self.prompt_file.write_text(GOOD_PROMPT, encoding="utf-8")
        plan_path = self.root / "output/job-001/seedance/director_plan.json"
        manifest_path = (
            self.root
            / "output/job-001/seedance/part_compilation_manifest.json"
        )
        manifest_path.write_text(
            json.dumps(
                {
                    "job_id": "job-001",
                    "director_plan_sha256": hashlib.sha256(
                        plan_path.read_bytes()
                    ).hexdigest(),
                    "parts": [
                        {
                            "part_id": "part2",
                            "files": [
                                {
                                    "path": "seedance/seedance_part2_prompt.txt",
                                    "sha256": hashlib.sha256(
                                        GOOD_PROMPT.encode("utf-8")
                                    ).hexdigest(),
                                }
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                "python3",
                str(SCRIPT),
                "--root",
                str(self.root),
                "--job-id",
                "job-001",
                "--prompt-files",
                str(self.prompt_file),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        failed = {
            check["name"]
            for check in self.read_report()["checks"]
            if check["status"] != "PASS"
        }
        self.assertIn("prompt_files_match_compilation_manifest", failed)

    def test_v5_plan_rejects_free_form_calibration_preamble(self):
        plan_path = self.root / "output/job-001/seedance/director_plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["version"] = 5
        plan_path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.prompt_file.write_text(GOOD_PROMPT, encoding="utf-8")

        result = self.run_qc()

        self.assertNotEqual(result.returncode, 0)
        failed = {
            check["name"]
            for check in self.read_report()["prompts"][0]["checks"]
            if check["status"] != "PASS"
        }
        self.assertIn("part1_standard_reference_preamble", failed)

    def test_named_product_binding_passes_without_repeating_calibration_phrase(self):
        compact_prompt = GOOD_PROMPT.replace(
            "@图片1 只控制镜头顺序、景别、人物动作、产品出现节奏；不要复制分镜网格、边框、编号和任何画面文字。",
            "@图片1定义为“分镜板”，控制镜头顺序、景别、人物动作和产品出现节奏；成片不显示分镜网格和编号。",
        ).replace(
            "@图片2 只校准目标产品的正面包装身份和标签文字；镜头构图、手部动作和产品出现节奏仍以@图片1为准。",
            "@图片2中的产品定义为“目标产品”，锁定正面包装和标签文字；不控制镜头构图和动作。",
        ).replace("只校准开盖质地", "锁定开盖质地")
        self.prompt_file.write_text(compact_prompt, encoding="utf-8")

        result = self.run_qc()

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_male_presenter_prompt_rejects_female_lead_terms(self):
        plan_path = self.root / "output/job-001/seedance/director_plan.json"
        plan_path.write_text(
            json.dumps(
                {"presenter_gender": {"source": "male", "target": "male"}},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        self.prompt_file.write_text(GOOD_PROMPT, encoding="utf-8")

        result = self.run_qc()

        self.assertNotEqual(result.returncode, 0)
        failed = {
            check["name"]
            for check in self.read_report()["prompts"][0]["checks"]
            if check["status"] != "PASS"
        }
        self.assertIn("part1_presenter_gender_consistent", failed)

    def test_female_presenter_prompt_rejects_male_lead_terms(self):
        self.prompt_file.write_text(GOOD_PROMPT.replace("女主", "男主播"), encoding="utf-8")

        result = self.run_qc()

        self.assertNotEqual(result.returncode, 0)
        failed = {
            check["name"]
            for check in self.read_report()["prompts"][0]["checks"]
            if check["status"] != "PASS"
        }
        self.assertIn("part1_presenter_gender_consistent", failed)

    def test_split_audio_execution_fails(self):
        split_prompt = GOOD_PROMPT + "\n声音执行：另行安排台词。\n"
        self.prompt_file.write_text(split_prompt, encoding="utf-8")

        result = self.run_qc()

        self.assertNotEqual(result.returncode, 0)
        failed = {
            check["name"]
            for check in self.read_report()["prompts"][0]["checks"]
            if check["status"] != "PASS"
        }
        self.assertIn("part1_no_split_audio_execution", failed)

    def test_execution_block_may_omit_sound_effect(self):
        missing_sfx = GOOD_PROMPT.replace("音效：<轻微衣料摩擦声>", "")
        self.prompt_file.write_text(missing_sfx, encoding="utf-8")

        result = self.run_qc()

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_placeholder_no_sound_effect_line_fails(self):
        placeholder_sfx = GOOD_PROMPT.replace("音效：<轻微衣料摩擦声>", "音效：无")
        self.prompt_file.write_text(placeholder_sfx, encoding="utf-8")

        result = self.run_qc()

        self.assertNotEqual(result.returncode, 0)
        failed = {
            check["name"]
            for check in self.read_report()["prompts"][0]["checks"]
            if check["status"] != "PASS"
        }
        self.assertIn("part1_omits_empty_sound_effect_lines", failed)

    def test_execution_block_cannot_cover_more_than_five_storyboard_panels(self):
        too_broad = GOOD_PROMPT.replace(
            "1.5–7.0秒｜Shot 02–04",
            "1.5–7.0秒｜Shot 02–08",
        ).replace(
            "7.0–10.0秒｜Shot 05",
            "7.0–10.0秒｜Shot 09",
        ).replace(
            "10.0–15.0秒｜Shot 06",
            "10.0–15.0秒｜Shot 10–12",
        )
        self.prompt_file.write_text(too_broad, encoding="utf-8")

        result = self.run_qc()

        self.assertNotEqual(result.returncode, 0)
        failed = {
            check["name"]
            for check in self.read_report()["prompts"][0]["checks"]
            if check["status"] != "PASS"
        }
        self.assertIn("part1_execution_block_scope", failed)

    def test_global_rules_must_stay_compact(self):
        bloated = GOOD_PROMPT.replace(
            "生成约15秒、9:16竖屏、720p真实护肤测评短视频。",
            "生成约15秒、9:16竖屏、720p真实护肤测评短视频。" + "保持真实自然的手机拍摄质感。" * 12,
        )
        self.prompt_file.write_text(bloated, encoding="utf-8")

        result = self.run_qc()

        self.assertNotEqual(result.returncode, 0)
        failed = {
            check["name"]
            for check in self.read_report()["prompts"][0]["checks"]
            if check["status"] != "PASS"
        }
        self.assertIn("part1_compact_global_rules", failed)

    def test_spoken_product_anchor_allows_source_repeated_brand_mention(self):
        repeated_product = GOOD_PROMPT.replace(
            "第二句，覆盖产品、手机和质地证明。",
            "第一句，第二句，覆盖产品、手机和质地证明。",
        )
        repeated_map = SHOT_LINE_MAP.replace(
            "第二句，覆盖产品、手机和质地证明。",
            "第一句，第二句，覆盖产品、手机和质地证明。",
        )
        (self.root / "output/job-001/voiceover/shot_line_map.md").write_text(
            repeated_map,
            encoding="utf-8",
        )
        self.prompt_file.write_text(repeated_product, encoding="utf-8")

        result = self.run_qc()

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_disabled_product_anchor_does_not_inject_a_new_product_mention(self):
        self.assertIsNone(
            check_spoken_product_anchor(
                {"enabled": False},
                {1: GOOD_PROMPT},
            )
        )

    def test_execution_blocks_must_stay_in_time_order(self):
        out_of_order = GOOD_PROMPT.replace(
            "7.0–10.0秒｜Shot 05",
            "7.5–10.0秒｜Shot 05",
        )
        self.prompt_file.write_text(out_of_order, encoding="utf-8")

        result = self.run_qc()

        self.assertNotEqual(result.returncode, 0)
        failed = {
            check["name"]
            for check in self.read_report()["prompts"][0]["checks"]
            if check["status"] != "PASS"
        }
        self.assertIn("part1_ordered_continuous_execution", failed)

    def test_broad_three_shot_summary_fails(self):
        self.prompt_file.write_text(BROAD_PROMPT, encoding="utf-8")

        result = self.run_qc()

        self.assertNotEqual(result.returncode, 0)
        report = self.read_report()
        self.assertEqual(report["overall"], "FAIL")
        checks = report["prompts"][0]["checks"]
        failed = {check["name"]: check for check in checks if check["status"] != "PASS"}
        self.assertIn("part1_covers_shot_line_map_times", failed)
        self.assertIn("part1_variable_time_axis", failed)

    def test_source_to_target_speaker_mode_mismatch_fails(self):
        (self.root / "output/job-001/voiceover/shot_line_map.md").write_text(
            MISMATCHED_SHOT_LINE_MAP,
            encoding="utf-8",
        )
        mismatched_prompt = GOOD_PROMPT.replace(
            '女主画外音旁白：“第二句，覆盖产品、手机和质地证明。”',
            '女主画面内同期口播：“第二句，覆盖产品、手机和质地证明。”',
        )
        self.prompt_file.write_text(mismatched_prompt, encoding="utf-8")

        result = self.run_qc()

        self.assertNotEqual(result.returncode, 0)
        report = self.read_report()
        self.assertEqual(report["overall"], "FAIL")
        checks = report["prompts"][0]["checks"]
        failed = {check["name"]: check for check in checks if check["status"] != "PASS"}
        self.assertIn("part1_preserves_source_speaker_modes", failed)

    def test_execution_block_cannot_cross_speaker_mode_boundary(self):
        mixed_mode_map = SHOT_LINE_MAP.replace(
            "speech2 | 1.5-7.0s |",
            "speech2 | 1.5-5.0s |",
            1,
        ).replace(
            '女主画外音旁白：“原第四句。” | Open jar proof. | speech2 |  | '
            '女主画外音旁白（speech2承接，无新增台词）',
            '女主画面内同期口播：“原第四句。” | Open jar proof. | speech4 | 5.0-7.0s | '
            '女主画面内同期口播：“第四句。”',
        )
        (self.root / "output/job-001/voiceover/shot_line_map.md").write_text(
            mixed_mode_map,
            encoding="utf-8",
        )
        self.prompt_file.write_text(GOOD_PROMPT, encoding="utf-8")

        result = self.run_qc()

        self.assertNotEqual(result.returncode, 0)
        failed = {
            check["name"]
            for check in self.read_report()["prompts"][0]["checks"]
            if check["status"] != "PASS"
        }
        self.assertIn("part1_execution_blocks_respect_speaker_mode_boundaries", failed)

    def test_kongfengchun_prompt_cannot_weaken_afterwash_result(self):
        plan_path = self.root / "output/job-001/seedance/director_plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["job"] = {"product_name": "孔凤春清洁泥膜"}
        plan_path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        weakened_prompt = GOOD_PROMPT.replace(
            "洗后脸证明，镜头轻微推进",
            "洗后油光减少，保留真实毛孔和皮肤纹理",
        )
        self.prompt_file.write_text(weakened_prompt, encoding="utf-8")

        result = self.run_qc()

        self.assertNotEqual(result.returncode, 0)
        failed = {
            check["name"]
            for check in self.read_report()["prompts"][0]["checks"]
            if check["status"] != "PASS"
        }
        self.assertIn("part1_profile_effect_not_weakened", failed)

    def test_prompt_speaker_mode_must_match_target_map(self):
        prompt_mismatch = GOOD_PROMPT.replace(
            "旁白{第二句，覆盖产品、手机和质地证明。}",
            "女主画面内同期口播{第二句，覆盖产品、手机和质地证明。}",
        )
        self.prompt_file.write_text(prompt_mismatch, encoding="utf-8")

        result = self.run_qc()

        self.assertNotEqual(result.returncode, 0)
        report = self.read_report()
        self.assertEqual(report["overall"], "FAIL")
        checks = report["prompts"][0]["checks"]
        failed = {check["name"]: check for check in checks if check["status"] != "PASS"}
        self.assertIn("part1_prompt_matches_target_speaker_modes", failed)

    def test_prompt_cannot_add_an_unmapped_spoken_line(self):
        prompt_with_extra_line = GOOD_PROMPT.replace(
            "声音：旁白{第二句，覆盖产品、手机和质地证明。}。",
            "声音：旁白{第二句，覆盖产品、手机和质地证明。}；旁白{偷偷多说一句。}。",
        )
        self.prompt_file.write_text(prompt_with_extra_line, encoding="utf-8")

        result = self.run_qc()

        self.assertNotEqual(result.returncode, 0)
        report = self.read_report()
        checks = report["prompts"][0]["checks"]
        failed = {check["name"]: check for check in checks if check["status"] != "PASS"}
        self.assertIn("part1_prompt_has_exact_speech_lines", failed)

    def test_prompt_cannot_reference_unprovided_source_video_context(self):
        polluted_prompt = GOOD_PROMPT.replace(
            "画面：女主近脸看镜头，手部轻微移动。",
            "画面：按原片节奏，女主近脸看镜头，按分镜手位轻微移动。",
        )
        self.prompt_file.write_text(polluted_prompt, encoding="utf-8")

        result = self.run_qc()

        self.assertNotEqual(result.returncode, 0)
        failed = {
            check["name"]
            for check in self.read_report()["prompts"][0]["checks"]
            if check["status"] != "PASS"
        }
        self.assertIn("part1_no_unbound_source_context", failed)

    def test_prompt_rejects_negative_references_to_objects_already_removed_from_storyboard(self):
        polluted_prompt = GOOD_PROMPT.replace(
            "画面：女主近脸看镜头，手部轻微移动。",
            "画面：女主近脸看镜头，手部轻微移动，前景保持干净无产品。",
        )
        self.prompt_file.write_text(polluted_prompt, encoding="utf-8")

        result = self.run_qc()

        self.assertNotEqual(result.returncode, 0)
        failed = {
            check["name"]
            for check in self.read_report()["prompts"][0]["checks"]
            if check["status"] != "PASS"
        }
        self.assertIn("part1_no_resolved_object_negative_prompts", failed)

    def test_visible_product_text_is_not_counted_as_dialogue(self):
        prompt_with_label = GOOD_PROMPT.replace(
            "随后产品自然落位收口",
            "随后产品自然落位收口，瓶身可见“52%马齿苋”",
        )
        self.prompt_file.write_text(prompt_with_label, encoding="utf-8")

        result = self.run_qc()

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_legacy_shot_line_map_without_source_speaker_modes_fails(self):
        (self.root / "output/job-001/voiceover/shot_line_map.md").write_text(
            LEGACY_SHOT_LINE_MAP,
            encoding="utf-8",
        )
        self.prompt_file.write_text(GOOD_PROMPT, encoding="utf-8")

        result = self.run_qc()

        self.assertNotEqual(result.returncode, 0)
        report = self.read_report()
        self.assertEqual(report["overall"], "FAIL")
        checks = report["prompts"][0]["checks"]
        failed = {check["name"]: check for check in checks if check["status"] != "PASS"}
        self.assertIn("part1_source_speaker_modes_present", failed)


if __name__ == "__main__":
    unittest.main()
