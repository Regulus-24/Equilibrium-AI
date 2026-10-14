"use strict";
(() => {
 let snapshot=null, selectedCategory=null, comparisonCategory=null;
 const empty=()=>({income:0,expense:0,balance:0,categories:{income:{},expense:{}}});
 const pad=n=>String(n).padStart(2,"0");
 function render(){
  if(!snapshot)return;
  const annual=$("stats-mode").value==="year", kind=$("stats-kind").value;
  $("stats-month-label").hidden=annual;$("stats-year-label").hidden=!annual;
  const period=annual?String(Number($("stats-year").value)).padStart(4,"0"):$("stats-month").value;
  const valid=annual?/^[0-9]{4}$/.test(period)&&Number(period)>=1:/^[0-9]{4}-(0[1-9]|1[0-2])$/.test(period)&&Number(period.slice(0,4))>=1;
  $("month-analysis").hidden=true;
  if(!valid){$("stats-period").textContent="请选择有效的年份或月份。";$("stats-chart").replaceChildren();$("stats-ranking").replaceChildren();$("stats-detail").hidden=true;for(const id of ["stats-income","stats-expense","stats-balance"])$(id).textContent="—";$("stats-average").textContent="";$("stats-summary").textContent="";return;}
  const year=Number(period.slice(0,4)), month=Number(period.slice(5,7));
  const leap=year%4===0&&(year%100!==0||year%400===0);
  const count=annual?12:[31,leap?29:28,31,30,31,30,31,31,30,31,30,31][month-1];
  const asOf=snapshot.as_of, unit=annual?"月":"日", label=kind==="income"?"收入":"支出";
  const total=(annual?snapshot.years:snapshot.months)[period]||empty();
  if(!annual)renderComparison(period,kind);
  const points=Array.from({length:count},(_,i)=>{
   const key=period+"-"+pad(i+1), future=key>(annual?asOf.slice(0,7):asOf);
   return {key,label:(i+1)+unit,value:future?null:((annual?snapshot.months:snapshot.days)[key]||empty())[kind]};
  });
  const elapsed=points.filter(p=>p.value!==null).length;
  $("stats-period").textContent=period+" · "+(annual?"年度":"月度")+"汇总"+(period===(annual?asOf.slice(0,4):asOf.slice(0,7))?" · 截至 "+asOf:elapsed===0?" · 尚未开始":"");
  for(const key of ["income","expense","balance"])$("stats-"+key).textContent=money(total[key]);
  $("stats-average").textContent=elapsed?(annual?"月均":"日均")+label+" "+money(Math.round(total[kind]/elapsed))+"（总"+label+" ÷ "+elapsed+(annual?"个月":"天")+"；含无记录日期，当前期间计至今日）":"该期间尚未开始，暂无平均值。";
  $("stats-chart-title").textContent=label+"趋势 · 按"+unit+"汇总";
  $("stats-ranking-title").textContent="分类"+label+"排行榜";
  $("stats-point").textContent="点击或悬停图中节点查看金额，也可用 Tab 键选择节点。";
  draw(points,label);
  const ranked=Object.entries(total.categories[kind]).sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0],"zh-CN"));
  const rows=snapshot.entries.filter(r=>r.date.startsWith(period)&&r.kind===kind);
  $("stats-summary").textContent=rows.length?"本期已记录 "+rows.length+" 笔"+label+"；金额最多的类别是“"+ranked[0][0]+"”，合计 "+money(ranked[0][1])+"。":"本期暂无已记录的"+label+"。可切换期间或收支类型查看。";
  $("stats-ranking").innerHTML=ranked.length?ranked.map(([name,cents],index)=>'<button type="button" class="stats-rank" data-rank="'+index+'"><span class="stats-rank-line"><span>'+esc(name)+' <small>'+((cents/total[kind])*100).toFixed(1)+'%</small></span><b>'+money(cents)+'</b></span><span class="stats-bar"><span style="width:'+(cents/total[kind]*100)+'%"></span></span></button>').join(""):'<div class="empty">没有可排名的'+label+'记录。</div>';
  $("stats-ranking").querySelectorAll("button").forEach((button,i)=>button.addEventListener("click",()=>{selectedCategory=ranked[i][0];details(rows,label);}));
  details(rows,label);
 }
 function details(rows,label){
  $("stats-detail").hidden=selectedCategory===null;
  if(selectedCategory===null)return;
  const matches=rows.filter(row=>row.category===selectedCategory);
  $("stats-detail-title").textContent=selectedCategory+" · "+label+"明细（"+matches.length+"笔）";
  $("stats-detail-rows").innerHTML=matches.length?matches.map(row=>'<div class="stats-detail-row"><span>'+esc(row.date)+'<br>'+esc(row.note||"无备注")+'</span><b>'+money(row.cents)+'</b></div>').join(""):'<p class="caption">当前期间没有该类别的记录。</p>';
 }
 function renderComparison(period,kind){
  $("month-analysis").hidden=false;
  const report=snapshot.comparisons?.[period], label=kind==="income"?"收入":"支出";
  $("analysis-title").textContent="月度"+label+"变化";
  $("analysis-categories").replaceChildren();$("analysis-evidence").hidden=true;
  $("analysis-contributions").textContent="";
  if(!report){
   $("analysis-range").textContent=period;
   $("analysis-caution").textContent=period>snapshot.as_of.slice(0,7)?"所选月份尚未开始。":"缺少该期间记录，暂不计算变化。";
   for(const id of ["analysis-current","analysis-previous","analysis-delta"])$(id).textContent="—";
   $("analysis-summary").textContent="可切换月份，或先补充记账记录。";return;
  }
  const value=report.kinds[kind];
  $("analysis-range").textContent="本期："+report.current_start+" 至 "+report.current_end+"（"+report.current_days+"天，"+report.current_count+"笔收支）｜上期："+(report.previous_start?report.previous_start+" 至 "+report.previous_end+"（整月"+report.previous_days+"天，"+report.previous_count+"笔收支）":"无更早月份");
  $("analysis-caution").textContent=report.partial?"本月尚未结束：按本月至今对比上月整月，两期时长不同。当前差额不代表本月最终增减，不作整月预测。":"整月对整月；只比较已记录金额，月份天数和记录完整程度可能不同。";
  $("analysis-current").textContent=money(value.current);$("analysis-previous").textContent=money(value.previous);
  const change=cents=>cents===0?"持平":(cents>0?"增加 ":"减少 ")+money(Math.abs(cents));
  if(report.status!=="ready"){
   $("analysis-delta").textContent="暂不比较";
   $("analysis-summary").textContent=report.status==="missing_previous"?"缺少上月记录，无法判断变化；上月显示的0仅表示没有录入。":"缺少本期记录，无法判断变化；本期显示的0仅表示没有录入。";
  }else{
   $("analysis-delta").textContent=change(value.delta);
   const rate=value.percent_basis_points===null?"上月已记录"+label+"为0，不计算变化百分比。":"相对上月整月的变化率为 "+(value.percent_basis_points>0?"+":"")+(value.percent_basis_points/100).toLocaleString("zh-CN",{maximumFractionDigits:2})+"%。";
   $("analysis-summary").textContent="本期已记录"+label+" "+money(value.current)+"，上月整月 "+money(value.previous)+"；"+change(value.delta)+"。"+rate;
   const increases=value.categories.filter(r=>r.delta>0).sort((a,b)=>b.delta-a.delta).slice(0,3);
   const decreases=value.categories.filter(r=>r.delta<0).sort((a,b)=>a.delta-b.delta).slice(0,3);
   $("analysis-contributions").textContent="各类别增加合计 "+money(value.increase)+"，减少合计 "+money(value.decrease)+"，相抵后"+change(value.delta)+"。"+(increases.length?"主要增加："+increases.map(r=>r.category+" "+money(r.delta)).join("、")+"。":"")+(decreases.length?"主要减少："+decreases.map(r=>r.category+" "+money(-r.delta)).join("、")+"。":"");
  }
  $("analysis-categories").innerHTML=value.categories.length?'<div class="table-scroll"><table><thead><tr><th>分类（按增减绝对金额排序）</th><th>本期</th><th>上月整月</th><th>增减</th></tr></thead><tbody>'+value.categories.map((row,i)=>'<tr><td><button type="button" class="text-button" data-compare-category="'+i+'">'+esc(row.category)+'</button></td><td>'+money(row.current)+'</td><td>'+money(row.previous)+'</td><td>'+(row.delta===null?"—":change(row.delta))+'</td></tr>').join("")+'</tbody></table></div>':'<p class="caption">两期没有已记录的'+label+'分类可展示。</p>';
  function evidence(){
   if(comparisonCategory===null)return;
   $("analysis-evidence").hidden=false;
   $("analysis-evidence-title").textContent=comparisonCategory+" · 两期"+label+"依据";
   for(const [id,start,end] of [["analysis-current-rows",report.current_start,report.current_end],["analysis-previous-rows",report.previous_start,report.previous_end]]){
    const rows=snapshot.entries.filter(r=>start&&r.kind===kind&&r.category===comparisonCategory&&r.date>=start&&r.date<=end);
    $(id).innerHTML=rows.length?rows.map(r=>'<div class="stats-detail-row"><span>'+esc(r.date)+'<br>'+esc(r.note||"无备注")+'</span><b>'+money(r.cents)+'</b></div>').join(""):'<p class="caption">该期间无此类别的已记录'+label+'。</p>';
   }
  }
  $("analysis-categories").querySelectorAll("button").forEach((button,i)=>button.addEventListener("click",()=>{comparisonCategory=value.categories[i].category;evidence();}));
  evidence();
 }
 function draw(points,label){
  const W=760,H=270,left=100,right=20,top=25,bottom=40;
  const max=Math.max(100,...points.map(p=>p.value||0));
  const x=i=>left+i*(W-left-right)/(points.length-1), y=v=>H-bottom-v/max*(H-top-bottom);
  const ticks=[0,max/2,max];
  let svg='<svg viewBox="0 0 '+W+' '+H+'" role="group" aria-label="'+label+'折线图，金额单位元"><title>'+label+'随日期变化</title>';
  for(const v of ticks)svg+='<line x1="'+left+'" x2="'+(W-right)+'" y1="'+y(v)+'" y2="'+y(v)+'" class="chart-grid"/><text x="'+(left-10)+'" y="'+(y(v)+4)+'" text-anchor="end">'+esc(money(Math.round(v)))+'</text>';
  const known=points.map((p,i)=>p.value===null?null:[x(i),y(p.value)]).filter(Boolean);
  svg+='<polyline points="'+known.map(p=>p.join(",")).join(" ")+'" class="chart-line"/>';
  points.forEach((p,i)=>{
   if(points.length===12||i===0||i===points.length-1||((i+1)%5===0&&i<points.length-3))svg+='<text x="'+x(i)+'" y="'+(H-12)+'" text-anchor="middle">'+p.label+'</text>';
   if(p.value!==null){const text=p.key+' · 已记录'+label+' '+money(p.value);svg+='<circle data-point="'+i+'" tabindex="0" role="button" aria-label="'+esc(text)+'" cx="'+x(i)+'" cy="'+y(p.value)+'" r="5" class="chart-dot"><title>'+esc(text)+'</title></circle>';}
  });
  svg+='</svg>';
  $("stats-chart").innerHTML=svg;
  $("stats-chart").querySelectorAll("[data-point]").forEach(dot=>{
   const display=()=>{const p=points[Number(dot.dataset.point)];$("stats-point").textContent=p.key+" · 已记录"+label+" "+money(p.value);};
   for(const event of ["mouseenter","focus","click"])dot.addEventListener(event,display);
   dot.addEventListener("keydown",event=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();display();}});
  });
 }
 for(const id of ["stats-mode","stats-month","stats-year","stats-kind"])$(id).addEventListener("change",()=>{selectedCategory=null;comparisonCategory=null;render();});
 window.renderLedgerStats=data=>{
  if(!snapshot){$("stats-month").value=data.as_of.slice(0,7);$("stats-year").value=data.as_of.slice(0,4);}
  snapshot=data;render();
 };
})();
