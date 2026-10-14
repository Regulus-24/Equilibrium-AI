const { chromium } = require('C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:"msedge"});
 const page=await browser.newPage({viewport:{width:1440,height:1120},deviceScaleFactor:1});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(process.env.DEMO_URL || 'http://127.0.0.1:18128');
 await page.locator('[data-page="overview"]').click();
 await page.getByText('¥6,909',{exact:true}).waitFor();
 await page.screenshot({path:'preview-desktop.jpg',type:'jpeg',quality:75,fullPage:true});
 await page.getByRole('button',{name:'比较理财条件'}).click();
 await page.getByRole('button',{name:'查看比较结果'}).click();
 await page.getByText('当前条件下排除',{exact:true}).first().waitFor();
 if(await page.getByText('当前条件下排除',{exact:true}).count()!==2) throw new Error('No-loss filtering failed');
 await page.selectOption('#loss','yes');await page.selectOption('#days','90');
 await page.getByRole('button',{name:'查看比较结果'}).click();
 await page.getByText('待进一步核实',{exact:true}).waitFor();
 await page.getByRole('button',{name:'▤ 卡片管理'}).click();
 await page.getByRole('button',{name:'预览临时锁卡'}).click();
 if(!await page.getByRole('button',{name:'确认模拟锁卡'}).isDisabled()) throw new Error('Confirmation not gated');
 await page.getByRole('button',{name:'暂不操作'}).click();
 if(await page.locator('#card-status').textContent()!=='正常使用')throw new Error('Cancel mutated card');
 await page.getByRole('button',{name:'预览临时锁卡'}).click();
 await page.locator('#consent').check();
 await page.getByRole('button',{name:'确认模拟锁卡'}).click();
 await page.getByText('✓ 模拟锁卡已核验',{exact:true}).waitFor();
 await page.reload();
 await page.getByRole('button',{name:'▤ 卡片管理'}).click();
 await page.getByText('✓ 模拟锁卡已核验',{exact:true}).waitFor();
 await page.screenshot({path:'preview-receipt.jpg',type:'jpeg',quality:75,fullPage:true});
 // Clear only this QA simulation; do not create fabricated participant feedback.
 await page.evaluate(async()=>{
  const s=await(await fetch('/api/state')).json();
  await fetch('/api/reset',{method:'POST',headers:{'Content-Type':'application/json','X-Demo-Token':s.csrf_token},body:JSON.stringify({confirm:true})});
 });
 await page.reload();
 await page.setViewportSize({width:390,height:844});
 await page.screenshot({path:'preview-mobile.jpg',type:'jpeg',quality:70,fullPage:true});
 const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
 if(overflow)throw new Error('Mobile horizontal overflow');
 if(errors.length)throw new Error(errors.join('\n'));
 console.log(JSON.stringify({passed:true,checks:['ledger','no-loss exclusions','liquidity comparison','confirmation checkbox','cancel has no mutation','lock receipt','reload persistence','mobile no horizontal overflow','no page exceptions'],screenshots:['preview-desktop.jpg','preview-receipt.jpg','preview-mobile.jpg']}));
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});


