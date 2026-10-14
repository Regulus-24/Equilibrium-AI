"""Public money-fund history, local scheduling and isolated transaction notebooks.

No model, account login or trading integration. External JavaScript is parsed as
JSON assignments only, never executed. One server process per data directory.
"""
from __future__ import annotations
import calendar, copy, hashlib, json, re, threading, uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from pathlib import Path
from urllib.request import Request, urlopen
from vendor.io_utils import atomic_write_json, atomic_write_text

CST = timezone(timedelta(hours=8))
CATALOG = [
    dict(code="000343", name="华夏财富宝货币A", aliases=["华夏财富宝货币A"]),
    dict(code="000359", name="易方达易理财货币A", aliases=["易方达易理财货币A"]),
    dict(code="000397", name="汇添富全额宝货币A", aliases=["汇添富全额宝货币A"]),
    dict(code="000389", name="广发天天红A", aliases=["广发天天红货币A", "广发天天红A"]),
    dict(code="000719", name="南方现金通货币E", aliases=["南方现金通E", "南方现金通货币E"]),
]
BY_CODE = {x["code"]: x for x in CATALOG}

def now():
    return datetime.now(CST)

def numeric(value, places=6, allow_zero=True):
    if not isinstance(value, str) or not re.fullmatch(r"\d{1,12}(?:\.\d{1,"+str(places)+r"})?", value):
        raise ValueError("金额或份额格式无效；金额最多2位、份额最多6位小数。")
    d = Decimal(value)
    if d < 0 or (not allow_zero and d == 0):
        raise ValueError("请输入大于0的数值。")
    return d

