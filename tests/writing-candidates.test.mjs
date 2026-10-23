import {test} from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {prepareWritingCandidates,renderCandidateCount} from '../src/novel_writer/ui/static/writing_candidates.js';
import {renderComparison} from '../src/novel_writer/ui/static/comparison_views.js';
import {renderSceneExpansionPrepare} from '../src/novel_writer/ui/static/scene_expansion.js';
import {renderChapterPlanningPrepare} from '../src/novel_writer/ui/static/chapter_planning.js';
import {renderChapterWritingPrepare} from '../src/novel_writer/ui/static/chapter_writing.js';

test('multiple candidates freeze the same source with independent identities, no execute call',async t=>{
 const original=globalThis.fetch;t.after(()=>globalThis.fetch=original);const calls=[];
 globalThis.fetch=async(path,options)=>{const body=options.body?JSON.parse(options.body):null;calls.push({path,body});return {ok:true,json:async()=>path.endsWith('/prepare')?{task:{id:'task-'+body.operation_id},revision:3}:path.endsWith('/comparisons')?{experiment_id:body.experiment_id}:{revision:7}};};
 const payload={operation_id:randomUUID(),source_options:{selection_start:1,selection_end:5},source_sha256:'frozen-123',model_options:{max_tokens:500}};
 const result=await prepareWritingCandidates('fiction-project','scene_expansion','/api/projects/fiction-project/scene-expansion',payload,3);
 const prepares=calls.filter(v=>v.path.endsWith('/prepare'));assert.equal(prepares.length,3);assert.equal(new Set(prepares.map(v=>v.body.operation_id)).size,3);
 for(const v of prepares){assert.deepEqual(v.body.source_options,payload.source_options);assert.equal(v.body.source_sha256,payload.source_sha256);}
 assert.equal(calls.filter(v=>v.path.endsWith('/comparisons')).length,1);assert.ok(result.experiment_id);assert.ok(calls.every(v=>!v.path.includes('/execute')));
});
test('task-bound rules cannot create a partial multi-candidate group',async t=>{
 const original=globalThis.fetch;t.after(()=>globalThis.fetch=original);let calls=0;
 globalThis.fetch=async()=>{calls++;throw Error('must reject before preparation');};
 const identity=randomUUID();
 for(const options of [{rule_task_id:identity},{source_options:{rule_task_id:identity}},{context_options:{rule_task_id:identity}},{source_options:{context_options:{rule_task_id:identity}}}]){
  await assert.rejects(prepareWritingCandidates('fiction','chapter_planning','/api/projects/fiction/chapter-planning',{operation_id:identity,...options},2),/单任务规则绑定/);
 }
 assert.equal(calls,0);
});

test('a single candidate preserves the nested chapter-writing task binding and exact payload',async t=>{
 const original=globalThis.fetch;t.after(()=>globalThis.fetch=original);const calls=[];
 globalThis.fetch=async(path,options)=>{calls.push({path,body:JSON.parse(options.body)});return {ok:true,json:async()=>({task:{id:'single'}})};};
 const payload={request_id:randomUUID(),source_options:{context_options:{rule_task_id:randomUUID()}},source_sha256:'fiction-source'};
 const result=await prepareWritingCandidates('fiction','chapter_writing','/api/projects/fiction/chapter-writing',payload,1);
 assert.deepEqual(calls,[{path:'/api/projects/fiction/chapter-writing/prepare',body:payload}]);assert.equal(result.task.id,'single');
});

test('lost group response retries the original identities and original revision only on user action',async t=>{
 const original=globalThis.fetch;t.after(()=>globalThis.fetch=original);const requests=[];let revision=5;
 globalThis.fetch=async(path,options)=>{const body=options.body?JSON.parse(options.body):null;if(path.endsWith('/comparisons')){requests.push(body);if(requests.length===1){revision++;throw Error('fiction lost reply');}}return {ok:true,json:async()=>path.endsWith('/prepare')?{task:{id:'task-'+body.request_id}}:path.endsWith('/comparisons')?{experiment_id:body.experiment_id}:{revision}};};
 const payload={request_id:randomUUID(),source_sha256:'unchanged'};const args=['fiction','chapter_writing','/api/projects/fiction/chapter-writing',payload,2];
 await assert.rejects(prepareWritingCandidates(...args),/lost reply/);assert.equal(requests.length,1);await prepareWritingCandidates(...args);assert.deepEqual(requests[1],requests[0]);
});
test('all three prepare pages show explicit candidate count without issuing requests',t=>{
 const originalWindow=globalThis.window,originalFetch=globalThis.fetch;let calls=0;globalThis.window={};globalThis.fetch=()=>{calls++;throw Error('render must not send');};t.after(()=>{globalThis.window=originalWindow;globalThis.fetch=originalFetch;});
 const workspace={document:{project:{id:'fiction'},chapters:[{id:'chapter',title:'虚构',content:''}],chapter_outlines:[],characters:[{id:'person',name:'虚构人物'}]},ideas:{},creation_presets:[],creation_preset_choices:[]};
 const caps={real_model_enabled:true,connections:[],providers:[]};
 assert.match(renderSceneExpansionPrepare(workspace,'chapter',null,caps),/expansion-candidates/);
 assert.match(renderChapterPlanningPrepare(workspace,'chapter','brainstorm',caps),/planning-candidates/);
 assert.match(renderChapterWritingPrepare(workspace,'chapter','draft',caps),/writing-candidates/);
 assert.equal((renderCandidateCount('fiction','6').match(/<option /g)||[]).length,6);assert.match(renderCandidateCount('fiction','6'),/value="6" selected/);
 assert.equal(calls,0);
});
test('six-side reveal requires all scores and winner only opens the original workflow',()=>{
 const listing={experiments:[{id:'e',title:'六候选'}]},candidates=[...'ABCDEF'].map(side=>({side,status:'succeeded',text:'虚构 <script>',usage:{total_tokens:null},elapsed_seconds:0}));
 const blind={experiment_id:'e',title:'六候选',trial_kind:'writing_candidates',ready:true,revealed:false,candidates,scores:[...'ABCDE'].map(side=>({side,outcome:'scored',rating:3}))};
 assert.match(renderComparison(listing,blind,{}, {},[]),/id="reveal-comparison" disabled/);
 blind.scores.push({side:'F',outcome:'scored',rating:3});assert.doesNotMatch(renderComparison(listing,blind,{}, {},[]),/id="reveal-comparison" disabled/);
 blind.revealed=true;blind.identities=[...'ABCDEF'].map(side=>({side,profile:{connection_id:'fiction',model_id:'fiction-model'}}));const html=renderComparison(listing,blind,{}, {},[]);
 assert.equal((html.match(/data-choice-action="open_candidate"/g)||[]).length,6);assert.doesNotMatch(html,/data-choice-action="save_preset"/);assert.doesNotMatch(html,/<script>/);assert.match(html,/&lt;script&gt;/);
});
test('interrupted preparation remains cancellable and cannot be executed by reopening',()=>{
 const listing={experiments:[{id:'e',title:'重开'}]},blind={experiment_id:'e',title:'重开',trial_kind:'writing_candidates',ready:false};
 const setup={configurations:[{configuration_id:'cfg',configuration_label:'配置1',profile:{},request_body:'虚构',submitted:true,can_cancel:true}],can_submit:true};
 const html=renderComparison(listing,blind,setup,{real_model_enabled:true},[]);
 assert.match(html,/data-comparison-execute="cfg" disabled/);assert.match(html,/data-comparison-cancel="cfg" >/);
});
