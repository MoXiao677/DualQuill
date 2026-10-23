"""仅绑定本机的标准库 HTTP 界面，所有写操作经过会话令牌和业务层。"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import base64
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from urllib.parse import parse_qs,quote,urlsplit

from novel_writer.application.service import NovelService
from novel_writer.application.skill_import import MODULE as SKILLS_MODULE, SkillLibrary
from novel_writer.application.provider_connections import ProviderConnections
from novel_writer.storage.sqlite_repository import ConflictError, SQLiteRepository

STATIC = Path(__file__).resolve().parent / "static"
MAX_BODY = 12 * 1024 * 1024
REJECT_DRAIN_BYTES = 4096
REJECT_DRAIN_SECONDS = .2

class BlindProjectionError(ValueError):
    """正常盲态读取限制，不伪装成存储读取故障。"""


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def server_close(self):
        if hasattr(self,'materials'):self.materials.index_jobs.close()
        super().server_close()

    def __init__(self, database_path, port, provider_path=None, *, offline=False,local_protocol_demo=False,enable_model_generation=False,model_adapter=None,drafts_path=None):
        self.database_path = Path(database_path).resolve()
        self.service = NovelService(SQLiteRepository(self.database_path))
        self.skills = SkillLibrary(self.database_path)
        self.offline = offline
        self.providers = ProviderConnections(provider_path, offline=offline)
        from novel_writer.application.drafts import DiskDrafts,DraftError
        self.drafts=DiskDrafts(drafts_path or Path(database_path).resolve().parent/'drafts')
        from novel_writer.application.local_data import LocalDataSafety
        self.local_data=LocalDataSafety(self.drafts,self.database_path,offline=offline,models_enabled=enable_model_generation and not offline)
        from novel_writer.application.tasks import TaskCoordinator
        from novel_writer.application.task_protocol import AdapterRegistry,LocalProtocolAdapter
        self.local_protocol_demo=local_protocol_demo
        registry=AdapterRegistry()
        from novel_writer.application.review_rules import OfflineAuditAdapter
        registry.register('audit_chapter',OfflineAuditAdapter())
        if local_protocol_demo:registry.register('rewrite_chapter',LocalProtocolAdapter())
        from novel_writer.application.model_adapter import ChatCompletionsAdapter
        if type(enable_model_generation) is not bool:raise ValueError('模型启用开关必须是布尔值')
        self.model_generation_enabled=enable_model_generation and not offline
        adapter=model_adapter or ChatCompletionsAdapter(self.providers)
        if type(adapter) is not ChatCompletionsAdapter:raise ValueError('模型adapter必须经明确内部构造')
        adapter.enabled=self.model_generation_enabled
        self.model_adapter=adapter  # Desktop session mode controls this existing adapter only.
        from novel_writer.application.custom_protocols import ConfiguredHttpAdapter
        self.configured_model_adapter=ConfiguredHttpAdapter(self.providers,enabled=self.model_generation_enabled)
        self.model_adapters=(adapter,self.configured_model_adapter)
        registry.register('rewrite_chapter',adapter);registry.register('audit_chapter',adapter)
        registry.register('rewrite_chapter',self.configured_model_adapter);registry.register('audit_chapter',self.configured_model_adapter)
        for writing_adapter in self.model_adapters:
            registry.register('draft_chapter',writing_adapter);registry.register('continue_chapter',writing_adapter)
        self.task_coordinator=TaskCoordinator(self.service,registry)
        from novel_writer.application.chapter_writing import ChapterWriting
        self.chapter_writing=ChapterWriting(self.task_coordinator,self.providers)
        from novel_writer.application.comparisons import ComparisonCoordinator
        self.comparisons=ComparisonCoordinator(self.service,self.task_coordinator)
        from novel_writer.application.workflows import WorkflowCoordinator
        self.workflows=WorkflowCoordinator(self.service,self.task_coordinator)
        from novel_writer.application.book_creation import BookCreation
        self.book_creation=BookCreation(self.service)
        from novel_writer.application.book_ai import BookAICoordinator
        self.book_ai=BookAICoordinator(self.task_coordinator,self.providers,self.book_creation,enabled=self.model_generation_enabled)
        from novel_writer.application.chapter_planning import ChapterPlanningCoordinator
        self.chapter_planning=ChapterPlanningCoordinator(self.task_coordinator,self.providers,enabled=self.model_generation_enabled)
        self.comparisons.planning=self.chapter_planning
        from novel_writer.application.scene_expansion import SceneExpansionCoordinator
        self.scene_expansion=SceneExpansionCoordinator(self.task_coordinator,self.providers,enabled=self.model_generation_enabled)
        from novel_writer.application.console import ConsoleCoordinator
        self.console=ConsoleCoordinator(self.service,self.chapter_writing,self.chapter_planning,self.scene_expansion)
        from novel_writer.application.console_background import BackgroundExecutor
        self.console_background=BackgroundExecutor(self.console)
        from novel_writer.application.creative_dialogue import CreativeDialogue
        self.dialogue=CreativeDialogue(self.console,self.book_ai)
        from novel_writer.application.materials import Materials
        self.materials=Materials(self.service)
        from novel_writer.application.full_book_planning import FullBookPlanning
        self.full_book_planning=FullBookPlanning(self.service)
        from novel_writer.application.body_planning import BodyPlanning
        self.body_planning=BodyPlanning(self.service)
        from novel_writer.application.model_planning import ModelPlanningCoordinator
        self.model_planning=ModelPlanningCoordinator(self.task_coordinator,self.providers,enabled=self.model_generation_enabled)
        from novel_writer.application.scoped_rules import RuleCoordinator
        self.scoped_rules=RuleCoordinator(self.service)
        from novel_writer.application.rule_reviews import RuleReviewCoordinator
        self.rule_reviews=RuleReviewCoordinator(self.task_coordinator,self.providers,enabled=self.model_generation_enabled)
        from novel_writer.application.semantic_retrieval import SemanticRetrievalCoordinator
        self.semantic_retrieval=SemanticRetrievalCoordinator(self.task_coordinator,self.providers,enabled=self.model_generation_enabled)
        from novel_writer.application.styles import StyleCoordinator
        self.styles=StyleCoordinator(self.task_coordinator,self.providers,enabled=self.model_generation_enabled)
        from novel_writer.application.public_search import SearchCoordinator
        self.public_search=SearchCoordinator(self.task_coordinator,self.providers,self.styles,enabled=self.model_generation_enabled)
        from novel_writer.application.style_trials import TrialCoordinator
        self.style_trials=TrialCoordinator(self.task_coordinator,self.providers,self.styles,enabled=self.model_generation_enabled)
        self.token = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), Handler)
        # 仅在明确备份操作时加载和创建传输暂存区。
        self._backups = None
        self._backups_lock = threading.Lock()
        self._backups_closed = False

    @property
    def backups(self):
        with self._backups_lock:
            if self._backups is None:
                if self._backups_closed:
                    from novel_writer.application.backups import BackupError
                    raise BackupError('transfer', 'closed', '服务正在关闭，未启动备份操作')
                from novel_writer.ui.backup_routes import BackupTransfers
                self._backups = BackupTransfers(self.database_path,self.drafts.directory)
            return self._backups

    def model_capabilities(self):
        from novel_writer.application.provider_connections import PROVIDERS
        from novel_writer.application.custom_protocols import PROTOCOLS
        saved=self.providers.status() if self.model_generation_enabled else {key:dict(id=key,**value,model_id='') for key,value in PROVIDERS.items()}
        connections=[dict(id=value['id'],name=value['name'],model_id=value['model_id'],adapter_id='configured-http-v2' if value.get('custom') else 'chat-completions-http-v1',protocol=value['protocol'] if value.get('custom') else 'openai-chat') for value in saved.values()]
        return dict(local_protocol_demo=self.local_protocol_demo,offline_audit_enabled=True,real_model_enabled=self.model_generation_enabled,capabilities=['rewrite_chapter','audit_chapter','draft_chapter','continue_chapter','brainstorm_chapter','outline_chapter','expand_scene_selection','review_rule_conflicts','body_planning'],connections=connections,protocols=PROTOCOLS,model_adapters=[dict(adapter_id=adapter.adapter_id,connection_ids=[value['id'] for value in connections if value['adapter_id']==adapter.adapter_id],capabilities=list(adapter.capabilities),enabled=self.model_generation_enabled) for adapter in self.model_adapters],note='模型准备不执行；外发仍须逐次确认正文、确切去向及未知费用。')

    def server_close(self):
        with self._backups_lock:
            self._backups_closed = True
            backups = self._backups
            if backups is not None:
                backups.closed.set()
        # 不持惰性创建锁等待请求线程或执行磁盘清理。
        try:
            super().server_close()
        finally:
            if backups is not None:
                backups.close()
            self.console_background.close()
            self.workflows.close()
            self.task_coordinator.close()


class _PostBodyReader:
    """保留原缓冲reader，仅累计POST解析/上传实际返回的正文长度。"""
    def __init__(self, reader):
        self.reader = reader
        self.consumed = 0

    def read(self, size=-1):
        data = self.reader.read(size)
        self.consumed += len(data) if data else 0
        return data

    def read1(self, size=-1):
        data = self.reader.read1(size)
        self.consumed += len(data) if data else 0
        return data

    def __getattr__(self, name):
        return getattr(self.reader, name)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # 正文、编号与错误内容不输出到终端日志。
        pass

    def send_body(self, status, body: bytes, content_type: str, *, filename=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)
        if self.command == 'POST' and status >= 400:
            self._post_error_response = True

    def send_json(self, status, value, *, filename=None):
        value=self._public_json(value,filename)
        self.send_body(status, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"),
                       "application/json; charset=utf-8", filename=filename)

    def _public_json(self,value,filename):
        # 完整导出是作者有意取得原始资料；普通页面只读取投影，不删改持久记录。
        if filename is not None or type(value) is not dict:return value
        from novel_writer.application.comparisons import hidden_task_ids,public_workspace
        if 'workspace_version' in value and 'document' in value:return public_workspace(value)
        if not any(k in value for k in ('task','tasks','report','reports','task_id','interrupted')):return value
        parts=urlsplit(self.path).path.strip('/').split('/')
        if len(parts)<3 or parts[:2]!=['api','projects']:return value
        hidden=hidden_task_ids(self.server.service.get(parts[2]))
        if not hidden:return value
        if value.get('task_id') in hidden or (type(value.get('task')) is dict and value['task'].get('id') in hidden) or (type(value.get('report')) is dict and value['report'].get('task_id') in hidden):raise BlindProjectionError('未揭晓实验只通过盲评入口读取结果')
        result=dict(value)
        if type(value.get('tasks')) is list:result['tasks']=[v for v in value['tasks'] if v['task']['id'] not in hidden]
        if type(value.get('reports')) is list:result['reports']=[v for v in value['reports'] if v['task_id'] not in hidden]
        if type(value.get('interrupted')) is list:result['interrupted']=[v for v in value['interrupted'] if (v.get('id') if type(v) is dict else v) not in hidden]
        return result

    def reject_request(self, message):
        self.close_connection = True
        self.send_json(403, {"error": message})

    def _finish_rejected_body(self):
        # 所有POST错误出口共享一次收尾；状态码和业务拒绝逻辑不参与分支。
        self.close_connection = True
        self.wfile.flush()
        try:
            length = int(self.headers.get('Content-Length'))
        except (TypeError, ValueError):
            length = -1
        # 长度未知/非法或chunked已被业务拒绝，只丢弃有界数据，不解析其帧。
        remaining = REJECT_DRAIN_BYTES if length < 0 or self.headers.get('Transfer-Encoding') else min(
            max(0, length - self.rfile.consumed), REJECT_DRAIN_BYTES)
        if remaining <= 0:
            return
        # 响应已发出；仅有界接收尚未消费的迟到正文，避免未读数据关闭丢响应。
        # 不解析、不落盘、不进入业务入口，滴流也不能延长总时限。
        deadline = time.monotonic() + REJECT_DRAIN_SECONDS
        original_timeout = self.connection.gettimeout()
        try:
            while remaining:
                seconds = deadline - time.monotonic()
                if seconds <= 0:
                    break
                self.connection.settimeout(seconds)
                chunk = self.rfile.read1(min(remaining, 1024))
                if not chunk:
                    break
                remaining -= len(chunk)
        except OSError:
            pass  # 拒绝后的超时/对端离开仅结束收尾；不更改响应或执行请求。
        finally:
            self.connection.settimeout(original_timeout)

    def allowed_request(self, *, write=False):
        port = self.server.server_address[1]
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        host = self.headers.get("Host", "")
        if host not in hosts:
            self.reject_request("只允许从本机地址访问")
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {f"http://{item}" for item in hosts}:
            self.reject_request("拒绝其他网站的请求")
            return False
        if write and not secrets.compare_digest(self.headers.get("X-Novel-Token", ""), self.server.token):
            self.reject_request("页面会话已失效，请保留输入后重新打开页面")
            return False
        return True

    def do_GET(self):
        if not self.allowed_request():
            return
        path = urlsplit(self.path).path
        service = self.server.service
        try:
            if path == "/api/session":
                self.send_json(200, {"token": self.server.token})
            elif path.startswith('/api/projects/') and path.endswith('/drafts') and len(path.strip('/').split('/'))==4:
                from novel_writer.application.drafts import DraftError
                parts=path.strip('/').split('/');self.server.service.get(parts[2])
                try:self.send_json(200,self.server.drafts.list(parts[2]))
                except DraftError as error:self.send_json(422,{'error':str(error)})
            elif path.startswith('/api/projects/') and path.endswith('/export') and len(path.strip('/').split('/'))==4 and urlsplit(self.path).query:
                parts=path.strip('/').split('/')
                if len(parts)!=4 or parts[3]!='export':raise ValueError('导出入口无效')
                from novel_writer.application.migration_text import export_payload
                query=parse_qs(urlsplit(self.path).query);scope=query.get('scope',['book'])[0];format_=query.get('format',['txt'])[0]
                chapter_id=query.get('chapter_id',[None])[0];volume_raw=query.get('volume_number',[None])[0];volume_number=int(volume_raw) if volume_raw not in (None,'') else None
                payload=export_payload(self.server.service.get(parts[2]),scope,format_,chapter_id,volume_number);body=payload['text'].encode('utf-8')
                self.send_response(200);self.send_header('Content-Type',payload['media_type']);self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+quote(payload['filename']));self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body)
            elif path.startswith('/api/projects/') and '/export/' in path:
                parts=path.strip('/').split('/')
                if len(parts) not in (6,7) or parts[3]!='export':raise ValueError('导出入口无效')
                from novel_writer.application.migration_text import export_payload
                scope,format_=parts[4],parts[5];chapter_id=None;volume_number=None
                if scope=='chapter':chapter_id=parts[6] if len(parts)==7 else None
                elif scope=='volume':volume_number=int(parts[6]) if len(parts)==7 else None
                elif scope!='book' or len(parts)!=6:raise ValueError('导出范围无效')
                payload=export_payload(self.server.service.get(parts[2]),scope,format_,chapter_id,volume_number);body=payload['text'].encode('utf-8')
                self.send_response(200);self.send_header('Content-Type',payload['media_type']);self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+quote(payload['filename']));self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body)
            elif path=='/api/tasks/capabilities':
                self.send_json(200,self.server.model_capabilities())
            elif path=='/api/providers/catalog':
                from novel_writer.application.provider_catalog import catalog
                self.send_json(200,catalog())
            elif path == '/api/backups/capabilities':
                self.send_json(200,{'backup_format_version':51,'full_library':True,
                    'backup_format_versions':list(range(1,52)),'workspace_versions':list(range(1,53)),
                    'independent_restore':True,'merge_restore':False,'credentials_included':False})
            elif path == '/api/migrations/capabilities':
                self.send_json(200,{'new_projects':True,'legacy_json':True,'copy_project':True,
                    'formats':[f'backup_v{version}' for version in range(1,52)]+['sqlite_v1','sqlite_v2','workspace_json_v1','novel_json_v1'],
                    'skills_scope':'all_global','credentials_included':False})
            elif path.startswith('/api/migrations/operations/'):
                if self.allowed_request(write=True): self.handle_migration(path)
            elif path.startswith('/api/backups/download/'):
                self.handle_backup_download(path[len('/api/backups/download/'):])
            elif path.startswith('/api/backups/operations/'):
                if self.allowed_request(write=True):
                    self.handle_backup_status(path[len('/api/backups/operations/'):])
            elif path == "/api/projects":
                self.send_json(200, service.list_projects())
            elif path == "/api/modules":
                self.send_json(200, [*service.modules(), SKILLS_MODULE])
            elif path == "/api/settings":
                # 维护模式不调用环境密钥状态检查，也不读取 DPAPI 文件。
                status = {"model_calls_enabled": False,
                          "providers": {name: {"key_configured": None} for name in ("deepseek", "gemini")}} \
                         if self.server.offline else service.settings()
                self.send_json(200, {**status, "connections": self.server.providers.status(),
                                     "offline_mode": self.server.offline,
                                     "configuration_writes_enabled": self.server.providers.configuration_writes_enabled,
                                     "real_model_enabled": self.server.model_generation_enabled,
                                     "connection_checks_enabled": not self.server.offline,
                                     "credential_storage": "Windows DPAPI · 当前账户加密",
                                     "database_path": str(self.server.database_path)})
            elif path == "/api/skills":
                self.send_json(200, self.server.skills.list_skills())
            elif path.startswith("/api/skills/") and len(path.strip("/").split("/")) == 3:
                self.send_json(200, self.server.skills.get(path.split("/")[-1]))
            elif path.startswith("/api/projects/"):
                preset_parts=path.strip('/').split('/')
                if len(preset_parts) in (4,6) and preset_parts[3]=='author-scope':
                    from novel_writer.application.author_scope import describe,preview
                    state=service.get(preset_parts[2])
                    if len(preset_parts)==4:self.send_json(200,describe(state))
                    elif preset_parts[4]=='preview':self.send_json(200,preview(state,preset_parts[5]))
                    else:raise KeyError('author-scope route')
                    return
                if len(preset_parts)==4 and preset_parts[3]=='trash':
                    self.send_json(200,self.server.service.trash_listing(preset_parts[2]));return
                if len(preset_parts)==6 and preset_parts[3]=='chapters' and preset_parts[5]=='trash-preview':
                    self.send_json(200,self.server.service.trash_preview(preset_parts[2],preset_parts[4]));return
                if len(preset_parts)==6 and preset_parts[3]=='trash' and preset_parts[5]=='preview':
                    self.send_json(200,self.server.service.trash_preview(preset_parts[2],preset_parts[4]));return
                if len(preset_parts) in (4,5) and preset_parts[3]=='style-trials':
                    self.send_json(200,self.server.style_trials.listing(preset_parts[2]) if len(preset_parts)==4 else self.server.style_trials.describe(preset_parts[2],preset_parts[4]));return
                if len(preset_parts)>=4 and preset_parts[3]=='public-search':
                    engine=self.server.public_search
                    if len(preset_parts)==4:self.send_json(200,engine.listing(preset_parts[2]));return
                    if len(preset_parts)==6 and preset_parts[4]=='queries':self.send_json(200,engine.describe(preset_parts[2],preset_parts[5]));return
                    if len(preset_parts)==6 and preset_parts[4]=='reads':self.send_json(200,engine.read_detail(preset_parts[2],preset_parts[5]));return
                    if len(preset_parts)==6 and preset_parts[4]=='search-entry':
                        body=('<!doctype html><meta charset="utf-8">'+engine.search_entry(preset_parts[2],preset_parts[5])).encode('utf-8')
                        self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; img-src data:; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'; sandbox");self.end_headers();self.wfile.write(body);return
                    raise KeyError('public search route')
                if len(preset_parts)>=4 and preset_parts[3]=='styles':
                    if len(preset_parts)==4:self.send_json(200,self.server.styles.listing(preset_parts[2]));return
                    if len(preset_parts)==6 and preset_parts[4]=='sources':self.send_json(200,self.server.styles.source(preset_parts[2],preset_parts[5]));return
                    if len(preset_parts)==6 and preset_parts[4]=='analyses':self.send_json(200,self.server.styles.describe(preset_parts[2],preset_parts[5]));return
                    if len(preset_parts)==6 and preset_parts[4]=='compile':self.send_json(200,self.server.styles.compile(preset_parts[2],preset_parts[5]));return
                    raise KeyError('styles route')
                if len(preset_parts) in (4,5) and preset_parts[3]=='book-ai':self.send_json(200,self.server.book_ai.describe(preset_parts[2],preset_parts[4] if len(preset_parts)==5 else None));return
                if len(preset_parts) in (4,5) and preset_parts[3]=='chapter-planning':self.send_json(200,self.server.chapter_planning.describe(preset_parts[2],preset_parts[4] if len(preset_parts)==5 else None));return
                if len(preset_parts) in (4,5) and preset_parts[3]=='model-planning':self.send_json(200,self.server.model_planning.describe(preset_parts[2],preset_parts[4] if len(preset_parts)==5 else None));return
                if len(preset_parts) in (4,5) and preset_parts[3]=='scene-expansion':self.send_json(200,self.server.scene_expansion.describe(preset_parts[2],preset_parts[4] if len(preset_parts)==5 else None));return
                if len(preset_parts)==4 and preset_parts[3]=='console':self.send_json(200,self.server.console.list(preset_parts[2]));return
                if len(preset_parts)==6 and preset_parts[3]=='console' and preset_parts[4]=='sessions':self.send_json(200,dict(self.server.console.describe(preset_parts[2],preset_parts[5]),dialogue=self.server.dialogue.describe(preset_parts[2],preset_parts[5])));return
                if len(preset_parts)==5 and preset_parts[3]=='console' and preset_parts[4]=='runs':
                    query=parse_qs(urlsplit(self.path).query);self.send_json(200,self.server.console.list_runs(preset_parts[2],query.get('session_id',[None])[0]));return
                if len(preset_parts)==6 and preset_parts[3]=='console' and preset_parts[4]=='runs':
                    self.send_json(200,dict(self.server.console.describe_run(preset_parts[2],preset_parts[5]),background=self.server.console_background.describe(preset_parts[2],preset_parts[5])));return
                if len(preset_parts)==7 and preset_parts[3:5]==['console','runs'] and preset_parts[6]=='background':
                    self.send_json(200,self.server.console_background.describe(preset_parts[2],preset_parts[5]));return
                if len(preset_parts)==4 and preset_parts[3]=='rules':
                    query=parse_qs(urlsplit(self.path).query);self.send_json(200,self.server.scoped_rules.list(preset_parts[2],query.get('chapter_id',[None])[0]));return
                if len(preset_parts)==5 and preset_parts[3]=='rules' and preset_parts[4]=='history':
                    query=parse_qs(urlsplit(self.path).query);self.send_json(200,self.server.scoped_rules.history(preset_parts[2],query.get('rule_id',[None])[0]));return
                if len(preset_parts)==6 and preset_parts[3]=='rules' and preset_parts[4]=='history':self.send_json(200,self.server.scoped_rules.history(preset_parts[2],preset_parts[5]));return
                if len(preset_parts) in (4,5) and preset_parts[3]=='rule-reviews':self.send_json(200,self.server.rule_reviews.describe(preset_parts[2],preset_parts[4] if len(preset_parts)==5 else None));return
                if len(preset_parts) in (4,5) and preset_parts[3]=='semantic-retrieval':self.send_json(200,self.server.semantic_retrieval.describe(preset_parts[2],preset_parts[4] if len(preset_parts)==5 else None));return
                if len(preset_parts)==6 and preset_parts[3]=='rules' and preset_parts[4]=='resolve':self.send_json(200,self.server.scoped_rules.resolve(preset_parts[2],preset_parts[5]));return
                if len(preset_parts)>=4 and preset_parts[3]=='materials':
                    engine=self.server.materials
                    if len(preset_parts)==6 and preset_parts[4]=='index-jobs':self.send_json(200,engine.index_jobs.status(preset_parts[2],preset_parts[5]));return
                    if len(preset_parts)==4:
                        query=parse_qs(urlsplit(self.path).query);include=query.get('include_archived',['1'])[0]
                        if include not in ('0','1'):raise ValueError('资料筛选参数无效')
                        self.send_json(200,engine.listing(preset_parts[2],query.get('tag',[None])[0],include=='1'));return
                    if len(preset_parts)==5:self.send_json(200,engine.describe(preset_parts[2],preset_parts[4]));return
                    if len(preset_parts)==7 and preset_parts[5]=='versions':self.send_json(200,engine.version(preset_parts[2],preset_parts[4],preset_parts[6]));return
                    raise KeyError('materials route')
                if len(preset_parts)==4 and preset_parts[3]=='full-book-planning':
                    self.send_json(200,dict(self.server.full_book_planning.listing(preset_parts[2]),
                                          ai_completion=dict(status='requires_explicit_model_confirmation' if self.server.model_generation_enabled else 'native_model_session_disabled',
                                              reason='原生正文规划模型须逐请求确认，候选仅能独立转待审提案，再经影响预览与人工接受'),
                                          body_planning=self.server.body_planning.listing(preset_parts[2]),
                                          model_planning=self.server.model_planning.describe(preset_parts[2]),
                                          model_capabilities=self.server.model_capabilities()));return
                if len(preset_parts)==4 and preset_parts[3]=='book-creation':self.send_json(200,self.server.book_creation.describe(preset_parts[2]));return
                if len(preset_parts)>=4 and preset_parts[3]=='creation-presets':
                    from novel_writer.application.creation_presets import CreationPresets
                    presets=CreationPresets(service)
                    if len(preset_parts)==4:self.send_json(200,dict(presets.describe(preset_parts[2]),library=presets.library(),connections=self.server.model_capabilities()['connections']));return
                    if len(preset_parts)==6 and preset_parts[5]=='export':self.send_json(200,presets.export(preset_parts[2],preset_parts[4]));return
                    if len(preset_parts)==6 and preset_parts[5]=='preflight':self.send_json(200,presets.preflight(preset_parts[2],preset_parts[4],connections={c['id']:c for c in self.server.model_capabilities()['connections']}));return
                    self.send_json(404,{'error':'创作预设读取入口不存在'});return
                parts = path.strip("/").split("/")
                if len(parts) == 3:
                    self.send_json(200, service.get(parts[2]))
                elif len(parts) == 4 and parts[3] == "export":
                    self.send_json(200, service.get(parts[2]), filename="novel-workspace.json")
                elif len(parts)==4 and parts[3]=='memories':
                    self.send_json(200,service.memory_records(parts[2]))
                elif len(parts)==4 and parts[3]=='memory-refresh':
                    from novel_writer.application.memory_refresh import MemoryRefresh
                    self.send_json(200,MemoryRefresh(service).listing(parts[2]))
                elif len(parts)==4 and parts[3]=='memory-automation':
                    self.send_json(200,service.memory_automation(parts[2]))
                elif len(parts)==4 and parts[3]=='canon-maintenance':
                    self.send_json(200,service.canon_maintenance(parts[2]))
                elif len(parts)==6 and parts[3]=='memories' and parts[5]=='source':
                    self.send_json(200,service.memory_source(parts[2],parts[4]))
                elif len(parts)==4 and parts[3]=='rollups':
                    self.send_json(200,service.memory_rollups(parts[2]))
                elif len(parts)==5 and parts[3]=='rollups' and parts[4]=='conflicts':
                    self.send_json(200,dict(revision=service.get(parts[2])['revision'],conflicts=service.memory_rollups(parts[2])['conflicts']))
                elif len(parts) in (4,5) and parts[3]=='tasks':
                    self.send_json(200,self.server.task_coordinator.describe(parts[2],parts[4] if len(parts)==5 else None))
                elif len(parts)==5 and parts[3]=='adoptions':
                    self.send_json(200,self.server.task_coordinator.receipt(parts[2],parts[4]))
                elif len(parts)==4 and parts[3]=='reviews':
                    saved=service.get(parts[2]);self.send_json(200,dict(revision=saved['revision'],reports=saved.get('review_reports',[])))
                elif len(parts)==5 and parts[3]=='reviews':
                    self.send_json(200,self.server.task_coordinator.review_report(parts[2],parts[4]))
                elif len(parts)==5 and parts[3]=='model-reviews':
                    self.send_json(200,self.server.task_coordinator.model_review(parts[2],parts[4]))
                elif len(parts) in (5,6) and parts[3]=='deep-review-books':
                    from novel_writer.application.deep_reviews import DeepReviews
                    engine=DeepReviews(self.server.task_coordinator)
                    if len(parts)==5 and parts[4]=='list':self.send_json(200,engine.list_books(parts[2]))
                    elif len(parts)==5:self.send_json(200,engine.describe_book(parts[2],parts[4]))
                    else:raise KeyError('book review route')
                elif len(parts)==5 and parts[3]=='deep-reviews':
                    from novel_writer.application.deep_reviews import DeepReviews
                    self.send_json(200,DeepReviews(self.server.task_coordinator).describe(parts[2],parts[4]))
                elif len(parts)==4 and parts[3]=='model-reviews':
                    state=service.get(parts[2]);self.send_json(200,dict(revision=state['revision'],reports=state.get('model_reports',[])))
                elif len(parts)==4 and parts[3]=='knowledge':
                    from novel_writer.application.knowledge import view
                    self.send_json(200,view(service,parts[2],{}))
                elif len(parts) in (4,5,6) and parts[3]=='comparisons':
                    if len(parts)==4:
                        state=service.get(parts[2]);self.send_json(200,dict(revision=state['revision'],experiments=[dict(id=e['id'],title=e['title']) for e in state.get('comparison_experiments',[])]))
                    elif len(parts)==5:self.send_json(200,self.server.comparisons.blind(parts[2],parts[4]))
                    elif parts[5]=='setup':self.send_json(200,self.server.comparisons.setup(parts[2],parts[4]))
                    else:self.send_json(404,{'error':'比较入口不存在'})
                elif len(parts) in (4,6) and parts[3]=='extensions':
                    from novel_writer.application.extensions import export_template
                    from novel_writer.application.extension_policy import dependencies,policy_for
                    if len(parts)==4:
                        state=service.get(parts[2]);policy=policy_for(service);self.send_json(200,dict(revision=state['revision'],versions=state.get('extension_templates',[]),presets=state.get('generation_presets',[]),dependencies=dependencies(state,policy=policy),authorizations=[policy.status(parts[2],v) for v in state.get('extension_templates',[])]))
                    elif parts[5]=='export':self.send_json(200,export_template(service,parts[2],parts[4]),filename='public-template.json')
                    else:self.send_json(404,{'error':'模板入口不存在'})
                elif len(parts)>=4 and parts[3]=='workflows':
                    engine=self.server.workflows
                    if len(parts)==4:
                        state=service.get(parts[2]);self.send_json(200,dict(revision=state['revision'],templates=state.get('workflow_templates',[]),runs=[dict(id=r['id'],name=r['template']['name'],status=next(e['status'] for e in reversed(state['workflow_run_events']) if e['run_id']==r['id'])) for r in state.get('workflow_runs',[])]))
                    elif len(parts)==6 and parts[4]=='runs':self.send_json(200,engine.describe(parts[2],parts[5]))
                    elif len(parts)==7 and parts[4]=='templates' and parts[6]=='export':self.send_json(200,engine.export_template(parts[2],parts[5]),filename='public-workflow.json')
                    else:self.send_json(404,{'error':'工作流读取入口不存在'})
                else:
                    self.send_json(404, {"error": "找不到这个入口"})
            else:
                assets = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                          "/api.js": ("api.js", "text/javascript"), "/state.js": ("state.js", "text/javascript"),
                          "/layout.js": ("layout.js", "text/javascript"), "/views.js": ("views.js", "text/javascript"),
                          "/memory_automation.js": ("memory_automation.js", "text/javascript"),
                          "/i18n.js": ("i18n.js", "text/javascript"),
                          "/provider_views.js": ("provider_views.js", "text/javascript"),
                          "/sampling.js": ("sampling.js", "text/javascript"),
                          "/creative_dialogue.js": ("creative_dialogue.js", "text/javascript"),
                          "/creation_presets.js": ("creation_presets.js", "text/javascript"),
                          "/workflow_editor.js": ("workflow_editor.js", "text/javascript"),
                          "/styles.js": ("styles.js", "text/javascript"),
                          "/public_search.js": ("public_search.js", "text/javascript"),
                          "/style_trials.js": ("style_trials.js", "text/javascript"),
                          "/chapter_writing.js": ("chapter_writing.js", "text/javascript"),
                          "/chapter_planning.js": ("chapter_planning.js", "text/javascript"),
                          "/model_planning.js": ("model_planning.js", "text/javascript"),
                          "/scene_expansion.js": ("scene_expansion.js", "text/javascript"),
                          "/writing_candidates.js": ("writing_candidates.js", "text/javascript"),
                          "/migration.js": ("migration.js", "text/javascript"),
                          "/chapter_management.js": ("chapter_management.js", "text/javascript"),
                          "/provider_management.js": ("provider_management.js", "text/javascript"),
                          "/console.js": ("console.js", "text/javascript"),
                          "/console_usage.js": ("console_usage.js", "text/javascript"),
                          "/rules_scope.js": ("rules_scope.js", "text/javascript"),
                          "/rule_reviews.js": ("rule_reviews.js", "text/javascript"),
                          "/semantic_retrieval.js": ("semantic_retrieval.js", "text/javascript"),
                          "/materials.js": ("materials.js", "text/javascript"),
                          "/full_book_planning.js": ("full_book_planning.js", "text/javascript"),
                          "/book_creation.js": ("book_creation.js", "text/javascript"),
                          "/book_ai.js": ("book_ai.js", "text/javascript"),
                          "/knowledge.js": ("knowledge.js", "text/javascript"),
                          "/graph_view.js": ("graph_view.js", "text/javascript"),
                          "/model_tasks.js": ("model_tasks.js", "text/javascript"),
                          "/deep_reviews.js": ("deep_reviews.js", "text/javascript"),
                          "/comparison_views.js": ("comparison_views.js", "text/javascript"),
                          "/workflow_views.js": ("workflow_views.js", "text/javascript"),
                          "/style.css": ("style.css", "text/css"), "/local_data.js": ("local_data.js", "text/javascript"), "/author_scope.js": ("author_scope.js", "text/javascript"), "/favicon.svg": ("favicon.svg", "image/svg+xml"),
                          "/guide.html": ("guide.html", "text/html")}
                if path not in assets:
                    self.send_json(404, {"error": "找不到这个入口"})
                else:
                    name, mime = assets[path]
                    self.send_body(200, (STATIC / name).read_bytes(), mime + "; charset=utf-8")
        except BlindProjectionError as error:
            self.send_json(422,{'error':str(error)})
        except KeyError:
            self.send_json(404, {"error": "找不到这份资料"})
        except (ValueError, OSError, sqlite3.Error):
            self.send_json(500, {"error": "读取失败，请检查数据文件；现有数据没有被修改"})

    def do_POST(self):
        # 在请求头解析完成后开始计数，仍使用原rfile及其缓冲/关闭行为。
        self.rfile = _PostBodyReader(self.rfile)
        self._post_error_response = False
        try:
            self._handle_post()
        finally:
            if self._post_error_response:
                self._finish_rejected_body()

    def _handle_post(self):
        if not self.allowed_request(write=True):
            return
        path = urlsplit(self.path).path
        if path.startswith('/api/migrations/'):
            self.handle_migration(path)
            return
        if path in ('/api/backups/export', '/api/backups/restore') or path.startswith('/api/backups/operations/'):
            self.handle_backup(path)
            return
        try:
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                raise ValueError("写操作必须提交 JSON")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                self.send_json(413, {"error": "请求为空或超过 12 MiB 限制，请拆分章节"})
                return
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if type(payload) is not dict:
                raise ValueError("提交内容必须是对象")
            path = urlsplit(self.path).path
            if path == '/api/settings/local-data/preview':
                if payload:raise ValueError('本地诊断预览不接受文件路径或其他字段')
                self.server.local_data.offline=self.server.offline
                self.server.local_data.models_enabled=self.server.model_generation_enabled
                self.send_json(200,self.server.local_data.preview());return
            if path == '/api/settings/local-data/cleanup':
                if set(payload)!={'preview_token','selected','confirmation'}:raise ValueError('本地清理仅接受预览编号、已选条目和确认')
                self.send_json(200,self.server.local_data.cleanup(**payload));return
            if path == '/api/providers/manage':
                self.send_json(200,self.server.providers.manage(**payload));return
            if path == '/api/providers/estimate':
                from novel_writer.application.provider_catalog import estimate
                self.send_json(200,estimate(payload));return
            if path == '/api/providers/custom':
                if set(payload)!={'id','name','base_url','protocol','model_id','api_key','allow_local'}:raise ValueError('自建供应商字段缺失或含未知字段')
                self.send_json(201,self.server.providers.save_custom(**payload));return
            if path == "/api/providers/save":
                if set(payload) != {"id", "base_url", "model_id", "api_key"}:
                    raise ValueError("API 配置参数不完整或含未知字段")
                self.send_json(200, self.server.providers.save(**payload))
                return
            if path == "/api/providers/test":
                if set(payload) != {"id"}:
                    raise ValueError("连接检查只接受站点编号")
                self.send_json(200, self.server.providers.test_connection(payload["id"]))
                return
            if path == "/api/projects":
                self.send_json(201, self.server.service.create(**payload))
                return
            if path == "/api/skills/import":
                if set(payload) != {"files"}:
                    raise ValueError("导入参数必须只包含 files")
                self.send_json(201, self.server.skills.import_files(payload["files"]))
                return
            parts = path.strip("/").split("/")
            if len(parts)==5 and parts[:2]==['api','projects'] and parts[3]=='import' and parts[4]=='preview':
                from novel_writer.application.migration_text import preview
                if set(payload)!={'filename','content_base64','encoding'}:raise ValueError('导入预览字段不完整或含未知字段')
                state=self.server.service.get(parts[2]);self.send_json(200,preview(parts[2],base64.b64decode(payload['content_base64'],validate=True),payload['encoding'],state,payload['filename']));return
            if len(parts)==5 and parts[:2]==['api','projects'] and parts[3]=='import' and parts[4]=='commit':
                if set(payload)!={'expected_revision','filename','content_base64','encoding','items','preview_sha256','confirmed'}:raise ValueError('导入提交字段不完整或含未知字段')
                expected=payload.pop('expected_revision');self.send_json(200,self.server.service.execute(parts[2],'import_chapters',payload,expected_revision=expected));return
            if len(parts)==4 and parts[:2]==['api','projects'] and parts[3]=='drafts':
                from novel_writer.application.drafts import DraftError
                self.server.service.get(parts[2])
                if set(payload)!={'document_key','base_revision','values','position'}:raise ValueError('草稿字段不完整或含未知字段')
                try:self.send_json(200,self.server.drafts.save(parts[2],payload['document_key'],payload['base_revision'],payload['values'],payload['position']))
                except DraftError as error:self.send_json(422,{'error':str(error)})
                return
            if len(parts)==5 and parts[:2]==['api','projects'] and parts[3]=='drafts' and parts[4]=='clear':
                from novel_writer.application.drafts import DraftError
                self.server.service.get(parts[2])
                if set(payload)!={'document_key'}:raise ValueError('清除草稿只接受文档键')
                try:self.send_json(200,self.server.drafts.clear(parts[2],payload['document_key']))
                except DraftError as error:self.send_json(422,{'error':str(error)})
                return
            if len(parts)==5 and parts[:2]==['api','projects'] and parts[3]=='chapter-writing':
                method={'preview':self.server.chapter_writing.preview,'prepare':self.server.chapter_writing.prepare}.get(parts[4])
                if method is None:raise KeyError('chapter writing route')
                self.send_json(200 if parts[4]=='preview' else 201,method(parts[2],payload));return
            if len(parts)>=5 and parts[:2]==['api','projects'] and parts[3]=='style-trials':
                engine=self.server.style_trials
                if len(parts)==5:
                    method={'preview':engine.preview,'prepare':engine.prepare,'compare':engine.create_comparison,'choose':engine.choose}.get(parts[4])
                    if method is None:raise KeyError('style trial route')
                    self.send_json(200 if parts[4]=='preview' else 201,method(parts[2],payload));return
                if len(parts)==6:
                    from novel_writer.application.comparisons import hidden_task_ids
                    if parts[4] in hidden_task_ids(self.server.service.get(parts[2])):raise ValueError('trial.arena_owned')
                if len(parts)==6 and parts[5]=='execute':self.send_json(200,engine.start(parts[2],parts[4],payload));return
                if len(parts)==6 and parts[5]=='cancel':
                    if payload!={}:raise ValueError('trial.invalid_input')
                    self.send_json(200,engine.cancel(parts[2],parts[4]));return
                raise KeyError('style trial route')
            if len(parts)>=5 and parts[:2]==['api','projects'] and parts[3]=='public-search':
                engine=self.server.public_search
                if len(parts)==5:
                    method={'prepare':engine.prepare,'choose-identity':engine.choose_identity,'prepare-read':engine.prepare_read,'import-sample':engine.import_sample}.get(parts[4])
                    if method is None:raise KeyError('public search route')
                    self.send_json(201,method(parts[2],payload));return
                if len(parts)==7 and parts[4] in ('queries','reads'):
                    if parts[6]=='execute':self.send_json(200,(engine.start if parts[4]=='queries' else engine.start_read)(parts[2],parts[5],payload));return
                    if parts[6]=='cancel':
                        if payload!={}:raise ValueError('search.invalid_input')
                        self.send_json(200,engine.cancel(parts[2],parts[5]));return
                raise KeyError('public search route')
            if len(parts)>=5 and parts[:2]==['api','projects'] and parts[3]=='styles':
                engine=self.server.styles
                if len(parts)==5:
                    method={'import-source':engine.import_source,'import-card':engine.import_card,'create-analysis':engine.create_analysis,'prepare-next':engine.prepare_next,'correct':engine.correct,'save-card':engine.save_card,'choose':engine.choose,'extend-budget':engine.extend_budget}.get(parts[4])
                    if method is None:raise KeyError('styles route')
                    self.send_json(200 if parts[4]=='choose' else 201,method(parts[2],payload));return
                if len(parts)==7 and parts[4]=='requests':
                    if parts[6]=='execute':self.send_json(200,engine.start(parts[2],parts[5],payload));return
                    if parts[6]=='cancel':
                        if payload!={}:raise ValueError('styles.invalid_input')
                        self.send_json(200,engine.cancel(parts[2],parts[5]));return
                raise KeyError('styles route')
            if len(parts)>=5 and parts[:2]==['api','projects'] and parts[3]=='book-ai':
                engine=self.server.book_ai
                if len(parts)==5:
                    method={'prepare':engine.prepare,'correct':engine.correct,'review':engine.review,'accept':engine.accept}.get(parts[4])
                    if method is None:raise KeyError('book AI route')
                    self.send_json(201 if parts[4] in ('prepare','correct','review') else 200,method(parts[2],payload));return
                if len(parts)==6 and parts[5]=='execute':self.send_json(200,engine.start(parts[2],parts[4],payload));return
                if len(parts)==6 and parts[5]=='cancel':
                    if payload!={}:raise ValueError('book_ai.cancel_fields')
                    self.send_json(200,engine.cancel(parts[2],parts[4]));return
                raise KeyError('book AI route')
            if len(parts)>=5 and parts[:2]==['api','projects'] and parts[3]=='chapter-planning':
                engine=self.server.chapter_planning
                from novel_writer.application.comparisons import hidden_task_ids
                if payload.get('task_id',parts[4]) in hidden_task_ids(self.server.service.get(parts[2])):raise ValueError('未揭晓多候选须通过比较入口操作')
                if len(parts)==5:
                    method={'preview':engine.preview,'prepare':engine.prepare,'correct':engine.correct,'review':engine.review,'accept':engine.accept}.get(parts[4])
                    if method is None:raise KeyError('chapter planning route')
                    self.send_json(200 if parts[4]=='preview' else 201 if parts[4] in ('prepare','correct','review') else 200,method(parts[2],payload));return
                if len(parts)==6 and parts[5]=='execute':self.send_json(200,engine.start(parts[2],parts[4],payload));return
                if len(parts)==6 and parts[5]=='cancel':
                    if payload!={}:raise ValueError('chapter_planning.cancel_fields')
                    self.send_json(200,engine.cancel(parts[2],parts[4]));return
                raise KeyError('chapter planning route')
            if len(parts)>=5 and parts[:2]==['api','projects'] and parts[3]=='scene-expansion':
                engine=self.server.scene_expansion
                from novel_writer.application.comparisons import hidden_task_ids
                if payload.get('task_id',parts[4]) in hidden_task_ids(self.server.service.get(parts[2])):raise ValueError('未揭晓多候选须通过比较入口操作')
                if len(parts)==5:
                    method={'preview':engine.preview,'prepare':engine.prepare,'correct':engine.correct,'review':engine.review,'accept':engine.accept}.get(parts[4])
                    if method is None:raise KeyError('scene expansion route')
                    self.send_json(200 if parts[4]=='preview' else 201 if parts[4] in ('prepare','correct','review') else 200,method(parts[2],payload));return
                if len(parts)==6 and parts[5]=='execute':self.send_json(200,engine.start(parts[2],parts[4],payload));return
                if len(parts)==6 and parts[5]=='cancel':
                    if payload!={}:raise ValueError('scene_expansion.cancel_fields')
                    self.send_json(200,engine.cancel(parts[2],parts[4]));return
                raise KeyError('scene expansion route')
            if len(parts)==5 and parts[:2]==['api','projects'] and parts[3]=='dialogue' and parts[4]=='prepare':
                self.send_json(201,self.server.dialogue.prepare(parts[2],payload));return
            if len(parts)>=5 and parts[:2]==['api','projects'] and parts[3]=='console':
                engine=self.server.console
                if len(parts)==5 and parts[4]=='sessions':self.send_json(201,engine.create(parts[2],payload));return
                if len(parts)==5 and parts[4]=='runs':self.send_json(201,engine.start(parts[2],payload));return
                if len(parts)==7 and parts[4]=='sessions':
                    method={'rename':engine.rename,'archive':engine.archive,'messages':engine.append_message,'plan':engine.save_plan,'dispatch':engine.dispatch,'proposal-preview':engine.preview_plan,'candidate-plan':engine.candidate_plan}.get(parts[6])
                    if method is None:raise KeyError('console route')
                    self.send_json(201 if parts[6] in ('messages',) else 200,method(parts[2],dict(payload,session_id=parts[5])));return
                if len(parts)==8 and parts[4]=='runs' and parts[6]=='background':
                    background=self.server.console_background
                    action=parts[7]
                    if action=='recover':
                        if payload!={}:raise ValueError('后台恢复核对只接受空参数')
                        background.describe(parts[2],parts[5])
                        background.recover(parts[2])
                        self.send_json(200,background.describe(parts[2],parts[5]));return
                    if action=='preview':self.send_json(200,background.preview(parts[2],parts[5],payload));return
                    if action=='start':
                        self.send_json(202,background.start(parts[2],parts[5],payload));return
                    if action in ('pause','cancel'):
                        if payload!={}:raise ValueError('后台控制只接受空参数')
                        self.send_json(200,background.control(parts[2],parts[5],action));return
                    raise KeyError('console background route')
                if len(parts)==7 and parts[4]=='runs':
                    method={'advance':engine.advance,'pause':engine.pause,'resume':engine.resume,'cancel':engine.cancel,'skip':engine.skip}.get(parts[6])
                    if method is None:raise KeyError('console route')
                    self.send_json(200,method(parts[2],payload,parts[5]));return
                raise KeyError('console route')
            if len(parts)>=5 and parts[:2]==['api','projects'] and parts[3]=='semantic-retrieval':
                engine=self.server.semantic_retrieval
                if len(parts)==5:
                    method={'preview':engine.preview,'prepare':engine.prepare}.get(parts[4])
                    if parts[4]=='recover':
                        if payload:raise ValueError('semantic_retrieval.recover_fields')
                        self.send_json(200,engine.recover(parts[2]));return
                    if method is not None:self.send_json(200,method(parts[2],payload));return
                if len(parts)==6:
                    if parts[5]=='cancel':
                        if payload:raise ValueError('semantic_retrieval.cancel_fields')
                        self.send_json(200,engine.cancel(parts[2],parts[4]));return
                    method={'execute':engine.start,'inspect':engine.inspect}.get(parts[5])
                    if method is not None:self.send_json(200,method(parts[2],parts[4],payload));return
                raise KeyError('semantic retrieval route')
            if len(parts)>=5 and parts[:2]==['api','projects'] and parts[3]=='rule-reviews':
                engine=self.server.rule_reviews
                if len(parts)==5:
                    method={'preview':engine.preview,'prepare':engine.prepare}.get(parts[4])
                    if parts[4]=='recover':
                        if payload:raise ValueError('rule_reviews.recover_fields')
                        self.send_json(200,engine.recover(parts[2]));return
                    if method is not None:self.send_json(200,method(parts[2],payload));return
                if len(parts)==6:
                    if parts[5]=='cancel':
                        if payload:raise ValueError('rule_reviews.cancel_fields')
                        self.send_json(200,engine.cancel(parts[2],parts[4]));return
                    method={'execute':engine.start,'inspect':engine.inspect}.get(parts[5])
                    if method is not None:self.send_json(200,method(parts[2],parts[4],payload));return
                raise KeyError('rule reviews route')
            if len(parts)==5 and parts[:2]==['api','projects'] and parts[3]=='rules':
                engine=self.server.scoped_rules
                method={'save':engine.save,'enabled':engine.set_enabled,'archive':engine.archive,'delete':engine.delete,'import-preview':engine.preview_import,'import':engine.import_rules,'bind-task':engine.bind_task,'resolve-task':engine.resolve_task,'semantic-preview':engine.semantic_preview}.get(parts[4])
                if method is None:raise KeyError('rules route')
                self.send_json(200,method(parts[2],payload));return
            if len(parts)==4 and parts[:2]==['api','projects'] and parts[3]=='memory-refresh':
                from novel_writer.application.memory_refresh import MemoryRefresh
                self.send_json(200,MemoryRefresh(self.server.service).change(parts[2],payload));return
            if len(parts)==4 and parts[:2]==['api','projects'] and parts[3]=='memory-automation':
                self.send_json(200,self.server.service.change_memory_automation(parts[2],payload));return
            if len(parts)==4 and parts[:2]==['api','projects'] and parts[3]=='canon-maintenance':
                if payload.get('action') == 'rollback':
                    payload={key:value for key,value in payload.items() if key != 'action'}
                    self.send_json(200,self.server.service.rollback_canon_maintenance(parts[2],payload))
                else:
                    self.send_json(200,self.server.service.configure_canon_maintenance(parts[2],payload))
                return
            if len(parts)>=4 and parts[:2]==['api','projects'] and parts[3]=='materials':
                engine=self.server.materials
                if len(parts)==7 and parts[4]=='index-jobs' and parts[6]=='cancel':
                    if payload!={}:raise ValueError('取消索引任务只接受空参数')
                    self.send_json(200,engine.index_jobs.cancel(parts[2],parts[5]));return
                if len(parts)==4:self.send_json(201,engine.create(parts[2],payload));return
                if len(parts)==5 and parts[4]=='rebuild-all':self.send_json(200,engine.rebuild_all(parts[2],payload));return
                if len(parts)==5:self.send_json(200,engine.update(parts[2],parts[4],payload));return
                if len(parts)==6:
                    if parts[5]=='index-jobs':self.send_json(202,engine.index_jobs.start(parts[2],parts[4],payload));return
                    if parts[5]=='suggest-tags':self.send_json(200,engine.suggest_tags(parts[2],parts[4],payload));return
                    method={'update':engine.update,'archive':engine.archive,'restore':engine.restore,'rebuild':engine.rebuild}.get(parts[5])
                    if method is not None:self.send_json(200,method(parts[2],parts[4],payload));return
                raise KeyError('materials route')
            if len(parts)>=5 and parts[:2]==['api','projects'] and parts[3]=='model-planning':
                engine=self.server.model_planning
                if len(parts)==5:
                    method={'preview':engine.preview,'prepare':engine.prepare,'transfer-preview':engine.preview_transfer,'propose':engine.propose}.get(parts[4])
                    if method is None:raise KeyError('model planning route')
                    self.send_json(200,method(parts[2],payload));return
                if len(parts)==6 and parts[5]=='execute':self.send_json(200,engine.start(parts[2],parts[4],payload));return
                if len(parts)==6 and parts[5]=='cancel':self.send_json(200,engine.cancel(parts[2],parts[4],payload));return
                raise KeyError('model planning route')
            if len(parts)==5 and parts[:2]==['api','projects'] and parts[3]=='body-planning':
                engine=self.server.body_planning
                method={'prepare':engine.prepare,'infer':engine.infer,'preview':engine.preview,'decide':engine.decide,
                        'set-lock':engine.set_lock,'lifecycle':engine.lifecycle,'references':engine.references,
                        'completion':engine.completion}.get(parts[4])
                if method is None:raise KeyError('body planning route')
                self.send_json(200,method(parts[2],payload));return
            if len(parts)==5 and parts[:2]==['api','projects'] and parts[3]=='full-book-planning' and parts[4]=='actions':
                action=payload.get('action')
                if type(action) is not str:raise ValueError('全书规划操作缺少action')
                request={key:value for key,value in payload.items() if key!='action'}
                self.send_json(200,self.server.full_book_planning.act(parts[2],action,request));return
            if len(parts)==5 and parts[:2]==['api','projects'] and parts[3]=='book-creation':
                method={'start':self.server.book_creation.start,'fork':self.server.book_creation.fork,'save-step':self.server.book_creation.save_step,'choose':self.server.book_creation.choose,'set-lock':self.server.book_creation.set_lock,'preview':self.server.book_creation.preview,'decide':self.server.book_creation.decide}.get(parts[4])
                if method is None:raise KeyError('book creation route')
                self.send_json(201 if parts[4] in ('start','fork','save-step','preview') else 200,method(parts[2],payload));return
            if len(parts)==5 and parts[:2]==['api','projects'] and parts[3]=='creation-presets':
                from novel_writer.application.creation_presets import CreationPresets
                presets=CreationPresets(self.server.service)
                method={'save':presets.save,'choose':presets.choose,'reuse':presets.reuse,'import':presets.import_preset}.get(parts[4])
                if method is None:raise KeyError('creation preset route')
                self.send_json(201 if parts[4] in ('save','reuse','import') else 200,method(parts[2],payload));return
            if len(parts)>=5 and parts[:2]==['api','projects'] and parts[3]=='workflows':
                engine=self.server.workflows
                if len(parts)==5 and parts[4]=='preflight':self.send_json(200,engine.preflight(payload));return
                if len(parts)==5 and parts[4]=='templates':self.send_json(201,engine.import_template(parts[2],payload));return
                if len(parts)==5 and parts[4]=='runs':self.send_json(201,engine.create(parts[2],payload));return
                if len(parts)==7 and parts[4]=='runs':
                    if parts[6]=='control':
                        if set(payload)!={'action'}:raise ValueError('运行控制只接受action')
                        self.send_json(200,engine.control(parts[2],parts[5],payload['action']));return
                    if parts[6]=='step':
                        if payload!={}:raise ValueError('单步不接受任意output或授权字段')
                        self.send_json(200,engine.step(parts[2],parts[5]));return
                    if parts[6]=='retry':
                        if set(payload)!={'node_id'}:raise ValueError('明确重跑只接受节点身份')
                        self.send_json(200,engine.retry(parts[2],parts[5],payload['node_id']));return
                if len(parts)==9 and parts[4]=='runs' and parts[6]=='nodes' and parts[8]=='confirm':self.send_json(200,engine.confirm(parts[2],parts[5],parts[7],payload));return
                self.send_json(404,{'error':'工作流操作入口不存在'});return
            if len(parts) in (4,6) and parts[:2]==['api','projects'] and parts[3]=='comparisons':
                c=self.server.comparisons
                if len(parts)==4:self.send_json(201,c.create(parts[2],payload));return
                if parts[5]=='execute':
                    if set(payload)!={'configuration_id','confirm_external','request_sha256'}:raise ValueError('比较执行只接受配置身份与单次请求确认')
                    self.send_json(202,c.execute(parts[2],parts[4],payload['configuration_id'],{k:payload[k] for k in ('confirm_external','request_sha256')}));return
                if parts[5]=='score':self.send_json(200,c.score(parts[2],parts[4],payload));return
                if parts[5]=='cancel':
                    if set(payload)!={'configuration_id'}:raise ValueError('trial.invalid_input')
                    self.send_json(200,c.cancel(parts[2],parts[4],payload['configuration_id']));return
                if parts[5]=='reveal':self.send_json(200,c.reveal(parts[2],parts[4],payload));return
                if parts[5]=='choose':self.send_json(200,c.choose(parts[2],parts[4],payload));return
                self.send_json(404,{'error':'比较操作不存在'});return
            if len(parts)==5 and parts[:2]==['api','projects'] and parts[3]=='extensions':
                from novel_writer.application.extensions import preflight,import_template,reference_preview
                from novel_writer.application.extension_policy import policy_for
                if parts[4]=='preflight':self.send_json(200,preflight(payload));return
                if parts[4]=='import':self.send_json(201,import_template(self.server.service,parts[2],payload));return
                if parts[4]=='authorization':self.send_json(200,policy_for(self.server.service).change(self.server.service,parts[2],payload));return
                if parts[4]=='reference-preview':self.send_json(200,reference_preview(self.server.service,parts[2],payload));return
                self.send_json(404,{'error':'模板操作不存在'});return
            if len(parts)>=5 and parts[:2]==['api','projects'] and parts[3]=='deep-review-books':
                from novel_writer.application.deep_reviews import DeepReviews
                engine=DeepReviews(self.server.task_coordinator)
                if len(parts)==5 and parts[4]=='create':self.send_json(201,engine.create_book(parts[2],payload));return
                if len(parts)==6 and parts[5]=='prepare':self.send_json(201,engine.prepare_batch(parts[2],parts[4],payload));return
                raise KeyError('book review route')
            if len(parts)>=5 and parts[:2]==['api','projects'] and parts[3]=='deep-reviews':
                from novel_writer.application.deep_reviews import DeepReviews
                engine=DeepReviews(self.server.task_coordinator)
                if len(parts)==5 and parts[4]=='prepare':self.send_json(201,engine.prepare(parts[2],payload));return
                if len(parts)==6 and parts[5]=='decision':self.send_json(200,engine.decide(parts[2],parts[4],payload));return
                raise KeyError('deep review route')
            if len(parts)==6 and parts[:2]==['api','projects'] and parts[3]=='model-reviews' and parts[5]=='proposal':
                from novel_writer.application.comparisons import hidden_task_ids
                state=self.server.service.get(parts[2]);report=next((r for r in state.get('model_reports',[]) if r['id']==parts[4]),None)
                if report and report['task_id'] in hidden_task_ids(state):raise ValueError('未揭晓比较不能经报告入口执行写入')
                self.send_json(200,self.server.task_coordinator.decide_model_proposal(parts[2],parts[4],payload));return
            if len(parts)==5 and parts[:2]==['api','projects'] and parts[3]=='knowledge':
                from novel_writer.application.knowledge import command,view,merge_preview,source_detail
                if parts[4]=='paths':
                    from novel_writer.application.graph_queries import paths
                    result=paths(self.server.service,parts[2],payload)
                elif parts[4]=='rebuild-index':
                    from novel_writer.application.graph_index import rebuild
                    result=rebuild(self.server.service,parts[2],payload)
                elif parts[4] in ('extract-prepare','extract-list','extract-decide'):
                    from novel_writer.application.graph_extraction import prepare,describe,decide
                    result={'extract-prepare':prepare,'extract-list':describe,'extract-decide':decide}[parts[4]](self.server.task_coordinator,parts[2],payload)
                elif parts[4]=='query':result=view(self.server.service,parts[2],payload)
                elif parts[4]=='merge-preview':result=merge_preview(self.server.service,parts[2],payload)
                elif parts[4]=='source':result=source_detail(self.server.service,parts[2],payload)
                else:result=command(self.server.service,parts[2],parts[4],payload)
                self.send_json(200,result);return
            if len(parts)==6 and parts[:2]==['api','projects'] and parts[3]=='reviews':
                if parts[5]=='issue':self.send_json(200,self.server.task_coordinator.review_issue(parts[2],parts[4],payload));return
                if parts[5]=='proposal':self.send_json(200,self.server.task_coordinator.decide_proposal(parts[2],parts[4],payload));return
            if len(parts) in (5,6) and parts[:2]==['api','projects'] and parts[3]=='tasks':
                coordinator=self.server.task_coordinator
                from novel_writer.application.comparisons import hidden_task_ids
                if parts[4] in hidden_task_ids(self.server.service.get(parts[2])):raise ValueError('未揭晓比较任务须从配置确认/盲评入口操作')
                if len(parts)==5 and parts[4]=='prepare':self.send_json(201,coordinator.prepare(parts[2],payload));return
                if len(parts)==5 and parts[4]=='recover':
                    if payload!={}:raise ValueError('中断核对只接受空参数')
                    self.send_json(200,coordinator.recover(parts[2]));return
                if len(parts)==6:
                    if parts[5]=='writing-correction':self.send_json(201,self.server.chapter_writing.correct(parts[2],parts[4],payload));return
                    if parts[5]=='writing-review':self.send_json(200,self.server.chapter_writing.review(parts[2],parts[4],payload));return
                    if parts[5]=='cancel' and payload!={}:raise ValueError('取消不接受输出、scenario或额外参数')
                    if parts[5]=='execute':self.send_json(202,coordinator.start(parts[2],parts[4],confirmation=payload));return
                    if parts[5]=='cancel':self.send_json(200,coordinator.cancel(parts[2],parts[4]));return
                    if parts[5]=='adopt':self.send_json(200,coordinator.adopt(parts[2],parts[4],payload));return
                self.send_json(404,{'error':'任务入口不存在'});return
            if len(parts)==4 and parts[:2]==['api','projects'] and parts[3]=='context-preview':
                self.send_json(200,self.server.service.preview_context(parts[2],payload))
                return
            if len(parts)==5 and parts[:2]==['api','projects'] and parts[3]=='model-summaries' and parts[4]=='prepare':
                from novel_writer.application.semantic_summaries import prepare
                self.send_json(201,prepare(self.server.task_coordinator,parts[2],payload));return
            if len(parts)==5 and parts[:2]==['api','projects'] and parts[3]=='rollups' and parts[4]=='preview':
                self.send_json(200,self.server.service.preview_memory_rollup(parts[2],payload));return
            if len(parts)==4 and parts[:2]==['api','projects'] and parts[3]=='rollups':
                self.send_json(201,self.server.service.save_memory_rollup(parts[2],payload));return
            if len(parts)==6 and parts[:2]==['api','projects'] and parts[3]=='rollups' and parts[5]=='rebuild':
                self.send_json(200,self.server.service.rebuild_memory_rollup(parts[2],parts[4],payload));return
            if len(parts)==4 and parts[:2]==['api','projects'] and parts[3]=='search':
                self.send_json(200,self.server.service.search_local(parts[2],payload))
                return
            if len(parts) != 4 or parts[:2] != ["api", "projects"] or parts[3] != "actions":
                self.send_json(404, {"error": "找不到这个入口"})
                return
            if set(payload) != {"action", "fields", "expected_revision"}:
                raise ValueError("操作参数不完整或含未知字段")
            state = self.server.service.execute(parts[2], payload["action"], payload["fields"], expected_revision=payload["expected_revision"])
            self.send_json(200, state)
        except ConflictError as error:
            self.send_json(409, {"error": str(error)})
        except KeyError:
            self.send_json(404, {"error": "找不到这本小说"})
        except (ValueError, TypeError, UnicodeError) as error:
            self.send_json(422, {"error": str(error)})
        except (sqlite3.Error, OSError):
            self.send_json(500, {"error": "保存失败，事务已回滚。请保留页面输入并检查磁盘空间和数据库文件"})

    def handle_migration(self, path):
        from novel_writer.application.backups import BackupError
        from novel_writer.ui.migration_routes import MigrationOperations, read_parameters
        try:
            if path == '/api/migrations/import' and self.command=='POST':
                result = MigrationOperations(self.server.backups).upload(self)
            elif path == '/api/migrations/copy' and self.command=='POST':
                result = MigrationOperations(self.server.backups).copy(read_parameters(self))
            else:
                parts = path.strip('/').split('/')
                if len(parts)==4 and parts[:3]==['api','migrations','operations'] and self.command=='GET':
                    result = MigrationOperations(self.server.backups).status(parts[3])
                elif len(parts)==5 and parts[:3]==['api','migrations','operations'] and parts[4]=='cancel' and self.command=='POST':
                    if read_parameters(self)!={}: raise ValueError('cancel fields')
                    result = MigrationOperations(self.server.backups).cancel(parts[3])
                else: raise KeyError('route')
            code = 201 if path in ('/api/migrations/import','/api/migrations/copy') else 200
            response = result
        except KeyError:
            code,response = 404,{'error':'找不到迁移操作或入口；请保留原文件与操作编号'}
        except BackupError as error:
            code,response = 422,{'error':str(error),'stage':error.stage,'code':error.code}
        except (ValueError,TypeError,OSError,sqlite3.Error,UnicodeError):
            code,response = 422,{'error':'迁移参数或文件交接失败；请核对操作状态，输入及已有数据保留'}
        try: self.send_json(code,response)
        except (BrokenPipeError,ConnectionError,OSError): self.close_connection = True

    def handle_backup(self, path):
        from novel_writer.application.backups import BackupError
        try:
            if path == '/api/backups/export' or path.startswith('/api/backups/operations/'):
                if self.headers.get('Content-Type','').split(';')[0] != 'application/json' or self.headers.get('Transfer-Encoding'):
                    raise BackupError('transfer','type','备份操作仅接受空JSON对象')
                length = int(self.headers.get('Content-Length','0'))
                if not 0 < length <= 64:
                    raise BackupError('transfer','size','备份参数为空或超限')
                self.connection.settimeout(20)
                if json.loads(self.rfile.read(length)) != {}:
                    raise BackupError('transfer','fields','备份操作不接受路径或其他参数')
                if path == '/api/backups/export':
                    result = self.server.backups.export()
                else:
                    parts=path.strip('/').split('/')
                    if len(parts)!=5 or parts[:3]!=['api','backups','operations'] or parts[4]!='cancel':
                        raise KeyError('operation')
                    result=self.server.backups.cancel(parts[3])
            else:
                result = self.server.backups.restore_upload(self)
            try:
                self.send_json(200 if path.startswith('/api/backups/operations/') else 201,result)
            except (BrokenPipeError,ConnectionError,OSError):
                # 恢复可能已发布，持久操作收据用于重连核对，不追加虚假失败响应。
                pass
            return
        except KeyError:
            status, error_response = 404, {'error':'找不到此恢复操作'}
        except BackupError as error:
            status, error_response = 422, {'error':str(error), 'stage':error.stage, 'code':error.code}
        except (ValueError, OSError, sqlite3.Error, UnicodeError):
            status, error_response = 422, {'error':'备份文件交接失败；输入及已有数据保留'}
        try:
            self.send_json(status, error_response)
        except (BrokenPipeError, ConnectionError, OSError):
            # 上传断开后的资源已由restore_upload的finally释放；不再写第二个响应。
            self.close_connection = True

    def handle_backup_download(self, ticket):
        from novel_writer.application.backups import BackupError
        try:
            self.server.backups.download(self, ticket)
            return
        except KeyError:
            status, result = 404, {'error': '找不到此备份下载'}
        except BackupError as error:
            status, result = 422, {'error': str(error), 'stage': error.stage, 'code': error.code}
        except OSError:
            # 二进制响应可能已发送，不能再追加JSON。
            self.close_connection = True
            return
        try:
            self.send_json(status, result)
        except (BrokenPipeError, ConnectionError, OSError):
            self.close_connection = True

    def handle_backup_status(self,identity):
        from novel_writer.application.backups import BackupError
        try:
            self.send_json(200,self.server.backups.status(identity))
        except KeyError:
            self.send_json(404,{'error':'找不到此恢复操作；请保留原操作编号和输入包'})
        except BackupError as error:
            self.send_json(422,{'error':str(error),'stage':error.stage,'code':error.code})
        except (OSError,sqlite3.Error):
            self.send_json(422,{'error':'操作状态无法核对，请保留原操作编号和输入包'})


def create_server(database_path: str | Path, *, port=8765, provider_path=None, offline=False,local_protocol_demo=False,enable_model_generation=False,model_adapter=None,drafts_path=None) -> LocalServer:
    return LocalServer(database_path, port, provider_path, offline=offline,local_protocol_demo=local_protocol_demo,enable_model_generation=enable_model_generation,model_adapter=model_adapter,drafts_path=drafts_path)
