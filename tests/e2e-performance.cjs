// S1 loaded-navigation acceptance. All data are fictional and outside the repo.
// Set NOVEL_WRITER_ARTIFACTS to an external directory. Runtime overrides:
// NOVEL_WRITER_PYTHON, NOVEL_WRITER_BROWSER, and NODE_PATH for existing Playwright.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { spawn, spawnSync } = require('node:child_process');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
const python = process.env.NOVEL_WRITER_PYTHON || 'python';
const artifacts = path.resolve(process.env.NOVEL_WRITER_ARTIFACTS || path.join(os.tmpdir(), `novel-writer-s1-results-${Date.now()}`));
const artifactRelative = path.relative(root, artifacts);
assert.ok(artifactRelative && (artifactRelative === '..' || artifactRelative.startsWith('..' + path.sep) || path.isAbsolute(artifactRelative)), '验收产物必须位于仓库外');
fs.mkdirSync(artifacts, { recursive: true });
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'novel-writer-s1-performance-'));
const database = path.join(temporary, 'fictional.sqlite3');
const reportPath = path.join(artifacts, 's1-performance.json');
const report = {
  started_at: new Date().toISOString(), status: 'running',
  environment: {
    os: `${os.type()} ${os.release()} ${os.arch()}`,
    cpu: os.cpus()[0]?.model || 'unknown', logical_cpus: os.cpus().length,
    memory_gib: Number((os.totalmem() / 1024 ** 3).toFixed(2)),
    node: process.version, playwright: require('playwright/package.json').version,
    headless: true, browser_executable: process.env.NOVEL_WRITER_BROWSER || 'Playwright default',
  },
  methodology: {
    scope: '已加载的 100 章项目；每章约 2000 汉字和 1 个章节快照',
    start: '浏览器内 performance.now()，紧接章节树按钮 DOM click() 之前',
    end: '对应正文完整匹配后再经过两次 requestAnimationFrame，记录可绘制的呈现时间',
    exclusion: '项目加载、HTTP、数据库读取、Playwright 操作等待均不计入；切章期间断言无 HTTP 请求',
    warmup_samples: 5, measured_samples: 30, target_ms: 300,
    limitation: '本机 Edge 无头浏览器测量；不是操作系统输入法实测，也不是 S2 大规模存储基准',
  },
  warmup_ms: [], samples: [], layouts: [], checks: {},
};
let server, browser, page;

