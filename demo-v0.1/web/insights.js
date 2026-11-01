"use strict";
(()=>{
 let report=null,stale=false,preview=null;
 const n=id=>document.getElementById(id),fmt=v=>v===null?'资料不足':money(v);
 function error(e){n('insight-error').textContent=e.message;n('insight-error').hidden=false;window.reportSystemStatus?.('分析状态',e.message,'refresh','刷新报告');}
 function invalidate(message){stale=true;preview=null;n('insight-preview').textContent='旧比较结果已失效，请刷新报告并重新比较。';n('insight-status').textContent=message;n('insight-compare').disabled=true;n('insight-export').disabled=true;}
 async function generate(){
  report=await api('/api/insights/report?period='+encodeURIComponent(n('insight-period').value));stale=false;preview=null;
  n('insight-error').hidden=true;n('insight-export').disabled=false;n('insight-compare').disabled=false;n('insight-preview').replaceChildren();
  n('insight-status').textContent=`${report.start} 至 ${report.end}；上期 ${report.previous_start} 至 ${report.previous_end}。${report.partial?'本期尚未结束，两期时长不同。':''}报告版本 ${report.version.slice(0,10)} · ${report.rule_version}`;
  const stateMessage={empty:'当前期间没有账单记录。下一步：先导入账单或记一笔。',income_only:'当前只有收入记录，无法分析支出。下一步：补充支出账单。',expense_only:'当前只有支出记录，无法判断收入覆盖。下一步：补充收入记录或确认这是单独账本。',missing_previous:'没有上一期间记录，本期仍可查看，但不生成趋势结论。下一步：选择有历史记录的月份或继续积累账单。'}[report.status]||{income_only_missing_previous:'当前只有收入记录，且没有上一期间。下一步：补充支出或历史账单。',expense_only_missing_previous:'当前只有支出记录，且没有上一期间。下一步：补充收入或历史账单。'}[report.status];
  if(stateMessage)n('insight-status').innerHTML=esc(stateMessage)+' <button class="quiet" type="button" data-recovery="bookkeeping">去补充账单</button>';
  const narrative=report.narrative||{};
  const certaintyLabel={fact:'已核实事实',candidate:'待人工核查',information_needed:'信息不足'};
  const narrativeHtml=(narrative.insights||[]).map(item=>`<article class="fund-card"><div class="assistant-meta"><span class="tag">${esc(certaintyLabel[item.certainty]||item.certainty)}</span><span class="tag">优先级 ${esc(item.priority)}</span></div><h3>${esc(item.title)}</h3><p>${esc(item.body)}</p>${item.suggestion?`<p class="reason">建议：${esc(item.suggestion)}</p>`:''}${item.evidence_ids?.length?`<p class="caption">依据记录：${item.evidence_ids.map(esc).join('、')}</p>`:''}</article>`).join('');
  n('insight-narrative').innerHTML=`<div class="panel"><p class="eyebrow">OFFLINE NARRATIVE</p><h3>重点发现与建议</h3><p>${esc(narrative.summary||'')}</p><div class="fund-grid">${narrativeHtml||'<p class="caption">暂无可生成的重点发现。</p>'}</div><p class="caption">以上内容由服务端规则事实生成；“待人工核查”不等于欺诈认定。</p></div>`;
  const safety=report.cash_safety||{};
  n('insight-report').innerHTML=`<p>已记录收入 <b>${fmt(report.facts.income)}</b>，支出 <b>${fmt(report.facts.expense)}</b>，净结余 <b>${fmt(report.facts.balance)}</b>。</p><p>共 ${report.income_count} 笔收入、${report.expense_count} 笔支出；支出较上期变化：${fmt(report.comparison.expense.delta)}。</p><p>支出类别：${report.category_expenses.map(([k,v])=>esc(k)+' '+fmt(v)).join('；')||'无记录'}。</p><p>最大支出：${report.top_expenses.map(r=>esc(r.category)+' '+fmt(r.cents)).join('；')||'无记录'}。</p><p>近90天平均月支出 ${fmt(safety.average_monthly_expense_cents)}，必要支出参考线（三个月）${fmt(safety.suggested_reserve_floor_cents)}。</p><p class="caption">${report.limitations.map(esc).join(' ')} ${esc(safety.note||'')}</p><details><summary>查看本期 ${report.evidence.length} 笔依据</summary>${report.evidence.map(r=>`<p>${esc(r.date)} · ${esc(r.category)} · ${fmt(r.cents)} · ${esc(r.note)} <small>${esc(r.id)}</small></p>`).join('')}</details>`;
  const labels={normal:'已标记正常',check:'已标记需核查',insufficient:'已标记信息不足'};
  const recurring=report.recurring_candidates||[];
  const flagHtml=report.candidates.map(c=>`<div class="fund-card"><strong>${c.type==='amount'?'金额偏离个人同类历史':'疑似重复记账'}</strong><p>${c.records.map(r=>`${esc(r.date)} ${esc(r.category)} ${fmt(r.cents)} ${esc(r.note)}`).join('<br>')}</p><p class="caption">${c.type==='amount'?`历史${c.reason.history_count}笔，中位数${fmt(c.reason.median_cents)}，提示阈值${fmt(c.reason.threshold_cents)}。`:'日期、分类、金额与非空备注相同；仍可能是正常的多次消费。'}</p><p>${labels[c.feedback?.decision]||'待人工核查'}</p>${[['normal','正常'],['check','需核查'],['insufficient','信息不足']].map(([v,label])=>`<button class="quiet" data-key="${c.key}" data-decision="${v}">${label}</button>`).join('')}<button class="quiet" data-open-card="true">进入卡片处置预览</button></div>`).join('');
  const recurringHtml=recurring.length?`<h3>可能的固定支出或订阅</h3>`+recurring.map(c=>`<div class="fund-card"><strong>${esc(c.reason.merchant)} · ${esc(c.reason.category)}</strong><p>${c.records.map(r=>`${esc(r.date)} ${fmt(r.cents)}`).join('；')}</p><p class="caption">近120天出现 ${c.reason.occurrences} 次${c.reason.same_amount?'，金额相同':''}。这是模式提示，需要人工确认是否为固定账单或订阅。</p></div>`).join(''):'';
  n('insight-flags').innerHTML=`<p class="caption">${report.insufficient_ids.length}笔缺少足够同类历史，未作金额偏离判断；没有候选也不代表所有交易正常。</p>`+(flagHtml||'<p>本期没有触发当前规则的候选。</p>')+recurringHtml;
 }
 n('insight-preview').addEventListener('click',e=>{if(e.target.closest('[data-recovery="recompare"]'))n('insight-cash').requestSubmit();});
 n('insight-period').value=new Date().toLocaleDateString('en-CA').slice(0,7);
 n('insight-form').addEventListener('submit',e=>{e.preventDefault();generate().catch(error);});
 n('insight-period').addEventListener('input',()=>report&&invalidate('期间已修改，请重新生成报告。'));
 n('insight-status').addEventListener('click',e=>{if(e.target.closest('[data-recovery="bookkeeping"]'))page('bookkeeping');});
 n('insight-flags').addEventListener('click',async e=>{const card=e.target.closest('[data-open-card]');if(card){window.__insightPeriod=report.period;page('cards');return;}const btn=e.target.closest('[data-key]');if(!btn)return;try{await api('/api/insights/feedback',{period:report.period,version:report.version,key:btn.dataset.key,decision:btn.dataset.decision});await generate();}catch(e){error(e);}});
 n('insight-export').addEventListener('click',()=>{if(!report||stale)return;const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='衡智-'+report.period+'-规则报告.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
 const cents=id=>{const s=n(id).value;if(!/^\d{1,9}(\.\d{1,2})?$/.test(s))throw Error('金额最多两位小数，不能为负数。');const [a,b='']=s.split('.');return Number(a)*100+Number(b.padEnd(2,'0'));};
 n('insight-cash').addEventListener('input',()=>{if(preview){preview=null;n('insight-preview').textContent='资金条件已变化，请重新比较。';}});
 n('insight-cash').addEventListener('submit',async e=>{
  e.preventDefault();if(!report||stale)return;
  try{preview=await api('/api/insights/preview',{period:report.period,version:report.version,funding:{available_cents:cents('insight-available'),reserve_cents:cents('insight-reserve'),amount_cents:cents('insight-amount'),need_date:n('insight-need').value,accept_loss:n('insight-loss').value==='yes',confirmed_on:new Date().toLocaleDateString('en-CA')}});
   n('insight-error').hidden=true;n('insight-preview').innerHTML=`<h3>${preview.funding.status==='ready_for_comparison'?'金额条件通过，产品资料仍待补齐':'暂不能形成投入方案'}</h3><p>给定输入下的金额上限：${fmt(preview.funding.limit_cents)}</p><p>${preview.funding.reasons.map(esc).join(' ')}</p><p class="caption">${esc(preview.note)}</p><div class="table-scroll"><table><thead><tr><th>真实基金</th><th>收益日期</th><th>新鲜度</th><th>万份收益</th><th>七日年化</th><th>比较状态</th></tr></thead><tbody>${preview.products.map(p=>`<tr><td>${esc(p.name)} ${p.code}</td><td>${esc(p.data_date||'无行情')}</td><td>${esc(p.source?.freshness||'unknown')}</td><td>${esc(p.per10k??'—')}</td><td>${esc(p.annual7??'—')}%</td><td>资料不足：${p.reasons.map(esc).join(' ')}</td></tr>`).join('')}</tbody></table></div>`;
  }catch(e){error(e);}
 });
 setInterval(async()=>{if(document.hidden||n('insights').hidden||!report||stale)return;try{const s=await api('/api/ledger');if(s.version!==report.version)invalidate('账本发生变化，报告和比较已失效，请重新生成。');else if(preview){const f=await api('/api/funds');if(f.market_version!==preview.product_version){preview=null;n('insight-preview').innerHTML='<p class="fund-warning">行情版本或数据新鲜度已变化，旧比较结果已失效。<button class="quiet" data-recovery="recompare" type="button">重新比较</button></p>'; }}}catch(e){error(e);}},5000);
})();
