'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {open} = require('./electron-local-harness.cjs');

const auditRoot = process.env.NOVEL_WRITER_ARTIFACTS;
assert.ok(auditRoot, 'NOVEL_WRITER_ARTIFACTS is required');
const sourceReport = JSON.parse(fs.readFileSync(path.join(auditRoot, 'scale', 'report.json'), 'utf8'));
const output = path.join(auditRoot, 'scale-ui');
fs.mkdirSync(output, {recursive: true});
const report = {
  status: 'running', checks: [], errors: [], external: [], providerCalls: 0,
  project: sourceReport.project_id, database: sourceReport.database,
  samples_ms: [], timings_ms: {},
};

(async () => {
  let ui;
  try {
    assert.equal(sourceReport.status, 'passed');
    const executable = process.env.NOVEL_WRITER_EXE;
    assert.ok(executable, 'NOVEL_WRITER_EXE is required');
    const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'novel-lead-million-character-ui-'));
    const started = performance.now();
    ui = await open({executable, profile, database: sourceReport.database, report});
    await ui.nav('writing');
    await ui.wait("document.querySelectorAll('#chapter-tree button[data-chapter]').length === 200", 60000);
    report.timings_ms.startup_to_loaded_chapters = Math.round(performance.now() - started);
    const chapterInfo = await ui.evaluate(`(async () => {
      const state = await (await fetch('/api/projects/${sourceReport.project_id}')).json();
      window.__leadScaleChapters = state.document.chapters.slice().sort((left, right) => left.number - right.number);
      return {count: state.document.chapters.length, characters: state.document.chapters.reduce((sum, chapter) => sum + chapter.content.length, 0)};
    })()`);
    assert.equal(chapterInfo.count, 200);
    assert.ok(chapterInfo.characters >= 1000000);
    report.checks.push('extracted desktop loads all 200 chapters and more than one million saved characters');
    for (let sample = 0; sample < 30; sample++) {
      const result = await ui.evaluate(`(async () => {
        const chapter = window.__leadScaleChapters[${(sample * 47 + 9) % 200}];
        const button = document.querySelector('#chapter-tree button[data-chapter="' + chapter.id + '"]');
        const started = performance.now();
        button.click();
        while (document.querySelector('#edit-content')?.value !== chapter.content) {
          if (performance.now() - started > 15000) throw new Error('chapter switch did not show the exact saved body');
          await new Promise(requestAnimationFrame);
        }
        await new Promise(requestAnimationFrame);
        await new Promise(requestAnimationFrame);
        return {elapsed: performance.now() - started, chapter: chapter.number};
      })()`);
      report.samples_ms.push({chapter: result.chapter, elapsed: Math.round(result.elapsed * 100) / 100});
    }
    const sortedSamples = report.samples_ms.map(sample => sample.elapsed).sort((left, right) => left - right);
    report.navigation_median_ms = sortedSamples[14];
    report.navigation_p95_ms = sortedSamples[28];
    report.navigation_max_ms = sortedSamples[29];
    report.checks.push('30 chapter switches display the exact persisted bodies before measurement ends');
    const original = await ui.evaluate("document.querySelector('#edit-content').value");
    const edited = original + '\n百万字桌面保存与重开验证。';
    await ui.fill('#edit-content', edited);
    const saveStarted = performance.now();
    await ui.click('[form="active-editor"]');
    await ui.idle();
    await ui.wait("document.querySelector('#save-state').textContent.includes('已保存')", 60000);
    report.timings_ms.desktop_save = Math.round(performance.now() - saveStarted);
    const selectedId = await ui.evaluate("document.querySelector('#chapter-select').value");
    await ui.close();
    ui = await open({executable, profile, database: sourceReport.database, report});
    const state = await ui.state(sourceReport.project_id);
    assert.equal(state.document.chapters.find(chapter => chapter.id === selectedId).content, edited);
    report.checks.push('typing and saving in the million-character desktop project survive a process restart exactly');
    await ui.nav('writing');
    const screenshot = await ui.send('Page.captureScreenshot', {format: 'png'});
    fs.writeFileSync(path.join(output, 'million-character-desktop.png'), Buffer.from(screenshot.data, 'base64'));
    assert.deepEqual(report.errors, []);
    assert.deepEqual(report.external, []);
    report.status = 'passed';
  } catch (error) {
    report.status = 'failed';
    report.error = String(error.stack || error);
    throw error;
  } finally {
    if (ui) await ui.close();
    fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
  }
})().then(() => process.stdout.write(JSON.stringify(report) + '\n')).catch(error => {
  process.stderr.write(String(error.stack || error) + '\n');
  process.exitCode = 1;
});
