"""Manual from-zero planning. No model request or formal write on draft/branch/preview."""
from copy import deepcopy
from dataclasses import fields,replace
from uuid import uuid4,uuid5,NAMESPACE_URL
from novel_writer.domain.book_creation import *
from novel_writer.domain.models import utc_now,Chapter,Character,ChapterOutline,BookOutline,VolumePlan
from novel_writer.application.fields import check_fields
from novel_writer.storage.json_codec import document_from_dict,document_to_dict
from novel_writer.storage.sqlite_repository import ConflictError
from novel_writer.application.creation_quality import stale_steps,quality_report

def upgrade(state):
    from novel_writer.application.creation_presets import upgrade as previous
    previous(state);state['workspace_version']=max(state['workspace_version'],11)
    for name in COLLECTIONS:state.setdefault(name,[])

def signature(request):return fingerprint({key:value for key,value in request.items() if key!='expected_revision'})
def formal_hash(state):return fingerprint(dict(document=state['document'],worldbuilding=state['worldbuilding']))
def lock_hash(state):return fingerprint(dict(creation=current_locks(state),existing=state.get('planning_locks',[])))
def fresh(state,request):require(type(request['expected_revision']) is int and request['expected_revision']==state['revision'],'creation.stale')
def known(request,names):
    required=set(names)|{'operation_id','expected_revision'};check_fields(request,required);require(set(request)==required,'creation.invalid_request');uuid_value(request['operation_id'])
def get_version(state,identifier):
    value=next((v for v in state.get('book_creation_versions',[]) if v['id']==identifier),None);require(value is not None,'creation.missing_version');return value
def replay(state,collection,request):
    old=next((v for v in state.get(collection,[]) if v['operation_id']==request['operation_id']),None)
    if old is not None:require(old['request_sha256']==signature(request),'creation.identity_conflict')
    return old
def metadata(project,request):return dict(id=str(uuid5(NAMESPACE_URL,request['operation_id']+'/record')),project_id=project,operation_id=request['operation_id'],request_sha256=signature(request),created_at=utc_now())
def normalized_data(raw,operation):
    value=deepcopy(raw)
    def identified(item,kind,path):
        names={f.name for f in fields(kind)};check_fields(item,names);data={f.name:[] if f.name in ('goals','chapters') else '' for f in fields(kind)};data.update(item)
        data['id']=data['id'] or str(uuid5(NAMESPACE_URL,operation+'/'+path))
        if kind is PlanChapter:data['outline_id']=data['outline_id'] or str(uuid5(NAMESPACE_URL,operation+'/'+path+'/outline'))
        return data
    value['characters']=[identified(v,PlanCharacter,'character/'+str(i)) for i,v in enumerate(value['characters'])]
    volumes=[]
    for i,raw_volume in enumerate(value['volumes']):
        volume=identified(raw_volume,PlanVolume,'volume/'+str(i));volume['chapters']=[identified(c,PlanChapter,'volume/'+str(i)+'/chapter/'+str(j)) for j,c in enumerate(volume['chapters'])];volumes.append(volume)
    value['volumes']=volumes;return parse(PlanData,value)

def seed(state,operation):
    doc=state['document'];outline=doc['book_outline'] or {};volumes=[];assigned=set();outlines={v['chapter_id']:v for v in doc['chapter_outlines']}
    def chapter(c):
        plan=outlines.get(c['id'],{});return dict(id=c['id'],outline_id=plan.get('id') or str(uuid5(NAMESPACE_URL,operation+'/'+c['id']+'/outline')),title=c['title'],core_idea=plan.get('core_idea',''),objective=plan.get('objective',''),story_time=plan.get('story_time',''))
    for i,volume in enumerate(outline.get('volumes',[])):
        members=[chapter(c) for c in doc['chapters'] if c['id'] in volume['chapter_ids']];assigned.update(c['id'] for c in members);volumes.append(dict(id=str(uuid5(NAMESPACE_URL,operation+'/volume/'+str(i))),title=volume['title'],summary=volume['summary'],chapters=members))
    remaining=[chapter(c) for c in doc['chapters'] if c['id'] not in assigned]
    if remaining:volumes.append(dict(title=doc['project']['title'],summary='',chapters=remaining))
    return normalized_data(dict(title=doc['project']['title'],creative_idea=doc['project']['summary'],genre=doc['project']['genre'],readership='',target_words=0,manuscript_language=doc['project']['language'],theme=outline.get('theme',''),core_conflict='',worldbuilding=state['worldbuilding'],characters=[{name:c[name] for name in ('id','name','role','personality','background','goals','notes')} for c in doc['characters']],main_plot=outline.get('main_plot',''),subplots=[],ending=outline.get('ending',''),volumes=volumes),operation)

