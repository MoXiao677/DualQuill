import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const text=await readFile(new URL('../src/novel_writer/ui/static/workflow_editor.js',import.meta.url),'utf8');
const {editGraph,validateGraph,nodeDefaults}=await import('data:text/javascript;base64,'+Buffer.from(text).toString('base64'));
const node=(id,parents=[],source=null,kind='reference')=>({id,parents,source,kind,role:null,parameters:nodeDefaults(kind),when:null});
const graph=()=>({workflow_format:1,interface_version:1,name:'fictional',permissions:['read_saved_source'],nodes:[node('read'),node('other'),node('join',['read','other'],'read','join')]});

test('connect source explicitly, reorder peers, add and remove preserve original graph',()=>{
 const original=graph();
 const changed=editGraph(original,{action:'connect',id:'join',parents:['read','other'],source:'other',parameters:{},when:null});
 assert.equal(changed.nodes.at(-1).source,'other');assert.equal(original.nodes.at(-1).source,'read');
 const moved=editGraph(changed,{action:'move',id:'other',delta:-1});assert.equal(moved.nodes[0].id,'other');assert.deepEqual(moved.nodes.at(-1).parents,['read','other']);
 const added=editGraph(moved,{action:'add',kind:'model_candidate_audit'});assert.equal(added.nodes.at(-1).role,'auditor');assert.ok(added.permissions.includes('prepare_model_request'));
 assert.equal(editGraph(added,{action:'remove',id:'node1'}).nodes.length,3);
});
test('cycles, dangling sources and deleting referenced producers fail with no mutation',()=>{
 const spec=graph(),before=JSON.stringify(spec);
 assert.throws(()=>editGraph(spec,{action:'connect',id:'read',parents:['join'],source:'join',parameters:{},when:null}),/循环/);
 assert.throws(()=>editGraph(spec,{action:'connect',id:'join',parents:['read'],source:'other',parameters:{},when:null}),/source/);
 assert.throws(()=>editGraph(spec,{action:'remove',id:'read'}),/后继/);
 assert.equal(JSON.stringify(spec),before);
});
test('bounded nested loop and branch gates remain pure-data declarations',()=>{
 const loop=node('repeat',[],null,'loop');loop.parameters.iterations=2;assert.doesNotThrow(()=>validateGraph([loop]));
 const spec=graph();spec.nodes.at(-1).when={source:'missing',equals:true};assert.throws(()=>validateGraph(spec.nodes),/分支/);
 assert.throws(()=>editGraph(graph(),{action:'add',kind:'execute_script'}),/未接通/);
});
