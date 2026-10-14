import tempfile
import unittest
import copy
import json
from pathlib import Path
from datetime import date, timedelta

from ledger import Ledger, LedgerConflict, parse_amount
from server import Store


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = Ledger(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def payload(self, **changes):
        row = dict(id="test-1", revision=0, kind="expense", amount="25.10",
                   date="2026-09-01", category="礼物", note="给朋友的一本书")
        row.update(changes)
        return row

    def test_amount_precision(self):
        for text, expected in [("25", 2500), ("25.10", 2510), ("25.12", 2512), ("0.01", 1), ("999999999.99", 99999999999)]:
            self.assertEqual(parse_amount(text), expected)
        for text in ["25.123", "1e2", "NaN", "-1", "0", "0.00", "1,000", "1.", ".1", "1000000000", 25, True, None]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_amount(text)

    def test_daily_monthly_annual_summaries_and_recalculation(self):
        self.ledger.save(self.payload(id="a", date="2024-02-01", amount="10.1"))
        self.ledger.save(self.payload(id="b", date="2024-02-01", amount="0.2"))
        self.ledger.save(self.payload(id="c", date="2024-02-29", kind="income", category="工资", amount="100"))
        self.ledger.save(self.payload(id="d", date="2024-03-01", amount="20", category="宠物"))
        self.ledger.save(self.payload(id="e", date="2025-01-01", amount="5"))
        result = self.ledger.public()
        self.assertEqual(result["days"]["2024-02-01"]["expense"], 1030)
        self.assertEqual(result["months"]["2024-02"]["balance"], 8970)
        self.assertEqual(result["years"]["2024"]["expense"], 3030)
        self.assertEqual(result["years"]["2024"]["categories"]["expense"]["宠物"], 2000)
        self.assertEqual(result["years"]["2025"]["expense"], 500)
        backup = self.ledger.backup()
        self.ledger.save(self.payload(id="a", revision=1, date="2024-02-01", amount="11.1"))
        self.assertEqual(self.ledger.public()["years"]["2024"]["expense"], 3130)
        self.ledger.delete(dict(id="d", revision=1))
        self.assertNotIn("2024-03", self.ledger.public()["months"])
        preview = self.ledger.preview_restore({"backup": backup})
        self.ledger.restore(dict(backup=backup, expected_version=preview["expected_version"], confirm=True))
        self.assertEqual(self.ledger.public()["years"], result["years"])
        self.assertEqual(self.ledger.public()["days"], result["days"])

    def test_backup_restore_roundtrip_and_safety_copy(self):
        self.ledger.save(self.payload(category="宠物"))
        backup = self.ledger.backup()
        self.ledger.save(self.payload(id="second", amount="1"))
        before = self.ledger.backup()
        preview = self.ledger.preview_restore({"backup": backup})
        result = self.ledger.restore(dict(backup=backup, expected_version=preview["expected_version"], confirm=True))
        self.assertEqual(self.ledger.public()["months"]["2026-09"]["expense"], 2510)
        self.assertIn("宠物", self.ledger.public()["categories"]["expense"])
        safety = json.loads((Path(self.tmp.name) / result["safety_backup"]).read_text(encoding="utf-8"))
        self.assertEqual(safety, before)
        self.assertEqual(Ledger(self.tmp.name).public(), self.ledger.public())
        with self.assertRaises(LedgerConflict):
            self.ledger.save(self.payload(revision=1, amount="2"))
        with self.assertRaises(LedgerConflict):
            self.ledger.delete(dict(id="test-1", revision=1))
        with tempfile.TemporaryDirectory() as other:
            independent = Ledger(other)
            self.assertEqual(independent.public()["entries"], [])
            p = independent.preview_restore({"backup": safety})
            independent.restore(dict(backup=safety, expected_version=p["expected_version"], confirm=True))
            self.assertEqual(len(independent.public()["entries"]), 2)

    def test_restore_conflict_and_invalid_backups_leave_ledger_untouched(self):
        self.ledger.save(self.payload())
        backup = self.ledger.backup()
        preview = self.ledger.preview_restore({"backup": backup})
        self.ledger.save(self.payload(id="second"))
        before = self.ledger.file.read_bytes()
        with self.assertRaises(LedgerConflict):
            self.ledger.restore(dict(backup=backup, expected_version=preview["expected_version"], confirm=True))
        for field, value in [("cents", True), ("cents", 1.2), ("revision", 0), ("date", "bad"), ("kind", []), ("note", None), ("category", "未定义分类")]:
            bad = copy.deepcopy(backup)
            bad["data"]["entries"]["test-1"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.ledger.preview_restore({"backup": bad})
        for bad in [None, [], {}, {**backup, "version": True}]:
            with self.assertRaises(ValueError):
                self.ledger.preview_restore({"backup": bad})
        with self.assertRaises(ValueError):
            self.ledger.restore(dict(backup=backup, expected_version=self.ledger.public()["version"], confirm=False))
        self.assertEqual(self.ledger.file.read_bytes(), before)
        self.assertFalse((Path(self.tmp.name) / "backups").exists())

    def test_save_replay_and_restart(self):
        payload = self.payload()
        self.ledger.save(payload)
        self.assertTrue(self.ledger.save(payload)["replayed"])
        restarted = Ledger(self.tmp.name).public()
        self.assertEqual(len(restarted["entries"]), 1)
        self.assertEqual(restarted["entries"][0]["cents"], 2510)
        self.assertEqual(restarted["months"]["2026-09"]["balance"], -2510)

    def test_custom_category_persist_and_deduplicate(self):
        self.ledger.save(self.payload(category="  宠物  ", note=""))
        self.ledger.save(self.payload(id="test-2", category="宠物"))
        restarted = Ledger(self.tmp.name).public()
        self.assertEqual(restarted["categories"]["expense"].count("宠物"), 1)
        self.assertNotIn("宠物", restarted["categories"]["income"])
        self.assertEqual(restarted["months"]["2026-09"]["categories"]["expense"]["宠物"], 5020)

    def test_month_isolation_edit_and_delete(self):
        self.ledger.save(self.payload())
        self.ledger.save(self.payload(id="test-2", date="2026-08-31", kind="income", amount="100", category="工资"))
        self.ledger.save(self.payload(revision=1, amount="0.1", kind="income", category="兼职", date="2026-08-01"))
        state = self.ledger.public()
        self.assertNotIn("2026-09", state["months"])
        self.assertEqual(state["months"]["2026-08"]["income"], 10010)
        self.ledger.delete({"id": "test-1", "revision": 2})
        self.assertEqual(self.ledger.public()["months"]["2026-08"]["income"], 10000)

    def test_exact_sum(self):
        self.ledger.save(self.payload(amount="0.1"))
        self.ledger.save(self.payload(id="test-2", amount="0.2"))
        self.assertEqual(self.ledger.public()["months"]["2026-09"]["expense"], 30)

    def test_conflict_and_no_resurrection(self):
        self.ledger.save(self.payload())
        self.ledger.save(self.payload(revision=1, amount="30"))
        with self.assertRaises(LedgerConflict):
            self.ledger.save(self.payload(revision=1, amount="40"))
        with self.assertRaises(LedgerConflict):
            self.ledger.delete({"id":"test-1", "revision":1})
        self.ledger.delete({"id":"test-1", "revision":2})
        with self.assertRaises(LedgerConflict):
            self.ledger.save(self.payload(revision=2))

    def test_server_validation_is_atomic(self):
        for change in [dict(date="2026-02-30"), dict(date=(date.today()+timedelta(days=1)).isoformat()), dict(category=" "), dict(category="字"*21), dict(note="字"*501), dict(kind="refund"), dict(revision=True), dict(amount="1.234"), dict(extra="bad")]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.ledger.save(self.payload(**change))
            self.assertEqual(self.ledger.public()["entries"], [])

    def test_bank_reset_preserves_ledger_and_bank_figures(self):
        store = Store(self.tmp.name)
        self.ledger.save(self.payload())
        store.reset()
        self.assertEqual(len(Ledger(self.tmp.name).public()["entries"]), 1)
        self.assertEqual(store.public()["summary"]["net_expense"], 690900)
        self.assertEqual(store.public()["balance_cents"], 1800000)


if __name__ == "__main__":
    unittest.main()
