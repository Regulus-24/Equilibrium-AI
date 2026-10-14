import unittest
from pathlib import Path

from vendor.schema_contracts import SchemaStore


class BillContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schemas = SchemaStore(Path(__file__).parent / "schemas")

    def facts_payload(self):
        return {
            "contract_version": "bill-analysis-facts-v1",
            "snapshot": {
                "ledger_version": "fixture-ledger-v1",
                "as_of": "2026-10-13",
                "source": "manual_ledger",
                "scope": "recorded_transactions_only",
            },
            "period": {
                "requested": "2026-09",
                "start": "2026-09-01",
                "end": "2026-09-30",
                "partial": False,
                "current_days": 30,
                "previous": {
                    "start": "2026-08-01",
                    "end": "2026-08-31",
                    "days": 31,
                    "status": "ready",
                    "basis": "whole_period_vs_whole_period",
                },
            },
            "transactions": [
                {
                    "id": "tx-sep-1",
                    "revision": 1,
                    "date": "2026-09-28",
                    "kind": "expense",
                    "amount_cents": 2400,
                    "category": "约会",
                    "note": "吃晚饭",
                    "source": "manual_ledger",
                },
                {
                    "id": "tx-sep-2",
                    "revision": 1,
                    "date": "2026-09-29",
                    "kind": "expense",
                    "amount_cents": 1780,
                    "category": "餐饮",
                    "note": "中午点外卖吃陕西菜",
                    "source": "manual_ledger",
                },
            ],
            "facts": {
                "income_cents": 0,
                "expense_cents": 4180,
                "net_cents": -4180,
                "income_record_count": 0,
                "expense_record_count": 2,
                "savings_rate_basis_points": None,
                "available_balance_cents": None,
            },
            "comparison": {
                "status": "ready",
                "income": {
                    "current_cents": 0,
                    "previous_cents": 0,
                    "delta_cents": 0,
                    "percent_basis_points": None,
                },
                "expense": {
                    "current_cents": 4180,
                    "previous_cents": 7450,
                    "delta_cents": -3270,
                    "percent_basis_points": -4389,
                },
            },
            "categories": [
                {
                    "kind": "expense",
                    "category": "约会",
                    "amount_cents": 2400,
                    "share_basis_points": 5741,
                    "transaction_ids": ["tx-sep-1"],
                },
                {
                    "kind": "expense",
                    "category": "餐饮",
                    "amount_cents": 1780,
                    "share_basis_points": 4258,
                    "transaction_ids": ["tx-sep-2"],
                },
            ],
            "data_quality": {
                "conclusion_level": "conditional_comparison",
                "has_recorded_income": False,
                "has_recorded_expense": True,
                "has_explicit_available_balance": False,
                "has_prior_comparable_period": True,
                "missing_fields": ["income_record"],
                "warnings": [
                    "没有收入记录，不能计算储蓄率。",
                    "没有明确可用余额，不能判断余额是否不足。",
                ],
                "insufficient_history_ids": ["tx-sep-1", "tx-sep-2"],
            },
        }

    def test_facts_contract_accepts_existing_ledger_shape(self):
        issues = self.schemas.validate(self.facts_payload(), "bill-analysis-facts-v1.json")
        self.assertEqual([], [issue.to_dict() for issue in issues])
        self.assertIsNone(self.facts_payload()["facts"]["available_balance_cents"])

    def test_narrative_contract_requires_evidence_and_priority(self):
        payload = {
            "contract_version": "bill-analysis-narrative-v1",
            "source_ledger_version": "fixture-ledger-v1",
            "summary": "已记录支出较上期减少，但缺少收入和可用余额信息。",
            "insights": [
                {
                    "id": "insight-1",
                    "priority": 1,
                    "type": "comparison",
                    "certainty": "fact",
                    "title": "本期支出较上期减少",
                    "body": "已记录的支出比上期少 32.70 元，降幅约 43.89%。",
                    "evidence_ids": ["tx-sep-1", "tx-sep-2"],
                    "suggestion": None,
                },
                {
                    "id": "insight-2",
                    "priority": 2,
                    "type": "information_needed",
                    "certainty": "information_needed",
                    "title": "需要补充信息",
                    "body": "当前没有收入记录或明确可用余额，不能计算储蓄率或判断余额是否不足。",
                    "evidence_ids": [],
                    "suggestion": "如需完整分析，请补充本期收入和明确的可用余额。",
                },
            ],
        }
        issues = self.schemas.validate(payload, "bill-analysis-narrative-v1.json")
        self.assertEqual([], [issue.to_dict() for issue in issues])


if __name__ == "__main__":
    unittest.main(verbosity=2)
