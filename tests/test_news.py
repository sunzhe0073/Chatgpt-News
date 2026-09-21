import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from generate_news import Item, summary_source, translate_batch
from news_common import chinese_dominant, validate_html


class NewsGenerationTest(unittest.TestCase):
    def test_chinese_with_english_names_and_acronyms_is_accepted(self):
        self.assertTrue(chinese_dominant("Reuters报道，OpenAI与BBC讨论AI监管，NATO也回应了Trump的讲话。"))

    def test_genuinely_english_copy_is_rejected(self):
        self.assertFalse(chinese_dominant("Trump Announces New Tariffs After NATO Meeting"))
        self.assertFalse(chinese_dominant("突发：Global Markets Rally After Trump Announces New Tariffs"))

    def test_local_translation_uses_only_feed_text(self):
        item = Item(
            "A factual English headline", "https://example.com/news", "Example",
            datetime(2026, 9, 21, tzinfo=timezone.utc), "Publisher supplied facts.",
        )
        inputs = []

        def translate(value):
            inputs.append(value)
            return {item.title: "忠实的中文标题", item.summary: "出版方提供的事实。"}[value]

        translate_batch([item], translator=translate)
        self.assertEqual(inputs, ["A factual English headline", "Publisher supplied facts."])
        self.assertEqual(item.title, "忠实的中文标题")
        self.assertEqual(item.summary, "出版方提供的事实。")

    def test_missing_feed_summary_has_non_inventive_fallback(self):
        item = Item(
            "A factual English headline", "https://example.com/news", "Example",
            datetime(2026, 9, 21, tzinfo=timezone.utc), "",
        )
        self.assertEqual(
            summary_source(item),
            "The report says: A factual English headline. No additional summary was provided by the feed.",
        )

    def test_one_bad_translation_is_skipped_without_failing_batch(self):
        good = Item(
            "Good headline", "https://example.com/good", "Reuters",
            datetime(2026, 9, 21, tzinfo=timezone.utc), "Good description",
        )
        bad = Item(
            "Bad headline", "https://example.com/bad", "BBC",
            datetime(2026, 9, 21, tzinfo=timezone.utc), "Bad description",
        )
        translations = {
            "Good headline": "OpenAI发布新的AI模型",
            "Good description": "Reuters报道，新模型已经向开发者开放。",
            "Bad headline": "Bad headline remains in English",
            "Bad description": "This entire description remains untranslated English prose.",
        }

        items = [good, bad]
        warnings = translate_batch(items, translator=translations.__getitem__)

        self.assertEqual(items, [good])
        self.assertTrue(chinese_dominant(good.title))
        self.assertEqual(len(warnings), 1)
        self.assertIn('Translation skipped "Bad headline"', warnings[0])
        self.assertIn("CJK chars=0", warnings[0])

    def test_validator_reports_failed_text_and_character_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "bad.html"
            output.write_text(
                '<title>私人 AI 新闻简报｜2026-09-21</title>ENGLISH SOURCES'
                + ''.join(f'<section id="{name}"></section>' for name in (
                    "must", "ukraine", "middleeast", "migration", "ai", "robots", "energy", "other"
                ))
                + '<article class="card"><h3>Entirely English Headline Here</h3>'
                  '<p>This summary was not translated by the model.</p>'
                  '<div class="src"><a href="https://reuters.com/story">Reuters</a></div></article>',
                encoding="utf-8",
            )
            errors = validate_html(output, "2026-09-21")
            joined = "\n".join(errors)
            self.assertIn('news title is not Chinese-dominant: "Entirely English Headline Here"', joined)
            self.assertRegex(joined, r"CJK chars=0, Latin chars=\d+")

    def test_workflow_has_no_github_models_dependency(self):
        workflow = (ROOT / ".github/workflows/generate-daily-news.yml").read_text(encoding="utf-8")
        self.assertNotIn("models: read", workflow)
        self.assertNotIn("GITHUB_TOKEN:", workflow)
        self.assertIn("scripts/setup_translation.py", workflow)

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
