"""Fiction-only V43 proposals, exact saved citations, atomicity and copy isolation."""
from copy import deepcopy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from test_full_book_planning import FullBookPlanningTests
from novel_writer.application.body_planning import BodyPlanning, formal_fingerprint
from novel_writer.application.full_book_planning import FullBookPlanning
from novel_writer.application.service import NovelService
from novel_writer.application.backups import create_backup, restore_backup
from novel_writer.application.migrations import migrate
from novel_writer.application.skill_import import SkillLibrary
from novel_writer.storage.sqlite_repository import SQLiteRepository, ConflictError, validate_workspace


class BodyPlanningTests(unittest.TestCase):
    setUp = FullBookPlanningTests.setUp
    revision = FullBookPlanningTests.revision
    act = FullBookPlanningTests.act
    arc = FullBookPlanningTests.arc
    stage = FullBookPlanningTests.stage
    event = FullBookPlanningTests.event
    dependency = FullBookPlanningTests.dependency
    confirm = FullBookPlanningTests.confirm

    def engine(self): return BodyPlanning(self.service)

    def save(self, chapter=None, content='林默交出旧钥匙。星灯熄灭。', status='draft'):
        return self.service.execute(self.pid, 'save_chapter', dict(chapter_id=chapter or self.c1, title='虚构章节',
            content=content, status=status, authorize_confirmed=True), expected_revision=self.revision())

    def request(self, **values):
        return dict(operation_id=str(uuid4()), expected_revision=self.revision(), **values)

    def proposal(self, actions, chapter=None, quote='林默交出旧钥匙。', **kwargs):
        return self.engine().prepare(self.pid, self.request(chapter_id=chapter or self.c1, start=0, end=len(quote),
            quote=quote, actions=actions, reason='从已保存正文核对规划', **kwargs))

    def preview(self, proposal): return self.engine().preview(self.pid, dict(proposal_id=proposal['id']))

    def decision(self, proposal, decision='accepted', **values):
        return self.engine().decide(self.pid, self.request(proposal_id=proposal['id'], decision=decision, **values))

    def test_saved_body_proposal_preview_accept_is_atomic_and_idempotent(self):
        event = self.event(planned_chapter_id=self.c2)
        self.save(); before = deepcopy(self.service.get(self.pid))
        proposal = self.proposal([dict(action='occur_event', values=dict(event_id=event, occurrence_chapter_id=self.c1, body_reference='林默交出旧钥匙。'))])
        pending = self.service.get(self.pid)
        self.assertEqual(before['key_events'], pending['key_events'])
        self.assertEqual(before['document'], pending['document'])
        preview = self.preview(proposal)
        self.assertEqual(preview['deviation']['reason_delta']['early'], 1)
        self.assertFalse(preview['quality_verified'])
        self.assertEqual(pending, self.service.get(self.pid))
        request = self.request(proposal_id=proposal['id'], decision='accepted', preview_sha256=preview['preview_sha256'])
        receipt = self.engine().decide(self.pid, request)
        accepted = self.service.get(self.pid)
        self.assertEqual(accepted['key_events'][0]['status'], 'occurred')
        self.assertEqual(accepted['key_events'][0]['body_reference'], proposal['quote'])
        self.assertEqual(accepted['document'], pending['document'])
        self.assertEqual(accepted['revision'], pending['revision'] + 1)
        self.assertEqual(self.engine().decide(self.pid, request), receipt)
        self.assertEqual(accepted, self.service.get(self.pid))
        with self.assertRaises(ValueError): self.engine().decide(self.pid, dict(request, decision='rejected'))
        with self.assertRaises(ValueError): self.decision(proposal)

    def test_all_deviation_reason_impacts(self):
        self.save(status='confirmed'); self.save(self.c2); self.save(self.c3)
        late = self.event('晚到', planned_chapter_id=self.c1)
        early = self.event('提前', planned_chapter_id=self.c3)
        unplanned = self.event('未计划')
        missing = self.event('缺席', planned_chapter_id=self.c1)
        dependency = self.dependency(self.c2, self.c1)
        for event, chapter in ((late, self.c3), (early, self.c1), (unplanned, self.c2)):
            self.act('occur_event', event_id=event, occurrence_chapter_id=chapter, body_reference='作者原有位置记录')
        actions = [dict(action='update_event', values=dict(event_id=identifier, planned_chapter_id=chapter))
                   for identifier, chapter in ((late,self.c3),(early,self.c1),(unplanned,self.c2))]
        actions += [dict(action='drop_event', values=dict(event_id=missing)),
                    dict(action='set_dependency_enabled', values=dict(dependency_id=dependency, enabled=False))]
        proposal = self.proposal(actions)
        preview = self.preview(proposal)
        self.assertEqual(preview['deviation']['reason_delta'], dict(late=-1,early=-1,unplanned=-1,missing=-1,blocked=-1))
        self.assertIn(self.c2, preview['impact']['later_chapter_ids'])
        self.decision(proposal,preview_sha256=preview['preview_sha256'])
        self.assertEqual(self.planning.listing(self.pid)['deviation']['deviations_by_reason'],dict(late=0,early=0,unplanned=0,missing=0,blocked=0))

    def test_reject_keeps_formal_state_even_when_source_stale(self):
        event = self.event(); self.save()
        proposal = self.proposal([dict(action='update_event', values=dict(event_id=event,title='建议标题'))])
        self.save(content='新的已保存正文。')
        before = self.service.get(self.pid)
        receipt = self.decision(proposal, 'rejected')
        after = self.service.get(self.pid)
        self.assertEqual(receipt['decision'], 'rejected')
        self.assertEqual(formal_fingerprint(before), formal_fingerprint(after))
        self.assertEqual(before['full_book_planning_operations'], after['full_book_planning_operations'])

    def test_preview_revision_change_and_body_change_reject_without_partial_write(self):
        event = self.event(); self.save()
        p = self.proposal([dict(action='update_event',values=dict(event_id=event,title='建议'))])
        old = self.preview(p)
        self.proposal([dict(action='update_event',values=dict(event_id=event,title='另一建议'))])
        before = self.service.get(self.pid)
        with self.assertRaises(ConflictError): self.decision(p, preview_sha256=old['preview_sha256'])
        self.assertEqual(before, self.service.get(self.pid))
        self.save(content='正文已经更新。')
        with self.assertRaises(ConflictError): self.preview(p)

    def test_c07_locks_block_proposals_and_direct_mutations(self):
        arc = self.arc(); stage = self.stage(arc); self.save()
        self.engine().set_lock(self.pid, self.request(target_kind='arc',target_id=arc,locked=True,reason='锁定弧光'))
        before = self.service.get(self.pid)
        with self.assertRaises(ValueError): self.act('update_stage',stage_id=stage,title='绕过')
        with self.assertRaises(ValueError): self.act('create_stage',arc_id=arc,title='绕过')
        with self.assertRaises(ValueError): self.proposal([dict(action='update_stage',values=dict(stage_id=stage,title='绕过'))])
        self.assertEqual(before, self.service.get(self.pid))
        self.engine().set_lock(self.pid,self.request(target_kind='arc',target_id=arc,locked=False,reason='明确解锁'))
        self.act('update_stage',stage_id=stage,title='已解除')

    def test_exact_unicode_citation_and_occurrence_provenance(self):
        event = self.event(); self.save(content='😀林默交出旧钥匙。')
        before = self.service.get(self.pid)
        with self.assertRaises(ValueError): self.proposal([dict(action='update_event',values=dict(event_id=event,title='新'))])
        for values in (dict(event_id=event,occurrence_chapter_id=self.c2,body_reference='😀'),
                       dict(event_id=event,occurrence_chapter_id=self.c1,body_reference='描述而非引文')):
            with self.assertRaises(ValueError): self.proposal([dict(action='occur_event',values=values)],quote='😀')
        self.assertEqual(before, self.service.get(self.pid))
        p = self.proposal([dict(action='occur_event',values=dict(event_id=event,occurrence_chapter_id=self.c1,body_reference='😀'))],quote='😀',origin='ai_import')
        self.assertEqual(p['end'],1)
        self.assertEqual(p['source']['version_id'],before['document']['chapters'][0]['current_version_id'])

    def test_f1_reuses_existing_proposals_locks_versions_and_receipts(self):
        self.save()
        self.service.execute(self.pid,'save_book_outline',dict(theme='原主题',ending='原结局'),expected_revision=self.revision())
        target = self.service.get(self.pid)['document']['book_outline']['id']
        action = dict(action='prepare_plan',values=dict(target_kind='book_outline',target_id=target,field='ending',new_text='交出钥匙后的新结局',reason='正文反馈',source=dict(kind='chapter',entity_id=self.c1)))
        p = self.proposal([action]); v = self.preview(p)
        self.decision(p,preview_sha256=v['preview_sha256'])
        state = self.service.get(self.pid)
        self.assertEqual(state['document']['book_outline']['ending'],'交出钥匙后的新结局')
        self.assertEqual(len(state['planning_proposals']),1);self.assertEqual(len(state['planning_receipts']),1)
        SkillLibrary(self.db);package=self.root/'f1-v36.zip';create_backup(self.db,package)
        copy_path=self.root/'f1-copy.sqlite3';SQLiteRepository(copy_path);SkillLibrary(copy_path)
        result=migrate(package,copy_path,operation_id=str(uuid4()))
        copied=NovelService(SQLiteRepository(copy_path)).get(result['projects'][0]['new_id'])
        self.assertEqual(copied['body_planning_proposals'][0]['planning_proposal_ids'],[copied['planning_proposals'][0]['id']])
        self.assertEqual(copied['planning_receipts'][0]['proposal_id'],copied['planning_proposals'][0]['id'])
        from novel_writer.application.knowledge import command
        command(self.service,self.pid,'set_plan_lock',self.request(target_kind='book_outline',target_id=target,field='ending',locked=True,reason='固定结局'))
        action['values']['new_text']='绕过锁定'
        with self.assertRaises(ValueError): self.proposal([action])

    def test_character_reference_archive_restore_and_reopen(self):
        arc = self.arc(); event = self.event(character_id=self.character,arc_id=arc)
        before = self.service.get(self.pid)
        refs = self.engine().references(self.pid,dict(kind='character',entity_id=self.character))
        self.assertTrue(any(p.startswith('character_arcs/') for p in refs['references']))
        self.engine().lifecycle(self.pid,self.request(kind='character',entity_id=self.character,archived=True,confirm=True))
        with self.assertRaises(ValueError): self.arc('不应新增')
        self.service = NovelService(SQLiteRepository(self.db)); self.planning = FullBookPlanning(self.service)
        self.assertTrue(self.planning.listing(self.pid)['characters'][0]['archived'])
        self.assertEqual(before['document'],self.service.get(self.pid)['document'])
        self.assertEqual(before['key_events'],self.service.get(self.pid)['key_events'])
        self.engine().lifecycle(self.pid,self.request(kind='character',entity_id=self.character,archived=False,confirm=True))
        self.arc('恢复后新增')

    def test_completion_is_readonly_and_does_not_invent_quality_or_send(self):
        self.save(); before = self.service.get(self.pid)
        context = self.engine().completion(self.pid,dict(chapter_id=self.c1,start=0,end=len('林默交出旧钥匙。'),quote='林默交出旧钥匙。'))
        self.assertFalse(context['model_request_sent']); self.assertFalse(context['quality_verified'])
        self.assertEqual(before,self.service.get(self.pid))

    def test_v36_disk_reopen_backup_and_copy_new_collections(self):
        event = self.event();self.save()
        p = self.proposal([dict(action='update_event',values=dict(event_id=event,title='新标题'))])
        v = self.preview(p); self.decision(p,preview_sha256=v['preview_sha256'])
        self.engine().set_lock(self.pid,self.request(target_kind='event',target_id=event,locked=True,reason='固定事件'))
        self.engine().lifecycle(self.pid,self.request(kind='character',entity_id=self.character,archived=True,confirm=True))
        state = self.service.get(self.pid)
        self.assertEqual(NovelService(SQLiteRepository(self.db)).get(self.pid),state)
        SkillLibrary(self.db)
        package = self.root/'v36.zip'; create_backup(self.db,package)
        restored = restore_backup(package,self.root/'restored')
        restored_service = NovelService(SQLiteRepository(restored['database_path']))
        self.assertEqual(state,restored_service.get(self.pid))
        target_path = self.root/'copy.sqlite3'
        SQLiteRepository(target_path); SkillLibrary(target_path)
        result = migrate(package,target_path,operation_id=str(uuid4()))
        target = NovelService(SQLiteRepository(target_path))
        copied = target.get(result['projects'][0]['new_id'])
        self.assertEqual(copied['workspace_version'],43)
        for collection in ('body_planning_proposals','body_planning_receipts','body_planning_locks','planning_entity_lifecycle'):
            self.assertEqual(len(state[collection]),len(copied[collection]))
            self.assertNotEqual(state[collection][0]['operation_id'],copied[collection][0]['operation_id'])
        self.assertEqual(copied['body_planning_proposals'][0]['actions'][0]['values']['event_id'],copied['key_events'][0]['id'])
        self.assertEqual(copied['body_planning_receipts'][0]['proposal_id'],copied['body_planning_proposals'][0]['id'])
        self.assertEqual(copied['body_planning_locks'][0]['target_id'],copied['key_events'][0]['id'])
        self.assertEqual(copied['planning_entity_lifecycle'][0]['entity_id'],copied['document']['characters'][0]['id'])

    def test_literal_inference_is_pending_and_replay_is_readonly(self):
        event=self.event('旧钥匙',planned_chapter_id=self.c2);arc=self.arc();stage=self.stage(arc,title='旧钥匙',planned=self.c2);self.save()
        request=self.request(chapter_id=self.c1,start=0,end=len('林默交出旧钥匙。'),quote='林默交出旧钥匙。')
        proposal=self.engine().infer(self.pid,request)
        before=self.service.get(self.pid)
        self.assertEqual(before['key_events'][0]['status'],'planned')
        self.assertEqual(self.engine().infer(self.pid,request),proposal)
        self.assertEqual(before,self.service.get(self.pid))
        self.assertEqual(proposal['origin'],'body_excerpt')
        self.assertEqual(len(proposal['actions']),2)
        preview=self.preview(proposal);self.decision(proposal,preview_sha256=preview['preview_sha256'])
        state=self.service.get(self.pid)
        self.assertEqual(state['character_arc_stages'][0]['body_reference'],proposal['quote'])
        self.assertEqual(state['character_arc_stages'][0]['status'],'occurred')
        self.assertEqual(self.engine().infer(self.pid,request),proposal)

    def test_structured_setting_archive_keeps_edges_and_restores_selection(self):
        self.save()
        from novel_writer.application.knowledge import command, view
        node=command(self.service,self.pid,'save_node',self.request(kind='setting',label='星灯供能规则',aliases=[],memory_ids=[],position_chapter_id=self.c1,source=dict(kind='chapter',entity_id=self.c1),confirmed=True))
        other=command(self.service,self.pid,'save_node',self.request(kind='prop',label='星灯',aliases=[],memory_ids=[],position_chapter_id=self.c1,source=dict(kind='chapter',entity_id=self.c1),confirmed=True))
        command(self.service,self.pid,'save_edge',self.request(from_id=node['id'],to_id=other['id'],relation='限制',position_chapter_id=self.c1,source=dict(kind='chapter',entity_id=self.c1),confirmed=True))
        before=self.service.get(self.pid)
        self.engine().lifecycle(self.pid,self.request(kind='knowledge_node',entity_id=node['id'],archived=True,confirm=True))
        self.assertEqual([v['id'] for v in view(self.service,self.pid,{})['nodes']],[other['id']])
        self.assertEqual(view(self.service,self.pid,{})['edges'],[])
        self.assertEqual(len(view(self.service,self.pid,dict(include_inactive=True))['nodes']),2)
        with self.assertRaises(ValueError):command(self.service,self.pid,'save_node',self.request(node_id=node['id'],kind='setting',label='越过归档',aliases=[],memory_ids=[],position_chapter_id=self.c1,source=dict(kind='chapter',entity_id=self.c1),confirmed=True))
        self.assertEqual(before['knowledge_nodes'],self.service.get(self.pid)['knowledge_nodes'])
        self.assertEqual(before['knowledge_edges'],self.service.get(self.pid)['knowledge_edges'])
        self.engine().lifecycle(self.pid,self.request(kind='knowledge_node',entity_id=node['id'],archived=False,confirm=True))
        self.assertIn(node['id'],[v['id'] for v in view(self.service,self.pid,{})['nodes']])
        self.assertEqual(len(view(self.service,self.pid,{})['edges']),1)

    def test_v35_readonly_zero_write_and_backup_roundtrip(self):
        self.save()
        from novel_writer.application.chapter_lifecycle import upgrade
        state=self.service.get(self.pid);upgrade(state);state['workspace_version']=35
        self.service.repository.save(state,expected_revision=state['revision'])
        SkillLibrary(self.db)
        before=self.service.get(self.pid);sha=hashlib.sha256(self.db.read_bytes()).hexdigest()
        self.planning.listing(self.pid);self.engine().listing(self.pid)
        self.engine().completion(self.pid,dict(chapter_id=self.c1,start=0,end=len('林默交出旧钥匙。'),quote='林默交出旧钥匙。'))
        self.assertEqual(self.service.get(self.pid),before)
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(),sha)
        package=self.root/'v35.zip';manifest=create_backup(self.db,package)
        self.assertEqual(manifest['backup_format_version'],51)
        restored=restore_backup(package,self.root/'v35-restored')
        self.assertEqual(NovelService(SQLiteRepository(restored['database_path'])).get(self.pid),before)

    def test_f1_owned_proposal_cannot_bypass_and_rejection_resolves_inner(self):
        self.save();self.service.execute(self.pid,'save_book_outline',dict(ending='原结局'),expected_revision=self.revision())
        outline=self.service.get(self.pid)['document']['book_outline']['id']
        p=self.proposal([dict(action='prepare_plan',values=dict(target_kind='book_outline',target_id=outline,field='ending',new_text='新结局',reason='正文',source=dict(kind='chapter',entity_id=self.c1)))])
        inner=self.service.get(self.pid)['planning_proposals'][0]
        from novel_writer.application.knowledge import command
        with self.assertRaises(ValueError):command(self.service,self.pid,'decide_plan',self.request(proposal_id=inner['id'],decision='accepted'))
        self.decision(p,'rejected')
        state=self.service.get(self.pid)
        self.assertEqual(state['document']['book_outline']['ending'],'原结局')
        self.assertEqual(state['planning_receipts'][0]['decision'],'rejected')

    def test_lock_cannot_be_bypassed_by_direct_repository_save(self):
        event=self.event()
        self.engine().set_lock(self.pid,self.request(target_kind='event',target_id=event,locked=True,reason='固定'))
        before=self.service.get(self.pid);bad=deepcopy(before);bad['key_events'][0]['title']='越过业务层'
        with self.assertRaises(ValueError):self.service.repository.save(bad,expected_revision=before['revision'])
        self.assertEqual(before,self.service.get(self.pid))

    def test_reopen_and_restore_never_inherit_preview_permission(self):
        self.save();p=self.proposal([dict(action='create_event',values=dict(title='新事件'))])
        old=self.preview(p)
        self.service=NovelService(SQLiteRepository(self.db));self.planning=FullBookPlanning(self.service)
        before=self.service.get(self.pid)
        with self.assertRaises(ConflictError):self.decision(p,preview_sha256=old['preview_sha256'])
        self.assertEqual(before,self.service.get(self.pid))
        new=self.preview(p)
        self.assertNotEqual(old['preview_sha256'],new['preview_sha256'])
        self.decision(p,preview_sha256=new['preview_sha256'])

    def test_atomic_failure_rolls_back_event_and_receipt(self):
        from unittest.mock import patch
        import novel_writer.storage.sqlite_repository as repository
        self.save();p=self.proposal([dict(action='create_event',values=dict(title='必须整体回滚'))]);v=self.preview(p)
        before=self.service.get(self.pid);original=repository.validate_workspace
        def fail_after_decision(state,**kwargs):
            if state.get('body_planning_receipts'):raise ValueError('虚构提交校验故障')
            return original(state,**kwargs)
        with patch.object(repository,'validate_workspace',side_effect=fail_after_decision):
            with self.assertRaises(ValueError):self.decision(p,preview_sha256=v['preview_sha256'])
        self.assertEqual(before,self.service.get(self.pid))
        self.decision(p,preview_sha256=v['preview_sha256'])

    def test_archived_source_and_changed_plan_refuse_old_proposal(self):
        self.save();event=self.event('目标')
        p=self.proposal([dict(action='update_event',values=dict(event_id=event,title='新目标'))])
        self.act('update_event',event_id=event,title='人工后续编辑')
        with self.assertRaises(ConflictError):self.preview(p)
        q=self.proposal([dict(action='update_event',values=dict(event_id=event,title='再次建议'))])
        self.service.execute(self.pid,'archive_chapter',dict(chapter_id=self.c1,confirmed=True),expected_revision=self.revision())
        before=self.service.get(self.pid)
        with self.assertRaises(ConflictError):self.preview(q)
        self.assertEqual(before,self.service.get(self.pid))

    def test_creation_ending_lock_cannot_be_bypassed_by_f1_envelope(self):
        self.save();self.service.execute(self.pid,'save_book_outline',dict(ending='已锁定的结局'),expected_revision=self.revision())
        from novel_writer.application.book_creation import BookCreation
        creation=BookCreation(self.service);version=creation.start(self.pid,self.request(name='虚构手动方案'))
        creation.set_lock(self.pid,self.request(version_id=version['version_id'],field='ending',locked=True,current_lock_id=None,confirmed=True))
        outline=self.service.get(self.pid)['document']['book_outline']['id'];before=self.service.get(self.pid)
        with self.assertRaises(ValueError):self.proposal([dict(action='prepare_plan',values=dict(target_kind='book_outline',target_id=outline,field='ending',new_text='绕过结局锁',reason='正文建议',source=dict(kind='chapter',entity_id=self.c1)))])
        self.assertEqual(before,self.service.get(self.pid))

    def test_v36_manual_occurrence_also_requires_saved_quote(self):
        self.save();event=self.event();arc=self.arc();stage=self.stage(arc)
        self.engine().set_lock(self.pid,self.request(target_kind='event',target_id=event,locked=False,reason='启用新规划守卫'))
        before=self.service.get(self.pid)
        for action,key,identifier in (('occur_event','event_id',event),('occur_stage','stage_id',stage)):
            with self.assertRaises(ValueError):self.act(action,**{key:identifier,'occurrence_chapter_id':self.c1,'body_reference':'并不存在的作者引文'})
        self.assertEqual(before,self.service.get(self.pid))
        self.act('occur_event',event_id=event,occurrence_chapter_id=self.c1,body_reference='林默交出旧钥匙。')
        self.act('occur_stage',stage_id=stage,occurrence_chapter_id=self.c1,body_reference='林默交出旧钥匙。')
        self.assertEqual(self.service.get(self.pid)['character_arc_stages'][0]['status'],'occurred')


if __name__ == '__main__': unittest.main()
