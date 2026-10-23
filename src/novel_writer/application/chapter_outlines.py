"""章节细纲管理：与 IDEA 分开保存。"""

from novel_writer.application.fields import check_fields, find, update_text, structured_list, text_list
from novel_writer.application.versions import record
from novel_writer.domain.models import ChapterOutline, ScenePlan

MODULE = {"id": "chapter_outlines", "name": "章节细纲管理", "status": "ready", "description": "按章节编辑核心情节、目标与剧情时间说明。"}


def save(document, values):
    names = ("core_idea", "objective", "story_time")
    check_fields(values, {"chapter_id", *names,'scenes','character_ids'})
    chapter = find(document.chapters, values.get("chapter_id"), "章节")
    outline = next((item for item in document.chapter_outlines if item.chapter_id == chapter.id), None)
    if outline is None:
        outline = ChapterOutline(project_id=document.project.id, chapter_id=chapter.id)
        document.chapter_outlines.append(outline)
    update_text(outline, values, names)
    if 'scenes' in values:
        outline.scenes = structured_list(values['scenes'],ScenePlan,'场景')
    if 'character_ids' in values:
        outline.character_ids = text_list(values['character_ids'],'本章人物')
    record(document, "chapter_outline", outline, "手动保存章节细纲")
