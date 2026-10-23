"""Explicit, redacted local diagnostics and narrowly scoped recovery-file cleanup.

No database writes, credential reads, recursive deletion, or directory discovery.
Preview tokens are process-local and expire; cleanup never accepts a client path.
"""
from hashlib import sha256
import json
from pathlib import Path
import re
import secrets
import stat
import time

from .drafts import MAX_DRAFT_BYTES, MAX_FILES, read_draft


class LocalDataError(ValueError):
    pass


class LocalDataSafety:
    def __init__(self, drafts, database, *, offline, models_enabled):
        self.drafts = drafts
        self.database = Path(database)
        self.offline = offline
        self.models_enabled = models_enabled
        self.previews = {}
        self.root_identity = None

    def _root(self):
        root = self.drafts.directory
        info = root.lstat()
        if (not stat.S_ISDIR(info.st_mode) or root.is_symlink()
                or getattr(info, 'st_file_attributes', 0) & 0x400):
            raise LocalDataError('草稿目录含链接或不是普通目录；未执行清理')
        identity = (info.st_dev, info.st_ino)
        if self.root_identity is not None and self.root_identity != identity:
            raise LocalDataError('草稿目录已替换；请重启后重新预览')
        self.root_identity = identity
        return root

    def _fingerprint(self, path):
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or getattr(info, 'st_file_attributes', 0) & 0x400
                or info.st_size > MAX_DRAFT_BYTES):
            raise LocalDataError('特殊文件或超限文件不允许清理')
        raw = path.read_bytes()
        after = path.lstat()
        identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
        if identity(info) != identity(after):
            raise LocalDataError('草稿在读取期间已变化；请重新预览')
        return (*identity(info), sha256(raw).hexdigest())

    def _scan(self):
        root = self._root()
        paths = []
        # Stop rather than materialize an unbounded directory in memory.
        for path in root.iterdir():
            paths.append(path)
            if len(paths) > MAX_FILES:
                raise LocalDataError('草稿目录条目超过诊断上限；未执行清理')
        counts = dict(valid=0, corrupt=0, preserved=0, bytes=0)
        candidates = {}
        for path in sorted(paths):
            if not re.fullmatch(r'[0-9a-f]{64}\.json', path.name):
                counts['preserved'] += 1
                continue
            try:
                fingerprint = self._fingerprint(path)
            except (OSError, LocalDataError):
                counts['preserved'] += 1
                continue
            counts['bytes'] += fingerprint[2]
            malformed = False
            try:
                record = json.loads(path.read_text(encoding='utf-8'))
            except (ValueError, UnicodeError, RecursionError):
                record = None; malformed = True
            except OSError:
                raise LocalDataError('本地草稿读取失败；未执行清理') from None
            if not malformed and (type(record) is not dict
                    or set(record) != {'version','project_id','document_key','base_revision','values','position','updated_at'}
                    or type(record.get('version')) is not int or record['version'] != 1):
                # New formats and unknown parseable files are not garbage.
                counts['preserved'] += 1
                continue
            try:
                read_draft(path)
                counts['valid'] += 1
            except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
                counts['corrupt'] += 1
                candidates[secrets.token_urlsafe(18)] = (path.name, fingerprint)
            except OSError:
                raise LocalDataError('本地草稿读取失败；未执行清理') from None
        return counts, candidates

    def preview(self):
        with self.drafts._lock:
            try:
                counts, candidates = self._scan()
            except (OSError, LocalDataError):
                raise LocalDataError('本地草稿诊断读取失败或目录已变化；请保留输入并重试') from None
            now = time.monotonic()
            self.previews = {key: value for key, value in self.previews.items() if value[0] > now}
            while len(self.previews) >= 16:
                self.previews.pop(next(iter(self.previews)))
            token = secrets.token_urlsafe(24)
            self.previews[token] = (now + 300, candidates)
            database_bytes = 0
            for suffix in ('', '-wal', '-shm'):
                try:
                    database_bytes += Path(str(self.database) + suffix).stat().st_size
                except FileNotFoundError:
                    continue
                except OSError:
                    database_bytes = None
                    break
            # This is also the entire public diagnostic allowlist.
            report = dict(format_version=1, offline=self.offline,
                          model_generation_enabled=self.models_enabled,
                          database_bytes=database_bytes, recovery_drafts=counts,
                          credentials_included=False, content_included=False,
                          history_cleanup_supported=False,
                          draft_partition_in_backup=False)
            return dict(report=report, preview_token=token, expires_in_seconds=300,
                        candidates=[dict(id=identity, label=f'损坏草稿 {index + 1}',
                                         bytes=value[1][2])
                                    for index, (identity, value) in enumerate(candidates.items())],
                        warning='仅可逐项清理已损坏的本地恢复草稿，删除后不能恢复；有效草稿、未知文件、正式正文、历史、备份和凭据均保留。')

    def cleanup(self, *, preview_token, selected, confirmation):
        with self.drafts._lock:
            if (type(preview_token) is not str or type(selected) is not list
                    or not selected or len(selected) > MAX_FILES
                    or any(type(item) is not str for item in selected)
                    or len(set(selected)) != len(selected)
                    or confirmation != '清理损坏草稿'):
                raise LocalDataError('请逐项选择预览中的损坏草稿并明确确认')
            preview = self.previews.get(preview_token)
            if preview is None or preview[0] <= time.monotonic():
                raise LocalDataError('清理预览已过期；请重新预览')
            if any(identity not in preview[1] for identity in selected):
                raise LocalDataError('所选条目不属于本次预览')
            try:
                root = self._root()
                for identity in selected:
                    name, expected = preview[1][identity]
                    if self._fingerprint(root / name) != expected:
                        raise LocalDataError('所选草稿已变化；请重新预览')
                    try:
                        read_draft(root / name)
                    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
                        pass
                    else:
                        raise LocalDataError('所选草稿现已有效；请重新预览')
            except (OSError, LocalDataError):
                raise LocalDataError('所选草稿或目录已变化或不可访问；未清理，请重新预览') from None
            # Consume once before deletion; partial failure is reported accurately.
            self.previews.pop(preview_token)
            removed = 0
            removed_bytes = 0
            for identity in selected:
                name, expected = preview[1][identity]
                try:
                    if self._fingerprint(root / name) != expected:
                        break
                    (root / name).unlink()
                except (OSError, LocalDataError):
                    break
                removed += 1
                removed_bytes += expected[2]
            complete = removed == len(selected)
            return dict(completed=complete, removed_count=removed,
                        removed_bytes=removed_bytes, remaining_count=len(selected)-removed,
                        warning='' if complete else '部分条目未清理；已完成数量如实保留，请重新预览后重试。')
