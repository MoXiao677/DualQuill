"""Bounded, explicitly batch-confirmed console executor. Never adopts content."""
from copy import deepcopy
import threading
import time
from uuid import uuid4, uuid5, NAMESPACE_URL
from novel_writer.application.fields import check_fields
from novel_writer.application.console_tools import READ_ONLY
from novel_writer.domain.tasks import require, encode
from novel_writer.domain.models import utc_now
from novel_writer.domain.book_creation import fingerprint
from novel_writer.domain.console import Message, Ref, Dispatch
from novel_writer.domain.console_background import COLLECTIONS, TERMINAL


def upgrade(state):
    from novel_writer.application.migrations import upgrade_console_background
    upgrade_console_background(state)


class Stopped(Exception):pass


class BackgroundExecutor:
    def __init__(self, console):
        self.console=console; self.service=console.service; self.repository=console.repository
        self.owner_id=str(uuid4()); self.lock=threading.RLock(); self.active={}; self.closed=False

    def _events(self,state,bid):return [v for v in state.get(COLLECTIONS[1],[]) if v['batch_id']==bid]

    def _status(self,state,b):
        events=self._events(state,b['id'])
        return events[-1]['kind'] if events and events[-1]['kind'] in TERMINAL else 'running'

    def _emit(self,state,b,kind,step=None,elapsed=0,**detail):
        state[COLLECTIONS[1]].append(dict(id=str(uuid4()),batch_id=b['id'],kind=kind,step_id=step,
            elapsed_ms=max(0,int(elapsed)),detail=detail,created_at=utc_now()))

    def recover(self, project):
        """Only a newly owned server marks unfinished grants interrupted; never resends."""
        def operation(state):
            changed=False
            for b in state.get(COLLECTIONS[0],[]):
                if b['owner_id']!=self.owner_id and self._status(state,b)=='running':
                    self._emit(state,b,'interrupted',reason='进程已重启或从备份/复制恢复；旧授权失效，结果未知请求不会重发。')
                    changed=True
            return (state if changed else None),None
        self.repository.atomic(project,operation)

    def describe(self,project,run_id):
        state=self.service.get(project); self.console._run(state,run_id)
        batches=[]
        for b in state.get(COLLECTIONS[0],[]):
            if b['run_id']==run_id:
                status=self._status(state,b)
                if status=='running' and b['owner_id']!=self.owner_id:status='interrupted'
                batches.append(dict(deepcopy(b),status=status,events=deepcopy(self._events(state,b['id']))))
        return dict(revision=state['revision'],batches=batches)

    def _selection(self,state,run_id,request):
        require(type(request) is dict and set(request)=={'step_ids','max_steps','max_seconds'},'后台启动须选择步骤及步数/时间上限')
        require(type(request['max_steps']) is int and 1<=request['max_steps']<=100,'步数上限须1至100')
        require(type(request['max_seconds']) in (int,float) and 0<request['max_seconds']<=3600,'时间上限须大于0且不超过3600秒')
        ids=request['step_ids']; require(type(ids) is list and ids and all(type(s) is str for s in ids) and len(set(ids))==len(ids),'所选步骤非法')
        view=self.console._run_view(state,self.console._run(state,run_id))
        require(view['status']=='running' and not view['blocked_reason'],'运行暂停、结束或来源/计划已变化')
        steps=view['steps']; index=next((i for i,s in enumerate(steps) if s['id']==view['current_step_id']),None)
        require(index is not None and ids==[s['id'] for s in steps[index:index+len(ids)]],'必须从当前步骤按计划顺序连续选择；不能跳过人工节点')
        return steps[index:index+len(ids)]

    def _planning_preview(self,state,step,operation):
        engine=self.console.planning; require(engine is not None,'构思引擎不可用')
        if step.get('task_id'):
            detail=engine.describe(state['document']['project']['id'],step['task_id'])
            require(detail['status']=='pending','任务已发送或中断；不可重复执行')
            return dict(task=detail['task'],preparation=None)
        from novel_writer.application.chapter_planning import build_source
        source=dict(chapter_id=step['chapter_id'],mode='brainstorm' if step['type']=='idea' else 'outline',
            instruction=step['instruction'],character_ids=[v['id'] for v in state['document']['characters']],
            include_worldbuilding=True,include_writing_rules=True,include_facts=True,include_locations=True,context_budget_chars=20000)
        prepared_source=build_source(state,source)
        request=dict(operation_id=operation,source_options=source,source_sha256=prepared_source['source_sha256'],
            model_options=None,max_output_chars=12000,timeout_ms=30000)
        operation,_=engine._preparer(state['document']['project']['id'],request,state=state)
        _,result=operation(deepcopy(state))
        return dict(task=result['task'],preparation=request)

    def preview(self,project,run_id,request):
        state=self.service.get(project); steps=self._selection(state,run_id,request); items=[]
        for step in steps:
            source=dict(workspace_revision=state['revision'],plan_revision=self.console._run(state,run_id)['plan_revision'],step=deepcopy(step))
            source['step'].pop('result',None)
            if step['type'] in READ_ONLY and step['status']=='queued':
                result=self.console._read_tool(state,step)
                items.append(dict(step_id=step['id'],kind='readonly',source=source,result_sha256=fingerprint(result)))
            elif step['type'] in ('idea','outline') and step['status'] in ('queued','awaiting_confirmation'):
                op=str(uuid5(NAMESPACE_URL,run_id+'/background-prepare/'+step['id']+'/'+str(state['revision'])))
                model=self._planning_preview(state,step,op)
                items.append(dict(step_id=step['id'],kind='model',source=source,**model))
                # Generated candidates always need separate adoption; later requests depend on that decision.
                break
            else:
                items.append(dict(step_id=step['id'],kind='human',source=source,reason='正文生成、采纳、规划修改或非待执行状态需要作者单独确认'))
                break
        body=dict(run_id=run_id,request=deepcopy(request),items=items)
        return dict(revision=state['revision'],sha256=fingerprint(body),**body)

    def start(self,project,run_id,request):
        from novel_writer.domain.tasks import uuid_value
        fields={'operation_id','expected_revision','preview_sha256','confirmed','step_ids','max_steps','max_seconds'}
        check_fields(request,fields); require(set(request)==fields and request['confirmed'] is True,'必须明确批量确认来源、确切请求及预算')
        identity=uuid_value(request['operation_id']); selection={k:request[k] for k in ('step_ids','max_steps','max_seconds')}
        with self.lock:
            require(not self.closed,'后台执行器已关闭')
            state=self.service.get(project)
            old=next((b for b in state.get(COLLECTIONS[0],[]) if b['operation_id']==identity),None)
            if old:
                require(old['run_id']==run_id and old['request']==selection and old['preview']['sha256']==request['preview_sha256'],'批次操作编号已绑定其它请求')
                return dict(batch=next(b for b in self.describe(project,run_id)['batches'] if b['id']==old['id']))
            preview=self.preview(project,run_id,selection)
            require(type(request['expected_revision']) is int and preview['revision']==request['expected_revision'],'保存编号已变化，请重新预览')
            require(preview['sha256']==request['preview_sha256'],'冻结请求或来源已变化，请重新预览确认')
            batch=dict(id=str(uuid5(NAMESPACE_URL,identity+'/background')),project_id=project,run_id=run_id,operation_id=identity,
                owner_id=self.owner_id,request=deepcopy(selection),preview=preview,created_at=utc_now())
            def operation(current):
                require(current['revision']==preview['revision'],'来源已变化，请重新预览')
                require(not any(b['run_id']==run_id and self._status(current,b)=='running' for b in current.get(COLLECTIONS[0],[])),'已有后台批次，不能并行重复启动')
                upgrade(current); current[COLLECTIONS[0]].append(batch); self._emit(current,batch,'started',authorization_sha256=preview['sha256'])
                return current,None
            self.repository.atomic(project,operation,identity_claim=(COLLECTIONS[0],'operation_id',identity))
            token=threading.Event(); deadline=time.monotonic()+selection['max_seconds']
            worker=threading.Thread(target=self._worker,name='console-background-'+batch['id'][:8],args=(project,batch,token,deadline),daemon=True)
            self.active[batch['id']]=dict(worker=worker,token=token,reason='cancelled',project=project,run_id=run_id,task_id=None)
            worker.start()
            return dict(batch=dict(deepcopy(batch),status='running',events=[]))

    def _guard(self,project,b,token,deadline,state=None):
        if token.is_set():raise Stopped(self.active[b['id']]['reason'])
        if time.monotonic()>=deadline:raise Stopped('time_limit')
        state=self.service.get(project) if state is None else state
        if self._status(state,b)!='running':raise Stopped('interrupted')
        run=self.console._run_view(state,self.console._run(state,b['run_id']))
        if run['status']=='paused':raise Stopped('paused')
        if run['status']=='cancelled':raise Stopped('cancelled')
        require(not run['blocked_reason'],'计划或输入已变化：'+str(run['blocked_reason']))

    def _readonly(self,project,b,item,token,deadline):
        start=time.monotonic()
        def operation(state):
            self._guard(project,b,token,deadline,state)
            run=self.console._run(state,b['run_id']); step=next(s for s in state['console_run_steps'] if s['id']==item['step_id'])
            require(run['current_step_id']==step['id'] and step['status']=='queued','步骤游标已变化')
            result=self.console._read_tool(state,step)
            self._guard(project,b,token,deadline,state)
            # Batch audit writes advance revision without changing the saved tool inputs.
            frozen_state=dict(state,revision=b['preview']['revision'])
            frozen_result=self.console._read_tool(frozen_state,step)
            self._guard(project,b,token,deadline,state)
            require(fingerprint(frozen_result)==item['result_sha256'],'输入来源已变化，请重新批量确认')
            import json
            text=json.dumps(result,ensure_ascii=False,sort_keys=True); require(len(text)<=50000,'结果超过保存上限')
            now=utc_now(); state['console_messages'].append(encode(Message(id=str(uuid4()),project_id=project,
                session_id=run['session_id'],role='result',text=text,refs=(Ref(kind='step',id=step['plan_step_id']),),created_at=now)))
            step.update(status='completed',updated_at=now)
            following=next((s for s in self.console._run_steps(state,run['id']) if s['position']>step['position'] and s['status']=='queued'),None)
            run.update(current_step_id=following['id'] if following else None,status='running' if following else 'completed',updated_at=now)
            self._emit(state,b,'step_completed',step['id'],(time.monotonic()-start)*1000,source=item['source'],request=dict(tool=step['type']),result=result)
            return state,None
        self.repository.atomic(project,operation)

    def _model(self,project,b,item,token,deadline):
        engine=self.console.planning; start=time.monotonic()
        def operation(state):
            self._guard(project,b,token,deadline,state)
            run=self.console._run(state,b['run_id']); step=next(s for s in state['console_run_steps'] if s['id']==item['step_id'])
            require(run['current_step_id']==step['id'],'步骤游标已变化')
            if item['preparation']:
                prepare,_=engine._preparer(project,item['preparation'],state=state)
                _,result=prepare(state); task=result['task']
                require(task['binding']==item['task']['binding'] and task['source_sha256']==item['task']['source_sha256'],'实际请求与批量确认不一致')
                dispatch=encode(Dispatch(id=str(uuid4()),project_id=project,session_id=run['session_id'],step_id=step['plan_step_id'],engine='chapter_planning',task_id=task['id'],created_at=utc_now()))
                state['console_dispatches'].append(dispatch)
                step.update(status='awaiting_confirmation',dispatch_id=dispatch['id'],engine='chapter_planning',task_id=task['id'],updated_at=utc_now())
            else:task=item['task']
            self._guard(project,b,token,deadline,state)
            self._emit(state,b,'step_started',step['id'],source=item['source'],request=task['binding'],task_id=task['id'])
            return state,task['id']
        with self.lock:
            task_id=self.repository.atomic(project,operation)
            self.active[b['id']]['task_id']=task_id
            self._guard(project,b,token,deadline)
            engine.start(project,task_id,dict(confirm_external=True,request_sha256=item['task']['binding']['request_sha256']))
        while True:
            self._guard(project,b,token,deadline)
            detail=engine.describe(project,task_id)
            if detail['status']!='running':break
            token.wait(.025)
        require(detail['status']=='succeeded','候选请求未成功：'+detail['status'])
        def complete(state):
            self._guard(project,b,token,deadline,state)
            self._emit(state,b,'step_completed',item['step_id'],(time.monotonic()-start)*1000,source=item['source'],request=item['task']['binding'],result=detail)
            return state,None
        self.repository.atomic(project,complete)
        return 'awaiting_human'

    def _worker(self,project,b,token,deadline):
        status='completed'; reason='所选步骤已完成'; done=0
        try:
            for item in b['preview']['items']:
                self._guard(project,b,token,deadline)
                if done>=b['request']['max_steps']:status='step_limit'; reason='达到步数上限'; break
                if item['kind']=='human':status='awaiting_human';reason=item['reason'];break
                if item['kind']=='model':status=self._model(project,b,item,token,deadline);reason='候选已保存，等待作者独立采纳';done+=1;break
                self._readonly(project,b,item,token,deadline);done+=1
        except Stopped as error:status=str(error);reason='授权已停止，未完成步骤不会继续或重发'
        except Exception as error:status='failed';reason=str(error)
        finally:
            entry=self.active.get(b['id'])
            if status in ('cancelled','paused','time_limit','interrupted') and entry and entry['task_id']:
                try:self.console.planning.cancel(project,entry['task_id'])
                except (ValueError,KeyError):pass
            def finish(state):
                if self._status(state,b)!='running':return None,None
                self._emit(state,b,status,reason=reason,completed_steps=done)
                return state,None
            try:self.repository.atomic(project,finish)
            finally:
                with self.lock:self.active.pop(b['id'],None)

    def control(self,project,run_id,action):
        require(action in ('pause','cancel'),'后台控制非法')
        # Signal first: a long read transaction must be able to roll back before control waits for SQLite.
        for entry in list(self.active.values()):
            if entry['project']==project and entry['run_id']==run_id:
                entry['reason']='paused' if action=='pause' else 'cancelled';entry['token'].set()
        return self.describe(project,run_id)

    def wait_idle(self,timeout=5):
        end=time.monotonic()+timeout
        for entry in list(self.active.values()):entry['worker'].join(max(0,end-time.monotonic()))
        return not self.active

    def close(self):
        self.closed=True
        for entry in list(self.active.values()):entry['reason']='interrupted';entry['token'].set()
        self.wait_idle(5)
