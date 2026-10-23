"""PRD-sized fictional test: 500 chapters, 1M current chars, >=5 versions each.

Explicit output root required. No providers, user profile, or external network.
"""
import base64
import ctypes
from ctypes import wintypes
from hashlib import sha256
import json
import os
from pathlib import Path
import time
import traceback
from uuid import uuid4

from novel_writer.application import projects, versions
from novel_writer.application.backups import create_backup, restore_backup
from novel_writer.application.chapter_lifecycle import upgrade
from novel_writer.application.migration_text import export_text, preview
from novel_writer.application.service import NovelService
from novel_writer.application.skill_import import SkillLibrary
from novel_writer.domain.models import BookOutline, Chapter, VolumePlan
from novel_writer.storage.json_codec import document_from_dict, document_to_dict
from novel_writer.storage.sqlite_repository import SQLiteRepository


def peak_memory():
    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in (
                'peak_working', 'working', 'peak_paged', 'paged', 'peak_nonpaged',
                'nonpaged', 'pagefile', 'peak_pagefile')]
    kernel, psapi = ctypes.WinDLL('kernel32'), ctypes.WinDLL('psapi')
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    value = Counters()
    value.cb = ctypes.sizeof(value)
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(value), value.cb):
        raise OSError('GetProcessMemoryInfo failed')
    return value.peak_working


