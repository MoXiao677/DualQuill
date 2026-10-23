"""C10 read-only compatibility: real frozen oracles and synthetic empty formats."""
from copy import deepcopy
from hashlib import sha256
from importlib import import_module
import json
from pathlib import Path
import sqlite3
from contextlib import closing
import tempfile
import unittest

from novel_writer.application.graph_index import rebuild
from novel_writer.application.knowledge import view
from novel_writer.application.projects import create
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository


class GraphLegacyTests(unittest.TestCase):
    def inspect_without_write(self, database, expected_version):
        before = database.read_bytes()
        with closing(sqlite3.connect(database)) as connection:
            versions = {identity: json.loads(payload)['workspace_version'] for identity, payload in connection.execute('SELECT id, payload FROM projects')}
        self.assertIn(expected_version, versions.values())
        service = NovelService(SQLiteRepository(database))
        for project in service.list_projects():
            identity = project['id']
            state = service.get(identity)
            self.assertEqual(state['workspace_version'], versions[identity])
            self.assertNotIn('graph_extractions', state)
            self.assertNotIn('graph_decisions', state)
            first = view(service, identity, {})
            index = rebuild(service, identity, dict(expected_revision=state['revision']))
            self.assertEqual(rebuild(service, identity, dict(expected_revision=state['revision'])), index)
            self.assertEqual(view(service, identity, {}), first)
            self.assertEqual(service.get(identity), state)
        self.assertEqual(sha256(database.read_bytes()).hexdigest(), sha256(before).hexdigest())
        self.assertEqual(database.read_bytes(), before)

    def test_populated_frozen_v1_v7_v10_v11_databases_stay_byte_identical(self):
        fixtures = Path(__file__).resolve().parent / 'fixtures'
        specifications = [(1, 's3b_legacy_v1.json', None), (2, 's4a_legacy.json', 'v2'),
            (3, 's5a_legacy.json', 'v3'), (4, 's5b_legacy.json', 'v4'),
            (5, 's5c_legacy.json', 'v5'), (6, 's6a_legacy.json', 'v6'),
            (7, 's6b_legacy.json', 'v7'), (10, 'f1_legacy_v10.json', None),
            (11, 'f1ai_legacy_v11.json', None)]
        with tempfile.TemporaryDirectory(prefix='graph-frozen-') as directory:
            for version, name, key in specifications:
                with self.subTest(version=version):
                    fixture = json.loads((fixtures / name).read_text(encoding='utf8'))
                    if key:
                        fixture = fixture[key]
                    database = Path(directory) / ('v' + str(version) + '.sqlite3')
                    database.write_bytes(bytes.fromhex(fixture['database_hex']))
                    self.inspect_without_write(database, version)

    def test_all_v1_v35_synthetic_empty_collections_stay_byte_identical(self):
        # These are structural compatibility cases, not historical populated oracles.
        collections = [(2, None, ('memories', 'memory_history')),
            (3, 'tasks', 'COLLECTIONS'), (4, 'review', 'REVIEW_COLLECTIONS'),
            (5, 'knowledge', 'KNOWLEDGE_COLLECTIONS'), (6, 'model_contract', 'MODEL_COLLECTIONS'),
            (7, 'experiments', 'EXPERIMENT_COLLECTIONS'), (8, 'workflows', 'WORKFLOW_COLLECTIONS'),
            (10, 'creation_presets', 'CREATION_COLLECTIONS'), (11, 'book_creation', 'COLLECTIONS'),
            (12, 'book_ai', 'COLLECTIONS'), (13, 'styles', 'COLLECTIONS'),
            (14, 'public_search', 'COLLECTIONS'), (15, 'style_trials', 'COLLECTIONS'),
            (16, 'chapter_writing', 'COLLECTIONS'), (17, 'chapter_planning', 'COLLECTIONS'),
            (18, 'scene_expansion', 'COLLECTIONS'), (19, 'chapter_lifecycle', 'COLLECTIONS'),
            (20, 'console', 'COLLECTIONS'), (21, None, ('scoped_rules',)),
            (22, None, ('scoped_rule_history',)), (23, 'memory_rollups', 'COLLECTIONS'),
            (24, 'console', 'RUN_COLLECTIONS'), (25, 'materials', 'COLLECTIONS'),
            (26, 'full_book_planning', 'COLLECTIONS'), (27, 'chapter_trash', 'COLLECTIONS')]
        original = create(dict(title='虚构格式兼容样本'))
        with tempfile.TemporaryDirectory(prefix='graph-formats-') as directory:
            for version in range(1, 36):
                with self.subTest(version=version):
                    state = deepcopy(original)
                    state['workspace_version'] = version
                    for minimum, module, attribute in collections:
                        if version >= minimum:
                            names = getattr(import_module('novel_writer.domain.' + module), attribute) if module else attribute
                            state.update({name: [] for name in names})
                    database = Path(directory) / ('v' + str(version) + '.sqlite3')
                    SQLiteRepository(database).create(state)
                    self.inspect_without_write(database, version)


if __name__ == '__main__':
    unittest.main()
