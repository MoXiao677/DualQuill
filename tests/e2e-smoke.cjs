// 可选浏览器验收：使用临时数据库，不接触作者实际小说。需要开发者安装 Playwright。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'novel-writer-e2e-'));
const database = path.join(temporary, 'test.sqlite3');
const python = process.env.NOVEL_WRITER_PYTHON || 'python';
const oldText = '\n\n旧版正文。\n\n中文换行保留。';
let server, browser;

async function startServer() {
  const source = "import sys; sys.path.insert(0, 'src'); from novel_writer.ui.server import create_server; s=create_server(sys.argv[1], port=0, offline=True); print('http://127.0.0.1:'+str(s.server_address[1]), flush=True); s.serve_forever()";
  server = spawn(python, ['-X', 'utf8', '-u', '-c', source, database], { cwd: root, windowsHide: true });
  return new Promise((resolve, reject) => {
    let output = '';
    const timeout = setTimeout(() => reject(new Error('本地服务未启动')), 10000);
    server.stdout.on('data', chunk => {
      output += chunk.toString();
      const match = output.match(new RegExp('http://127[.]0[.]0[.]1:[0-9]+'));
      if (match) { clearTimeout(timeout); resolve(match[0]); }
    });
    server.stderr.on('data', chunk => process.stderr.write(chunk));
    server.once('exit', code => { clearTimeout(timeout); reject(new Error('服务退出：' + code)); });
  });
}

async function stopServer() {
  if (!server || server.exitCode !== null) return;
  await new Promise(resolve => { server.once('exit', resolve); server.kill(); });
}

async function saved(page) {
  await page.waitForFunction(() => document.querySelector('#save-state').textContent.startsWith('已保存'));
}
async function modulePage(page,name) {
  const button=page.locator('#tabs').getByRole('button',{name,exact:true,includeHidden:true});
  if(!await button.isVisible())await page.locator('#toggle-modules').click();
  await button.click();
}

(async () => {
  let url = await startServer();
  browser = await chromium.launch({ headless: true, ...(process.env.NOVEL_WRITER_BROWSER ? { executablePath: process.env.NOVEL_WRITER_BROWSER } : {}) });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(url);
  await page.getByRole('button',{name:'切换导航面板',exact:true}).click();
  await page.getByRole('button', { name: '＋ 创建小说', exact: true }).click();
  await page.getByLabel('小说名称', { exact: true }).fill('浏览器验收小说');
  await page.getByRole('button', { name: '创建', exact: true }).click();
  await saved(page);
  await page.getByRole('button', { name: '章节写作', exact: true }).click();
  await page.route(url + '/api/projects', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: '模拟书架刷新失败' }) }), { times: 1 });
  await page.getByRole('button', { name: '＋ 新建章节', exact: true }).click();
  await page.getByLabel('章节标题', { exact: true }).fill('第一章 来信');
  await page.getByRole('button', { name: '创建', exact: true }).click();
  await saved(page);
  await page.waitForFunction(() => document.querySelector('#notification').textContent.includes('刷新'));
  assert.equal(await page.locator('#create-dialog').evaluate(dialog => dialog.open), false, '保存成功后的书架刷新失败不能让作者重复创建');
  const currentBooks = await (await page.request.get(url + '/api/projects')).json();
  const currentBook = await (await page.request.get(url + '/api/projects/' + currentBooks[0].id)).json();
  assert.equal(currentBook.document.chapters.length, 1);
  await page.getByLabel('正文', { exact: true }).fill(oldText);
  await page.getByRole('button', { name: '保存正文', exact: true }).click();
  await saved(page);
  assert.equal(await page.getByLabel('正文', { exact: true }).inputValue(), oldText, '保存重绘必须保留开头的空行');
  await page.reload();
  await modulePage(page,'章节写作');
  assert.equal(await page.getByLabel('正文', { exact: true }).inputValue(), oldText);
  await page.getByLabel('正文', { exact: true }).fill('新的正文。');
  await page.getByRole('button', { name: '保存正文', exact: true }).click();
  await saved(page);
  if(!await page.locator('#right-panel').isVisible()) await page.getByRole('button',{name:'切换上下文面板',exact:true}).click();
  await page.getByLabel('历史版本', { exact: true }).selectOption({ index: 1 });
  assert.match(await page.locator('#version-preview').textContent(), /旧版正文/);
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: '恢复此版为新草稿', exact: true }).click();
  await saved(page);
  assert.equal(await page.getByLabel('正文', { exact: true }).inputValue(), oldText);
  const historyCount = await page.getByLabel('历史版本', { exact: true }).locator('option').count();
  assert.equal(historyCount, 4);
  await stopServer();
  url = await startServer();
  await page.goto(url);
  await modulePage(page,'章节写作');
  assert.equal(await page.getByLabel('正文', { exact: true }).inputValue(), oldText);
  await page.getByRole('button', { name: '人物设定', exact: true }).click();
  await page.getByRole('button', { name: '＋ 新建人物', exact: true }).click();
  await page.getByLabel('人物姓名', { exact: true }).fill('林舟');
  await page.getByRole('button', { name: '创建', exact: true }).click();
  await saved(page);
  assert.equal(await page.locator('#content').getByLabel('人物姓名', { exact: true }).inputValue(), '林舟');
  await page.getByRole('button', { name: '世界观', exact: true }).click();
  await page.getByLabel('世界观与设定', { exact: true }).fill('雾港，旧灯塔。');
  await page.getByRole('button', { name: '保存世界观', exact: true }).click();
  await saved(page);
  await page.getByRole('button', { name: 'Skills', exact: true }).click();
  const original = '---\nname: 浏览器技能\ndescription: 原文保留测试\n---\n# 参考资料\n<script>window.untrustedSkillExecuted = true</script>\n';
  await page.locator('#skill-file').setInputFiles({ name: 'SKILL.md', mimeType: 'text/markdown', buffer: Buffer.from(original, 'utf8') });
  await page.getByRole('button', { name: '导入所选资料', exact: true }).click();
  await page.getByRole('button', { name: '浏览器技能', exact: true }).waitFor();
  assert.equal(await page.getByLabel('技能原文', { exact: true }).inputValue(), original);
  assert.equal(await page.evaluate(() => window.untrustedSkillExecuted), undefined);
  await page.reload();
  await modulePage(page,'Skills');
  assert.equal(await page.getByLabel('技能原文', { exact: true }).inputValue(), original);
  await page.getByRole('button', { name: '使用指南', exact: true }).click();
  await page.getByRole('heading', { name: '小说作者：第一次使用', exact: true }).waitFor();
  await page.getByRole('heading', { name: 'AI 助手：协作约定', exact: true }).waitFor();
  await page.getByRole('button', { name: '章节写作', exact: true }).click();
  if (process.env.NOVEL_WRITER_SCREENSHOT) await page.screenshot({ path: process.env.NOVEL_WRITER_SCREENSHOT, fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true, '窄屏出现页面横向溢出');
  assert.deepEqual(errors, [], '页面出现 JavaScript 错误');
  console.log('浏览器验收通过：创建小说、章节保存、刷新读取、版本恢复、服务重启、人物与世界观保存、Skills 导入与原文展示、使用指南、窄屏布局。');
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close();
  await stopServer();
  assert.ok(temporary.startsWith(path.join(os.tmpdir(), 'novel-writer-e2e-')), '临时目录路径异常，停止清理');
  fs.rmSync(temporary, { recursive: true, force: true });
});
