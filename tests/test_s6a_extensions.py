from importlib import util,import_module
from pathlib import Path
from uuid import uuid4
import sys,json,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository
from test_s5a_review import rows
from novel_writer.application.skill_import import SkillLibrary
from novel_writer.application.extension_policy import policy_for

SPEC=dict(template_format=1,interface_version=1,name='只读原稿参考',description='受控纯数据示例，不执行代码',capability='saved-text-reference',permissions=['read_saved_source'],parameters=dict(source='current_chapter',max_chars=1000))
class ExtensionTests(unittest.TestCase):
    def authorize(self, saved):
        policy=policy_for(self.service);record=next(v for v in self.service.get(self.pid)['extension_templates'] if v['id']==saved['version_id'])
        return policy.change(self.service,self.pid,dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision'],expected_policy_revision=policy.status(self.pid,record)['policy_revision'],version_id=record['id'],enabled=True,permissions=record['template']['permissions']))
    def setUp(self):
        self.assertIsNotNone(util.find_spec('novel_writer.application.extensions'),'缺少版本/权限/纯数据扩展契约')
        self.api=import_module('novel_writer.application.extensions');self.temp=tempfile.TemporaryDirectory(prefix='novel-s6a-extension-');self.addCleanup(self.temp.cleanup);self.db=Path(self.temp.name)/'fictional.sqlite3';self.service=NovelService(SQLiteRepository(self.db));SkillLibrary(self.db);s=self.service.create(title='虚构模板测试');self.pid=s['document']['project']['id'];s=self.service.execute(self.pid,'add_chapter',dict(title='原稿'),expected_revision=s['revision']);self.cid=s['document']['chapters'][0]['id'];self.service.execute(self.pid,'save_chapter',dict(chapter_id=self.cid,content='只读原稿，不应由模板写回。'),expected_revision=s['revision'])
    def test_template_preview_is_readonly_import_versioned_export_public_reference_adapter_readonly(self):
        before=rows(self.db);preview=self.api.preflight(SPEC);self.assertTrue(preview['compatible']);self.assertEqual(rows(self.db),before);request=dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision'],template=SPEC,template_id=None);saved=self.api.import_template(self.service,self.pid,request);version=self.api.export_template(self.service,self.pid,saved['version_id']);self.assertEqual(version,SPEC);self.assertNotIn(self.cid,json.dumps(version));self.assertNotIn(self.pid,json.dumps(version));self.authorize(saved);before=rows(self.db);out=self.api.reference_preview(self.service,self.pid,dict(version_id=saved['version_id'],chapter_id=self.cid));self.assertEqual(out['text'],'只读原稿，不应由模板写回。');self.assertTrue(out['read_only']);self.assertEqual(rows(self.db),before)
        revised=dict(SPEC,description='作者修改公开说明');second=self.api.import_template(self.service,self.pid,dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision'],template=revised,template_id=saved['template_id']));state=self.service.get(self.pid);self.assertEqual(second['revision'],2);self.assertEqual(len(state['extension_templates']),2);self.assertEqual(self.api.export_template(self.service,self.pid,saved['version_id']),SPEC)
    def test_unknown_interface_permissions_code_private_fields_rejected_without_execution(self):
        before=rows(self.db)
        for bad in (dict(SPEC,interface_version=2),dict(SPEC,permissions=['write_confirmed_body']),dict(SPEC,capability='arbitrary-code'),dict(SPEC,script='raise RuntimeError()'),dict(SPEC,chapter_body='private'),dict(SPEC,api_key='private'),dict(SPEC,session_id='private'),dict(SPEC,parameters=dict(source='current_chapter',max_chars=1000,endpoint='https://untrusted.example'))):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):self.api.preflight(bad)
        self.assertEqual(rows(self.db),before)

if __name__=='__main__':unittest.main()
