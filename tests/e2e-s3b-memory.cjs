const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn}=require('node:child_process'),{chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'novel-s3b-browser-'));
const python=process.env.NOVEL_WRITER_PYTHON,report={checks:[],external:[],errors:[]};let server,browser;
async function modulePage(page,name){await page.waitForFunction(()=>!document.querySelector('#toggle-modules').disabled);let button=page.locator('#tabs').getByRole('button',{name,exact:true,includeHidden:true});if(!await button.isVisible())await page.locator('#toggle-modules').click();await button.click();await page.waitForFunction(()=>!document.querySelector('#toggle-modules').disabled);}
async function saved(page){await page.waitForFunction(()=>document.querySelector('#save-state').textContent.startsWith('已保存'));}
async function stop(){if(server&&server.exitCode===null)await new Promise(r=>{server.once('exit',r);server.kill();});}
(async()=>{
 const db=path.join(temp,'fictional.sqlite3'),frozen=JSON.parse(fs.readFileSync(path.join(root,'tests/fixtures/s3b_legacy_v1.json')));fs.writeFileSync(db,Buffer.from(frozen.database_hex,'hex'));
 server=spawn(python,['-B','-X','utf8','-u','run.py','--no-browser','--offline','--port','0','--database',db],{cwd:root,windowsHide:true,env:process.env});server.stderr.on('data',d=>process.stderr.write(d));
 const url=await new Promise((resolve,reject)=>{let s='';const timer=setTimeout(()=>reject(new Error('startup')),10000);server.stdout.on('data',d=>{s+=d;const m=s.match(/http:\/\/127\.0\.0\.1:\d+/);if(m){clearTimeout(timer);resolve(m[0]);}});});
 browser=await chromium.launch({headless:true,executablePath:process.env.NOVEL_WRITER_BROWSER});const context=await browser.newContext({viewport:{width:1440,height:900}});
 await context.route('**/*',route=>{if(new URL(route.request().url()).hostname!=='127.0.0.1'){report.external.push(route.request().url());return route.abort();}return route.continue();});
 const page=await context.newPage();page.on('pageerror',e=>report.errors.push(e.message));await page.goto(url);
 if(!await page.locator('#project-list').isVisible())await page.locator('#toggle-left').click();await page.locator('[data-project="p1"]').click();await saved(page);
 await modulePage(page,'长篇记忆');assert.equal(await page.locator('#memory-select').count(),1,'手动记忆实际入口缺失');
 await page.getByLabel('记忆标题',{exact:true}).fill('港口事件');await page.getByLabel('记忆正文',{exact:true}).fill('\n人工记忆 KEYWORD_MEMORY  ');
 await page.getByLabel('适用故事位置',{exact:true}).selectOption('p1-c5');await page.getByLabel('来源对象',{exact:true}).selectOption({label:'正文 · 第5章 章节5'});
 await page.getByLabel('作者已确认',{exact:true}).check();await page.getByRole('button',{name:'保存记忆',exact:true}).click();await saved(page);
 let state=await(await page.request.get(url+'/api/projects/p1')).json();assert.equal(state.workspace_version,2);const id=state.memories[0].id;
 await page.reload();await modulePage(page,'长篇记忆');await page.locator('#memory-select').selectOption(id);await saved(page);
 assert.equal(await page.getByLabel('记忆正文',{exact:true}).inputValue(),'\n人工记忆 KEYWORD_MEMORY  ');assert.ok((await page.locator('#memory-freshness').textContent()).includes('来源未变'));
 report.checks.push('新增确认记忆与V2保存刷新，原文/来源新鲜度');
 await modulePage(page,'章节写作');await page.locator('#chapter-select').selectOption('p1-c5');await page.getByLabel('正文',{exact:true}).fill('来源新正文');await page.getByRole('button',{name:'保存正文',exact:true}).click();await saved(page);
 await modulePage(page,'长篇记忆');assert.ok((await page.locator('#memory-freshness').textContent()).includes('已过期'));
 await page.getByRole('button',{name:'查看固定来源',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#memory-source-result').textContent.includes('BODY_p1_5'));
 await page.getByRole('button',{name:'复核来源并更新确认',exact:true}).click();await saved(page);assert.ok((await page.locator('#memory-freshness').textContent()).includes('来源未变'));
 report.checks.push('正文变更记忆过期，固定旧出处仍可追溯，显式复核');
 await page.getByRole('button',{name:'本地字面检索',exact:true}).click();await page.waitForSelector('#local-search-form');
 await page.getByLabel('检索词',{exact:true}).fill('KEYWORD_MEMORY');await page.getByLabel('检索故事位置',{exact:true}).selectOption('p1-c5');
 await page.getByRole('button',{name:'检索已保存资料',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#local-search-status').textContent.includes('1 条命中'));
 await page.getByRole('button',{name:'跳到出处',exact:true}).click();await page.waitForSelector('#memory-select');assert.equal(await page.getByLabel('记忆标题',{exact:true}).inputValue(),'港口事件');
 await page.getByRole('button',{name:'本地字面检索',exact:true}).click();await page.getByLabel('检索词',{exact:true}).fill('KEYWORD_MEMORY');await page.getByLabel('检索故事位置',{exact:true}).selectOption('p1-c5');await page.getByRole('button',{name:'检索已保存资料',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#local-search-status').textContent.includes('1 条命中'));
 await page.getByLabel('选入此来源',{exact:true}).check();await page.getByRole('button',{name:'预览已选资料',exact:true}).click();
 await page.getByRole('button',{name:'生成只读预览',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#context-preview-text').textContent.includes('KEYWORD_MEMORY'));
 report.checks.push('字面命中、真实记忆出处跳转、选入上下文重校验');
 await modulePage(page,'长篇记忆');await page.getByRole('button',{name:'归档记忆',exact:true}).click();await saved(page);
 state=await(await page.request.get(url+'/api/projects/p1')).json();assert.equal(state.memories[0].active,false);assert.equal(state.memory_history.length,3);
 await page.getByRole('button',{name:'本地字面检索',exact:true}).click();await page.getByLabel('检索词',{exact:true}).fill('没有这个检索词');await page.getByRole('button',{name:'检索已保存资料',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#local-search-status').textContent.includes('0 条命中'));
 report.checks.push('归档保留历史及无命中诚实报告');
 for(const [w,h]of[[1440,900],[390,844]]){await page.setViewportSize({width:w,height:h});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);}
 assert.deepEqual(report.external,[]);assert.deepEqual(report.errors,[]);report.status='passed';console.log(JSON.stringify(report));
 fs.writeFileSync(path.join(process.env.NOVEL_WRITER_ARTIFACTS,'s3b-browser-report.json'),JSON.stringify(report,null,2));
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();await stop();fs.rmSync(temp,{recursive:true,force:true});});
