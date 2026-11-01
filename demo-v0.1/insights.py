"""Offline, evidence-linked analysis. No LLM, forecasting or order execution."""
import calendar, hashlib, json, re, threading
from datetime import date, timedelta
from statistics import median
from pathlib import Path
from analysis import monthly_comparisons
from funds import CATALOG, performance, market_version
from vendor.io_utils import atomic_write_json
from narrative import build_narrative

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

def _merchant_key(note):
    text=' '.join(str(note or '').split()).casefold()
    return text.split('；',1)[0].strip()

def recurring_patterns(entries, end):
    """Find repeated merchant/category charges in the last four months."""
    end_date=date.fromisoformat(end);start_date=end_date-timedelta(days=120);groups={}
    for row in entries:
        if row.get('kind')!='expense': continue
        try: row_date=date.fromisoformat(row['date'])
        except (KeyError,ValueError): continue
        merchant=_merchant_key(row.get('note'))
        if merchant and start_date<=row_date<=end_date: groups.setdefault((merchant,row.get('category')),[]).append(row)
    found=[]
    for (merchant,category),rows in groups.items():
        rows=sorted(rows,key=lambda r:(r['date'],r['id']));dates=sorted({date.fromisoformat(r['date']) for r in rows})
        if len(dates)<2: continue
        gaps=[(b-a).days for a,b in zip(dates,dates[1:])]
        same_amount=len({r['cents'] for r in rows})==1
        if not (same_amount or all(15<=gap<=45 for gap in gaps)): continue
        found.append(dict(type='recurring_pattern',ids=[r['id'] for r in rows],evidence=[],
                          reason={'merchant':merchant,'category':category,'occurrences':len(dates),'same_amount':same_amount,'gaps_days':gaps},records=rows))
    return sorted(found,key=lambda item:(-item['reason']['occurrences'],item['reason']['merchant']))

def cashflow_profile(entries, end):
    """Show an evidence-based cash safety reference without treating balance as investable cash."""
    end_date=date.fromisoformat(end);start_date=end_date-timedelta(days=89)
    rows=[]
    essential={'住房','居住','餐饮','交通','出行','日用','生活','医疗','水电','通信'}
    for row in entries:
        try: row_date=date.fromisoformat(row['date'])
        except (KeyError,ValueError): continue
        if start_date<=row_date<=end_date and row.get('kind') in ('income','expense'): rows.append(row)
    months={}
    for row in rows:
        item=months.setdefault(row['date'][:7],{'income':0,'expense':0,'essential_expense':0})
        item[row['kind']]+=row['cents']
        if row['kind']=='expense' and row.get('category') in essential: item['essential_expense']+=row['cents']
    active=list(months.values())
    average=lambda key: round(sum(item[key] for item in active)/len(active)) if active else None
    essential_average=average('essential_expense')
    reserve_floor=essential_average*3 if essential_average is not None else None
    return dict(window_start=start_date.isoformat(),window_end=end_date.isoformat(),months=months,
                income_cents= sum(r['cents'] for r in rows if r['kind']=='income'),
                expense_cents=sum(r['cents'] for r in rows if r['kind']=='expense'),
                average_monthly_expense_cents=average('expense'),
                average_monthly_essential_cents=essential_average,
                suggested_reserve_floor_cents=reserve_floor,
                evidence_count=len(rows),
                note='仅以已导入的近90天账单估算生活费参考线；不代表银行余额、可投资金额或收益承诺。')

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
    expense_total=facts['expense']
    category_shares=[dict(category=k,cents=v,share_bps=round(v*10000/expense_total) if expense_total else 0)
                     for k,v in sorted(categories.items(),key=lambda x:(-x[1],x[0]))]
    top_expenses=sorted([r for r in current if r['kind']=='expense'],key=lambda r:(-r['cents'],r['date'],r['id']))[:5]
    recurring=recurring_patterns(entries,end.isoformat())
    status = 'empty' if not current else ('income_only' if facts['income'] and not facts['expense'] else ('expense_only' if facts['expense'] and not facts['income'] else 'ready'))
    if not previous and current: status = 'missing_previous' if status == 'ready' else status + '_missing_previous'
    return dict(version=version,rule_version=rule,status=status,period=period,start=start.isoformat(),end=end.isoformat(),
        previous_start=prior_start.isoformat(),previous_end=prior_end.isoformat(),partial=end<calendar_end,
        facts=facts,comparison=comparison,category_expenses=sorted(categories.items(),key=lambda x:(-x[1],x[0])),
        category_shares=category_shares,expense_count=sum(r['kind']=='expense' for r in current),
        income_count=sum(r['kind']=='income' for r in current),top_expenses=top_expenses,
        recurring_candidates=recurring,cash_safety=cashflow_profile(entries,end.isoformat()),evidence=current,previous_evidence=previous,candidates=flags,insufficient_ids=insufficient,
        limitations=['仅分析已记录账单，不保证账本完整；结余不是可投资现金。','规则候选需要人工核实，不认定欺诈或消费动机。',
                     '金额偏离需前90天至少6笔同类历史；相同日期/金额/分类/非空备注只提示疑似重复。',
                     '当前未结束期间与上一完整期间比较，时长不同，不预测期末金额。','固定/订阅模式基于近120天商户与分类重复记录，仅供人工确认。'] if end<calendar_end else
                    ['仅分析已记录账单，不保证账本完整；规则候选需要人工核实，不认定欺诈或消费动机。','金额偏离需前90天至少6笔同类历史；相同日期/金额/分类/非空备注只提示疑似重复。','固定/订阅模式基于近120天商户与分类重复记录，仅供人工确认。'])

