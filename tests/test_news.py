import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class NewsGenerationTest(unittest.TestCase):
    def test_fixture_generation_and_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "brief.html"
            subprocess.run([
                "python3", "scripts/generate_news.py", "--date", "2026-09-21",
                "--fixture", str((ROOT / "tests/fixtures/news.xml").resolve()),
                "--translation-fixture", str((ROOT / "tests/fixtures/translations.json").resolve()),
                "--output", str(output)
            ], cwd=ROOT, check=True)
            text = output.read_text(encoding="utf-8")
            self.assertEqual(text.count("<h3>乌克兰盟友宣布提供新的防空支持</h3>"), 1)
            self.assertNotIn("<h3>Ukraine allies", text)
            self.assertIn("来源：<a href=", text)
            self.assertIn("私人 AI 新闻简报｜2026-09-21", text)
            subprocess.run(["python3", "scripts/validate_news.py", str(output), "--date", "2026-09-21"], cwd=ROOT, check=True)

    def test_validator_rejects_english_editorial_content(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "brief.html"
            subprocess.run([
                "python3", "scripts/generate_news.py", "--date", "2026-09-21",
                "--fixture", str((ROOT / "tests/fixtures/news.xml").resolve()),
                "--translation-fixture", str((ROOT / "tests/fixtures/translations.json").resolve()),
                "--output", str(output)
            ], cwd=ROOT, check=True)
            text = output.read_text(encoding="utf-8").replace(
                "乌克兰盟友宣布提供新的防空支持", "Ukraine allies announce new air defence support"
            ).replace(
                "欧洲盟友在基辅会谈后宣布新的援助方案，重点补充乌克兰防空能力。相关支持可能影响其应对空袭的能力，具体交付安排仍有待公布。",
                "European allies announced a new package after talks in Kyiv. This is an English summary."
            )
            output.write_text(text, encoding="utf-8")
            result = subprocess.run([
                "python3", "scripts/validate_news.py", str(output), "--date", "2026-09-21"
            ], cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not Chinese-dominant", result.stderr)


if __name__ == "__main__":
    unittest.main()
