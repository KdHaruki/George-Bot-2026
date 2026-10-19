from datetime import timedelta
import unittest

from daily_affection import settle_daily, start_daily, seed_daily
import test_presents


class DailyAffectionTests(unittest.TestCase):
    setUp = test_presents.StorageTests.setUp
    set_favorite = test_presents.StorageTests.set_favorite

    def test_catchup_same_day_and_restart_do_not_duplicate(self):
        self.assertEqual(self.store.points(42, 'ロザリー'), 0)
        self.day += timedelta(days=4)
        self.assertEqual(self.store.points(42, 'ロザリー'), 4)
        self.assertEqual(self.store.points(42, 'ロザリー'), 4)
        from presents import PresentStore
        self.assertEqual(PresentStore('unused').points(42, 'ロザリー'), 4)
        self.day += timedelta(days=1)
        self.assertEqual(self.store.points(42, 'ロザリー'), 5)
        self.assertEqual(self.store.points(43, 'ロザリー'), 0)

    def test_cap_records_actual_crossing_day_without_perfect_link(self):
        self.store.points(42, 'ロザリー')
        self.db.execute("INSERT INTO george_affection VALUES (42,'ロザリー',98)")
        expected = self.day + timedelta(days=2)
        self.day += timedelta(days=10)
        self.assertEqual(self.store.affection_status(42, 'ロザリー'), (100, False))
        row = self.db.execute('SELECT first_gift_at,max_affection_at FROM george_favorite_album').fetchone()
        self.assertIsNone(row[0])
        self.assertEqual(row[1], expected.isoformat() + 'T00:00:00+09:00')
        self.day += timedelta(days=5)
        self.assertEqual(self.store.points(42, 'ロザリー'), 100)
        self.assertEqual(self.db.execute('SELECT max_affection_at FROM george_favorite_album').fetchone()[0], row[1])

    def test_same_person_continues_switch_and_clear_stop_old_accrual(self):
        with self.store.connect() as conn:
            start_daily(conn, 42, 'ロザリー')
        self.day += timedelta(days=2)
        with self.store.connect() as conn:
            start_daily(conn, 42, 'ロザリー')
            self.assertEqual(settle_daily(conn, 42), 2)
            start_daily(conn, 42, '日向美海')
        self.day += timedelta(days=3)
        with self.store.connect() as conn:
            self.assertEqual(settle_daily(conn, 42), 3)
            start_daily(conn, 42, None)
        self.set_favorite(None)
        self.day += timedelta(days=20)
        self.assertEqual(self.store.points(42, 'ロザリー'), 2)
        self.assertEqual(self.store.points(42, '日向美海'), 3)

    def test_existing_favorite_starts_today_and_migration_is_once(self):
        self.db.execute('CREATE TABLE george_gacha_migrations(name TEXT PRIMARY KEY)')
        with self.store.connect() as conn:
            seed_daily(conn)
        self.day += timedelta(days=2)
        with self.store.connect() as conn:
            seed_daily(conn)
            self.assertEqual(settle_daily(conn, 42), 2)

    def test_transaction_failure_does_not_lose_days(self):
        self.store.points(42, 'ロザリー')
        self.day += timedelta(days=2)
        self.fail_on = 'UPDATE george_daily_affection'
        with self.assertRaises(Exception):
            self.store.points(42, 'ロザリー')
        self.fail_on = None
        self.assertEqual(self.store.points(42, 'ロザリー'), 2)
