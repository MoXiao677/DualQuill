"""Synthetic empty V1--V35 disk fixtures: reads must preserve exact bytes."""
import importlib,tempfile,unittest
from pathlib import Path
from copy import deepcopy
from novel_writer.application.service import NovelService
from novel_writer.application.skill_import import SkillLibrary
from novel_writer.storage.sqlite_repository import SQLiteRepository

class LegacyArenaReadTests(unittest.TestCase):
    def test_all_35_workspace_versions_open_without_upgrade_or_any_disk_write(self):
        groups=[(2,None,['memories','memory_history']),(3,'tasks','COLLECTIONS'),(4,'review','REVIEW_COLLECTIONS'),(5,'knowledge','KNOWLEDGE_COLLECTIONS'),(6,'model_contract','MODEL_COLLECTIONS'),(7,'experiments','EXPERIMENT_COLLECTIONS'),(8,'workflows','WORKFLOW_COLLECTIONS'),(10,'creation_presets','CREATION_COLLECTIONS'),(11,'book_creation','COLLECTIONS'),(12,'book_ai','COLLECTIONS'),(13,'styles','COLLECTIONS'),(14,'public_search','COLLECTIONS'),(15,'style_trials','COLLECTIONS'),(16,'chapter_writing','COLLECTIONS'),(17,'chapter_planning','COLLECTIONS'),(18,'scene_expansion','COLLECTIONS'),(19,'chapter_lifecycle','COLLECTIONS'),(20,'console','COLLECTIONS'),(21,None,['scoped_rules']),(22,None,['scoped_rule_history']),(23,'memory_rollups','COLLECTIONS'),(24,'console','RUN_COLLECTIONS'),(25,'materials','COLLECTIONS'),(26,'full_book_planning','COLLECTIONS'),(27,'chapter_trash','COLLECTIONS')]
        with tempfile.TemporaryDirectory(prefix='c12-legacy-') as directory:
            for version in range(1,36):
                with self.subTest(version=version):
                    path=Path(directory)/f'v{version}.sqlite3';service=NovelService(SQLiteRepository(path));state=service.create(title=f'虚构旧格式{version}');pid=state['document']['project']['id'];SkillLibrary(path);expected=deepcopy(state);expected['workspace_version']=version
                    for threshold,module,collection in groups:
                        if version>=threshold:
                            names=getattr(importlib.import_module('novel_writer.domain.'+module),collection) if module else collection
                            for name in names:expected[name]=[]
                    saved=service.repository.save(expected,expected_revision=state['revision'])
                    before=path.read_bytes();opened=NovelService(SQLiteRepository(path)).get(pid);self.assertEqual(opened,saved);self.assertEqual(path.read_bytes(),before)

if __name__=='__main__':unittest.main()
