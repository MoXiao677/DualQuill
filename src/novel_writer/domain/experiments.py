"""V7同题实验与纯数据扩展；持久身份映射不作为盲评视图。"""
from __future__ import annotations
from novel_writer.domain.sampling import Sampling
from dataclasses import dataclass
from typing import Literal
import json
from novel_writer.domain.tasks import ContextOptions,check_types,parse,encode,require,uuid_value,digest
from novel_writer.domain.models import _timestamp
from novel_writer.domain.model_contract import ModelBinding,validate_model_options
from novel_writer.domain.connections import canonical_messages

SIDES=tuple('ABCDEFGH')
Side=Literal['A','B','C','D','E','F','G','H']

class Value:
    def __post_init__(self):
        check_types(type(self),self)
        if hasattr(self,'id'):uuid_value(self.id)
        if hasattr(self,'created_at'):_timestamp(self.created_at,'experiment.created_at')
        if isinstance(self,Profile):validate_model_options(encode(self))
        elif isinstance(self,PresetSettings):validate_model_options({**{key:value for key,value in encode(self).items() if key not in ('max_output_chars','timeout_ms')},'budget_limit':1.0,'allow_unknown_cost':True})
        elif isinstance(self,ComparisonScore):
            require(len(self.notes)<=4000,'作者评分备注超限')
            if self.outcome=='scored':require(self.rating is not None and 1<=self.rating<=5 and self.candidate_id is not None and self.result_sha256 is not None and self.terminal_status=='succeeded','评分必须绑定已完成的成功候选')
            else:require(self.rating is None and self.candidate_id is None and self.result_sha256 is None and self.terminal_status!='succeeded','无可评分结果不能记为数字败者')
        elif isinstance(self,ReferenceParameters):require(1<=self.max_chars<=20000,'只读预览字符上限非法')
        elif isinstance(self,PresetParameters):require(0<=self.temperature<=2 and 128<=self.max_tokens<=8192 and 128<=self.max_output_chars<=100000 and 100<=self.timeout_ms<=30000,'模板参数超限')
        elif isinstance(self,DataTemplate):
            require(0<len(self.name.strip())<=100 and len(self.description)<=500,'公开模板名称/说明非法')
            require((self.capability,self.permissions,type(self.parameters)) in (('saved-text-reference',('read_saved_source',),ReferenceParameters),('model-request-preset',('prepare_model_request',),PresetParameters)),'模板权限/输入契约与注册能力不符')

@dataclass(frozen=True,kw_only=True)
class Profile(Value):
    adapter_id:Literal['chat-completions-http-v1','configured-http-v2']
    connection_id:str
    model_id:str
    temperature:float
    max_tokens:int
    budget_limit:float
    allow_unknown_cost:bool
    prompt_version:Literal['rewrite-1','review-json-1']
    sampling:Sampling|None=None


@dataclass(frozen=True,kw_only=True)
class Configuration(Value):
    id:str
    index:int
    side:Side
    task_id:str

@dataclass(frozen=True,kw_only=True)
class ComparisonExperiment(Value):
    id:str
    project_id:str
    title:str
    chapter_id:str
    source_revision:int
    context_options:ContextOptions
    context_sha256:str
    instruction:str
    rubric:str
    max_output_chars:int
    timeout_ms:int
    profiles:tuple[Profile,...]
    configurations:tuple[Configuration,...]
    common_messages_sha256:str
    created_at:str

@dataclass(frozen=True,kw_only=True)
class ArenaExperiment(ComparisonExperiment):
    arena_version:Literal[1]
    task_kind:Literal['rewrite_chapter','outline_chapter','audit_chapter']
    planning_options:dict|None
    budget:dict
    price_quotes:tuple[dict|None,...]

@dataclass(frozen=True,kw_only=True)
class StrictArenaExperiment(ArenaExperiment):
    blind_protocol:Literal[2]

DIMENSIONS=('structure','character_consistency','language','intent_alignment')

@dataclass(frozen=True,kw_only=True)
class DimensionScore(Value):
    dimension:Literal['structure','character_consistency','language','intent_alignment']
    rating:int
    reason:str

    def __post_init__(self):
        super().__post_init__()
        require(1<=self.rating<=5 and len(self.reason)<=4000,'维度分数或理由非法')

@dataclass(frozen=True,kw_only=True)
class ComparisonScore(Value):
    id:str
    project_id:str
    experiment_id:str
    side:Side
    rating:int|None
    outcome:Literal['scored','unscorable']
    candidate_id:str|None
    result_sha256:str|None
    terminal_status:Literal['succeeded','failed','cancelled','interrupted']
    notes:str
    created_at:str