def funding_check(p,today,cashflow=None):
    required={'available_cents','reserve_cents','amount_cents','need_date','accept_loss','confirmed_on'}
    if not required<=set(p):return {'status':'information_needed','reasons':['请确认当前现金、预留金额、拟投入、用款日期及本金损失承受意愿。'],'limit_cents':None}
    for key in ('available_cents','reserve_cents','amount_cents'):
        if type(p[key]) is not int or not 0<=p[key]<=99999999999:raise ValueError('资金须以非负整数分表示。')
    if type(p['accept_loss']) is not bool:raise ValueError('请明确是否接受本金损失。')
    if p['confirmed_on']!=today.isoformat():return dict(status='information_needed',reasons=['请重新确认今天的现金和保留金额。'],limit_cents=None)
    try:need=date.fromisoformat(p['need_date'])
    except (ValueError,TypeError):raise ValueError('用款日期无效。')
    limit=max(0,p['available_cents']-p['reserve_cents']);reasons=[]
    if cashflow and cashflow.get('suggested_reserve_floor_cents') is not None and p['reserve_cents']<cashflow['suggested_reserve_floor_cents']:
        reasons.append('预留金额低于近90天必要支出的三个月参考线，请先补足安全垫或确认这只是演示输入。')
    if not p['amount_cents'] or p['amount_cents']>limit:reasons.append('拟投入必须大于0且不超过已确认现金扣除预留金额后的上限。')
    if need<today:reasons.append('用款日期不能早于今天。')
    if not p['accept_loss']:reasons.append('你不接受本金损失，本实验不生成基金投入方案。')
    return dict(status='blocked' if reasons else 'ready_for_comparison',reasons=reasons,limit_cents=limit)

def compare_products(snapshot,today):
    result=[]
    for product in CATALOG:
        code=product['code'];rows=snapshot.get('quotes',{}).get(code,[]);source=dict(snapshot.get('sources',{}).get(code,{}))
        try:
            age=(today-date.fromisoformat(source['data_date'])).days
            source['age_days']=age;source['freshness']='fresh' if 0<=age<=3 else ('future' if age<0 else 'stale')
        except (KeyError,TypeError,ValueError): source['age_days']=None;source['freshness']='unknown'
        reasons=['当前理财通在售状态、起购金额、赎回到账及完整费用尚未核实。']
        if source.get('status')!='ok':reasons.append('行情来源未成功更新。')
        if not rows:reasons.append('缺少收益历史。')
        elif (today-date.fromisoformat(rows[-1]['date'])).days>3:reasons.append('行情距离今天超过3个自然日，请核实披露；可能包含假期。')
        if source.get('freshness') in ('stale','future','unknown'): reasons.append('行情数据新鲜度不足，不能据此形成可靠比较。')
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
        result['narrative']=build_narrative(result)
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
        cash=funding_check(p['funding'],date.today(),r.get('cash_safety'));products=compare_products(s,date.today())
        freshness_snapshot={p['code']:{key:p['source'].get(key) for key in ('data_date','freshness','age_days')} for p in products}
        product_version=market_version(s,self.funds.clock().date())
        return dict(ledger_version=r['version'],product_version=product_version,funds_version=s.get('version'),freshness_snapshot=freshness_snapshot,
            funding=cash,products=products,executable=False,
            note='只读条件比较，不生成订单；资料不足不视为符合条件。七日年化不是未来收益或固定利率，不据此自动排名。')
