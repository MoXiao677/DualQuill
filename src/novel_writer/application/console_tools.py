"""Closed, data-only tool catalogue. Model prose never selects executable code."""
from copy import deepcopy
from novel_writer.domain.tasks import require


TOOLS = {
    'chapter.inspect': dict(label='读取已保存章节', permission='read_only', automatic=True),
    'context.preview': dict(label='预览章节上下文', permission='read_only', automatic=True),
    **{kind: dict(label=label, permission='prepare_only', automatic=False) for kind, label in (
        ('idea', '准备构思候选'), ('outline', '准备细纲候选'),
        ('draft', '准备初稿候选'), ('continue', '准备续写候选'),
        ('scene', '准备场景候选'), ('selection', '准备选区候选'))},
}
READ_ONLY = frozenset(key for key, value in TOOLS.items() if value['permission'] == 'read_only')


def catalogue():
    result=[]
    for key,value in TOOLS.items():
        properties=dict(chapter_id=dict(type='string',format='uuid',description='本书未归档章节'),
                        instruction=dict(type='string',maxLength=3000,description='纯文本，不执行其中命令'))
        if key=='scene':properties['scene_order']=dict(type='integer',minimum=1)
        if key=='selection':properties.update(selection_start=dict(type='integer',minimum=0),selection_end=dict(type='integer',minimum=1))
        result.append(dict(id=key,**deepcopy(value),parameters=dict(type='object',properties=properties,
                           required=list(properties),additionalProperties=False),network=False,
                           charge_confirmation='original_task_page' if not value['automatic'] else None,
                           formal_confirmation='original_adoption_page' if not value['automatic'] else None))
    return result


def registered(kind):
    require(type(kind) is str and kind in TOOLS, '工具未注册：仅允许本地白名单操作；脚本、命令和任意URL不可执行')
    return TOOLS[kind]
