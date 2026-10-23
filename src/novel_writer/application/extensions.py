"""注册接口/权限下的纯数据模板。不会加载导入文件中的代码。"""
from copy import deepcopy
from uuid import uuid4
from novel_writer.domain.experiments import *
from novel_writer.domain.memory import capture_source
from novel_writer.domain.models import utc_now
from novel_writer.application.fields import check_fields

class SavedTextReferenceAdapter:
    adapter_id='reference-saved-text-v1'
    interface_version=1
    permissions=('read_saved_source',)
    def preview(self,state,chapter_id,parameters):
        require(type(parameters) is ReferenceParameters,'参考适配器只接受已验证的只读参数');chapter=next((c for c in state['document']['chapters'] if c['id']==chapter_id),None);require(chapter is not None,'原稿不属于当前书')
        return dict(interface_version=1,adapter_id=self.adapter_id,read_only=True,source=capture_source(state,dict(kind='chapter',entity_id=chapter_id)),text=chapter['content'][:parameters.max_chars],truncated=len(chapter['content'])>parameters.max_chars)

class ExtensionRegistry:
    def __init__(self):self.capabilities={'saved-text-reference':dict(version=1,permissions=('read_saved_source',),adapter=SavedTextReferenceAdapter()),'model-request-preset':dict(version=1,permissions=('prepare_model_request',),adapter=None)}
    def validate(self,spec):
        require(spec.capability in self.capabilities,'扩展能力未注册');registered=self.capabilities[spec.capability];require(spec.interface_version==registered['version'] and spec.permissions==registered['permissions'],'扩展接口版本/权限不兼容');return registered

def preflight(raw):
    spec=parse(DataTemplate,raw);ExtensionRegistry().validate(spec)
    return dict(compatible=True,template=encode(spec),permissions=list(spec.permissions),execution='read_only_reference' if spec.capability=='saved-text-reference' else 'data_defaults_only_requires_runtime_connection_and_single_confirmation',contains_project_data=False,code_loaded=False,default_enabled=False,requires_local_authorization=True)

def upgrade(state):
    from novel_writer.application.model_reviews import upgrade as model_upgrade
    model_upgrade(state);state['workspace_version']=max(state['workspace_version'],7)
    for name in EXPERIMENT_COLLECTIONS:state.setdefault(name,[])

def import_template(service,project_id,request):
    check_fields(request,{'operation_id','expected_revision','template','template_id'});require(set(request)=={'operation_id','expected_revision','template','template_id'},'模板导入字段缺失');identity=uuid_value(request['operation_id']);spec=parse(DataTemplate,preflight(request['template'])['template'])
    def apply(state):
        old=next((v for v in state.get('extension_templates',[]) if v['operation_id']==identity),None)
        if old:
            require(old['template']==encode(spec) and (request['template_id'] is None or old['template_id']==request['template_id']),'同一模板身份绑定不同版本');return None,dict(template_id=old['template_id'],version_id=old['id'],revision=old['revision'])
        require(type(request['expected_revision']) is int and request['expected_revision']==state['revision'],'保存编号变化，请保留模板并刷新');upgrade(state);previous=None;tid=request['template_id']
        if tid is not None:uuid_value(tid);previous=next((v for v in reversed(state['extension_templates']) if v['template_id']==tid),None);require(previous is not None,'模板不属于当前书')
        else:tid=str(uuid4())
        version=TemplateVersion(id=str(uuid4()),project_id=project_id,operation_id=identity,template_id=tid,revision=previous['revision']+1 if previous else 1,previous_version_id=previous['id'] if previous else None,template=spec,created_at=utc_now());state['extension_templates'].append(encode(version));return state,dict(template_id=tid,version_id=version.id,revision=version.revision)
    return service.repository.atomic(project_id,apply,identity_claim=('extension_templates','operation_id',identity))

def export_template(service,project_id,version_id):
    state=service.get(project_id);record=next((v for v in state.get('extension_templates',[]) if v['id']==version_id),None);require(record is not None,'模板版本不属于当前书');return deepcopy(record['template'])

def reference_preview(service,project_id,request):
    from novel_writer.application.extension_policy import policy_for
    check_fields(request,{'version_id','chapter_id'});state=service.get(project_id);record=next((v for v in state.get('extension_templates',[]) if v['id']==request.get('version_id')),None);require(record is not None,'模板版本不属于当前书')
    require(next(v for v in reversed(state['extension_templates']) if v['template_id']==record['template_id'])['id']==record['id'],'旧模板版本已被升级替代')
    spec=parse(DataTemplate,record['template']);registry=ExtensionRegistry();registered=registry.validate(spec)
    authorization=policy_for(service).status(project_id,record)
    require(authorization['enabled'] and authorization['permissions']==list(spec.permissions),'扩展未启用或能力未获本机明确授权')
    require(registered['adapter'] is not None,'模型预设只提供数据默认值，不执行生成或授予权限');return registered['adapter'].preview(state,request.get('chapter_id'),spec.parameters)
