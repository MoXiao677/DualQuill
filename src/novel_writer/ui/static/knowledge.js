import {activeChapters} from './views.js';
import {renderGraphExtras,bindGraphExtras} from './graph_view.js';


import {api} from './api.js';
import {escapeHTML as h} from './views.js';
import {diffLines} from './state.js';
const drafts=new Map(),identities=new Map(),queries=new Map();
const list=(v)=>String(v||'').split('\n').map(x=>x.trim()).filter(Boolean);
const opts=items=>items.map(([id,label])=>'<option value="'+h(id)+'">'+h(label)+'</option>').join('');
let controlSequence=0;
const sel=(name,label,items)=>{const id='k-control-'+(++controlSequence);return '<div class="field"><label for="'+id+'">'+label+'</label><select id="'+id+'" data-passive '+(name==='memory_ids'?'multiple':'')+' name="'+name+'">'+opts(items)+'</select></div>';};
const txt=(name,label,value='')=>{const id='k-control-'+(++controlSequence);return '<div class="field"><label for="'+id+'">'+label+'</label><textarea id="'+id+'" name="'+name+'">'+h(value)+'</textarea></div>';};
const check=(name,label,checked=false)=>'<label class="check-label"><input name="'+name+'" type="checkbox" '+(checked?'checked':'')+'>'+label+'</label>';
const button=(label,attrs='')=>'<button type="button" '+attrs+'>'+label+'</button>';
const pre=value=>'<pre class="context-text">'+h(typeof value==='string'?value:JSON.stringify(value,null,2))+'</pre>';
const form=(id,title,body,submit)=>'<form data-k-form="'+id+'"><h3>'+title+'</h3>'+body+(submit?'<button id="k-save-'+id+'" type="submit">'+submit+'</button>':'')+'</form>';
const sourceInfo=s=>'<p>出处 '+h(s.kind)+' / '+h(s.entity_id)+' · 保存编号 '+s.workspace_revision+' · 版本 '+h(s.version_id||'无独立版本')+'</p>'+button('查看固定出处',"data-k-source='"+h(JSON.stringify(s))+"'");
const planLabels={theme:'核心主题',premise:'故事起点',main_plot:'全书主线',ending:'预期结局',core_idea:'核心情节',objective:'本章目标',story_time:'剧情时间'};
const labels={character:'人物',location:'地点',organization:'组织',event:'事件',prop:'道具',setting:'设定',foreshadow:'伏笔'};
export const knowledgeOptions=(project,chapter)=>queries.get(project)||(chapter?{chapter_id:chapter}:{});
export function renderKnowledge(workspace,data){
 const doc=workspace.document,p=doc.project.id,chapters=activeChapters(workspace).map(c=>[c.id,'第'+c.number+'章 · '+c.title]);
 const sources=activeChapters(workspace).map(c=>[JSON.stringify({kind:'chapter',entity_id:c.id}),'正文 · '+c.title]);
 sources.push(...doc.characters.map(c=>[JSON.stringify({kind:'character',entity_id:c.id}),'人物设定 · '+c.name]),[JSON.stringify({kind:'worldbuilding',entity_id:p}),'世界观']);
 const allSources=[...sources,...doc.chapter_outlines.map(o=>[JSON.stringify({kind:'chapter_outline',entity_id:o.id}),'创作计划 · 第'+doc.chapters.find(c=>c.id===o.chapter_id)?.number+'章'])];
 const nodes=data.nodes.map(n=>[n.id,n.label]),targets=[];
 if(doc.book_outline)targets.push([JSON.stringify({kind:'book_outline',entity_id:doc.book_outline.id}),'全书大纲']);
 targets.push(...doc.chapter_outlines.map(o=>[JSON.stringify({kind:'chapter_outline',entity_id:o.id}),'章节细纲 · '+doc.chapters.find(c=>c.id===o.chapter_id)?.title]));
 const rules=workspace.review_issues?.filter(i=>['duplicate_exact','duplicate_near'].includes(i.finding.rule_id))||[];
 const nodeForm=form('node','人工节点',sel('node_id','编辑节点',[['','新建节点'],...nodes])+sel('kind','节点类型',Object.entries(labels))+txt('label','节点名称')+txt('aliases','别名（每行一个）')+sel('memory_ids','关联记忆',[['','不关联'],...(workspace.memories||[]).map(m=>[m.id,m.title])])+sel('position_chapter_id','节点生效章节',chapters)+sel('source','节点出处',allSources)+check('confirmed','我已复核此人工声明',true),'保存人工节点');
 const edgeForm=form('edge','人工关系',sel('from_id','关系起点',nodes)+sel('to_id','关系终点',nodes)+txt('relation','关系说明')+sel('position_chapter_id','关系生效章节',chapters)+sel('source','关系出处',allSources)+check('confirmed','我已复核此人工关系',true),'保存人工关系');
 const queryForm=form('query','检索与有限关系链',txt('query','节点或别名检索')+sel('chapter_id','图谱故事位置',[['','全书（包含未来声明）'],...chapters])+sel('root_id','关系链起点',[['','全部节点'],...nodes])+sel('depth','关系链深度',[['1','一层邻接'],['2','两层'],['3','三层']])+check('ready_only','只看已复核、来源未变的已保存资料声明'),'检索关系图谱');
 const mergeForm=form('merge','别名合并',sel('source_id','合并来源节点',nodes)+sel('target_id','保留节点',nodes)+button('预览别名合并影响','data-k-preview')+'<div id="k-merge-preview" hidden></div>','');
 const planForm=form('plan','手动规划反馈',sel('target','反馈目标',targets)+sel('field','反馈字段',[])+txt('new_text','规划建议值')+sel('source','规划反馈出处',sources)+txt('reason','规划反馈理由')+'<p id="k-lock-state"></p>'+button('锁定此规划字段','data-k-lock="true"')+button('明确解除此字段锁','data-k-lock="false"'),'准备单字段规划反馈');
 const localForm=form('local','从真实查重证据准备局部修改',sel('issue_id','查重问题',rules.map((i,n)=>[i.id,'重复问题 '+(n+1)+' · '+i.finding.message]))+sel('side','修改哪一侧',[['1','第二侧'],['0','第一侧']])+sel('mode','局部修改类型',[['delete','删除该段'],['merge','合并为作者文字'],['rewrite','替换为作者改写']])+txt('replacement','局部替换文字')+txt('reason','局部修改理由'),'从双侧证据准备局部修改');
 const graph=data.nodes.map(n=>'<article class="context-card" data-graph-node="'+n.id+'"><h3>'+h(n.label)+' · '+labels[n.kind]+'</h3><p>'+h(n.aliases.join('、'))+'</p><p>人工声明 · '+(n.basis==='plan'?'创作计划（不作为已发生事实）':'已保存资料')+' · '+(n.confirmed?'已复核':'未复核')+' · '+(n.outdated?'来源已过期':'来源未变')+' · 生效章位 '+n.effective_chapter_number+'</p><p>记忆链接 '+h(n.memory_ids.join('、')||'无')+'</p>'+sourceInfo(n.source)+'</article>').join('')+data.edges.map(e=>'<article data-graph-edge><p>'+h((nodes.find(n=>n[0]===e.from_id)?.[1]||e.from_id)+' → '+e.relation+' → '+(nodes.find(n=>n[0]===e.to_id)?.[1]||e.to_id))+' · '+(e.outdated?'来源已过期':'来源未变')+'</p>'+sourceInfo(e.source)+'</article>').join('');
 const merges=data.merges.map(m=>'<article><p>合并 '+h(m.source_id)+' → '+h(m.target_id)+' · '+(data.restores.some(r=>r.merge_id===m.id)?'已恢复':button('恢复此次合并','data-k-restore="'+m.id+'"'))+'</p></article>').join('');
 const plans=data.plans.map(p=>'<article class="context-card" data-plan-proposal="'+p.id+'"><h3>规划字段 '+h(planLabels[p.field])+'</h3><p>'+(p.receipt?h(p.receipt.decision):p.outdated?'来源/目标已过期':p.locked?'字段已锁定':'待明确决定')+'</p><p>旧值</p>'+pre(p.old_text)+'<p>建议值</p>'+pre(p.new_text)+'<p>差异</p>'+pre(diffLines(p.old_text,p.new_text).map(r=>(r.kind==='add'?'+ ':r.kind==='remove'?'- ':'  ')+r.text).join('\n'))+'<details><summary>后续章、人工伏笔/记忆影响</summary>'+pre(p.impact)+'</details>'+sourceInfo(p.source)+button('明确接受此字段差异','data-k-plan-decision="accepted" data-k-id="'+p.id+'" '+(p.receipt||p.outdated||p.locked?'disabled':''))+button('拒绝此规划提案','data-k-plan-decision="rejected" data-k-id="'+p.id+'" '+(p.receipt?'disabled':''))+'</article>').join('');
 const edits=data.edits.map(p=>'<article class="context-card" data-local-edit="'+p.id+'"><h3>局部正文提案修订 '+p.revision+'</h3><p>'+(p.receipt?h(p.receipt.decision):p.outdated?'双侧出处已过期':'待明确决定')+'</p><p>双侧原文证据（精确字符范围）</p>'+p.evidence.map(e=>'<p>'+h(e.chapter_id)+' · '+e.start+'–'+e.end+' · 版本 '+h(e.version_id||'无')+'</p>'+pre(e.quote)).join('')+'<details><summary>原正文与候选正文</summary>'+pre(p.before_text)+pre(p.after_text)+'</details><p>原文 → 建议差异</p>'+pre(diffLines(p.before_text,p.after_text).map(r=>(r.kind==='add'?'+ ':r.kind==='remove'?'- ':'  ')+r.text).join('\n'))+'<details><summary>章位、伏笔、记忆引用影响</summary>'+pre(p.impact)+'</details>'+form('edit-'+p.id,'编辑此提案',sel('mode','编辑提案类型',[['delete','删除'],['merge','合并'],['rewrite','改写']])+txt('replacement','编辑替换文字',p.replacement)+txt('reason','编辑提案理由',p.reason),p.receipt?'':'保存提案修订并重看差异')+check('authorize-'+p.id,'我明确授权修改已确认章节并保留旧版')+button('明确采纳此局部正文差异','data-k-edit-decision="accepted" data-k-id="'+p.id+'" '+(p.receipt||p.outdated?'disabled':''))+button('拒绝局部提案','data-k-edit-decision="rejected" data-k-id="'+p.id+'" '+(p.receipt?'disabled':''))+button('取消局部提案','data-k-edit-decision="cancelled" data-k-id="'+p.id+'" '+(p.receipt?'disabled':''))+'</article>').join('');
 return '<section id="knowledge-panel" class="panel"><h2>图谱与人工反馈</h2><p>人工声明与已保存出处分开保存。计划不自动变为事实；修改始终先看差异再明确决定。</p><p id="k-status" role="status">保存编号 '+data.revision+'</p>'+button('刷新图谱与反馈','data-k-refresh')+'<pre id="k-source-detail" class="context-text" hidden></pre>'+queryForm+renderGraphExtras(workspace,data)+'<h3>当前节点与关系</h3>'+graph+nodeForm+edgeForm+mergeForm+merges+planForm+plans+localForm+edits+'</section>';
}
export function bindKnowledge(root,workspace,data,onRefresh,onPrepared){
 bindGraphExtras(root.querySelector('#graph-extras'),workspace,data,{refresh:onRefresh,prepared:onPrepared});
 const project=workspace.document.project.id,base='/api/projects/'+encodeURIComponent(project)+'/knowledge/';let pending=false,preview=null;
 const key=form=>project+'/'+form.dataset.kForm;
 const values=form=>Object.fromEntries([...form.elements].filter(e=>e.name).map(e=>[e.name,e.multiple?[...e.selectedOptions].map(o=>o.value).filter(Boolean):e.type==='checkbox'?e.checked:e.value]));
 const capture=()=>root.querySelectorAll('[data-k-form]').forEach(f=>drafts.set(key(f),values(f)));
 function hydrate(){root.querySelectorAll('[data-k-form]').forEach(f=>{const v=drafts.get(key(f));if(v)for(const [name,value]of Object.entries(v)){const e=f.elements.namedItem(name);if(e){if(e.multiple){for(const o of e.options)o.selected=value.includes(o.value);}else if(e.type==='checkbox')e.checked=value;else e.value=value;}}});}
 const plan=root.querySelector('[data-k-form="plan"]');
 function fields(restore=false){if(!plan.elements.target.value)return;const t=JSON.parse(plan.elements.target.value),names=t.kind==='book_outline'?['theme','premise','main_plot','ending']:['core_idea','objective','story_time'];const old=restore?drafts.get(key(plan))?.field:plan.elements.field.value;plan.elements.field.innerHTML=opts(names.map(n=>[n,planLabels[n]]));if(names.includes(old))plan.elements.field.value=old;lockState();}
 function lockState(){if(!plan.elements.target.value)return;const t=JSON.parse(plan.elements.target.value),events=data.locks.filter(l=>l.target_kind===t.kind&&l.target_id===t.entity_id&&l.field===plan.elements.field.value);root.querySelector('#k-lock-state').textContent=events.at(-1)?.locked?'此字段已锁定':'此字段未锁定';}
 hydrate();fields(true);
 const query=root.querySelector('[data-k-form="query"]');if(!drafts.has(key(query))){for(const [name,value]of Object.entries(data.graph_options||{})){const e=query.elements.namedItem(name);if(e){if(e.type==='checkbox')e.checked=value;else e.value=value;}}}
 root.querySelectorAll('[data-local-edit]').forEach(card=>{const p=data.edits.find(p=>p.id===card.dataset.localEdit);card.querySelector('h3').insertAdjacentHTML('afterend','<p>提案来源：'+(p.model_proposal_id?'模型桥段意见（原意见未验证）':'离线双侧原文证据')+'</p>');if(!drafts.has(key(card.querySelector('form'))))card.querySelector('[name="mode"]').value=p.mode;});
 async function perform(action,payload,after){
  if(pending)return;pending=true;capture();const buttons=[...root.querySelectorAll('button')],disabled=buttons.map(b=>b.disabled);buttons.forEach(b=>b.disabled=true);
  const signature=project+'/'+action+'/'+JSON.stringify(payload);let request=identities.get(signature);
  if(!request){request={...payload,operation_id:crypto.randomUUID(),expected_revision:data.revision};identities.set(signature,request);}
  request.expected_revision=data.revision;
  try{const result=await api(base+action,{method:'POST',body:JSON.stringify(request)});if(after)after(result);await onRefresh();identities.delete(signature);}
  catch(error){root.querySelector('#k-status').textContent='操作失败：'+error.message+'。输入与本次操作身份仍保留，可重试或刷新核对。';}
  finally{pending=false;buttons.forEach((b,n)=>{if(b.isConnected)b.disabled=disabled[n];});}
 }
 root.addEventListener('input',capture);
 root.addEventListener('change',e=>{capture();if(e.target===plan.elements.target)fields();if(e.target===plan.elements.field)lockState();if(e.target.name==='source_id'||e.target.name==='target_id'){preview=null;root.querySelector('#k-merge-preview').hidden=true;}
  if(e.target.name==='node_id'){const n=data.nodes.find(n=>n.id===e.target.value),f=e.target.form;if(n){for(const name of ['kind','label','position_chapter_id','confirmed']){if(typeof n[name]==='boolean')f.elements[name].checked=n[name];else f.elements[name].value=n[name];}f.elements.aliases.value=n.aliases.join('\n');for(const o of f.elements.memory_ids.options)o.selected=n.memory_ids.includes(o.value);f.elements.source.value=JSON.stringify({kind:n.source.kind,entity_id:n.source.entity_id});capture();}}
 });
 root.addEventListener('submit',async event=>{event.preventDefault();event.stopPropagation();const f=event.target,v=values(f),id=f.dataset.kForm;capture();
  if(id==='query'){queries.set(project,{query:v.query,...(v.chapter_id?{chapter_id:v.chapter_id}:{}),...(v.root_id?{root_id:v.root_id}:{}),depth:Number(v.depth),ready_only:v.ready_only});await onRefresh();return;}
  if(id==='node'){if(!v.node_id)delete v.node_id;await perform('save_node',{...v,...(v.node_id?{node_id:v.node_id}:{}),aliases:list(v.aliases),memory_ids:Array.isArray(v.memory_ids)?v.memory_ids:(v.memory_ids?[v.memory_ids]:[]),source:JSON.parse(v.source)});}
  else if(id==='edge')await perform('save_edge',{...v,source:JSON.parse(v.source)});
  else if(id==='plan'){const t=JSON.parse(v.target);delete v.target;await perform('prepare_plan',{...v,target_kind:t.kind,target_id:t.entity_id,source:JSON.parse(v.source)});}
  else if(id==='local')await perform('prepare_edit',{...v,side:Number(v.side)});
  else if(id.startsWith('edit-'))await perform('revise_edit',{...v,proposal_id:id.slice(5)},()=>drafts.delete(key(f)));
 });
 root.addEventListener('click',async event=>{const b=event.target.closest('button');if(!b)return;event.stopPropagation();if(pending)return;
  try{
   if(b.hasAttribute('data-k-refresh')){capture();await onRefresh();}
   else if(b.hasAttribute('data-k-preview')){const v=values(b.closest('form'));preview=await api(base+'merge-preview',{method:'POST',body:JSON.stringify(v)});const box=root.querySelector('#k-merge-preview');box.hidden=false;box.innerHTML=pre(preview)+button('确认按预览合并','data-k-confirm-merge');}
   else if(b.hasAttribute('data-k-confirm-merge')&&preview){await perform('merge',{source_id:preview.source.id,target_id:preview.target.id});}
   else if(b.dataset.kRestore)await perform('restore_merge',{merge_id:b.dataset.kRestore});
   else if(b.hasAttribute('data-k-lock')){const v=values(plan),t=JSON.parse(v.target);await perform('set_plan_lock',{target_kind:t.kind,target_id:t.entity_id,field:v.field,locked:b.dataset.kLock==='true',reason:v.reason});}
   else if(b.dataset.kPlanDecision)await perform('decide_plan',{proposal_id:b.dataset.kId,decision:b.dataset.kPlanDecision});
   else if(b.dataset.kEditDecision){const p=data.edits.find(p=>p.id===b.dataset.kId);await perform('decide_edit',{proposal_id:p.id,proposal_revision:p.revision,decision:b.dataset.kEditDecision,authorize_confirmed:root.querySelector('[name="authorize-'+p.id+'"]').checked});}
   else if(b.dataset.kSource){const source=JSON.parse(b.dataset.kSource),result=await api(base+'source',{method:'POST',body:JSON.stringify({source})});const box=root.querySelector('#k-source-detail');box.hidden=false;box.textContent=JSON.stringify(result,null,2);box.scrollIntoView({block:'nearest'});}
  }catch(error){root.querySelector('#k-status').textContent='操作失败：'+error.message;}
 });
}


