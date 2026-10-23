import {api} from './api.js';
import {escapeHTML as h,activeChapters} from './views.js';
import {connectionChoices,modelAdapterId} from './model_tasks.js';
import {renderSampling,captureSampling,fillSampling,samplingOptions} from './sampling.js';

const drafts=new Map(),requests=new Map();
const pre=v=>'<pre class="context-text">'+h(typeof v==='string'?v:JSON.stringify(v,null,2))+'</pre>';
const options=items=>items.map(([id,label])=>'<option value="'+h(id)+'">'+h(label)+'</option>').join('');
const field=(name,label,value,type='text')=>'<label>'+label+'<input name="'+name+'" type="'+type+'" '+(type==='number'?'step="any"':'')+' value="'+h(value)+'"></label>';
const select=(name,label,items,multiple=false)=>'<label>'+label+'<select name="'+name+'" data-passive '+(multiple?'multiple':'')+'>'+options(items)+'</select></label>';
const labels={character:'人物',location:'地点',organization:'组织',event:'事件',prop:'道具',setting:'设定',foreshadow:'伏笔'};

export function graphLayout(nodes){
 const radius=Math.max(160,Math.min(450,nodes.length*18));
 return nodes.map((n,i)=>({...n,x:500+Math.cos(i/Math.max(1,nodes.length)*Math.PI*2)*radius,y:500+Math.sin(i/Math.max(1,nodes.length)*Math.PI*2)*radius}));
}
export function graphMarkup(data){
 const positions=graphLayout(data.nodes),map=new Map(positions.map(n=>[n.id,n]));
 const edges=data.edges.map(e=>{const a=map.get(e.from_id),b=map.get(e.to_id);if(!a||!b)return '';const x=(a.x+b.x)/2,y=(a.y+b.y)/2;
  return '<g data-svg-edge="'+h(e.id)+'" tabindex="0" role="button" aria-label="'+h(a.label+' '+e.relation+' '+b.label)+'"><line x1="'+a.x+'" y1="'+a.y+'" x2="'+b.x+'" y2="'+b.y+'" stroke="'+(e.outdated?'#b95136':'#6b809c')+'" stroke-width="4"/><text x="'+x+'" y="'+y+'" fill="currentColor" font-size="17">'+h(e.relation)+'</text></g>';}).join('');
 const nodes=positions.map(n=>'<g data-svg-node="'+h(n.id)+'" transform="translate('+n.x+' '+n.y+')" tabindex="0" role="button" aria-label="'+h(n.label)+'"><circle r="28" stroke="'+(n.outdated?'#b95136':'#4a97b9')+'" stroke-width="4" fill="'+(n.ready_as_declared_fact?'#233b4d':'#5b4d36')+'"/><text y="48" text-anchor="middle" fill="currentColor" font-size="20">'+h(n.label.length>18?n.label.slice(0,18)+'…':n.label)+'</text></g>').join('');
 return '<div class="graph-toolbar"><button type="button" data-graph-zoom="1.25">放大</button><button type="button" data-graph-zoom="0.8">缩小</button><button type="button" data-graph-reset>复位视图</button><button type="button" data-graph-rebuild>显式重建图谱索引</button></div><p>拖动空白平移，滚轮或按钮缩放；拖动节点调整位置，点击节点或关系查看出处，键盘 Enter 打开证据。布局仅留在本次页面。</p><svg class="interactive-graph" viewBox="0 0 1000 1000" role="img" aria-label="可交互知识图谱" style="width:100%;height:420px;touch-action:none"><g data-graph-scene>'+edges+nodes+'</g></svg><section data-graph-detail aria-live="polite"></section>';
}

function quoteMarkup(e){
 return '<p>'+h(e.chapter_id)+' · 版本 '+h(e.version_id||'无')+' · Unicode '+e.start+'–'+e.end+'</p>'+pre(e.quote)+'<button type="button" data-graph-quote="'+h(JSON.stringify(e))+'">打开精确引文的保存版本</button>';
}