function writeReport() { fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + '\n', 'utf8'); }
function percentile(values, fraction) {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.ceil(sorted.length * fraction) - 1];
}
async function startServer() {
  server = spawn(python, ['-B', '-X', 'utf8', '-u', '-c',
    "import sys; sys.path.insert(0,'src'); from novel_writer.ui.server import create_server; s=create_server(sys.argv[1],port=0); print('http://127.0.0.1:'+str(s.server_address[1]),flush=True); s.serve_forever()", database],
    { cwd: root, windowsHide: true, env: { ...process.env, DEEPSEEK_API_KEY: 'fictional-test-key', GEMINI_API_KEY: 'fictional-test-key' } });
  return new Promise((resolve, reject) => {
    let output = '';
    const timeout = setTimeout(() => reject(new Error('临时服务启动超时')), 15000);
    server.once('error', error => { clearTimeout(timeout); reject(error); });
    server.once('exit', code => { clearTimeout(timeout); reject(new Error(`临时服务退出 ${code}`)); });
    server.stderr.on('data', chunk => process.stderr.write(chunk));
    server.stdout.on('data', chunk => {
      output += chunk;
      const match = output.match(/http:\/\/127[.]0[.]0[.]1:[0-9]+/);
      if (match) { clearTimeout(timeout); resolve(match[0]); }
    });
  });
}
async function activate(name) {
  await page.waitForFunction(()=>!document.querySelector('#toggle-modules').disabled);
  const module=page.locator('#tabs').getByRole('button',{name,exact:true,includeHidden:true});
  if(await module.count()&&!await module.isVisible())await page.locator('#toggle-modules').click();
  await page.getByRole('button', { name, exact: true }).click();
}
async function treeIds() { return page.locator('#chapter-tree button[data-chapter]').evaluateAll(elements => elements.map(element => element.dataset.chapter)); }
async function openNavigation() {
  if (!await page.locator('#left-panel').isVisible()) await activate('切换导航面板');
}
async function selectChapter(chapter) {
  await openNavigation();
  await page.locator(`#chapter-tree button[data-chapter="${chapter.id}"]`).click();
  await page.waitForFunction(expected => document.querySelector('#edit-content')?.value === expected, chapter.content);
}
async function measuredSwitch(chapter) {
  return page.evaluate(async ({ id, content }) => {
    const button = document.querySelector(`#chapter-tree button[data-chapter="${id}"]`);
    if (!button) throw new Error('缺少章节树按钮');
    const start = performance.now();
    button.click();
    while (document.querySelector('#edit-content')?.value !== content) {
      if (performance.now() - start > 3000) throw new Error('切章正文未出现');
      await new Promise(requestAnimationFrame);
    }
    await new Promise(requestAnimationFrame);
    await new Promise(requestAnimationFrame);
    return performance.now() - start;
  }, chapter);
}
async function visibleGeometry(locator, label, minimumHeight = 1) {
  await locator.scrollIntoViewIfNeeded();
  const geometry = await locator.evaluate(element => {
    const rect = element.getBoundingClientRect();
    const points = [
      [rect.left + rect.width / 2, rect.top + rect.height / 2],
      [rect.left + 8, rect.top + 8], [rect.right - 8, rect.top + 8],
      [rect.left + 8, rect.bottom - 8], [rect.right - 8, rect.bottom - 8],
    ];
    const uncoveredPoints = points.filter(([x, y]) => {
      const hit = document.elementFromPoint(x, y);
      return !!hit && (element === hit || element.contains(hit));
    }).length;
    return {
      x: rect.x, y: rect.y, width: rect.width, height: rect.height,
      withinViewport: rect.left >= -1 && rect.top >= -1 && rect.right <= innerWidth + 1 && rect.bottom <= innerHeight + 1,
      unobscured: uncoveredPoints === points.length,
    };
  });
  assert.ok(geometry.width > 20 && geometry.height >= minimumHeight, `${label}可用面积不足`);
  assert.ok(geometry.withinViewport, `${label}被视口裁切：${JSON.stringify(geometry)}`);
  assert.ok(geometry.unobscured, `${label}被其他面板遮挡`);
  return geometry;
}
async function activeTabGeometry(width, assertVisible = true) {
  const geometry = await page.evaluate(async () => {
    await new Promise(requestAnimationFrame);
    const strip = document.querySelector('#document-tabs').getBoundingClientRect();
    const tab = document.querySelector('#document-tabs .document-tab.active').getBoundingClientRect();
    return {
      x: tab.x, right: tab.right, strip_left: strip.left, strip_right: strip.right,
      visible: tab.left >= strip.left - 1 && tab.right <= strip.right + 1,
    };
  });
  if (assertVisible) assert.ok(geometry.visible, `${width}px 当前章节标签未滚动到标签栏可视范围：${JSON.stringify(geometry)}`);
  return geometry;
}