def main():
    out = Path(os.environ['NOVEL_WRITER_ARTIFACTS']).resolve()
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='running', chapter_count=500, initial_current_characters=1_000_000,
                  minimum_versions_per_chapter=5, real_provider_calls=0,
                  timings_seconds={}, checks=[])
    started = time.perf_counter()
    def measured(name, operation):
        before = time.perf_counter()
        value = operation()
        report['timings_seconds'][name] = round(time.perf_counter()-before, 4)
        print(json.dumps(dict(phase=name, seconds=report['timings_seconds'][name])), flush=True)
        return value
    def act(service, state, action, fields):
        return service.execute(state['document']['project']['id'], action, fields, expected_revision=state['revision'])
    def bodies(state):
        return [sha256(c['content'].encode('utf-8')).hexdigest() for c in state['document']['chapters']]
    def history(state):
        return {v['id']: sha256(json.dumps(v, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
                for v in state['document']['versions']}
    try:
        def fixture():
            state = projects.create(dict(title='虚构五百章规模'))
            upgrade(state)
            document = document_from_dict(state['document'])
            phrase = '海风吹过虚构港湾，作者只在隔离目录中写作。'
            for index in range(500):
                chapter = Chapter(project_id=document.project.id, number=index+1, title=f'虚构章{index+1}')
                document.chapters.append(chapter)
                for revision in range(5):
                    prefix = f'虚构第{index+1}章第{revision+1}版。'
                    chapter.content = prefix+(phrase*100)[:2000-len(prefix)-1]+'\n'
                    assert len(chapter.content) == 2000
                    versions.record(document, 'chapter', chapter, '虚构固定规模历史')
            document.book_outline = BookOutline(project_id=document.project.id, volumes=[
                VolumePlan(number=number+1, title=f'虚构卷{number+1}', chapter_ids=[c.id for c in document.chapters[number*100:(number+1)*100]])
                for number in range(5)])
            versions.record(document, 'book_outline', document.book_outline, '虚构五卷')
            state['document'] = document_to_dict(document)
            return state
        state = measured('build_fixture', fixture)
        scope = os.environ.get('NOVEL_WRITER_BENCHMARK_AUTHOR_SCOPE', 'legacy')
        assert scope in ('legacy', 'author-unlocked', 'author-locked')
        if scope != 'legacy':
            from novel_writer.application.author_scope import upgrade as upgrade_author_scope
            upgrade_author_scope(state)
        database = out/'fiction.sqlite3'
        repository = SQLiteRepository(database)
        SkillLibrary(database)
        service = NovelService(repository)
        state = measured('persist_initial', lambda: repository.create(state))
        if scope == 'author-locked':
            from novel_writer.domain.author_scope import digest
            chapter = state['document']['chapters'][0]
            state = measured('create_persistent_lock', lambda: act(service, state, 'lock_body_range', dict(
                operation_id=str(uuid4()), confirmed=True, chapter_id=chapter['id'],
                version_id=chapter['current_version_id'], body_sha256=digest(chapter['content']),
                start=0, end=10, text_sha256=digest(chapter['content'][:10]))))
        original_history = history(state)
        assert sum(len(c['content']) for c in state['document']['chapters']) == 1_000_000
        report['initial_version_count'] = len(original_history)
        chapter_versions={chapter['id']:[] for chapter in state['document']['chapters']}
        for version in state['document']['versions']:
            if version['entity_type']=='chapter':chapter_versions[version['entity_id']].append(version['version_number'])
        assert all(numbers==[1,2,3,4,5] for numbers in chapter_versions.values())
        report['initial_chapter_version_min']=min(map(len,chapter_versions.values()))
        report['initial_chapter_version_max']=max(map(len,chapter_versions.values()))
        report['fixture_workspace_version']=state['workspace_version']
        from novel_writer.domain.author_scope import active_locks
        initial_locks = active_locks(state)
        report['fixture_active_range_locks']=len(initial_locks)
        report['fixture_author_scope_mode']=scope
        save_samples=[]
        save_revisions=[]
        for iteration in range(30):
            index=(0,249,499)[iteration%3]
            chapter = state['document']['chapters'][index]
            before=time.perf_counter()
            state = act(service, state, 'save_chapter', dict(chapter_id=chapter['id'],content=chapter['content']+'继续写作。\n'))
            save_samples.append(round(time.perf_counter()-before,6))
            save_revisions.append(state['revision'])
            print(json.dumps(dict(phase='actual_save',sample=iteration+1,chapter=index+1,revision=state['revision'],seconds=save_samples[-1])),flush=True)
        reopened = measured('reopen', lambda: NovelService(SQLiteRepository(database)).get(state['document']['project']['id']))
        assert reopened == state
        samples=[]
        for iteration in range(30):
            before=time.perf_counter()
            assert service.get(state['document']['project']['id']) == state
            samples.append(round(time.perf_counter()-before,4))
        report['warm_read_samples_seconds']=samples
        report['warm_read_p95_seconds']=sorted(samples)[28]
        report['warm_read_sample_count']=len(samples)
        report['save_sample_count']=len(save_samples)
        report['save_samples_seconds']=save_samples
        report['save_revisions']=save_revisions
        report['save_p95_seconds']=sorted(save_samples)[28]
        report['save_p95_accepted']=report['save_p95_seconds']<1.0
        report['p95_method']='nearest rank: sorted 30 samples, rank ceil(0.95*30)=29'
        current_history = history(state)
        assert all(current_history[key] == value for key, value in original_history.items())
        report['checks'].append('500 chapters / 1M initial characters / 2500 chapter versions; 30 actual saves across first-middle-last; contiguous saved revisions and all original version hashes retained')
        assert save_revisions==list(range(save_revisions[0],save_revisions[0]+30))
        if initial_locks:
            final_locks = active_locks(state)
            assert set(final_locks) == set(initial_locks)
            for identity, lock in initial_locks.items():
                current = final_locks[identity]
                chapter = next(c for c in state['document']['chapters'] if c['id'] == current['chapter_id'])
                assert (current['start'], current['end'], current['text_sha256']) == (lock['start'], lock['end'], lock['text_sha256'])
                assert current['version_id'] == chapter['current_version_id']
            report['checks'].append('one persistent first-chapter Unicode range lock stays exact and rebases to current version during 10 outside-range appends; all 30 saves remain explicit')
        report['final_version_count']=len(state['document']['versions'])
        report['final_current_characters']=sum(len(chapter['content']) for chapter in state['document']['chapters'])
        if os.environ.get('NOVEL_WRITER_SAVE_BENCHMARK_ONLY')=='1':
            report.update(status='passed',benchmark_only=True,backup_flow_executed=False,
                          database_bytes=database.stat().st_size,total_seconds=round(time.perf_counter()-started,4),peak_working_set_bytes=peak_memory())
            return
        text = measured('export_txt', lambda: export_text(state, 'book', 'txt'))
        raw = text.encode('gb18030')
        target_service = NovelService(SQLiteRepository(out/'import.sqlite3'))
        imported = target_service.create(title='虚构旧编码重新导入')
        parsed = measured('gb18030_preview_500', lambda: preview(imported['document']['project']['id'],raw,'auto',imported,'fiction.txt'))
        assert parsed['encoding'] == 'gb18030' and len(parsed['items']) == 500
        imported = measured('gb18030_import_500', lambda: act(target_service, imported, 'import_chapters', dict(
            filename='fiction.txt', content_base64=base64.b64encode(raw).decode('ascii'), encoding='auto',
            items=[{key:item[key] for key in ('index','title','start','content_start','end','chars')} for item in parsed['items']],
            preview_sha256=parsed['preview_sha256'], confirmed=True)))
        # Export adds one separator LF; chapter internal content is exact.
        assert all(new['content'] == old['content']+'\n' for old,new in zip(state['document']['chapters'],imported['document']['chapters']))
        report['checks'].append('500-chapter GB18030 auto preview and actual import; every internal body matches plus explicit export separator LF')
        package = out/'fiction.nwbak'
        measured('backup', lambda: create_backup(database, package))
        restored = measured('restore', lambda: restore_backup(package, out/'restored'))
        recovered_service = NovelService(SQLiteRepository(restored['database_path']))
        recovered = measured('restored_reopen', lambda: recovered_service.get(state['document']['project']['id']))
        assert bodies(recovered) == bodies(state) and history(recovered) == history(state)
        chapter = recovered['document']['chapters'][249]
        old_version = next(v for v in recovered['document']['versions'] if v['entity_id']==chapter['id'] and v['version_number']==2)
        count = len(recovered['document']['versions'])
        recovered = measured('restore_historical_version', lambda: act(recovered_service,recovered,'restore_chapter',dict(chapter_id=chapter['id'],version_id=old_version['id'])))
        assert recovered['document']['chapters'][249]['content'] == old_version['snapshot']['content']
        assert len(recovered['document']['versions']) == count+1
        recovered = measured('continue_after_restore', lambda: act(recovered_service,recovered,'save_chapter',dict(chapter_id=chapter['id'],content=old_version['snapshot']['content']+'恢复后继续写作。')))
        assert recovered_service.get(recovered['document']['project']['id']) == recovered
        recovered_history = history(recovered)
        assert all(recovered_history[key] == value for key,value in current_history.items())
        report['checks'].append('full backup, independent restore, historical restore as a new version, continue writing and disk reopen; every earlier version hash retained')
        report.update(status='passed', database_bytes=database.stat().st_size, backup_bytes=package.stat().st_size,
                      total_seconds=round(time.perf_counter()-started,4), peak_working_set_bytes=peak_memory())
    except Exception:
        report.update(status='failed', error=traceback.format_exc(), total_seconds=round(time.perf_counter()-started,4))
        raise
    finally:
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
