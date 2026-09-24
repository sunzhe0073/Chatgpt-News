import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from generate_news import Item, low_quality_item, protect_proper_nouns, restore_proper_nouns, select_section, topic_eligible


class QualityGuardTest(unittest.TestCase):
    def item(self, title, source="Example", category="ai", summary="Routine update."):
        return Item(title, "https://example.com/story", source, datetime(2026, 9, 24, tzinfo=timezone.utc), summary, category)

    def test_market_pr_is_rejected(self):
        item = self.item("Humanoid robot market size projected to reach 40 billion", "openPR.com", "robots")
        self.assertTrue(low_quality_item(item))
        self.assertFalse(topic_eligible(item, "robots"))

    def test_robot_and_energy_need_core_relevance(self):
        self.assertFalse(topic_eligible(self.item("MEMS sensor market forecast expands with automation demand", category="robots"), "robots"))
        self.assertTrue(topic_eligible(self.item("Unitree deploys humanoid robots for autonomous factory work", category="robots"), "robots"))
        self.assertFalse(topic_eligible(self.item("Ranking the world's most indebted countries", category="energy"), "energy"))
        self.assertTrue(topic_eligible(self.item("New battery storage technology enters commercial grid deployment", category="energy"), "energy"))

    def test_other_requires_major_trusted_story(self):
        self.assertFalse(topic_eligible(self.item("Local council discusses weekend parking rules", "Local Daily", "other"), "other"))
        self.assertTrue(topic_eligible(self.item("Government declares emergency after major international crisis", "Reuters", "other"), "other"))

    def test_proper_nouns_round_trip(self):
        original = "OpenAI and Anthropic discuss NVIDIA systems with Google"
        protected, mapping = protect_proper_nouns(original)
        self.assertNotIn("Anthropic", protected)
        self.assertEqual(restore_proper_nouns(protected, mapping), original)
        self.assertEqual(restore_proper_nouns("Anthropologie发布更新", {}), "Anthropic发布更新")

    def test_weak_tail_is_not_used_to_fill_section(self):
        strong = self.item("OpenAI launches artificial intelligence model after major agreement", "Reuters", "ai", "OpenAI artificial intelligence launch agreement.")
        weak = self.item("Company mentions AI in a routine update", "Example", "ai", "Routine company update.")
        chosen = select_section([strong, weak], "ai")
        self.assertIn(strong, chosen)
        self.assertNotIn(weak, chosen)


if __name__ == "__main__":
    unittest.main()
