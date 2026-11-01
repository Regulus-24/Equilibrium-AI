"use strict";
let state=null, token="", pending=null;
const $=id=>document.getElementById(id);
const money=cents=>"¥"+(cents/100).toLocaleString("zh-CN",{minimumFractionDigits:0,maximumFractionDigits:2});
const esc=s=>String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const systemStatuses=[];
function renderSystemStatuses(){const box=$("system-status"),list=$("system-status-list");if(!box||!list)return;box.hidden=!systemStatuses.length;list.innerHTML=systemStatuses.map((s,i)=>`<article class="reminder"><strong>${esc(s.title)}</strong><span>${esc(s.at)}</span><p>${esc(s.message)}</p><button class="quiet" data-status-action="${esc(s.action||'refresh')}" data-status-index="${i}" type="button">${esc(s.actionLabel||'刷新状态')}</button></article>`).join('');}
window.reportSystemStatus=(title,message,action='refresh',actionLabel='刷新状态')=>{if(systemStatuses.some(s=>s.title===title&&s.message===message&&s.action===action))return;systemStatuses.unshift({title,message,action,actionLabel,at:new Date().toLocaleTimeString('zh-CN')});if(systemStatuses.length>8)systemStatuses.pop();renderSystemStatuses();};
function showError(msg){$("error").innerHTML=esc(msg)+" <button class=\"quiet\" type=\"button\" data-recover-refresh>刷新状态</button>";$("error").hidden=false;window.reportSystemStatus('操作未完成',msg,'refresh','刷新状态');}
$("error").addEventListener("click",e=>{if(e.target.closest("[data-recover-refresh]"))location.reload();});
$("system-status-list").addEventListener("click",async e=>{const b=e.target.closest('[data-status-action]');if(!b)return;const action=b.dataset.statusAction;if(action==='refresh')location.reload();else if(action==='ledger-refresh'){page('bookkeeping');$('ledger-refresh').click();}else if(action==='ledger'){$("ledger-import").click();}else if(action==='funds'){page('fundtracking');$("fund-sync")?.click();}else if(action==='ics'){await exportReminders();return;}else if(action==='cases'){page('cards');if(!await loadCases())return;}systemStatuses.splice(Number(b.dataset.statusIndex),1);renderSystemStatuses();});
$("clear-system-status").addEventListener("click",()=>{systemStatuses.length=0;renderSystemStatuses();});
async function api(path,payload){
 const options=payload===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json","X-Demo-Token":token},body:JSON.stringify(payload)};
 const response=await fetch(path,options);const data=await response.json();
 if(!response.ok)throw new Error(data.error||"请求未完成，请刷新后检查状态。");return data;
}
function confirmAction(message){
 return new Promise(resolve=>{
  const dialog=document.createElement('dialog');
  dialog.setAttribute('aria-label','确认本地操作');
  dialog.innerHTML='<h2>确认本地操作</h2><p></p><div class="tools"><button type="button" data-cancel>取消操作</button><button type="button" data-confirm>确认继续</button></div>';
  dialog.querySelector('p').textContent=message;
  let finished=false;
  const finish=value=>{if(finished)return;finished=true;dialog.close();dialog.remove();resolve(value);};
  dialog.querySelector('[data-cancel]').onclick=()=>finish(false);
  dialog.querySelector('[data-confirm]').onclick=()=>finish(true);
  dialog.oncancel=event=>{event.preventDefault();finish(false);};
  document.body.appendChild(dialog);dialog.showModal();dialog.querySelector('[data-cancel]').focus();
 });
}
function page(name){
 document.querySelectorAll(".page").forEach(el=>el.hidden=el.id!==name);
 document.querySelectorAll(".nav").forEach(el=>el.classList.toggle("active",el.dataset.page===name));
 $("page-title").textContent={bookkeeping:"手动记账",assistant:"衡智助手",statistics:"账单统计",insights:"账单分析实验",fundtracking:"理财跟踪",wealth:"理财条件比较",cards:"卡片管理"}[name];
 $("error").hidden=true;
 if(name==="cards"&&state)refresh().catch(e=>showError(e.message));
}
function render(){
 const locked=state.card.status==="LOCKED";
 $("card-status").textContent=locked?"临时锁定":"正常使用";
 $("preview-lock").disabled=false;$("preview-lock").textContent=locked?"已锁定 · 重置模拟卡片":"预览临时锁卡";
 if(state.receipts.length){
  const r=state.receipts[state.receipts.length-1];
  $("receipt").innerHTML='<p class="receipt-title">'+(r.status==="VERIFIED"?"✓ 模拟锁卡已核验":"模拟操作已写入，待核验")+'</p><div class="receipt-grid"><div>卡片：尾号 '+esc(r.last4)+'</div><div>当前状态：临时锁定</div><div>回执：<code>'+esc(r.id)+'</code></div><div>时间：'+esc(new Date(r.at).toLocaleString("zh-CN"))+'</div></div><p class="caption">'+esc(r.note)+'</p>';
 }else{$("receipt").innerHTML='<p class="muted">尚未操作。预览不会改变卡片状态。</p>';}
 const labels={"demo.initialized":"模拟账户已初始化","plan.frozen":"已冻结操作预览，未执行","approval.recorded":"参与者确认具体计划（模拟）","operation.applied":"模拟卡片状态已写入","state.verified":"重新读取状态，核验通过"};
 $("events").innerHTML=state.events.map(e=>'<div class="event"><small>'+esc(new Date(e.at).toLocaleTimeString("zh-CN"))+'</small><div>'+esc(labels[e.event]||e.event)+(e.plan_id?'<br><small>'+esc(e.plan_id)+'</small>':"")+'</div></div>').join("");
}
async function loadCases(){try{const data=await api('/api/cases');const labels={OPEN:'待核查',UNDER_REVIEW:'核查中',LOCK_PREVIEWED:'已预览锁卡',LOCKED:'已锁卡',SUBMITTED:'已提交银行',CONFIRMED_NORMAL:'已确认正常',CLOSED:'已关闭'};$("cases").innerHTML=data.cases.length?data.cases.map(c=>'<article class="reminder"><strong>'+esc(c.status_label||labels[c.status]||c.status)+'</strong><span>'+esc(c.id)+'</span><p>证据 '+esc(c.transaction_ids.join('、'))+'</p><div class="tools">'+(c.status==='OPEN'?'<button class="quiet case-action" data-id="'+esc(c.id)+'" data-action="review">开始核查</button><button class="quiet case-action" data-id="'+esc(c.id)+'" data-action="mark_normal">确认正常</button><button class="quiet case-action" data-id="'+esc(c.id)+'" data-action="lock_previewed">预览锁卡</button>':'')+(c.status==='UNDER_REVIEW'?'<button class="quiet case-action" data-id="'+esc(c.id)+'" data-action="submit">提交银行</button>':'')+(c.status==='LOCK_PREVIEWED'?'<button class="quiet case-action" data-id="'+esc(c.id)+'" data-action="locked">确认已锁卡</button>':'')+((['OPEN','UNDER_REVIEW','SUBMITTED','LOCKED','LOCK_PREVIEWED'].includes(c.status))?'<button class="quiet case-action" data-id="'+esc(c.id)+'" data-action="close">关闭案件</button>':'')+'</div></article>').join(''):'<p class="muted">暂无异常处置案件。准备演示数据后可查看完整状态流转。</p>';return true;}catch(e){$("cases").textContent='案件暂不可用，请刷新后重试。';return false;}}
async function refresh(){state=await api("/api/state");token=state.csrf_token;render();loadReminders();loadCases();try{const period=window.__insightPeriod||new Date().toLocaleDateString('en-CA').slice(0,7);const [link,billing]=await Promise.all([fetch('/api/cross-scene?period='+encodeURIComponent(period)).then(r=>r.json()),fetch('/api/card/summary?period='+encodeURIComponent(period)).then(r=>r.json())]);$('card-cross-scene').textContent=link.explanation+' 当前联动状态：'+(link.action==='preview_temporary_lock'?'可预览临时锁卡':'请先核对账单')+'。';$('card-billing-summary').innerHTML='<div class="card-summary-grid"><div>分析期间<strong>'+esc(period)+'</strong></div><div>本期净支出<strong>'+money(billing.net_expense_cents)+'</strong></div><div>关联记录<strong>'+billing.transaction_count+' 笔</strong></div><div>距离还款日<strong>'+billing.days_to_due+' 天</strong></div><div>预计还款日<strong>'+esc(billing.next_payment_due)+'</strong></div></div><p class="caption">'+esc(billing.note)+'</p>';}catch(e){$('card-cross-scene').textContent='账单联动摘要暂不可用，请刷新后重试。';$('card-billing-summary').textContent='卡片账单摘要暂不可用，请刷新后重试。';}}
async function loadReminders(){try{const period=window.__insightPeriod||new Date().toLocaleDateString('en-CA').slice(0,7);const data=await fetch('/api/reminders?period='+encodeURIComponent(period)).then(r=>r.json());$('reminders').innerHTML=data.items.length?data.items.map(x=>'<article class="reminder"><strong>'+esc(x.title)+'</strong><span>'+esc(x.date)+'</span><p>'+esc(x.body)+'</p></article>').join(''):'<p class="muted">当前没有待处理提醒。</p>';}catch(e){$('reminders').textContent='提醒暂不可用，请刷新后重试。';}}
document.querySelectorAll("[data-page]").forEach(el=>el.addEventListener("click",()=>page(el.dataset.page)));
$("preview-lock").addEventListener("click",async()=>{
 if(state?.card.status==="LOCKED"){if(!await confirmAction("卡片已锁定。要恢复为正常使用以重新演示吗？"))return;try{await api("/api/reset",{confirm:true});await refresh();}catch(e){showError(e.message);}return;}
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
 try{const data=await api("/api/compare",{days:Number($("days").value),need_date:$("compare-need-date").value,accept_loss:$("loss").value==="yes"});
 $("products").innerHTML=data.products.map(p=>'<article class="product"><span class="tag '+(p.eligible?"":"amber")+'">'+(p.eligible?"条件暂未排除":"当前条件下排除")+'</span><h3>'+esc(p.name)+'</h3><p>'+esc(p.detail)+'</p><p>持有 '+p.term+' 天 · 预计到账 '+esc(p.arrival_date)+' · 数据 '+esc(p.freshness)+'（'+esc(p.data_date)+'）</p><div class="reason">'+esc(p.reason)+'</div><p class="caption">仍缺：'+p.missing_information.map(esc).join('、')+'</p></article>').join("")+'<div class="table-scroll" style="grid-column:1/-1"><table><thead><tr><th>比较维度</th><th>示例产品 A</th><th>示例产品 B</th></tr></thead><tbody>'+data.comparison.map(r=>'<tr><td>'+esc(r.criterion)+'</td>'+r.options.map(o=>'<td>'+esc(String(o.value))+(o.unit?' '+esc(o.unit):'')+'</td>').join('')+'</tr>').join('')+'</tbody></table></div><p class="caption" style="grid-column:1/-1">'+esc(data.note)+'</p>';
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
 if(!await confirmAction("清除本轮模拟操作记录并恢复示例卡片？已保存反馈会保留。"))return;
 try{await api("/api/reset",{confirm:true});pending=null;await refresh();}catch(e){showError(e.message);}
});
refresh().catch(e=>showError(e.message));
async function exportReminders(){
 const button=$("export-reminders-ics");if(button.disabled)return false;button.disabled=true;
 try{
  const period=window.__insightPeriod||new Date().toLocaleDateString('en-CA').slice(0,7);
  const response=await fetch('/api/reminders.ics?period='+encodeURIComponent(period));
  if(!response.ok)throw new Error('提醒导出失败，请重试导出。');
  const blob=await response.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='equilibrium-reminders.ics';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  for(let i=systemStatuses.length-1;i>=0;i--)if(systemStatuses[i].action==='ics')systemStatuses.splice(i,1);
  renderSystemStatuses();return true;
 }catch(e){window.reportSystemStatus('ICS 导出失败',e.message,'ics','重试导出 ICS');return false;}finally{button.disabled=false;}
}
$("export-reminders-ics").addEventListener("click",exportReminders);

async function demoAction(path,message){const button=$(path.endsWith("seed")?"demo-seed":"demo-clear");const status=$("demo-status");button.disabled=true;try{token=(await api("/api/state")).csrf_token;await api(path,{confirm:true});status.textContent=message;if(path.endsWith("seed"))window.__insightPeriod="2026-09";else delete window.__insightPeriod;await refresh();if(path.endsWith("seed")){page("cards");loadCases();}}catch(e){status.textContent=e.message;}finally{button.disabled=false;}}
$("demo-seed").addEventListener("click",()=>demoAction("/api/demo/seed","演示数据已准备，并已打开异常扣款场景。"));
$("demo-clear").addEventListener("click",()=>demoAction("/api/demo/clear","演示数据已清理；卡片已恢复正常，用户账单已保留。"));
$("demo-export").addEventListener("click",()=>download("/api/demo/evidence","equilibrium-demo-evidence.json").catch(e=>showError(e.message)));
$("cases").addEventListener("click",async e=>{const b=e.target.closest(".case-action");if(!b)return;b.disabled=true;try{token=(await api("/api/state")).csrf_token;await api("/api/cases/transition",{case_id:b.dataset.id,action:b.dataset.action});await loadCases();if(b.dataset.action==="lock_previewed")$("preview-lock").click();}catch(err){window.reportSystemStatus?.('案件操作冲突',err.message,'cases','刷新案件状态');b.disabled=false;}});

let assistantPending=null;
function renderAssistant(data){
 const result=$("assistant-result"); result.hidden=false;
 const tools=(data.tool_calls||[]).map(t=>'<span class="tag">'+esc(t.name)+'</span>').join(" ");
 const evidence=(data.evidence_ids||[]).length?'<p class="caption">依据记录：'+data.evidence_ids.map(esc).join("、")+'</p>':"";
 const missing=(data.missing_information||[]).length?'<p class="reason">需要补充：'+data.missing_information.map(esc).join("；")+'</p>':"";
 const limitations=(data.limitations||[]).length?'<ul class="caption">'+data.limitations.map(x=>'<li>'+esc(x)+'</li>').join("")+'</ul>':"";
 const source=data.source||"local";
 const sourceLabel=source==="qwen"?"Qwen 已验证":(source==="deterministic_fallback"?"本地规则回退":"本地规则");
 const sourceTag='<span class="tag">来源：'+esc(sourceLabel)+(data.model?' · '+esc(data.model):'')+'</span>';
 const fallback=data.fallback_reason?'<p class="caption">Qwen 不可用，已回退本地规则：'+esc(data.fallback_reason)+'</p>':"";
 let action="";
 if(data.requires_confirmation&&data.plan){
  assistantPending=data.plan;
  action='<div class="assistant-action"><button id="assistant-approve" class="primary" type="button">确认临时锁卡</button><button id="assistant-cancel" class="quiet" type="button">取消</button></div>';
 } else if(data.requires_confirmation&&data.order){
  assistantPending=data.order;
  action='<div class="assistant-action"><button id="assistant-order-approve" class="primary" type="button">确认模拟申购</button><button id="assistant-cancel" class="quiet" type="button">取消</button></div>';
 } else assistantPending=null;
 result.innerHTML='<div class="assistant-meta"><span class="tag">'+esc(data.intent)+'</span> '+sourceTag+' '+tools+'</div><p class="assistant-answer">'+esc(data.answer)+'</p>'+fallback+missing+evidence+limitations+action;
 const approve=$("assistant-approve");
 if(approve)approve.addEventListener("click",async()=>{
  approve.disabled=true;
  try{
   await api("/api/approve",{plan_id:assistantPending.plan.id,plan_hash:assistantPending.plan_hash,confirm:true});
   $("assistant-status").textContent="已执行并重新核验卡片状态。";assistantPending=null;await refresh();
   renderAssistant({intent:"card_management",answer:"尾号 0428 已临时锁定，状态已重新读取并核验。锁卡不会退款，也不等同于正式挂失。",tool_calls:[{name:"get_card_status",arguments:{card_id:"demo-card-0428"}},{name:"verify_card_status",arguments:{expected:"LOCKED"}}],evidence_ids:[],source_versions:{card_version:"updated"},missing_information:[],requires_confirmation:false});
  }
  catch(e){$("assistant-status").textContent=e.message;approve.disabled=false;}
 });
 const orderApprove=$("assistant-order-approve");
 if(orderApprove)orderApprove.addEventListener("click",async()=>{
  orderApprove.disabled=true;
  try{const out=await api("/api/order/confirm",{order_id:assistantPending.id,preview_hash:assistantPending.preview_hash,confirm:true});$("assistant-status").textContent="模拟订单已完成，可在订单记录中查询。";assistantPending=null;renderAssistant({intent:"wealth_operation",answer:"模拟订单已完成，状态为 COMPLETED。真实银行和基金平台未发生交易。",tool_calls:[{name:"query_order",arguments:{order_id:out.order.id}}],evidence_ids:[out.order.id],source_versions:{order_version:"updated"},missing_information:[],requires_confirmation:false});}
  catch(e){$("assistant-status").textContent=e.message;orderApprove.disabled=false;}
 });
 const cancel=$("assistant-cancel");if(cancel)cancel.addEventListener("click",()=>{assistantPending=null;result.hidden=true;});
}
$("assistant-form").addEventListener("submit",async e=>{
 e.preventDefault();const message=$("assistant-message").value.trim();if(!message)return;
 const btn=$("assistant-send");btn.disabled=true;$("assistant-status").textContent="正在读取受控业务事实……";
 try{const data=await api("/api/agent/chat",{message,context:{}});renderAssistant(data);$("assistant-status").textContent=data.source==="qwen"?"Qwen 已返回并完成服务端校验。": "已使用本地规则生成可核对结果。";}
 catch(err){$("assistant-status").textContent=err.message;}
 finally{btn.disabled=false;}
});
$("assistant-clear").addEventListener("click",()=>{$("assistant-message").value="";$("assistant-result").hidden=true;$("assistant-status").textContent="";assistantPending=null;});
