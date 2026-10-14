"use strict";
let state=null, token="", pending=null;
const $=id=>document.getElementById(id);
const money=cents=>"¥"+(cents/100).toLocaleString("zh-CN",{minimumFractionDigits:0,maximumFractionDigits:2});
const esc=s=>String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function showError(msg){$("error").textContent=msg;$("error").hidden=false;}
async function api(path,payload){
 const options=payload===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json","X-Demo-Token":token},body:JSON.stringify(payload)};
 const response=await fetch(path,options);const data=await response.json();
 if(!response.ok)throw new Error(data.error||"请求未完成，请刷新后检查状态。");return data;
}
function page(name){
 if(name==="wealth")name="fundtracking";
 document.querySelectorAll(".page").forEach(el=>el.hidden=el.id!==name);
 document.querySelectorAll(".nav").forEach(el=>el.classList.toggle("active",el.dataset.page===name));
 $("page-title").textContent={bookkeeping:"手动记账",statistics:"账单统计",insights:"账单分析实验",overview:"示例账单与资金",fundtracking:"理财跟踪",wealth:"理财条件比较",cards:"卡片管理"}[name];
 $("error").hidden=true;
}
function render(){
 $("expense").textContent=money(state.summary.net_expense);$("income").textContent=money(state.summary.income);$("balance").textContent=money(state.balance_cents);
 $("summary-note").textContent=state.summary.note;
 const colors=["#315b9d","#7199c4","#92bdb4","#b3c9dc","#d5c0a0","#c29166"];
 const categories=Object.entries(state.summary.categories).sort((a,b)=>b[1]-a[1]);
 $("categories").innerHTML=categories.map(([name,value],i)=>'<div class="category"><span><i style="background:'+colors[i]+'"></i>'+esc(name)+'</span><span><b>'+money(value)+'</b><em>'+(value/state.summary.net_expense*100).toFixed(1)+'%</em></span></div>').join("");
 $("distribution").innerHTML=categories.map(([name,value],i)=>'<span title="'+esc(name)+' '+money(value)+'" style="background:'+colors[i]+';flex:'+value+'"></span>').join("");
 $("transactions").innerHTML=state.transactions.map(t=>'<tr><td>'+esc(t.date.slice(5))+'</td><td>'+esc(t.merchant)+'</td><td>'+esc(t.category)+'</td><td>'+(t.kind==="expense"?"−":"+")+money(t.cents)+'</td></tr>').join("");
 const locked=state.card.status==="LOCKED";
 $("card-status").textContent=locked?"临时锁定":"正常使用";
 $("preview-lock").disabled=locked;$("preview-lock").textContent=locked?"已临时锁定":"预览临时锁卡";
 if(state.receipts.length){
  const r=state.receipts[state.receipts.length-1];
  $("receipt").innerHTML='<p class="receipt-title">'+(r.status==="VERIFIED"?"✓ 模拟锁卡已核验":"模拟操作已写入，待核验")+'</p><div class="receipt-grid"><div>卡片：尾号 '+esc(r.last4)+'</div><div>当前状态：临时锁定</div><div>回执：<code>'+esc(r.id)+'</code></div><div>时间：'+esc(new Date(r.at).toLocaleString("zh-CN"))+'</div></div><p class="caption">'+esc(r.note)+'</p>';
 }else{$("receipt").innerHTML='<p class="muted">尚未操作。预览不会改变卡片状态。</p>';}
 const labels={"demo.initialized":"模拟账户已初始化","plan.frozen":"已冻结操作预览，未执行","approval.recorded":"参与者确认具体计划（模拟）","operation.applied":"模拟卡片状态已写入","state.verified":"重新读取状态，核验通过"};
 $("events").innerHTML=state.events.map(e=>'<div class="event"><small>'+esc(new Date(e.at).toLocaleTimeString("zh-CN"))+'</small><div>'+esc(labels[e.event]||e.event)+(e.plan_id?'<br><small>'+esc(e.plan_id)+'</small>':"")+'</div></div>').join("");
}
async function refresh(){state=await api("/api/state");token=state.csrf_token;render();}
document.querySelectorAll("[data-page]").forEach(el=>el.addEventListener("click",()=>page(el.dataset.page)));
$("preview-lock").addEventListener("click",async()=>{
 $("preview-lock").disabled=true;
 try{pending=await api("/api/plan",{card_id:state.card.id});$("consent").checked=false;$("approve-lock").disabled=true;$("confirm-error").hidden=true;$("confirm-dialog").showModal();await refresh();}
 catch(e){showError(e.message);await refresh().catch(()=>{});}
});
$("consent").addEventListener("change",()=>{$("approve-lock").disabled=!$("consent").checked;});
$("cancel-lock").addEventListener("click",()=>{$("confirm-dialog").close();pending=null;});
$("approve-lock").addEventListener("click",async()=>{
 if(!pending||!$("consent").checked)return;
 $("approve-lock").disabled=true;
 try{await api("/api/approve",{plan_id:pending.plan.id,plan_hash:pending.plan_hash,confirm:true});pending=null;$("confirm-dialog").close();await refresh();}
 catch(e){$("confirm-error").textContent=e.message;$("confirm-error").hidden=false;$("approve-lock").disabled=false;}
});
$("compare-form").addEventListener("submit",async e=>{
 e.preventDefault();const btn=e.submitter;btn.disabled=true;
 try{const data=await api("/api/compare",{days:Number($("days").value),accept_loss:$("loss").value==="yes"});
 $("products").innerHTML=data.products.map(p=>'<article class="product"><span class="tag '+(p.eligible?"":"amber")+'">'+(p.eligible?"待进一步核实":"当前条件下排除")+'</span><h3>'+esc(p.name)+'</h3><p>'+esc(p.detail)+'</p><p>非保本 · 无真实发行机构 · 无收益承诺</p><div class="reason">'+esc(p.reason)+'</div></article>').join("")+'<p class="caption" style="grid-column:1/-1">'+esc(data.note)+'</p>';
 }catch(err){showError(err.message);}finally{btn.disabled=false;}
});
$("feedback-open").addEventListener("click",()=>{$("feedback-message").textContent="";$("feedback-dialog").showModal();});
$("feedback-form").addEventListener("submit",async e=>{
 e.preventDefault();const btn=e.submitter;btn.disabled=true;
 try{const result=await api("/api/feedback",{useful:$("useful").value,note:$("feedback-note").value.trim()});$("feedback-message").textContent="已保存到本机，编号 "+result.id+"。谢谢，你的反馈会用于下一版。";$("feedback-note").value="";}
 catch(err){$("feedback-message").textContent=err.message;}finally{btn.disabled=false;}
});
async function download(path,name){const data=await api(path);const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:"application/json"}));const a=document.createElement("a");a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
$("export-evidence").addEventListener("click",()=>download("/api/evidence","equilibrium-demo-evidence.json").catch(e=>showError(e.message)));
$("export-feedback").addEventListener("click",()=>download("/api/feedback","equilibrium-feedback.json").catch(e=>showError(e.message)));
$("reset").addEventListener("click",async()=>{
 if(!confirm("清除本轮模拟操作记录并恢复示例卡片？已保存反馈会保留。"))return;
 try{await api("/api/reset",{confirm:true});pending=null;await refresh();}catch(e){showError(e.message);}
});
refresh().catch(e=>showError(e.message));