def conflicts(state,data):
    return [Conflict(field=field,code='creation.lock_conflict',entity_id=lock['id']) for field,lock in current_locks(state).items() if fingerprint(getattr(data,field))!=lock['value_sha256']]
def enforce_formal_locks(state,action,values):
    locks=current_locks(state)
    if action in ('add_character','save_character') and 'characters' in locks:raise ValueError('creation.lock_conflict:characters')
    field='ending' if action=='save_book_outline' and 'ending' in values else 'worldbuilding' if action=='save_worldbuilding' else None
    if field in locks:
        value=values.get('ending') if field=='ending' else values.get('content','')
        require(fingerprint(value)==locks[field]['value_sha256'],'creation.lock_conflict:'+field)

class BookCreation:
    def __init__(self,service):self.service,self.repository=service,service.repository;self.owner_id=str(uuid4())
    def describe(self,project):
        state=self.service.get(project);versions=state.get('book_creation_versions',[]);choices=state.get('book_creation_choices',[]);identifier=choices[-1]['version_id'] if choices else versions[-1]['id'] if versions else None;selected=next((v for v in versions if v['id']==identifier),None)
        return dict(revision=state['revision'],versions=deepcopy(versions),selected=deepcopy(selected),locks=deepcopy(current_locks(state)),decisions=deepcopy(state.get('book_creation_decisions',[])),ui_language_independent=True,stale_steps=stale_steps(state,selected),quality=quality_report(parse(PlanData,selected['data'])) if selected else None)
    def _atomic(self,project,collection,request,operation):return self.repository.atomic(project,operation,identity_claim=(collection,'operation_id',request['operation_id']))
    def _select(self,state,project,version,request):
        data=metadata(project,dict(request,operation_id=str(uuid5(NAMESPACE_URL,request['operation_id']+'/selection'))));data['version_id']=version['id'];state['book_creation_choices'].append(encode(PlanChoice(**data)))
    def start(self,project,request):
        known(request,{'name'})
        def apply(state):
            old=replay(state,'book_creation_versions',request)
            if old:return None,dict(version_id=old['id'],branch_id=old['branch_id'])
            fresh(state,request);upgrade(state);record=PlanVersion(**metadata(project,request),branch_id=str(uuid5(NAMESPACE_URL,request['operation_id']+'/branch')),branch_name=request['name'],revision=1,previous_version_id=None,derived_from_version_id=None,data=seed(state,request['operation_id']),current_step='idea',completed_steps=(),skipped_steps=());value=encode(record);state['book_creation_versions'].append(value);self._select(state,project,value,request);return state,dict(version_id=record.id,branch_id=record.branch_id)
        return self._atomic(project,'book_creation_versions',request,apply)
    def fork(self,project,request):
        known(request,{'version_id','name'})
        def apply(state):
            old=replay(state,'book_creation_versions',request)
            if old:return None,dict(version_id=old['id'],branch_id=old['branch_id'])
            fresh(state,request);base=get_version(state,request['version_id']);record=PlanVersion(**metadata(project,request),branch_id=str(uuid5(NAMESPACE_URL,request['operation_id']+'/branch')),branch_name=request['name'],revision=1,previous_version_id=None,derived_from_version_id=base['id'],data=parse(PlanData,base['data']),current_step=base['current_step'],completed_steps=tuple(base['completed_steps']),skipped_steps=tuple(base['skipped_steps']));value=encode(record);state['book_creation_versions'].append(value);self._select(state,project,value,request);return state,dict(version_id=record.id,branch_id=record.branch_id)
        return self._atomic(project,'book_creation_versions',request,apply)
    def _save_step_operation(self,project,request):
        known(request,{'base_version_id','step','fields','mark','next_step'});require(request['step'] in STEPS and request['next_step'] in STEPS and request['mark'] in ('save','complete','skip') and type(request['fields']) is dict,'creation.invalid_request');check_fields(request['fields'],STEP_FIELDS[request['step']])
        def apply(state):
            old=replay(state,'book_creation_versions',request)
            if old:return None,dict(version_id=old['id'],branch_id=old['branch_id'])
            fresh(state,request);base=get_version(state,request['base_version_id']);latest=next(v for v in reversed(state['book_creation_versions']) if v['branch_id']==base['branch_id']);require(latest['id']==base['id'],'creation.fork_old_version');raw=deepcopy(base['data']);raw.update(request['fields']);data=normalized_data(raw,request['operation_id']);require(not conflicts(state,data),'creation.lock_conflict')
            completed=set(base['completed_steps']);skipped=set(base['skipped_steps']);step=request['step']
            changed=any(fingerprint(raw[f])!=fingerprint(base['data'][f]) for f in STEP_FIELDS[step])
            boundary=STEPS.index(request['next_step']) if STEPS.index(request['next_step'])<STEPS.index(base['current_step']) else STEPS.index(step)
            if changed or STEPS.index(request['next_step'])<STEPS.index(base['current_step']):
                completed.difference_update(STEPS[boundary+1:])
            if request['mark']=='skip':skipped.add(step);completed.discard(step)
            else:
                skipped.discard(step)
                if request['mark']=='complete':completed.add(step)
            record=PlanVersion(**metadata(project,request),branch_id=base['branch_id'],branch_name=base['branch_name'],revision=base['revision']+1,previous_version_id=base['id'],derived_from_version_id=None,data=data,current_step=request['next_step'],completed_steps=tuple(s for s in STEPS if s in completed),skipped_steps=tuple(s for s in STEPS if s in skipped));value=encode(record);state['book_creation_versions'].append(value);self._select(state,project,value,request);return state,dict(version_id=record.id,branch_id=record.branch_id)
        return apply
    def _save_dialogue_operation(self,project,request):
        def apply(state):
            base=get_version(state,request['base_version_id']);data=normalized_data(request['fields'],request['operation_id']);require(not conflicts(state,data),'creation.lock_conflict')
            record=PlanVersion(**metadata(project,request),branch_id=base['branch_id'],branch_name=base['branch_name'],revision=base['revision']+1,previous_version_id=base['id'],derived_from_version_id=None,data=data,current_step='structure',completed_steps=tuple(STEPS),skipped_steps=());value=encode(record);state['book_creation_versions'].append(value);self._select(state,project,value,request);return state,dict(version_id=record.id,branch_id=record.branch_id)
        return apply
    def save_step(self,project,request):
        return self._atomic(project,'book_creation_versions',request,self._save_step_operation(project,request))
    def choose(self,project,request):
        known(request,{'version_id'})
        def apply(state):
            old=replay(state,'book_creation_choices',request)
            if old:return None,old
            fresh(state,request);version=get_version(state,request['version_id']);require(not conflicts(state,parse(PlanData,version['data'])),'creation.lock_conflict');record=PlanChoice(**metadata(project,request),version_id=version['id']);state['book_creation_choices'].append(encode(record));return state,encode(record)
        return self._atomic(project,'book_creation_choices',request,apply)
    def set_lock(self,project,request):
        known(request,{'version_id','field','locked','current_lock_id','confirmed'});require(request['field'] in LOCK_FIELDS and type(request['locked']) is bool and request['confirmed'] is True,'creation.unlock_confirmation')
        def apply(state):
            old=replay(state,'book_creation_locks',request)
            if old:return None,old
            fresh(state,request);version=get_version(state,request['version_id']);previous=next((v for v in reversed(state['book_creation_locks']) if v['field']==request['field']),None);active=previous if previous and previous['locked'] else None;require(request['current_lock_id']==(active['id'] if active else None),'creation.stale_lock')
            if not request['locked']:require(active is not None,'creation.invalid_lock');version=get_version(state,active['version_id'])
            elif active:require(active['value_sha256']==fingerprint(version['data'][request['field']]),'creation.unlock_first')
            record=PlanLock(**metadata(project,request),version_id=version['id'],field=request['field'],locked=request['locked'],value_sha256=fingerprint(version['data'][request['field']]),previous_lock_id=previous['id'] if previous else None);state['book_creation_locks'].append(encode(record));return state,encode(record)
        return self._atomic(project,'book_creation_locks',request,apply)
    def _impact(self,state,version):
        data=parse(PlanData,version['data']);doc=state['document'];skip=set(version['skipped_steps']);chapters=[] if 'structure' in skip else [c for v in data.volumes for c in v.chapters];characters=[] if 'world' in skip else list(data.characters);existing={c['id']:c for c in doc['chapters']};actual_chars={c['id'] for c in doc['characters']};issues=conflicts(state,data);outlines={v['chapter_id']:v['id'] for v in doc['chapter_outlines']}
        if 'structure' not in skip:
            for identifier in set(existing)-{c.id for c in chapters}:issues.append(Conflict(field='structure',code='creation.keep_existing_chapters',entity_id=identifier))
            for chapter in chapters:
                if chapter.id in outlines and outlines[chapter.id]!=chapter.outline_id:issues.append(Conflict(field='structure',code='creation.outline_identity',entity_id=chapter.id))
        for step in stale_steps(state,version):issues.append(Conflict(field=step,code='creation.stale_step',entity_id=None))
        for step in STEPS:
            if step in skip:continue
            for error in quality_report(data,step)['errors']:
                issues.append(Conflict(field=error['field'],code='creation.quality:'+error['code'],entity_id=None))
        return Impact(chapter_creates=tuple(c.id for c in chapters if c.id not in existing),chapter_reuses=tuple(c.id for c in chapters if c.id in existing),character_creates=tuple(c.id for c in characters if c.id not in actual_chars),character_reuses=tuple(c.id for c in characters if c.id in actual_chars),outline_ids=tuple(c.outline_id for c in chapters),requires_confirmed_metadata=any(c.id in existing and existing[c.id]['status']=='confirmed' and existing[c.id]['title']!=c.title for c in chapters),conflicts=tuple(issues))
    def preview(self,project,request):
        known(request,{'version_id'})
        def apply(state):
            old=replay(state,'book_creation_previews',request)
            if old:return None,dict(preview=old,version=get_version(state,old['version_id']))
            fresh(state,request);version=get_version(state,request['version_id']);impact=self._impact(state,version)
            try:self._apply_formal(deepcopy(state),version,True)
            except ValueError:impact=replace(impact,conflicts=(*impact.conflicts,Conflict(field='planning',code='creation.existing_lock_or_conflict',entity_id=None)))
            record=PlanPreview(**metadata(project,request),version_id=version['id'],owner_id=self.owner_id,document_sha256=formal_hash(state),locks_sha256=lock_hash(state),plan_sha256=fingerprint(version['data']),impact=impact);state['book_creation_previews'].append(encode(record));return state,dict(preview=encode(record),version=version)
        return self._atomic(project,'book_creation_previews',request,apply)
    def _apply_formal(self,state,version,authorize):
        from novel_writer.application.versions import record
        from novel_writer.application.knowledge import enforce_plan_locks
        from novel_writer.application import book_outlines,chapter_outlines,chapters
        data=parse(PlanData,version['data']);skip=set(version['skipped_steps']);document=document_from_dict(state['document']);before=len(document.versions)
        changes={}
        if 'idea' not in skip:changes.update(title=data.title,summary=data.creative_idea)
        if 'audience' not in skip:changes['genre']=data.genre
        if 'scope' not in skip:changes['language']=data.manuscript_language
        if any(getattr(document.project,key)!=value for key,value in changes.items()):
            for key,value in changes.items():setattr(document.project,key,value)
            record(document,'project',document.project,'Author confirmed creation plan')
        if 'world' not in skip:
            state['worldbuilding']=data.worldbuilding
            for character in data.characters:
                actual=next((c for c in document.characters if c.id==character.id),None);values=encode(character);values.pop('id')
                if actual is None:actual=Character(id=character.id,project_id=document.project.id,**values);document.characters.append(actual);record(document,'character',actual,'Author confirmed proposed character')
                elif any(getattr(actual,key)!=value for key,value in values.items()):
                    for key,value in values.items():setattr(actual,key,value)
                    record(document,'character',actual,'Author confirmed character planning update')
        outline_values={}
        if 'conflict' not in skip:outline_values['theme']=data.theme
        if 'idea' not in skip:outline_values['premise']=data.creative_idea
        if 'plot' not in skip:outline_values.update(main_plot=data.main_plot,ending=data.ending)
        if 'structure' not in skip:
            volumes=[]
            for number,volume in enumerate(data.volumes,1):
                ids=[]
                for proposed in volume.chapters:
                    actual=next((c for c in document.chapters if c.id==proposed.id),None)
                    if actual is None:actual=Chapter(id=proposed.id,project_id=document.project.id,number=max((c.number for c in document.chapters),default=0)+1,title=proposed.title);document.chapters.append(actual);record(document,'chapter',actual,'Author confirmed new planned chapter')
                    elif actual.title!=proposed.title:chapters.save(document,dict(chapter_id=actual.id,title=proposed.title,authorize_confirmed=authorize))
                    ids.append(actual.id);values=dict(chapter_id=actual.id,core_idea=proposed.core_idea,objective=proposed.objective,story_time=proposed.story_time);enforce_plan_locks(state,'save_chapter_outline',values)
                    outline=next((v for v in document.chapter_outlines if v.chapter_id==actual.id),None)
                    if outline is None:outline=ChapterOutline(id=proposed.outline_id,project_id=document.project.id,chapter_id=actual.id);document.chapter_outlines.append(outline)
                    if not any(v.entity_type=='chapter_outline' and v.entity_id==outline.id for v in document.versions) or any(getattr(outline,key)!=value for key,value in values.items() if key!='chapter_id'):chapter_outlines.save(document,values)
                volumes.append(dict(number=number,title=volume.title,summary=volume.summary,chapter_ids=ids))
            outline_values['volumes']=volumes
        enforce_plan_locks(state,'save_book_outline',outline_values)
        if outline_values and document.book_outline is None:document.book_outline=BookOutline(id=str(uuid5(NAMESPACE_URL,project_key(document.project.id))),project_id=document.project.id)
        if outline_values:book_outlines.save(document,outline_values)
        state['document']=document_to_dict(document)
        return [v.id for v in document.versions[before:]]
    def decide(self,project,request):
        known(request,{'preview_id','decision','confirmed','create_entities','authorize_confirmed_metadata'});require(request['decision'] in ('accepted','rejected','cancelled') and all(type(request[key]) is bool for key in ('confirmed','create_entities','authorize_confirmed_metadata')),'creation.invalid_decision')
        def apply(state):
            old=replay(state,'book_creation_decisions',request)
            if old:return None,old
            fresh(state,request);preview=next((v for v in state['book_creation_previews'] if v['id']==request['preview_id']),None);require(preview is not None,'creation.preview_required');require(not any(v['preview_id']==preview['id'] for v in state['book_creation_decisions']),'creation.already_decided');version=get_version(state,preview['version_id']);chapters=[];characters=[];outline_ids=[];document_versions=[]
            if request['decision']=='accepted':
                require(request['confirmed'] and request['create_entities'],'creation.confirm_required');require(preview['owner_id']==self.owner_id,'creation.preview_again');require(formal_hash(state)==preview['document_sha256'] and lock_hash(state)==preview['locks_sha256'],'creation.source_changed');impact=self._impact(state,version);require(not impact.conflicts and not preview['impact']['conflicts'],'creation.resolve_conflicts');require(not impact.requires_confirmed_metadata or request['authorize_confirmed_metadata'],'creation.confirm_metadata');document_versions=self._apply_formal(state,version,request['authorize_confirmed_metadata']);chapters=list(impact.chapter_creates+impact.chapter_reuses);characters=list(impact.character_creates+impact.character_reuses);outline_ids=list(impact.outline_ids)
            record=PlanDecision(**metadata(project,request),preview_id=preview['id'],version_id=version['id'],decision=request['decision'],confirmed=request['confirmed'],create_entities=request['create_entities'],authorize_confirmed_metadata=request['authorize_confirmed_metadata'],chapter_ids=tuple(chapters),character_ids=tuple(characters),outline_ids=tuple(outline_ids),document_version_ids=tuple(document_versions));state['book_creation_decisions'].append(encode(record));return state,encode(record)
        return self._atomic(project,'book_creation_decisions',request,apply)

def project_key(identifier):return identifier+'/book-creation/formal-outline'
