"""FinNexus local research prototype. Synthetic data; no model or bank connection."""
from __future__ import annotations
import argparse, hashlib, json, secrets, threading, time, uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from vendor.io_utils import atomic_write_json
from vendor.schema_contracts import SchemaStore
from ledger import Ledger, LedgerConflict
from funds import FundTracker, FundConflict
from insights import Insights

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
        self.ledger = Ledger(self.root)
        self.funds = FundTracker(self.root)
        self.insights = Insights(self.root, self.ledger, self.funds)
        if not self.file.exists(): self.reset()
    def read(self):
        return json.loads(self.file.read_text(encoding="utf-8"))
    def write(self, state):
        atomic_write_json(self.file, state)
    def event(self, state, name, **data):
        state["events"].append(dict(at=timestamp(), event=name, **data))
    def reset(self):
        with self.lock:
            state = dict(card=dict(id="demo-card-0428", last4="0428", status="ACTIVE", version=1),
                         plans={}, receipts={}, events=[], balance_cents=1800000)
            self.event(state, "demo.initialized", scope="synthetic-single-user-local")
            self.write(state)
            return self.public()
    def public(self):
        state = self.read()
        return dict(card=state["card"], balance_cents=state["balance_cents"], summary=summary(),
                    transactions=TX, receipts=list(state["receipts"].values()), events=state["events"],
                    mode="RULE_BASED_PROTOTYPE_NO_LLM", synthetic=True)
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
        if set(payload)!={"days","accept_loss"} or type(payload["days"]) is not int or payload["days"] not in (30,90) or type(payload["accept_loss"]) is not bool:
            raise ValueError("请选择 30 天或 90 天用款时间，并选择能否承受本金损失。")
        # This is a fictional product-condition illustration, not suitability assessment.
        products=[
            dict(id="P01", name="示例产品 A", term=7, detail="持有满 7 天后可申请赎回；本演示假设到账还需 2 天。"),
            dict(id="P02", name="示例产品 B", term=90, detail="持有满 90 天后可申请赎回；本演示假设到账还需 2 天。"),
        ]
        for p in products:
            p["eligible"]=payload["accept_loss"] and p["term"]+2<=payload["days"]
            p["reason"]="未被当前两项条件排除；仍缺正式测评和完整产品资料，不能申购。" if p["eligible"] else ("你选择不能承受本金损失，排除本演示中的非保本产品。" if not payload["accept_loss"] else "最早可用资金时间晚于你的用款日期。")
        return dict(products=products, purchasing_enabled=False,
                    note="合成产品、简化日历规则，无收益率。这里只比较两项条件，不是完整适当性评估。")
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
            raw=json.dumps(payload,ensure_ascii=False).encode() if kind.startswith("application/json") else payload
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
            if path=="/api/ledger":return self.send(200,store.ledger.public())
            if path=="/api/ledger/backup":return self.send(200,store.ledger.backup())
            if path=="/api/funds":return self.send(200,store.funds.public())
            if path=="/api/insights/report":
                try:return self.send(200,store.insights.get_report(parse_qs(urlsplit(self.path).query).get('period',[''])[0]))
                except (ValueError,TypeError):return self.send(400,dict(error="请选择有效且已经开始的年份或月份。"))
            if path=="/api/funds/detail":
                try:
                    q=parse_qs(urlsplit(self.path).query)
                    return self.send(200,store.funds.detail(q.get("code",[""])[0],int(q.get("months",["1"])[0]),q.get("mode",["actual"])[0]))
                except (ValueError,TypeError):return self.send(400,dict(error="产品或时间区间无效。"))
            if path=="/api/evidence":return self.send(200,store.public())
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
                limit = 6 * 1024 * 1024 if self.path in ("/api/ledger/restore-preview", "/api/ledger/restore") else 8192
                if not 0<size<=limit or self.headers.get("Content-Type")!="application/json":raise ValueError("请求无效或备份过大（最多 5 MB）。")
                payload=json.loads(self.rfile.read(size))
                if not isinstance(payload,dict):raise ValueError("请求必须为对象。")
                actions={"/api/plan":store.plan,"/api/approve":store.approve,"/api/compare":store.compare,"/api/feedback":store.feedback}
                actions.update({"/api/ledger/save":store.ledger.save,"/api/ledger/delete":store.ledger.delete})
                actions.update({"/api/ledger/restore-preview":store.ledger.preview_restore,"/api/ledger/restore":store.ledger.restore})
                actions.update({"/api/funds/settings":store.funds.settings,"/api/funds/sync":store.funds.request_sync,
                    "/api/funds/trade/save":store.funds.save_trade,"/api/funds/trade/delete":store.funds.delete_trade})
                actions.update({"/api/insights/feedback":store.insights.feedback,"/api/insights/preview":store.insights.preview})
                if self.path=="/api/reset":
                    if payload!={"confirm":True}:raise ValueError("需要确认重置。")
                    return self.send(200,store.reset())
                if self.path not in actions:return self.send(404,dict(error="不存在该操作。"))
                return self.send(200,actions[self.path](payload))
            except (Conflict,LedgerConflict,FundConflict) as exc:self.send(409,dict(error=str(exc)))
            except (ValueError,TypeError) as exc:self.send(400,dict(error=str(exc)))
            except Exception:self.send(500,dict(error="本地服务发生错误，请检查服务窗口；不要重复提交状态不明的操作。"))
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(("127.0.0.1",port),Handler)
    store.funds.start_scheduler()
    print(f"FinNexus prototype: http://127.0.0.1:{port} (synthetic data, no LLM)",flush=True)
    try:server.serve_forever()
    finally:store.funds.stop.set();server.server_close()

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--port",type=int,default=18128)
    parser.add_argument("--data-dir",type=Path,default=ROOT/"data")
    args=parser.parse_args()
    serve(args.port,args.data_dir)

