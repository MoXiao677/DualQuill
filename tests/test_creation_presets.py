from importlib import import_module,util
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository

class CreationPresetTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(util.find_spec('novel_writer.application.creation_presets'),'versioned per-step creation presets are missing')
        self.api=import_module('novel_writer.application.creation_presets');self.temp=tempfile.TemporaryDirectory(prefix='novel-creation-preset-');self.addCleanup(self.temp.cleanup)
        self.db=Path(self.temp.name)/'fiction.sqlite3';self.service=NovelService(SQLiteRepository(self.db));self.pid=self.service.create(title='虚构预设源书')['document']['project']['id'];self.other=self.service.create(title='虚构预设目标书')['document']['project']['id'];self.engine=self.api.CreationPresets(self.service)
    def settings(self):
        return dict(steps=[dict(step=step,adapter_id='configured-http-v2',connection_id=str(uuid4()),model_id='fiction-'+step,temperature=.3,max_tokens=512,budget_limit=1.0,allow_unknown_cost=False) for step in ('brainstorm','outline','draft','audit','rewrite','style_analysis','style_trial','search')],style_id=None,style_prompt='作者自己的简洁文风提示词',manuscript_language='en',budget=dict(max_external_calls=2,max_reserved_output_tokens=1024,risk_budget=1.0,allow_unknown_cost=False))
    def save(self,pid=None,**changes):
        pid=pid or self.pid;request=dict(operation_id=str(uuid4()),preset_id=None,name='整套虚构创作预设',settings=self.settings(),expected_revision=self.service.get(pid)['revision']);request.update(changes);return self.engine.save(pid,request)
    def test_steps_are_independent_versioned_and_applying_does_not_write_text_or_run_models(self):
        before=self.service.get(self.pid)['document'];first=self.save();state=self.service.get(self.pid);self.assertEqual(state['workspace_version'],10)
        second=self.save(preset_id=first['preset_id'],name='预设第二版');versions=self.engine.describe(self.pid)['versions'];self.assertEqual(len(versions),2);self.assertEqual(versions[-1]['previous_version_id'],first['version_id']);self.assertEqual(len({step['connection_id'] for step in versions[0]['settings']['steps']}),8)
        with self.assertRaises(ValueError):self.engine.choose(self.pid,dict(operation_id=str(uuid4()),version_id=first['version_id'],confirmed=False,expected_revision=self.service.get(self.pid)['revision']))
        self.engine.choose(self.pid,dict(operation_id=str(uuid4()),version_id=first['version_id'],confirmed=True,expected_revision=self.service.get(self.pid)['revision']))
        described=self.engine.describe(self.pid);self.assertEqual(described['selected_version_id'],first['version_id']);self.assertEqual(self.service.get(self.pid)['document'],before);self.assertEqual(self.service.get(self.pid)['generation_tasks'],[])
    def test_same_machine_reuse_keeps_model_preferences_while_public_share_requires_rebinding(self):
        first=self.save();source=self.engine.describe(self.pid)['versions'][0]
        reused=self.engine.reuse(self.other,dict(operation_id=str(uuid4()),source_project_id=self.pid,version_id=first['version_id'],expected_revision=self.service.get(self.other)['revision']))
        local=self.engine.describe(self.other)['versions'][0];self.assertEqual(local['settings'],source['settings']);self.assertNotEqual(reused['preset_id'],first['preset_id'])
        public=self.engine.export(self.pid,first['version_id']);text=json.dumps(public);self.assertNotIn(self.pid,text);self.assertNotIn(source['settings']['steps'][0]['connection_id'],text);self.assertNotIn('operation_id',text)
        imported=self.engine.import_preset(self.other,dict(operation_id=str(uuid4()),preset=public,expected_revision=self.service.get(self.other)['revision']))
        missing=self.engine.preflight(self.other,imported['version_id'],connections={});self.assertEqual(len(missing['missing_steps']),8);self.assertFalse(missing['ready'])
        with self.assertRaises(ValueError):self.engine.import_preset(self.other,dict(operation_id=str(uuid4()),preset=dict(public,api_key='fiction-forbidden'),expected_revision=self.service.get(self.other)['revision']))
    def test_complete_backup_restore_copy_preserves_preset_history_without_credentials(self):
        from novel_writer.application.backups import create_backup,restore_backup
        from novel_writer.application.migrations import migrate
        from novel_writer.application.skill_import import SkillLibrary
        first=self.save();self.save(preset_id=first['preset_id']);self.engine.choose(self.pid,dict(operation_id=str(uuid4()),version_id=first['version_id'],confirmed=True,expected_revision=self.service.get(self.pid)['revision']))
        SkillLibrary(self.db);root=Path(self.temp.name);package=root/'presets.nwbak';manifest=create_backup(self.db,package);self.assertEqual(manifest['backup_format_version'],51)
        restored=restore_backup(package,root/'restored');state=NovelService(SQLiteRepository(restored['database_path'])).get(self.pid);self.assertEqual(state['creation_presets'],self.service.get(self.pid)['creation_presets'])
        target=root/'copy.sqlite3';SQLiteRepository(target);SkillLibrary(target);result=migrate(package,target,operation_id=str(uuid4()),project_ids=[self.pid]);copied=NovelService(SQLiteRepository(target)).get(result['projects'][0]['new_id'])
        self.assertEqual(len(copied['creation_presets']),2);self.assertEqual(copied['creation_presets'][0]['settings'],state['creation_presets'][0]['settings']);self.assertNotEqual(copied['creation_presets'][0]['id'],state['creation_presets'][0]['id']);self.assertEqual(copied['creation_preset_choices'][0]['version_id'],copied['creation_presets'][0]['id'])

if __name__=='__main__':unittest.main()
