"""清理窗口的私有归属账本与显式恢复；不发现路径、不递归删除内容。"""
from contextlib import contextmanager, ExitStack
import ctypes
from ctypes import wintypes
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import tempfile
import time
from uuid import UUID, uuid4

from novel_writer.application import backup_staging as staging

NAMES = (".operation.json", ".owner.lock")
PHASES = {"registered", "prepared", "root_remove_intent", "root_removed", "completed", "restored"}


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf8")


def _sid():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                          wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    token, length, text = wintypes.HANDLE(), wintypes.DWORD(), wintypes.LPWSTR()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(length))
        buffer = ctypes.create_string_buffer(length.value)
        if not advapi.GetTokenInformation(token, 1, buffer, length, ctypes.byref(length)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not advapi.ConvertSidToStringSidW(ctypes.c_void_p.from_buffer(buffer), ctypes.byref(text)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return text.value
        finally:
            kernel.LocalFree(text)
    finally:
        staging._kernel().CloseHandle(token)


def _private_root(path, *, create):
    """只接受本用户所有、拒绝继承并仅本用户/系统可访问的固定账本目录。"""
    sid = _sid()
    expected = "O:" + sid + "D:P(A;OICI;FA;;;" + sid + ")(A;OICI;FA;;;SY)"
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wintypes.LPCWSTR,
        wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR), ctypes.c_void_p]
    advapi.GetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    advapi.GetNamedSecurityInfoW.restype = wintypes.DWORD
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    class Attributes(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("descriptor", ctypes.c_void_p), ("inherit", wintypes.BOOL)]
    kernel.CreateDirectoryW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(Attributes)]
    kernel.CreateDirectoryW.restype = wintypes.BOOL

    def render(descriptor):
        rendered = wintypes.LPWSTR()
        if not advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(descriptor, 1, 5, ctypes.byref(rendered), None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return rendered.value
        finally:
            kernel.LocalFree(rendered)

    expected_descriptor = ctypes.c_void_p()
    if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(expected, 1, ctypes.byref(expected_descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        # Win32可能将完整SID渲染为SDDL别名；两侧经相同转换后仍严格核对owner及完整DACL。
        expected = render(expected_descriptor)
        created = False
        if not os.path.lexists(path):
            if not create:
                raise staging.StagingError("缺少原权威账本；目录保留")
            attrs = Attributes(ctypes.sizeof(Attributes), expected_descriptor, False)
            created = bool(kernel.CreateDirectoryW(str(path), ctypes.byref(attrs)))
            if not created and ctypes.get_last_error() != 183:
                raise ctypes.WinError(ctypes.get_last_error())
        staging._plain(path, directory=True)
        descriptor = ctypes.c_void_p()
        error = advapi.GetNamedSecurityInfoW(str(path), 1, 5, None, None, None, None, ctypes.byref(descriptor))
        if error:
            raise ctypes.WinError(error)
        try:
            if render(descriptor) != expected:
                raise staging.StagingError("恢复账本所有者或私有权限不符；拒绝收编未知目录")
        finally:
            kernel.LocalFree(descriptor)
        return created
    finally:
        kernel.LocalFree(expected_descriptor)


def _authority(*, create=False):
    if os.name != "nt":
        raise staging.StagingError("显式清理恢复目前仅支持Windows")
    parent = Path(tempfile.gettempdir()).absolute()
    for part in [parent, *parent.parents]:
        staging._plain(part, directory=True)
    root = parent / "AI-Novel-Writer-staging-authority-v1"
    created = _private_root(root, create=create)
    keyfile = root / "signing.dpapi"
    # 只调用DPAPI字节工具，绝不实例化或加载模型配置。
    from novel_writer.application.provider_connections import _crypt
    if created:
        pending = root / (".key-" + uuid4().hex)
        with pending.open("xb") as output:
            output.write(_crypt(secrets.token_bytes(32)))
            output.flush()
            os.fsync(output.fileno())
        pending.rename(keyfile)
    elif create and not keyfile.exists():
        deadline = time.monotonic() + 2
        while not keyfile.exists() and time.monotonic() < deadline:
            time.sleep(.01)  # 仅首次并发初始化，绝不重新签发丢失key。
    if staging._plain(keyfile).st_size > 4096:
        raise staging.StagingError("恢复账本签名材料不合法；目录保留")
    blob = keyfile.read_bytes()
    key = _crypt(blob, decrypt=True)
    if len(key) != 32:
        raise staging.StagingError("恢复账本签名材料不合法；目录保留")
    return root, key, hashlib.sha256(blob).hexdigest()


def _id(value):
    if type(value) is not str or str(UUID(value)) != value:
        raise staging.StagingError("恢复操作编号不合法")
    return value


def _save(root, key, body, *, initial=False):
    packet = {"body": body, "mac": hmac.new(key, _canonical(body), hashlib.sha256).hexdigest()}
    destination = root / (body["operation_id"] + ".json")
    temporary = root / (".write-" + uuid4().hex)
    with temporary.open("xb") as output:
        output.write(_canonical(packet))
        output.flush()
        os.fsync(output.fileno())
    if initial:
        temporary.rename(destination)
    else:
        os.replace(temporary, destination)


def _load(root, key, key_id, operation_id):
    path = root / (_id(operation_id) + ".json")
    if staging._plain(path).st_size > 16384:
        raise staging.StagingError("恢复账本超出限制")
    packet = json.loads(path.read_text(encoding="utf8"), object_pairs_hook=staging._pairs)
    if type(packet) is not dict or set(packet) != {"body", "mac"}:
        raise staging.StagingError("恢复账本格式不合法")
    body = packet["body"]
    if not hmac.compare_digest(packet["mac"], hmac.new(key, _canonical(body), hashlib.sha256).hexdigest()):
        raise staging.StagingError("恢复账本验签失败；拒绝按副本签发归属")
    if (body["version"] != 1 or body["operation_id"] != operation_id or body["phase"] not in PHASES
            or body["authority_identity"] != staging._identity(staging._plain(root, directory=True))
            or body["key_id"] != key_id):
        raise staging.StagingError("恢复账本实例或操作归属不符")
    return body


def register(directory, receipt, stream):
    """仅真实创建流程调用，现存目录不会经inspect/cleanup注册。"""
    root, key, key_id = _authority(create=True)
    identity = _id(receipt["operation_id"])
    gate = root / (identity + ".lock")
    with gate.open("xb") as output:
        output.write(b"0")
        output.flush()
        os.fsync(output.fileno())
    marker = directory / NAMES[0]
    body = {"version": 1, "operation_id": identity, "receipt": receipt,
            "authority_identity": staging._identity(staging._plain(root, directory=True)), "key_id": key_id,
            "gate_identity": staging._identity(staging._plain(gate)),
            "marker_identity": staging._identity(staging._plain(marker)),
            "marker_hash": hashlib.sha256(marker.read_bytes()).hexdigest(),
            "phase": "registered", "generation": 0, "recovery": None,
            "delete_intents": {}, "recovery_remove_intent": False}
    if staging._identity(os.fstat(stream.fileno())) != receipt["lock_identity"]:
        raise staging.StagingError("新建暂存锁对象不符")
    _save(root, key, body, initial=True)


def _gate(path):
    import msvcrt
    kernel = staging._kernel()
    handle = kernel.CreateFileW(str(path), 0xC0000000, 3, None, 3, 0x00200080, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDWR)
    except BaseException:
        kernel.CloseHandle(handle)
        raise
    os.set_inheritable(descriptor, False)
    return os.fdopen(descriptor, "r+b")


@contextmanager
def transaction(operation_id):
    """独立持久gate；任何检查都不补建key、gate或未知operation。"""
    try:
        root, key, key_id = _authority()
        body = _load(root, key, key_id, operation_id)
        gate = root / (operation_id + ".lock")
        if staging._identity(staging._plain(gate)) != body["gate_identity"]:
            raise staging.StagingError("恢复操作锁被替换；目录保留")
        with _gate(gate) as stream:
            if staging._identity(os.fstat(stream.fileno())) != body["gate_identity"]:
                raise staging.StagingError("实际恢复操作锁被替换")
            acquired = staging._acquire(stream)
            if acquired:
                body = _load(root, key, key_id, operation_id)
            class Journal:
                def __init__(self):
                    self.body = body
                    self.acquired = acquired
                def write(self, **changes):
                    if not self.acquired:
                        raise staging.StagingError("恢复操作仍活动")
                    self.body.update(changes)
                    _save(root, key, self.body)
            yield Journal()
    except staging.StagingError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise staging.StagingError("恢复权威记录无法安全核对；全部未知对象保留") from None


def verify_original(body, root, receipt):
    marker = root / NAMES[0]
    if (body["receipt"] != receipt or receipt["directory"] != str(root)
            or staging._identity(staging._plain(marker)) != body["marker_identity"]):
        raise staging.StagingError("暂存不属于创建时登记的原对象")
    with staging._receipt_stream(marker) as stream:
        raw = stream.read().encode("utf8")
    if hashlib.sha256(raw).hexdigest() != body["marker_hash"]:
        raise staging.StagingError("暂存原收据已变化")


def prepare(journal, recovery):
    body = journal.body
    journal.write(phase="prepared", generation=body["generation"] + 1,
        recovery={"directory": str(recovery), "identity": staging._identity(staging._plain(recovery, directory=True)),
                  "parent_identity": staging._identity(staging._plain(recovery.parent, directory=True))},
        delete_intents={}, recovery_remove_intent=False)


def intent(journal, name):
    body = journal.body
    objects = dict(body["delete_intents"])
    identity = body["marker_identity"] if name == NAMES[0] else body["receipt"]["lock_identity"]
    objects[name] = {"identity": identity, "generation": body["generation"],
                     "directory": body["recovery"]["directory"], "type": "file"}
    journal.write(delete_intents=objects)


def _paths(journal, directory, recovery):
    body = journal.body
    root, escrow = Path(directory).absolute(), Path(recovery).absolute()
    if (str(root) != body["receipt"]["directory"] or body["recovery"] is None
            or str(escrow) != body["recovery"]["directory"] or root.parent != escrow.parent):
        raise staging.StagingError("显式路径与原登记不符；不推测位置")
    return root, escrow


def _objects(journal, root, escrow, stack):
    body = journal.body
    expected_root = body["receipt"]["directory_identity"]
    directories = {}
    for path, expected in ((root, expected_root), (escrow, body["recovery"]["identity"])):
        if os.path.lexists(path):
            handle = stack.enter_context(staging._pin(path, metadata_directory=True))
            if staging._identity(staging._plain(path, directory=True)) != expected:
                raise staging.StagingError("原目录或恢复目录已被替换；未知内容保留")
            directories[path] = handle
    if staging._identity(staging._plain(root.parent, directory=True)) != body["recovery"]["parent_identity"]:
        raise staging.StagingError("恢复父目录已被替换")
    root_exists = root in directories
    if not root_exists and body["phase"] not in {"root_remove_intent", "root_removed", "completed"}:
        raise staging.StagingError("原路径缺失且无可信删除意图；保留")
    if escrow in directories and any(path.name not in NAMES for path in escrow.iterdir()):
        raise staging.StagingError("恢复目录含未知内容；拒绝清理")
    found, lock_stream = {}, None
    for name in NAMES:
        expected = body["marker_identity"] if name == NAMES[0] else body["receipt"]["lock_identity"]
        locations = [path / name for path in directories if os.path.lexists(path / name)]
        if len(locations) > 1:
            raise staging.StagingError("原元数据出现多处副本；保留")
        if not locations:
            allowed = body["delete_intents"].get(name)
            if root_exists or not allowed or allowed != {"identity": expected, "generation": body["generation"],
                   "directory": str(escrow), "type": "file"}:
                raise staging.StagingError("原元数据缺失且无对应删除意图；保留")
            continue
        path = locations[0]
        if staging._identity(staging._plain(path)) != expected:
            raise staging.StagingError("元数据文件对象被替换；保留")
        if name == NAMES[1]:
            lock_stream = stack.enter_context(staging._open_lock(path, deleting=True))
            if staging._identity(os.fstat(lock_stream.fileno())) != expected or not staging._acquire(lock_stream):
                raise staging.StagingError("原操作仍活动或锁不符；保留")
            import msvcrt
            handle = msvcrt.get_osfhandle(lock_stream.fileno())
        else:
            pinned = stack.enter_context(staging._pin(path))
            handle = pinned.handle
            with staging._receipt_stream(path) as stream:
                raw = stream.read(4097).encode("utf8")
            if hashlib.sha256(raw).hexdigest() != body["marker_hash"]:
                raise staging.StagingError("原归属收据字节不符；保留")
        close = lock_stream.close if name == NAMES[1] else pinned.close
        found[name] = (path, handle, close)
    if escrow not in directories and not body["recovery_remove_intent"]:
        raise staging.StagingError("恢复目录缺失但无清理意图；保留")
    return directories, found


def inspect_staging_recovery(directory, recovery_directory, operation_id):
    return _recover(directory, recovery_directory, operation_id, mutate=False)


def recover_staging(directory, recovery_directory, operation_id):
    return _recover(directory, recovery_directory, operation_id, mutate=True)


def _recover(directory, recovery_directory, operation_id, *, mutate):
    with transaction(operation_id) as journal:
        root, escrow = _paths(journal, directory, recovery_directory)
        if not journal.acquired:
            return {"operation_id": operation_id, "state": "active_or_locked", "can_recover": False}
        with ExitStack() as stack:
            stack.enter_context(staging._pin(root.parent))
            directories, found = _objects(journal, root, escrow, stack)
            root_exists = root in directories
            terminal = journal.body["phase"] in {"restored", "completed"} and escrow not in directories
            state = "restored" if root_exists else "completed"
            if not mutate:
                return {"operation_id": operation_id, "state": state if terminal else "recoverable",
                        "can_recover": True, "original_path": "present" if root_exists else "absent",
                        "metadata_locations": {name: str(path) for name, (path, _, _) in found.items()}}
            if not terminal:
                if root_exists:
                    for name, (path, handle, close) in found.items():
                        if path.parent != root:
                            staging._move(handle, directories[root].handle, name)
                else:
                    for name, (path, handle, close) in found.items():
                        intent(journal, name)
                        staging._dispose(handle)
                        close()
                    if os.path.lexists(root):
                        raise staging.StagingError("清理期间原路径出现新内容；保留")
                if escrow in directories:
                    staging._plain(escrow, directory=True)
                    if list(escrow.iterdir()):
                        raise staging.StagingError("恢复目录新增内容；保留")
                    journal.write(recovery_remove_intent=True)
                    staging._dispose(directories[escrow].handle)
                    directories[escrow].close()
                journal.write(phase=state)
            return {"operation_id": operation_id, "state": state, "can_recover": True,
                    "original_path": "present" if root_exists else "absent", "idempotent": terminal}
