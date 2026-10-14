"use strict";
(()=>{
 let report=null,stale=false,preview=null;
 const n=id=>document.getElementById(id),fmt=v=>v===null?'资料不足':money(v);
 function error(e){n('insight-error').textContent=e.message;n('insight-error').hidden=false;}
 function invalidate(message){stale=true;preview=null;n('insight-preview').textContent='旧比较结果已失效，请刷新报告并重新比较。';n('insight-status').textContent=message;n('insight-compare').disabled=true;n('insight-export').disabled=true;}
 async function generate(){
  report=await api('/api/insights/report?period='+encodeURIComponent(n('insight-period').value));stale=false;preview=null;
  n('insight-error').hidden=true;n('insight-export').disabled=false;n('insight-compare').disabled=false;n('insight-preview').replaceChildren();
  n('insight-status').textContent=`${report.start} 至 ${report.end}；上期 ${report.previous_start} 至 ${report.previous_end}。${report.partial?'本期尚未结束，两期时长不同。':''}报告版本 ${report.version.slice(0,10)} · ${report.rule_version}`;
  n('insight-report').innerHTML=`<p>已记录收入 <b>${fmt(report.facts.income)}</b>，支出 <b>${fmt(report.facts.expense)}</b>，净结余 <b>${fmt(report.facts.balance)}</b>。</p><p>支出较上期变化：${fmt(report.comparison.expense.delta)}；收入变化：${fmt(report.comparison.income.delta)}。</p><p>支出类别：${report.category_expenses.map(([k,v])=>esc(k)+' '+fmt(v)).join('；')||'无记录'}。</p><p class="caption">${report.limitations.map(esc).join(' ')}</p><details><summary>查看本期 ${report.evidence.length} 笔依据</summary>${report.evidence.map(r=>`<p>${esc(r.date)} · ${esc(r.category)} · ${fmt(r.cents)} · ${esc(r.note)} <small>${esc(r.id)}</small></p>`).join('')}</details>`;
  const labels={normal:'已标记正常',check:'已标记需核查',insufficient:'已标记信息不足'};
  n('insight-flags').innerHTML=`<p class="caption">${report.insufficient_ids.length}笔缺少足够同类历史，未作金额偏离判断；没有候选也不代表所有交易正常。</p>`+(report.candidates.map(c=>`<div class="fund-card"><strong>${c.type==='amount'?'金额偏离个人同类历史':'疑似重复记账'}</strong><p>${c.records.map(r=>`${esc(r.date)} ${esc(r.category)} ${fmt(r.cents)} ${esc(r.note)}`).join('<br>')}</p><p class="caption">${c.type==='amount'?`历史${c.reason.history_count}笔，中位数${fmt(c.reason.median_cents)}，提示阈值${fmt(c.reason.threshold_cents)}。`:'日期、分类、金额与非空备注相同；仍可能是正常的多次消费。'}</p><p>${labels[c.feedback?.decision]||'待人工核查'}</p>${[['normal','正常'],['check','需核查'],['insufficient','信息不足']].map(([v,label])=>`<button class="quiet" data-key="${c.key}" data-decision="${v}">${label}</button>`).join('')}</div>`).join('')||'<p>本期没有触发当前规则的候选。</p>');
 }
 n('insight-period').value=new Date().toLocaleDateString('en-CA').slice(0,7);
 n('insight-form').addEventListener('submit',e=>{e.preventDefault();generate().catch(error);});
 n('insight-period').addEventListener('input',()=>report&&invalidate('期间已修改，请重新生成报告。'));
 n('insight-flags').addEventListener('click',async e=>{const btn=e.target.closest('[data-key]');if(!btn)return;try{await api('/api/insights/feedback',{period:report.period,version:report.version,key:btn.dataset.key,decision:btn.dataset.decision});await generate();}catch(e){error(e);}});
 n('insight-export').addEventListener('click',()=>{if(!report||stale)return;const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='衡智-'+report.period+'-规则报告.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
 const cents=id=>{const s=n(id).value;if(!/^\d{1,9}(\.\d{1,2})?$/.test(s))throw Error('金额最多两位小数，不能为负数。');const [a,b='']=s.split('.');return Number(a)*100+Number(b.padEnd(2,'0'));};
 n('insight-cash').addEventListener('input',()=>{if(preview){preview=null;n('insight-preview').textContent='资金条件已变化，请重新比较。';}});
 n('insight-cash').addEventListener('submit',async e=>{
  e.preventDefault();if(!report||stale)return;
  try{preview=await api('/api/insights/preview',{period:report.period,version:report.version,funding:{available_cents:cents('insight-available'),reserve_cents:cents('insight-reserve'),amount_cents:cents('insight-amount'),need_date:n('insight-need').value,accept_loss:n('insight-loss').value==='yes',confirmed_on:new Date().toLocaleDateString('en-CA')}});
   n('insight-error').hidden=true;n('insight-preview').innerHTML=`<h3>${preview.funding.status==='ready_for_comparison'?'金额条件通过，产品资料仍待补齐':'暂不能形成投入方案'}</h3><p>给定输入下的金额上限：${fmt(preview.funding.limit_cents)}</p><p>${preview.funding.reasons.map(esc).join(' ')}</p><p class="caption">${esc(preview.note)}</p><div class="table-scroll"><table><thead><tr><th>真实基金</th><th>收益日期</th><th>万份收益</th><th>七日年化</th><th>比较状态</th></tr></thead><tbody>${preview.products.map(p=>`<tr><td>${esc(p.name)} ${p.code}</td><td>${esc(p.data_date||'无行情')}</td><td>${esc(p.per10k??'—')}</td><td>${esc(p.annual7??'—')}%</td><td>资料不足：${p.reasons.map(esc).join(' ')}</td></tr>`).join('')}</tbody></table></div>`;
  }catch(e){error(e);}
 });
 setInterval(async()=>{if(document.hidden||n('insights').hidden||!report||stale)return;try{const s=await api('/api/ledger');if(s.version!==report.version)invalidate('账本发生变化，报告和比较已失效，请重新生成。');else if(preview){const f=await api('/api/funds');const current=Object.fromEntries(preview.products.map(p=>[p.code,p.source]));if(JSON.stringify(f.sources)!==JSON.stringify(current)){preview=null;n('insight-preview').textContent='行情来源已更新，请重新比较。';}}}catch(e){error(e);}},5000);
})();
