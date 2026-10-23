"""备份暂存持久归属、OS活动锁和按明确路径/操作编号清理；不自动扫描。"""
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import tempfile
import weakref
from uuid import UUID, uuid4

PREFIXES = {"backup": ".novel-backup-", "restore": ".novel-backup-",
            "preflight": ".novel-backup-", "transfers": "novel-backup-transfers-",
            "receipt": ".receipt-", "receipt_preflight": "novel-backup-receipt-"}
FIELDS = {"format", "version", "operation_id", "kind", "created_at", "pid", "directory",
          "directory_identity", "lock_identity"}


class StagingError(ValueError):
    pass


def _plain(path, *, directory=False):
    info = Path(path).lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode) or getattr(info, "st_file_attributes", 0) & 1024:
        raise StagingError("暂存管理拒绝链接、重解析点或未知文件类型；目录保留")
    return info


def _identity(info):
    return [info.st_dev, info.st_ino]


def _kernel():
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                wintypes.LPVOID, wintypes.DWORD]
    kernel.SetFileInformationByHandle.restype = wintypes.BOOL
    return kernel


@contextmanager
def _pin(path, *, metadata_directory=False):
    """Windows固定原对象，禁止写入/重命名/替换；不跟随重解析点。"""
    import ctypes
    kernel = _kernel()
    access, sharing = (0x10082, 3) if metadata_directory else (0x10080, 1)
    handle = kernel.CreateFileW(str(path), access, sharing, None, 3, 0x02200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    class Pinned:
        def __init__(self, value):
            self.handle = value
        def close(self):
            if self.handle is not None:
                kernel.CloseHandle(self.handle)
                self.handle = None
    pinned = Pinned(handle)
    try:
        _plain(path, directory=Path(path).is_dir())
        yield pinned
    finally:
        pinned.close()


def _dispose(handle):
    import ctypes
    deleting = ctypes.c_ubyte(1)
    if not _kernel().SetFileInformationByHandle(handle, 4, ctypes.byref(deleting), 1):
        raise ctypes.WinError(ctypes.get_last_error())


def _move(handle, directory_handle, name):
    """按固定的原句柄移动，目的地存在即拒绝，绝不覆盖未知内容。"""
    import ctypes
    from ctypes import wintypes
    if name not in (".operation.json", ".owner.lock"):
        raise StagingError("未知归属元数据名称")
    class RenameInfo(ctypes.Structure):
        _fields_ = [("replace", ctypes.c_ubyte), ("root", wintypes.HANDLE),
                    ("length", wintypes.DWORD), ("name", wintypes.WCHAR * (len(name) + 1))]
    class Status(ctypes.Structure):
        _fields_ = [("status", ctypes.c_void_p), ("information", ctypes.c_size_t)]
    native = ctypes.WinDLL("ntdll")
    native.NtSetInformationFile.argtypes = [wintypes.HANDLE, ctypes.POINTER(Status),
                                          ctypes.c_void_p, wintypes.ULONG, ctypes.c_int]
    native.NtSetInformationFile.restype = wintypes.LONG
    native.RtlNtStatusToDosError.argtypes = [wintypes.LONG]
    native.RtlNtStatusToDosError.restype = wintypes.ULONG
    info = RenameInfo(0, directory_handle, len(name.encode("utf-16-le")), name)
    status = Status()
    result = native.NtSetInformationFile(handle, ctypes.byref(status), ctypes.byref(info),
                                         ctypes.sizeof(info), 10)
    if result < 0:
        raise ctypes.WinError(native.RtlNtStatusToDosError(result))


def _open_lock(path, *, deleting=False):
    if os.name != "nt":
        return open(path, "r+b")
    # Windows默认Python句柄不共享DELETE；显式共享允许持有排他字节锁时删除自身锁文件。
    import ctypes
    import msvcrt
    kernel = _kernel()
    handle = kernel.CreateFileW(str(path), 0xC0000000 | (0x10000 if deleting else 0),
                                7, None, 3, 0x00200080, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDWR)
    except BaseException:
        kernel.CloseHandle(handle)
        raise
    os.set_inheritable(descriptor, False)
    return os.fdopen(descriptor, "r+b")


def _acquire(stream):
    stream.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False  # 不能确认独占时保守视为活动或不可用，绝不按PID猜测清理。
    return True


class OwnedTemporaryDirectory:
    def __init__(self, *, kind, prefix, dir=None):
        if PREFIXES.get(kind) != prefix:
            raise StagingError("未知暂存类型或前缀")
        # 不注册stdlib按路径rmtree的finalizer；所有生命周期均核对原对象。
        self.name = tempfile.mkdtemp(prefix=prefix, dir=dir)
        self._stream = None
        self._finalizer = None
        self.cleanup_warnings = []
        try:
            directory = Path(self.name).resolve(strict=True)
            lock = directory / ".owner.lock"
            lock.write_bytes(b"0")
            self._stream = _open_lock(lock, deleting=True)
            if not _acquire(self._stream):
                raise StagingError("无法取得新暂存独占锁")
            receipt = {"format": "novel-writer-owned-staging", "version": 1,
                       "operation_id": str(uuid4()), "kind": kind, "pid": os.getpid(),
                       "created_at": datetime.now(timezone.utc).isoformat(), "directory": str(directory),
                       "directory_identity": _identity(directory.stat()),
                       "lock_identity": _identity(os.fstat(self._stream.fileno()))}
            with (directory / ".operation.json").open("x", encoding="utf8") as output:
                json.dump(receipt, output, ensure_ascii=False)
                output.flush()
                os.fsync(output.fileno())
            from novel_writer.application.backup_staging_recovery import register
            register(directory, receipt, self._stream)
            self._finalizer = weakref.finalize(self, _finalize_owned, directory, receipt, self._stream)
        except BaseException:
            # 初始化未完成不能建立可信归属，保守留下目录而不是递归猜测删除。
            if self._stream is not None:
                self._stream.close()
            raise

    def __enter__(self):
        return self.name

    def __exit__(self, *arguments):
        self.cleanup()

    def cleanup(self):
        if self._finalizer is not None and self._finalizer.alive:
            _, callback, arguments, keywords = self._finalizer.detach()
            self.cleanup_warnings.extend(_cleanup_owned(*arguments, **keywords))


def _cleanup_owned(directory, receipt, stream):
    """活动所有者保留原锁，拒绝替换对象；失败后只允许显式重新核对。"""
    try:
        if os.name != "nt":
            raise StagingError("此平台尚未实现固定对象清理；目录保留")
        with _pin(directory) as guard:
            root, actual = _load(directory)
            if actual != receipt or _identity(os.fstat(stream.fileno())) != receipt["lock_identity"]:
                raise StagingError("活动暂存对象或归属已经改变；目录保留")
            return _remove_pinned(root, receipt, guard, stream)
    except StagingError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise StagingError("活动暂存无法安全清理；目录保留，请明确核对归属") from None
    finally:
        stream.close()


def _finalize_owned(directory, receipt, stream):
    try:
        _cleanup_owned(directory, receipt, stream)
    except StagingError:
        # GC不能把保守拒绝变成重试；已关闭锁，持久证据/未知目录保留。
        pass


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise StagingError("暂存归属记录含重复字段；目录保留")
        result[key] = value
    return result


@contextmanager
def _receipt_stream(path):
    if os.name != "nt":
        with path.open("r", encoding="utf8") as stream:
            yield stream
        return
    import ctypes
    import msvcrt
    kernel = _kernel()
    handle = kernel.CreateFileW(str(path), 0x80000000, 7, None, 3, 0x00200080, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY)
    except BaseException:
        kernel.CloseHandle(handle)
        raise
    with os.fdopen(descriptor, "r", encoding="utf8") as stream:
        yield stream


def _load(directory):
    original = Path(directory).absolute()
    _plain(original, directory=True)
    root = original.resolve(strict=True)
    marker, lock = root / ".operation.json", root / ".owner.lock"
    if _plain(marker).st_size > 4096 or _plain(lock).st_size != 1:
        raise StagingError("暂存归属或锁记录不合法；目录保留")
    with _receipt_stream(marker) as stream:
        receipt = json.loads(stream.read(4097), object_pairs_hook=_pairs)
    if (type(receipt) is not dict or set(receipt) != FIELDS or
        receipt["format"] != "novel-writer-owned-staging" or type(receipt["version"]) is not int or
        receipt["version"] != 1 or receipt["directory"] != str(root) or
        receipt["directory_identity"] != _identity(_plain(root, directory=True)) or
        receipt["lock_identity"] != _identity(_plain(lock)) or
        type(receipt["pid"]) is not int or receipt["pid"] <= 0 or
        receipt["kind"] not in PREFIXES or not root.name.startswith(PREFIXES[receipt["kind"]])):
        raise StagingError("暂存归属不匹配或类型未知；目录保留")
    if str(UUID(receipt["operation_id"])) != receipt["operation_id"]:
        raise StagingError("暂存操作编号不合法；目录保留")
    stamp = datetime.fromisoformat(receipt["created_at"])
    if stamp.tzinfo is None or stamp.utcoffset().total_seconds() != 0:
        raise StagingError("暂存时间记录不合法；目录保留")
    return root, receipt


@contextmanager
def _claim(directory, *, removing=False):
    try:
        with ExitStack() as stack:
            guard = stack.enter_context(_pin(Path(directory).absolute())) if removing and os.name == "nt" else None
            root, receipt = _load(directory)
            stream = stack.enter_context(_open_lock(root / ".owner.lock", deleting=removing))
            if _identity(os.fstat(stream.fileno())) != receipt["lock_identity"]:
                raise StagingError("实际锁对象与持久归属不符；目录保留")
            acquired = _acquire(stream)
            if acquired and _load(root)[1] != receipt:
                raise StagingError("暂存归属在核对期间变化；目录保留")
            yield root, receipt, acquired, guard, stream
    except StagingError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise StagingError("暂存归属无法安全核对；目录保留，不按名称或PID猜测") from None


def inspect_staging(directory):
    """明确路径，仅读本目录归属/锁；未加锁不能判为可清理。"""
    with _claim(directory) as (root, receipt, acquired, guard, stream):
        return {**receipt, "state": "inactive_owned" if acquired else "active_or_locked",
                "automatically_removed": False}


def cleanup_staging(directory, operation_id):
    """明确路径+对应编号+OS独占锁，删除仅此暂存；未知/活动/嵌套操作均保留。"""
    with _claim(directory, removing=True) as (root, receipt, acquired, guard, stream):
        if not acquired or receipt["operation_id"] != operation_id:
            raise StagingError("暂存仍活动、锁不可用或操作编号不符；目录保留")
        if os.name != "nt":
            raise StagingError("此平台尚未实现固定对象清理；目录保留")
        warnings = _remove_pinned(root, receipt, guard, stream)
        return {"operation_id": operation_id, "kind": receipt["kind"], "removed": True,
                "cleanup_warnings": warnings}


def _remove_pinned(root, receipt, root_handle, lock_stream):
    from novel_writer.application import backup_staging_recovery as recovery
    with recovery.transaction(receipt["operation_id"]) as journal:
        if not journal.acquired:
            raise StagingError("清理/恢复操作仍活动；目录保留")
        recovery.verify_original(journal.body, root, receipt)
        return _remove_registered(root, receipt, root_handle, lock_stream, journal)


def _remove_registered(root, receipt, root_handle, lock_stream, journal):
    """先固定全部原对象再删除，新增对象只导致非空失败，绝不扫入新内容。"""
    import msvcrt
    with ExitStack() as stack:
        objects = []
        expected = set()
        for parent, directories, files in os.walk(root, followlinks=False):
            if Path(parent) != root and ".operation.json" in files:
                raise StagingError("包含另一个暂存操作；请单独核对，父目录保留")
            for name, is_directory in [(name, True) for name in directories] + [(name, False) for name in files]:
                path = Path(parent) / name
                identity = _identity(_plain(path, directory=is_directory))
                if len(objects) >= 256:
                    raise StagingError("暂存目录内容超出受控清理范围；目录保留")
                if path == root / ".owner.lock":
                    handle = msvcrt.get_osfhandle(lock_stream.fileno())
                else:
                    handle = stack.enter_context(_pin(path))
                if _identity(_plain(path, directory=is_directory)) != identity:
                    raise StagingError("暂存子对象在固定期间变化；目录保留")
                expected.add(path)
                objects.append((path, handle))
        actual = {Path(parent) / name for parent, directories, files in os.walk(root, followlinks=False)
                  for name in directories + files}
        if actual != expected or _load(root)[1] != receipt:
            raise StagingError("暂存目录在核对期间变化；目录保留")
        metadata = {root / ".operation.json", root / ".owner.lock"}
        for path, handle in sorted(objects, key=lambda item: len(item[0].parts), reverse=True):
            if path not in metadata:
                _dispose(handle.handle)
                handle.close()
        if set(root.iterdir()) != metadata:
            raise StagingError("清理期间新增内容；内容与原归属保留")

        # 根目录必须空才能删除。先临时保留两个原文件对象，最后删除失败时
        # 按句柄无覆盖移回，保留原receipt字节和lock_identity，不伪造新锁。
        with _pin(root.parent):
            # 枚举/删除内容时根始终拒绝外部写。仅当全部payload已结束，且
            # 两个原元数据仍固定时切换根句柄；此后不再枚举或删除新内容。
            root_handle.close()
            root_handle = stack.enter_context(_pin(root, metadata_directory=True))
            if _identity(_plain(root, directory=True)) != receipt["directory_identity"]:
                raise StagingError("最终暂存根身份变化；目录保留")
            recovery = Path(tempfile.mkdtemp(prefix=".novel-staging-recovery-" + receipt["operation_id"] + "-",
                                             dir=root.parent))
            with _pin(recovery, metadata_directory=True) as recovery_handle:
                from novel_writer.application.backup_staging_recovery import prepare, intent
                prepare(journal, recovery)
                moved = []
                try:
                    for path, handle in objects:
                        if path in metadata:
                            value = handle if path.name == ".owner.lock" else handle.handle
                            _move(value, recovery_handle.handle, path.name)
                            moved.append((path, value))
                    if list(root.iterdir()):
                        raise StagingError("最终根目录新增内容；拒绝删除")
                    journal.write(phase="root_remove_intent")
                    _dispose(root_handle.handle)
                except BaseException:
                    try:
                        for path, value in reversed(moved):
                            _move(value, root_handle.handle, path.name)
                    except OSError:
                        raise StagingError("原归属恢复受阻，禁止覆盖新增内容；检查原目录及原对象恢复位置 " + str(recovery)) from None
                    try:
                        journal.write(phase="restored", recovery_remove_intent=True)
                        _dispose(recovery_handle.handle)
                    except OSError:
                        raise StagingError("原归属已恢复，原目录仍保留；另有恢复目录残留 " + str(recovery)) from None
                    raise
                root_handle.close()
                journal.write(phase="root_removed")
                # 原根删除已提交，后续失败不再补偿或宣称原目录仍在。
                try:
                    for path, handle in objects:
                        if path in metadata:
                            intent(journal, path.name)
                            _dispose(handle if path.name == ".owner.lock" else handle.handle)
                            if path.name == ".owner.lock":
                                lock_stream.close()
                            else:
                                handle.close()
                    journal.write(recovery_remove_intent=True)
                    _dispose(recovery_handle.handle)
                except OSError:
                    return ["原暂存目录已移除；归属元数据恢复目录清理未完成，保留位置 " + str(recovery)]
        journal.write(phase="completed")
        return []


def inspect_staging_recovery(directory, recovery_directory, operation_id):
    from novel_writer.application.backup_staging_recovery import inspect_staging_recovery as inspect
    return inspect(directory, recovery_directory, operation_id)


def recover_staging(directory, recovery_directory, operation_id):
    from novel_writer.application.backup_staging_recovery import recover_staging as recover
    return recover(directory, recovery_directory, operation_id)
