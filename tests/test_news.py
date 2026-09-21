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
                "--fixture", str((ROOT / "tests/fixtures/news.xml").resolve()), "--output", str(output)
            ], cwd=ROOT, check=True)
            text = output.read_text(encoding="utf-8")
            self.assertEqual(text.count("<h3>Ukraine allies announce new air defence support</h3>"), 1)
            self.assertIn("私人 AI 新闻简报｜2026-09-21", text)
            subprocess.run(["python3", "scripts/validate_news.py", str(output), "--date", "2026-09-21"], cwd=ROOT, check=True)


if __name__ == "__main__":
    unittest.main()
