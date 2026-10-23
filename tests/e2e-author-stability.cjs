'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const {spawn}=require('node:child_process');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
if(!process.env.NOVEL_WRITER_ARTIFACTS)throw Error('Explicit owned evidence directory required');
const out=path.resolve(process.env.NOVEL_WRITER_ARTIFACTS),fixture=path.join(out,'fixture');
fs.mkdirSync(fixture,{recursive:true});
const report={status:'running',checks:[],errors:[],external:[],provider_calls:0};
let server,browser,page,url;
const fault=(name,enabled)=>{const file=path.join(fixture,'fault-'+name);if(enabled)fs.writeFileSync(file,'fictional scoped fault');else fs.rmSync(file,{force:true});};
async function start(){
  server=spawn(process.env.NOVEL_WRITER_PYTHON||'python',['-B','-X','utf8','-u','tests/author_stability_server.py',fixture],{cwd:root,windowsHide:true,env:{...process.env,PYTHONPATH:path.join(root,'src'),PYTHONDONTWRITEBYTECODE:'1'}});
  server.stderr.on('data',chunk=>fs.appendFileSync(path.join(out,'server.log'),chunk));
  return new Promise((resolve,reject)=>{let output='';const timer=setTimeout(()=>reject(Error('Fixture startup timeout')),15000);server.stdout.on('data',chunk=>{output+=chunk;const match=output.match(/http:\/\/127\.0\.0\.1:\d+/);if(match){clearTimeout(timer);resolve(match[0]);}});server.once('exit',code=>{clearTimeout(timer);reject(Error('Fixture exit '+code));});});
}
async function saved(){await page.waitForFunction(()=>document.querySelector('#save-state')?.textContent.startsWith('已保存'));}
async function activate(name){
  await page.waitForFunction(()=>!document.querySelector('#toggle-modules').disabled);
  const module=page.locator('#tabs').getByRole('button',{name,exact:true,includeHidden:true});
  if(await module.count()&&!await module.isVisible())await page.locator('#toggle-modules').click();
  await page.getByRole('button',{name,exact:true}).click();
}
async function writing(){await activate('章节写作');await page.locator('#edit-content').waitFor();}
async function settings(){
  const target=page.locator('#tabs [data-view="settings"]');
  if(!await target.isVisible())await page.locator('#toggle-modules').click();
  await target.click();await page.locator('#local-data-preview').waitFor();
}
async function state(){return await page.evaluate(async()=>{const projects=await(await fetch('/api/projects')).json();return await(await fetch('/api/projects/'+projects[0].id)).json();});}
async function untilDraft(text){await page.waitForFunction(async expected=>{const items=await(await fetch('/api/projects')).json();const list=await(await fetch('/api/projects/'+items[0].id+'/drafts')).json();return list.drafts?.some(d=>d.values.content===expected);},text);}
async function create(kind,label,value){await page.getByRole('button',{name:kind,exact:true}).click();await page.locator('#create-dialog').getByLabel(label,{exact:true}).fill(value);await page.locator('#create-dialog').getByRole('button',{name:'创建',exact:true}).click();await saved();}
async function screenshot(name){await page.screenshot({path:path.join(out,name+'.png'),fullPage:false});}

