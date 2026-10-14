"""Offline, evidence-linked analysis. No LLM, forecasting or order execution."""
import calendar, hashlib, json, re, threading
from datetime import date, timedelta
from statistics import median
from pathlib import Path
from analysis import monthly_comparisons
from funds import CATALOG, performance
from vendor.io_utils import atomic_write_json

RULE_VERSION = 'category-history-v2'

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def candidates(entries, start, end, rule=RULE_VERSION):
    rows=sorted((r for r in entries if r['kind']=='expense' and r['date']<=end),key=lambda r:(r['date'],r['id']))
    current=[r for r in rows if start<=r['date']<=end];found=[];insufficient=[]
    for r in current:
        first=(date.fromisoformat(r['date'])-timedelta(days=90)).isoformat()
        history=[p for p in rows if first<=p['date']<r['date'] and p['category']==r['category']]
        values=[p['cents'] for p in history]
        if rule=='fixed-v1':
            high=r['cents']>=50000;reason={'threshold_cents':50000,'history_count':len(history)}
        else:
            if len(values)<6:
                insufficient.append(r['id']);continue
            center=median(values);mad=median(abs(v-center) for v in values)
            threshold=max(center*3,center+20000,center+6*mad)
            high=r['cents']>threshold
            reason={'median_cents':center,'mad_cents':mad,'threshold_cents':threshold,'history_count':len(history)}
        if high:
            found.append(dict(type='amount',ids=[r['id']],evidence=[p['id'] for p in history],reason=reason))
    groups={}
    for r in current:
        note=' '.join(r.get('note','').casefold().split())
        if rule!='fixed-v1' and not note:continue
        key=(r['date'],r['cents']) if rule=='fixed-v1' else (r['date'],r['cents'],r['category'],note)
        groups.setdefault(key,[]).append(r)
    for group in groups.values():
        if len(group)>1:
            found.append(dict(type='duplicate',ids=[r['id'] for r in group],evidence=[],reason={'same_date':group[0]['date'],'cents':group[0]['cents'],'note_matched':rule!='fixed-v1'}))
    lookup={r['id']:r for r in rows}
    for item in found:
        item['key']=digest({'type':item['type'],'rows':[lookup[i] for i in item['ids']]})
        item['records']=[lookup[i] for i in item['ids']]
    return found,insufficient

def report(entries, period, today, version, rule=RULE_VERSION):
    if not isinstance(period,str) or not re.fullmatch(r'\d{4}(?:-(?:0[1-9]|1[0-2]))?',period) or int(period[:4])<2:
        raise ValueError('请选择有效年份或月份。')
    year=int(period[:4]);annual=len(period)==4
    month=1 if annual else int(period[5:]);start=date(year,month,1)
    if start>today:raise ValueError('所选期间尚未开始。')
    calendar_end=date(year,12,31) if annual else date(year,month,calendar.monthrange(year,month)[1])
    end=min(today,calendar_end)
    prior_end=start-timedelta(days=1);prior_start=date(year-1,1,1) if annual else prior_end.replace(day=1)
    current=[r for r in entries if start.isoformat()<=r['date']<=end.isoformat()]
    previous=[r for r in entries if prior_start.isoformat()<=r['date']<=prior_end.isoformat()]
    facts={k:sum(r['cents'] for r in current if r['kind']==k) for k in ('income','expense')}
    facts['balance']=facts['income']-facts['expense']
    comparison={k:{'current':facts[k],'previous':sum(r['cents'] for r in previous if r['kind']==k)} for k in ('income','expense')}
    for v in comparison.values():
        v['delta']=v['current']-v['previous'] if current and previous else None
        v['percent_basis_points']=round(v['delta']*10000/v['previous']) if v['delta'] is not None and v['previous'] else None
    flags,insufficient=candidates(entries,start.isoformat(),end.isoformat(),rule)
    categories={}
    for r in current:
        if r['kind']=='expense':categories[r['category']]=categories.get(r['category'],0)+r['cents']
    return dict(version=version,rule_version=rule,period=period,start=start.isoformat(),end=end.isoformat(),
        previous_start=prior_start.isoformat(),previous_end=prior_end.isoformat(),partial=end<calendar_end,
        facts=facts,comparison=comparison,category_expenses=sorted(categories.items(),key=lambda x:(-x[1],x[0])),
        evidence=current,previous_evidence=previous,candidates=flags,insufficient_ids=insufficient,
        limitations=['仅分析已记录账单，不保证账本完整；结余不是可投资现金。','规则候选需要人工核实，不认定欺诈或消费动机。',
                     '金额偏离需前90天至少6笔同类历史；相同日期/金额/分类/非空备注只提示疑似重复。',
                     '当前未结束期间与上一完整期间比较，时长不同，不预测期末金额。'] if end<calendar_end else
                    ['仅分析已记录账单，不保证账本完整；结余不是可投资现金。','规则候选需要人工核实，不认定欺诈或消费动机。','金额偏离需前90天至少6笔同类历史；相同日期/金额/分类/非空备注只提示疑似重复。'])

