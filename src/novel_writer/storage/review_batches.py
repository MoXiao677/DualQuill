"""Local immutable batch manifests; execution remains in shared generation tasks.

Manifests are local orchestration metadata in a sibling local SQLite database.
They are deliberately not injected into the versioned portable workspace format.
"""
from contextlib import contextmanager
import sqlite3
import json
from novel_writer.storage.sqlite_repository import ConflictError


class ReviewBatchStore:
    def __init__(self, repository):
        self.repository = repository
        self.path = repository.path.with_name(repository.path.name + '.deep-reviews.sqlite3')

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute('PRAGMA synchronous=FULL')
            with connection:
                yield connection
        finally:
            connection.close()

    def list(self, project_id):
        if not self.path.is_file():
            return []
        with self._connection() as connection:
            exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='deep_review_books'").fetchone()
            if not exists:
                return []
            return [json.loads(row['payload']) for row in connection.execute('SELECT payload FROM deep_review_books WHERE project_id=? ORDER BY rowid', (project_id,))]

    def create(self, manifest, expected_revision):
        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('CREATE TABLE IF NOT EXISTS deep_review_books (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, payload TEXT NOT NULL)')
            old = connection.execute('SELECT payload FROM deep_review_books WHERE id=?', (manifest['id'],)).fetchone()
            if old:
                old = json.loads(old['payload'])
                if old['project_id'] != manifest['project_id'] or old['request'] != manifest['request']:
                    raise ConflictError('整书审核编号已绑定其他输入')
                return old
            state = self.repository.get(manifest['project_id'])
            if state['revision'] != expected_revision:
                raise ConflictError('保存编号已变化，请刷新后创建整书审核')
            connection.execute('INSERT INTO deep_review_books VALUES (?,?,?)', (manifest['id'], manifest['project_id'], json.dumps(manifest, ensure_ascii=False)))
        return manifest

