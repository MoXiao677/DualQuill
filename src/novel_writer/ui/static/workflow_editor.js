// Pure-data graph editing. Server preflight remains authoritative.
export const nodeKinds=['outline_source','generate_candidates','audit','await_author','adopt','reference','manual','search','model_idea','model_outline','model_draft','model_rewrite','model_candidate_audit','model_audit','offline_audit','branch','join','loop','human','apply','plan_proposal','memory_proposal'];
const task={context_budget:4000,max_output_chars:10000,timeout_ms:30000};
export function nodeDefaults(kind){
 if(kind==='generate_candidates')return {...task,count:2};
 if(kind==='audit')return {...task};
 if(kind.startsWith('model_'))return {...task};
 if(kind==='offline_audit')return {...task,forbidden_literals:[]};
 return structuredClone({outline_source:{},await_author:{action:'body'},adopt:{action:'body'},reference:{max_chars:20000},manual:{slot:'instruction'},search:{max_results:5},branch:{expected:'succeeded'},join:{},human:{action:'body'},apply:{action:'body'},plan_proposal:{target_kind:'chapter_outline',field:'core_idea'},memory_proposal:{index:0},loop:{iterations:1,nodes:[{id:'read',kind:'reference',parents:[],source:null,role:null,parameters:{max_chars:20000},when:null}]}}[kind]);
}
function permissions(nodes){
 const needed=new Set(['read_saved_source']);
 for(const n of nodes){
  const p=(n.kind.startsWith('model_')||['generate_candidates','audit'].includes(n.kind))?'prepare_model_request':({search:'search_local',offline_audit:'offline_analysis',human:'human_approval',await_author:'human_approval',adopt:'apply_approved_change',apply:'apply_approved_change',plan_proposal:'propose_changes',memory_proposal:'propose_changes'})[n.kind];
  if(p)needed.add(p);
  if(n.kind==='loop')for(const p of permissions(n.parameters.nodes))needed.add(p);
 }
 return [...needed].sort();
}
export function validateGraph(nodes){
 const ids=new Set(nodes.map(n=>n.id)),seen=new Set(),active=new Set();
 if(ids.size!==nodes.length||nodes.some(n=>!nodeKinds.includes(n.kind)))throw new Error('节点身份重复或能力不支持');
 function visit(n){
  if(seen.has(n.id))return;
  if(active.has(n.id))throw new Error('连线产生未声明循环；请使用有界loop节点');
  active.add(n.id);
  if(new Set(n.parents).size!==n.parents.length||n.parents.some(p=>!ids.has(p))||(n.source!==null&&!n.parents.includes(n.source)))throw new Error('父节点或source连线非法');
  if(n.when&&!n.parents.includes(n.when.source))throw new Error('分支条件必须声明父连线');
  for(const p of n.parents)visit(nodes.find(v=>v.id===p));
  if(n.kind==='loop')validateGraph(n.parameters.nodes);
  active.delete(n.id);seen.add(n.id);
 }
 nodes.forEach(visit);return nodes;
}
export function editGraph(spec,operation){
 const next=structuredClone(spec),nodes=next.nodes,index=nodes.findIndex(n=>n.id===operation.id);
 if(operation.action==='add'){
  if(!nodeKinds.includes(operation.kind))throw new Error('此能力未接通');
  let number=1;while(nodes.some(n=>n.id==='node'+number))number++;
  const kind=operation.kind;
  nodes.push({id:'node'+number,kind,parents:[],source:null,role:(kind.startsWith('model_')||['generate_candidates','audit'].includes(kind))?(['model_audit','model_candidate_audit','audit'].includes(kind)?'auditor':'writer'):null,parameters:nodeDefaults(kind),when:null});
 }else{
  if(index<0)throw new Error('节点不存在');
  if(operation.action==='remove'){
   if(nodes.some(n=>n.parents.includes(operation.id)||n.when?.source===operation.id))throw new Error('先解除后继连线再删除节点');
   nodes.splice(index,1);
  }else if(operation.action==='move'){
   const target=index+operation.delta;
   if(target<0||target>=nodes.length)return next;
   [nodes[index],nodes[target]]=[nodes[target],nodes[index]];
  }else if(operation.action==='connect'){
   nodes[index].parents=operation.parents;nodes[index].source=operation.source;
   nodes[index].parameters=operation.parameters;nodes[index].when=operation.when;
  }else throw new Error('编辑动作不支持');
 }
 validateGraph(nodes);next.permissions=permissions(nodes);return next;
}
export function renderGraphEditor(spec,h){
 return '<p>编辑只改变待预检模板。上下移动改变同级可运行顺序；执行依赖以连线为准。IDEA/细纲候选不会自动保存。未列出的节点能力不支持。</p><div class="field"><label for="workflow-add-kind">新增已接通节点</label><select id="workflow-add-kind" data-passive>'+nodeKinds.map(k=>'<option>'+k+'</option>').join('')+'</select><button type="button" data-wf-edit="add">新增节点</button></div>'+spec.nodes.map(n=>'<article class="context-card" data-wf-edit-node="'+h(n.id)+'"><h4>'+h(n.id)+' · '+h(n.kind)+'</h4><p>'+h(n.parents.join(' + ')||'起点')+' → '+h(n.id)+'；原文source：'+h(n.source||'无')+'</p><label>父节点ID（逗号分隔）<input data-wf-parents value="'+h(n.parents.join(','))+'"></label><label>消费的source父节点ID<input data-wf-source value="'+h(n.source||'')+'"></label><label>节点参数JSON<textarea data-wf-parameters>'+h(JSON.stringify(n.parameters,null,2))+'</textarea></label><label>分支条件JSON（null或source/equals）<input data-wf-when value="'+h(JSON.stringify(n.when))+'"></label><button type="button" data-wf-edit="connect">保存连线/参数</button><button type="button" data-wf-edit="up">上移</button><button type="button" data-wf-edit="down">下移</button><button type="button" data-wf-edit="remove">删除无后继节点</button></article>').join('');
}
