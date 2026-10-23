import hashlib
import os
import json
from pathlib import Path
import sqlite3
import sys
import time
import traceback
from uuid import uuid4

AUDIT_ROOT = Path(os.environ['NOVEL_WRITER_ARTIFACTS'])
BACKEND = Path(os.environ.get('NOVEL_WRITER_AUDIT_BACKEND',str(Path(__file__).resolve().parents[1]/'src')))
sys.path.insert(0, str(BACKEND))

from novel_writer.application import projects, versions
from novel_writer.application.backups import create_backup, restore_backup
from novel_writer.application.chapter_lifecycle import upgrade
from novel_writer.application.migrations import migrate
from novel_writer.application.service import NovelService
from novel_writer.application.skill_import import SkillLibrary
from novel_writer.domain.models import BookOutline, Chapter, VolumePlan
from novel_writer.storage.json_codec import document_from_dict, document_to_dict
from novel_writer.storage.sqlite_repository import SQLiteRepository


def digest(document):
    return {
        chapter['number']: hashlib.sha256(chapter['content'].encode('utf-8')).hexdigest()
        for chapter in document['chapters']
    }


def main():
    output = AUDIT_ROOT / 'scale'
    output.mkdir(exist_ok=False)
    database = output / 'fictional-million-character.sqlite3'
    report = {
        'status': 'running', 'fictional': True, 'backend': str(BACKEND),
        'database': str(database), 'chapter_count': 200,
        'characters_per_chapter': 5000, 'save_count': 12,
        'timings_seconds': {}, 'checks': [], 'provider_calls': 0,
    }

    def measured(name, operation):
        started = time.perf_counter()
        result = operation()
        report['timings_seconds'][name] = round(time.perf_counter() - started, 4)
        print(json.dumps({'phase': name, 'seconds': report['timings_seconds'][name]}), flush=True)
        return result

    try:
        state = projects.create({'title': '百万字隔离验收样本'})
        upgrade(state)
        document = document_from_dict(state['document'])
        phrase = '海风吹过虚构港湾少年沿着石阶走向灯塔旧信纸上的字迹在晨光里渐渐清晰。'
        for index in range(report['chapter_count']):
            prefix = f'虚构长篇第{index + 1:03d}章。'
            body = prefix + (phrase * (5000 // len(phrase) + 1))[:5000 - len(prefix)]
            chapter = Chapter(project_id=document.project.id, number=index + 1,
                              title=f'规模验收 {index + 1:03d}', content=body)
            document.chapters.append(chapter)
            versions.record(document, 'chapter', chapter, '虚构规模样本初始版本')
        document.book_outline = BookOutline(
            project_id=document.project.id, theme='虚构规模验收',
            volumes=[VolumePlan(number=index + 1, title=f'虚构卷 {index + 1}',
                                chapter_ids=[chapter.id for chapter in document.chapters[index * 50:(index + 1) * 50]])
                     for index in range(4)])
        versions.record(document, 'book_outline', document.book_outline, '虚构分卷')
        state['document'] = document_to_dict(document)
        repository = SQLiteRepository(database)
        SkillLibrary(database)
        service = NovelService(repository)
        state = measured('create_million_character_project', lambda: repository.create(state))
        initial_version_count = len(state['document']['versions'])
        project_id = document.project.id
        report['project_id'] = project_id
        report['characters_total'] = sum(len(chapter['content']) for chapter in state['document']['chapters'])
        assert report['characters_total'] == 1_000_000
        original = digest(state['document'])
        save_samples = []
        for iteration in range(report['save_count']):
            chapter = state['document']['chapters'][iteration * 16]
            started = time.perf_counter()
            state = service.execute(project_id, 'save_chapter', {
                'chapter_id': chapter['id'], 'title': chapter['title'],
                'content': chapter['content'] + f'\n第{iteration + 1}次实际保存。', 'status': 'draft'},
                expected_revision=state['revision'])
            save_samples.append(round(time.perf_counter() - started, 4))
            print(json.dumps({'save': iteration + 1, 'seconds': save_samples[-1]}), flush=True)
        report['save_samples_seconds'] = save_samples
        report['checks'].append('200 chapters and 1000000 original characters saved through 12 real revision writes')
        reopened = measured('reopen_project', lambda: NovelService(SQLiteRepository(database)).get(project_id))
        assert reopened == state
        assert len(reopened['document']['versions']) == initial_version_count + report['save_count']
        report['checks'].append('reopening retains exact state and every initial and newly saved entity version')
        untouched = [index for index in original if (index - 1) % 16 != 0 or index > 177]
        current_hashes = digest(reopened['document'])
        assert all(current_hashes[index] == original[index] for index in untouched)
        report['checks'].append('all unedited chapters retain exact body hashes')
        search = measured('literal_search', lambda: service.search_local(project_id, {
            'query': '虚构长篇第200章', 'chapter_id': reopened['document']['chapters'][-1]['id'],
            'scopes': ['body'], 'whole_book': True, 'limit': 30}))
        assert len(search['hits']) == 1
        assert search['hits'][0]['entity_id'] == reopened['document']['chapters'][-1]['id']
        report['checks'].append('whole-book literal search finds the unique last chapter')
        archive = output / 'million-character.nwbak'
        measured('create_full_backup', lambda: create_backup(database, archive))
        restored = measured('restore_full_backup', lambda: restore_backup(archive, output / 'restored'))
        restored_state = NovelService(SQLiteRepository(restored['database_path'])).get(project_id)
        assert restored_state == reopened
        report['checks'].append('independent backup restore retains the complete million-character history')
        target = output / 'copy.sqlite3'
        SQLiteRepository(target)
        SkillLibrary(target)
        copied = measured('copy_full_project', lambda: migrate(archive, target, operation_id=str(uuid4())))
        clone = NovelService(SQLiteRepository(target)).get(copied['projects'][0]['new_id'])
        assert clone['document']['project']['id'] != project_id
        assert digest(clone['document']) == current_hashes
        assert len(clone['document']['versions']) == len(reopened['document']['versions'])
        report['checks'].append('project copy maps identity and retains every body hash and version')
        with sqlite3.connect(database) as connection:
            report['snapshot_count'] = connection.execute('SELECT COUNT(*) FROM project_snapshots').fetchone()[0]
        report['database_bytes'] = database.stat().st_size
        report['backup_bytes'] = archive.stat().st_size
        report['status'] = 'passed'
    except Exception:
        report['status'] = 'failed'
        report['error'] = traceback.format_exc()
        raise
    finally:
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
