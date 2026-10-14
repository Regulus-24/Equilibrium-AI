import unittest
from datetime import date
from analysis import monthly_comparisons


def row(day, cents, category="餐饮", kind="expense"):
    return dict(date=day, cents=cents, category=category, kind=kind)


class AnalysisTests(unittest.TestCase):
    def test_complete_month_category_decomposition(self):
        rows = [row("2026-07-01", 50000), row("2026-07-31", 20000, "交通"), row("2026-07-12", 80000, "购物"),
                row("2026-08-01", 80000), row("2026-08-31", 30000, "交通"), row("2026-08-12", 100000, "购物")]
        r = monthly_comparisons(rows, date(2026, 9, 15))["2026-08"]
        self.assertEqual((r["current_start"], r["current_end"], r["previous_end"]), ("2026-08-01", "2026-08-31", "2026-07-31"))
        self.assertFalse(r["partial"])
        e = r["kinds"]["expense"]
        self.assertEqual((e["current"], e["previous"], e["delta"], e["percent_basis_points"]), (210000, 150000, 60000, 4000))
        self.assertEqual(e["categories"][0]["category"], "餐饮")
        self.assertEqual(sum(c["delta"] for c in e["categories"]), e["delta"])

    def test_partial_month_uses_entire_previous_month(self):
        r = monthly_comparisons([row("2026-08-01", 100), row("2026-08-31", 200), row("2026-09-01", 120), row("2026-09-20", 999)], date(2026, 9, 15))["2026-09"]
        self.assertEqual((r["current_end"], r["previous_end"], r["current_days"], r["previous_days"]), ("2026-09-15", "2026-08-31", 15, 31))
        self.assertTrue(r["partial"])
        self.assertEqual(r["kinds"]["expense"]["previous"], 300)
        self.assertEqual(r["kinds"]["expense"]["delta"], -180)

    def test_new_removed_categories_and_offsetting_changes(self):
        r = monthly_comparisons([row("2026-07-01", 20, "餐饮"), row("2026-07-02", 30, "宠物"), row("2026-08-01", 50, "礼物")], date(2026, 9, 15))["2026-08"]["kinds"]["expense"]
        self.assertEqual(r["delta"], 0)
        self.assertEqual((r["increase"], r["decrease"], r["percent_basis_points"]), (50, 50, 0))
        self.assertEqual(len(r["categories"]), 3)

    def test_missing_records_are_not_a_zero_baseline(self):
        reports = monthly_comparisons([row("2026-08-01", 10)], date(2026, 9, 15))
        self.assertEqual(reports["2026-08"]["status"], "missing_previous")
        self.assertIsNone(reports["2026-08"]["kinds"]["expense"]["delta"])
        self.assertEqual(reports["2026-09"]["status"], "missing_current")
        self.assertIsNone(reports["2026-09"]["kinds"]["expense"]["percent_basis_points"])
        self.assertEqual(monthly_comparisons([], date(2026, 9, 15))["2026-09"]["status"], "missing_current")

    def test_zero_expense_baseline_and_income_are_separate(self):
        r = monthly_comparisons([row("2026-07-01", 10000, "工资", "income"), row("2026-08-01", 1000)], date(2026, 9, 15))["2026-08"]
        self.assertEqual(r["status"], "ready")
        self.assertEqual(r["kinds"]["expense"]["delta"], 1000)
        self.assertIsNone(r["kinds"]["expense"]["percent_basis_points"])
        self.assertEqual(r["kinds"]["income"]["percent_basis_points"], -10000)

    def test_calendar_year_boundary_and_leap_day(self):
        rows = [row("2023-12-31", 100), row("2024-01-31", 150), row("2024-02-29", 200), row("2024-03-01", 250)]
        reports = monthly_comparisons(rows, date(2024, 3, 10))
        self.assertEqual(reports["2024-01"]["previous_start"], "2023-12-01")
        self.assertEqual(reports["2024-03"]["previous_end"], "2024-02-29")
        self.assertFalse(reports["2024-02"]["partial"])

    def test_percent_rounding_and_minimum_year(self):
        r = monthly_comparisons([row("2026-07-01", 3), row("2026-08-01", 4)], date(2026, 8, 31))["2026-08"]
        self.assertEqual(r["kinds"]["expense"]["percent_basis_points"], 3333)
        self.assertFalse(r["partial"])
        self.assertIsNone(monthly_comparisons([row("0001-01-01", 1)], date(1, 1, 1))["0001-01"]["previous_end"])


if __name__ == "__main__":
    unittest.main()
