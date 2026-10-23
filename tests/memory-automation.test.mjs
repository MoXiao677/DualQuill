import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const path=new URL('../src/novel_writer/ui/static/memory_automation.js',import.meta.url);
const module=await import('data:text/javascript;base64,'+Buffer.from(await readFile(path,'utf8')).toString('base64'));
const escape=value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const workspace={document:{project:{id:'fiction-book'},chapters:[{id:'c1',number:1,title:'<script>虚构</script>'}]}};
test('defaults and copied policy remain disabled',()=>{
  assert.deepEqual(module.memoryAutomationPolicy(workspace),{track_updates:false,auto_select:false});
  const copied={...workspace,memory_automation_events:[{kind:'policy',authorization_project_id:'other-book',policy:{track_updates:true,auto_select:true}}]};
  assert.equal(module.memoryAutomationPolicy(copied).auto_select,false);
});
test('policy and queue render author controls with escaped chapter labels',()=>{
  const state={...workspace,memory_automation_events:[{kind:'policy',authorization_project_id:'fiction-book',policy:{track_updates:true,auto_select:true}},{id:'job',kind:'impact',revision:3,chapter_ids:['c1'],memory_ids:['m1'],rollup_ids:[]},{kind:'cancel',job_id:'job'}]};
  const html=module.renderMemoryAutomation(state,escape);
  assert.match(html,/memory-auto-select[^>]*checked/);assert.match(html,/data-memory-queue="reopen"/);assert.match(html,/开关不授权外发或自动付费/);assert.ok(!html.includes('<script>'));
});
test('context and writing entry points expose the automatic selection option',async()=>{
  for(const name of ['views.js','chapter_writing.js','model_tasks.js']){
    const source=await readFile(new URL('../src/novel_writer/ui/static/'+name,import.meta.url),'utf8');
    assert.ok(source.includes('include_automatic_memories'),name);
    assert.ok(source.includes('memoryAutomationPolicy'),name);
  }
});
test('resolved queue items can be reopened without pretending to accept a memory',()=>{
  const state={...workspace,memory_automation_events:[{id:'job',kind:'impact',revision:3,chapter_ids:[],memory_ids:['m1'],rollup_ids:[]},{kind:'resolve',job_id:'job'}]};
  const html=module.renderMemoryAutomation(state,escape);
  assert.match(html,/已核对/);assert.match(html,/data-memory-queue="reopen"/);assert.ok(!html.includes('data-memory-queue="resolve"'));
});
