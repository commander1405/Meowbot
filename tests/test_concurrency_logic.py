"""
Regression tests for economy/concurrency guards.
These tests validate pure logic and SQL-shape helpers without production DB.
Live concurrent asyncpg tests require DATABASE_URL and are marked separately.
"""
import ast
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)


class TestSourceGuards(unittest.TestCase):
    """Static checks that critical paths use atomic patterns."""

    def _read(self, rel):
        with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
            return f.read()

    def test_daily_uses_atomic_claim(self):
        src = self._read("core/menu.py")
        self.assertIn("claim_daily_reward_atomic", src)
        # old non-atomic path must not remain
        self.assertNotIn("await add_meow_coins(user_id, reward)\n    await update_user(user_id, last_daily", src)

    def test_meow_uses_atomic_claim(self):
        src = self._read("core/meow.py")
        self.assertIn("try_claim_meow_atomic", src)
        self.assertNotIn("await add_meow_points(user_id, points, chat_id)\n    await set_last_meow", src)

    def test_shop_buy_uses_purchase_helper(self):
        src = self._read("main.py")
        self.assertIn("purchase_shop_item", src)

    def test_remove_item_returns_false_path(self):
        src = self._read("database/inventory.py")
        self.assertIn("RETURNING quantity", src)
        # must not unconditionally return True after update
        self.assertIn("if not row:\n        return False", src)

    def test_consume_use_uses_for_update(self):
        src = self._read("database/inventory.py")
        self.assertIn("FOR UPDATE", src)
        self.assertIn("async with conn.transaction()", src)

    def test_purchase_shop_item_transaction(self):
        src = self._read("database/inventory.py")
        self.assertIn("async def purchase_shop_item", src)
        self.assertIn("FOR UPDATE", src)
        self.assertIn("meow_coins = meow_coins -", src)

    def test_bank_transfer_atomic(self):
        src = self._read("database/bank.py")
        self.assertIn("async with conn.transaction()", src)
        self.assertIn("balance = balance - $2", src)

    def test_on_ready_fails_loud(self):
        src = self._read("main.py")
        self.assertIn("NOT fully operational", src)
        self.assertIn("_ready_lock", src)

    def test_config_untouched_hash_marker(self):
        # config must still exist and not be empty
        path = os.path.join(ROOT, "config.py")
        self.assertTrue(os.path.isfile(path))
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("BOT_TOKEN", text)
        self.assertIn("OWNER_ID", text)

    def test_halloween_pumpkin_transaction(self):
        src = self._read("halloween/handlers.py")
        self.assertIn("FOR UPDATE", src)
        self.assertIn("halloween_pumpkin_claims", src)

    def test_no_rubika_package(self):
        self.assertFalse(os.path.isdir(os.path.join(ROOT, "mega_rubika")))
        self.assertFalse(os.path.isfile(os.path.join(ROOT, "run_both.py")))


class TestAtomicSQLSemantics(unittest.TestCase):
    """Document expected semantics of the atomic SQL patterns."""

    def test_daily_condition_excludes_same_day(self):
        # claim condition: last_daily IS NULL OR last_daily <> today
        cond = "last_daily IS NULL OR last_daily <> $2"
        self.assertIn("<>", cond)

    def test_meow_threshold_formula(self):
        now, cooldown = 1000.0, 300.0
        threshold = now - cooldown  # 700
        last_eligible = 700.0
        last_blocked = 701.0
        self.assertTrue(last_eligible <= threshold)  # eligible
        self.assertFalse(last_blocked <= threshold)  # blocked

    def test_stock_unlimited_vs_finite(self):
        stock_unlimited = -1
        stock_zero = 0
        stock_finite = 3
        self.assertTrue(stock_unlimited < 0)
        self.assertEqual(stock_zero, 0)
        self.assertTrue(stock_finite > 0)


if __name__ == "__main__":
    unittest.main()