@dataclass(frozen=True,kw_only=True)
class DetailedComparisonScore(ComparisonScore):
    dimensions:tuple[DimensionScore,...]

    def __post_init__(self):
        super().__post_init__()
        require((len(self.dimensions)==4 and {d.dimension for d in self.dimensions}==set(DIMENSIONS))
                if self.outcome=='scored' else not self.dimensions,'须填写四个维度，失败侧不可填分')

@dataclass(frozen=True,kw_only=True)
class ComparisonReveal(Value):
    id:str
    project_id:str
    experiment_id:str
    score_ids:tuple[str,...]
    created_at:str

@dataclass(frozen=True,kw_only=True)
class PresetSettings(Value):
    adapter_id:Literal['chat-completions-http-v1','configured-http-v2']
    connection_id:str
    model_id:str
    temperature:float
    max_tokens:int
    prompt_version:Literal['rewrite-1']
    max_output_chars:int
    timeout_ms:int
    sampling:Sampling|None=None


@dataclass(frozen=True,kw_only=True)
class GenerationPreset(Value):
    id:str
    project_id:str
    name:str
    role:Literal['writer']
    experiment_id:str
    side:Side
    settings:PresetSettings
    created_at:str

@dataclass(frozen=True,kw_only=True)
class ComparisonChoice(Value):
    id:str
    project_id:str
    experiment_id:str
    side:Side
    action:Literal['open_candidate','save_preset']
    task_id:str
    candidate_id:str
    preset_id:str|None
    created_at:str

@dataclass(frozen=True,kw_only=True)
class ReferenceParameters(Value):
    source:Literal['current_chapter']
    max_chars:int

@dataclass(frozen=True,kw_only=True)
class PresetParameters(Value):
    role:Literal['writer']
    temperature:float
    max_tokens:int
    max_output_chars:int
    timeout_ms:int
    prompt_version:Literal['rewrite-1']

@dataclass(frozen=True,kw_only=True)
class DataTemplate(Value):
    template_format:Literal[1]
    interface_version:Literal[1]
    name:str
    description:str
    capability:Literal['saved-text-reference','model-request-preset']
    permissions:tuple[Literal['read_saved_source','prepare_model_request'],...]
    parameters:ReferenceParameters|PresetParameters

@dataclass(frozen=True,kw_only=True)
class TemplateVersion(Value):
    id:str
    project_id:str
    operation_id:str
    template_id:str
    revision:int
    previous_version_id:str|None
    template:DataTemplate
    created_at:str

EXPERIMENT_COLLECTIONS={'comparison_experiments':ComparisonExperiment,'comparison_scores':ComparisonScore,'comparison_reveals':ComparisonReveal,'comparison_choices':ComparisonChoice,'generation_presets':GenerationPreset,'extension_templates':TemplateVersion}
TERMINAL={'succeeded','failed','cancelled','interrupted'}
def messages_sha(frozen):
    binding=frozen['parameters']['binding'];protocol=binding.get('destination',{}).get('protocol','openai-chat')
    return digest(json.dumps(canonical_messages(json.loads(binding['request_body']),protocol),ensure_ascii=False,sort_keys=True,separators=(',',':')))
def common_instruction(instruction,rubric):return instruction+'\n\n共同评价要求：\n'+rubric

def parse_experiment(value):
    if value.get('trial_kind')=='writing_candidates':
        from novel_writer.domain.writing_comparisons import WritingExperiment
        return parse(WritingExperiment,value)
    if 'arena_version' in value:return parse(StrictArenaExperiment if 'blind_protocol' in value else ArenaExperiment,value)
    if value.get('trial_kind')=='style_trial':
        from novel_writer.domain.style_trials import TrialExperiment
        return parse(TrialExperiment,value)
    return parse(ComparisonExperiment,value)

def arena_records(state):
    from novel_writer.domain.style_trials import arena_tasks,arena_candidates,arena_results
    from novel_writer.domain.arena import additional_records
    from novel_writer.domain.writing_comparisons import records
    tasks,candidates,results=additional_records(state,arena_tasks(state),arena_candidates(state),arena_results(state))
    writing_tasks,writing_candidates,writing_results=records(state)
    tasks.update(writing_tasks)
    return tasks,list({v['id']:v for v in candidates+writing_candidates}.values()),list({v['id']:v for v in results+writing_results}.values())