(async () => {
  const fixture = spawnSync(python, ['-B', '-X', 'utf8', path.join(__dirname, 'fixtures', 's1-performance.py'), database], { cwd: root, encoding: 'utf8', windowsHide: true, maxBuffer: 1024 * 1024 });
  if (fixture.error) throw fixture.error;
  assert.equal(fixture.status, 0, fixture.stderr || '夹具创建失败');
  report.fixture = JSON.parse(fixture.stdout);
  report.environment.python = report.fixture.python;
  report.environment.sqlite = report.fixture.sqlite;
  const url = await startServer();
  browser = await chromium.launch({ headless: true, ...(process.env.NOVEL_WRITER_BROWSER ? { executablePath: process.env.NOVEL_WRITER_BROWSER } : {}) });
  report.environment.browser_version = browser.version();
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const externalRequests = [];
  await context.route('**/*', route => {
    if (new URL(route.request().url()).origin === url) return route.continue();
    externalRequests.push(route.request().url());
    return route.abort();
  });
  page = await context.newPage();
  page.setDefaultTimeout(15000);
  const errors = [], requests = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => requests.push({ method: request.method(), path: new URL(request.url()).pathname }));
  await page.goto(url);
  await page.waitForFunction(()=>!document.querySelector('#new-project').disabled);
  await openNavigation();
  await page.locator(`#project-list button[data-project="${report.fixture.project_id}"]`).click();
  await activate('章节写作');
  await page.waitForFunction(() => document.querySelectorAll('#chapter-tree button[data-chapter]').length === 100);
  const initial = await (await page.request.get(`${url}/api/projects/${report.fixture.project_id}`)).json();
  const chapters = initial.document.chapters;
  assert.equal(chapters.length, 100);
  assert.deepEqual(await treeIds(), chapters.map(chapter => chapter.id), '章节树必须保留章节顺序及 ID');
  for (const chapter of chapters) {
    assert.equal(createHash('sha256').update(chapter.content).digest('hex'), report.fixture.chapters.find(item => item.id === chapter.id).content_sha256);
  }

  // Title-only client filtering, including identical titles tied to distinct IDs.
  const beforeFiltering = requests.length;
  await page.locator('#chapter-filter').fill('定位样本');
  assert.deepEqual(await treeIds(), [report.fixture.filter_chapter_id]);
  await selectChapter(chapters.find(chapter => chapter.id === report.fixture.filter_chapter_id));
  await page.locator('#chapter-filter').fill(report.fixture.duplicate_title);
  assert.deepEqual(await treeIds(), report.fixture.duplicate_chapter_ids);
  for (const id of report.fixture.duplicate_chapter_ids) await selectChapter(chapters.find(chapter => chapter.id === id));
  await page.locator('#chapter-filter').fill('标题中不存在的定位词');
  assert.deepEqual(await treeIds(), []);
  await page.locator('#chapter-filter').fill('');
  assert.deepEqual(await treeIds(), chapters.map(chapter => chapter.id));
  assert.deepEqual(requests.slice(beforeFiltering), [], '客户端标题筛选及定位不应发出 HTTP 请求');
  report.checks.title_filter_duplicate_titles_stable_ids_order = true;
  report.checks.http_requests_during_filtering = 0;

  // Timing occurs entirely in the renderer after the project was loaded.
  await selectChapter(chapters[0]);
  const beforeMeasurements = requests.length;
  for (let index = 0; index < 35; index++) {
    const chapter = chapters[(index * 37 + 19) % chapters.length];
    const duration = await measuredSwitch(chapter);
    if (index < 5) report.warmup_ms.push(duration);
    else report.samples.push({ sample: index - 4, chapter_number: chapter.number, duration_ms: duration });
  }
  const measurementRequests = requests.slice(beforeMeasurements);
  assert.deepEqual(measurementRequests, [], '已加载切章测量期间不应发出 HTTP 请求');
  const durations = report.samples.map(sample => sample.duration_ms);
  report.timing = { count: durations.length, median_ms: percentile(durations, 0.5), p95_ms: percentile(durations, 0.95), maximum_ms: Math.max(...durations), http_requests_during_measurement: measurementRequests.length };
  writeReport();

  // Real pointer navigation and geometry with a long book and chapter title.
  const longChapter = chapters.find(chapter => chapter.id === report.fixture.long_title_chapter_id);
  await selectChapter(longChapter);
  for (const [width, height] of [[1440, 900], [1280, 720], [1024, 768], [390, 844]]) {
    await page.setViewportSize({ width, height });
    await openNavigation();
    await page.locator('#chapter-filter').fill('长标题样本');
    assert.deepEqual(await treeIds(), [longChapter.id]);
    await selectChapter(longChapter);
    if (width <= 760) assert.equal(await page.locator('#left-panel').isVisible(), false, '窄屏选择后应关闭导航抽屉');
    const selectedTab = await activeTabGeometry(width);
    const editor = page.getByLabel('正文', { exact: true });
    assert.equal(await editor.inputValue(), longChapter.content);
    const editorGeometry = await visibleGeometry(editor, `${width}px 正文`, 100);
    const save = page.getByRole('button', { name: '保存正文', exact: true });
    const saveGeometry = await visibleGeometry(save, `${width}px 保存按钮`);
    await save.click({ trial: true });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true, `${width}px 页面横向溢出`);
    const screenshot = path.join(artifacts, `s1-performance-${width}.png`);
    await page.screenshot({ path: screenshot });
    report.layouts.push({ width, height, editor: editorGeometry, save_button: saveGeometry, active_tab: selectedTab, screenshot, horizontal_overflow: false });
    await openNavigation();
    await page.locator('#chapter-filter').fill('');
    assert.deepEqual(await treeIds(), chapters.map(chapter => chapter.id));
    if (width <= 760) await activate('切换导航面板');
  }

  // User-resizable desktop panels must yield space when their saved maximum
  // widths would squeeze the actual body editor below the PRD's 560px target.
  await page.setViewportSize({ width: 1440, height: 900 });
  await openNavigation();
  if (!await page.locator('#right-panel').isVisible()) await activate('切换上下文面板');
  // With expanded module navigation, increasing left first already hides the
  // right separator. Resize the visible right panel first, then the left one.
  await page.locator('#right-resize').focus();
  await page.keyboard.press('End');
  assert.equal(await page.locator('#right-resize').getAttribute('aria-valuenow'), '380');
  await page.locator('#left-resize').focus();
  await page.keyboard.press('End');
  assert.equal(await page.locator('#left-resize').getAttribute('aria-valuenow'), '340');
  const maximumPanelsEditor = await visibleGeometry(page.getByLabel('正文', { exact: true }), '最大面板宽度下的正文', 100);
  assert.ok(maximumPanelsEditor.width >= 560, `最大面板宽度下正文仅 ${maximumPanelsEditor.width}px，要求至少 560px`);
  assert.equal(await page.locator('#right-panel').isVisible(), false, '空间不足时应先自动收起资料栏');
  assert.equal(await page.locator('#left-panel').isVisible(), true, '1440px 应优先保留章节导航');
  report.maximum_panel_widths = { viewport: { width: 1440, height: 900 }, left: 340, right: 380, editor: maximumPanelsEditor, right_panel_auto_collapsed: true };
  const resizedTab = await activeTabGeometry(1440, false);
  const selectedTreeItem = await page.evaluate(id => {
    const tree = document.querySelector('#chapter-tree').getBoundingClientRect();
    const chapter = document.querySelector(`#chapter-tree button[data-chapter="${id}"]`).getBoundingClientRect();
    return {
      top: chapter.top, bottom: chapter.bottom, tree_top: tree.top, tree_bottom: tree.bottom,
      visible: chapter.top >= tree.top - 1 && chapter.bottom <= tree.bottom + 1,
    };
  }, longChapter.id);
  report.selection_after_layout = { active_tab: resizedTab, active_tree_item: selectedTreeItem };
  await page.screenshot({ path: path.join(artifacts, 's1-performance-max-panels.png') });
  writeReport();
  assert.deepEqual([resizedTab.visible, selectedTreeItem.visible], [true, true], `窗口与面板尺寸变化后，当前标签和树选中项仍应可见：${JSON.stringify(report.selection_after_layout)}`);

  // Fake keys are set only on the temporary server. Every local model action
  // must still reject without changing the workspace or reaching a provider.
  const settings = await (await page.request.get(`${url}/api/settings`)).json();
  assert.equal(settings.model_calls_enabled, false);
  assert.equal(settings.providers.deepseek.key_configured, true);
  assert.equal(settings.providers.gemini.key_configured, true);
  const session = await (await page.request.get(`${url}/api/session`)).json();
  report.disabled_model_actions = [];
  for (const action of ['generate_body', 'deepseek_review', 'gemini_revision', 'auto_update_outline']) {
    const response = await page.request.post(`${url}/api/projects/${report.fixture.project_id}/actions`, {
      headers: { 'X-Novel-Token': session.token, Origin: url },
      data: { action, fields: {}, expected_revision: initial.revision },
    });
    const result = await response.json();
    assert.equal(response.status(), 422);
    assert.match(result.error, /未启用.*离线.*不调用真实模型/);
    report.disabled_model_actions.push({ action, status: response.status(), error: result.error });
  }
  const finalState = await (await page.request.get(`${url}/api/projects/${report.fixture.project_id}`)).json();
  assert.deepEqual(finalState, initial, '导航、筛选、布局和禁用动作不能改正文、版本或顺序');
  assert.deepEqual(externalRequests, [], '浏览器不得尝试外部请求');
  assert.deepEqual(errors, [], '页面 JavaScript 错误');
  report.checks.no_data_or_version_changes = true;
  report.checks.model_actions_disabled_with_fictional_keys = true;
  report.checks.page_errors = errors;
  report.checks.external_browser_requests = externalRequests;
  assert.ok(report.timing.maximum_ms < 300, `切章最大耗时 ${report.timing.maximum_ms.toFixed(2)}ms，未达到 <300ms 目标；原始数据已记录`);
  report.status = 'passed';
  console.log(`S1 100 章验收通过：30 次切章中位数 ${report.timing.median_ms.toFixed(2)}ms，P95 ${report.timing.p95_ms.toFixed(2)}ms，最大 ${report.timing.maximum_ms.toFixed(2)}ms；四尺寸长标题与离线禁用通过。报告：${reportPath}`);
})().catch(async error => {
  report.status = 'failed';
  report.error = error.stack || String(error);
  if (page && !page.isClosed()) await page.screenshot({ path: path.join(artifacts, 's1-performance-failure.png') }).catch(() => {});
  console.error(error);
  process.exitCode = 1;
}).finally(async () => {
  report.finished_at = new Date().toISOString();
  writeReport();
  if (browser) await browser.close();
  if (server && server.exitCode === null) await new Promise(resolve => { server.once('exit', resolve); server.kill(); });
  const resolved = path.resolve(temporary);
  const expectedParent = path.resolve(os.tmpdir());
  assert.equal(path.dirname(resolved), expectedParent, '临时目录父路径异常，停止清理');
  assert.ok(path.basename(resolved).startsWith('novel-writer-s1-performance-'), '临时目录名异常，停止清理');
  fs.rmSync(resolved, { recursive: true, force: true });
});
