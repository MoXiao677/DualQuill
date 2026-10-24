"""Local immutable attachment originals and bounded text extraction; no network calls."""
from __future__ import annotations
import hashlib
import io
import json
import os
import re
import threading
import time
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TEXT_CHARS = 200_000
_ALLOWED = {'.txt', '.md', '.markdown', '.docx', '.pdf'}

def _safe_name(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('附件文件名无效')
    value = unicodedata.normalize('NFC', value).replace('\\', '/').rsplit('/', 1)[-1]
    return ''.join(c for c in value if ord(c) >= 32 and ord(c) != 127)[:180] or 'attachment'

def _decode(raw):
    if raw.startswith(b'\xef\xbb\xbf'): return raw.decode('utf-8-sig')
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')): return raw.decode('utf-16')
    for encoding in ('utf-8', 'gb18030'):
        try: return raw.decode(encoding)
        except UnicodeDecodeError: pass
    raise ValueError('文本编码须为 UTF-8、带 BOM 的 UTF-16 或 GB18030')

def _docx(raw):
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if len(infos) > 4096 or sum(i.file_size for i in infos) > 32 * 1024 * 1024:
                raise ValueError('DOCX 解压内容过大')
            for i in infos:
                if i.flag_bits & 1 or i.filename.startswith('/') or '..' in PurePosixPath(i.filename).parts or i.file_size > 16 * 1024 * 1024:
                    raise ValueError('DOCX 包含加密、不安全或过大的内容')
                if i.file_size > 1024 * 1024 and i.file_size / max(i.compress_size, 1) > 100:
                    raise ValueError('DOCX 压缩比例过高')
            document = archive.read('word/document.xml')
            if re.search(br'<!\s*(?:DOCTYPE|ENTITY)', document, re.I) or b'\x00' in document:
                raise ValueError('DOCX XML 包含不支持的编码或实体声明')
        root = ET.fromstring(document)
    except (KeyError, zipfile.BadZipFile, ET.ParseError) as error:
        raise ValueError('DOCX 文件结构无效') from error
    ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    return '\n'.join(''.join(n.text or '' for n in p.iter(ns + 't')) for p in root.iter(ns + 'p'))

def _pdf(raw):
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted: raise ValueError('PDF 已加密，无法读取；原文件已保留')
        if len(reader.pages) > 200: raise ValueError('PDF 超过 200 页，请拆分后上传')
        parts, total = [], 0
        for page in reader.pages:
            part = page.extract_text() or ''
            total += len(part) + 1
            if total > MAX_TEXT_CHARS: raise ValueError('PDF 文本超过 200000 字，请拆分后上传')
            parts.append(part)
        text = '\n'.join(parts)
    except ValueError: raise
    except Exception as error: raise ValueError('PDF 解析失败，原文件已保留') from error
    if not text.strip(): raise ValueError('扫描 PDF 不支持，没有可提取文本；原文件已保留')
    return text

def extract(filename, raw):
    suffix = Path(filename).suffix.lower()
    if suffix not in _ALLOWED: raise ValueError('仅支持 TXT、Markdown、DOCX 和文本 PDF；不支持 DOC')
    text = _decode(raw) if suffix in ('.txt', '.md', '.markdown') else _docx(raw) if suffix == '.docx' else _pdf(raw)
    if not text.strip(): raise ValueError('文件没有可导入的文本')
    if len(text) > MAX_TEXT_CHARS: raise ValueError('提取文本超过 200000 字，请拆分后上传；原文件已保留')
    return text

def sections(text):
    matches = list(re.finditer(r'(?mi)^[ \t]*(?:第\s*[0-9零〇一二三四五六七八九十百千万两]+\s*[章节回][^\r\n]*|#{1,6}\s+[^\r\n]+|Chapter\s+\d+[^\r\n]*)[ \t]*\r?$', text))
    if not matches: return [dict(id='section0', title='全文', content=text, start=0, end=len(text))]
    spans = ([(0, '前言')] if matches[0].start() else []) + [(m.start(), m.group(0).strip()[:200]) for m in matches]
    return [dict(id='section' + str(i), title=title, content=text[start:spans[i + 1][0] if i + 1 < len(spans) else len(text)], start=start, end=spans[i + 1][0] if i + 1 < len(spans) else len(text)) for i, (start, title) in enumerate(spans)]

class ChatAttachments:
    _lock = threading.RLock()
    def __init__(self, database_path):
        self.root = Path(database_path).resolve().parent / 'attachments'
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.root / 'manifest.json'
    @staticmethod
    def _id(value):
        try: return str(UUID(str(value)))
        except (ValueError, TypeError, AttributeError): raise ValueError('附件编号无效') from None
    @staticmethod
    def _summary(record):
        return {k: v for k, v in record.items() if k not in ('text', 'sections')}
    def _atomic_json(self, path, value):
        temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
        try:
            with temporary.open('w', encoding='utf-8') as handle:
                json.dump(value, handle, ensure_ascii=False)
                handle.flush(); os.fsync(handle.fileno())
            temporary.replace(path)
        finally: temporary.unlink(missing_ok=True)
    def _manifest(self):
        if self.manifest_path.is_file():
            value = json.loads(self.manifest_path.read_text(encoding='utf-8'))
            if type(value) is not dict or type(value.get('attachments')) is not dict or type(value.get('operations')) is not dict: raise ValueError('附件索引损坏')
            return value
        value = {'attachments': {}, 'operations': {}}
        for path in self.root.glob('*/metadata.json'):
            record = json.loads(path.read_text(encoding='utf-8'))
            if self._id(record['id']) != path.parent.name: raise ValueError('附件索引编号无效')
            value['attachments'][record['id']] = self._summary(record)
            if record.get('operation_id'): value['operations'][record['operation_id']] = dict(id=record['id'], sha256=record['sha256'], filename=record['filename'])
        return value
    def _persist(self, record):
        manifest = self._manifest()
        self._atomic_json(self.root / self._id(record['id']) / 'metadata.json', record)
        manifest['attachments'][record['id']] = self._summary(record)
        if record.get('operation_id'): manifest['operations'][record['operation_id']] = dict(id=record['id'], sha256=record['sha256'], filename=record['filename'])
        self._atomic_json(self.manifest_path, manifest)
    def save(self, filename, raw, project_id=None, operation_id=None):
        if not isinstance(raw, (bytes, bytearray)) or not 0 < len(raw) <= MAX_FILE_BYTES: raise ValueError('附件须为非空文件且不超过 8 MiB')
        if project_id is not None and (type(project_id) is not str or not project_id): raise ValueError('小说编号无效')
        name, checksum = _safe_name(filename), hashlib.sha256(raw).hexdigest()
        operation_id = self._id(operation_id) if operation_id is not None else None
        with self._lock:
            prior = self._manifest()['operations'].get(operation_id) if operation_id else None
            if prior:
                record = self.get(prior['id'])
                if prior['sha256'] != checksum or prior['filename'] != name or record.get('project_id') != project_id: raise ValueError('上传操作编号已用于其他文件或小说')
                return self._summary(record)
            identifier, now = str(uuid4()), time.time()
            directory = self.root / identifier; directory.mkdir()
            with (directory / 'original').open('xb') as handle: handle.write(raw); handle.flush(); os.fsync(handle.fileno())
            record = dict(id=identifier, filename=name, title=name, size=len(raw), sha256=checksum, created_at=now, updated_at=now, project_id=project_id, status='pending', error='', archived=False, material_id=None, source_ids=[], operation_id=operation_id, original='original')
            try: record['text'] = extract(name, bytes(raw)); record['sections'] = sections(record['text']); record['status'] = 'parsed'
            except Exception as error: record.update(status='error', error=str(error), text='', sections=[])
            self._persist(record)
            return self._summary(record)
    def get(self, attachment_id, project_id=None):
        path = self.root / self._id(attachment_id) / 'metadata.json'
        if not path.is_file(): raise KeyError('附件不存在')
        record = json.loads(path.read_text(encoding='utf-8'))
        if project_id is not None and record.get('project_id') != project_id: raise ValueError('附件不属于当前小说')
        return record
    def bind(self, attachment_ids, project_id):
        if type(attachment_ids) is not list or not project_id: raise ValueError('附件绑定参数无效')
        ids = [self._id(i) for i in attachment_ids]
        if len(ids) != len(set(ids)): raise ValueError('附件编号重复')
        with self._lock:
            records = [self.get(i) for i in ids]
            for r in records:
                if r.get('status') != 'parsed' or r.get('archived') or r.get('project_id') not in (None, project_id): raise ValueError('附件解析失败、已归档或不属于当前小说')
            for r in records: r.update(project_id=project_id, updated_at=time.time()); self._persist(r)
            return [self._summary(r) for r in records]
    def list(self, project_id, include_archived=True):
        with self._lock:
            records = [self.get(i) for i in self._manifest()['attachments']]
            return sorted([self._summary(r) for r in records if r.get('project_id') == project_id and (include_archived or not r.get('archived'))], key=lambda r: r.get('created_at', 0))
    def _set_archived(self, attachment_id, project_id, archived):
        with self._lock:
            record = self.get(attachment_id)
            if record.get('project_id') != project_id: raise ValueError('附件不属于当前小说')
            record.update(archived=archived, updated_at=time.time()); self._persist(record)
            return self._summary(record)
    def archive(self, attachment_id, project_id): return self._set_archived(attachment_id, project_id, True)
    def restore(self, attachment_id, project_id): return self._set_archived(attachment_id, project_id, False)
    def associate_material(self, attachment_id, project_id, material_id, source_ids=None):
        with self._lock:
            record = self.get(attachment_id)
            if record.get('project_id') != project_id: raise ValueError('附件不属于当前小说')
            record.update(material_id=material_id, source_ids=list(dict.fromkeys((record.get('source_ids') or []) + (source_ids or []))), updated_at=time.time()); self._persist(record)
            return self._summary(record)
    def import_local_path(self, value, project_id=None, operation_id=None):
        """Read only an explicit author path; never exposed as a model tool."""
        import stat
        from uuid import uuid5
        operation = UUID(self._id(operation_id))
        if type(value) is not str or not value.strip(): raise ValueError('必须提供本地绝对路径')
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"): value = value[1:-1]
        path = Path(value)
        if not path.is_absolute() or value.startswith(('\\\\', '//')) or '..' in path.parts or path.parent == path:
            raise ValueError('只允许本机非根目录绝对路径，不支持 UNC、设备路径或父目录跳转')
        blocked = re.compile(r'(?i)(?:^\.|password|passwd|credential|secret|token|config|settings|profile|appdata|program files|windows|node_modules|private|id_rsa|id_ed25519|密码|口令|凭据|密钥|配置)')
        def checked(item):
            for part in item.parts[1:]:
                if blocked.search(part): raise ValueError('不允许读取隐藏、程序、凭证或配置路径')
            for parent in reversed((item, *item.parents)):
                info = parent.lstat()
                attributes = getattr(info, 'st_file_attributes', 0)
                if stat.S_ISLNK(info.st_mode) or attributes & 0x402:
                    raise ValueError('不允许读取隐藏、链接或 reparse 路径')
            return item.lstat()
        checked(path)
        request_key = hashlib.sha256((str(path) + '\0' + str(project_id)).encode('utf-8')).hexdigest()
        receipt = self.root / ('path-' + str(operation) + '.json')
        with self._lock:
            if receipt.is_file():
                previous = json.loads(receipt.read_text(encoding='utf-8'))
                if previous['request_key'] != request_key: raise ValueError('操作编号已用于其他路径或小说')
                return previous['attachments']
            candidates, visited, total = [], 0, 0
            def collect(item, depth):
                nonlocal visited, total
                visited += 1
                if visited > 2000: raise ValueError('文件夹条目超过 2000，请选择更小的文件夹')
                try: info = checked(item)
                except ValueError:
                    if item == path: raise
                    return
                if stat.S_ISDIR(info.st_mode):
                    if depth > 5: raise ValueError('文件夹深度超过 5 层，请选择更小的文件夹')
                    with os.scandir(item) as entries:
                        for entry in entries: collect(Path(entry.path), depth + 1)
                elif stat.S_ISREG(info.st_mode):
                    if item.suffix.lower() not in _ALLOWED:
                        if item == path: raise ValueError('仅支持 TXT、MD、DOCX 和文本 PDF')
                        return
                    if not 0 < info.st_size <= MAX_FILE_BYTES: raise ValueError('文件为空或超过 8 MiB：' + item.name)
                    candidates.append(item); total += info.st_size
                    if len(candidates) > 30 or total > 64 * 1024 * 1024:
                        raise ValueError('导入超过 30 个文件或 64 MiB，请分批选择文件夹')
                elif item == path: raise ValueError('路径必须是普通文件或文件夹')
            collect(path, 0)
            if not candidates: raise ValueError('没有可安全导入的支持文件；已跳过链接及敏感配置')
            candidates.sort(key=lambda item: str(item))
            results = []
            for item in candidates:
                before = checked(item)
                flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
                descriptor = os.open(item, flags)
                with os.fdopen(descriptor, 'rb') as handle:
                    opened = os.fstat(handle.fileno())
                    if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                        raise ValueError('文件在读取前发生变化，请重试')
                    data = handle.read(MAX_FILE_BYTES + 1)
                    after = os.fstat(handle.fileno())
                checked(item)
                if len(data) > MAX_FILE_BYTES or (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError('文件在读取时发生变化或超过限制，请重试')
                child_operation = str(uuid5(operation, request_key + '\0' + str(item)))
                results.append(self.save(item.name, data, project_id, child_operation))
            self._atomic_json(receipt, dict(request_key=request_key, attachments=results))
            return results

    def original(self, attachment_id, project_id=None):
        record = self.get(attachment_id)
        if record.get('project_id') != project_id: raise ValueError('附件不属于当前小说')
        raw = (self.root / self._id(attachment_id) / 'original').read_bytes()
        if hashlib.sha256(raw).hexdigest() != record['sha256']: raise ValueError('附件原文件校验失败')
        return record, raw
