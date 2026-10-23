"""Bounded process-local index jobs. Reopening never resumes or grants permission."""
from copy import deepcopy
import threading
from uuid import uuid4

from novel_writer.application.fields import check_fields
from novel_writer.domain.tasks import require,uuid_value
from novel_writer.storage.sqlite_repository import ConflictError


class MaterialIndexJobs:
    def __init__(self,materials):
        self.materials=materials;self.jobs={};self.lock=threading.RLock()

    def _find(self,project,identifier):
        job=self.jobs.get(identifier)
        if job is None or job['project_id']!=project:raise KeyError('本进程没有此索引任务；重开不会自动续跑')
        return job

    def _view(self,job):
        return deepcopy({k:v for k,v in job.items() if k not in ('cancel','thread','request')})

    def start(self,project,material_id,request):
        check_fields(request,{'operation_id','expected_revision'})
        require(set(request)=={'operation_id','expected_revision'},'materials.invalid_rebuild_request')
        request=deepcopy(request)
        uuid_value(request['operation_id']);require(type(request['expected_revision']) is int and request['expected_revision']>=1,'materials.invalid_revision')
        with self.lock:
            for job in self.jobs.values():
                if job['project_id']==project and job['request']['operation_id']==request['operation_id']:
                    require(job['material_id']==material_id and job['request']==request,'materials.operation_conflict');return self._view(job)
            require(not any(j['status'] in ('running','cancelling') for j in self.jobs.values()),'materials.index_busy')
            # Finished entries contain no source text. Bound process memory.
            if len(self.jobs)>=100:
                self.jobs.pop(next(iter(self.jobs)))
            state=self.materials.service.get(project);material=self.materials._material(state,material_id)
            from novel_writer.application.materials import _hash,_detail
            old=self.materials._replay(state,request['operation_id'],'rebuild',_hash(request),material_id)
            if old:
                job=dict(id=str(uuid4()),project_id=project,material_id=material_id,version_id=old['version_id'],status='succeeded',
                    request=request,cancel=threading.Event(),result=dict(_detail(state,material_id),replayed=True),error=None,model_request_sent=False)
                self.jobs[job['id']]=job;return self._view(job)
            self.materials._check(state,request['expected_revision']);require(not material['archived'],'materials.archived_cannot_rebuild')
            job=dict(id=str(uuid4()),project_id=project,material_id=material_id,version_id=material['current_version_id'],status='running',
                request=deepcopy(request),cancel=threading.Event(),result=None,error=None,model_request_sent=False)
            self.jobs[job['id']]=job
            def work():
                try:
                    result=self.materials.rebuild(project,material_id,request,cancelled=job['cancel'].is_set)
                    with self.lock:job.update(status='succeeded',result=result)
                except (ValueError,KeyError) as error:
                    with self.lock:job.update(status='cancelled' if str(error)=='materials.index_cancelled' else 'conflict' if isinstance(error,ConflictError) else 'failed',error=str(error))
                except Exception:
                    # No arbitrary exception/source text is exposed to clients.
                    with self.lock:job.update(status='failed',error='materials.index_failed')
            job['thread']=threading.Thread(target=work,daemon=True,name='material-index-'+job['id']);job['thread'].start()
            return self._view(job)

    def status(self,project,identifier):
        with self.lock:return self._view(self._find(project,identifier))

    def cancel(self,project,identifier):
        with self.lock:
            job=self._find(project,identifier)
            if job['status'] in ('running','cancelling'):
                job['cancel'].set();job['status']='cancelling'
            # A cancellation racing a committed transaction reports succeeded;
            # only a rollback may be described as cancelled.
            return self._view(job)

    def close(self):
        with self.lock:
            jobs=list(self.jobs.values())
            for job in jobs:job['cancel'].set()
        for job in jobs:
            if job.get('thread') is not None:job['thread'].join(2)
