import unittest

from narrative import CONTRACT_VERSION, build_narrative


def make_report(**overrides):
    report = {
        "version": "ledger-v1",
        "period": "2026-10",
        "partial": False,
        "facts": {"income": 100000, "expense": 45000, "balance": 55000},
        "evidence": [
            {"id": "expense-1", "date": "2026-10-01", "category": "餐饮", "cents": 2500},
            {"id": "expense-2", "date": "2026-10-02", "category": "住房", "cents": 42500},
        ],
        "previous_evidence": [{"id": "previous-1"}],
        "comparison": {"expense": {"delta": 10000}},
        "top_expenses": [{"id": "expense-2", "date": "2026-10-02", "category": "住房", "cents": 42500}],
        "candidates": [],
        "recurring_candidates": [],
        "insufficient_ids": [],
    }
    report.update(overrides)
    return report


class NarrativeTests(unittest.TestCase):
    def test_contract_and_evidence_are_stable(self):
        result = build_narrative(make_report())
        self.assertEqual(result["contract_version"], CONTRACT_VERSION)
        self.assertEqual(result["source_ledger_version"], "ledger-v1")
        self.assertTrue(result["summary"])
        self.assertTrue(result["insights"])
        for item in result["insights"]:
            self.assertEqual(item["evidence_ids"], list(dict.fromkeys(item["evidence_ids"])))
            self.assertTrue(item["body"])

    def test_duplicate_and_amount_candidates_remain_candidates(self):
        report = make_report(candidates=[
            {"type": "duplicate", "ids": ["expense-1", "expense-2"], "evidence": []},
            {"type": "amount", "ids": ["expense-2"], "evidence": ["history-1"], "reason": {"history_count": 8}},
        ])
        result = build_narrative(report)
        types = [item["type"] for item in result["insights"]]
        certainties = [item["certainty"] for item in result["insights"]]
        self.assertIn("duplicate_candidate", types)
        self.assertIn("large_expense_candidate", types)
        self.assertIn("candidate", certainties)
        duplicate = next(item for item in result["insights"] if item["type"] == "duplicate_candidate")
        self.assertIn("expense-1", duplicate["evidence_ids"])

    def test_empty_period_is_information_needed(self):
        result = build_narrative(make_report(
            period="2026-11", facts={"income": 0, "expense": 0, "balance": 0},
            evidence=[], previous_evidence=[], comparison={"expense": {"delta": None}},
            top_expenses=[], candidates=[], insufficient_ids=[]
        ))
        self.assertEqual(result["insights"][0]["type"], "information_needed")
        self.assertEqual(result["insights"][0]["certainty"], "information_needed")
        self.assertIn("暂无已记录交易", result["summary"])

    def test_invalid_report_is_rejected(self):
        with self.assertRaises(ValueError):
            build_narrative({})


if __name__ == "__main__":
    unittest.main()
