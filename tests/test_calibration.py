import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from generate_news import Item, category_for, globally_significant, selection_eligible


class CalibrationTest(unittest.TestCase):
    def item(self, title, summary="", category="other", source="Reuters"):
        return Item(title, "https://example.com/story", source, datetime(2026, 9, 24, tzinfo=timezone.utc), summary, category)

    def test_important_signal_survives_translation(self):
        item = self.item("俄罗斯无人机袭击基辅", "中文摘要", "ukraine")
        item.original_title = "Russian drone attack strikes Kyiv"
        item.original_summary = "Ukraine reports a major military attack."
        self.assertTrue(globally_significant(item))

    def test_broad_live_blog_does_not_jump_to_ukraine_from_summary(self):
        item = self.item(
            "Venezuela at UN; Trump meets Xi ahead of summit — live",
            "Latest Russian attack came before Zelensky addressed the UN.",
        )
        self.assertEqual(category_for(item, "other"), "other")

    def test_headline_can_classify_ukraine(self):
        item = self.item(
            "Russian drone attack hits Kyiv before Zelensky UN speech",
            "World leaders meet in New York.",
        )
        self.assertEqual(category_for(item, "other"), "ukraine")

    def test_energy_core_relevance_does_not_need_second_popularity_gate(self):
        item = self.item(
            "New geothermal project deploys grid technology",
            "Commercial geothermal plant adds renewable capacity.",
            "energy",
            "Energy Monitor",
        )
        self.assertTrue(selection_eligible(item, "energy"))


if __name__ == "__main__":
    unittest.main()