export function renderGraphExtras(workspace,data){
 const chapters=activeChapters(workspace),nodes=data.nodes.map(n=>[n.id,n.label]),project=workspace.document.project.id;
 const selected=data.graph_options?.chapter_id||chapters.at(-1)?.id;
 const cap=workspace.document.chapters.find(c=>c.id===selected)?.number;
 const eligible=chapters.filter(c=>cap===undefined||c.number<=cap);
 const preparation='<form id="graph-extract-form"><h3>已保存正文 → 模型图谱提案</h3><p>明确选择至多8章，只发送所选已保存正文；截至章之后的素材不能发送。先冻结核对，再单次确认，结果待核实，接受才新增正式实体/边。</p>'+select('chapter_id','抽取截至章节',chapters.map(c=>[c.id,'第'+c.number+'章 · '+c.title]))+select('selected_chapter_ids','明确选择来源章节',eligible.map(c=>[c.id,'第'+c.number+'章 · '+c.title]),true)+select('connection_id','图谱抽取模型连接',connectionChoices(data.graph_caps))+field('model_id','模型编号',data.graph_caps?.connections?.[0]?.model_id||'')+field('instruction','本次要求','抽取实体、别名和关系，每条都提供精确引文。')+field('temperature','温度',.3,'number')+field('max_tokens','输出令牌上限',2048,'number')+renderSampling('graph',null)+field('budget_limit','单次风险预算（美元，非硬封顶）',1,'number')+'<label><input name="allow_unknown_cost" type="checkbox">我允许费用未知，执行前仍须核对并逐次确认</label>'+field('timeout_ms','总时限（毫秒，最多300000）',120000,'number')+'<button type="submit">冻结图谱抽取请求（不发送）</button></form>';
 const proposals=(data.graph_extractions||[]).map(e=>'<article data-graph-extraction="'+h(e.id)+'"><h3>模型图谱提案 · '+(e.receipt?h(e.receipt.decision):e.outdated?'出处过期':'待核实')+'</h3>'+pre(e.output.overview)+e.output.nodes.map(n=>'<details><summary>'+h(labels[n.kind]+' · '+n.label)+' · 别名 '+h(n.aliases.join('、'))+'</summary>'+n.evidence.map(quoteMarkup).join('')+'</details>').join('')+e.output.edges.map(edge=>'<details><summary>'+h(edge.from_key+' → '+edge.relation+' → '+edge.to_key)+'</summary>'+edge.evidence.map(quoteMarkup).join('')+'</details>').join('')+'<label><input data-graph-inference type="checkbox">我已核对全部实体、别名及关系的引文和推断，明确新增正式节点/边</label>'+['accepted','rejected','cancelled'].map((decision,i)=>'<button type="button" data-graph-decision="'+decision+'" '+(e.receipt||(decision==='accepted'&&e.outdated)?'disabled':'')+'>'+['明确接受全部提案','拒绝提案','取消提案'][i]+'</button>').join('')+'</article>').join('');
 const query='<form id="graph-path-form"><h3>有界关系路径</h3>'+select('from_id','路径起点',nodes)+select('to_id','路径终点',nodes)+select('direction','方向',[['outgoing','沿关系方向'],['incoming','反向'],['both','双向']])+field('max_depth','最大深度（1至6）',4,'number')+field('max_paths','最多路径（1至50）',20,'number')+field('relations','关系白名单（逗号分隔，可空）','')+'<button type="submit">查询已复核且有效的路径</button></form><div id="graph-path-results" aria-live="polite"></div>';
 return '<section id="graph-extras" data-project="'+h(project)+'"><h3>关系图谱视图</h3><p id="graph-status" role="status">图中仅展示当前检索章位可见的声明；颜色区分有效与过期，未确认声明不参与事实路径。</p>'+graphMarkup(data)+query+preparation+'<h3>已保存抽取提案</h3>'+proposals+'</section>';
}

