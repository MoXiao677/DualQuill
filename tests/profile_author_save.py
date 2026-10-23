"""Profile one actual save on an independent copy of the fixed fixture."""
from pathlib import Path
from contextlib import closing
import cProfile
import io
import os
import pstats
import sqlite3
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository

root=Path(os.environ['NOVEL_WRITER_ARTIFACTS']).resolve()
root.mkdir(parents=True,exist_ok=False)
source=Path(os.environ['NOVEL_WRITER_PROFILE_SOURCE']).resolve()
with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as before,closing(sqlite3.connect(root/'fiction.sqlite3')) as target:before.backup(target)
service=NovelService(SQLiteRepository(root/'fiction.sqlite3'));pid=service.list_projects()[0]['id'];state=service.get(pid)
chapter=state['document']['chapters'][249];profile=cProfile.Profile()
state=profile.runcall(service.execute,pid,'save_chapter',dict(chapter_id=chapter['id'],content=chapter['content']+'独立性能剖析'),expected_revision=state['revision'])
profile.dump_stats(str(root/'save.prof'))
stream=io.StringIO();pstats.Stats(profile,stream=stream).strip_dirs().sort_stats('cumulative').print_stats(45)
(root/'profile.txt').write_text(stream.getvalue(),encoding='utf-8');print(stream.getvalue())
