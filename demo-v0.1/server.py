"""FinNexus local research prototype. Synthetic data; no model or bank connection."""
from __future__ import annotations
import argparse, calendar, hashlib, json, re, secrets, threading, time, uuid
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from vendor.io_utils import atomic_write_json
from vendor.schema_contracts import SchemaStore
from ledger import Ledger, LedgerConflict
from ledger_import import preview_payload
from funds import FundTracker, FundConflict
from insights import Insights
from agent import EquilibriumAgent, AgentError
from orders import OrderBook, OrderConflict

ROOT = Path(__file__).resolve().parent
SCHEMAS = SchemaStore(ROOT / "schemas")
TX = [
    dict(id="T01", date="2026-09-01", merchant="示例公司工资", category="收入", cents=1200000, kind="income"),
    dict(id="T02", date="2026-09-02", merchant="房租", category="居住", cents=350000, kind="expense"),
    dict(id="T03", date="2026-09-03", merchant="日常餐饮", category="餐饮", cents=126000, kind="expense"),
    dict(id="T04", date="2026-09-05", merchant="超市采购", category="生活", cents=68000, kind="expense"),
    dict(id="T05", date="2026-09-07", merchant="公共交通", category="出行", cents=26000, kind="expense"),
    dict(id="T06", date="2026-09-10", merchant="购物订单", category="购物", cents=86000, kind="expense"),
    dict(id="T07", date="2026-09-12", merchant="购物退款 · 对应 T06", category="购物", cents=20000, kind="refund"),
    dict(id="T08", date="2026-09-14", merchant="水电与通信", category="居住", cents=42000, kind="expense"),
    dict(id="T09", date="2026-09-18", merchant="STREAM SERVICE（示例商户）", category="待核实", cents=12900, kind="expense"),
    dict(id="T10", date="2026-09-20", merchant="其他自有账户转入", category="账户划转", cents=200000, kind="transfer"),
]
def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
def timestamp():
    return datetime.now(timezone.utc).isoformat()
def summary():
    income = sum(t["cents"] for t in TX if t["kind"] == "income")
    categories = {}
    for t in TX:
        if t["kind"] in ("expense", "refund"):
            categories[t["category"]] = categories.get(t["category"], 0) + t["cents"] * (-1 if t["kind"] == "refund" else 1)
    return dict(income=income, net_expense=sum(categories.values()), categories=categories,
                note="2026 年 9 月合成账单，截止 9 月 28 日。支出扣除退款，自有账户划转不计收入。当前余额独立给定，不由本月收支直接推算。")

