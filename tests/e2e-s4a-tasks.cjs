const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn}=require('node:child_process'),{chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'novel-s4a-browser-'));
const report={checks:[],external:[],errors:[]};let server,browser;
async function modulePage(page,name){await page.waitForFunction(()=>!document.querySelector('#toggle-modules').disabled);const button=page.locator('#tabs').getByRole('button',{name,exact:true,includeHidden:true});if(!await button.isVisible())await page.locator('#toggle-modules').click();await button.click();await page.waitForFunction(()=>!document.querySelector('#toggle-modules').disabled);}
async function saved(page){await page.waitForFunction(()=>document.querySelector('#save-state').textContent.startsWith('已保存'));}
(async()=>{
 const frozen=JSON.parse(fs.readFileSync(path.join(root,'tests/fixtures/s4a_legacy.json'))),db=path.join(temp,'fictional.sqlite3');fs.writeFileSync(db,Buffer.from(frozen.v2.database_hex,'hex'));
 server=spawn(process.env.NOVEL_WRITER_PYTHON,['-B','-X','utf8','-u','run.py','--no-browser','--offline','--local-protocol-demo','--port','0','--database',db],{cwd:root,windowsHide:true,env:process.env});server.stderr.on('data',d=>process.stderr.write(d));
 const url=await new Promise((resolve,reject)=>{let text='';const timer=setTimeout(()=>reject(new Error('startup')),10000);server.stdout.on('data',d=>{text+=d;const m=text.match(/http:\/\/127\.0\.0\.1:\d+/);if(m){clearTimeout(timer);resolve(m[0]);}});server.once('exit',code=>{clearTimeout(timer);reject(new Error('server exit '+code));});});
 browser=await chromium.launch({headless:true,executablePath:process.env.NOVEL_WRITER_BROWSER});const context=await browser.newContext({viewport:{width:1440,height:900}});
 await context.route('**/*',route=>{if(new URL(route.request().url()).hostname!=='127.0.0.1'){report.external.push(route.request().url());return route.abort();}return route.continue();});
 const page=await context.newPage();page.on('pageerror',e=>report.errors.push(e.message));await page.goto(url);
 if(!await page.locator('#project-list').isVisible())await page.locator('#toggle-left').click();await page.locator('[data-project="p1"]').click();await saved(page);await modulePage(page,'章节写作');await page.locator('#chapter-select').selectOption('p1-c5');
 await page.getByLabel('正文',{exact:true}).fill('UNSAVED_TASK_DRAFT');await page.getByRole('button',{name:'预览已保存上下文',exact:true}).click();
 await page.getByRole('button',{name:'生成只读预览',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#context-preview-report').textContent.length>0);
 assert.equal(await page.locator('#prepare-local-task').count(),1,'缺少真实任务准备入口');
 await page.getByLabel('整章改写要求',{exact:true}).fill('本地协议验收');await page.getByRole('button',{name:'准备整章改写任务',exact:true}).click();await page.waitForSelector('#task-status');
 assert.ok((await page.locator('#task-mode').textContent()).includes('本地协议'));assert.ok(!(await page.locator('#task-frozen').textContent()).includes('UNSAVED_TASK_DRAFT'));
 report.checks.push('可见上下文准备V3任务，冻结已保存原稿且排除未保存草稿');
 await page.getByRole('button',{name:'执行本地协议验证',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#task-status').textContent.includes('成功'));
 assert.ok((await page.locator('#task-candidate').textContent()).includes('不是真实AI输出'));assert.ok((await page.locator('#task-original').textContent()).includes('旧V2冻结正文'));
 const original=await(await page.request.get(url+'/api/projects/p1')).json();const beforeVersions=original.document.versions.length;
 // 写入后丢弃响应，UI必须按同一采纳UUID核对，不重复追加正文版本。
 await page.route('**/tasks/*/adopt',async route=>{await route.fetch();await route.abort('failed');});
 await page.getByRole('button',{name:'明确采纳候选为新草稿',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#task-adoption-result').textContent.includes('采纳已核对'));
 await page.unroute('**/tasks/*/adopt');
 const after=await(await page.request.get(url+'/api/projects/p1')).json();assert.equal(after.document.versions.length,beforeVersions+1);assert.equal(after.adoption_receipts.length,1);assert.ok(after.document.chapters[4].content.includes('本地协议验证'));
 report.checks.push('单一执行管线完成候选/差异，显式采纳响应丢失恰一次');
 await page.reload();await modulePage(page,'章节写作');await page.getByRole('button',{name:'任务与候选',exact:true}).click();await page.waitForSelector('#task-select');
 assert.ok((await page.locator('#task-adoption-result').textContent()).includes('采纳已核对'));assert.equal((await(await page.request.get(url+'/api/projects/p1')).json()).adoption_receipts.length,1);
 report.checks.push('刷新重开持久任务/候选/收据，不自动重跑');
 for(const [w,h]of[[1440,900],[390,844]]){await page.setViewportSize({width:w,height:h});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);}
 assert.deepEqual(report.external,[]);assert.deepEqual(report.errors,[]);report.status='passed';console.log(JSON.stringify(report));fs.writeFileSync(path.join(process.env.NOVEL_WRITER_ARTIFACTS,'s4a-browser-report.json'),JSON.stringify(report,null,2));
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();if(server&&server.exitCode===null)await new Promise(r=>{server.once('exit',r);server.kill();});fs.rmSync(temp,{recursive:true,force:true});});