def funding_check(p,today):
    required={'available_cents','reserve_cents','amount_cents','need_date','accept_loss','confirmed_on'}
    if not required<=set(p):return {'status':'information_needed','reasons':['请确认当前现金、预留金额、拟投入、用款日期及本金损失承受意愿。'],'limit_cents':None}
    for key in ('available_cents','reserve_cents','amount_cents'):
        if type(p[key]) is not int or not 0<=p[key]<=99999999999:raise ValueError('资金须以非负整数分表示。')
    if type(p['accept_loss']) is not bool:raise ValueError('请明确是否接受本金损失。')
    if p['confirmed_on']!=today.isoformat():return dict(status='information_needed',reasons=['请重新确认今天的现金和保留金额。'],limit_cents=None)
    try:need=date.fromisoformat(p['need_date'])
    except (ValueError,TypeError):raise ValueError('用款日期无效。')
    limit=max(0,p['available_cents']-p['reserve_cents']);reasons=[]
    if not p['amount_cents'] or p['amount_cents']>limit:reasons.append('拟投入必须大于0且不超过已确认现金扣除预留金额后的上限。')
    if need<today:reasons.append('用款日期不能早于今天。')
    if not p['accept_loss']:reasons.append('你不接受本金损失，本实验不生成基金投入方案。')
    return dict(status='blocked' if reasons else 'ready_for_comparison',reasons=reasons,limit_cents=limit)

def compare_products(snapshot,today):
    result=[]
    for product in CATALOG:
        code=product['code'];rows=snapshot.get('quotes',{}).get(code,[]);source=snapshot.get('sources',{}).get(code,{})
        reasons=['当前理财通在售状态、起购金额、赎回到账及完整费用尚未核实。']
        if source.get('status')!='ok':reasons.append('行情来源未成功更新。')
        if not rows:reasons.append('缺少收益历史。')
        elif (today-date.fromisoformat(rows[-1]['date'])).days>3:reasons.append('行情距离今天超过3个自然日，请核实披露；可能包含假期。')
        result.append(dict(code=code,name=product['name'],status='information_needed',reasons=reasons,
            data_date=rows[-1]['date'] if rows else None,source=source,
            per10k=rows[-1]['per10k'] if rows else None,annual7=rows[-1]['annual7'] if rows else None,
            returns={str(n):performance(rows,n)['return_pct'] for n in (1,3,6,12)}))
    return result

class Insights:
    def __init__(self,root,ledger,funds):
        self.path=Path(root)/'analysis-feedback.json';self.ledger=ledger;self.funds=funds;self.lock=threading.RLock()
    def get_report(self,period,today=None):
        snap=self.ledger.public();result=report(snap['entries'],period,today or date.today(),snap['version'])
        with self.lock:feedback=json.loads(self.path.read_text(encoding='utf8')) if self.path.exists() else {}
        for c in result['candidates']:c['feedback']=feedback.get(c['key'])
        return result
    def feedback(self,p):
        if set(p)!={'period','version','key','decision'} or p['decision'] not in ('normal','check','insufficient'):raise ValueError('反馈参数无效。')
        with self.ledger.lock:
            r=self.get_report(p['period'])
            if r['version']!=p['version']:raise ValueError('账本已变化，请重新生成报告。')
            if p['key'] not in {c['key'] for c in r['candidates']}:raise ValueError('待核查项已变化。')
            with self.lock:
                feedback=json.loads(self.path.read_text(encoding='utf8')) if self.path.exists() else {}
                feedback[p['key']]={'decision':p['decision'],'on':date.today().isoformat()};atomic_write_json(self.path,feedback)
        return dict(saved=True)
    def preview(self,p):
        if set(p)!={'period','version','funding'} or not isinstance(p['funding'],dict):raise ValueError('比较参数无效。')
        with self.ledger.lock:
            r=self.get_report(p['period'])
            if r['version']!=p['version']:raise ValueError('账本已变化，旧报告失效，请先重新生成。')
        with self.funds.lock:s=self.funds.read()
        cash=funding_check(p['funding'],date.today());products=compare_products(s,date.today())
        return dict(ledger_version=r['version'],product_version=digest({'sources':s['sources'],'quotes':s['quotes']}),
            funding=cash,products=products,executable=False,
            note='只读条件比较，不生成订单；资料不足不视为符合条件。七日年化不是未来收益或固定利率，不据此自动排名。')
