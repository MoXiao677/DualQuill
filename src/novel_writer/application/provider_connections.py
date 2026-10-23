"""独立 API 配置与模型目录检查；不读取小说、不执行生成。

Windows DPAPI 使用当前系统账户加密整个配置，凭据不进入业务数据库。
"""
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from uuid import UUID,uuid4
from hashlib import sha256
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

PROVIDERS = {
    "gg": {"name": "GG 公益站 · Gemini", "base_url": "https://gcli.ggchan.dev/v1"},
    "catie": {"name": "Catiecli · Gemini", "base_url": "https://catiecli.sukaka.top/v1"},
    "odys": {"name": "Odys · DeepSeek", "base_url": "https://api.odys.work/v1"},
}
MAX_RESPONSE = 1024 * 1024


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(value: bytes, *, decrypt=False) -> bytes:
    if os.name != "nt":
        raise OSError("当前系统没有 Windows DPAPI，未保存凭据")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    operation = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                          ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    operation.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    buffer = ctypes.create_string_buffer(value)
    source = Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise OSError("系统凭据加密/读取失败；未降级为明文")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel32.LocalFree(target.data)


def protect(value: bytes) -> bytes:
    return _crypt(value)


def _text(value, limit):
    if type(value) is not str or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError("API 配置格式不正确或超出长度限制")
    return value.strip()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ProviderConnections:
    def __init__(self, path=None, *, offline=False, allow_manual_configuration=False):
        self.path = Path(path or os.environ.get("NOVEL_WRITER_PROVIDER_CONFIG") or
                         Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AI-Novel-Writer" / "providers.dpapi")
        self.lock = threading.RLock()
        self.offline = offline
        self.allow_manual_configuration = allow_manual_configuration
        self._manual_status = {}
        self._request_times = {}

    @property
    def configuration_writes_enabled(self):
        return not self.offline or self.allow_manual_configuration

    def _public_metadata(self):
        """Non-authoritative display metadata; never used to authorize a destination."""
        path=self.path.with_suffix('.metadata.json')
        try:
            if not path.exists() or path.stat().st_size > 2*MAX_RESPONSE:return {}
            data=json.loads(path.read_text(encoding='utf-8'))
            if type(data) is not dict or set(data)!={'version','connections'} or data['version']!=1 or type(data['connections']) is not dict:return {}
            permitted={'id','name','base_url','protocol','model_id','allow_local','custom','revision','key_configured','enabled','min_interval_ms','requests_per_minute','sampling_support','sampling_model_id','temperature_mode','chat_token_field','request_model_id','stream_mode','stream_model_id'}
            result={}
            for identifier,value in data['connections'].items():
                self._id(identifier)
                if type(value) is not dict or set(value)-permitted or value.get('id')!=identifier or any(type(v) not in (str,bool,int,type(None)) for v in value.values()):return {}
                result[identifier]={**value,'last_test':None,'credential_access_enabled':False,'metadata_only':True}
            return result
        except (ValueError,OSError,UnicodeError):return {}

    def _remember_metadata(self,data):
        if not self.allow_manual_configuration:return
        permitted={'id','name','base_url','protocol','model_id','allow_local','custom','revision','key_configured','enabled','min_interval_ms','requests_per_minute','sampling_support','sampling_model_id','temperature_mode','chat_token_field','request_model_id','stream_mode','stream_model_id'}
        values={identifier:{key:value for key,value in self._safe(identifier,saved).items() if key in permitted} for identifier,saved in data.items()}
        self._manual_status={identifier:{**value,'last_test':None,'credential_access_enabled':False,'metadata_only':True} for identifier,value in values.items()}
        path=self.path.with_suffix('.metadata.json');temporary=path.with_name(path.name+'.'+str(uuid4())+'.tmp')
        try:
            temporary.write_text(json.dumps(dict(version=1,connections=values),ensure_ascii=False),encoding='utf-8');os.replace(temporary,path)
        except OSError:
            # Credentials already committed. This optional display cache must not
            # turn a successful save into a misleading retry of the secret write.
            pass
        finally:
            try:temporary.unlink(missing_ok=True)
            except OSError:pass

    def _load(self):
        if not self.path.exists():
            return {}
        try:
            if self.path.stat().st_size > 2 * MAX_RESPONSE:
                raise ValueError()
            data = json.loads(_crypt(self.path.read_bytes(), decrypt=True))
            if type(data) is not dict or data.get("version") not in (1,2) or type(data.get("connections")) is not dict:
                raise ValueError()
            return data["connections"]
        except (ValueError, OSError, UnicodeError):
            raise OSError("无法读取本机加密配置，请检查系统账户和凭据文件") from None

    def _write(self, data):
        version=2 if any(key not in PROVIDERS or "revision" in value for key,value in data.items()) else 1
        encrypted = protect(json.dumps({"version": version, "connections": data}, ensure_ascii=False).encode("utf-8"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix="providers-", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(encrypted)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            self._remember_metadata(data)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()

    def _id(self, value):
        if type(value) is not str:raise ValueError("不支持这个 API 连接")
        if value not in PROVIDERS:
            try:
                if str(UUID(value))!=value:raise ValueError()
            except ValueError:raise ValueError("不支持这个 API 连接") from None
        return value

    def _safe(self, identifier, saved):
        if identifier not in PROVIDERS:
            return dict(id=identifier,name=saved['name'],base_url=saved['base_url'],protocol=saved['protocol'],model_id=saved['model_id'],allow_local=saved['allow_local'],custom=True,revision=saved['revision'],key_configured=bool(saved.get('api_key')),last_test=saved.get('last_test'),credential_access_enabled=not self.offline,enabled=saved.get('enabled',True),min_interval_ms=saved.get('min_interval_ms',0),requests_per_minute=saved.get('requests_per_minute',0),sampling_support=saved.get('sampling_support',''),sampling_model_id=saved.get('sampling_model_id',''),temperature_mode=saved.get('temperature_mode','configured'),chat_token_field=saved.get('chat_token_field','max_tokens'),request_model_id=saved.get('request_model_id',''),stream_mode=saved.get('stream_mode','json'),stream_model_id=saved.get('stream_model_id',''))
        return {"id": identifier, **PROVIDERS[identifier],
                "base_url": saved.get("base_url", PROVIDERS[identifier]["base_url"]),
                "protocol": "OpenAI 兼容 · 模型列表",
                "model_id": saved.get("model_id", ""), "key_configured": bool(saved.get("api_key")),
                "last_test": saved.get("last_test"), "credential_access_enabled": not self.offline,
                "enabled": saved.get('enabled',True), "revision":saved.get('revision'),
                "min_interval_ms":saved.get('min_interval_ms',0),"requests_per_minute":saved.get('requests_per_minute',0),"sampling_support":saved.get('sampling_support',''),"sampling_model_id":saved.get('sampling_model_id',''),"temperature_mode":saved.get('temperature_mode','configured'),"chat_token_field":saved.get('chat_token_field','max_tokens'),"request_model_id":saved.get('request_model_id','')}

    @staticmethod
    def _require_enabled(saved):
        if saved.get('enabled',True) is not True:
            raise ValueError('连接已禁用；旧冻结请求已过期，请启用后重新准备并逐次确认')

    def validate_sampling(self,options):
        from novel_writer.domain.sampling import requested,canonical
        selected=requested(options.get('sampling'))
        if options.get('adapter_id')=='chat-completions-http-v1' and not options.get('sampling'):return
        if self.offline:
            if selected or options.get('sampling'):raise ValueError('请明确开启模型会话后核对参数能力')
            return
        with self.lock:
            saved=self._load().get(self._id(options['connection_id']),{})
            self._require_enabled(saved)
            mode=saved.get('temperature_mode','configured');field=saved.get('chat_token_field','max_tokens')
            explicit=options.get('sampling') or {}
            if mode!='configured' or field!='max_tokens' or any(k in explicit for k in ('temperature_mode','chat_token_field')):
                if options['model_id']!=saved.get('model_id') or saved.get('request_model_id')!=options['model_id']:
                    raise ValueError('原生请求配置只适用已声明的当前默认模型；覆盖模型须另建连接并声明')
                if any(k in explicit and explicit[k]!=v for k,v in (('temperature_mode',mode),('chat_token_field',field))):
                    raise ValueError('预设原生请求配置与当前连接声明不一致，请重新核对')
                value=dict(top_p=None,seed=None,stop=[])|explicit
                value.update(temperature_mode=mode,chat_token_field=field)
                options['sampling']=canonical(value)
            if not selected:return
            if options['model_id']!=saved.get('model_id') or saved.get('sampling_model_id')!=options['model_id']:
                raise ValueError('此模型参数能力未知，请先在连接管理核对并声明当前模型支持；模型覆盖不继承声明')
            if not selected<=set(saved.get('sampling_support','').split(',')):
                raise ValueError('参数支持未知或未声明，不能静默忽略；请核对该模型原生契约')
            if saved.get('protocol')=='anthropic-messages' and 'seed' in selected:
                raise ValueError('Messages 原生协议未支持 seed')

    def manage(self, *, id, action, confirmed, **options):
        if not self.configuration_writes_enabled:raise ValueError('离线维护模式不允许修改配置')
        identifier=self._id(id)
        if confirmed is not True:raise ValueError('连接管理需要明确确认')
        if action in ('request_profile','stream_profile') and identifier in PROVIDERS:raise ValueError('旧内置连接保持不读凭据的准备契约；请另存自建连接后配置原生请求')
        if action not in ('enable','disable','delete_credentials','limits','sampling_support','request_profile','stream_profile'):raise ValueError('未知连接管理操作')
        if set(options) != ({'min_interval_ms','requests_per_minute'} if action=='limits' else {'parameters'} if action=='sampling_support' else {'temperature_mode','chat_token_field'} if action=='request_profile' else {'stream_mode'} if action=='stream_profile' else set()):raise ValueError('连接管理参数不完整或含未知字段')
        if action=='sampling_support' and (type(options['parameters']) is not list or not all(type(p) is str for p in options['parameters']) or len(set(options['parameters']))!=len(options['parameters']) or not set(options['parameters'])<={'top_p','seed','stop'}):raise ValueError('参数支持声明非法')
        if action=='request_profile' and (options['temperature_mode'] not in ('configured','omit') or options['chat_token_field'] not in ('max_tokens','max_completion_tokens')):raise ValueError('原生请求配置非法')
        if action=='stream_profile' and options['stream_mode'] not in ('json','sse'):raise ValueError('流式配置非法')
        if action=='limits':
            for name,limit in (('min_interval_ms',60000),('requests_per_minute',1000)):
                if type(options[name]) is not int or not 0<=options[name]<=limit:raise ValueError('本地限流数值无效')
        with self.lock:
            data=self._load()
            if identifier not in data:raise ValueError('请先保存此连接')
            saved=data[identifier]
            if action=='enable' and not saved.get('api_key') and not saved.get('allow_local'):
                raise ValueError('凭据已删除，请先重新保存密钥，再启用连接')
            if action in ('enable','disable'):saved['enabled']=action=='enable'
            elif action=='delete_credentials':saved['api_key']='';saved['enabled']=False
            elif action=='request_profile':
                if saved.get('protocol','openai-chat')!='openai-chat' and options['chat_token_field']!='max_tokens':raise ValueError('非 Chat 协议不能选择 Chat 输出令牌字段')
                saved.update(options);saved['request_model_id']=saved['model_id']
            elif action=='stream_profile':
                saved['stream_mode']=options['stream_mode'];saved['stream_model_id']=saved['model_id']
            elif action=='sampling_support':
                if saved.get('protocol')=='anthropic-messages' and 'seed' in options['parameters']:raise ValueError('Messages 原生协议未支持 seed')
                saved['sampling_support']=','.join(sorted(options['parameters']));saved['sampling_model_id']=saved['model_id']
            else:saved.update(options)
            saved['revision']=str(uuid4());saved.pop('last_test',None)
            saved['invalidated_at']=datetime.now(timezone.utc).isoformat()
            self._write(data)
            return self._safe(identifier,saved)

    def _reserve_request(self,identifier,saved):
        self._require_enabled(saved)
        with self.lock:
            current=self._load().get(identifier,{})
            self._require_enabled(current)
            if current.get('revision')!=saved.get('revision'):raise ValueError('连接配置已变化，旧冻结请求已过期，请重新准备')
            now=time.monotonic();recent=[stamp for stamp in self._request_times.get(identifier,[]) if now-stamp<60]
            interval=saved.get('min_interval_ms',0)/1000
            maximum=saved.get('requests_per_minute',0)
            if recent and now-recent[-1]<interval:raise ValueError('本地连接限流：尚未达到最小请求间隔；请稍后重新确认，不自动重试')
            if maximum and len(recent)>=maximum:raise ValueError('本地连接限流：一分钟请求上限已到；不自动重试')
            self._request_times[identifier]=recent+[now]

    def assert_prepared(self,identifier,created_at):
        """Legacy frozen schemas remain immutable; management invalidates older tasks."""
        with self.lock:
            saved=self._load().get(self._id(identifier),{})
            self._require_enabled(saved)
            if saved.get('invalidated_at') and datetime.fromisoformat(created_at)<=datetime.fromisoformat(saved['invalidated_at']):
                raise ValueError('连接配置已变化，旧冻结请求已过期；请重新准备并逐次确认')

    def status(self):
        if self.offline:
            result={identifier: {**self._safe(identifier, {}), "key_configured": None} for identifier in PROVIDERS}
            if self.allow_manual_configuration:
                with self.lock:result.update(self._public_metadata());result.update(self._manual_status)
            return result
        with self.lock:
            data = self._load()
            return {identifier: self._safe(identifier, data.get(identifier, {})) for identifier in dict.fromkeys([*PROVIDERS,*data])}

    def save_custom(self,*,id,name,base_url,protocol,model_id,api_key='',allow_local=False):
        if not self.configuration_writes_enabled:raise ValueError('离线维护模式不允许修改配置。')
        from novel_writer.application.custom_protocols import validate_endpoint,PROTOCOLS
        identifier=self._id(id)
        if identifier in PROVIDERS:raise ValueError('内置旧连接保留原身份；请为自建供应商使用新编号。')
        name=_text(name,100);base_url=_text(base_url,500).rstrip('/');model_id=_text(model_id,200);api_key=_text(api_key,4096)
        if protocol not in PROTOCOLS or type(allow_local) is not bool or not name or not model_id:raise ValueError('供应商名称、协议、模型或本机范围非法')
        validate_endpoint(base_url,allow_local=allow_local)
        with self.lock:
            data=self._load();previous=data.get(identifier,{})
            key=api_key or previous.get('api_key','')
            if not key and not allow_local:raise ValueError('公开供应商须先配置密钥；显式本机模型可无密钥。')
            if key and any(key in text for text in (name,base_url,model_id)):raise ValueError('公开供应商元数据不能包含密钥')
            saved=dict(name=name,base_url=base_url,protocol=protocol,model_id=model_id,api_key=key,allow_local=allow_local,revision=str(uuid4()),enabled=previous.get('enabled',True),min_interval_ms=previous.get('min_interval_ms',0),requests_per_minute=previous.get('requests_per_minute',0))
            saved['invalidated_at']=datetime.now(timezone.utc).isoformat()
            data[identifier]=saved;self._write(data);return self._safe(identifier,saved)

    @staticmethod
    def _destination(identifier,saved):
        value=dict(connection_id=identifier,revision=saved['revision'],protocol=saved['protocol'],base_url=saved['base_url'],allow_local=saved['allow_local'])
        if saved.get('stream_mode')=='sse':value['stream_mode']='sse'
        value['sha256']=sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()
        from novel_writer.domain.connections import ConnectionDestination
        ConnectionDestination(**value)
        return value

    def destination(self,identifier,model_id,*,allow_model_override=False):
        if self.offline:raise ValueError('完全手动模式不读取模型配置')
        identifier=self._id(identifier)
        with self.lock:saved=self._load().get(identifier,{})
        self._require_enabled(saved)
        if identifier in PROVIDERS or not saved or (not allow_model_override and saved.get('model_id')!=model_id):raise ValueError('请选择已保存的自建供应商及模型')
        if saved.get('stream_mode')=='sse' and (saved.get('stream_model_id')!=model_id or saved.get('model_id')!=model_id):raise ValueError('流式声明仅适用于当前默认模型；请另建连接并声明')
        if allow_model_override and (not model_id or _text(model_id,200)!=model_id):raise ValueError('本次模型覆盖编号非法')
        return self._destination(identifier,saved)

    def save(self, *, id, base_url, model_id, api_key=""):
        if not self.configuration_writes_enabled:
            raise ValueError("离线维护中：配置未读取，配置保存和连接检查已禁用")
        identifier = self._id(id)
        if identifier not in PROVIDERS:raise ValueError('自建供应商请使用带协议与范围的配置入口')
        base_url, model_id, api_key = _text(base_url, 250).rstrip("/"), _text(model_id, 200), _text(api_key, 4096)
        if base_url != PROVIDERS[identifier]["base_url"]:
            raise ValueError("请使用此站点的固定 API 地址（以 /v1 结尾）；登录地址不能作为 API 地址")
        if api_key and api_key in model_id:
            raise ValueError("模型 ID 不能包含 API 密钥")
        with self.lock:
            data = self._load()
            previous = data.get(identifier, {})
            key = api_key or previous.get("api_key", "")
            if not key:
                raise ValueError("请先配置 API Key")
            if key in model_id:
                raise ValueError("模型 ID 不能包含 API 密钥")
            data[identifier] = {"base_url": base_url, "model_id": model_id, "api_key": key,"revision":str(uuid4()),'enabled':previous.get('enabled',True),'min_interval_ms':previous.get('min_interval_ms',0),'requests_per_minute':previous.get('requests_per_minute',0)}
            data[identifier]['invalidated_at']=datetime.now(timezone.utc).isoformat()
            self._write(data)
            return self._safe(identifier, data[identifier])

    def test_connection(self, identifier):
        if self.offline:
            raise ValueError("离线维护中：配置未读取，配置保存和连接检查已禁用")
        identifier = self._id(identifier)
        with self.lock:
            saved = self._load().get(identifier, {}).copy()
        self._reserve_request(identifier,saved)
        if identifier not in PROVIDERS:
            if not saved:raise ValueError('请先保存这个供应商')
            from novel_writer.application.custom_protocols import list_models
            result=list_models(saved)
            with self.lock:
                data=self._load()
                if data.get(identifier,{})!=saved:return dict(result,ok=False,message='检查期间配置已变化，请重新检查')
                data[identifier]['last_test']=result;self._write(data)
            return result
        if not saved.get("api_key"):
            raise ValueError("请先保存此站点的 API Key")
        if saved.get("base_url") != PROVIDERS[identifier]["base_url"]:
            raise ValueError("API 地址已变化，请重新保存配置")
        result = {"ok": False, "models": [], "http_status": None,
                  "tested_at": datetime.now(timezone.utc).isoformat(), "selected_model_available": False}
        request = Request(saved["base_url"] + "/models", headers={"Authorization": "Bearer " + saved["api_key"],
                           "Accept": "application/json", "User-Agent": "AI-Novel-Writer/0.2"})
        try:
            with build_opener(NoRedirect()).open(request, timeout=15) as response:
                result["http_status"] = response.status
                raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise ValueError()
            payload = json.loads(raw)
            if type(payload) is not dict or type(payload.get("data")) is not list or len(payload["data"]) > 2000:
                raise ValueError()
            models = []
            for item in payload["data"]:
                value = _text(item.get("id") if type(item) is dict else None, 200)
                if value and saved["api_key"] not in value:
                    models.append(value)
            result.update(ok=True, models=list(dict.fromkeys(models)), message="模型列表连接通过；尚未验证文本生成",
                          selected_model_available=saved["model_id"] in models)
            if saved["model_id"] and not result["selected_model_available"]:
                result["message"] += "；所选模型不在当前列表中"
        except HTTPError as error:
            error.close()
            result["http_status"] = error.code
            result["message"] = {401: "API Key 无效或已过期，请更换密钥", 403: "此 API Key 没有访问权限",
                                 404: "未找到模型列表接口", 429: "站点限流，请稍后再试"}.get(error.code, "站点返回 HTTP 错误，请稍后检查")
        except (URLError, TimeoutError, OSError):
            result["message"] = "连接失败或超时，请检查网络或站点状态"
        except (ValueError, UnicodeError):
            result["message"] = "站点未返回有效的模型列表"
        with self.lock:
            data = self._load()
            if data.get(identifier, {}) != saved:
                return {**result, "ok": False, "message": "测试期间配置已变化，请重新测试"}
            data[identifier]["last_test"] = result
            self._write(data)
        return result

    def generation_connection(self,identifier,model_id,*,enabled=False,confirmed=False,destination=None,allow_model_override=False,reserve=True):
        """只由已明确启用/单次确认的模型adapter调用；不返回给HTTP界面或持久任务。"""
        if self.offline or enabled is not True or confirmed is not True:raise ValueError('真实生成未明确启用或未单次确认')
        identifier=self._id(identifier)
        with self.lock:saved=self._load().get(identifier,{}).copy()
        self._require_enabled(saved)
        if identifier not in PROVIDERS:
            if not saved or (not allow_model_override and saved.get('model_id')!=model_id) or type(destination) is not dict or destination!=self._destination(identifier,saved):raise ValueError('供应商版本、协议或去向已变化，请重新准备并确认请求')
            if allow_model_override:
                if not model_id or _text(model_id,200)!=model_id:raise ValueError('本次模型覆盖编号非法')
                saved['model_id']=model_id
            from novel_writer.application.custom_protocols import validate_endpoint
            validate_endpoint(saved['base_url'],allow_local=saved['allow_local'])
            if reserve:self._reserve_request(identifier,saved)
            return {key:saved[key] for key in ('base_url','model_id','api_key','protocol','allow_local','stream_mode') if key in saved}
        if saved.get('base_url')!=PROVIDERS[identifier]['base_url'] or saved.get('model_id')!=model_id:raise ValueError('所选连接/模型已变化，请重新准备')
        key=_text(saved.get('api_key'),4096)
        if not key or key in model_id:raise ValueError('所选连接不可用')
        if reserve:self._reserve_request(identifier,saved)
        return dict(base_url=PROVIDERS[identifier]['base_url'],model_id=model_id,api_key=key)

    def configuration_stamp(self):
        """Ciphertext fingerprint only: verifying an old candidate does not decrypt keys."""
        if not self.path.is_file() or self.path.stat().st_size>2*MAX_RESPONSE:raise ValueError('book_ai.connection_missing')
        return sha256(self.path.read_bytes()).hexdigest()

    def _book_saved(self,identifier,model_id):
        identifier=self._id(identifier);model_id=_text(model_id,200)
        with self.lock:saved=self._load().get(identifier,{}).copy()
        if not saved or not model_id:raise ValueError('book_ai.connection_missing')
        self._require_enabled(saved)
        if not saved.get('revision'):raise ValueError('book_ai.save_connection_version')
        if saved.get('api_key') and saved['api_key'] in model_id:raise ValueError('book_ai.invalid_model')
        if identifier in PROVIDERS:
            if saved.get('base_url')!=PROVIDERS[identifier]['base_url']:raise ValueError('book_ai.connection_changed')
            saved.update(protocol='openai-chat',allow_local=False)
        return saved

    def book_destination(self,identifier,model_id):
        if self.offline:raise ValueError('book_ai.models_disabled')
        saved=self._book_saved(identifier,model_id)
        from novel_writer.domain.book_ai import BookDestination
        if saved.get('stream_mode')=='sse' and (saved.get('stream_model_id')!=model_id or saved.get('model_id')!=model_id):raise ValueError('流式声明仅适用于当前默认模型；请另建连接并声明')
        value=dict(connection_id=identifier,revision=saved['revision'],protocol=saved['protocol'],base_url=saved['base_url'],allow_local=saved['allow_local'])
        if saved.get('stream_mode')=='sse':value['stream_mode']='sse'
        value['sha256']=sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest();BookDestination(**value)
        return value

    def generation_book_connection(self,identifier,model_id,*,destination,stamp,enabled=False,confirmed=False,reserve=True):
        if self.offline or enabled is not True or confirmed is not True:raise ValueError('book_ai.models_disabled')
        with self.lock:
            if self.configuration_stamp()!=stamp or self.book_destination(identifier,model_id)!=destination:raise ValueError('book_ai.connection_changed')
            saved=self._book_saved(identifier,model_id)
        key=_text(saved.get('api_key'),4096)
        if not key and not saved['allow_local']:raise ValueError('book_ai.connection_missing')
        if reserve:self._reserve_request(identifier,saved)
        return dict(base_url=saved['base_url'],model_id=model_id,api_key=key,protocol=saved['protocol'],allow_local=saved['allow_local'],**({'stream_mode':'sse'} if saved.get('stream_mode')=='sse' else {}))
