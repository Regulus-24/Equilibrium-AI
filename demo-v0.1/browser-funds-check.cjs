const {chromium}=require('C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const {spawn,spawnSync}=require('node:child_process');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict');
const root=__dirname,dataDir=fs.mkdtempSync(path.join(os.tmpdir(),'equilibrium-funds-')),port=18141;
// Synthetic quotes exist only in this temporary browser test, never the user app.
const seeded=spawnSync('python',['-c',`from funds import FundTracker, CATALOG
from datetime import date,timedelta
import sys
t=FundTracker(sys.argv[1]);s=t.read();start=date(2025,9,28)
rows=[dict(date=(start+timedelta(days=i)).isoformat(),per10k='1',annual7='3.65',nav=None) for i in range(366)]
for p in CATALOG:s['quotes'][p['code']]=rows
t.write(s)`,dataDir],{cwd:root,windowsHide:true,encoding:'utf8'});assert.equal(seeded.status,0,seeded.stderr);
const server=spawn('python',[path.join(root,'server.py'),'--port',String(port),'--data-dir',dataDir],{cwd:root,windowsHide:true,stdio:['ignore','pipe','pipe']});
let browser;
(async()=>{
 await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('Server timeout')),10000);server.once('error',reject);server.once('exit',c=>reject(Error('Exit '+c)));server.stdout.once('data',()=>{clearTimeout(timer);resolve();});});
 browser=await chromium.launch({headless:true,channel:'msedge'});
 const context=await browser.newContext(),page=await context.newPage(),errors=[];
 page.on('pageerror',e=>errors.push(e.message));await page.goto('http://127.0.0.1:'+port);await page.locator('#entry-save:enabled').waitFor();
 await page.locator('.nav[data-page="fundtracking"]').click();await page.locator('#fund-chart svg').waitFor();
 assert.equal(await page.locator('#fund-watchlist input').count(),5);
 for(const months of [1,3,6,12]){await page.locator(`[data-fund-months="${months}"]`).click();const count={1:32,3:93,6:185,12:366}[months];await page.waitForFunction(n=>document.querySelectorAll('#fund-chart [data-point]').length===n,count);}
 await page.locator('#fund-metric').selectOption('nav');assert.match(await page.locator('#fund-chart').textContent(),/没有单位净值历史/);
 await page.locator('#fund-metric').selectOption('cumulative');
 await page.locator('#fund-schedule-time').fill('10:15');await page.locator('#fund-settings button[type=submit]').click();await page.reload();await page.locator('.nav[data-page="fundtracking"]').click();await page.locator('#fund-chart svg').waitFor();
 assert.equal(await page.locator('#fund-schedule-time').inputValue(),'10:15');assert.equal(await page.locator('#fund-schedule-enabled').isChecked(),false);
 const add=async(amount,note)=>{await page.locator('#fund-trade-date').fill('2026-09-27');await page.locator('#fund-trade-amount').fill(amount);await page.locator('#fund-trade-units').fill(amount);await page.locator('#fund-trade-note').fill(note);await page.locator('#fund-trade-submit').click();await page.waitForFunction(t=>document.getElementById('fund-trades').textContent.includes(t),note);};
 await add('10000','实际测试');assert.equal(await page.locator('#fund-profit').textContent(),'2 元');assert.equal(await page.locator('#fund-chart [data-trade]').count(),1);
 await page.locator('#fund-mode').selectOption('simulation');await page.waitForFunction(()=>document.getElementById('fund-trades').textContent.includes('尚无交易'));
 await add('20000','模拟测试');assert.equal(await page.locator('#fund-profit').textContent(),'4 元');assert.doesNotMatch(await page.locator('#fund-trades').textContent(),/实际测试/);
 const other=await browser.newContext(),editor=await other.newPage();await editor.goto('http://127.0.0.1:'+port);await editor.locator('.nav[data-page="fundtracking"]').click();await editor.locator('#fund-chart svg').waitFor();
 await editor.locator('#fund-trades [data-edit]').click();await editor.locator('#fund-trade-note').fill('跨浏览器修改');await editor.locator('#fund-trade-submit').click();
 await page.locator('#fund-mode').selectOption('actual');await page.waitForFunction(()=>document.getElementById('fund-trades').textContent.includes('跨浏览器修改'));
 // Dirty schedule uses its original version even after a polling refresh.
 await page.locator('#fund-schedule-time').fill('11:30');await page.locator('#fund-schedule-time').press('Tab');
 await editor.locator('#fund-schedule-time').fill('12:30');await editor.locator('#fund-settings button[type=submit]').click();
 await page.waitForFunction(()=>document.getElementById('fund-schedule-state').textContent.includes('未开启'));await page.waitForTimeout(5300);
 assert.equal(await page.locator('#fund-schedule-time').inputValue(),'11:30');await page.locator('#fund-settings button[type=submit]').click();await page.waitForFunction(()=>document.getElementById('fund-error').textContent.includes('其他页面'));
 page.once('dialog',d=>d.accept());await page.locator('#fund-trades [data-delete]').click();await page.waitForFunction(()=>document.getElementById('fund-trades').textContent.includes('尚无交易'));
 await page.locator('#fund-mode').selectOption('simulation');await page.waitForFunction(()=>document.getElementById('fund-trades').textContent.includes('模拟测试'));
 await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 assert.deepEqual(errors,[]);await other.close();console.log('PASS: four periods, no fabricated NAV, persisted settings, isolated actual/simulation P&L and markers, cross-browser edit, stale-settings conflict, delete isolation, mobile overflow, no JS errors');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();server.kill();if(path.dirname(path.resolve(dataDir))===path.resolve(os.tmpdir())&&path.basename(dataDir).startsWith('equilibrium-funds-'))fs.rmSync(dataDir,{recursive:true,force:true});});
