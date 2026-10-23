"""Explicit local TXT/Markdown material library, versions, and derived literal index."""
import base64,hashlib,json
from uuid import NAMESPACE_URL,uuid5

from novel_writer.application.fields import check_fields
from novel_writer.domain.materials import (
    ACTIONS,COLLECTIONS,FORMATS,MAX_TAGS,MAX_TAG_CHARS,MAX_TEXT_CHARS,
    Material,MaterialChunk,MaterialOperation,MaterialVersion,chunk_ranges,current_version,index_status,index_version_id,material_chunks,
)
from novel_writer.domain.models import utc_now
from novel_writer.domain.tasks import digest,require,uuid_value
from novel_writer.storage.content_blobs import MAX_BYTES
from novel_writer.storage.sqlite_repository import ConflictError

REQUEST_FIELDS={'operation_id','expected_revision','title','format','tags','text','data_base64','note'}


def upgrade(state):
    from novel_writer.application.console import upgrade_runs as previous
    previous(state);state['workspace_version']=max(state['workspace_version'],25)
    for name in COLLECTIONS:state.setdefault(name,[])
    return state


def _uid(operation,suffix):
    return str(uuid5(NAMESPACE_URL,'novel-writer/materials/1/'+operation+'/'+suffix))


def _hash(request):
    semantic={key:value for key,value in request.items() if key not in ('operation_id','expected_revision')}
    raw=json.dumps(semantic,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf8')
    return hashlib.sha256(raw).hexdigest()


def _record(value):
    return {key:getattr(value,key) for key in value.__dataclass_fields__}


def _revision(request):
    value=request.get('expected_revision')
    require(type(value) is int and value>=1,'materials.invalid_revision')
    return value


def _tags(value):
    require(type(value) is list and len(value)<=MAX_TAGS,'materials.invalid_tags')
    result=[]
    for item in value:
        require(type(item) is str,'materials.invalid_tags')
        tag=item.strip()
        require(0<len(tag)<=MAX_TAG_CHARS and not any(ord(char)<32 or ord(char)==127 for char in tag),'materials.invalid_tags')
        if tag not in result:result.append(tag)
    return tuple(result)


def _text(request):
    has_text='text' in request;has_file='data_base64' in request
    require(has_text!=has_file,'materials.text_source_required')
    if has_text:
        value=request['text'];require(type(value) is str,'materials.invalid_text')
        try:raw=value.encode('utf8',errors='strict')
        except UnicodeError:raise ValueError('materials.invalid_text') from None
    else:
        value=request['data_base64'];require(type(value) is str and len(value)<=((MAX_BYTES+2)//3)*4,'materials.invalid_bytes')
        try:raw=base64.b64decode(value,validate=True)
        except (ValueError,TypeError):raise ValueError('materials.invalid_bytes') from None
        require(0<len(raw)<=MAX_BYTES,'materials.invalid_bytes')
        try:value=raw.decode('utf-8-sig')
        except UnicodeError:raise ValueError('materials.invalid_text') from None
    require(0<len(value)<=MAX_TEXT_CHARS and bool(value.strip()) and len(raw)<=MAX_BYTES,'materials.invalid_text')
    require(not any(ord(char)==0 or (ord(char)<32 and char not in '\n\r\t') or ord(char)==127 for char in value),'materials.invalid_text')
    return value


def _metadata(request):
    check_fields(request,REQUEST_FIELDS)
    identity=uuid_value(request.get('operation_id'));revision=_revision(request)
    title=request.get('title');require(type(title) is str and 0<len(title.strip())<=200 and not any(ord(char)<32 or ord(char)==127 for char in title.strip()),'materials.invalid_title')
    format_=request.get('format');require(format_ in FORMATS,'materials.invalid_format')
    tags=_tags(request.get('tags'));note=request.get('note','');require(type(note) is str and len(note)<=1000 and '\x00' not in note,'materials.invalid_note')
    return identity,revision,title.strip(),format_,tags,note


def _material_view(state,material):
    versions=sorted((value for value in state['material_versions'] if value['material_id']==material['id']),key=lambda value:value['version_number'])
    current=next(value for value in versions if value['id']==material['current_version_id'])
    chunks=material_chunks(state,material['id'],current['id'])
    return dict(material,version_count=len(versions),current_version_number=current['version_number'],current_text_sha256=current['text_sha256'],
        char_count=len(current['text']),index_status=index_status(state,material),index_version_id=index_version_id(state,material),chunk_count=len(chunks))


def _detail(state,material_id,revision=None):
    material=next((value for value in state['materials'] if value['id']==material_id),None)
    if material is None:raise KeyError('资料不存在')
    versions=sorted((value for value in state['material_versions'] if value['material_id']==material_id),key=lambda value:value['version_number'])
    chunks=sorted((value for value in state['material_chunks'] if value['material_id']==material_id),key=lambda value:(value['material_version_id'],value['ordinal']))
    return dict(revision=state['revision'] if revision is None else revision,material=_material_view(state,material),
        versions=[{key:value[key] for key in ('id','version_number','text_sha256','note','created_at','previous_version_id')}|dict(char_count=len(value['text'])) for value in versions],
        chunks=[{key:value[key] for key in ('id','material_version_id','ordinal','start','end','text_sha256')} for value in chunks],
        method='资料索引仅为固定字符窗口和SHA256字面定位，不是语义检索或向量索引',model_request_sent=False)


def _summary(state,material):
    return _material_view(state,material)


class Materials:
    def __init__(self,service):
        self.service,self.repository=service,service.repository
        from novel_writer.application.material_index_jobs import MaterialIndexJobs
        self.index_jobs=MaterialIndexJobs(self)

    def suggest_tags(self,project,material_id,request):
        """Read-only literal suggestions with exact evidence; authors save tags."""
        check_fields(request,set())
        from collections import Counter
        import re
        from novel_writer.application.lexical_rank import terms,normalized_spans
        state=self.service.get(project);material=self._material(state,material_id)
        require(not material['archived'],'materials.archived_cannot_suggest')
        version=current_version(state,material);body=version['text'];sample=body[:200000];normal,spans=normalized_spans(sample)
        tokens=terms(normal);counts=Counter(t[0] for t in tokens);candidates=[];seen=set()
        for match in re.finditer(r'(?m)^[ \t]*#{1,6}[ \t]+([^\r\n]{2,40})',sample):
            raw=match.group(1);tag=raw.strip()
            if len(tag)<2:continue
            start=match.start(1)+len(raw)-len(raw.lstrip())
            candidates.append((tag,start,start+len(tag),'markdown_heading'))
        for term,start,end in sorted(tokens,key=lambda t:(-counts[t[0]],t[1])):
            if len(term)<2 or counts[term]<2:continue
            a,b=spans[start][0],spans[end-1][1];tag=body[a:b]
            if len(tag)<=40:candidates.append((tag,a,b,'repeated_lexical_term'))
        result=[]
        for tag,start,end,method in candidates:
            if tag in seen or tag in material['tags'] or any(ord(c)<32 for c in tag):continue
            seen.add(tag);result.append(dict(tag=tag,method=method,version_id=version['id'],source_sha256=version['text_sha256'],
                start=start,end=end,sha256=digest(body[start:end]),evidence=body[start:end]))
            if len(result)==10:break
        return dict(project_id=project,material_id=material_id,revision=state['revision'],version_id=version['id'],suggestions=result,
            requires_manual_save=True,model_request_sent=False,method='literal_tag_suggestions_v1',scanned_chars=len(sample),truncated=len(sample)<len(body))

    def _material(self,state,material_id):
        material=next((value for value in state.get('materials',[]) if value['id']==material_id),None)
        if material is None:raise KeyError('资料不存在')
        return material

    def _replay(self,state,identity,action,request_hash,material_id=None):
        old=next((value for value in state.get('material_operations',[]) if value['operation_id']==identity),None)
        if old is None:return None
        require(old['action']==action and old['request_sha256']==request_hash and (material_id is None or old['material_id']==material_id),'materials.operation_conflict')
        return old

    def _check(self,state,revision):
        if state['revision']!=revision:raise ConflictError('小说已在其他窗口更新，请重新读取资料后再操作')

    def listing(self,project,tag=None,include_archived=True):
        state=self.service.get(project);upgrade(state)
        require(type(include_archived) is bool,'materials.invalid_filter')
        if tag is not None:require(type(tag) is str and len(tag.strip())<=MAX_TAG_CHARS,'materials.invalid_filter');tag=tag.strip()
        materials=[value for value in state['materials'] if (include_archived or not value['archived']) and (tag is None or tag in value['tags'])]
        materials.sort(key=lambda value:(value['updated_at'],value['title'],value['id']),reverse=True)
        materials.sort(key=lambda value:value['archived'])
        tags=sorted({item for value in state['materials'] for item in value['tags']})
        return dict(revision=state['revision'],materials=[_summary(state,value) for value in materials],tags=tags,
            method='本地TXT/Markdown资料；分块仅作字面定位，不是语义检索',model_request_sent=False)

    def describe(self,project,material_id):
        state=self.service.get(project);upgrade(state)
        return _detail(state,material_id)

    def version(self,project,material_id,version_id):
        state=self.service.get(project);upgrade(state);material=self._material(state,material_id);uuid_value(version_id)
        version=next((value for value in state['material_versions'] if value['id']==version_id and value['material_id']==material_id),None)
        if version is None:raise KeyError('资料版本不存在')
        return dict(revision=state['revision'],material_id=material_id,material_title=material['title'],
            version_number=version['version_number'],version_id=version['id'],text=version['text'],text_sha256=version['text_sha256'],
            note=version['note'],created_at=version['created_at'],previous_version_id=version['previous_version_id'],char_count=len(version['text']))

    def create(self,project,request):
        identity,revision,title,format_,tags,note=_metadata(request);text=_text(request);request_hash=_hash(request)
        material_id=_uid(identity,'material');version_id=_uid(identity,'version')
        def operation(state):
            upgrade(state);old=self._replay(state,identity,'create',request_hash,material_id)
            if old:return None,_detail(state,material_id)
            self._check(state,revision)
            require(all(value['id']!=material_id for value in state['materials']),'materials.identity_conflict')
            now=utc_now()
            material=Material(id=material_id,project_id=project,title=title,format=format_,tags=tags,archived=False,current_version_id=version_id,revision=1,created_at=now,updated_at=now)
            version=MaterialVersion(id=version_id,project_id=project,material_id=material_id,version_number=1,text=text,text_sha256=digest(text),note=note,created_at=now,previous_version_id=None)
            record=MaterialOperation(id=_uid(identity,'operation'),project_id=project,material_id=material_id,operation_id=identity,action='create',expected_revision=revision,version_id=version_id,request_sha256=request_hash,created_at=now)
            state['materials'].append(_record(material))
            state['material_versions'].append(_record(version))
            state['material_operations'].append(_record(record))
            return state,_detail(state,material_id,state['revision']+1)
        return self.repository.atomic(project,operation,identity_claim=('material_operations','operation_id',identity))

    def update(self,project,material_id,request):
        identity,revision,title,format_,tags,note=_metadata(request);text=_text(request);request_hash=_hash(request);uuid_value(material_id)
        version_id=_uid(identity,'version')
        def operation(state):
            upgrade(state);material=self._material(state,material_id);old=self._replay(state,identity,'update',request_hash,material_id)
            if old:return None,_detail(state,material_id)
            self._check(state,revision);require(not material['archived'],'materials.archived_cannot_update')
            versions=[value for value in state['material_versions'] if value['material_id']==material_id]
            previous=next(value for value in versions if value['id']==material['current_version_id']);number=max(value['version_number'] for value in versions)+1
            require(all(value['id']!=version_id for value in state['material_versions']),'materials.identity_conflict')
            now=utc_now();version=MaterialVersion(id=version_id,project_id=project,material_id=material_id,version_number=number,text=text,text_sha256=digest(text),note=note,created_at=now,previous_version_id=previous['id'])
            material.update(title=title,format=format_,tags=tags,current_version_id=version_id,revision=material['revision']+1,updated_at=now)
            record=MaterialOperation(id=_uid(identity,'operation'),project_id=project,material_id=material_id,operation_id=identity,action='update',expected_revision=revision,version_id=version_id,request_sha256=request_hash,created_at=now)
            state['material_versions'].append(_record(version))
            state['material_operations'].append(_record(record))
            return state,_detail(state,material_id,state['revision']+1)
        return self.repository.atomic(project,operation,identity_claim=('material_operations','operation_id',identity))

    def archive(self,project,material_id,request):
        return self._archived(project,material_id,request,True)

    def restore(self,project,material_id,request):
        return self._archived(project,material_id,request,False)

    def _archived(self,project,material_id,request,archived):
        check_fields(request,{'operation_id','expected_revision'});require(set(request)=={'operation_id','expected_revision'},'materials.invalid_archive_request')
        identity=uuid_value(request['operation_id']);revision=_revision(request);request_hash=_hash(request);uuid_value(material_id);action='archive' if archived else 'restore'
        def operation(state):
            upgrade(state);material=self._material(state,material_id);old=self._replay(state,identity,action,request_hash,material_id)
            if old:return None,_detail(state,material_id)
            self._check(state,revision)
            now=utc_now();material['archived']=archived;material['revision']+=1;material['updated_at']=now
            record=MaterialOperation(id=_uid(identity,'operation'),project_id=project,material_id=material_id,operation_id=identity,action=action,expected_revision=revision,version_id=None,request_sha256=request_hash,created_at=now)
            state['material_operations'].append(_record(record))
            return state,_detail(state,material_id,state['revision']+1)
        return self.repository.atomic(project,operation,identity_claim=('material_operations','operation_id',identity))

    def _build(self,state,project,material,identity,ordinal_prefix='',cancelled=None):
        version=next(value for value in state['material_versions'] if value['id']==material['current_version_id'])
        versions={value['id']:value for value in state['material_versions']}
        old={(c['start'],c['end']):c for c in material_chunks(state,material['id'])};built=[];reused=0;changed=[]
        for ordinal,(start,end) in enumerate(chunk_ranges(len(version['text']))):
            require(cancelled is None or not cancelled(),'materials.index_cancelled')
            previous=old.get((start,end));body=version['text'][start:end]
            same=previous is not None and versions[previous['material_version_id']]['text'][start:end]==body
            if same:
                # Stored old hashes are validated on repository load. Preserve the
                # derived window ID/hash, but rebind to the exact current version.
                chunk=dict(previous,material_version_id=version['id']);reused+=1
            else:
                chunk=_record(MaterialChunk(id=_uid(identity,ordinal_prefix+'chunk/'+material['id']+'/'+str(ordinal)),project_id=project,material_id=material['id'],material_version_id=version['id'],ordinal=ordinal,start=start,end=end,text_sha256=digest(body)))
                changed.append(dict(start=start,end=end))
            built.append(chunk)
        require(cancelled is None or not cancelled(),'materials.index_cancelled')
        state['material_chunks']=[value for value in state['material_chunks'] if value['material_id']!=material['id']]+built
        return version,dict(reused_chunks=reused,rebuilt_chunks=len(built)-reused,removed_chunks=len(set(old)-{(c['start'],c['end']) for c in built}),changed_ranges=changed,method='fixed_window_incremental_v1')

    def rebuild(self,project,material_id,request,*,cancelled=None):
        check_fields(request,{'operation_id','expected_revision'});require(set(request)=={'operation_id','expected_revision'},'materials.invalid_rebuild_request')
        identity=uuid_value(request['operation_id']);revision=_revision(request);request_hash=_hash(request);uuid_value(material_id)
        def operation(state):
            upgrade(state);material=self._material(state,material_id);old=self._replay(state,identity,'rebuild',request_hash,material_id)
            if old:return None,_detail(state,material_id)
            self._check(state,revision);require(not material['archived'],'materials.archived_cannot_rebuild')
            version,stats=self._build(state,project,material,identity,cancelled=cancelled)
            now=utc_now();record=MaterialOperation(id=_uid(identity,'operation'),project_id=project,material_id=material_id,operation_id=identity,action='rebuild',expected_revision=revision,version_id=version['id'],request_sha256=request_hash,created_at=now)
            state['material_operations'].append(_record(record))
            require(cancelled is None or not cancelled(),'materials.index_cancelled')
            return state,dict(_detail(state,material_id,state['revision']+1),index_update=stats)
        return self.repository.atomic(project,operation,identity_claim=('material_operations','operation_id',identity))

    def rebuild_all(self,project,request):
        check_fields(request,{'operation_id','expected_revision'});require(set(request)=={'operation_id','expected_revision'},'materials.invalid_rebuild_request')
        identity=uuid_value(request['operation_id']);revision=_revision(request);request_hash=_hash(request)
        def operation(state):
            upgrade(state);old=self._replay(state,identity,'rebuild_all',request_hash)
            if old:return None,self._rebuild_all_view(state,[value['id'] for value in state['materials'] if not value['archived']])
            self._check(state,revision);rebuilt=[];skipped=[]
            for material in state['materials']:
                if material['archived']:skipped.append(material['id']);continue
                self._build(state,project,material,identity,material['id']+'/');rebuilt.append(material['id'])
            now=utc_now();record=MaterialOperation(id=_uid(identity,'operation'),project_id=project,material_id=None,operation_id=identity,action='rebuild_all',expected_revision=revision,version_id=None,request_sha256=request_hash,created_at=now)
            state['material_operations'].append(_record(record))
            return state,self._rebuild_all_view(state,rebuilt,skipped,state['revision']+1)
        return self.repository.atomic(project,operation,identity_claim=('material_operations','operation_id',identity))

    def _rebuild_all_view(self,state,rebuilt,skipped=None,revision=None):
        values=self.listing_for_state(state)
        values['revision']=state['revision'] if revision is None else revision
        return dict(values,rebuilt_material_ids=rebuilt,skipped_archived_material_ids=skipped or [])

    def listing_for_state(self,state):
        materials=[value for value in state['materials'] if not value['archived']]
        tags=sorted({item for value in state['materials'] for item in value['tags']})
        return dict(revision=state['revision'],materials=[_summary(state,value) for value in materials],tags=tags,
            method='本地TXT/Markdown资料；分块仅作字面定位，不是语义检索',model_request_sent=False)
