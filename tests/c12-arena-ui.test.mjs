import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';

const source=(await readFile(new URL('../src/novel_writer/ui/static/comparison_views.js',import.meta.url),'utf8'))
 .replace(/^import .*;\r?$/gm,'').replaceAll('export function ','function ').replaceAll('export const ','const ');
function ui(api=async()=>{throw Error('Unexpected API call');}){
 const context={api,crypto:webcrypto,TextEncoder,t:k=>k,h:v=>String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),renderSampling:id=>'<div data-sampling="'+id+'"></div>',captureSampling:()=>({}),samplingOptions:()=>({}),connectionChoices:()=>[['fake','虚构连接',true]],modelAdapterId:()=> 'configured-http-v2'};
 vm.createContext(context);vm.runInContext(source+'\nthis.ui={renderComparisonCreate,renderComparison,bindComparison};',context);return context.ui;
}
const workspace={document:{project:{id:'fiction-book'},characters:[{id:'fiction-person',name:'<虚构人物>'}]}};
function blind(revealed=false){return {experiment_id:'fiction-experiment',title:'虚构比较',revision:1,ready:true,revealed,task_kind:'audit_chapter',scores:[{side:'A',rating:4,outcome:'scored'},{side:'B',rating:4,outcome:'scored'}],candidates:['A','B','C'].map(side=>({side,status:'succeeded',text:'<虚构待核实意见>',usage:{prompt_tokens:17,completion_tokens:9,total_tokens:26},elapsed_seconds:.1})),...(revealed?{identities:['A','B','C'].map(side=>({side,profile:{connection_id:'fiction-connection',model_id:'fiction-model',temperature:.3,max_tokens:512},reported_model:'fiction-reported'}))}:{})};}
test('creator offers eight configs, three typed requests, explicit budgets and sourced optional prices',()=>{
 const html=ui().renderComparisonCreate(workspace,{real_model_enabled:true});assert.equal((html.match(/data-arena-profile=/g)||[]).length,8);
 for(const value of ['rewrite_chapter','outline_chapter','audit_chapter','configuration_count','max_calls','max_output_tokens','price-source-7','arena-person-fiction-person'])assert.ok(html.includes(value),value);
 assert.ok(html.includes('&lt;虚构人物>'));assert.ok(html.includes('输入token未知'));assert.ok(html.includes('不是实际账单'));
});
test('blind render carries no private bindings; all three scores gate reveal and typed winner is read-only',()=>{
 const functions=ui(),listing={experiments:[{id:'fiction-experiment',title:'虚构比较'}]},data=blind();let html=functions.renderComparison(listing,data,null,{},[]);
 assert.match(html,/id="reveal-comparison" disabled/);assert.ok(!html.includes('fiction-model'));assert.ok(!html.includes('fiction-connection'));assert.ok(html.includes('实际输入 17 / 输出 9 / 总计 26'));assert.ok(html.includes('&lt;虚构待核实意见>'));
 data.scores.push({side:'C',rating:4,outcome:'scored'});html=functions.renderComparison(listing,data,null,{},[]);assert.ok(!html.includes('id="reveal-comparison" disabled'));
 html=functions.renderComparison(listing,blind(true),null,{},[]);assert.ok(html.includes('fiction-model'));assert.ok(html.includes('只读打开结果'));assert.ok(!html.includes('data-choice-action="save_preset"'));
});
function form(values){const elements=Object.entries(values).map(([name,value])=>({name,type:typeof value==='boolean'?'checkbox':'text',...(typeof value==='boolean'?{checked:value}:{value:String(value)})}));elements.namedItem=name=>elements.find(e=>e.name===name);const profiles=Array.from({length:8},(_,i)=>({dataset:{arenaProfile:String(i)},hidden:false}));const planning={hidden:true};return {elements,querySelector:selector=>selector==='[data-arena-planning]'?planning:{},querySelectorAll:()=>profiles};}
test('creator submits three explicit profiles and outline preview with the same common instruction and rubric',async()=>{
 const calls=[],functions=ui(async(path,options)=>{calls.push({path,options});if(path.endsWith('context-preview'))return {context_text:'虚构共同规则',revision:1};if(path.endsWith('chapter-planning/preview'))return {context_sha256:'fiction-planning-source'};if(path.endsWith('/comparisons'))return {experiment_id:'new-fiction'};throw Error(path);});
 const values={task_kind:'outline_chapter',configuration_count:3,title:'三配置细纲',instruction:'虚构共同要求',rubric:'虚构共同评分',allow_unknown:true,max_calls:3,max_output_tokens:1536,planning_budget:20000,'arena-person-fiction-person':true};
 for(let i=0;i<3;i++)Object.assign(values,{['connection-'+i]:'fake',['model-'+i]:'fiction-'+i,['temperature-'+i]:.3,['tokens-'+i]:512,['budget-'+i]:1});
 const creator=form(values),listeners={},status={textContent:''},root={isConnected:true,querySelector:selector=>selector==='#comparison-create'?creator:status,querySelectorAll:()=>[],addEventListener:(name,fn)=>listeners[name]=fn};let created;
 functions.bindComparison(root,workspace,'fiction-chapter',{create:true},{created:async id=>created=id});await listeners.submit({preventDefault(){},stopPropagation(){},target:creator});assert.equal(created,'new-fiction',status.textContent);
 const request=JSON.parse(calls.find(c=>c.path.endsWith('/comparisons')).options.body);assert.equal(request.profiles.length,3);assert.equal(request.context_sha256,'fiction-planning-source');assert.equal(request.planning_options.instruction,'虚构共同要求\n\n共同评价要求：\n虚构共同评分');assert.deepEqual(request.planning_options.character_ids,['fiction-person']);assert.equal(request.budget.max_output_tokens,1536);assert.deepEqual(request.price_quotes,[null,null,null]);
});
