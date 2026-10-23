"""Synthetic minimal V1-V35 read-only compatibility; not historical fixture proof."""
from copy import deepcopy
import importlib,tempfile,unittest
from pathlib import Path
from novel_writer.application.service import NovelService
from novel_writer.application.chapter_lifecycle import upgrade
from novel_writer.storage.sqlite_repository import SQLiteRepository
from novel_writer.application.comparisons import ComparisonCoordinator,public_workspace
from novel_writer.application.tasks import TaskCoordinator
from novel_writer.application.task_protocol import AdapterRegistry

class WritingComparisonLegacyTests(unittest.TestCase):
    def test_all_35_minimal_workspace_versions_remain_exactly_read_only(self):
        with tempfile.TemporaryDirectory(prefix='c04-legacy-') as directory:
            root=Path(directory);service=NovelService(SQLiteRepository(root/'source.sqlite3'));base=service.create(title='旧格式虚构空书');full=deepcopy(base);upgrade(full)
            thresholds=[(2,None,('memories','memory_history')),(3,'tasks','COLLECTIONS'),(4,'review','REVIEW_COLLECTIONS'),(5,'knowledge','KNOWLEDGE_COLLECTIONS'),(6,'model_contract','MODEL_COLLECTIONS'),(7,'experiments','EXPERIMENT_COLLECTIONS'),(8,'workflows','WORKFLOW_COLLECTIONS'),(10,'creation_presets','CREATION_COLLECTIONS'),(11,'book_creation','COLLECTIONS'),(12,'book_ai','COLLECTIONS'),(13,'styles','COLLECTIONS'),(14,'public_search','COLLECTIONS'),(15,'style_trials','COLLECTIONS'),(16,'chapter_writing','COLLECTIONS'),(17,'chapter_planning','COLLECTIONS'),(18,'scene_expansion','COLLECTIONS'),(19,'chapter_lifecycle','COLLECTIONS'),(20,'console','COLLECTIONS'),(21,None,('scoped_rules',)),(22,None,('scoped_rule_history',)),(23,'memory_rollups','COLLECTIONS'),(24,'console','RUN_COLLECTIONS'),(25,'materials','COLLECTIONS'),(26,'full_book_planning','COLLECTIONS'),(27,'chapter_trash','COLLECTIONS')]
            for version in range(1,36):
                with self.subTest(version=version):
                    names=set(base)
                    for minimum,module,collection in thresholds:
                        if version>=minimum:names.update(getattr(importlib.import_module('novel_writer.domain.'+module),collection) if module else collection)
                    state={k:deepcopy(full[k]) for k in names};state['workspace_version']=version
                    path=root/('v'+str(version)+'.sqlite3');repo=SQLiteRepository(path);saved=repo.create(state);before=path.read_bytes();parent=TaskCoordinator(NovelService(repo),AdapterRegistry())
                    try:
                        self.assertEqual(parent.service.get(saved['document']['project']['id']),saved);self.assertEqual(public_workspace(saved),saved);self.assertEqual(ComparisonCoordinator(parent.service,parent).service.get(saved['document']['project']['id']),saved)
                    finally:parent.close()
                    self.assertEqual(path.read_bytes(),before)

if __name__=='__main__':unittest.main()