class Conflict(ValueError): pass
class Store:
    def __init__(self, root):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.file = self.root / "state.json"; self.lock = threading.RLock()
        self.bindings_file = self.root / "bindings.json"
        self.cases_file = self.root / "cases.json"
        self.budgets_file = self.root / "budgets.json"
        self.ledger = Ledger(self.root)
        self.funds = FundTracker(self.root)
        self.insights = Insights(self.root, self.ledger, self.funds)
        self.agent = EquilibriumAgent(self)
        self.orders = OrderBook(self.root)
        if not self.file.exists(): self.reset()
        if not self.bindings_file.exists(): atomic_write_json(self.bindings_file, {"version": 1, "items": {}})
        if not self.cases_file.exists(): atomic_write_json(self.cases_file, {"version": 1, "items": {}})
        if not self.budgets_file.exists(): atomic_write_json(self.budgets_file, {"version": 1, "items": {}})
    def read(self):
        return json.loads(self.file.read_text(encoding="utf-8"))
    def write(self, state):
        atomic_write_json(self.file, state)
    def event(self, state, name, **data):
        state["events"].append(dict(at=timestamp(), event=name, **data))
    def reset(self):
        with self.lock:
            state = dict(card=dict(id="demo-card-0428", last4="0428", status="ACTIVE", version=1,
                                   billing_day=25, payment_due_day=10, credit_limit_cents=5000000,
                                   autopay=False),
                         plans={}, receipts={}, events=[], balance_cents=1800000)
            self.event(state, "demo.initialized", scope="synthetic-single-user-local")
            self.write(state)
            return self.public()
    def public(self):
        state = self.read()
        # Migrate older demo state files without changing their card status.
        state["card"].setdefault("billing_day", 25); state["card"].setdefault("payment_due_day", 10)
        state["card"].setdefault("credit_limit_cents", 5000000); state["card"].setdefault("autopay", False)
        return dict(card=state["card"], balance_cents=state["balance_cents"], summary=summary(),
                    transactions=TX, receipts=list(state["receipts"].values()), events=state["events"],
                    mode="RULE_BASED_PROTOTYPE_NO_LLM", synthetic=True)
    def card_summary(self, period=None):
        period = period or date.today().strftime("%Y-%m")
        try: year, month = map(int, period.split("-")); start=date(year, month, 1)
        except (ValueError, TypeError): raise ValueError("请选择有效账单月份。")
        end=date(year, month, calendar.monthrange(year, month)[1])
        state=self.public(); card=state["card"]
        rows=[t for t in TX if t.get("kind") in ("expense", "refund") and start.isoformat()<=t["date"]<=end.isoformat()]
        expense=sum(t["cents"]*( -1 if t["kind"]=="refund" else 1) for t in rows)
        today=date.today(); due=date(today.year,today.month,min(card["payment_due_day"],calendar.monthrange(today.year,today.month)[1]))
        if due<today:
            next_month=1 if today.month==12 else today.month+1; next_year=today.year+1 if today.month==12 else today.year
            due=date(next_year,next_month,min(card["payment_due_day"],calendar.monthrange(next_year,next_month)[1]))
        return dict(card=card,period=period,transaction_count=len(rows),net_expense_cents=expense,
                    suspicious=[t for t in rows if t.get("category")=="待核实"],next_payment_due=due.isoformat(),
                    days_to_due=(due-today).days,utilization_bps=round(expense*10000/card["credit_limit_cents"]) if card["credit_limit_cents"] else None,
                    note="合成卡片账单摘要；还款日、额度和自动还款状态仅用于演示，不代表真实银行账户。")
    def cross_scene_summary(self, period=None):
        """Join ledger risk evidence with the demo card state for the P0 flow."""
        period = period or date.today().strftime("%Y-%m")
        report = self.insights.get_report(period)
        state = self.public()
        suspicious = [t for t in state["transactions"] if t.get("category") == "待核实"]
        return {
            "period": period,
            "ledger_version": report["version"],
            "card_version": state["card"]["version"],
            "card": state["card"],
            "suspicious_transactions": suspicious,
            "ledger_candidates": report["candidates"],
            "action": "preview_temporary_lock" if suspicious and state["card"]["status"] == "ACTIVE" else "review",
            "explanation": "发现待核实扣款，可先预览临时锁卡；锁卡不会撤回既有交易。" if suspicious else "当前没有合成待核实扣款。",
        }
    def bindings(self):
        data = json.loads(self.bindings_file.read_text(encoding="utf-8"))
        return data.get("items", {})
    def save_binding(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("卡片绑定参数不完整。")
        if "binding_status" in payload or "binding_source" in payload:
            payload = dict(payload); payload["status"] = payload.pop("binding_status", payload.get("status")); payload["source"] = payload.pop("binding_source", payload.get("source"))
        required = {"entry_id", "card_id", "card_last4", "status", "source"}
        if set(payload) != required: raise ValueError("卡片绑定参数不完整。")
        if not isinstance(payload["entry_id"], str) or not payload["entry_id"]:
            raise ValueError("账单记录编号无效。")
        if payload["card_id"] != "demo-card-0428" or not isinstance(payload["card_last4"], str) or not payload["card_last4"].isdigit() or len(payload["card_last4"]) != 4:
            raise ValueError("当前仅支持绑定演示卡片尾号。")
        if payload["status"] not in ("linked", "needs_review") or payload["source"] not in ("manual", "imported", "inferred"):
            raise ValueError("绑定状态或来源无效。")
        if payload["entry_id"] not in {row["id"] for row in self.ledger.public()["entries"]}:
            raise ValueError("账单记录不存在。")
        with self.lock:
            data = json.loads(self.bindings_file.read_text(encoding="utf-8"))
            data["items"][payload["entry_id"]] = dict(payload, binding_status=payload["status"], binding_source=payload["source"])
            data["version"] += 1
            atomic_write_json(self.bindings_file, data)
            return dict(binding=data["items"][payload["entry_id"]], version=data["version"])
    def create_case(self, payload):
        if not isinstance(payload, dict) or set(payload) != {"period", "ledger_version", "transaction_ids"} or not isinstance(payload["transaction_ids"], list) or not payload["transaction_ids"]:
            raise ValueError("案件参数不完整。")
        report = self.insights.get_report(payload["period"])
        if report["version"] != payload["ledger_version"]:
            raise Conflict("账本已变化，请重新生成分析报告。")
        known = {row["id"] for row in self.ledger.public()["entries"]}
        if any(item not in known for item in payload["transaction_ids"]):
            raise ValueError("案件包含不存在的账单记录。")
        with self.lock:
            data = json.loads(self.cases_file.read_text(encoding="utf-8"))
            case_id = "case-" + uuid.uuid4().hex[:12]
            case = {"id": case_id, "period": payload["period"], "ledger_version": payload["ledger_version"], "transaction_ids": payload["transaction_ids"], "status": "OPEN", "status_label": "待核查", "timeline": [{"status": "OPEN", "status_label": "待核查", "at": timestamp(), "actor_type": "user", "source": "user", "evidence_id": case_id + ":0"}]}
            data["items"][case_id] = case; data["version"] += 1
            atomic_write_json(self.cases_file, data)
            return case
    def cases(self):
        data = json.loads(self.cases_file.read_text(encoding="utf-8"))
        return list(data.get("items", {}).values())
    def transition_case(self, payload):
        if not isinstance(payload, dict) or set(payload) != {"case_id", "action"}:
            raise ValueError("案件操作参数不完整。")
        transitions = {"review": ("OPEN", "UNDER_REVIEW"), "lock_previewed": ("OPEN", "LOCK_PREVIEWED"), "locked": ("LOCK_PREVIEWED", "LOCKED"), "submit": ("UNDER_REVIEW", "SUBMITTED"), "close": (("OPEN", "UNDER_REVIEW", "SUBMITTED", "LOCKED", "LOCK_PREVIEWED"), "CLOSED"), "mark_normal": (("OPEN", "UNDER_REVIEW"), "CONFIRMED_NORMAL")}
        if payload["action"] not in transitions: raise ValueError("不支持的案件操作。")
        with self.lock:
            data = json.loads(self.cases_file.read_text(encoding="utf-8")); case = data["items"].get(payload["case_id"])
            if not case: raise ValueError("案件不存在。")
            expected, target = transitions[payload["action"]]; allowed = expected if isinstance(expected, tuple) else (expected,)
            if case["status"] not in allowed: raise Conflict("当前案件状态不允许执行该操作。")
            if target == "LOCKED":
                current = self.read()
                bindings = self.bindings()
                linked = [bindings.get(key, {}) for key in case["transaction_ids"]]
                if not linked or any(b.get("card_id") != current["card"]["id"] or b.get("binding_status") != "linked" for b in linked):
                    raise Conflict("案件尚未关联到当前模拟卡片，请先核对卡片绑定。")
                if current["card"]["status"] != "LOCKED" or not any(r.get("status") == "VERIFIED" for r in current["receipts"].values()):
                    raise Conflict("卡片尚未完成锁卡核验，请先预览并确认模拟锁卡，再更新案件。")
            labels = {"UNDER_REVIEW":"核查中", "LOCK_PREVIEWED":"已预览锁卡", "LOCKED":"已锁卡", "SUBMITTED":"已提交银行", "CONFIRMED_NORMAL":"已确认正常", "CLOSED":"已关闭"}
            case["status"] = target; case["status_label"] = labels.get(target, target); case["timeline"].append({"status": target, "status_label": case["status_label"], "at": timestamp(), "actor_type": "user", "source": "user", "action": payload["action"], "evidence_id": case["id"] + ":" + str(len(case["timeline"]))}); data["version"] += 1
            atomic_write_json(self.cases_file, data)
            return case
    def demo_seed(self):
        """Load a deterministic cross-scene case for a stable live demo."""
        with self.lock:
            self.reset()
            data = self.ledger.read()
            rows = [
                {"id":"demo-bill-0428", "revision":1, "kind":"expense", "cents":12900,
                 "date":"2026-09-18", "category":"娱乐", "note":"STREAM SERVICE（演示陌生扣款）"},
                {"id":"demo-income-01", "revision":1, "kind":"income", "cents":1200000,
                 "date":"2026-09-01", "category":"工资", "note":"演示工资入账"},
            ]
            for row in rows:
                data["entries"][row["id"]] = row
            atomic_write_json(self.ledger.file, data)
            bindings = {"version": 1, "items": {"demo-bill-0428": {
                "entry_id":"demo-bill-0428", "card_id":"demo-card-0428", "card_last4":"0428",
                "status":"linked", "source":"demo", "binding_status":"linked", "binding_source":"demo"}}}
            existing_bindings = json.loads(self.bindings_file.read_text(encoding="utf-8"))
            existing_bindings["items"].update(bindings["items"]); existing_bindings["version"] += 1
            atomic_write_json(self.bindings_file, existing_bindings)
            cases = json.loads(self.cases_file.read_text(encoding="utf-8")); cases["version"] += 1
            report = self.insights.get_report("2026-09")
            case_id = "case-demo-0428"
            cases["items"][case_id] = {"id": case_id, "period":"2026-09", "ledger_version":report["version"],
                "transaction_ids":["demo-bill-0428"], "status":"OPEN", "status_label":"待核查",
                "timeline":[{"status":"OPEN", "status_label":"待核查", "at":timestamp(), "actor_type":"system", "source":"demo", "evidence_id":case_id+":0"}]}
            atomic_write_json(self.cases_file, cases)
            return self.public()
    def demo_clear(self):
        """Remove demo-only ledger records and case artifacts while preserving user data."""
        with self.lock:
            # Return the simulated card to ACTIVE and clear demo receipts/events too.
            self.reset()
            data = self.ledger.read()
            for entry_id in ("demo-bill-0428", "demo-income-01"):
                data["entries"].pop(entry_id, None)
            atomic_write_json(self.ledger.file, data)
            bindings = json.loads(self.bindings_file.read_text(encoding="utf-8"))
            bindings["items"].pop("demo-bill-0428", None); bindings["version"] += 1
            atomic_write_json(self.bindings_file, bindings)
            cases = json.loads(self.cases_file.read_text(encoding="utf-8"))
            cases["items"].pop("case-demo-0428", None); cases["version"] += 1
            atomic_write_json(self.cases_file, cases)
            return self.public()
    def demo_evidence(self):
        """Export one self-contained, labelled evidence package for the demo run."""
        return {"format":"equilibrium-demo-evidence","version":1,"generated_at":timestamp(),
                "demo_scope":"synthetic-local-only","run":self.public(),"ledger":self.ledger.public(),
                "bindings":self.bindings(),"cases":self.cases(),"budgets":self.budgets(),"reminders":self.reminders(),
                "limitations":["所有数据均为本机合成或用户手动录入。","不代表银行审计记录，也不会执行真实资金操作。"]}
    def reminders(self, period=None):
        period = period or date.today().strftime("%Y-%m")
        card = self.card_summary(period)
        rows = [{"id": "card-due-" + period, "type": "card_payment_due", "date": card["next_payment_due"], "title": "卡片还款日", "body": f"演示卡片尾号 0428 距还款日 {card['days_to_due']} 天。", "source_ids": []}]
        for case in self.cases():
            if case["status"] != "CLOSED":
                rows.append({"id": case["id"], "type": "open_case", "date": date.today().isoformat(), "title": "待处理账单案件", "body": f"案件 {case['id']} 当前状态：{case['status']}。", "source_ids": case["transaction_ids"]})
        report = self.insights.get_report(period)
        for item in (report.get("recurring_candidates") or []):
            reason = item.get("reason", {})
            rows.append({"id": "recurring-" + item["key"] if item.get("key") else "recurring-" + str(item["ids"][0]), "type": "recurring_candidate", "date": period + "-01", "title": "可能的固定支出或订阅", "body": f"{reason.get('merchant', '某项支出')}近120天出现 {reason.get('occurrences', 0)} 次，请人工确认。", "source_ids": item.get("ids", [])})
        return {"period": period, "items": rows}
    def ledger_import_preview(self, payload):
        snapshot = self.ledger.public()
        return dict(preview_payload(payload, snapshot["entries"]),
                    ledger_version=snapshot["version"])
    def ledger_import(self, payload):
        if not isinstance(payload, dict) or set(payload) != {"version", "rows", "confirm"}:
            raise ValueError("导入参数无效。")
        result = self.ledger.import_rows(payload)
        for row in payload["rows"]:
            if row.get("card_last4"):
                self.save_binding({"entry_id": row["id"], "card_id": "demo-card-0428", "card_last4": row["card_last4"], "status": "linked", "source": "imported"})
        return result
    def reminders_ics(self, period=None):
        items = self.reminders(period)["items"]
        def esc_ics(value): return str(value).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Equilibrium AI//Reminders//CN"]
        for item in items:
            lines += ["BEGIN:VEVENT", "UID:" + esc_ics(item["id"]) + "@equilibrium.local", "DTSTAMP:" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"), "DTSTART;VALUE=DATE:" + item["date"].replace("-", ""), "SUMMARY:" + esc_ics(item["title"]), "DESCRIPTION:" + esc_ics(item["body"]), "END:VEVENT"]
        lines.append("END:VCALENDAR"); return "\r\n".join(lines) + "\r\n"
    def budgets(self, period=None):
        period = period or date.today().strftime("%Y-%m")
        if not isinstance(period, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period): raise ValueError("请选择有效预算月份。")
        raw=json.loads(self.budgets_file.read_text(encoding="utf-8")); item=raw["items"].get(period)
        totals=self.ledger.public()["months"].get(period,{"income":0,"expense":0,"balance":0,"categories":{"expense":{}}})
        total=item.get("total_cents") if item else None; categories=item.get("categories",{}) if item else {}
        rows=[]
        for name in sorted(set(categories) | set(totals.get("categories",{}).get("expense",{}))):
            spent=totals.get("categories",{}).get("expense",{}).get(name,0)
            limit=categories.get(name); rows.append({"category":name,"budget_cents":limit,"spent_cents":spent,"remaining_cents":limit-spent if limit is not None else None,"used_bps":round(spent*10000/limit) if limit else None,"over":bool(limit is not None and spent>limit)})
        spent=totals.get("expense",0)
        return {"period":period,"version":raw["version"],"configured":bool(item),"total_cents":total,"spent_cents":spent,"remaining_cents":total-spent if total is not None else None,"used_bps":round(spent*10000/total) if total else None,"over":bool(total is not None and spent>total),"categories":rows,"category_budgets":categories,"note":"预算只使用你主动设置的金额，不从历史支出推断目标。"}
    def save_budgets(self, payload):
        if not isinstance(payload,dict) or set(payload)!={"period","version","total_cents","categories"}: raise ValueError("预算参数不完整。")
        if not isinstance(payload["period"],str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])",payload["period"]): raise ValueError("预算月份无效。")
        if type(payload["version"]) is not int or (payload["total_cents"] is not None and (type(payload["total_cents"]) is not int or not 0<=payload["total_cents"]<=99999999999)): raise ValueError("月度预算金额无效。")
        if not isinstance(payload["categories"],dict): raise ValueError("分类预算格式无效。")
        categories={}
        for name,cents in payload["categories"].items():
            if not isinstance(name,str) or not 1<=len(name.strip())<=20 or type(cents) is not int or not 0<=cents<=99999999999: raise ValueError("分类预算金额无效。")
            categories[name.strip()]=cents
        with self.lock:
            data=json.loads(self.budgets_file.read_text(encoding="utf-8"))
            if payload["version"]!=data["version"]: raise Conflict("预算已在其他页面更新，请刷新后重试。")
            data["items"][payload["period"]]={"total_cents":payload["total_cents"],"categories":categories,"updated_at":timestamp()};data["version"]+=1
            atomic_write_json(self.budgets_file,data)
        return self.budgets(payload["period"])
    def order_preview(self, payload):
        """Attach the current ledger cash safety reference when funding is supplied."""
        if not isinstance(payload, dict):
            raise ValueError("申购预览参数不完整。")
        data = dict(payload)
        funding = data.pop("funding", None)
        if funding is not None:
            period = date.today().strftime("%Y-%m")
            report = self.insights.get_report(period)
            from insights import funding_check
            data["funding_check"] = funding_check(funding, date.today(), report.get("cash_safety"))
        return self.orders.preview(data)
    def plan(self, payload):
        errors = SCHEMAS.validate(payload, "lock-request.json")
        if errors: raise ValueError("仅支持示例卡片的临时锁卡，请重新选择。")
        with self.lock:
            state = self.read(); card = state["card"]
            if card["status"] != "ACTIVE": raise Conflict("卡片已临时锁定，无需重复操作。")
            if len(state["plans"]) > 200: raise Conflict("体验计划已达上限，请重置演示。")
            plan = dict(id="plan-" + uuid.uuid4().hex[:12], card_id=card["id"], before_version=card["version"],
                        before_status=card["status"], action="TEMPORARY_LOCK", after_status="LOCKED",
                        expires_at=time.time()+300, environment="DEMO_ONLY")
            plan_hash=digest(plan)
            state["plans"][plan["id"]]=dict(plan=plan, hash=plan_hash)
            self.event(state,"plan.frozen", plan_id=plan["id"], plan_hash=plan_hash)
            self.write(state)
            return dict(plan=plan, plan_hash=plan_hash, last4=card["last4"])
    def approve(self, payload):
        errors=SCHEMAS.validate(payload,"approval.json")
        if errors: raise ValueError("需要勾选确认，并提交原操作计划。")
        with self.lock:
            state=self.read()
            saved=state["plans"].get(payload["plan_id"])
            if not saved: raise Conflict("未找到操作计划，请重新预览。")
            plan=saved["plan"]
            if saved["hash"]!=digest(plan) or payload["plan_hash"]!=saved["hash"]:
                raise Conflict("计划与预览不一致，请重新预览并确认。")
            if plan["id"] in state["receipts"]:
                return dict(receipt=state["receipts"][plan["id"]], replayed=True)
            if time.time()>plan["expires_at"]: raise Conflict("确认已过期，请重新预览。")
            card=state["card"]
            if card["id"]!=plan["card_id"] or card["version"]!=plan["before_version"] or card["status"]!=plan["before_status"]:
                raise Conflict("卡片状态发生变化，原计划不能执行。请刷新并重新预览。")
            self.event(state,"approval.recorded",plan_id=plan["id"], plan_hash=saved["hash"],
                       actor="local-demo-participant", real_identity_verified=False)
            card["status"]=plan["after_status"]; card["version"]+=1
            receipt=dict(id="receipt-"+uuid.uuid4().hex[:10], plan_id=plan["id"],
                         last4=card["last4"], status="APPLIED", card_status=card["status"], at=timestamp(),
                         note="仅模拟卡片状态已改变；未撤回任何账单交易，无真实银行操作。")
            state["receipts"][plan["id"]]=receipt
            self.event(state,"operation.applied",plan_id=plan["id"],card_status=card["status"])
            self.write(state)
            # Re-read persisted business state, rather than trusting submitted parameters.
            verified=self.read()
            if verified["card"]["status"]!="LOCKED": raise Conflict("状态核验未通过，请检查记录。")
            verified["receipts"][plan["id"]]["status"]="VERIFIED"
            self.event(verified,"state.verified",plan_id=plan["id"],card_status="LOCKED")
            self.write(verified)
            return dict(receipt=verified["receipts"][plan["id"]], replayed=False)
    def compare(self,payload):
        if not isinstance(payload,dict) or not {"days","accept_loss"}<=set(payload) or type(payload["days"]) is not int or payload["days"] not in (30,90) or type(payload["accept_loss"]) is not bool:
            raise ValueError("请选择 30 天或 90 天用款时间，并选择能否承受本金损失。")
        today=date.today(); need_date=payload.get("need_date") or (today+__import__('datetime').timedelta(days=payload["days"])).isoformat()
        try: need=date.fromisoformat(need_date)
        except ValueError: raise ValueError("到账日期无效。") from None
        if need<today: raise ValueError("到账日期不能早于今天。")
        # This is a fictional product-condition illustration, not suitability assessment.
        products=[
            dict(id="P01", name="示例产品 A", term=7, settle_days=2, detail="持有满 7 天后可申请赎回；到账还需 2 天。", data_date=today.isoformat(), freshness="fresh"),
            dict(id="P02", name="示例产品 B", term=90, settle_days=2, detail="持有满 90 天后可申请赎回；到账还需 2 天。", data_date=today.isoformat(), freshness="fresh"),
        ]
        for p in products:
            p["redemption_date"]=(today+__import__('datetime').timedelta(days=p["term"])).isoformat();p["arrival_date"]=(today+__import__('datetime').timedelta(days=p["term"]+p["settle_days"])).isoformat();p["missing_information"]=["正式风险测评","在售状态","完整费用与到账规则"]
            reasons=[]
            if not payload["accept_loss"]: reasons.append("你选择不能承受本金损失，排除本演示中的非保本产品。")
            if p["arrival_date"]>need_date: reasons.append("预计到账日晚于你的用款日期。")
            p["eligible"]=not reasons;p["exclusion_reasons"]=reasons;p["reason"]="符合当前期限与到账日期条件，但仍缺少正式资料，不能直接申购。" if p["eligible"] else "；".join(reasons)
        comparison=[{"criterion":"持有期限","need_date":need_date,"options":[{"id":p["id"],"value":p["term"],"unit":"天"} for p in products]},{"criterion":"预计到账","need_date":need_date,"options":[{"id":p["id"],"value":p["arrival_date"]} for p in products]},{"criterion":"数据新鲜度","options":[{"id":p["id"],"value":p["freshness"]} for p in products]}]
        return dict(products=products, comparison=comparison, purchasing_enabled=False,
                    note="只比较持有期限、预计到账日期和数据新鲜度；资料不足不视为推荐，也不会生成申购订单。")
    def feedback(self,payload):
        if set(payload)!={"useful","note"} or payload["useful"] not in ("yes","maybe","no") or not isinstance(payload["note"],str) or not 1<=len(payload["note"].strip())<=1000:
            raise ValueError("请选择评价并填写 1—1000 字反馈，请勿填写身份或账户信息。")
        with self.lock:
            path=self.root/"feedback.json"
            rows=json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
            row=dict(id=uuid.uuid4().hex[:10],at=timestamp(),version="0.1",**payload)
            rows.append(row);atomic_write_json(path,rows)
            return dict(saved=True,id=row["id"])

def serve(port, data_dir=None):
    store=Store(data_dir or ROOT/"data");token=secrets.token_urlsafe(32)
    hosts={f"127.0.0.1:{port}",f"localhost:{port}"}
    origins={"http://"+h for h in hosts}
    class Handler(BaseHTTPRequestHandler):
        def send(self,status,payload,kind="application/json; charset=utf-8"):
            raw=json.dumps(payload,ensure_ascii=False).encode() if kind.startswith("application/json") else (payload.encode("utf-8") if isinstance(payload,str) else payload)
            self.send_response(status)
            self.send_header("Content-Type",kind);self.send_header("Content-Length",str(len(raw)))
            self.send_header("Cache-Control","no-store");self.send_header("X-Content-Type-Options","nosniff")
            self.send_header("Content-Security-Policy","default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers();self.wfile.write(raw)
        def valid_host(self):
            return self.headers.get("Host") in hosts
        def do_GET(self):
            if not self.valid_host(): return self.send(403,dict(error="仅允许本机访问。"))
            path=urlsplit(self.path).path
            if path=="/api/state":return self.send(200,dict(**store.public(),csrf_token=token))
            if path=="/api/ledger":return self.send(200,dict(store.ledger.public(),bindings=store.bindings()))
            if path=="/api/bindings":return self.send(200,dict(bindings=store.bindings()))
            if path=="/api/cases":return self.send(200,dict(cases=store.cases()))
            if path=="/api/reminders":
                try:return self.send(200,store.reminders(parse_qs(urlsplit(self.path).query).get('period',[None])[0]))
                except (ValueError,TypeError):return self.send(400,dict(error="请选择有效账单月份。"))
            if path=="/api/reminders.ics":
                try:return self.send(200,store.reminders_ics(parse_qs(urlsplit(self.path).query).get('period',[None])[0]),"text/calendar; charset=utf-8")
                except (ValueError,TypeError):return self.send(400,dict(error="请选择有效账单月份。"))
            if path=="/api/budgets":
                try:return self.send(200,store.budgets(parse_qs(urlsplit(self.path).query).get('period',[None])[0]))
                except (ValueError,TypeError):return self.send(400,dict(error="请选择有效预算月份。"))
            if path=="/api/ledger/backup":return self.send(200,store.ledger.backup())
            if path=="/api/funds":return self.send(200,store.funds.public())
            if path=="/api/orders":return self.send(200,store.orders.public())
            if path=="/api/cross-scene":
                try:return self.send(200,store.cross_scene_summary(parse_qs(urlsplit(self.path).query).get('period',[None])[0]))
                except (ValueError,TypeError):return self.send(400,dict(error="请选择有效且已经开始的年份或月份。"))
            if path=="/api/card/summary":
                try:return self.send(200,store.card_summary(parse_qs(urlsplit(self.path).query).get('period',[None])[0]))
                except (ValueError,TypeError):return self.send(400,dict(error="请选择有效账单月份。"))
            if path=="/api/insights/report":
                try:return self.send(200,store.insights.get_report(parse_qs(urlsplit(self.path).query).get('period',[''])[0]))
                except (ValueError,TypeError):return self.send(400,dict(error="请选择有效且已经开始的年份或月份。"))
            if path=="/api/funds/detail":
                try:
                    q=parse_qs(urlsplit(self.path).query)
                    return self.send(200,store.funds.detail(q.get("code",[""])[0],int(q.get("months",["1"])[0]),q.get("mode",["actual"])[0]))
                except (ValueError,TypeError):return self.send(400,dict(error="产品或时间区间无效。"))
            if path=="/api/evidence" or path=="/api/demo/evidence":
                return self.send(200,store.demo_evidence())
            if path=="/api/feedback":
                fp=store.root/"feedback.json"
                return self.send(200,json.loads(fp.read_text(encoding="utf8")) if fp.exists() else [])
            files={"/":("index.html","text/html; charset=utf-8"),"/app.js":("app.js","text/javascript; charset=utf-8"),"/ledger.js":("ledger.js","text/javascript; charset=utf-8"),"/style.css":("style.css","text/css; charset=utf-8")}
            files["/ledger.css"]=("ledger.css","text/css; charset=utf-8")
            files["/statistics.js"]=("statistics.js","text/javascript; charset=utf-8")
            files["/funds.js"]=("funds.js","text/javascript; charset=utf-8")
            files["/funds.css"]=("funds.css","text/css; charset=utf-8")
            files["/insights.js"]=("insights.js","text/javascript; charset=utf-8")
            if path not in files:return self.send(404,dict(error="未找到页面。"))
            filename,kind=files[path];return self.send(200,(ROOT/"web"/filename).read_bytes(),kind)
        def do_POST(self):
            if not self.valid_host() or self.headers.get("Origin") not in origins or not secrets.compare_digest(self.headers.get("X-Demo-Token",""),token):
                return self.send(403,dict(error="会话校验失败，请刷新页面。"))
            try:
                size=int(self.headers.get("Content-Length","0"))
                request_path=urlsplit(self.path).path
                limit = 6 * 1024 * 1024 if request_path in ("/api/ledger/restore-preview", "/api/ledger/restore", "/api/ledger/import-preview", "/api/ledger/import") else 8192
                content_type=self.headers.get("Content-Type","").split(";",1)[0].strip().lower()
                if not 0<size<=limit or content_type!="application/json":raise ValueError("请求无效或备份过大（最多 5 MB）。")
                payload=json.loads(self.rfile.read(size))
                if not isinstance(payload,dict):raise ValueError("请求必须为对象。")
                actions={"/api/plan":store.plan,"/api/approve":store.approve,"/api/compare":store.compare,"/api/feedback":store.feedback}
                actions.update({"/api/ledger/save":store.ledger.save,"/api/ledger/delete":store.ledger.delete})
                actions.update({"/api/bindings/save":store.save_binding,"/api/cases/create":store.create_case,"/api/cases/transition":store.transition_case})
                actions.update({"/api/budgets/save":store.save_budgets})
                actions.update({"/api/ledger/restore-preview":store.ledger.preview_restore,"/api/ledger/restore":store.ledger.restore})
                actions.update({"/api/ledger/import-preview":store.ledger_import_preview,"/api/ledger/import":store.ledger_import})
                actions.update({"/api/funds/settings":store.funds.settings,"/api/funds/product/add":store.funds.add_product,"/api/funds/sync":store.funds.request_sync,
                    "/api/funds/trade/save":store.funds.save_trade,"/api/funds/trade/delete":store.funds.delete_trade})
                actions.update({"/api/insights/feedback":store.insights.feedback,"/api/insights/preview":store.insights.preview})
                actions.update({"/api/agent":store.agent.handle,"/api/agent/llm":store.agent.handle_llm_plan,
                    "/api/agent/chat":store.agent.handle_chat})
                actions.update({"/api/order/preview":store.order_preview,"/api/order/confirm":store.orders.confirm})
                actions.update({"/api/order/query":lambda p: store.orders.query(p.get("order_id",""))})
                if request_path=="/api/reset":
                    if payload!={"confirm":True}:raise ValueError("需要确认重置。")
                    return self.send(200,store.reset())
                if request_path=="/api/demo/seed":
                    if payload != {"confirm": True}: raise ValueError("需要确认准备演示数据。")
                    return self.send(200,store.demo_seed())
                if request_path=="/api/demo/clear":
                    if payload != {"confirm": True}: raise ValueError("需要确认清理演示数据。")
                    return self.send(200,store.demo_clear())
                if request_path not in actions:return self.send(404,dict(error="不存在该操作。"))
                return self.send(200,actions[request_path](payload))
            except (Conflict,LedgerConflict,FundConflict,OrderConflict) as exc:self.send(409,dict(error=str(exc)))
            except (ValueError,TypeError,AgentError) as exc:self.send(400,dict(error=str(exc)))
            except Exception:self.send(500,dict(error="本地服务发生错误，请检查服务窗口；不要重复提交状态不明的操作。"))
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(("127.0.0.1",port),Handler)
    store.funds.start_scheduler()
    print(f"FinNexus prototype: http://127.0.0.1:{port} (synthetic data; Qwen via /api/agent/chat when DASHSCOPE_API_KEY is set)",flush=True)
    try:server.serve_forever()
    finally:store.funds.stop.set();server.server_close()

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--port",type=int,default=18128)
    parser.add_argument("--data-dir",type=Path,default=ROOT/"data")
    args=parser.parse_args()
    serve(args.port,args.data_dir)
