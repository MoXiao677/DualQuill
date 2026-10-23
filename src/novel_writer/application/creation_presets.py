"""Versioned step bindings reuse repository snapshots, backup and explicit selection."""
from copy import deepcopy
from uuid import uuid4
from novel_writer.application.fields import check_fields
from novel_writer.domain.creation_presets import Settings,PresetVersion,PresetChoice,CREATION_COLLECTIONS
from novel_writer.domain.tasks import parse,encode,require,uuid_value
from novel_writer.domain.models import utc_now
from novel_writer.storage.sqlite_repository import ConflictError

def upgrade(state):
    from novel_writer.application.workflows import upgrade as previous
    previous(state);state['workspace_version']=max(state['workspace_version'],10)
    for name in CREATION_COLLECTIONS:state.setdefault(name,[])

def settings(raw):
    require(type(raw) is dict,'创作设置必须是对象');value=deepcopy(raw)
    if type(value.get('steps')) is list:
        for step in value['steps']:
            if type(step) is not dict:raise ValueError('步骤设置必须是对象')
            for name in ('temperature','budget_limit'):
                require(type(step.get(name)) in (int,float),'步骤温度/风险预算必须为数字');step[name]=float(step[name])
    budget=value.get('budget')
    if type(budget) is dict and budget.get('risk_budget') is not None:
        require(type(budget['risk_budget']) in (int,float),'风险预算须为数字或未知');budget['risk_budget']=float(budget['risk_budget'])
    return parse(Settings,value)

class CreationPresets:
    def __init__(self,service):self.service,self.repository=service,service.repository
    def describe(self,project):
        state=self.service.get(project);choices=state.get('creation_preset_choices',[])
        return dict(versions=deepcopy(state.get('creation_presets',[])),selected_version_id=choices[-1]['version_id'] if choices else None,revision=state['revision'])
    def library(self):
        result=[]
        for project in self.service.list_projects():
            for version in self.describe(project['id'])['versions']:result.append(dict(project_id=project['id'],project_title=project['title'],version_id=version['id'],name=version['name'],revision=version['revision']))
        return result
    def _version(self,project,identifier):
        value=next((value for value in self.describe(project)['versions'] if value['id']==uuid_value(identifier)),None);require(value is not None,'创作预设版本不存在或不属于当前书');return value
    def save(self,project,request):
        check_fields(request,{'operation_id','preset_id','name','settings','expected_revision'});require(set(request)=={'operation_id','preset_id','name','settings','expected_revision'},'预设保存字段缺失')
        identity=uuid_value(request['operation_id']);selected=settings(request['settings'])
        if request['preset_id'] is not None:uuid_value(request['preset_id'])
        def operation(state):
            existing=next((value for value in state.get('creation_presets',[]) if value['operation_id']==identity),None)
            if existing:
                require(existing['name']==request['name'] and existing['settings']==encode(selected) and (request['preset_id']==existing['preset_id'] or request['preset_id'] is None and existing['revision']==1),'同一预设保存身份绑定了其他内容')
                return None,dict(version_id=existing['id'],preset_id=existing['preset_id'])
            if type(request['expected_revision']) is not int or state['revision']!=request['expected_revision']:raise ConflictError('资料已变化，请保留预设输入并重新核对')
            upgrade(state);family=request['preset_id'] or str(uuid4());previous=next((value for value in reversed(state['creation_presets']) if value['preset_id']==family),None)
            require(request['preset_id'] is None or previous is not None,'要编辑的预设不属于当前书')
            record=PresetVersion(id=str(uuid4()),project_id=project,operation_id=identity,preset_id=family,revision=previous['revision']+1 if previous else 1,previous_version_id=previous['id'] if previous else None,name=request['name'],settings=selected,created_at=utc_now())
            state['creation_presets'].append(encode(record));return state,dict(version_id=record.id,preset_id=record.preset_id)
        return self.repository.atomic(project,operation,identity_claim=('creation_presets','operation_id',identity))
    def choose(self,project,request):
        required={'operation_id','version_id','confirmed','expected_revision'};check_fields(request,required);require(set(request)==required and request['confirmed'] is True,'应用预设须明确确认；不会授权外发或改写正文')
        identity=uuid_value(request['operation_id']);version=uuid_value(request['version_id'])
        def operation(state):
            existing=next((value for value in state.get('creation_preset_choices',[]) if value['operation_id']==identity),None)
            if existing:require(existing['version_id']==version,'同一选择身份绑定其他预设');return None,existing
            if type(request['expected_revision']) is not int or state['revision']!=request['expected_revision']:raise ConflictError('资料变化，请重新选择预设')
            require(any(value['id']==version for value in state.get('creation_presets',[])),'预设版本不属于当前书');upgrade(state)
            choice=PresetChoice(id=str(uuid4()),project_id=project,operation_id=identity,version_id=version,created_at=utc_now());state['creation_preset_choices'].append(encode(choice));return state,encode(choice)
        return self.repository.atomic(project,operation,identity_claim=('creation_preset_choices','operation_id',identity))
    def reuse(self,project,request):
        required={'operation_id','source_project_id','version_id','expected_revision'};check_fields(request,required);require(set(request)==required,'跨书复用参数缺失')
        source=self._version(request['source_project_id'],request['version_id'])
        return self.save(project,dict(operation_id=request['operation_id'],preset_id=None,name=source['name'],settings=source['settings'],expected_revision=request['expected_revision']))
    def export(self,project,identifier):
        value=self._version(project,identifier);public=deepcopy(value['settings'])
        for step in public['steps']:step['connection_id']=None
        public['style_id']=None
        from novel_writer.domain.sampling import contains,contains_native
        return dict(creation_preset_format=3 if contains_native(public) else 2 if contains(public) else 1,name=value['name'],settings=public)
    def import_preset(self,project,request):
        required={'operation_id','preset','expected_revision'};check_fields(request,required);require(set(request)==required,'导入预设参数缺失');public=request['preset']
        from novel_writer.domain.sampling import contains,contains_native
        require(type(public) is dict and set(public)=={'creation_preset_format','name','settings'} and type(public['creation_preset_format']) is int and public['creation_preset_format'] in (1,2,3),'不是受支持的纯数据创作预设')
        require(public['creation_preset_format']>=2 or not contains(public),'采样参数需要创作预设格式2')
        require(public['creation_preset_format']>=3 or not contains_native(public),'原生请求配置需要创作预设格式3')
        selected=settings(public['settings']);require(all(step.connection_id is None for step in selected.steps) and selected.style_id is None,'共享预设不能夹带私有配置或文风身份，请显式重新绑定')
        return self.save(project,dict(operation_id=request['operation_id'],preset_id=None,name=public['name'],settings=encode(selected),expected_revision=request['expected_revision']))
    def preflight(self,project,identifier,*,connections):
        version=self._version(project,identifier);missing=[]
        for step in version['settings']['steps']:
            current=connections.get(step['connection_id'])
            if current is None or not step['model_id'] or current.get('model_id')!=step['model_id']:missing.append(step['step'])
        missing_style=version['settings']['style_id'] is not None and not any(v['id']==version['settings']['style_id'] for v in self.service.get(project).get('style_cards',[]))
        return dict(ready=not missing and not missing_style,missing_steps=missing,missing_style=missing_style,note='偏好不会授权模型请求；缺失的模型/文风须补配，不会自动替换。')
