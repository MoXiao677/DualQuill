// S1 真实浏览器验收，全部资料为虚构内容，数据库仅在临时目录。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'novel-writer-s1-'));
const database = path.join(temporary, 'test.sqlite3');
let server, browser;
async function start() {
  server = spawn(process.env.NOVEL_WRITER_PYTHON || 'python', ['-B', '-X', 'utf8', '-u', '-c', "import sys; sys.path.insert(0,'src'); from novel_writer.ui.server import create_server; s=create_server(sys.argv[1],port=0); print('http://127.0.0.1:'+str(s.server_address[1]),flush=True); s.serve_forever()", database], { cwd: root, windowsHide: true });
  return new Promise((resolve, reject) => {
    let text = ''; const timeout = setTimeout(() => reject(new Error('服务启动超时')), 10000);
    server.stdout.on('data', chunk => { text += chunk; const match = text.match(/http:\/\/127[.]0[.]0[.]1:[0-9]+/); if (match) { clearTimeout(timeout); resolve(match[0]); } });
    server.stderr.on('data', chunk => process.stderr.write(chunk));
    server.once('exit', code => { clearTimeout(timeout); reject(new Error('服务退出 ' + code)); });
  });
}
async function waitSaved(page) { await page.waitForFunction(() => document.querySelector('#save-state').textContent.startsWith('已保存')); }
async function create(page, kind, label, value) {
  await page.getByRole('button', { name: kind, exact: true }).click();
  await page.locator('#create-dialog').getByLabel(label, { exact: true }).fill(value);
  await page.getByRole('button', { name: '创建', exact: true }).click();
  await waitSaved(page);
}
async function activate(page, name) {
  await page.waitForFunction(()=>!document.querySelector('#toggle-modules').disabled);
  if((name.startsWith('查看')&&/上下文|记忆状态/.test(name)||name==='编辑人物资料')&&!await page.locator('#right-panel').isVisible())await page.getByRole('button',{name:'切换上下文面板',exact:true}).click();
  const module=page.locator('#tabs').getByRole('button',{name,exact:true,includeHidden:true});
  if(await module.count()&&!await module.isVisible())await page.locator('#toggle-modules').click();
  await page.getByRole('button', { name, exact: true }).click();
}