(async()=>{
  url=await start();
  browser=await chromium.launch({headless:true,executablePath:process.env.NOVEL_WRITER_BROWSER});
  const context=await browser.newContext({viewport:{width:1440,height:900},acceptDownloads:true});
  await context.route('**/*',route=>{if(route.request().url().startsWith(url+'/'))return route.continue();report.external.push(route.request().url());return route.abort();});
  page=await context.newPage();page.on('pageerror',error=>report.errors.push(error.message));
  page.on('dialog',dialog=>dialog.accept());
  await page.goto(url);
  await page.waitForFunction(()=>!document.querySelector('#save-state')?.textContent.includes('处理'));
  await page.getByRole('button',{name:'创建小说',exact:true}).click();
  await page.locator('#create-dialog').getByLabel('小说名称',{exact:true}).fill('隔离作者验收');
  await page.locator('#create-dialog').getByRole('button',{name:'创建',exact:true}).click();await saved();
  await activate('章节写作');
  await create('＋ 新建章节','章节标题','第一章 虚构港湾');
  const original='\n\n虚构正文😀，只有本地数据。  \n';
  await page.locator('#edit-content').fill(original);await page.keyboard.press('Control+s');await saved();
  assert.equal((await state()).document.chapters[0].content,original);
  report.checks.push('offline/no credentials: real UI creates book/chapter and saves exact leading LF, emoji and whitespace');

  fault('body-save',true);const failed=original+'数据库失败仍保留';
  await page.locator('#edit-content').fill(failed);await page.keyboard.press('Control+s');
  await page.waitForFunction(()=>document.querySelector('#notification').textContent.includes('失败'));
  assert.equal(await page.locator('#edit-content').inputValue(),failed);assert.equal((await state()).document.chapters[0].content,original);
  fault('body-save',false);await page.keyboard.press('Control+s');await saved();
  assert.equal((await state()).document.chapters[0].content,failed);
  report.checks.push('injected SQLite full: save fails, UI input and saved body remain distinct, retry appends normally');

  fault('draft-write',true);const newer=failed+'草稿磁盘满模拟';
  await page.locator('#edit-content').fill(newer);
  await page.waitForFunction(()=>document.querySelector('#save-state').textContent.includes('恢复草稿存储异常'));
  assert.equal(await page.locator('#edit-content').inputValue(),newer);await screenshot('draft-write-failure');
  fault('draft-write',false);await settings();await page.locator('#local-data-retry').click();
  await page.waitForFunction(()=>document.querySelector('#local-data-result').textContent.includes('重试完成'));
  await writing();assert.equal(await page.locator('#edit-content').inputValue(),newer);await untilDraft(newer);
  report.checks.push('injected ENOSPC: draft input persists in memory and explicit settings retry writes exact input');

  // A failed retry must not hydrate the older on-disk draft over newer memory.
  fault('draft-write',true);const newest=newer+'较新内存';await page.locator('#edit-content').fill(newest);await settings();await page.locator('#local-data-retry').click();
  await page.waitForFunction(()=>document.querySelector('#local-data-result').textContent.includes('仍有'));
  await writing();assert.equal(await page.locator('#edit-content').inputValue(),newest);fault('draft-write',false);
  await settings();await page.locator('#local-data-retry').click();await page.waitForFunction(()=>document.querySelector('#local-data-result').textContent.includes('重试完成'));await writing();await untilDraft(newest);
  await page.reload();await writing();assert.equal(await page.locator('#edit-content').inputValue(),newest);assert.ok((await page.locator('#draft-review').innerText()).includes('本地恢复草稿'));
  report.checks.push('failed retry keeps newer memory over old disk draft; actual page reopen restores the successful draft without body commit');

  fault('draft-clear',true);await page.keyboard.press('Control+s');await saved();
  await page.waitForFunction(()=>document.querySelector('#save-state').textContent.includes('恢复草稿存储异常'));
  assert.equal((await state()).document.chapters[0].content,newest);
  fault('draft-clear',false);await settings();await page.locator('#local-data-retry').click();await page.waitForFunction(()=>document.querySelector('#local-data-result').textContent.includes('重试完成'));
  report.checks.push('permission-denied draft cleanup does not misreport formal save; explicit retry clears stale recovery file');

  fault('draft-read',true);await page.reload();await writing();
  assert.equal(await page.locator('#edit-content').inputValue(),newest);
  assert.ok((await page.locator('#save-state').innerText()).includes('恢复草稿存储异常'));
  fault('draft-read',false);await settings();await page.locator('#local-data-retry').click();await page.waitForFunction(()=>document.querySelector('#local-data-result').textContent.includes('重试完成'));
  report.checks.push('permission-denied draft read at startup keeps saved body usable; later recovery read can be retried');

  const corrupt=path.join(fixture,'drafts','a'.repeat(64)+'.json');fs.writeFileSync(corrupt,'{private-corrupt-marker');
  fs.writeFileSync(path.join(fixture,'drafts','unknown-private.txt'),'private-text');
  await page.locator('#local-data-preview').click();await page.waitForFunction(()=>document.querySelectorAll('[data-local-cleanup]').length===1);
  const diagnostic=await page.locator('#local-data-report').inputValue();assert.ok(!diagnostic.includes('private-'));assert.ok(!diagnostic.includes(fixture));assert.ok(!diagnostic.includes('隔离作者验收'));
  assert.equal(await page.locator('#local-data-cleanup').isDisabled(),true);
  await page.locator('[data-local-cleanup]').check();await page.locator('#local-data-cleanup').click();await page.waitForFunction(()=>document.querySelector('#local-data-result').textContent.includes('实际清理 1 个'));
  assert.equal(fs.existsSync(corrupt),false);assert.ok(fs.existsSync(path.join(fixture,'drafts','unknown-private.txt')));
  report.checks.push('real diagnostic preview is redacted, requires per-item selection and confirm, preserves unknown files');

  await writing();await page.getByRole('button',{name:'切换上下文面板',exact:true}).click();
  if(!await page.locator('#left-panel').isVisible())await page.getByRole('button',{name:'切换导航面板',exact:true}).click();
  assert.ok(await page.locator('#right-panel').isVisible());assert.ok(await page.locator('#left-panel').isVisible());
  await screenshot('wide-two-panels');await page.setViewportSize({width:640,height:800});
  await page.getByRole('button',{name:'切换导航面板',exact:true}).click();await page.locator('#close-left').click();
  const narrow=newest+'窄屏继续写';await page.locator('#edit-content').fill(narrow);await page.keyboard.press('Control+s');await saved();assert.equal((await state()).document.chapters[0].content,narrow);
  await screenshot('narrow-writing');
  await page.setViewportSize({width:390,height:844});await page.locator('#edit-content').scrollIntoViewIfNeeded();
  assert.ok(await page.locator('.chapter-writing-toolbar').evaluate(element=>element.getBoundingClientRect().height<=174));
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await screenshot('390-writing');await settings();await page.locator('#local-data-preview').click();await page.waitForFunction(()=>document.querySelector('#local-data-result').textContent.includes('预览完成'));
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await screenshot('390-diagnostics');
  report.checks.push('1440 two side panels; 640 and 390 narrow edit/save, bounded scrollable chapter toolbar and redacted diagnostics without page overflow');
  assert.deepEqual(report.errors,[]);assert.deepEqual(report.external,[]);report.status='passed';
})().catch(async error=>{report.status='failed';report.error=String(error.stack||error);if(page)await screenshot('failure').catch(()=>{});process.exitCode=1;}).finally(async()=>{if(browser)await browser.close().catch(()=>{});if(server)server.kill();fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));process.stdout.write(JSON.stringify(report)+'\n');});
