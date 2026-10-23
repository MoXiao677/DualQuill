"""V10 author preferences. These records grant neither network nor writing permission."""
from novel_writer.domain.sampling import Sampling
from dataclasses import dataclass
from typing import Literal
import math
from novel_writer.domain.tasks import check_types,parse,require,uuid_value,encode
from novel_writer.domain.models import _timestamp
from novel_writer.domain.model_contract import validate_model_options

STEPS=('brainstorm','outline','draft','audit','rewrite','style_analysis','style_trial','search')
class Value:
    def __post_init__(self):
        check_types(type(self),self)
        if hasattr(self,'id'):uuid_value(self.id);require(type(self.project_id) is str and bool(self.project_id.strip()),'预设项目身份非法');uuid_value(self.operation_id);_timestamp(self.created_at,'creation_preset.created_at')
        if isinstance(self,StepBinding):
            require(self.step in STEPS and len(self.model_id)<=200 and all(ord(c)>=32 for c in self.model_id),'步骤或模型编号非法')
            if self.connection_id is not None:
                value=encode(self);value.pop('step');value['allow_unknown_cost']=True;value['prompt_version']='rewrite-1';validate_model_options(value)
            require(math.isfinite(self.temperature) and 0<=self.temperature<=2 and 128<=self.max_tokens<=8192 and math.isfinite(self.budget_limit) and 0<self.budget_limit<=10000,'步骤模型偏好上限非法')
        elif isinstance(self,Budget):require(0<=self.max_external_calls<=10 and 0<=self.max_reserved_output_tokens<=81920 and (self.risk_budget is None or math.isfinite(self.risk_budget) and 0<self.risk_budget<=10000),'创作预算偏好非法')
        elif isinstance(self,Settings):
            require(1<=len(self.steps)<=len(STEPS) and len({step.step for step in self.steps})==len(self.steps),'步骤绑定为空、重复或超限')
            require(len(self.style_prompt)<=8000 and 0<len(self.manuscript_language.strip())<=100,'文风提示或正文语言非法')
            if self.style_id is not None:uuid_value(self.style_id)
        elif isinstance(self,PresetVersion):
            uuid_value(self.preset_id);require(self.revision>=1 and 0<len(self.name.strip())<=100,'创作预设版本或名称非法')
            if self.previous_version_id is not None:uuid_value(self.previous_version_id)
        elif isinstance(self,PresetChoice):uuid_value(self.version_id)

@dataclass(frozen=True,kw_only=True)
class StepBinding(Value):
    step:Literal['brainstorm','outline','draft','audit','rewrite','style_analysis','style_trial','search']
    adapter_id:Literal['chat-completions-http-v1','configured-http-v2']
    connection_id:str|None
    model_id:str
    temperature:float
    max_tokens:int
    budget_limit:float
    allow_unknown_cost:bool
    sampling:Sampling|None=None


@dataclass(frozen=True,kw_only=True)
class Budget(Value):
    max_external_calls:int
    max_reserved_output_tokens:int
    risk_budget:float|None
    allow_unknown_cost:bool

@dataclass(frozen=True,kw_only=True)
class Settings(Value):
    steps:tuple[StepBinding,...]
    style_id:str|None
    style_prompt:str
    manuscript_language:str
    budget:Budget

@dataclass(frozen=True,kw_only=True)
class PresetVersion(Value):
    id:str
    project_id:str
    operation_id:str
    preset_id:str
    revision:int
    previous_version_id:str|None
    name:str
    settings:Settings
    created_at:str

@dataclass(frozen=True,kw_only=True)
class PresetChoice(Value):
    id:str
    project_id:str
    operation_id:str
    version_id:str
    created_at:str

CREATION_COLLECTIONS={'creation_presets':PresetVersion,'creation_preset_choices':PresetChoice}
def validate_creation_state(state):
    project=state['document']['project']['id'];versions={};families={}
    for name,model in CREATION_COLLECTIONS.items():
        require(type(state[name]) is list and len(state[name])<=10000,'创作预设集合非法或超限');seen=set();operations=set()
        for raw in state[name]:
            value=parse(model,raw);require(value.id not in seen and value.operation_id not in operations and value.project_id==project,'预设身份重复或跨书');seen.add(value.id);operations.add(value.operation_id)
            if name=='creation_presets':
                previous=families.get(value.preset_id);require((value.revision,value.previous_version_id)==((previous.revision+1,previous.id) if previous else (1,None)),'预设历史链不连续');families[value.preset_id]=value;versions[value.id]=value
            else:require(value.version_id in versions,'所选创作预设版本不存在')

def validate_creation_transition(state,previous):
    previous=previous or {}
    for name in CREATION_COLLECTIONS:
        old=previous.get(name,[]);require(state[name][:len(old)]==old,'创作预设版本和选择历史只能追加，不能覆盖或删除')