(async () => {
  const url = await start();
  browser = await chromium.launch({ headless: true, ...(process.env.NOVEL_WRITER_BROWSER ? { executablePath: process.env.NOVEL_WRITER_BROWSER } : {}) });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto(url);
  await activate(page,'切换导航面板');
  await create(page, '＋ 创建小说', '小说名称', 'S1 虚构验收');
  await activate(page, '章节写作');
  await create(page, '＋ 新建章节', '章节标题', '第一章 雾港');
  const retained = '\n\n尚未保存的中文正文。  \n';
  await page.getByLabel('正文', { exact: true }).fill(retained);
  await activate(page, 'IDEA');
  await page.getByLabel('本章 IDEA', { exact: true }).fill('一封匿名信');
  await activate(page, '正文');
  assert.equal(await page.getByLabel('正文', { exact: true }).inputValue(), retained, '切标签必须保留正文草稿');
  await create(page, '＋ 新建章节', '章节标题', '第二章 旧灯塔');
  await page.getByLabel('正文', { exact: true }).fill('第二章未保存');
  await page.locator('#chapter-tree button[data-chapter]').filter({ hasText: '第一章 雾港' }).click();
  assert.equal(await page.getByLabel('正文', { exact: true }).inputValue(), retained);
  await page.keyboard.press('Control+s'); await waitSaved(page);
  await activate(page, 'IDEA');
  assert.equal(await page.getByLabel('本章 IDEA', { exact: true }).inputValue(), '一封匿名信');
  await page.keyboard.press('Control+s'); await waitSaved(page);
  await activate(page, '正文');
  await page.getByLabel('正文', { exact: true }).fill('已修改的新正文');
  await page.keyboard.press('Control+s'); await waitSaved(page);
  await activate(page,'查看历史上下文');
  await page.getByLabel('历史版本', { exact: true }).selectOption({ index: 1 });
  assert.match(await page.locator('#version-diff').textContent(), /尚未保存的中文正文/);
  assert.ok(await page.locator('#version-diff .diff-add').count());
  assert.ok(await page.locator('#version-diff .diff-remove').count());

  // 项目切换保留其它项目草稿；关闭标签必须能够拒绝丢弃。
  await page.getByLabel('正文', { exact: true }).fill('跨项目保留');
  await create(page, '＋ 创建小说', '小说名称', '第二本虚构小说');
  await page.locator('#project-list button').filter({ hasText: 'S1 虚构验收' }).click();
  await activate(page, '章节写作');
  await page.locator('#chapter-tree button[data-chapter]').filter({ hasText: '第一章 雾港' }).click();
  assert.equal(await page.getByLabel('正文', { exact: true }).inputValue(), '跨项目保留');
  page.once('dialog', dialog => dialog.dismiss());
  await page.locator('#document-tabs .document-tab.active button[data-close-tab]').click();
  assert.equal(await page.getByLabel('正文', { exact: true }).inputValue(), '跨项目保留');
  await page.keyboard.press('Control+s'); await waitSaved(page);

  // IME 合成期间 Ctrl+S 不提交，结束后正常保存。
  const beforeIME = await page.locator('#save-state').textContent();
  await page.getByLabel('正文', { exact: true }).fill('输入法中的文字');
  await page.getByLabel('正文', { exact: true }).dispatchEvent('compositionstart');
  await page.keyboard.press('Control+s');
  assert.match(await page.locator('#save-state').textContent(), /未保存/);
  await page.getByLabel('正文', { exact: true }).dispatchEvent('compositionend');
  await page.keyboard.press('Control+s'); await waitSaved(page);
  assert.notEqual(await page.locator('#save-state').textContent(), beforeIME);

  // 快捷保存后保留焦点和光标，查找只定位文本且不提交。
  await page.getByLabel('正文', { exact: true }).evaluate(editor=>{editor.focus();editor.setSelectionRange(2,2);});
  await page.keyboard.press('Control+s'); await waitSaved(page);
  assert.deepEqual(await page.getByLabel('正文', { exact: true }).evaluate(editor=>[editor===document.activeElement,editor.selectionStart]), [true,2]);
  await activate(page, '查找');
  await page.getByLabel('正文查找', { exact: true }).fill('文字');
  await activate(page,'下一个');
  assert.equal(await page.getByLabel('正文', {exact:true}).evaluate(editor=>editor.value.slice(editor.selectionStart,editor.selectionEnd)), '文字');
  await activate(page,'关闭查找');

  // 各类真实表单继续保存；右侧只读资料可以跳到中央编辑。
  await activate(page,'全书大纲');
  await page.getByLabel('核心主题',{exact:true}).fill('虚构主题');
  await page.getByLabel('全书主线',{exact:true}).fill('离开雾港');
  await page.keyboard.press('Control+s'); await waitSaved(page);
  await activate(page,'文风规则');
  await page.getByLabel('文风与写作规则',{exact:true}).fill('克制，具体。');
  await page.keyboard.press('Control+s'); await waitSaved(page);
  await activate(page,'世界观');
  assert.equal(await page.getByLabel('世界观与设定',{exact:true}).evaluate(editor=>editor===document.activeElement),true,'导航后焦点应进入实际编辑区');
  await page.getByLabel('世界观与设定',{exact:true}).fill('雾港旧灯塔');
  await page.keyboard.press('Control+s'); await waitSaved(page);
  await activate(page,'查看世界观上下文');
  assert.match(await page.locator('#context-content').textContent(),/雾港旧灯塔/);
  await activate(page,'人物设定');
  await create(page,'＋ 新建人物','人物姓名','虚构人物林舟');
  await page.getByLabel('性格',{exact:true}).fill('耐心');
  await page.keyboard.press('Control+s'); await waitSaved(page);
  await activate(page,'查看人物上下文');
  assert.match(await page.locator('#context-content').textContent(),/耐心/);
  await activate(page,'编辑人物资料');
  assert.equal(await page.locator('#content').getByLabel('人物姓名',{exact:true}).inputValue(),'虚构人物林舟');
  await activate(page,'章节写作');
  await activate(page,'章节细纲');
  await page.getByLabel('核心情节',{exact:true}).fill('前往灯塔');
  await page.keyboard.press('Control+s'); await waitSaved(page);
  await activate(page,'正文');
  await activate(page,'查看历史上下文');

  // 两窗口旧 revision 冲突、重读不自动覆盖、对照后明确重新绑定。
  const second = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await second.goto(url);
  await activate(second,'切换导航面板');
  await second.locator('#project-list button').filter({hasText:'S1 虚构验收'}).click();
  await activate(second, '章节写作');
  await second.getByLabel('正文', { exact: true }).fill('旧窗口的草稿');
  await page.getByLabel('正文', { exact: true }).fill('另一个窗口的新版本');
  await page.keyboard.press('Control+s'); await waitSaved(page);
  await second.keyboard.press('Control+s');
  await second.waitForFunction(() => document.querySelector('#notification').textContent.includes('已更新'));
  assert.equal(await second.getByLabel('正文', { exact: true }).inputValue(), '旧窗口的草稿');
  await activate(second, '重新读取');
  assert.equal(await second.getByLabel('正文', { exact: true }).inputValue(), '旧窗口的草稿');
  await second.locator('#draft-review').waitFor({ state: 'visible' });
  assert.match(await second.locator('#draft-review').textContent(), /另一个窗口的新版本/);
  second.once('dialog', dialog => dialog.accept());
  await activate(second, '保留草稿并绑定最新版本');
  await activate(second,'IDEA');
  await activate(second,'正文');
  assert.equal(await second.getByLabel('正文',{exact:true}).inputValue(),'旧窗口的草稿','明确保留后切标签也不能丢稿');
  await second.keyboard.press('Control+s'); await waitSaved(second);
  await second.close();
  await activate(page, '重新读取');

  // 正式章未授权不能保存；恢复也必须明确授权，并保留版本。
  await page.getByLabel('正文状态', { exact: true }).selectOption('confirmed');
  await page.keyboard.press('Control+s'); await waitSaved(page);
  await page.getByLabel('正文', { exact: true }).fill('未经授权的修改');
  await page.keyboard.press('Control+s');
  assert.match(await page.locator('#save-state').textContent(), /未保存/);
  await page.getByRole('checkbox').check();
  await page.keyboard.press('Control+s'); await waitSaved(page);
  const count = await page.getByLabel('历史版本', { exact: true }).locator('option').count();
  const id=(await (await page.request.get(url+'/api/projects')).json()).find(project=>project.title==='S1 虚构验收').id;
  const prior=(await (await page.request.get(url+'/api/projects/'+id)).json()).document;
  page.once('dialog', dialog => dialog.dismiss());
  await activate(page, '恢复此版为新草稿');
  assert.equal(await page.getByLabel('历史版本', { exact: true }).locator('option').count(), count);
  page.once('dialog', dialog => dialog.accept());
  await activate(page, '恢复此版为新草稿'); await waitSaved(page);
  assert.equal(await page.getByLabel('正文状态', { exact: true }).inputValue(), 'draft');
  assert.equal(await page.getByLabel('历史版本', { exact: true }).locator('option').count(), count + 1);
  const restored=(await (await page.request.get(url+'/api/projects/'+id)).json()).document;
  assert.deepEqual(restored.versions.slice(0,prior.versions.length),prior.versions,'原始版本必须完全不变');
  assert.deepEqual(restored.chapters.map(chapter=>[chapter.id,chapter.number]),prior.chapters.map(chapter=>[chapter.id,chapter.number]));

  // 失败保存与取消恢复不能丢未保存正文。
  await page.getByLabel('正文',{exact:true}).fill('失败后仍保留的草稿');
  await page.route(url+'/api/projects/*/actions',route=>route.fulfill({status:500,contentType:'application/json',body:JSON.stringify({error:'模拟写入失败'})}),{times:1});
  await page.keyboard.press('Control+s');
  await page.waitForFunction(()=>document.querySelector('#notification').textContent.includes('模拟写入失败'));
  assert.equal(await page.getByLabel('正文',{exact:true}).inputValue(),'失败后仍保留的草稿');
  page.once('dialog',dialog=>dialog.dismiss()); await activate(page,'恢复此版为新草稿');
  assert.equal(await page.getByLabel('正文',{exact:true}).inputValue(),'失败后仍保留的草稿');
  await page.keyboard.press('Control+s'); await waitSaved(page);

  // 命令、主题、面板尺寸和偏好不引起正文写入。
  const revision = await page.locator('#save-state').textContent();
  await page.keyboard.press('Control+k');
  await page.getByLabel('搜索命令', { exact: true }).fill('专注');
  await page.keyboard.press('Enter');
  assert.equal(await page.locator('#left-panel').isVisible(), false);
  await activate(page, '退出专注');
  const divider = page.locator('#left-resize');
  await divider.focus(); await page.keyboard.press('ArrowRight');
  const width = await divider.getAttribute('aria-valuenow');
  assert.equal(Number(width), 240);
  const right=await page.locator('#right-resize').boundingBox();
  await page.mouse.move(right.x+2,right.y+30);await page.mouse.down();
  await page.mouse.move(right.x-18,right.y+30);await page.mouse.up();
  assert.equal(Number(await page.locator('#right-resize').getAttribute('aria-valuenow')),320,'指针拖动应调整真实面板宽度');
  await activate(page, '切换明暗主题');
  assert.equal(await page.locator('html').getAttribute('data-theme'), 'light');
  assert.equal(await page.locator('#save-state').textContent(), revision);
  const stored = await page.evaluate(() => localStorage.getItem('novel-ui'));
  assert.doesNotMatch(stored, /草稿|窗口|正文/);
  // 有其它标签草稿时刷新必须提醒；拒绝后草稿仍可切回。
  const cancelledUnload=new Promise(resolve=>page.once('dialog',async dialog=>{assert.equal(dialog.type(),'beforeunload');await dialog.dismiss();resolve();}));
  await page.reload({timeout:2000}).catch(()=>{});
  await cancelledUnload;
  await activate(page,'章节写作');
  await page.locator('#chapter-tree button[data-chapter]').filter({hasText:'第二章 旧灯塔'}).click();
  assert.equal(await page.getByLabel('正文',{exact:true}).inputValue(),'第二章未保存');
  page.once('dialog',dialog=>dialog.accept());
  await activate(page,'保留草稿并绑定最新版本');
  await page.keyboard.press('Control+s'); await waitSaved(page);
  await page.reload();
  await page.locator('#chat-composer').waitFor({state:'visible'});
  assert.equal(await page.locator('html').getAttribute('data-theme'),'light');
  assert.equal(await page.locator('#left-resize').getAttribute('aria-valuenow'),width);
  await activate(page, '切换明暗主题');
  await activate(page,'章节写作');

  for (const [width, height] of [[1440,900],[1280,720],[1024,768],[390,844]]) {
    await page.setViewportSize({width,height});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true, `${width}横向溢出`);
    assert.ok(await page.getByLabel('正文', { exact: true }).isVisible());
    if (width === 390) {
      await activate(page, '切换导航面板');
      await page.locator('#chapter-tree button[data-chapter]').first().click();
      assert.equal(await page.locator('#left-panel').isVisible(), false, '选择章节后关闭抽屉');
      await activate(page, '切换上下文面板');
      await activate(page, '关闭上下文');
      assert.equal(await page.locator('#toggle-right').evaluate(el => el === document.activeElement), true);
      await activate(page,'切换上下文面板');
      await page.keyboard.press('Tab');
      assert.equal(await page.locator('#right-panel').evaluate(el=>el.contains(document.activeElement)),true);
      await page.keyboard.press('Escape');
      assert.equal(await page.locator('#toggle-right').evaluate(el=>el===document.activeElement),true);
    }
    if (process.env.NOVEL_WRITER_ARTIFACTS) await page.screenshot({ path: path.join(process.env.NOVEL_WRITER_ARTIFACTS, `s1-${width}.png`) });
  }
  await page.setViewportSize({width:1440,height:900});
  await activate(page,'查看记忆状态');
  assert.match(await page.locator('#context-content').textContent(),/尚未实现/);
  await activate(page,'活动 / 控制台');
  await activate(page,'智能创作控制台');
  assert.match(await page.locator('#console-scope').textContent(),/S1 虚构验收/);
  assert.equal(await page.locator('#console-shell button:disabled').count(),3);
  assert.match(await page.locator('#activity-log').textContent(),/书架读取完成/,'刷新后的活动区应记录本窗口真实读取');
  await activate(page,'关闭任务区');
  await activate(page,'查看历史上下文');
  await activate(page,'切换明暗主题');
  if(process.env.NOVEL_WRITER_ARTIFACTS) await page.screenshot({path:path.join(process.env.NOVEL_WRITER_ARTIFACTS,'s1-dark.png')});
  assert.deepEqual(errors, []);
  console.log('S1 工作台验收通过：草稿/多标签/跨项目/历史差异/冲突比较/正式章授权/IME/命令/主题/面板/四尺寸。');
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close();
  if (server && server.exitCode === null) await new Promise(resolve => {server.once('exit',resolve);server.kill();});
  assert.ok(temporary.startsWith(path.join(os.tmpdir(), 'novel-writer-s1-')));
  fs.rmSync(temporary, {recursive:true,force:true});
});
