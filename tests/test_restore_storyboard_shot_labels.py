import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "restore_storyboard_shot_labels.py"


class RestoreStoryboardShotLabelsTest(unittest.TestCase):
    def test_relabels_navigation_bars_without_changing_panel_pixels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "candidate.png"
            output = root / "restored.png"
            evidence = root / "evidence.json"

            image = Image.new("RGB", (400, 600), (90, 70, 50))
            draw = ImageDraw.Draw(image)
            # Image models may retain a title/header, so label rows need not
            # land inside exact equal-height thirds.
            label_bands = [(210, 225), (405, 420), (585, 600)]
            for row, (top, bottom) in enumerate(label_bands):
                draw.rectangle((0, top, 399, bottom - 1), fill=(38, 38, 38))
                for col in range(4):
                    draw.text((col * 100 + 8, top + 2), "Shot 04", fill=(0, 190, 255))
            image.save(source)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--evidence",
                    str(evidence),
                    "--cols",
                    "4",
                    "--rows",
                    "3",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            before = Image.open(source).convert("RGB")
            after = Image.open(output).convert("RGB")
            for y in range(before.height):
                if any(top <= y < bottom for top, bottom in label_bands):
                    continue
                for x in range(before.width):
                    self.assertEqual(before.getpixel((x, y)), after.getpixel((x, y)))

            report = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["labels"], [f"Shot {index:02d}" for index in range(1, 13)])
            self.assertEqual(report["label_bands"], [[210, 225], [405, 420], [585, 600]])
            self.assertEqual(report["outside_label_changed_pixels"], 0)
            self.assertFalse(report["panel_pixels_modified"])
            self.assertTrue(report["panel_content_sha256_before"])
            self.assertEqual(
                report["panel_content_sha256_before"],
                report["panel_content_sha256_after"],
            )

    def test_uses_label_template_when_terminal_bar_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "candidate.png"
            template = root / "label_template.png"
            output = root / "restored.png"
            evidence = root / "evidence.json"

            template_image = Image.new("RGB", (400, 600), (90, 70, 50))
            template_draw = ImageDraw.Draw(template_image)
            template_bands = [(210, 225), (405, 420), (585, 600)]
            for top, bottom in template_bands:
                template_draw.rectangle((0, top, 399, bottom - 1), fill=(38, 38, 38))
                template_draw.text((8, top + 2), "Shot XX", fill=(0, 190, 255))
            template_image.save(template)

            candidate = Image.new("RGB", (400, 600), (90, 70, 50))
            candidate_draw = ImageDraw.Draw(candidate)
            # The image model shifted the middle navigation band and omitted
            # the terminal band entirely. The template is authoritative only
            # for the missing metadata row; panel pixels remain untouched.
            candidate_bands = [(210, 225), (430, 445)]
            for top, bottom in candidate_bands:
                candidate_draw.rectangle((0, top, 399, bottom - 1), fill=(38, 38, 38))
                candidate_draw.text((8, top + 2), "Shot XX", fill=(0, 190, 255))
            candidate.save(source)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--evidence",
                    str(evidence),
                    "--label-template",
                    str(template),
                    "--cols",
                    "4",
                    "--rows",
                    "3",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            before = Image.open(source).convert("RGB")
            after = Image.open(output).convert("RGB")
            resolved_bands = candidate_bands + [template_bands[-1]]
            for y in range(before.height):
                if any(top <= y < bottom for top, bottom in resolved_bands):
                    continue
                for x in range(before.width):
                    self.assertEqual(before.getpixel((x, y)), after.getpixel((x, y)))

            report = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["label_bands"], [[210, 225], [430, 445], [585, 600]])
            self.assertEqual(report["label_band_sources"], ["candidate", "candidate", "template"])
            self.assertEqual(report["outside_label_changed_pixels"], 0)
            self.assertFalse(report["panel_pixels_modified"])
            self.assertEqual(
                report["panel_content_sha256_before"],
                report["panel_content_sha256_after"],
            )


if __name__ == "__main__":
    unittest.main()