def validate_experiment_state(state):
    project=state['document']['project']['id'];parsed={}
    for name,model in EXPERIMENT_COLLECTIONS.items():
        require(type(state[name]) is list and len(state[name])<=100000,'实验/模板集合非法或超限');parsed[name]=[parse_experiment(v) if name=="comparison_experiments" else parse(DetailedComparisonScore if name=='comparison_scores' and 'dimensions' in v else model,v) for v in state[name]];require(len({v.id for v in parsed[name]})==len(parsed[name]),'实验/模板ID重复')
        for v in parsed[name]:require(v.project_id==project,'实验/模板跨书')
    tasks,all_candidates,_=arena_records(state);experiments={e.id:e for e in parsed['comparison_experiments']};scores={s.id:s for s in parsed['comparison_scores']};reveals={r.experiment_id:r for r in parsed['comparison_reveals']};presets={p.id:p for p in parsed['generation_presets']}
    require(len(reveals)==len(parsed['comparison_reveals']),'实验不能重复揭晓')
    children=set()
    for e in experiments.values():
        if getattr(e,'trial_kind',None)=='writing_candidates':
            from novel_writer.domain.writing_comparisons import validate_experiment
            validate_experiment(e,state,children);continue
        if getattr(e,'trial_kind',None)=='style_trial':
            from novel_writer.domain.style_trials import validate_trial_experiment
            validate_trial_experiment(e,state,children);continue
        if isinstance(e,ArenaExperiment):
            from novel_writer.domain.arena import validate_arena_experiment
            validate_arena_experiment(e,state,children);continue
        if any(profile.adapter_id=='configured-http-v2' for profile in e.profiles):require(state['workspace_version']>=9,'配置协议实验须使用V9或更新工作区')
        require(0<len(e.title.strip())<=300 and 0<len(e.rubric.strip())<=2000 and len(e.instruction)<=2000 and 1<=e.source_revision<=state['revision'],'实验输入超限/保存编号非法')
        require(len(e.profiles)==len(e.configurations)==2 and {c.index for c in e.configurations}=={0,1} and {c.side for c in e.configurations}=={'A','B'},'实验须有两个独立配置及盲评侧')
        common=None
        for c in e.configurations:
            require(c.task_id in tasks and c.task_id not in children,'实验任务悬空/复用');children.add(c.task_id);t=tasks[c.task_id];f=t['frozen'];require(t['task_type']=='rewrite_chapter' and t['chapter_id']==e.chapter_id and f['source_revision']==e.source_revision,'实验任务能力/原稿保存编号不符')
            p=dict(f['parameters']);binding=p.pop('binding',None);require(binding is not None and {k:v for k,v in binding.items() if k not in ('request_body','request_sha256','destination')}==encode(e.profiles[c.index]),'实验配置冻结不符')
            snapshot=dict(f,parameters=p);require(common is None or common==snapshot,'两个实验任务的原稿/上下文/规则不一致');common=snapshot
            require(p==dict(instruction=common_instruction(e.instruction,e.rubric),max_output_chars=e.max_output_chars,timeout_ms=e.timeout_ms) and f['context_options']==encode(e.context_options) and f['context_sha256']==e.context_sha256,'实验评价要求/参数/上下文不符')
            require(messages_sha(f)==e.common_messages_sha256 and any(d['kind']=='writing_rules' for d in f['dependencies']),'实验共同消息/写作规则未冻结')
    candidates={c['id']:c for c in all_candidates}
    for s in scores.values():
        require(s.experiment_id in experiments,'评分实验悬空');e=experiments[s.experiment_id];slot=next((c for c in e.configurations if c.side==s.side),None);require(slot is not None,'评分配置不属于实验');t=tasks[slot.task_id]
        if isinstance(e,StrictArenaExperiment):
            require(isinstance(s,DetailedComparisonScore),'严格盲评必须保留四维评价')
            require(sum(v.experiment_id==s.experiment_id and v.side==s.side for v in scores.values())==1,'严格盲评同侧只能封存一次评分')
        require(t['status'] in TERMINAL and s.terminal_status==t['status'],'评分不能绑定未终态任务')
        if t['status']=='succeeded':require(s.outcome=='scored' and s.candidate_id==t['candidate_id'] and s.candidate_id in candidates and s.result_sha256==digest(candidates[s.candidate_id]['output_text']),'评分没有绑定当时的实际成功候选')
        else:require(s.outcome=='unscorable' and s.rating is None,'失败/取消侧必须明确无可评分结果')
    for r in reveals.values():
        require(r.experiment_id in experiments,'揭晓实验悬空');sides={c.side for c in experiments[r.experiment_id].configurations}
        require(len(r.score_ids)==len(sides) and set(r.score_ids)<=set(scores),'揭晓须引用全部配置评分');owned=[scores[i] for i in r.score_ids];require({s.side for s in owned}==sides and all(s.experiment_id==r.experiment_id for s in owned),'揭晓评分归属不符')
        require(all(tasks[c.task_id]['status'] in TERMINAL for c in experiments[r.experiment_id].configurations),'两任务未终态不能揭晓')
    for p in presets.values():require(p.experiment_id in reveals and bool(p.name.strip()),'预设须源自已揭晓实验')
    for c in parsed['comparison_choices']:
        require(c.experiment_id in reveals,'未揭晓不能选胜者');e=experiments[c.experiment_id];slot=next((s for s in e.configurations if s.side==c.side),None);require(slot is not None,'胜者配置不属于实验');t=tasks[slot.task_id]
        require(c.task_id==slot.task_id and t['status']=='succeeded' and c.candidate_id==t['candidate_id'],'胜者不是该侧完成候选')
        require((c.action=='open_candidate' and c.preset_id is None) or (c.action=='save_preset' and c.preset_id in presets),'胜者操作/预设不符')
    previous={};counts={};operations=set()
    for v in parsed['extension_templates']:
        uuid_value(v.operation_id);uuid_value(v.template_id);require(v.operation_id not in operations,'模板操作身份重复');operations.add(v.operation_id)
        require(v.revision==counts.get(v.template_id,0)+1 and v.previous_version_id==previous.get(v.template_id),'模板版本链不连续');counts[v.template_id]=v.revision;previous[v.template_id]=v.id

