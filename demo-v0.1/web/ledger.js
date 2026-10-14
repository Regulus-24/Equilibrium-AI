"use strict";
(() => {
 let ledger=null, editing=null, entryId=crypto.randomUUID(), busy=false, loadId=0, refreshing=false;
 const today=new Date();
 const localDate=[today.getFullYear(),String(today.getMonth()+1).padStart(2,"0"),String(today.getDate()).padStart(2,"0")].join("-");
 const kind=()=>document.querySelector('input[name="entry-kind"]:checked').value;
 const amountText=cents=>String(Math.floor(cents/100))+(cents%100?"."+String(cents%100).padStart(2,"0").replace(/0$/,""):"");
 $("entry-date").value=localDate;$("entry-date").max=localDate;$("ledger-month").value=localDate.slice(0,7);
 function error(message){$("entry-error").textContent=message;$("entry-error").hidden=!message;}
 function categories(selected=""){
  if(!ledger)return;
  $("entry-category").replaceChildren(...ledger.categories[kind()].map(name=>new Option(name,"category:"+name)),new Option("＋ 自定义类别","__custom__"));
  if(selected)$("entry-category").value="category:"+selected;
  customField();
  $("entry-save").textContent=editing?"保存修改":(kind()==="income"?"保存这笔收入":"保存这笔支出");
 }
 function customField(){const custom=$("entry-category").value==="__custom__";$("custom-category-wrap").hidden=!custom;$("entry-custom").required=custom;}
 function resetForm(){
  editing=null;entryId=crypto.randomUUID();$("entry-form").reset();$("entry-date").value=localDate;
  $("entry-title").textContent="记一笔，慢慢看清。";$("entry-cancel").hidden=true;categories();error("");
 }
 function renderLedger(){
  const month=$("ledger-month").value;
  const scope=$("ledger-scope").value, filterKind=$("ledger-kind").value, query=$("ledger-search").value.trim().toLocaleLowerCase();
  const scopeRows=ledger.entries.filter(row=>scope==="all"||row.date.slice(0,7)===month);
  const rows=scopeRows.filter(row=>(filterKind==="all"||row.kind===filterKind)&&(!query||row.category.toLocaleLowerCase().includes(query)||row.note.toLocaleLowerCase().includes(query)));
  const totals=ledger.months[month]||{income:0,expense:0,balance:0,categories:{income:{},expense:{}}};
  $("manual-income").textContent=money(totals.income);$("manual-expense").textContent=money(totals.expense);$("manual-balance").textContent=money(totals.balance);
  $("entry-count").textContent=rows.length+" / "+scopeRows.length+" 笔";
  const matchedIncome=rows.reduce((sum,row)=>sum+(row.kind==="income"?row.cents:0),0);
  const matchedExpense=rows.reduce((sum,row)=>sum+(row.kind==="expense"?row.cents:0),0);
  $("ledger-results-summary").textContent=(scope==="all"?"全部月份":(month||"未选择月份"))+" · 匹配 "+rows.length+" 笔 · 收入 "+money(matchedIncome)+" · 支出 "+money(matchedExpense);
  $("manual-categories").innerHTML=["expense","income"].map(type=>{
   const values=Object.entries(totals.categories[type]).sort((a,b)=>b[1]-a[1]);
   return values.length?'<div><h3>'+ (type==="expense"?"支出分类":"收入分类")+'</h3>'+values.map(([name,cents])=>'<div class="category"><span>'+esc(name)+'</span><b>'+money(cents)+'</b></div>').join("")+'</div>':"";
  }).join("");
  let lastDay="";
  const dayHeader=day=>{
   if(lastDay===day)return "";lastDay=day;
   const total=ledger.days[day];
   const weekday=new Date(day+"T12:00:00").toLocaleDateString("zh-CN",{weekday:"long"});
   return '<div class="daily-heading"><strong>'+esc(day)+' '+esc(weekday)+'</strong><span>当日全部记录 · 收入 '+money(total.income)+' · 支出 '+money(total.expense)+'</span></div>';
  };
  $("manual-entries").innerHTML=rows.length?rows.map(row=>dayHeader(row.date)+'<article class="manual-row"><div><div class="entry-row-title"><strong>'+esc(row.category)+'</strong><span>'+esc(row.date)+'</span></div>'+(row.note?'<p class="entry-note">'+esc(row.note)+'</p>':'<p class="caption">无备注</p>')+'</div><div class="entry-row-right"><strong class="entry-value '+row.kind+'">'+(row.kind==="income"?"+":"−")+money(row.cents)+'</strong><div><button type="button" class="text-button" data-edit="'+esc(row.id)+'" aria-label="编辑 '+esc(row.category)+' '+amountText(row.cents)+'">编辑</button><button type="button" class="text-button danger" data-delete="'+esc(row.id)+'" aria-label="删除 '+esc(row.category)+' '+amountText(row.cents)+'">删除</button></div></div></article>').join(""):'<div class="empty">'+(scopeRows.length?'没有匹配的记录。<br>试试调整关键词、收支类型或查找范围。':(scope==="all"?'账本还没有记录。':'所选月份还没有记录。')+'<br>可以记一笔，或调整查找范围。')+'</div>';
 }
 async function load(automatic=false){
  const id=++loadId, next=await api("/api/ledger");
  if(id!==loadId||(automatic&&busy))return;
  const changed=!ledger||ledger.version!==next.version||ledger.as_of!==next.as_of;
  ledger=next;
  if(changed){
   renderLedger();
   window.renderLedgerStats(ledger);
   // Refresh available categories without replacing a draft or its selection.
   const select=$("entry-category"), selected=select.value, label=select.selectedOptions[0]?.text;
   categories();
   if(selected){
    if(!Array.from(select.options).some(o=>o.value===selected))select.add(new Option(label,selected));
    select.value=selected;customField();
   }
   if(automatic)$("ledger-status").textContent="账本已自动更新，正在填写的内容已保留。";
  }
 }
 async function autoRefresh(){
  if(document.hidden||busy||refreshing||!ledger)return;
  refreshing=true;
  try{await load(true);}catch(e){$("ledger-status").textContent="自动更新失败，连接恢复后会重试。";}finally{refreshing=false;}
 }
 setInterval(autoRefresh,3000);
 window.addEventListener("focus",autoRefresh);
 document.addEventListener("visibilitychange",autoRefresh);
 $("ledger-backup").addEventListener("click",async()=>{
  if(busy)return;
  try{
   const backup=await api("/api/ledger/backup");
   const url=URL.createObjectURL(new Blob([JSON.stringify(backup,null,2)],{type:"application/json"}));
   const link=document.createElement("a");link.href=url;link.download="衡智账本-"+new Date().toISOString().replace(/[:.]/g,"-")+".json";link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
   $("ledger-status").textContent="账本备份已生成，请在浏览器下载中保存 JSON 文件。";
  }catch(e){error(e.message);}
 });
 $("ledger-restore").addEventListener("click",()=>{if(!busy)$("ledger-backup-file").click();});
 $("ledger-backup-file").addEventListener("change",async event=>{
  const file=event.target.files[0];event.target.value="";if(!file||busy)return;
  busy=true;++loadId;error("");
  try{
   if(file.size>5*1024*1024)throw new Error("备份文件最多 5 MB。");
   let backup;try{backup=JSON.parse(await file.text());}catch(e){throw new Error("文件不是有效的 JSON 备份。");}
   token=(await api("/api/state")).csrf_token;
   const preview=await api("/api/ledger/restore-preview",{backup});
   if(!confirm("备份含 "+preview.count+" 笔记录，将替换当前全部 "+preview.current_count+" 笔记录（不是合并）。恢复前会自动备份当前账本；正在填写的表单将清空。确认恢复？"))return;
   const result=await api("/api/ledger/restore",{backup,expected_version:preview.expected_version,confirm:true});
   resetForm();await load();categories();
   $("ledger-status").textContent="已恢复 "+result.count+" 笔记录。恢复前副本保存在数据目录的 "+result.safety_backup;
  }catch(e){error(e.message);}finally{busy=false;}
 });
 document.querySelectorAll('input[name="entry-kind"]').forEach(radio=>radio.addEventListener("change",()=>categories()));
 $("entry-category").addEventListener("change",customField);
 $("entry-cancel").addEventListener("click",resetForm);
 $("ledger-month").addEventListener("change",()=>{if(ledger)renderLedger();});
 ["ledger-search","ledger-scope","ledger-kind"].forEach(id=>$(id).addEventListener(id==="ledger-search"?"input":"change",()=>{if(ledger)renderLedger();}));
 $("ledger-clear-filters").addEventListener("click",()=>{
  $("ledger-search").value="";$("ledger-scope").value="month";$("ledger-kind").value="all";
  if(ledger)renderLedger();
 });
 $("ledger-refresh").addEventListener("click",async()=>{try{await load();$("ledger-status").textContent="账本已刷新。";}catch(e){error(e.message);}});
 $("entry-form").addEventListener("submit",async event=>{
  event.preventDefault();if(busy||!ledger)return;error("");
  const amount=$("entry-amount").value.trim();
  if(!/^[0-9]{1,9}(?:\.[0-9]{1,2})?$/.test(amount)||!/[1-9]/.test(amount)){error("请输入大于 0 的金额，最多 9 位整数、2 位小数。不会自动四舍五入。");return;}
  const category=($("entry-category").value==="__custom__"?$("entry-custom").value:$("entry-category").value.slice(9)).trim();
  if(!category){error("请输入自定义类别名称。");return;}
  const payload={id:editing?editing.id:entryId,revision:editing?editing.revision:0,kind:kind(),amount,date:$("entry-date").value,category,note:$("entry-note").value};
  busy=true;$("entry-form").querySelectorAll("input,select,textarea,button").forEach(el=>el.disabled=true);
  let saved=false;
  try{
   // Refresh CSRF token before a write, including after a local server restart.
   token=(await api("/api/state")).csrf_token;
   await api("/api/ledger/save",payload);saved=true;editing=null;entryId=crypto.randomUUID();
   $("ledger-month").value=payload.date.slice(0,7);await load();resetForm();
   $("ledger-status").textContent="已保存到本机账本。"+($("ledger-search").value.trim()||$("ledger-kind").value!=="all"?"若列表中未显示，请检查查找条件。":"");
  }catch(e){
   if(saved){resetForm();error("记录已保存，但列表刷新失败。请点击刷新账本，不要重复录入。");}
   else error(e.message);
  }finally{busy=false;$("entry-form").querySelectorAll("input,select,textarea,button").forEach(el=>el.disabled=false);}
 });
 $("manual-entries").addEventListener("click",async event=>{
  const button=event.target.closest("button");if(!button||busy)return;
  const row=ledger.entries.find(entry=>entry.id===(button.dataset.edit||button.dataset.delete));if(!row)return;
  if(button.dataset.edit){
   editing=row;document.querySelector('input[name="entry-kind"][value="'+row.kind+'"]').checked=true;categories(row.category);
   $("entry-amount").value=amountText(row.cents);$("entry-date").value=row.date;$("entry-note").value=row.note;
   $("entry-title").textContent="修改这笔记录";$("entry-cancel").hidden=false;error("");$("entry-amount").focus();return;
  }
  if(!confirm("删除这笔 "+row.category+" "+money(row.cents)+" 的记录？删除后将更新月度汇总。"))return;
  busy=true;button.disabled=true;
  try{token=(await api("/api/state")).csrf_token;await api("/api/ledger/delete",{id:row.id,revision:row.revision});if(editing?.id===row.id)resetForm();await load();$("ledger-status").textContent="记录已删除，汇总已更新。";}
  catch(e){error(e.message);}finally{busy=false;button.disabled=false;}
 });
 load().then(()=>{categories();$("entry-save").disabled=false;}).catch(e=>error("账本加载失败："+e.message+" 请刷新页面重试。"));
})();
