"""Natural-language contract and deterministic tool router for the demo.

The router is intentionally conservative: it can read facts and prepare a
card-lock plan, while the existing server-side approval gate remains the only
way to mutate business state. A model can be added behind the same contract
later without changing the tools or evidence format.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from llm_client import LLMClient, LLMClientError


CONTRACT_VERSION = "equilibrium-agent-v1"


class AgentError(ValueError):
    pass


def _money(cents: int) -> str:
    return f"¥{cents / 100:,.2f}".rstrip("0").rstrip(".")


def _period(text: str) -> str:
    match = re.search(r"(20\d{2}(?:年\s*\d{1,2}月|[-/]\d{1,2}月?))", text)
    if not match:
        return date.today().strftime("%Y-%m")
    value = match.group(1).replace("年", "-").replace("月", "").replace("/", "-").replace(" ", "")
    if re.fullmatch(r"20\d{2}", value):
        return value
    year, month = value.split("-", 1)
    return f"{year}-{int(month):02d}"


def _intent(text: str) -> str:
    if any(a in text for a in ("账单", "扣款", "交易")) and any(b in text for b in ("锁卡", "锁定卡", "卡片")):
        return "cross_scene"
    if any(k in text for k in ("锁卡", "锁定卡", "陌生扣款", "可疑交易", "卡片状态")):
        return "card_management"
    if any(k in text for k in ("基金", "理财", "申购", "赎回", "收益", "用款日期", "投资", "订单")):
        return "wealth_operation"
    if any(k in text for k in ("账单", "消费", "花了", "花在哪里", "支出", "异常", "报告", "分类", "重复扣款")):
        return "bill_analysis"
    return "clarification"


class EquilibriumAgent:
    def __init__(self, store, llm_client=None):
        self.store = store
        self.llm_client = llm_client or LLMClient()

    def handle_chat(self, payload: dict) -> dict:
        """Call Qwen, then validate its untrusted plan through the local router."""
        if not isinstance(payload, dict) or set(payload) not in ({"message"}, {"message", "context"}):
            raise AgentError("请求必须包含 message，可选 context。")
        message = payload.get("message") if isinstance(payload.get("message"), str) else ""
        if not 1 <= len(message.strip()) <= 2000:
            raise AgentError("请输入 1—2000 字的金融问题。")
        context = payload.get("context", {})
        try:
            model_output, metadata = self.llm_client.complete(message, context)
            result = self.handle_llm_plan({"message": message, "model_output": model_output})
        except (LLMClientError, AgentError) as exc:
            # Provider outages, invalid JSON, and unsafe model plans fall back
            # to the local evidence-linked router without attempting writes.
            result = self.handle({"message": message, "context": context})
            result["source"] = "deterministic_fallback"
            result["fallback_reason"] = str(exc)
            result["provider"] = "local"
            result["model"] = None
            return result
        result["source"] = "qwen"
        result["provider"] = metadata.get("provider", "dashscope") if isinstance(metadata, dict) else "dashscope"
        result["model"] = metadata.get("model") if isinstance(metadata, dict) else None
        result["model_answer"] = model_output.get("answer", "")
        return result

    def handle(self, payload: dict) -> dict:
        if not isinstance(payload, dict) or set(payload) != {"message", "context"}:
            raise AgentError("请求必须包含 message 和 context。")
        message = payload["message"].strip() if isinstance(payload["message"], str) else ""
        if not 1 <= len(message) <= 2000:
            raise AgentError("请输入 1—2000 字的金融问题。")
        context = payload["context"] if isinstance(payload["context"], dict) else {}
        intent = _intent(message)
        base = {
            "contract_version": CONTRACT_VERSION,
            "message": message,
            "intent": intent,
            "requires_confirmation": False,
            "tool_calls": [],
            "evidence_ids": [],
            "source_versions": {},
            "missing_information": [],
            "answer": "",
        }
        if intent == "bill_analysis":
            period = context.get("period") or _period(message)
            report = self.store.insights.get_report(period)
            facts = report["facts"]
            candidates = report["candidates"]
            base["tool_calls"] = [{"name": "get_bill_report", "arguments": {"period": period}}]
            base["source_versions"] = {"ledger_version": report["version"], "rule_version": report["rule_version"]}
            base["evidence_ids"] = [row["id"] for row in report["evidence"]]
            candidate_note = "；".join(
                f"{'疑似重复' if c['type']=='duplicate' else '金额偏离'}：{','.join(c['ids'])}，需人工核查"
                for c in candidates
            ) or "当前没有规则候选，仍只代表已记录账本。"
            recurring = report.get("recurring_candidates", [])
            if recurring:
                candidate_note += "；可能固定/订阅：" + "、".join(c["reason"]["merchant"] for c in recurring[:3]) + "，需人工确认"
            safety = report.get("cash_safety", {})
            safety_note = ""
            if safety.get("suggested_reserve_floor_cents") is not None:
                safety_note = f"近90天必要支出三个月参考线为 {_money(safety['suggested_reserve_floor_cents'])}。"
            base["answer"] = (
                f"{report['period']} 已记录收入 {_money(facts['income'])}，支出 {_money(facts['expense'])}，"
                f"账面结余 {_money(facts['balance'])}。{candidate_note}{safety_note}"
            )
            base["limitations"] = report["limitations"]
            return base
        if intent == "cross_scene":
            period = context.get("period") or _period(message)
            report = self.store.insights.get_report(period)
            state = self.store.public()
            base["tool_calls"] = [
                {"name": "get_bill_report", "arguments": {"period": period}},
                {"name": "get_card_status", "arguments": {"card_id": state["card"]["id"]}},
            ]
            base["source_versions"] = {
                "ledger_version": report["version"],
                "card_version": state["card"]["version"],
                "rule_version": report["rule_version"],
            }
            base["evidence_ids"] = [row["id"] for row in report["evidence"] if row["category"] == "待核实"]
            if state["card"]["status"] != "ACTIVE":
                base["answer"] = f"已核对账单和卡片：尾号 {state['card']['last4']} 已经临时锁定，锁卡不会撤回既有交易。"
                return base
            plan = self.store.plan({"card_id": state["card"]["id"]})
            base["tool_calls"].append({"name": "preview_temporary_lock", "arguments": {"card_id": state["card"]["id"]}})
            base["plan"] = plan
            base["requires_confirmation"] = True
            base["answer"] = (
                f"我先核对了 {period} 账单中的待核实交易，并关联到尾号 {state['card']['last4']}。"
                "已生成临时锁卡预览；锁卡不会退款，也不等同于正式挂失，请确认后执行。"
            )
            return base
        if intent == "wealth_operation":
            days = 30 if ("30" in message or "一个月" in message) else 90
            accept_loss = not any(k in message for k in ("不能承受", "不接受本金", "保本"))
            if any(k in message for k in ("申购", "买入", "下单", "投入")):
                amount_match = re.search(r"(?:申购|买入|投入|下单)\s*(\d+(?:\.\d{1,2})?)\s*(?:元|块)", message)
                amount_match = amount_match or re.search(r"(\d+(?:\.\d{1,2})?)\s*(?:元|块)", message)
                if not amount_match:
                    base["missing_information"] = ["请提供拟投入金额，例如“模拟申购 1000 元”。"]
                    base["answer"] = "模拟申购前需要明确具体金额、用款日期和本金损失承受意愿。"
                    return base
                amount_cents = int(round(float(amount_match.group(1)) * 100))
                code_match = re.search(r"\b(000343|000359|000397|000389|000719)\b", message)
                code = code_match.group(1) if code_match else "000343"
                need_date = (date.today() + timedelta(days=days)).isoformat()
                order_payload = {
                    "code": code, "amount_cents": amount_cents,
                    "need_date": need_date, "accept_loss": accept_loss
                }
                # If the user supplies cash and reserve in natural language, run
                # the same server-side safety gate used by the explicit API.
                cash_match = re.search(r"(?:现金|可用资金|有)\s*(\d+(?:\.\d{1,2})?)\s*元", message)
                reserve_match = re.search(r"(?:预留|备用金|安全垫)\s*(\d+(?:\.\d{1,2})?)\s*元", message)
                if cash_match and reserve_match:
                    to_cents = lambda m: int(round(float(m.group(1)) * 100))
                    order_payload["funding"] = {
                        "available_cents": to_cents(cash_match),
                        "reserve_cents": to_cents(reserve_match),
                        "amount_cents": amount_cents,
                        "need_date": need_date,
                        "accept_loss": accept_loss,
                        "confirmed_on": date.today().isoformat(),
                    }
                try:
                    order = self.store.order_preview(order_payload) if "funding" in order_payload else self.store.orders.preview(order_payload)
                except ValueError as exc:
                    base["missing_information"] = [str(exc)]
                    base["answer"] = "我已读取你提供的现金条件，但安全检查未通过，暂不生成模拟订单。"
                    return base
                base["tool_calls"] = [{"name": "preview_simulated_purchase", "arguments": {
                    "code": code, "amount_cents": amount_cents, "need_date": need_date
                }}]
                base["source_versions"] = {"order_version": self.store.orders.public()["version"]}
                base["order"] = order
                base["requires_confirmation"] = True
                base["answer"] = (
                    f"已生成 {code} 的模拟申购预览，金额 ¥{amount_cents / 100:.2f}，"
                    f"预计用款日 {need_date}。这是本地模拟订单，不会连接银行或基金平台；请确认后才会写入模拟状态。"
                )
                return base
            result = self.store.compare({"days": days, "accept_loss": accept_loss})
            base["tool_calls"] = [{"name": "compare_products", "arguments": {"days": days, "accept_loss": accept_loss}}]
            base["source_versions"] = {"fund_catalog": "five-fund-v1"}
            eligible = [p["name"] for p in result["products"] if p["eligible"]]
            base["answer"] = (
                f"按 {days} 天用款和{'可接受本金损失' if accept_loss else '不能承受本金损失'}条件，"
                + (f"候选为：{'、'.join(eligible)}。" if eligible else "当前没有满足演示条件的产品。")
                + " 这是条件比较，不是收益承诺或正式适当性评估。"
            )
            base["limitations"] = [result["note"]]
            return base
        if intent == "card_management":
            state = self.store.public()
            base["tool_calls"] = [{"name": "get_card_status", "arguments": {"card_id": state["card"]["id"]}}]
            base["source_versions"] = {"card_version": state["card"]["version"]}
            base["evidence_ids"] = [t["id"] for t in state["transactions"] if t["category"] == "待核实"]
            if state["card"]["status"] != "ACTIVE":
                base["answer"] = f"尾号 {state['card']['last4']} 当前已经临时锁定。锁卡不会撤回既有账单交易。"
                return base
            if any(k in message for k in ("确认", "执行", "现在锁", "帮我锁")):
                base["missing_information"] = ["请先使用“预览临时锁卡”并明确确认具体影响。"]
                base["answer"] = "为避免把自然语言误解成授权，请先生成锁卡预览，再勾选确认。"
                return base
            plan = self.store.plan({"card_id": state["card"]["id"]})
            base["tool_calls"] = [
                {"name": "get_card_status", "arguments": {"card_id": state["card"]["id"]}},
                {"name": "preview_temporary_lock", "arguments": {"card_id": state["card"]["id"]}},
            ]
            base["plan"] = plan
            base["requires_confirmation"] = True
            base["answer"] = (
                f"尾号 {state['card']['last4']} 当前正常。已生成临时锁卡预览：确认后卡片状态会变为“临时锁定”，"
                "不会退款，也不等同于正式挂失。请确认这项具体计划。"
            )
            return base
        base["missing_information"] = ["请说明你想查询账单、比较理财产品，还是查看/锁定卡片。"]
        base["answer"] = "我可以帮你分析账单、比较理财条件，或查询并预览卡片临时锁定。"
        return base

    def handle_llm_plan(self, payload: dict) -> dict:
        """Validate a model-produced plan and execute only safe preview/read tools.

        The caller may use Qwen or another provider. The model output is treated
        as untrusted data; facts are recomputed by this service and write tools
        remain behind the existing confirmation endpoints.
        """
        if not isinstance(payload, dict) or set(payload) != {"message", "model_output"}:
            raise AgentError("请求必须包含 message 和 model_output。")
        message = payload["message"] if isinstance(payload["message"], str) else ""
        model = payload["model_output"]
        if not 1 <= len(message.strip()) <= 2000 or not isinstance(model, dict):
            raise AgentError("message 或 model_output 无效。")
        allowed = {
            "get_bill_report", "get_card_status", "preview_temporary_lock",
            "get_card_summary", "compare_products", "preview_simulated_purchase", "query_order",
        }
        calls = model.get("tool_calls")
        intent = model.get("intent")
        if intent not in {"bill_analysis", "wealth_operation", "card_management", "cross_scene", "clarification"}:
            raise AgentError("模型返回了不支持的 intent。")
        if not isinstance(calls, list) or not calls or len(calls) > 5:
            raise AgentError("模型必须返回 1—5 个白名单 tool_calls。")
        results = []
        pending = None
        for call in calls:
            if not isinstance(call, dict) or set(call) != {"name", "arguments"}:
                raise AgentError("tool_call 必须包含 name 和 arguments。")
            name, args = call["name"], call["arguments"]
            if name not in allowed or not isinstance(args, dict):
                raise AgentError("模型请求了未授权工具。")
            if name == "get_bill_report":
                if set(args) != {"period"} or not isinstance(args.get("period"), str):
                    raise AgentError("get_bill_report 参数必须是 period。")
                period = args.get("period")
                result = self.store.insights.get_report(period)
                results.append({"name": name, "result": result})
            elif name == "get_card_status":
                if set(args) != {"card_id"} or args.get("card_id") != "demo-card-0428":
                    raise AgentError("只能读取演示卡片状态。")
                state = self.store.public()
                results.append({"name": name, "result": {
                    "card": state["card"],
                    "transactions": [t for t in state["transactions"] if t["category"] == "待核实"],
                }})
            elif name == "get_card_summary":
                if set(args) not in ({"period"}, set()) or ("period" in args and not isinstance(args["period"], str)):
                    raise AgentError("get_card_summary 参数必须是 period。")
                period = args.get("period") or date.today().strftime("%Y-%m")
                results.append({"name": name, "result": self.store.card_summary(period)})
            elif name == "preview_temporary_lock":
                if set(args) != {"card_id"} or args.get("card_id") != "demo-card-0428":
                    raise AgentError("只能预览演示卡片的临时锁定。")
                pending = self.store.plan({"card_id": "demo-card-0428"})
                results.append({"name": name, "result": pending})
            elif name == "compare_products":
                if set(args) != {"days", "accept_loss"}:
                    raise AgentError("compare_products 参数不完整。")
                days, loss = args.get("days"), args.get("accept_loss")
                result = self.store.compare({"days": days, "accept_loss": loss})
                results.append({"name": name, "result": result})
            elif name == "preview_simulated_purchase":
                required = {"code", "amount_cents", "need_date", "accept_loss"}
                if not required <= set(args) or not set(args) <= required | {"funding"}:
                    raise AgentError("模拟申购预览参数不完整。")
                pending = self.store.order_preview(args) if "funding" in args else self.store.orders.preview(args)
                results.append({"name": name, "result": pending})
            elif name == "query_order":
                if set(args) != {"order_id"} or not isinstance(args.get("order_id"), str):
                    raise AgentError("query_order 参数必须是 order_id。")
                results.append({"name": name, "result": self.store.orders.query(args.get("order_id", ""))})
        return {
            "contract_version": CONTRACT_VERSION,
            "source": "llm-validated",
            "message": message,
            "intent": intent,
            "answer": model.get("answer", ""),
            "tool_results": results,
            "requires_confirmation": pending is not None,
            "pending": pending,
            "limitations": [
                "模型输出只用于理解和规划；金额、卡片状态、账单事实和订单状态由服务端重新计算。",
                "approve、账本写入、卡片执行和订单确认不属于 LLM bridge 白名单，必须调用独立确认接口。",
            ],
        }
