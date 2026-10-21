from datetime import timedelta
import unittest

import test_presents
from presents import affection_display, PresentStore
from database import MemoryUnavailable


class LinkLevelTests(unittest.TestCase):
    setUp = test_presents.StorageTests.setUp
    set_favorite = test_presents.StorageTests.set_favorite

    def prepare(self, points=100):
        self.store.snapshot(42)
        self.db.execute("INSERT INTO george_affection VALUES (42,'ロザリー',?)", (points,))
        self.db.execute("INSERT INTO george_present_items VALUES (42,'magic',20)")
        self.db.execute("INSERT INTO george_present_items VALUES (42,'rare',3)")
        self.db.commit()

    def test_stages_require_gift_at_boundary_and_keep_first_date(self):
        self.prepare(99)
        self.assertEqual(self.store.give(42, 100, 'ロザリー', 'magic'), (1, 100, 0))
        self.assertEqual(self.store.give(42, 101, 'ロザリー', 'magic'), (0, 100, 1))
        first = self.store.album(42, 'ロザリー')[3]
        self.assertIn('100/200', affection_display(100, 1))
        self.db.execute("UPDATE george_affection SET points=199 WHERE user_id=42")
        self.db.commit()
        self.assertEqual(self.store.give(42, 102, 'ロザリー', 'magic'), (1, 200, 1))
        self.assertEqual(self.store.give(42, 103, 'ロザリー', 'rare'), (0, 200, 1))
        self.assertEqual(self.store.give(42, 104, 'ロザリー', 'magic'), (0, 200, 2))
        self.assertIn('パーフェクトリンクⅡ', affection_display(200, 2))
        self.assertIn('200/300', affection_display(200, 2))
        self.db.execute("UPDATE george_affection SET points=300 WHERE user_id=42")
        self.db.commit()
        self.assertEqual(self.store.give(42, 105, 'ロザリー', 'magic'), (0, 300, 3))
        self.assertEqual(self.store.give(42, 106, 'ロザリー', 'rare'), (10, 310, 3))
        self.assertEqual(self.store.album(42, 'ロザリー')[3], first)
        self.assertEqual(PresentStore('unused').affection_status(42, 'ロザリー'), (310, 3))
        self.set_favorite('美海')
        self.assertEqual(self.store.affection_status(42, 'ロザリー'), (310, 3))

    def test_legacy_perfect_links_unlock_next_cap_and_daily_stops_at_new_boundary(self):
        self.prepare()
        self.db.execute("INSERT INTO george_perfect_links VALUES (42,'ロザリー','2026-10-01T00:00:00+00:00')")
        self.db.commit()
        self.assertEqual(self.store.affection_status(42, 'ロザリー'), (100, 1))
        self.day += timedelta(days=150)
        self.assertEqual(self.store.affection_status(42, 'ロザリー'), (200, 1))
        self.assertEqual(self.store.give(42, 100, 'ロザリー', 'magic'), (0, 200, 2))
        self.day += timedelta(days=1)
        self.assertEqual(self.store.affection_status(42, 'ロザリー'), (201, 2))
        self.assertEqual(self.store.album(42, 'ロザリー')[3].day, 1)

    def test_stage_failure_rolls_back_inventory_and_first_link_together(self):
        self.prepare()
        self.fail_on = 'INSERT INTO george_perfect_link_levels'
        with self.assertRaises(MemoryUnavailable):
            self.store.give(42, 100, 'ロザリー', 'magic')
        self.fail_on = None
        self.assertEqual(self.store.affection_status(42, 'ロザリー'), (100, 0))
        self.assertEqual(self.store.inventory(42)['magic'], 20)
        self.assertIsNone(self.store.album(42, 'ロザリー')[3])

    def test_old_receipt_does_not_reconsume_or_regress_points_and_level(self):
        self.prepare()
        self.store.give(42, 100, 'ロザリー', 'magic')
        self.store.give(42, 101, 'ロザリー', 'magic')
        self.assertEqual(self.store.give(42, 100, 'ロザリー', 'magic'), (0, 105, 1))
        self.assertEqual(self.store.inventory(42)['magic'], 18)
        self.assertEqual(self.store.inventory(42)['rare'], 3)
