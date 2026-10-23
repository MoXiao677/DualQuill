'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {spawn}=require('node:child_process');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
if(!process.env.NOVEL_WRITER_ARTIFACTS)throw Error('Explicit owned evidence directory required');
const out=path.resolve(process.env.NOVEL_WRITER_ARTIFACTS),fixture=path.join(out,'fixture');
fs.mkdirSync(fixture,{recursive:true});
const report={status:'running',checks:[],errors:[],external:[],real_provider_calls:0};
let server,browser,page,url;
async function start(){
 server=spawn(process.env.NOVEL_WRITER_PYTHON,['-B','-X','utf8','-u','tests/author_stability_server.py',fixture],{cwd:root,windowsHide:true,env:{...process.env,PYTHONPATH:path.join(root,'src'),PYTHONDONTWRITEBYTECODE:'1'}});
 server.stderr.on('data',chunk=>fs.appendFileSync(path.join(out,'server.log'),chunk));
 return new Promise((resolve,reject)=>{let output='';const timer=setTimeout(()=>reject(Error('startup timeout')),15000);server.stdout.on('data',chunk=>{output+=chunk;const match=output.match(/http:\/\/127\.0\.0\.1:\d+/);if(match){clearTimeout(timer);resolve(match[0]);}});server.once('exit',code=>{clearTimeout(timer);reject(Error('fixture exit '+code));});});
}
async function saved(){await page.waitForFunction(()=>document.querySelector('#save-state')?.textContent.startsWith('已保存'));}
async function activate(view){
 await page.waitForFunction(()=>!document.querySelector('#toggle-modules').disabled);
 const button=page.locator('#tabs [data-view="'+view+'"]');
 if(!await button.isVisible())await page.locator('#toggle-modules').click();
 await button.click();
}
async function state(){return page.evaluate(async()=>{const projects=await(await fetch('/api/projects')).json();return(await fetch('/api/projects/'+projects[0].id)).json();});}
async function bodyIs(body){await page.waitForFunction(async value=>{const p=await(await fetch('/api/projects')).json();const s=await(await fetch('/api/projects/'+p[0].id)).json();return s.document.chapters[0]?.content===value;},body);await saved();}
async function scopeIs(scope){await page.waitForFunction(async expected=>{const p=await(await fetch('/api/projects')).json();return p[0].author_state===expected;},scope);await saved();}
async function lifecycle(action,after){
 await page.locator('[data-project-scope-preview="'+action+'"]').click();
 await page.locator('#project-scope-confirm-title').fill('虚构作者二阶段');
 await page.locator('#project-scope-confirmed').check();
 await page.locator('#commit-project-scope').click();await scopeIs(after);
}
(async()=>{
 try{
  url=await start();browser=await chromium.launch({headless:true,executablePath:process.env.NOVEL_WRITER_BROWSER});
  const context=await browser.newContext({viewport:{width:1440,height:900},acceptDownloads:true});
  await context.route('**/*',route=>{if(route.request().url().startsWith(url+'/'))return route.continue();report.external.push(route.request().url());return route.abort();});
  page=await context.newPage();page.on('pageerror',error=>report.errors.push(error.message));page.on('dialog',dialog=>dialog.accept());await page.goto(url);
  await page.getByRole('button',{name:'创建小说',exact:true}).click();await page.locator('#create-dialog').getByLabel('小说名称',{exact:true}).fill('虚构作者二阶段');await page.locator('#create-dialog').getByRole('button',{name:'创建',exact:true}).click();await saved();
  await activate('writing');await page.getByRole('button',{name:'＋ 新建章节',exact:true}).first().click();await page.locator('#create-dialog').getByLabel('章节标题',{exact:true}).fill('虚构选区');await page.locator('#create-dialog').getByRole('button',{name:'创建',exact:true}).click();await saved();
  const original='\n前言😀e\u0301\n受保护🧭正文。\n结尾  ';
  await page.locator('#edit-content').fill(original);await page.keyboard.press('Control+s');await bodyIs(original);
  await page.locator('#edit-content').evaluate(editor=>{const start=editor.value.indexOf('受保护'),end=start+'受保护🧭正文。'.length;editor.focus();editor.setSelectionRange(start,end);});
  await page.locator('#lock-body-selection').click();await page.locator('[data-unlock-range]').waitFor();await saved();
  let s=await state();let lock=s.author_scope_events.at(-1).data;
  assert.equal(lock.start,Array.from(original.slice(0,original.indexOf('受保护'))).length);assert.equal(lock.end-lock.start,Array.from('受保护🧭正文。').length);
  const unicode=await page.evaluate(async()=>{const module=await import('/author_scope.js');try{module.codepointRange('a😀b',1,2);return false;}catch{return true;}});assert.equal(unicode,true);
  report.checks.push('real UI selects supplementary emoji/combining Unicode body range, code-point persistence and split-surrogate rejection');
  const outside='新增😀\n'+original+'尾部';await page.locator('#edit-content').fill(outside);await page.keyboard.press('Control+s');await bodyIs(outside);
  const before=await state(),rejected=outside.replace('受保护','被更改');await page.locator('#edit-content').fill(rejected);await page.keyboard.press('Control+s');
  await page.waitForFunction(()=>document.querySelector('#notification').textContent.includes('locked_body_range_changed'));
  assert.equal(await page.locator('#edit-content').inputValue(),rejected);assert.deepEqual(await state(),before);
  report.checks.push('outside save rebases exact lock; overlapping manual save rejects with unchanged body/revision/history and retained input');
  await page.locator('#edit-content').fill(outside);await page.keyboard.press('Control+s');await bodyIs(outside);await page.reload();await activate('writing');await page.locator('[data-unlock-range]').waitFor();assert.equal(await page.locator('#edit-content').inputValue(),outside);
  await page.locator('#author-scope').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'persistent-body-lock.png')});
  await activate('project');const pre=await state();await page.locator('[data-project-scope-preview="archive"]').click();assert.deepEqual(await state(),pre);
  await page.locator('#project-scope-confirm-title').fill('错误书名');await page.locator('#project-scope-confirmed').check();await page.locator('#commit-project-scope').click();await page.waitForFunction(()=>document.querySelector('#author-scope-result').textContent.includes('完整书名'));assert.deepEqual(await state(),pre);
  await page.locator('#project-scope-confirm-title').fill('虚构作者二阶段');await page.locator('#commit-project-scope').click();await scopeIs('archived');
  await page.locator('#project-scope-filter').selectOption('archived');assert.equal(await page.locator('[data-project]').count(),1);
  await activate('writing');assert.equal(await page.locator('#edit-content').getAttribute('readonly'),'');
  await activate('project');await lifecycle('trash','deleted');await page.locator('#project-scope-filter').selectOption('deleted');assert.equal(await page.locator('[data-project]').count(),1);
  await page.screenshot({path:path.join(out,'whole-project-trash.png')});await lifecycle('restore','archived');await lifecycle('restore','active');
  report.checks.push('whole-project zero-write preview, exact title confirmation, archive/trash shelf filters, read-only body and restore to prior archived then active state');
  await activate('writing');await page.locator('[data-unlock-range]').click();await page.waitForFunction(()=>document.querySelector('#body-lock-list').textContent.includes('尚无'));
  await page.locator('#edit-content').fill(rejected);await page.keyboard.press('Control+s');await bodyIs(rejected);
  report.checks.push('fresh explicit unlock permits later author save; lifecycle restoration never implicitly unlocks');
  for(const width of [900,760]){await page.setViewportSize({width,height:900});await page.waitForTimeout(100);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true);await page.screenshot({path:path.join(out,'body-lock-'+width+'.png')});}
  report.checks.push('1440, 900 and 760 pixel real Edge layouts; screenshots retained');
  assert.deepEqual(report.errors,[]);assert.deepEqual(report.external,[]);report.status='passed';
 }catch(error){report.status='failed';report.error=error.stack;if(page)await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});throw error;}
 finally{if(browser)await browser.close();if(server)server.kill();fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));}
})().catch(error=>{console.error(error);process.exitCode=1;});
