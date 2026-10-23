"""Fictional cold-start hot paths must retain exact parsing/source identities."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from novel_writer.application import projects
from novel_writer.domain.memory import capture_source, source_catalog
from novel_writer.storage import json_codec as codec
from novel_writer.storage.json_codec import document_from_dict, document_to_dict
from novel_writer.domain.models import Chapter, BookOutline, VolumePlan, VersionRecord, DataValidationError
from novel_writer.domain import models
from novel_writer.storage.sqlite_repository import WorkspaceHistoryValidator
from novel_writer.application.versions import record


class CountingVersions(list):
    def __init__(self, values):
        super().__init__(values)
        self.iterations = 0
    def __iter__(self):
        self.iterations += 1
        return super().__iter__()


class StartupHotpathTests(unittest.TestCase):
    def state(self):
        state=projects.create(dict(title='虚构启动来源回归'))
        doc=document_from_dict(state['document'])
        for index in range(20):
            chapter=Chapter(project_id=doc.project.id,number=index+1,title=f'虚构{index+1}',content='原文😀e\u0301\r\n  ')
            doc.chapters.append(chapter)
            for _ in range(3):record(doc,'chapter',chapter,'虚构不可变历史')
        doc.book_outline=BookOutline(project_id=doc.project.id,volumes=[VolumePlan(number=1,title='虚构卷',chapter_ids=[c.id for c in doc.chapters])])
        record(doc,'book_outline',doc.book_outline,'虚构关联')
        state['document']=document_to_dict(doc)
        return state

    def test_chapter_source_uses_explicit_current_version_without_scanning_history(self):
        state=self.state();versions=CountingVersions(state['document']['versions']);state['document']['versions']=versions
        for c in state['document']['chapters']:
            source=capture_source(state,dict(kind='chapter',entity_id=c['id']))
            self.assertEqual(source['version_id'],c['current_version_id'])
        self.assertEqual(versions.iterations,0,'Chapter source must use its explicit current_version_id; repeated full history scans are quadratic')

    def test_catalog_preserves_every_source_identity_and_current_version(self):
        state=self.state();before=deepcopy(state)
        catalog=source_catalog(state)
        for key,value in catalog.items():
            self.assertEqual(value,capture_source(state,dict(kind=key[0],entity_id=key[1])))
        outline=state['document']['book_outline']
        expected=[v for v in state['document']['versions'] if v['entity_type']=='book_outline'][-1]
        self.assertEqual(catalog[('book_outline',outline['id'])]['version_id'],expected['id'])
        self.assertEqual(state,before)
        with self.assertRaises(ValueError):capture_source(state,dict(kind='chapter',entity_id='absent'))

    def test_parser_keeps_exact_unicode_escaped_strings_and_node_budget(self):
        values=['"','\\','\\"','{}[],:"\\'*1000,'\ufeff原文\r\n😀e\u0301','\\u0022','\n']
        text=json.dumps(values,ensure_ascii=False)
        with patch.object(codec,'MAX_JSON_DEPTH',1),patch.object(codec,'MAX_JSON_NODES',len(values)+1):
            self.assertEqual(codec.strict_json_loads(text),values)
        with patch.object(codec,'MAX_JSON_NODES',len(values)):
            with self.assertRaises(DataValidationError):codec.strict_json_loads(text)
        for text in ['{"a":1,"a":2}','[NaN]','[Infinity]','[1e999]','"\\ud800"','"unterminated\\','["x",]']:
            with self.subTest(text=text),self.assertRaises(DataValidationError):codec.strict_json_loads(text)
        self.assertEqual(codec.strict_json_loads('"\\ud83d\\ude00"'),'😀')
        self.assertEqual(codec.strict_json_loads('[1.25,-2e3]'),[1.25,-2000.0])

    def test_depth_and_wide_array_budget_still_reject_before_decode(self):
        for text in ['['*65+'0'+']'*65,'['+'{},'*999999+'{}]']:
            with patch.object(codec.json,'loads') as parser:
                with self.assertRaises(DataValidationError):codec.strict_json_loads(text)
                parser.assert_not_called()

    def test_large_escaped_strings_keep_exact_nodes_and_depth(self):
        def count(value):
            if type(value) is dict:return 1+sum(1+count(v) for v in value.values())
            if type(value) is list:return 1+sum(map(count,value))
            return 1
        for width in [7,31,127,16384]:
            values={'原文':['前缀'+('"\\[]{}\r\n😀e\u0301'*80),'普通'*width,True,None,1.25,{'x':[]}]*2}
            text=json.dumps(values,ensure_ascii=False)
            with self.subTest(width=width),patch.object(codec,'MAX_JSON_NODES',count(values)):
                self.assertEqual(codec.strict_json_loads(text),values)
                with patch.object(codec,'MAX_JSON_NODES',count(values)-1):
                    with self.assertRaises(DataValidationError):codec.strict_json_loads(text)

    def test_fast_depth_ignores_brackets_inside_prose_and_unicode_escaped_quotes(self):
        value=['[[{{}}]]'*200,'普通正文\\路径',{'x':'"'}]
        self.assertEqual(codec.strict_json_loads(json.dumps(value,ensure_ascii=False)),value)
        self.assertEqual(codec.strict_json_loads('["\\u0022[]{}"]').pop(),'"[]{}')
        text='['*64+json.dumps(']]}}'*100)+']'*64
        self.assertEqual(codec.strict_json_loads(text),json.loads(text))
        with patch.object(codec.json,'loads') as parser:
            with self.assertRaises(DataValidationError):codec.strict_json_loads('['*65+json.dumps(']]'*100)+']'*65)
            parser.assert_not_called()

    def test_unchanged_historical_versions_are_typechecked_once_across_revisions(self):
        state=self.state();state['revision']=1;validator=WorkspaceHistoryValidator()
        original=models._check_type;seen=[]
        def count(value,expected,*args,**kwargs):
            if expected is VersionRecord:seen.append(value.id)
            return original(value,expected,*args,**kwargs)
        with patch.object(models,'_check_type',side_effect=count):
            validator.validate(state)
            first=len(seen)
            changed=deepcopy(state);changed['revision']=2;changed['document']['project']['summary']='仅修改当前资料，历史完整不变'
            validator.validate(changed)
        self.assertEqual(len(seen),first,'Exact previously validated immutable records must not repeat recursive type validation')

    def test_history_rejects_boolean_numeric_alias_and_reordered_or_missing_versions(self):
        state=self.state();state['revision']=1
        for mutation in ['boolean','float','reorder','missing','extra_field','body']:
            with self.subTest(mutation=mutation):
                validator=WorkspaceHistoryValidator();validator.validate(state)
                changed=deepcopy(state);changed['revision']=2;versions=changed['document']['versions']
                if mutation=='boolean':versions[0]['snapshot']['number']=True
                if mutation=='float':versions[0]['snapshot']['number']=1.0
                if mutation=='reorder':versions[0],versions[1]=versions[1],versions[0]
                if mutation=='missing':versions.pop(0)
                if mutation=='extra_field':versions[0]['snapshot']['unknown']='非法'
                if mutation=='body':versions[0]['snapshot']['content']='不得改写历史'
                with self.assertRaises(ValueError):validator.validate(changed)


if __name__=='__main__':unittest.main()
