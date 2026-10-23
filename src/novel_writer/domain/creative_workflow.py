"""Saved outline provenance for creative workflow task inputs."""
import json
from novel_writer.domain.tasks import require, digest


def outline_payload(outline):
    # Narrative names stay text. Do not put library IDs in outbound JSON text.
    return dict(core_idea=outline['core_idea'], objective=outline['objective'],
                story_time=outline['story_time'], character_ids=[],
                scenes=[dict(order=s['order'], summary=s['summary'], character_ids=[],
                             location=s['location'], story_time=s['story_time']) for s in outline['scenes']])


def require_outline_source(state, snapshot, *, fresh=True):
    require(snapshot.kind=='chapter_outline' and snapshot.saved_target.text=='', '保存章纲初稿仅允许空正文目标')
    events=[e for e in state['workflow_node_events'] if e['attempt_id']==snapshot.via_node_attempt_id and e['status']=='succeeded']
    require(bool(events),'保存章纲来源节点未完成')
    refs=[r for r in events[-1]['output_refs'] if r['kind']=='chapter_outline']
    require(len(refs)==1,'初稿须消费真实保存章纲引用')
    r=refs[0]
    require((r['entity_id'],r['version_id'])==(snapshot.entity_id,snapshot.version_id),'章纲实体/版本引用不符')
    version=next((v for v in state['document']['versions'] if v['id']==r['version_id'] and v['entity_type']=='chapter_outline' and v['entity_id']==r['entity_id']),None)
    require(version is not None,'保存章纲历史版本缺失')
    require(version['snapshot']['chapter_id']==snapshot.chapter_id,'保存章纲目标章节不符')
    text=json.dumps(outline_payload(version['snapshot']),ensure_ascii=False,sort_keys=True)
    require(text==snapshot.text and digest(text)==snapshot.text_sha256==r['content_sha256'],'保存章纲原文/摘要不符')
    if fresh:
        outline=next((o for o in state['document']['chapter_outlines'] if o['id']==r['entity_id']),None)
        latest=next((v for v in reversed(state['document']['versions']) if v['entity_type']=='chapter_outline' and v['entity_id']==r['entity_id']),None)
        require(outline is not None and latest is not None and latest['id']==r['version_id'],'保存章纲已变化，请明确重新读取')
    value=json.loads(text)
    require(bool(value['core_idea'].strip()) and bool(value['scenes']),'初稿需要非空核心情节和保存场景')
    return value