def validate_experiment_transition(state,previous):
    previous=previous or {}
    for name in EXPERIMENT_COLLECTIONS:require(state[name][:len(previous.get(name,[]))]==previous.get(name,[]),'实验评分/映射/揭晓/模板历史不可改写')
    experiments={e['id']:e for e in previous.get('comparison_experiments',[])};tasks,previous_candidates,_=arena_records(previous);old_reveals={r['experiment_id'] for r in previous.get('comparison_reveals',[])}
    for e in state['comparison_experiments'][len(experiments):]:
        if e.get('trial_kind')=='writing_candidates':require(all(c['task_id'] in tasks and tasks[c['task_id']]['status']=='pending' for c in e['configurations']),'多候选编组只接受此前已保存且尚未发送的冻结任务')
    for s in state['comparison_scores'][len(previous.get('comparison_scores',[])):]:
        require(s['experiment_id'] in experiments and s['experiment_id'] not in old_reveals,'盲评分须引用此前保存且未揭晓实验')
        if experiments[s['experiment_id']].get('blind_protocol')!=2:require(all(tasks[c['task_id']]['status'] in TERMINAL for c in experiments[s['experiment_id']]['configurations']),'两个配置尚未结束，不能盲评')
        e=experiments[s['experiment_id']];slot=next(c for c in e['configurations'] if c['side']==s['side']);t=tasks[slot['task_id']];require(t['status']==s['terminal_status'],'评分终态与此前保存结果不符')
        if s['outcome']=='scored':require(t['status']=='succeeded' and t['candidate_id']==s['candidate_id'] and any(c['id']==s['candidate_id'] and digest(c['output_text'])==s['result_sha256'] for c in previous_candidates),'评分须绑定此前已保存的成功候选')
        else:require(t['status']!='succeeded' and s['rating'] is None,'失败评价不能记为数字分')
    for r in state['comparison_reveals'][len(previous.get('comparison_reveals',[])):]:
        latest={s['side']:s['id'] for s in previous.get('comparison_scores',[]) if s['experiment_id']==r['experiment_id']};require(set(latest)=={c['side'] for c in experiments[r['experiment_id']]['configurations']} and set(r['score_ids'])==set(latest.values()),'揭晓须引用此前保存的全部最新盲评分')
        require(all(tasks[c['task_id']]['status'] in TERMINAL for c in experiments[r['experiment_id']]['configurations']),'揭晓前两个任务必须终态')
    for c in state['comparison_choices'][len(previous.get('comparison_choices',[])):]:require(c['experiment_id'] in old_reveals,'选胜者必须在此前揭晓后显式操作')
