import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from server import Store
from llm_client import LLMClient, LLMClientError


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def ask(self, text):
        return self.store.agent.handle({"message": text, "context": {}})

    def test_bill_report_is_evidence_linked(self):
        result = self.ask("帮我看看 2026年9月花在哪里")
        self.assertEqual(result["intent"], "bill_analysis")
        self.assertIsInstance(result["evidence_ids"], list)
        self.assertEqual(result["source_versions"]["ledger_version"], self.store.ledger.public()["version"])

    def test_card_request_only_previews(self):
        result = self.ask("陌生扣款对应哪张卡？先帮我预览锁卡")
        self.assertEqual(result["intent"], "cross_scene")
        self.assertTrue(result["requires_confirmation"])
        self.assertEqual(self.store.public()["card"]["status"], "ACTIVE")
        self.assertIn("plan", result)

    def test_card_confirmation_language_does_not_bypass_gate(self):
        result = self.ask("确认锁卡")
        self.assertFalse(result["requires_confirmation"])
        self.assertEqual(self.store.public()["card"]["status"], "ACTIVE")

    def test_wealth_comparison_has_no_order(self):
        result = self.ask("比较30天内要用的钱适合什么理财")
        self.assertEqual(result["intent"], "wealth_operation")
        self.assertFalse(result["requires_confirmation"])
        self.assertIn("条件比较", result["answer"])

    def test_purchase_requires_explicit_confirmation(self):
        result = self.ask("模拟申购 1000 元 000343，30天后用，接受本金损失")
        self.assertEqual(result["intent"], "wealth_operation")
        self.assertTrue(result["requires_confirmation"])
        self.assertEqual(result["order"]["status"], "DRAFT")
        self.assertEqual(self.store.orders.public()["orders"][0]["status"], "DRAFT")

    def test_purchase_transition_and_query(self):
        result = self.ask("模拟申购 1000 元 000343，30天后用，接受本金损失")
        confirmed = self.store.orders.confirm({
            "order_id": result["order"]["id"],
            "preview_hash": result["order"]["preview_hash"],
            "confirm": True,
        })
        self.assertEqual(confirmed["order"]["status"], "COMPLETED")
        self.assertEqual([x["status"] for x in confirmed["order"]["history"]], ["DRAFT", "ACCEPTED", "COMPLETED"])
        self.assertEqual(self.store.orders.query(result["order"]["id"])["status"], "COMPLETED")

    def test_purchase_with_cash_safety_gate(self):
        funding = {"available_cents": 100000, "reserve_cents": 1000, "amount_cents": 200000,
                   "need_date": self.store.ledger.public()["as_of"], "accept_loss": True,
                   "confirmed_on": self.store.ledger.public()["as_of"]}
        with self.assertRaises(ValueError):
            self.store.order_preview({"code":"000343","amount_cents":200000,
                                      "need_date":funding["need_date"],"accept_loss":True,"funding":funding})
        funding["amount_cents"] = 1000
        order = self.store.order_preview({"code":"000343","amount_cents":1000,
                                           "need_date":funding["need_date"],"accept_loss":True,"funding":funding})
        self.assertEqual(order["funding_check"]["status"], "ready_for_comparison")

    def test_natural_language_cash_gate(self):
        blocked = self.ask("我有现金 1000 元，预留 100 元，模拟申购 2000 元 000343，接受本金损失")
        self.assertFalse(blocked["requires_confirmation"])
        self.assertIn("安全检查未通过", blocked["answer"])
        allowed = self.ask("我有现金 1000 元，预留 100 元，模拟申购 10 元 000343，接受本金损失")
        self.assertTrue(allowed["requires_confirmation"])
        self.assertEqual(allowed["order"]["funding_check"]["status"], "ready_for_comparison")

    def test_cross_scene_links_bill_and_card(self):
        result = self.ask("账单里的陌生扣款对应哪张卡，帮我预览锁卡")
        self.assertEqual(result["intent"], "cross_scene")
        self.assertTrue(result["requires_confirmation"])
        self.assertEqual([x["name"] for x in result["tool_calls"]], [
            "get_bill_report", "get_card_status", "preview_temporary_lock"
        ])

    def test_llm_bridge_recomputes_facts_and_returns_pending_preview(self):
        result = self.store.agent.handle_llm_plan({
            "message": "请核对陌生扣款并预览锁卡",
            "model_output": {
                "intent": "cross_scene",
                "answer": "我准备先核对账单和卡片。",
                "tool_calls": [
                    {"name": "get_bill_report", "arguments": {"period": "2026-10"}},
                    {"name": "get_card_status", "arguments": {"card_id": "demo-card-0428"}},
                    {"name": "preview_temporary_lock", "arguments": {"card_id": "demo-card-0428"}},
                ],
            },
        })
        self.assertEqual(result["source"], "llm-validated")
        self.assertTrue(result["requires_confirmation"])
        self.assertEqual(self.store.public()["card"]["status"], "ACTIVE")

    def test_llm_bridge_rejects_write_tool(self):
        with self.assertRaises(ValueError):
            self.store.agent.handle_llm_plan({
                "message": "确认锁卡",
                "model_output": {
                    "intent": "card_management",
                    "answer": "确认",
                    "tool_calls": [{"name": "approve", "arguments": {}}],
                },
            })

    def test_llm_bridge_can_read_card_billing_summary(self):
        result = self.store.agent.handle_llm_plan({
            "message": "查看卡片本期账单和还款日",
            "model_output": {"intent": "card_management", "answer": "先读取卡片账单摘要。",
                             "tool_calls": [{"name": "get_card_summary", "arguments": {"period": "2026-09"}}]},
        })
        self.assertEqual(result["tool_results"][0]["name"], "get_card_summary")
        self.assertEqual(result["tool_results"][0]["result"]["card"]["last4"], "0428")

    def test_qwen_chat_validates_fake_model_plan(self):
        class FakeQwen:
            def complete(self, message, context):
                return ({
                    "intent": "cross_scene",
                    "answer": "先核对账单和卡片，再预览临时锁卡。",
                    "tool_calls": [
                        {"name": "get_bill_report", "arguments": {"period": "2026-10"}},
                        {"name": "get_card_status", "arguments": {"card_id": "demo-card-0428"}},
                        {"name": "preview_temporary_lock", "arguments": {"card_id": "demo-card-0428"}},
                    ],
                }, {"provider": "dashscope", "model": "fake-qwen"})

        self.store.agent.llm_client = FakeQwen()
        result = self.store.agent.handle_chat({"message": "核对陌生扣款并锁卡", "context": {}})
        self.assertEqual(result["source"], "qwen")
        self.assertEqual(result["model"], "fake-qwen")
        self.assertTrue(result["requires_confirmation"])
        self.assertEqual(self.store.public()["card"]["status"], "ACTIVE")

    def test_qwen_chat_requires_server_key(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(LLMClientError):
                LLMClient().complete("分析账单", {})

    def test_qwen_failure_falls_back_to_local_bill_analysis(self):
        class BrokenQwen:
            def complete(self, message, context):
                raise LLMClientError("模拟网络失败")
        self.store.agent.llm_client = BrokenQwen()
        result = self.store.agent.handle_chat({"message": "分析 2026年9月账单", "context": {}})
        self.assertEqual(result["source"], "deterministic_fallback")
        self.assertEqual(result["provider"], "local")
        self.assertEqual(result["intent"], "bill_analysis")
        self.assertIn("模拟网络失败", result["fallback_reason"])

    def test_invalid_qwen_plan_falls_back_without_write(self):
        class UnsafeQwen:
            def complete(self, message, context):
                return ({"intent":"bill_analysis","answer":"执行写入","tool_calls":[{"name":"approve","arguments":{}}]}, {})
        self.store.agent.llm_client = UnsafeQwen()
        result = self.store.agent.handle_chat({"message": "看看账单", "context": {}})
        self.assertEqual(result["source"], "deterministic_fallback")
        self.assertEqual(self.store.public()["card"]["status"], "ACTIVE")

    def test_structured_tool_arguments_are_strict(self):
        with self.assertRaises(ValueError):
            self.store.agent.handle_llm_plan({
                "message": "分析账单",
                "model_output": {"intent":"bill_analysis","answer":"","tool_calls":[
                    {"name":"get_bill_report","arguments":{"period":"2026-10","write":True}}
                ]},
            })


if __name__ == "__main__":
    unittest.main()
