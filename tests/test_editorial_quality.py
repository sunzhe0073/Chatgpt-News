import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from generate_news import Item, globally_significant, low_quality_item, selection_eligible, topic_eligible, weak_syndication_item


class EditorialQualityTest(unittest.TestCase):
    def item(self, title, source="Reuters", category="other", summary=""):
        return Item(title, "https://example.com/story", source, datetime(2026, 9, 24, tzinfo=timezone.utc), summary, category)

    def test_local_crime_is_not_global_significance(self):
        item = self.item("Police reveal details in alleged murder of Sydney couple")
        self.assertFalse(globally_significant(item))
        self.assertFalse(topic_eligible(item, "other"))

    def test_major_international_crisis_remains_eligible(self):
        item = self.item("United Nations Security Council meets after international military crisis")
        self.assertTrue(globally_significant(item))
        self.assertTrue(topic_eligible(item, "other"))

    def test_investment_bait_is_filtered(self):
        item = self.item("This growth stock has an unbreakable moat in the AI supercycle", "Yahoo Finance", "ai")
        self.assertTrue(low_quality_item(item))
        self.assertFalse(selection_eligible(item, "ai"))

    def test_weak_syndication_needs_corroboration(self):
        item = self.item("Humanoid robot completes autonomous factory deployment", "Newsmax", "robots")
        self.assertTrue(weak_syndication_item(item))
        self.assertFalse(selection_eligible(item, "robots"))
        item.sources = [("Newsmax", item.url), ("Reuters", "https://reuters.example/robot")]
        self.assertTrue(selection_eligible(item, "robots"))


if __name__ == "__main__":
    unittest.main()
