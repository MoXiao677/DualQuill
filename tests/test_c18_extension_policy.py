"""Fictional data only; local grants never enter project history or backup packages."""
from contextlib import closing
import hashlib
import http.client
import json
from pathlib import Path
import shutil
import sqlite3
import threading
from uuid import uuid4

from test_s6a_extensions import SPEC
import test_s6a_extensions as base
from novel_writer.application import extensions
from novel_writer.application.backups import create_backup, preflight_backup, restore_backup
from novel_writer.application.extension_policy import ExtensionPolicy, dependencies, policy_for
from novel_writer.application.service import NovelService
from novel_writer.storage.sqlite_repository import SQLiteRepository


class C18ExtensionTests(base.ExtensionTests):
    def save(self, spec=None, template_id=None):
        return extensions.import_template(self.service, self.pid, dict(
            operation_id=str(uuid4()), expected_revision=self.service.get(self.pid)['revision'],
            template=spec or SPEC, template_id=template_id))

    def record(self, saved):
        return next(v for v in self.service.get(self.pid)['extension_templates']
                    if v['id'] == saved['version_id'])

    def change(self, saved, enabled=True, **overrides):
        record=self.record(saved); policy=policy_for(self.service)
        request=dict(operation_id=str(uuid4()), expected_revision=self.service.get(self.pid)['revision'],
                     expected_policy_revision=policy.status(self.pid, record)['policy_revision'],
                     version_id=record['id'], enabled=enabled,
                     permissions=record['template']['permissions'] if enabled else [])
        request.update(overrides)
        return policy.change(self.service, self.pid, request)

    def preview(self, saved):
        return extensions.reference_preview(self.service, self.pid,
            dict(version_id=saved['version_id'], chapter_id=self.cid))

    def test_default_deny_disable_reopen_and_explicit_restore_are_readonly(self):
        saved=self.save(); before=self.db.read_bytes()
        with self.assertRaises(ValueError):self.preview(saved)
        self.assertFalse(policy_for(self.service).path.exists())
        self.change(saved); self.assertTrue(self.preview(saved)['read_only'])
        self.change(saved, False)
        self.service=NovelService(SQLiteRepository(self.db))
        with self.assertRaises(ValueError):self.preview(saved)
        self.change(saved); self.assertEqual(self.preview(saved)['text'], '只读原稿，不应由模板写回。')
        self.assertEqual(self.db.read_bytes(), before)
        with closing(sqlite3.connect(policy_for(self.service).path)) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM events').fetchone()[0],3)
            with self.assertRaises(sqlite3.IntegrityError):connection.execute('DELETE FROM events')

    def test_upgrade_requires_new_permission_failed_upgrade_keeps_active_version(self):
        saved=self.save(); self.change(saved); before=self.db.read_bytes()
        with self.assertRaises(ValueError):self.save(dict(SPEC, interface_version=99), saved['template_id'])
        self.assertEqual(self.db.read_bytes(),before);self.preview(saved)
        newer=self.save(dict(SPEC, description='虚构升级'), saved['template_id'])
        with self.assertRaises(ValueError):self.preview(saved)
        with self.assertRaises(ValueError):self.preview(newer)
        with self.assertRaises(ValueError):self.change(saved)
        self.change(newer);self.preview(newer)
        self.assertEqual(extensions.export_template(self.service,self.pid,saved['version_id']),SPEC)

    def test_permission_revision_operation_and_cross_project_rejections(self):
        saved=self.save();policy=policy_for(self.service)
        for fields in (dict(permissions=[]),dict(permissions=['write_confirmed_body']),
                       dict(enabled='true'),dict(expected_revision=0),dict(expected_policy_revision=999)):
            with self.subTest(fields=fields),self.assertRaises(ValueError):self.change(saved,**fields)
        self.assertFalse(policy.path.exists())
        operation=str(uuid4());self.change(saved,operation_id=operation)
        request=dict(operation_id=operation,expected_revision=self.service.get(self.pid)['revision'],
            expected_policy_revision=0,version_id=saved['version_id'],enabled=True,permissions=SPEC['permissions'])
        self.assertTrue(policy.change(self.service,self.pid,request)['enabled'])
        with self.assertRaises(ValueError):policy.change(self.service,self.pid,dict(request,enabled=False,permissions=[]))
        other=self.service.create(title='虚构另一书')['document']['project']['id']
        with self.assertRaises(ValueError):policy.change(self.service,other,dict(request,operation_id=str(uuid4())))

    def test_data_only_paths_urls_and_executable_fields_are_rejected(self):
        before=self.db.read_bytes()
        for key in ('script','command','entrypoint','download','module','path','api_key'):
            with self.subTest(key=key),self.assertRaises(ValueError):extensions.preflight(dict(SPEC,**{key:'../../payload.py'}))
        for source in ('../outside.txt','C:\\private.txt','https://fiction.invalid/plugin.py','file:///private'):
            with self.subTest(source=source),self.assertRaises(ValueError):extensions.preflight(dict(SPEC,parameters=dict(source=source,max_chars=100)))
        self.assertEqual(self.db.read_bytes(),before)

    def test_model_defaults_never_execute_even_after_authorization(self):
        spec=dict(SPEC,capability='model-request-preset',permissions=['prepare_model_request'],
            parameters=dict(role='writer',temperature=.3,max_tokens=256,max_output_chars=1000,
                            timeout_ms=1000,prompt_version='rewrite-1'))
        saved=self.save(spec);self.change(saved)
        with self.assertRaisesRegex(ValueError,'不执行生成'):self.preview(saved)

    def test_backup_restore_preserves_data_reports_dependency_and_drops_grants(self):
        saved=self.save();self.change(saved);before=self.db.read_bytes()
        archive=self.db.parent/'fiction.nwbak';create_backup(self.db,archive)
        preflight=preflight_backup(archive)
        self.assertFalse(preflight['extension_authorizations_restored'])
        self.assertEqual(preflight['extension_dependencies'][0]['reason'],'requires_local_authorization')
        restored=restore_backup(archive,self.db.parent/'recovered')
        self.assertFalse(restored['extension_authorizations_restored'])
        self.assertTrue(restored['extension_dependencies'][0]['data_preserved'])
        original=self.service
        self.service=NovelService(SQLiteRepository(restored['database_path']))
        self.assertEqual(self.service.get(self.pid),original.get(self.pid))
        with self.assertRaises(ValueError):self.preview(saved)
        self.assertFalse(policy_for(self.service).path.exists())
        self.assertEqual(self.db.read_bytes(),before)
        self.change(saved);self.preview(saved)

    def test_copied_policy_cannot_grant_authority_at_another_database_path(self):
        saved=self.save();self.change(saved);copy=self.db.parent/'copy.sqlite3'
        shutil.copyfile(self.db,copy)
        shutil.copyfile(policy_for(self.service).path,ExtensionPolicy(copy).path)
        self.service=NovelService(SQLiteRepository(copy))
        with self.assertRaises(ValueError):self.preview(saved)

    def test_migration_copy_retains_extension_data_and_requires_new_local_permission(self):
        from novel_writer.application.migrations import migrate
        from novel_writer.application.skill_import import SkillLibrary
        saved=self.save();self.change(saved);archive=self.db.parent/'copy-source.nwbak'
        create_backup(self.db,archive)
        target=self.db.parent/'copy-target.sqlite3';SQLiteRepository(target);SkillLibrary(target)
        copied=migrate(archive,target,operation_id=str(uuid4()))
        new_id=copied['projects'][0]['new_id'];clone=NovelService(SQLiteRepository(target)).get(new_id)
        self.assertEqual(clone['extension_templates'][0]['template'],SPEC)
        self.assertNotEqual(clone['extension_templates'][0]['id'],saved['version_id'])
        self.assertEqual(dependencies(clone)[0]['reason'],'requires_local_authorization')
        self.assertFalse(ExtensionPolicy(target).path.exists())

    def test_http_authorization_token_guard_and_dependency_listing(self):
        from novel_writer.ui.server import create_server
        saved=self.save(); server=create_server(self.db,port=0,offline=True,
            provider_path=self.db.parent/'fictional-providers.dpapi')
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True)
        thread.start()
        def request(method,suffix,payload=None,token=True):
            connection=http.client.HTTPConnection('127.0.0.1',server.server_address[1],timeout=10)
            headers={'Content-Type':'application/json'}
            if token:headers['X-Novel-Token']=server.token
            try:
                connection.request(method,f'/api/projects/{self.pid}/extensions'+suffix,
                    body=None if payload is None else json.dumps(payload),headers=headers)
                response=connection.getresponse();return response.status,json.loads(response.read())
            finally:connection.close()
        try:
            payload=dict(operation_id=str(uuid4()),expected_revision=self.service.get(self.pid)['revision'],
                expected_policy_revision=0,version_id=saved['version_id'],enabled=True,permissions=SPEC['permissions'])
            self.assertEqual(request('POST','/authorization',payload,False)[0],403)
            self.assertEqual(request('POST','/authorization',dict(payload,permissions=['network']))[0],422)
            self.assertEqual(request('POST','/authorization',payload)[0],200)
            status,listing=request('GET','');self.assertEqual(status,200)
            self.assertTrue(listing['dependencies'][0]['enabled'])
            self.assertTrue(listing['authorizations'][0]['enabled'])
            self.assertEqual(request('POST','/reference-preview',dict(version_id=saved['version_id'],chapter_id=self.cid))[0],200)
            archive=self.db.parent/'http-restore.nwbak';create_backup(self.db,archive)
            connection=http.client.HTTPConnection('127.0.0.1',server.server_address[1],timeout=20)
            identity=str(uuid4())
            try:
                connection.request('POST','/api/backups/restore',body=archive.read_bytes(),
                    headers={'X-Novel-Token':server.token,'X-Novel-Backup-Operation':identity,
                             'Content-Type':'application/octet-stream'})
                response=connection.getresponse();body=json.loads(response.read())
                self.assertEqual(response.status,201,body)
                self.assertFalse(body['extension_authorizations_restored'])
                self.assertEqual(len(body['extension_dependencies']),1)
            finally:connection.close()
            connection=http.client.HTTPConnection('127.0.0.1',server.server_address[1],timeout=20)
            try:
                connection.request('GET','/api/backups/operations/'+identity,headers={'X-Novel-Token':server.token})
                response=connection.getresponse();body=json.loads(response.read())
                self.assertEqual(response.status,200,body)
                self.assertEqual(body['extension_dependencies'][0]['reason'],'requires_local_authorization')
            finally:connection.close()
        finally:
            server.shutdown();thread.join(3);server.server_close()
        self.assertFalse((self.db.parent/'fictional-providers.dpapi').exists())
