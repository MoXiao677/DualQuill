"""V37 groups existing C04 tasks; never grants execution or adoption permission."""
from copy import deepcopy
from dataclasses import dataclass
from typing import Literal
from novel_writer.domain.experiments import Value,Configuration,TERMINAL
from novel_writer.domain.tasks import fingerprint,require

SIDES=('A','B','C','D','E','F')
KINDS=('scene_expansion','chapter_planning','chapter_writing')

@dataclass(frozen=True,kw_only=True)
class WritingExperiment(Value):
    id:str
    project_id:str
    title:str
    chapter_id:str
    source_revision:int
    task_kind:Literal['scene_expansion','chapter_planning','chapter_writing']
    common_input_sha256:str
    configurations:tuple[Configuration,...]
    created_at:str
    trial_kind:Literal['writing_candidates']='writing_candidates'

def task_record(state,kind,identifier):
    collection={'scene_expansion':'scene_expansion_tasks','chapter_planning':'chapter_planning_tasks','chapter_writing':'generation_tasks'}[kind]
    task=next((v for v in state.get(collection,[]) if v['id']==identifier),None)
    require(task is not None,'writing_comparison.missing_task')
    if kind=='chapter_writing':require(task['task_type'] in ('draft_chapter','continue_chapter'),'writing_comparison.invalid_capability')
    return task

def common_input(task,kind):
    if kind=='chapter_writing':
        frozen=deepcopy(task['frozen']);frozen.pop('source_revision',None)
        frozen['parameters'].pop('binding',None)
        for key in ('preparation_sha256','prepared_owner','retry_of'):frozen['parameters']['writing'].pop(key,None)
        for dependency in frozen['dependencies']:dependency.pop('source_revision',None)
        return fingerprint(dict(task_type=task['task_type'],chapter_id=task['chapter_id'],frozen=frozen))
    return fingerprint({key:task[key] for key in ('chapter_id','source_options','source_sha256','context_text','max_output_chars','timeout_ms')})

def records(state):
    """Use immutable original results so corrections cannot rewrite blind scores."""
    tasks={};candidates=[];results=[]
    for kind in KINDS[:2]:
        by_task={};original_candidates={}
        for event in state.get(kind+'_events',[]):by_task.setdefault(event['task_id'],[]).append(event)
        for candidate in state.get(kind+'_candidates',[]):original_candidates.setdefault(candidate['task_id'],candidate)
        for task in state.get(kind+'_tasks',[]):
            events=by_task.get(task['id'],[])
            last=events[-1] if events else {};started=next((v for v in events if v['status']=='running'),None)
            finished=next((v for v in events if v['status'] in TERMINAL),None)
            candidate=original_candidates.get(task['id'])
            status=last.get('status','pending')
            if status=='succeeded' and (candidate is None or candidate.get('errors')):status='failed'
            if candidate and status=='succeeded':candidates.append(dict(candidate,output_text=candidate.get('text',candidate.get('raw_text',''))))
            tasks[task['id']]=dict(id=task['id'],status=status,candidate_id=candidate['id'] if candidate and status=='succeeded' else None,started_at=started['created_at'] if started else None,finished_at=finished['created_at'] if finished else None)
        results.extend(state.get(kind+'_results',[]))
    return tasks,candidates,results

def validate_experiment(experiment,state,children):
    e=experiment;n=len(e.configurations)
    require(state['workspace_version']>=37 and 2<=n<=6,'writing_comparison.invalid_version_or_count')
    require(0<len(e.title.strip())<=300 and 1<=e.source_revision<=state['revision'],'writing_comparison.invalid_metadata')
    require({v.index for v in e.configurations}==set(range(n)) and {v.side for v in e.configurations}==set(SIDES[:n]),'writing_comparison.invalid_slots')
    for slot in e.configurations:
        task=task_record(state,e.task_kind,slot.task_id)
        require(slot.task_id not in children and task['chapter_id']==e.chapter_id and task['project_id']==e.project_id,'writing_comparison.task_reused_or_cross_scope')
        require(common_input(task,e.task_kind)==e.common_input_sha256,'writing_comparison.different_frozen_input')
        children.add(slot.task_id)
