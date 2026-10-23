"""2本/各2卷20章的独立虚构计划，所有字段在现有V1结构中。"""
from dataclasses import asdict
from novel_writer.domain.models import (NovelDocument,NovelProject,Chapter,Character,
    BookOutline,VolumePlan,ChapterOutline,ScenePlan,CharacterRelationship)
from s2_a_samples import create_fixture_database

TIME='2020-01-01T00:00:00+00:00'
def build_planning_dataset():
    data={'fixture_version':1,'projects':[],'project_snapshots':[],'skills':[]}
    for p in ('p1','p2'):
        def identity(i): return dict(id=i,created_at=TIME,updated_at=TIME)
        project=NovelProject(**identity(p),title='虚构小说'+p,summary='PRIVATE_METADATA_'+p)
        chapters=[Chapter(**identity(f'{p}-c{n}'),project_id=p,number=n,title=f'章节{n}',
            content=f'BODY_{p}_{n} '+('FUTURE_CHAPTER_20' if n==20 else '已保存正文。'*30)) for n in range(1,21)]
        chars=[Character(**identity(f'{p}-char{n}'),project_id=p,name=f'人物{n}',
            background='FUTURE_CHARACTER',goals=['保存旧目标'],notes='旧备注') for n in range(1,4)]
        chars[0].relationships=[CharacterRelationship(target_character_id=chars[1].id,relation='同伴',description='旧关系')]
        book=BookOutline(**identity(p+'-outline'),project_id=p,theme='旧主题',main_plot='FUTURE_PLOT',
            ending='FUTURE_ENDING',key_events=['旧关键事件'],status='ready',
            volumes=[VolumePlan(number=v,title=f'卷{v}',summary='未来卷计划',
                chapter_ids=[c.id for c in chapters[(v-1)*10:v*10]]) for v in (1,2)])
        detail=ChapterOutline(**identity(p+'-detail'),project_id=p,chapter_id=p+'-c5',objective='本章计划目标',
            character_ids=[chars[0].id],scenes=[ScenePlan(order=1,summary='本章场景一',character_ids=[chars[0].id],location='港口',story_time='第一天'),
            ScenePlan(order=2,summary='\n本章后续场景\r\n保留空格  ',character_ids=[chars[1].id],location='塔',story_time='第二天')])
        state=dict(workspace_version=1,revision=1,document=asdict(NovelDocument(project=project,chapters=chapters,
            characters=chars,book_outline=book,chapter_outlines=[detail])),ideas={p+'-c5':'本章IDEA'},
            worldbuilding='FUTURE_WORLD',writing_rules='私人规则')
        data['projects'].append(dict(id=p,title=project.title,revision=1,payload=state,updated_at=TIME))
        data['project_snapshots'].append(dict(project_id=p,revision=1,payload=state,saved_at=TIME))
    return data

def create_planning_database(path): create_fixture_database(path,build_planning_dataset())
