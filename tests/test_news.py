import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from generate_news import (
    Item, deduplicate, postprocess_chinese, select_for_translation,
    select_section, summary_source, translate_batch,
)
from news_common import chinese_dominant, validate_html


class NewsGenerationTest(unittest.TestCase):
    def make_item(self, number, source="Example", category="ai", title=None):
        return Item(
            title or f"Company{number} unveils Codename{number} semiconductor project in Region{number}",
            f"https://example.com/{number}", source,
            datetime(2026, 9, 21, number % 20, tzinfo=timezone.utc),
            f"Distinct report {number} describes an artificial intelligence launch and agreement.",
            category,
        )

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

    def test_each_topic_accepts_zero_through_ten_and_caps_large_pool(self):
        self.assertEqual(select_section([], "ai"), [])
        ten = [self.make_item(i) for i in range(10)]
        self.assertEqual(len(select_section(ten, "ai")), 10)
        large = [self.make_item(i) for i in range(50)]
        selected = select_for_translation(large)
        self.assertLessEqual(len(selected), 10)

    def test_similar_events_do_not_consume_multiple_slots(self):
        duplicates = [
            self.make_item(i, title=f"Ukraine allies announce air defence support package {word}")
            for i, word in enumerate(("today", "again", "now", "latest"))
        ]
        merged = deduplicate(duplicates)
        self.assertEqual(len(merged), 1)
        selected = select_section(duplicates, "ukraine")
        self.assertEqual(len(selected), 1)

    def test_selection_rewards_source_diversity(self):
        pool = [self.make_item(i, source="Reuters") for i in range(12)]
        pool += [self.make_item(20 + i, source=f"Local {i}") for i in range(4)]
        chosen = select_section(pool, "ai")
        self.assertEqual(len(chosen), 10)
        self.assertLess(sum(item.source == "Reuters" for item in chosen), 10)

    def test_selection_occurs_before_translation(self):
        items = [self.make_item(i) for i in range(30)]
        selected = select_for_translation(items)
        calls = []

        def translate(value):
            calls.append(value)
            return "OpenAI发布AI模型" if "unveils" in value else "这是一项人工智能发布协议。"

        translate_batch(selected, translator=translate)
        self.assertEqual(len(selected), 10)
        self.assertEqual(len(calls), 20)

    def test_chinese_postprocessing_is_conservative(self):
        raw = '“OpenAI发布AI模型, 价格为100美元。” “OpenAI发布AI模型, 价格为100美元。” - Reuters'
        cleaned = postprocess_chinese(raw)
        self.assertEqual(cleaned.count("100"), 1)
        self.assertEqual(cleaned.count("OpenAI发布AI模型"), 1)
        self.assertNotIn("Reuters", cleaned)
        item = self.make_item(1, source="Reuters")
        original_url, original_source = item.url, item.source
        postprocess_chinese(raw)
        self.assertEqual((item.url, item.source), (original_url, original_source))
        factual = "BBC报道：OpenAI在2026年发布更新，详情见https://example.com/a?x=1。"
        factual_cleaned = postprocess_chinese(factual)
        self.assertIn("2026", factual_cleaned)
        self.assertIn("https://example.com/a?x=1", factual_cleaned)

    def test_validator_rejects_eleventh_item_in_section(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "too-many.html"
            cards = ''.join(
                f'<article class="card"><h3>中文标题{i}</h3><p>这是中文摘要。</p>'
                f'<div class="src"><a href="https://example.com/{i}">Reuters</a></div></article>'
                for i in range(11)
            )
            output.write_text(
                '<title>私人 AI 新闻简报｜2026-09-21</title>ENGLISH SOURCES'
                + ''.join(
                    f'<section id="{name}">{cards if name == "ai" else ""}</section>'
                    for name in ("must", "ukraine", "middleeast", "migration", "ai", "robots", "energy", "other")
                ), encoding="utf-8",
            )
            errors = validate_html(output, "2026-09-21")
            self.assertIn("section #ai contains 11 events; maximum is 10", errors)

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
        self.assertNotIn("scripts/setup_translation.py", workflow)
        self.assertIn("google-github-actions/auth@v2", workflow)
        self.assertIn("workload_identity_provider:", workflow)
        self.assertIn("service_account:", workflow)

    def test_validator_rejects_reused_source_url_and_incorrect_event_count(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "duplicates.html"
            sections = []
            for name in ("must", "ukraine", "middleeast", "migration", "ai", "robots", "energy", "other"):
                cards = ""
                if name in ("must", "ai"):
                    cards = (
                        f'<article class="card"><h3>{"重要事件" if name == "must" else "同一事件后续"}</h3>'
                        '<p>这是经过翻译的中文摘要。</p><div class="src">'
                        '<a href="https://example.com/same-story">Example</a></div></article>'
                    )
                sections.append(f'<section id="{name}">{cards}</section>')
            output.write_text(
                '<title>私人 AI 新闻简报｜2026-09-24</title>ENGLISH SOURCES'
                '<span class="pill">1 件独立事件</span>' + "".join(sections),
                encoding="utf-8",
            )
            errors = validate_html(output, "2026-09-24")
            self.assertTrue(any("reuses external source URLs" in error for error in errors))
            self.assertIn("brief declares 1 independent events but contains 2 event cards", errors)

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