def iso_day(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("日期格式无效。")
    date.fromisoformat(value)
    return value

def month_start(end, months):
    n = end.year * 12 + end.month - 1 - months
    year, m = divmod(n, 12)
    return date(year, m+1, min(end.day, calendar.monthrange(year, m+1)[1]))

def assignment(text, name):
    m = re.search(r"\bvar\s+"+re.escape(name)+r"\s*=\s*(.*?);", text, re.S)
    if not m:
        raise ValueError("数据源结构变化：缺少"+name)
    return json.loads(m.group(1))

def parse_history(text, code, today=None):
    today = today or now().date()
    if assignment(text, "fS_code") != code or assignment(text, "fS_name") not in BY_CODE[code]["aliases"]:
        raise ValueError("来源的基金名称/代码与跟踪产品不一致。")
    def series(name):
        raw = assignment(text, name)
        if not isinstance(raw, list) or not raw or len(raw) > 30000:
            raise ValueError("历史数据为空或格式错误。")
        result = {}
        for p in raw:
            if not isinstance(p, list) or len(p) != 2 or type(p[0]) not in (int, float) or type(p[1]) not in (int, float):
                raise ValueError("历史数据包含非数值记录。")
            d = datetime.fromtimestamp(p[0]/1000, CST).date()
            v = Decimal(str(p[1]))
            if not v.is_finite() or abs(v) > 10000 or d > today or d.year < 1990:
                raise ValueError("历史数据日期或数值越界。")
            key = d.isoformat()
            if key in result and result[key] != str(v):
                raise ValueError("同日数据冲突。")
            result[key] = str(v)
        return result
    income, annual = series("Data_millionCopiesIncome"), series("Data_sevenDaysYearIncome")
    # Keep full public history to support old transaction cost bases.
    return [dict(date=d, per10k=v, annual7=annual.get(d), nav=None) for d,v in sorted(income.items())]

def fetch_history(code):
    url = "https://fund.eastmoney.com/pingzhongdata/"+code+".js"
    req = Request(url, headers={"User-Agent":"Mozilla/5.0", "Referer":"https://fund.eastmoney.com/"+code+".html"})
    with urlopen(req, timeout=15) as response:
        raw = response.read(5_000_001)
    if len(raw) > 5_000_000:
        raise ValueError("来源响应过大。")
    text = raw.decode("utf-8-sig")
    return parse_history(text, code), text

def performance(rows, months):
    if months not in (1,3,6,12):
        raise ValueError("仅支持近1、3、6个月和1年。")
    if not rows:
        return dict(points=[], start=None, end=None, coverage=False, return_pct=None)
    end = date.fromisoformat(rows[-1]["date"])
    start = month_start(end, months)
    chosen = [r for r in rows if start.isoformat() <= r["date"] <= end.isoformat()]
    factor = Decimal(1); expected=start; complete=True; points=[]
    for row in chosen:
        d=date.fromisoformat(row["date"])
        if d != expected: complete=False
        expected=d+timedelta(days=1)
        # The left date is a zero baseline; subsequent dates compound daily income.
        if d > start: factor *= 1+Decimal(row["per10k"])/10000
        points.append(dict(**row, daily_pct=str(Decimal(row["per10k"])/100),
                           cumulative_pct=str((factor-1)*100) if complete else None))
    return dict(points=points,start=start.isoformat(),end=end.isoformat(),coverage=complete,
                return_pct=str((factor-1)*100) if complete else None)

def estimate(rows, trades, mode):
    """Cash-flow-aware reference estimate, not a platform-confirmed personal return.

    Recorded effective dates apply before that day's income. Daily distributions
    use a documented floor-to-cents reinvestment approximation. Missing income
    while invested invalidates the estimate rather than imputing zero.
    """
    selected=sorted([t for t in trades if t["mode"]==mode], key=lambda t:(t["date"],t["created_at"],t["id"]))
    confirmed=[t for t in selected if t["status"]=="confirmed"]
    if not confirmed or not rows:
        return dict(points=[],value=None,profit=None,note="尚无已确认记录或行情，无法测算。")
    end=date.fromisoformat(rows[-1]["date"]); begin=date.fromisoformat(confirmed[0]["date"])
    if begin > end:
        return dict(points=[],value=None,profit=None,note="交易晚于最新行情，等待披露。")
    quotes={r["date"]:r for r in rows}; events={}
    for t in confirmed: events.setdefault(t["date"],[]).append(t)
    units=Decimal(0); cash=Decimal(0); valid=True; points=[]; day=begin
    while day <= end:
        ds=day.isoformat()
        for t in events.get(ds,[]):
            n=Decimal(t["units"]); amount=Decimal(t["amount"])
            if t["kind"]=="buy": units+=n; cash-=amount
            else:
                if n>units: valid=False
                units-=n; cash+=amount
        quote=quotes.get(ds)
        if units > 0:
            if not quote: valid=False
            elif valid:
                units+=(units*Decimal(quote["per10k"])/10000).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        points.append(dict(date=ds,value=str(units) if valid else None,profit=str(units+cash) if valid else None))
        day+=timedelta(days=1)
    last=points[-1]
    return dict(points=points,value=last["value"],profit=last["profit"],
        note="参考测算：按1元份额、每日收益向下取分再投资；生效日买入参与当日收益，卖出不参与。金额应含全部实际费用。不是平台确认盈亏。" if valid else "持有期存在缺失行情或份额不足，停止损益测算，请补全记录。")

class FundConflict(ValueError): pass

class FundTracker:
    def __init__(self, root, fetcher=fetch_history, clock=now):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.path=self.root/"funds.json";self.lock=threading.RLock();self.job_lock=threading.Lock()
        self.fetcher=fetcher;self.clock=clock;self.stop=threading.Event()
        if not self.path.exists():
            self.write(dict(version=1,settings=dict(enabled=False,time="09:00",timezone="Asia/Shanghai",watchlist=list(BY_CODE)),
                schedule=dict(slot=None,attempts=0,next_retry=None,done=False),quotes={},sources={},trades=[],runs=[]))
    def read(self):return json.loads(self.path.read_text(encoding="utf-8"))
    def write(self,s):atomic_write_json(self.path,s)
    def public(self):
        with self.lock:
            s=self.read()
            return dict(version=s["version"],catalog=CATALOG,settings=s["settings"],schedule=s["schedule"],
                sources=s["sources"],running=self.job_lock.locked(),runs=s["runs"][-10:],
                counts={c:len(v) for c,v in s["quotes"].items()})
    def settings(self,p):
        if set(p)!={"version","enabled","time","watchlist"} or type(p["enabled"]) is not bool or type(p["version"]) is not int:
            raise ValueError("设置参数无效。")
        if not isinstance(p["time"],str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d",p["time"]):raise ValueError("请输入有效的更新时间。")
        codes=p["watchlist"]
        if not isinstance(codes,list) or len(codes)>5 or any(not isinstance(c,str) or c not in BY_CODE for c in codes) or len(set(codes))!=len(codes):
            raise ValueError("首批支持目录中的五只基金，不允许重复。")
        if p["enabled"] and not codes:raise ValueError("开启定时更新前至少添加一只基金。")
        with self.lock:
            s=self.read()
            if p["version"]!=s["version"]:raise FundConflict("设置已被其他页面修改，请刷新后重试。")
            s["settings"].update({k:p[k] for k in ("enabled","time","watchlist")})
            s["version"]+=1;self.write(s)
        return self.public()
    def due(self):
        with self.lock:
            s=self.read();cfg=s["settings"];dt=self.clock()
            if not cfg["enabled"] or not cfg["watchlist"] or dt.strftime("%H:%M")<cfg["time"]:return False
            key=dt.date().isoformat()+"T"+cfg["time"]+"/"+",".join(cfg["watchlist"])
            job=s["schedule"]
            if job["slot"]!=key:return True
            if job["done"] or job["attempts"]>=3:return False
            return not job["next_retry"] or dt >= datetime.fromisoformat(job["next_retry"])
    def start_scheduler(self):
        def loop():
            while not self.stop.is_set():
                try:
                    if self.due():self.sync("scheduled")
                except Exception:
                    # Persisted per-product errors are recorded in sync; a disk
                    # error must not take down the HTTP server.
                    pass
                self.stop.wait(15)
        threading.Thread(target=loop,daemon=True,name="fund-daily-update").start()
    def request_sync(self,p):
        if p!={"confirm":True}:raise ValueError("请确认更新。")
        if self.job_lock.locked():return dict(started=False,running=True)
        threading.Thread(target=self.sync,args=("manual",),daemon=True).start()
        return dict(started=True)
    def sync(self,trigger="manual"):
        if not self.job_lock.acquire(blocking=False):return False
        try:
            dt=self.clock(); stamp=dt.isoformat()
            with self.lock:
                s=self.read();cfg=copy.deepcopy(s["settings"]);codes=cfg["watchlist"]
                if not codes:return False
                key=dt.date().isoformat()+"T"+cfg["time"]+"/"+",".join(codes)
                if trigger=="scheduled":
                    j=s["schedule"]
                    s["schedule"]=dict(slot=key,attempts=(j["attempts"] if j["slot"]==key else 0)+1,
                        next_retry=(dt+timedelta(hours=1)).isoformat(),done=False)
                    self.write(s)
            results=[]
            for code in codes:
                try:
                    rows,raw=self.fetcher(code)
                    if not rows:raise ValueError("来源没有历史记录。")
                    sha=hashlib.sha256(raw.encode()).hexdigest()
                    atomic_write_text(self.root/"fund-sources"/(code+".js.txt"),raw)
                    with self.lock:
                        s=self.read();old={r["date"]:r for r in s["quotes"].get(code,[])}
                        corrections=sum(1 for r in rows if r["date"] in old and old[r["date"]]!=r)
                        old.update({r["date"]:r for r in rows});s["quotes"][code]=[old[d] for d in sorted(old)]
                        previous=s["sources"].get(code,{}).get("data_date")
                        newest=s["quotes"][code][-1]["date"]
                        s["sources"][code]=dict(status="ok",checked_at=stamp,data_date=newest,sha256=sha,
                            url="https://fund.eastmoney.com/"+code+".html",provider="天天基金公开行情（非腾讯接口）",
                            corrections=corrections,unchanged=(previous==newest and corrections==0))
                        self.write(s)
                    results.append(dict(code=code,ok=True,date=newest,corrections=corrections))
                except Exception as exc:
                    with self.lock:
                        s=self.read();source=s["sources"].setdefault(code,{})
                        source.update(status="error",checked_at=stamp,error=type(exc).__name__+": "+str(exc)[:180]);self.write(s)
                    results.append(dict(code=code,ok=False))
            with self.lock:
                s=self.read()
                if trigger=="scheduled" and s["schedule"]["slot"]==key:s["schedule"]["done"]=all(x["ok"] for x in results)
                s["runs"]=(s["runs"]+[dict(at=stamp,trigger=trigger,results=results)])[-30:];self.write(s)
            return True
        finally:self.job_lock.release()
    def detail(self,code,months,mode):
        if code not in BY_CODE or mode not in ("actual","simulation"):raise ValueError("产品或记录类型无效。")
        with self.lock:s=self.read()
        rows=s["quotes"].get(code,[]);trades=[t for t in s["trades"] if t["code"]==code]
        perf=performance(rows,months);portfolio=estimate(rows,trades,mode)
        if perf["start"]:portfolio["points"]=[p for p in portfolio["points"] if p["date"]>=perf["start"]]
        return dict(product=BY_CODE[code],source=s["sources"].get(code),performance=perf,portfolio=portfolio,
                    trades=[t for t in trades if t["mode"]==mode],latest=rows[-1] if rows else None)
    def save_trade(self,p):
        keys={"id","revision","code","mode","kind","status","date","amount","units","note"}
        if set(p)!=keys or p["code"] not in BY_CODE or p["mode"] not in ("actual","simulation") or p["kind"] not in ("buy","sell") or p["status"] not in ("pending","confirmed"):
            raise ValueError("交易记录参数无效。")
        if not isinstance(p["id"],str) or not re.fullmatch(r"[a-zA-Z0-9-]{1,64}",p["id"]) or type(p["revision"]) is not int:raise ValueError("记录版本无效。")
        if not isinstance(p["note"],str) or len(p["note"])>500:raise ValueError("备注最多500字。")
        iso_day(p["date"])
        if p["date"]>self.clock().date().isoformat() or p["date"]<"1990-01-01":raise ValueError("请输入已发生的有效日期。")
        numeric(p["amount"],2,False);numeric(p["units"],6,False)
        with self.lock:
            s=self.read();existing=next((r for r in s["trades"] if r["id"]==p["id"]),None)
            if existing and all(existing.get(k)==p[k] for k in keys-{"revision"}):return dict(saved=True,id=p["id"])
            if (existing and existing["revision"]!=p["revision"]) or (not existing and p["revision"]!=0):raise FundConflict("交易记录已变化，请刷新重试。")
            if existing and (existing["mode"]!=p["mode"] or existing["code"]!=p["code"]):raise ValueError("不能将实际与模拟记录互相移动。")
            if not existing and len(s["trades"])>=10000:raise ValueError("记录数量已达本机原型上限。")
            row=dict(p,revision=(existing["revision"] if existing else 0)+1,
                     created_at=existing["created_at"] if existing else self.clock().isoformat())
            s["trades"]=[r for r in s["trades"] if r["id"]!=p["id"]]+[row];self.write(s)
        return dict(saved=True,id=p["id"])
    def delete_trade(self,p):
        if set(p)!={"id","revision","mode"} or type(p["revision"]) is not int:raise ValueError("删除参数无效。")
        with self.lock:
            s=self.read();row=next((r for r in s["trades"] if r["id"]==p["id"]),None)
            if not row or row["revision"]!=p["revision"] or row["mode"]!=p["mode"]:raise FundConflict("记录已变化，请刷新。")
            s["trades"]=[r for r in s["trades"] if r["id"]!=p["id"]];self.write(s)
        return dict(deleted=True)
