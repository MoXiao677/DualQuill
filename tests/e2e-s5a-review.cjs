const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn}=require('node:child_process'),{chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'novel-s5a-browser-'));let server,browser;
const report={checks:[],external:[],errors:[]};
async function modulePage(page,name){await page.waitForFunction(()=>!document.querySelector('#toggle-modules').disabled);const b=page.locator('#tabs').getByRole('button',{name,exact:true,includeHidden:true});if(!await b.isVisible())await page.locator('#toggle-modules').click();await b.click();await page.waitForFunction(()=>!document.querySelector('#toggle-modules').disabled);}
(async()=>{
 const fixture=JSON.parse(fs.readFileSync(path.join(root,'tests/fixtures/s5a_legacy.json'))),db=path.join(temp,'fictional.sqlite3');fs.writeFileSync(db,Buffer.from(fixture.v3.database_hex,'hex'));
 server=spawn(process.env.NOVEL_WRITER_PYTHON,['-B','-X','utf8','-u','run.py','--no-browser','--offline','--port','0','--database',db],{cwd:root,windowsHide:true,env:process.env});server.stderr.on('data',d=>process.stderr.write(d));
 const url=await new Promise((resolve,reject)=>{let s='';const timer=setTimeout(()=>reject(new Error('startup')),10000);server.stdout.on('data',d=>{s+=d;const m=s.match(/http:\/\/127\.0\.0\.1:\d+/);if(m){clearTimeout(timer);resolve(m[0]);}});});
 browser=await chromium.launch({headless:true,executablePath:process.env.NOVEL_WRITER_BROWSER});const context=await browser.newContext({viewport:{width:1440,height:900}});await context.route('**/*',route=>{if(new URL(route.request().url()).hostname!=='127.0.0.1'){report.external.push(route.request().url());return route.abort();}return route.continue();});
 const page=await context.newPage();page.on('pageerror',e=>report.errors.push(e.message));await page.goto(url);
 const session=await(await page.request.get(url+'/api/session')).json();let state=await(await page.request.get(url+'/api/projects/p1')).json();
 for(const [id,content]of[['p1-c5','禁用词。\n\n港口灯塔照亮潮水，船员静静等待远方来信。'],['p1-c6','港口灯塔照亮潮水，船员静静等待远方来信。']]){const r=await page.request.post(url+'/api/projects/p1/actions',{headers:{'X-Novel-Token':session.token},data:{action:'save_chapter',fields:{chapter_id:id,content},expected_revision:state.revision}});assert.equal(r.status(),200);state=await r.json();}
 if(!await page.locator('#project-list').isVisible())await page.locator('#toggle-left').click();await page.locator('[data-project="p1"]').click();await modulePage(page,'章节写作');await page.locator('#chapter-select').selectOption('p1-c5');
 assert.equal(await page.getByRole('button',{name:'离线审核与查重',exact:true}).count(),1,'审核实际入口缺失');await page.getByRole('button',{name:'离线审核与查重',exact:true}).click();await page.waitForSelector('#audit-prepare-form');
 await page.getByLabel('审核章节范围',{exact:true}).selectOption(['p1-c5','p1-c6']);await page.getByLabel('禁用字面串（每行一条）',{exact:true}).fill('禁用词');
 await page.getByRole('button',{name:'冻结并准备离线审核',exact:true}).click();await page.waitForSelector('#execute-local-task');await page.getByRole('button',{name:'执行离线规则审核',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#task-status').textContent.includes('成功'));
 assert.equal(await page.locator('#adopt-generation-candidate').count(),0);await page.getByRole('button',{name:'查看审核报告',exact:true}).click();await page.waitForSelector('#review-report-status');
 assert.ok((await page.locator('#review-findings').textContent()).includes('禁用'));assert.ok((await page.locator('#review-findings').textContent()).includes('精确重复'));
 report.checks.push('可见范围/规则冻结→同一任务管线真实离线审核，分析不提供正文采纳');
 await page.getByRole('button',{name:'跳到证据出处',exact:true}).first().click();await page.waitForSelector('#edit-content');assert.ok((await page.getByLabel('正文',{exact:true}).inputValue()).includes('禁用词'));
 await page.getByRole('button',{name:'离线审核与查重',exact:true}).click();await page.waitForSelector('#review-report-select');
 const duplicate=page.locator('[data-review-rule="duplicate_exact"]').first();await duplicate.getByLabel('处理理由',{exact:true}).fill('作者允许的回环');await duplicate.getByLabel('将确切双侧原文与规则加入白名单',{exact:true}).check();await duplicate.getByRole('button',{name:'标为误报',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('[data-review-rule="duplicate_exact"]').textContent.includes('false_positive'));
 report.checks.push('双侧原文出处可跳转，误报理由/白名单/处理状态持久');
 const proposal=page.locator('[data-memory-proposal]').first();await proposal.getByLabel('确认并保留现有不同记忆',{exact:true}).check();const old=await(await page.request.get(url+'/api/projects/p1')).json();
 await proposal.getByRole('button',{name:'接受并确认摘录为新记忆',exact:true}).click();await page.waitForFunction(()=>document.querySelector('[data-memory-proposal]').textContent.includes('accepted'));
 const after=await(await page.request.get(url+'/api/projects/p1')).json();assert.equal(after.memories.length,old.memories.length+1);assert.equal(after.document.versions.length,old.document.versions.length);
 await page.reload();await modulePage(page,'章节写作');await page.getByRole('button',{name:'离线审核与查重',exact:true}).click();await page.waitForSelector('#review-report-status');assert.ok((await page.locator('#review-report-status').textContent()).includes('来源未变'));
 report.checks.push('显式接受提案仅新增可追溯记忆，不改正文，刷新仍有报告/收据');
 const current=await(await page.request.get(url+'/api/projects/p1')).json();await page.request.post(url+'/api/projects/p1/actions',{headers:{'X-Novel-Token':session.token},data:{action:'save_chapter',fields:{chapter_id:'p1-c5',content:'来源已更新'},expected_revision:current.revision}});
 await page.getByRole('button',{name:'刷新审核状态',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#review-report-status').textContent.includes('已过期'));
 for(const [w,h]of[[1440,900],[390,844]]){await page.setViewportSize({width:w,height:h});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);}
 report.checks.push('来源更新显示过期，真实接受保护由后端重核；窄屏不溢出');assert.deepEqual(report.external,[]);assert.deepEqual(report.errors,[]);report.status='passed';console.log(JSON.stringify(report));fs.writeFileSync(path.join(process.env.NOVEL_WRITER_ARTIFACTS,'s5a-browser-report.json'),JSON.stringify(report,null,2));
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();if(server&&server.exitCode===null)await new Promise(r=>{server.once('exit',r);server.kill();});fs.rmSync(temp,{recursive:true,force:true});});
