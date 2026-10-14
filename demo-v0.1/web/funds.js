"use strict";
(()=>{
 const node=id=>document.getElementById(id);
 let overview=null,detail=null,months=1,editing=null,requestSeq=0,busy=false,settingsDirty=false,settingsVersion=null,draftId=null;
 const num=(v,d=4)=>v===null||v===undefined?'—':Number(v).toLocaleString('zh-CN',{maximumFractionDigits:d});
 const names={actual:'实际手动记录',simulation:'模拟记录'};
 function error(e){node('fund-error').textContent=e.message||String(e);node('fund-error').hidden=false;}
 function selected(){return node('fund-select').value;}
 async function refreshOverview(initial=false){
  overview=await api('/api/funds');
  if(initial){
   node('fund-select').innerHTML=overview.catalog.map(f=>`<option value="${esc(f.code)}">${esc(f.name)} · ${esc(f.code)}</option>`).join('');
   node('fund-watchlist').innerHTML=overview.catalog.map(f=>`<label><input type="checkbox" value="${esc(f.code)}">${esc(f.name)}</label>`).join('');
   node('fund-watchlist').addEventListener('change',()=>settingsDirty=true);
  }
  if(!settingsDirty){
   settingsVersion=overview.version;
   node('fund-schedule-time').value=overview.settings.time;node('fund-schedule-enabled').checked=overview.settings.enabled;
   node('fund-watchlist').querySelectorAll('input').forEach(n=>n.checked=overview.settings.watchlist.includes(n.value));
  }
  node('fund-sync').disabled=overview.running;
  node('fund-sync').textContent=overview.running?'正在联网更新…':'立即更新已跟踪产品';
  node('fund-schedule-state').textContent=(overview.settings.enabled?`已启用：每天北京时间 ${overview.settings.time}`:'定时更新未开启')+'。由衡智服务运行；浏览器关闭不影响，电脑或服务关闭则暂停，重启后补做当日错过的更新。';
  node('fund-cards').innerHTML=overview.catalog.map(f=>{
   const s=overview.sources[f.code],watched=overview.settings.watchlist.includes(f.code);
   return `<div class="fund-card"><strong>${esc(f.name)} · ${f.code}</strong><p>${watched?'跟踪中':'已移出定时跟踪，历史保留'}</p><p>收益日期：${esc(s?.data_date||'尚无数据')}</p><p>读取状态：${s?.status==='ok'?'来源读取成功':s?.status==='error'?'更新失败，保留旧数据':'待首次更新'}</p><p class="caption">${s?.checked_at?'最近检查 '+esc(new Date(s.checked_at).toLocaleString('zh-CN')):''}</p>${s?.error?`<p class="caption">${esc(s.error)}</p>`:''}</div>`;
  }).join('');
  node('fund-runs').innerHTML=overview.runs.slice().reverse().map(r=>`<p>${esc(new Date(r.at).toLocaleString('zh-CN'))} · ${r.trigger==='scheduled'?'服务端定时':'手动'} · 成功 ${r.results.filter(x=>x.ok).length}/${r.results.length}</p>`).join('')||'<p>尚无更新记录。</p>';
 }
 async function loadDetail(){
  if(!selected())return;const seq=++requestSeq;
  const data=await api(`/api/funds/detail?code=${selected()}&months=${months}&mode=${node('fund-mode').value}`);
  if(seq!==requestSeq)return;detail=data;renderDetail();
 }
 function renderDetail(){
  const p=detail.performance,s=detail.source,l=detail.latest,mode=node('fund-mode').value;
  node('fund-detail-title').textContent=detail.product.name;
  node('fund-period-label').textContent=p.start?`${p.start} 至 ${p.end} · ${p.coverage?'所选区间每日收益齐全':'所选区间数据不足，累计曲线不补造'} · 末日为最新披露日期`:'尚无历史数据，请点击立即更新。';
  node('fund-source').innerHTML=s?`来源：<a href="${esc(s.url||'https://fund.eastmoney.com/')}" target="_blank" rel="noopener noreferrer">天天基金公开行情</a> · 非腾讯实时接口。数据日 ${esc(s.data_date||'未知')}；检查时间 ${esc(s.checked_at||'未知')}。${s.status==='error'?'本次更新失败，以下为已保存数据。':''}`:'尚未取得真实行情；不生成示例曲线。';
  node('fund-per10k').textContent=num(l?.per10k)+' 元';node('fund-annual7').textContent=num(l?.annual7)+'%';
  node('fund-return').textContent=num(p.return_pct)+'%';node('fund-profit').textContent=num(detail.portfolio.profit,2)+' 元';
  node('fund-mode-note').textContent=names[mode]+'：'+detail.portfolio.note;
  node('fund-mode-note').className='fund-warning '+(mode==='actual'?'fund-actual':'fund-simulation');
  node('fund-trade-mode-label').textContent='新增'+names[mode]+'（仅记录，不下单）';
  renderChart();
  node('fund-history-body').innerHTML=p.points.slice().reverse().map(r=>`<tr><td>${r.date}</td><td>${num(r.per10k)}</td><td>${num(r.annual7)}%</td><td>${num(r.daily_pct,6)}%</td><td>${num(r.cumulative_pct)}%</td></tr>`).join('');
  node('fund-trades').innerHTML=detail.trades.slice().sort((a,b)=>b.date.localeCompare(a.date)).map(t=>`<tr><td>${esc(t.date)}</td><td>${t.kind==='buy'?'买入':'卖出'} · ${t.status==='confirmed'?'已确认':'待确认'}</td><td>${num(t.amount,2)}</td><td>${num(t.units,6)}</td><td class="fund-note">${esc(t.note)}</td><td><button class="quiet" data-edit="${esc(t.id)}">编辑</button><button class="quiet" data-delete="${esc(t.id)}">删除</button></td></tr>`).join('')||'<tr><td colspan="6">该类型尚无交易记录。</td></tr>';
 }
 function renderChart(){
  const p=detail.performance,metric=node('fund-metric').value;
  const series=metric==='personal'?detail.portfolio.points:p.points;
  const key={daily:'daily_pct',cumulative:'cumulative_pct',annual:'annual7',income:'per10k',nav:'nav',personal:'profit'}[metric];
  const unit=['income','nav','personal'].includes(metric)?'元':'%';
  const valid=series.filter(r=>r[key]!==null&&r[key]!==undefined);
  if(!valid.length){node('fund-chart').innerHTML=`<div class="empty">${metric==='nav'?'当前货币基金来源提供万份收益与七日年化，没有单位净值历史；不伪造净值曲线。':metric==='personal'?'没有足够的行情或已确认交易可计算个人参考收益。':'没有足够真实数据绘制此曲线。'}</div>`;node('fund-chart-readout').textContent='';return;}
  const start=Date.parse(p.start+'T00:00:00Z'),end=Date.parse(p.end+'T00:00:00Z'),duration=Math.max(86400000,end-start);
  const vals=valid.map(r=>Number(r[key])),low=Math.min(...vals),high=Math.max(...vals),span=Math.max(high-low,0.0001);
  const x=d=>55+(Date.parse(d+'T00:00:00Z')-start)/duration*700,y=v=>230-(Number(v)-low)/span*180;
  let parts=[],segment=[],previous=null;
  for(const r of series){
   const ts=Date.parse(r.date+'T00:00:00Z');
   if(r[key]===null||r[key]===undefined||(previous!==null&&ts-previous>86400000)){if(segment.length)parts.push(segment.join(' '));segment=[];}
   if(r[key]!==null&&r[key]!==undefined)segment.push(x(r.date)+','+y(r[key]));previous=ts;
  }
  if(segment.length)parts.push(segment.join(' '));
  const marks=detail.trades.filter(t=>t.date>=p.start&&t.date<=p.end).map((t,i)=>`<g><line class="fund-marker" x1="${x(t.date)}" x2="${x(t.date)}" y1="40" y2="235"/><circle class="${t.kind==='buy'?'fund-buy':'fund-sell'}" cx="${x(t.date)}" cy="${27+(i%2)*14}" r="5" tabindex="0" data-trade="${esc(t.id)}"/><text x="${x(t.date)}" y="${18+(i%2)*14}" text-anchor="middle">${t.kind==='buy'?'买':'卖'}${t.status==='pending'?'?':''}</text></g>`).join('');
  node('fund-chart').innerHTML=`<svg viewBox="0 0 800 290" role="img" aria-label="${esc(node('fund-metric').selectedOptions[0].textContent)}历史曲线"><line x1="55" y1="235" x2="755" y2="235" stroke="#ccd5df"/><text x="5" y="55">${num(high,4)}</text><text x="5" y="230">${num(low,4)}</text><text x="55" y="270">${p.start}</text><text x="755" y="270" text-anchor="end">${p.end}</text>${parts.map(points=>`<polyline class="fund-path" points="${points}"/>`).join('')}${valid.map(r=>`<circle cx="${x(r.date)}" cy="${y(r[key])}" r="2.5" fill="#315b9d" tabindex="0" data-point="${r.date}" data-value="${esc(r[key])}"/>`).join('')}${marks}</svg>`;
  node('fund-chart-readout').textContent='点击曲线点查看数值；买/卖标记可点击，? 表示待确认。';
  node('fund-chart').querySelectorAll('[data-point]').forEach(el=>{const show=()=>node('fund-chart-readout').textContent=`${el.dataset.point}：${num(el.dataset.value,6)}${unit}`;el.addEventListener('mouseenter',show);el.addEventListener('focus',show);el.addEventListener('click',show);});
  node('fund-chart').querySelectorAll('[data-trade]').forEach(el=>{const show=()=>{const t=detail.trades.find(r=>r.id===el.dataset.trade);node('fund-chart-readout').textContent=`${names[t.mode]} · ${t.date} · ${t.kind==='buy'?'买入':'卖出'} · ${t.status==='pending'?'待确认':'已确认'} · 现金${t.amount}元 / ${t.units}份 · ${t.note}`;};el.addEventListener('focus',show);el.addEventListener('click',show);});
 }
 function clearForm(){editing=null;draftId=crypto.randomUUID();node('fund-trade-form').reset();node('fund-trade-date').value=new Date().toLocaleDateString('en-CA');node('fund-trade-cancel').hidden=true;node('fund-trade-submit').textContent='保存记录';}
 node('fund-settings').addEventListener('submit',async e=>{e.preventDefault();try{await api('/api/funds/settings',{version:settingsVersion,enabled:node('fund-schedule-enabled').checked,time:node('fund-schedule-time').value,watchlist:[...node('fund-watchlist').querySelectorAll('input:checked')].map(n=>n.value)});settingsDirty=false;await refreshOverview();node('fund-error').hidden=true;}catch(err){error(err);}});
 ['fund-schedule-time','fund-schedule-enabled'].forEach(id=>node(id).addEventListener('change',()=>settingsDirty=true));
 node('fund-sync').addEventListener('click',async()=>{try{await api('/api/funds/sync',{confirm:true});await refreshOverview();}catch(e){error(e);}});
 ['fund-select','fund-mode'].forEach(id=>node(id).addEventListener('change',()=>{clearForm();loadDetail().catch(error);}));
 node('fund-metric').addEventListener('change',()=>detail&&renderChart());
 document.querySelectorAll('[data-fund-months]').forEach(btn=>btn.addEventListener('click',()=>{months=Number(btn.dataset.fundMonths);document.querySelectorAll('[data-fund-months]').forEach(b=>b.setAttribute('aria-pressed',String(b===btn)));loadDetail().catch(error);}));
 node('fund-trade-form').addEventListener('submit',async e=>{
  e.preventDefault();const btn=node('fund-trade-submit');btn.disabled=true;busy=true;
  try{await api('/api/funds/trade/save',{id:editing?.id||draftId,revision:editing?.revision||0,code:selected(),mode:node('fund-mode').value,kind:node('fund-trade-kind').value,status:node('fund-trade-status').value,date:node('fund-trade-date').value,amount:node('fund-trade-amount').value,units:node('fund-trade-units').value,note:node('fund-trade-note').value});clearForm();await loadDetail();node('fund-error').hidden=true;}catch(err){error(err);}finally{btn.disabled=false;busy=false;}
 });
 node('fund-trade-cancel').addEventListener('click',clearForm);
 node('fund-trades').addEventListener('click',async e=>{
  const edit=e.target.closest('[data-edit]'),del=e.target.closest('[data-delete]');
  if(edit){editing=detail.trades.find(t=>t.id===edit.dataset.edit);const t=editing;node('fund-trade-kind').value=t.kind;node('fund-trade-status').value=t.status;node('fund-trade-date').value=t.date;node('fund-trade-amount').value=t.amount;node('fund-trade-units').value=t.units;node('fund-trade-note').value=t.note;node('fund-trade-cancel').hidden=false;node('fund-trade-submit').textContent='保存修改';}
  if(del&&confirm('仅删除这条本地记录？这不会撤销真实交易。')){const t=detail.trades.find(t=>t.id===del.dataset.delete);try{await api('/api/funds/trade/delete',{id:t.id,revision:t.revision,mode:t.mode});clearForm();await loadDetail();}catch(err){error(err);}}
 });
 refreshOverview(true).then(()=>{clearForm();return loadDetail();}).catch(error);
 setInterval(async()=>{if(document.hidden||node('fundtracking').hidden||busy)return;try{await refreshOverview();await loadDetail();}catch(e){error(e);}},5000);
})();