export function bindGraphExtras(root,workspace,data,hooks={}){
 if(!root)return;
 const project=workspace.document.project.id,base='/api/projects/'+encodeURIComponent(project)+'/knowledge/';
 const form=root.querySelector('#graph-extract-form'),status=root.querySelector('#graph-status');
 let busy=false;
 const say=message=>{if(status.isConnected)status.textContent=message;};
 const read=()=>Object.fromEntries([...form.elements].filter(e=>e.name).map(e=>[e.name,e.multiple?[...e.selectedOptions].map(o=>o.value):e.type==='checkbox'?e.checked:e.value]));
 const saved=drafts.get(project);
 if(saved){for(const [key,value] of Object.entries(saved)){const e=form.elements.namedItem(key);if(!e)continue;if(e.multiple){for(const o of e.options)o.selected=value.includes(o.value);}else if(e.type==='checkbox')e.checked=value;else e.value=value;}}
 else{form.elements.chapter_id.value=data.graph_options?.chapter_id||form.elements.chapter_id.options[0]?.value||'';for(const o of form.elements.selected_chapter_ids.options)o.selected=o.value===form.elements.chapter_id.value;}
 if(saved?.sampling)fillSampling(form.querySelector('[data-sampling="graph"]'),saved.sampling);
 const capture=()=>drafts.set(project,{...read(),sampling:captureSampling(form.querySelector('[data-sampling="graph"]'))});
 form.addEventListener('input',capture);
 form.addEventListener('change',event=>{if(event.target.name==='connection_id'){form.elements.model_id.value=data.graph_caps?.connections?.find(c=>c.id===event.target.value)?.model_id||'';}if(event.target.name==='chapter_id'){const cap=workspace.document.chapters.find(c=>c.id===event.target.value)?.number;form.elements.selected_chapter_ids.innerHTML=options(activeChapters(workspace).filter(c=>c.number<=cap).map(c=>[c.id,'第'+c.number+'章 · '+c.title]));}capture();});
 async function operation(action,payload,after){
  if(busy)return;
  busy=true;
  const buttons=[...root.querySelectorAll('button')],disabled=buttons.map(b=>b.disabled);buttons.forEach(b=>b.disabled=true);
  const signature=project+'/'+action+'/'+JSON.stringify(payload),old=requests.get(signature);
  let request=old;
  if(!request){request={...payload,...(action==='extract-prepare'?{request_id:crypto.randomUUID()}:{operation_id:crypto.randomUUID()}),expected_revision:data.revision};requests.set(signature,request);}
  if(action==='extract-decide')request.expected_revision=data.revision;
  try{const result=await api(base+action,{method:'POST',body:JSON.stringify(request)});await after?.(result);requests.delete(signature);}
  catch(error){say('操作失败：'+error.message+'；输入及操作身份保留，可刷新核对后重试。');}
  finally{busy=false;buttons.forEach((b,i)=>{if(b.isConnected)b.disabled=disabled[i];});}
 }
 form.addEventListener('submit',event=>{event.preventDefault();event.stopPropagation();capture();const v=read();try{
  const payload={chapter_id:v.chapter_id,selected_chapter_ids:v.selected_chapter_ids,instruction:v.instruction,max_output_chars:50000,timeout_ms:Number(v.timeout_ms),model_options:{...samplingOptions(captureSampling(form.querySelector('[data-sampling="graph"]'))),adapter_id:modelAdapterId(v.connection_id),connection_id:v.connection_id,model_id:v.model_id,temperature:Number(v.temperature),max_tokens:Number(v.max_tokens),budget_limit:Number(v.budget_limit),allow_unknown_cost:v.allow_unknown_cost,prompt_version:'graph-extract-json-1'}};
  void operation('extract-prepare',payload,async result=>{say('图谱请求已保存，尚未发送。请核对外发内容与预算，再明确执行。');await hooks.prepared?.(result.task.id);});
 }catch(error){say(error.message+'；输入保留，尚未发送。');}});
 const pathForm=root.querySelector('#graph-path-form');
 pathForm.addEventListener('submit',event=>{event.preventDefault();event.stopPropagation();if(busy)return;const v=Object.fromEntries(new FormData(pathForm));
  void(async()=>{try{const result=await api(base+'paths',{method:'POST',body:JSON.stringify({from_id:v.from_id,to_id:v.to_id,max_depth:Number(v.max_depth),max_paths:Number(v.max_paths),direction:v.direction,relations:v.relations.split(/[,，]/).map(s=>s.trim()).filter(Boolean),...(data.graph_options?.chapter_id?{chapter_id:data.graph_options.chapter_id}:{})})});
   root.querySelector('#graph-path-results').innerHTML='<p>'+result.paths.length+' 条路径 · 展开 '+result.expansions+' / '+result.limits.expansions+(result.truncated?' · 已达边界，结果不完整':'')+'</p>'+result.paths.map(p=>'<p>'+p.node_ids.map(id=>h(data.nodes.find(n=>n.id===id)?.label||id)).join(' → ')+'</p>').join('');
   const edgeIds=new Set(result.paths.flatMap(p=>p.edge_ids));for(const e of root.querySelectorAll('[data-svg-edge]'))e.style.opacity=edgeIds.has(e.dataset.svgEdge)?'1':'.25';
  }catch(error){say(error.message);}})();
 });
 const svg=root.querySelector('svg'),scene=root.querySelector('[data-graph-scene]');
 let zoom=1,offset={x:0,y:0},drag=null;
 const transform=()=>scene.setAttribute('transform','translate('+offset.x+' '+offset.y+') scale('+zoom+')');
 const zoomBy=factor=>{const next=Math.max(.35,Math.min(4,zoom*factor));offset={x:500-(500-offset.x)*next/zoom,y:500-(500-offset.y)*next/zoom};zoom=next;transform();};
 const point=event=>{const rect=svg.getBoundingClientRect(),scale=Math.min(rect.width,rect.height)/1000;return{x:(event.clientX-rect.left-(rect.width-1000*scale)/2)/scale,y:(event.clientY-rect.top-(rect.height-1000*scale)/2)/scale};};
 const layout=new Map(graphLayout(data.nodes).map(n=>[n.id,n]));
 function updateEdges(){for(const e of data.edges){const group=[...root.querySelectorAll('[data-svg-edge]')].find(g=>g.dataset.svgEdge===e.id),a=layout.get(e.from_id),b=layout.get(e.to_id);if(!group||!a||!b)continue;const line=group.querySelector('line'),text=group.querySelector('text');for(const [k,value]of Object.entries({x1:a.x,y1:a.y,x2:b.x,y2:b.y}))line.setAttribute(k,value);text.setAttribute('x',(a.x+b.x)/2);text.setAttribute('y',(a.y+b.y)/2);}}
 svg.addEventListener('pointerdown',event=>{if(event.button!==0)return;const target=event.target.closest('[data-svg-node]');drag={start:point(event),offset:{...offset},node:target,id:target?.dataset.svgNode,moved:false};if(drag.id)drag.position={...layout.get(drag.id)};svg.setPointerCapture(event.pointerId);});
 svg.addEventListener('pointermove',event=>{if(!drag)return;const p=point(event),dx=p.x-drag.start.x,dy=p.y-drag.start.y;if(Math.abs(dx)+Math.abs(dy)>4)drag.moved=true;if(drag.node){const value=layout.get(drag.id);value.x=drag.position.x+dx/zoom;value.y=drag.position.y+dy/zoom;drag.node.setAttribute('transform','translate('+value.x+' '+value.y+')');updateEdges();}else{offset={x:drag.offset.x+dx,y:drag.offset.y+dy};transform();}});
 let suppressClick=false;
 svg.addEventListener('pointerup',event=>{suppressClick=!!drag?.moved;drag=null;if(svg.hasPointerCapture(event.pointerId))svg.releasePointerCapture(event.pointerId);});
 svg.addEventListener('pointercancel',()=>{drag=null;suppressClick=false;});
 svg.addEventListener('wheel',event=>{event.preventDefault();zoomBy(event.deltaY<0?1.15:1/1.15);},{passive:false});
 function detail(target){
  const nodeId=target.dataset.svgNode,edgeId=target.dataset.svgEdge,value=nodeId?data.nodes.find(n=>n.id===nodeId):data.edges.find(e=>e.id===edgeId);if(!value)return;
  const source=value.source,box=root.querySelector('[data-graph-detail]');
  box.innerHTML='<h4>'+h(value.label||value.relation)+' · '+(value.outdated?'出处过期':value.ready_as_declared_fact?'作者已复核':'未确认/计划')+'</h4>'+pre({aliases:value.aliases,source})+(value.evidence||[]).map(quoteMarkup).join('')+'<button type="button" data-graph-primary="'+h(JSON.stringify(source))+'">打开固定出处</button>';
 }
 svg.addEventListener('click',event=>{if(suppressClick){suppressClick=false;return;}const target=event.target.closest('[data-svg-node],[data-svg-edge]');if(target)detail(target);});
 svg.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){const target=event.target.closest('[data-svg-node],[data-svg-edge]');if(target){event.preventDefault();detail(target);}}});
 root.addEventListener('click',event=>{const button=event.target.closest('button');if(!button)return;event.stopPropagation();
  if(button.dataset.graphZoom){zoomBy(Number(button.dataset.graphZoom));return;}
  if(button.hasAttribute('data-graph-reset')){zoom=1;offset={x:0,y:0};transform();for(const n of graphLayout(data.nodes)){layout.set(n.id,n);const group=[...root.querySelectorAll('[data-svg-node]')].find(g=>g.dataset.svgNode===n.id);group?.setAttribute('transform','translate('+n.x+' '+n.y+')');}updateEdges();return;}
  if(button.hasAttribute('data-graph-rebuild')){void api(base+'rebuild-index',{method:'POST',body:JSON.stringify({expected_revision:data.revision})}).then(result=>say('索引重建完成：'+result.node_count+'节点 / '+result.edge_count+'关系 · '+result.index_sha256)).catch(error=>say(error.message));return;}
  if(button.dataset.graphDecision){const card=button.closest('[data-graph-extraction]');void operation('extract-decide',{extraction_id:card.dataset.graphExtraction,decision:button.dataset.graphDecision,confirm_inference:card.querySelector('[data-graph-inference]').checked},hooks.refresh);return;}
  if(button.dataset.graphPrimary||button.dataset.graphQuote){let source;if(button.dataset.graphPrimary)source=JSON.parse(button.dataset.graphPrimary);else{const e=JSON.parse(button.dataset.graphQuote);source={project_id:project,kind:e.source_kind,entity_id:e.entity_id,chapter_id:e.chapter_id,version_id:e.version_id,workspace_revision:e.source_revision,source_sha256:e.source_sha256};}
   void api(base+'source',{method:'POST',body:JSON.stringify({source})}).then(result=>{const box=root.querySelector('[data-graph-detail]');box.innerHTML='<h4>已保存出处版本 · '+(result.outdated?'现已过期':'来源未变')+'</h4>'+pre(result.value);box.scrollIntoView({block:'nearest'});}).catch(error=>say(error.message));}
 });
}
